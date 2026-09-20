"""
GitHub Actionsから呼ぶ収集ジョブ。

フルpipelineを毎時回すと1回あたり約30分かかり、月10,000分を超えて
GitHub Actionsの無料枠(private 2,000分/月)を使い切る。そのため
用途ごとにジョブを分け、直前情報とオッズは「締切が近いレースだけ」に絞る。

  morning      : その日の全レースの出走表を取得（1日1回）
  prerace      : 締切がN分以内のレースだけ直前情報とオッズを取得（1回だけ）
  prerace-loop : preraceを指定時刻まで繰り返す。本番のスケジュールはこちら。
  morning-odds : その日の第1レースが始まる前に、全レースのオッズを揃える。
  results      : 確定結果を取得（1日1回）。実行が深夜〜昼にずれ込んだ場合は
                 前日を対象にする。GitHubのスケジュールは数時間遅れうるため。

本番で prerace ではなく prerace-loop を使うのは、GitHubのcronが
発火しないため。実測では30分毎に設定しても1日1〜2回しか発火せず、
しかも1〜4時間ずれた。「毎時発火する」前提の設計は成立しない。
1回起動したらプロセス内でループし、発火回数に依存しない形にする。

使い方:
  py -3 jobs.py morning
  py -3 jobs.py prerace --window 40
  py -3 jobs.py prerace-loop --until 21:40 --interval 15 --window 30
  py -3 jobs.py morning-odds --interval 20
  py -3 jobs.py results [YYYYMMDD]
  py -3 jobs.py target-date results   # 対象日だけを出力する
"""
import io
import json
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path


from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from scraper.schedule import get_active_venues, get_close_times
from scraper.racelist import get_racelist
from scraper.beforeinfo import get_beforeinfo, merge_into_racers
from scraper.odds import get_odds, get_trio_odds
from scraper.result import get_result
from scraper.scoring import score_race, CALIBRATED

OUTPUT_DIR = Path("output")
RACE_COUNT = 12

# 締切までこの分数を切ったら、展示が揃っていても直前情報を取り直す。
# 風速・波高は開催中に変わり、モデルはその2つを使っている。巡回間隔と
# 同じ値にしてあるので、最後の1周だけが取り直す形になる。
BEFOREINFO_REFRESH_MIN = 15

# 締切までこれ以上の余裕があるレースでは直前情報を取りに行かない。
# 展示タイムも気象も締切の30分前あたりまで出ないので、朝の一括取得で
# 全レース分を叩くと、1レースあたり1リクエストがまるごと無駄になる。
# 180レースなら6分ぶんの空打ちで、その間ほかのレースが取れない。
# 通常の巡回は窓が30分なので、この値には掛からない。
BEFOREINFO_MAX_LEAD_MIN = 90

# 朝の一括取得が、第1レースの締切の何分前に終わっていてほしいか。
# 「第1レースが始まる前に、その日の買い目が画面に出ている」状態を作るための値。
MORNING_ODDS_MARGIN_MIN = 10

# 朝の一括取得で、先頭から何レース続けてオッズが取れなかったらその周を諦めるか。
#
# **発売前に180レースを叩き切ってはいけない。** 1周12分の空振りを発売開始まで
# 繰り返すと、何も返らないリクエストを何百回も公式サイトへ送ることになる。
# 対象は締切の早い順に並んでいるので、先頭が発売前なら後ろはもっと発売前である。
# 先頭数レースを当たりに使い、駄目ならその周を畳んで次の周まで待つ。
MORNING_ODDS_MISS_STREAK = 6

# 朝の一括取得で、何レースごとにDBへ取り込むか。
#
# **取れていても、DBに入るまでは画面に出ない。** 取り込みをパスの終わりに
# 1回だけ行うと、168レースを回る76分のあいだ、最初に取った締切の早いレースが
# 画面に出ないまま締切を迎える。2026-09-20、07:29に取った三国1R（締切08:32）が
# DBへ入ったのは08:45だった。取得は間に合っていたのに、公開は間に合っていない。
# 通常の巡回は1パスが短いのでこの問題が出ない。
MORNING_ODDS_SYNC_EVERY = 20


def _use_utf8_stdio():
    """
    Windowsのコンソールでも日本語が化けないようにする。

    **import時ではなく、スクリプトとして起動されたときだけ呼ぶこと。**
    以前はモジュールの先頭で無条件に実行していた。この形だと、複数の
    モジュールを同じプロセスに読み込んだときに TextIOWrapper が二重にかかり、
    どちらか一方が終了時に閉じられた瞬間、もう一方が
    「I/O operation on closed file」で落ちる。実際に、テストが backtest と
    jobs の両方を読み込んだ時点でスイートが終了コード1になった。
    """
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _path(date_str: str) -> Path:
    return OUTPUT_DIR / f"{date_str}.json"


def _tomorrow_date(now: datetime = None) -> str:
    """
    翌日ジョブが対象とすべき開催日。**起動が日付を跨いでも正しく動くこと。**

    このジョブは22:30起動の想定だが、GitHubのcronは1〜4時間ずれる。実際に
    2026-09-10 の22:30起動が翌02:06にずれ、単純に「今日＋1日」で計算したために
    翌々日を対象にした。その日の出走表はまだ公開されておらず、開催場0場で
    異常終了した（results が同じ理由で _target_result_date を持っているのに、
    こちらに同じ配慮を入れていなかった）。

    開催時間帯の前（9時より前）に動いているなら、それは前夜の実行が遅れたもの
    なので対象は「今日」。それ以外は「翌日」。
    """
    now = now or datetime.now()
    if now.hour < 9:
        return now.strftime("%Y%m%d")
    return (now + timedelta(days=1)).strftime("%Y%m%d")


def _load(date_str: str) -> dict:
    """既存の日次JSONを読む。ジョブは追記的に同じファイルを育てる。"""
    p = _path(date_str)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"date": date_str, "venues": []}


def _save(data: dict):
    OUTPUT_DIR.mkdir(exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    _path(data["date"]).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _race_slot(data: dict, venue: dict, race_no: int) -> dict:
    """会場・レースの入れ物を取り出す（無ければ作る）。"""
    v = next((x for x in data["venues"] if x["code"] == venue["code"]), None)
    if v is None:
        v = {"code": venue["code"], "name": venue["name"], "races": []}
        data["venues"].append(v)
    r = next((x for x in v["races"] if x["race_no"] == race_no), None)
    if r is None:
        r = {"race_no": race_no}
        v["races"].append(r)
        v["races"].sort(key=lambda x: x["race_no"])
    return r


_SCHEDULE_CACHE: dict = {}

# 開催場が0場になったときの説明。
#
# ボートレースに開催0の日は無い。だから0場は「今日は何も無い」ではなく
# 「get_active_venues が静かに空を返した」と読むべきで、事実上
# パーサーが壊れたことの同義語になる。get_active_venues は
# トップページの jcd= リンクを拾い、取れなければ月間スケジュールに
# フォールバックするが、どちらもリンク構造が変わると例外を出さずに
# 空を返す。検査を置かないと、全ジョブが「0レース取得完了」と印字して
# 正常終了し、失敗時にしか飛ばない通知も鳴らないまま、その日の収集が
# まるごと失われる。
NO_VENUE_HINT = (
    "開催場が0場。ボートレースに開催0の日は無いので、"
    "get_active_venues が静かに空を返している可能性が高い。"
    "トップページのリンク構造か月間スケジュールの体裁を確認すること"
)


def _close_schedule(date_str: str) -> list:
    """
    開催場と、その場の各レースの締切時刻。

    どちらも1日を通して変わらないので、プロセス内で使い回す。
    prerace-loop で毎回取り直すと、場一覧1回＋14場ぶんの往復が
    1パスごとにそのまま無駄になる（ランナーからは1リクエスト約12秒）。
    """
    if date_str not in _SCHEDULE_CACHE:
        schedule = [
            (v, get_close_times(date_str, v["code"])) for v in get_active_venues(date_str)
        ]
        if not schedule:
            # 空はキャッシュしない。一度の失敗を覚えると、その日の残りの
            # パスが全部それを使い回して空のまま回り続け、サイト側が
            # 直っても復帰できなくなる。
            return []
        _SCHEDULE_CACHE[date_str] = schedule
    return _SCHEDULE_CACHE[date_str]


def morning(date_str: str = None):
    """当日の全レースの出走表を取得する。"""
    date_str = date_str or _today()
    data = _load(date_str)
    venues = get_active_venues(date_str)
    if not venues:
        print(f"[異常] {date_str}: {NO_VENUE_HINT}")
        sys.exit(1)
    print(f"[{date_str}] {len(venues)}場")

    count = 0
    problems = []
    for venue in venues:
        times = get_close_times(date_str, venue["code"])
        for rno in range(1, RACE_COUNT + 1):
            racelist = get_racelist(date_str, venue["code"], rno)
            if not racelist:
                continue
            slot = _race_slot(data, venue, rno)
            slot["racers"] = racelist["racers"]
            if rno in times:
                slot["closes_at"] = times[rno]
            problems += _racer_problems(f"{venue['name']} {rno}R", racelist["racers"])
            count += 1
        _save(data)
        print(f"  {venue['name']} 完了 (累計{count}レース)")

    print(f"出走表取得完了: {count}レース")

    # 出走表を一括で取るのはこのジョブだけなので、パーサーの列ずれが
    # 最初に現れるのもここ。途中で落とさず最後まで取ってから落とすのは、
    # 取れたぶんのデータを残すため。保存は各場の後に済んでいる。
    if problems:
        print("\n[異常] 出走表の値がありえない範囲にあります。")
        print("       公式サイトの列構成が変わってパーサーがずれた可能性が高い。")
        for p in problems[:20]:
            print(f"  - {p}")
        if len(problems) > 20:
            print(f"  ... 他{len(problems) - 20}件")
        sys.exit(1)


def tomorrow(date_str: str = None):
    """
    翌日の出走表を取り、予測だけを先に出す。

    **出せるのは予測確率までで、期待値と推奨買い目は出せない。** 三連単の
    オッズは前日には公開されていない（2026-09-09 に実際に叩いて確認した。
    開催場と出走表は取れるが、odds3t は返らない）。オッズが無いということは、
    公開している確率を市場へ引き戻す先も無いということなので、翌日の予測は
    **モデル単独の生の値**になる。当日の予測（市場へ2割引き戻し、展示タイムと
    気象を織り込み済み）とは別物である。

    検証1,212レースでの差:
      当日情報あり（配備構成）  1.1902
      出走表だけ               1.2059

    そのため provisional=True を刻む。画面はこの印を見て「暫定」と明示し、
    期待値と買い目を出さない。**印を外さないこと。** 外すと、質の違う2種類の
    予測が同じ「AI予想」として混ざる。
    """
    date_str = date_str or _tomorrow_date()
    data = _load(date_str)
    venues = get_active_venues(date_str)
    if not venues:
        print(f"[異常] {date_str}: {NO_VENUE_HINT}")
        sys.exit(1)
    print(f"[{date_str}] 翌日 {len(venues)}場")

    count = 0
    problems = []
    for venue in venues:
        times = get_close_times(date_str, venue["code"])
        for rno in range(1, RACE_COUNT + 1):
            racelist = get_racelist(date_str, venue["code"], rno)
            if not racelist:
                continue
            slot = _race_slot(data, venue, rno)
            slot["racers"] = racelist["racers"]
            if rno in times:
                slot["closes_at"] = times[rno]
            problems += _racer_problems(f"{venue['name']} {rno}R", racelist["racers"])

            # オッズが無いので market_prob は渡さない。score_race は
            # pub_prob にモデル単独の値をそのまま入れ、ev と picks を返さない。
            scores = score_race(slot.get("racers", []), None, venue["code"], None)
            if scores:
                slot.update(scores)
                slot["calibrated"] = CALIBRATED
                slot["provisional"] = True
                count += 1
        _save(data)
        print(f"  {venue['name']} 完了 (累計{count}レース)")

    print(f"翌日予測完了: {count}レース")
    print(f"  {_sync_to_db(date_str)}")

    if count == 0:
        print("[異常] 1レースも予測できなかった。出走表が取れていない可能性が高い。")
        sys.exit(1)

    if problems:
        print()
        print("[異常] 出走表の値がありえない範囲にあります。")
        for p in problems[:20]:
            print(f"  - {p}")
        sys.exit(1)


def prerace(window_min: int = 40, date_str: str = None, strict: bool = True,
            report_late: bool = True, only_missing: bool = False,
            require_odds: bool = True, miss_streak_limit: int = 0,
            sync_every: int = 0) -> list:
    """
    締切が window_min 分以内に迫ったレースだけ直前情報とオッズを取る。

    only_missing=True にすると、まだオッズを持っていないレースだけを対象にする。
    朝の一括取得（morning-odds）が繰り返し呼ぶための形で、2周目以降は
    前の周で取れたレースを叩き直さない。

    require_odds=False にすると、オッズが無いことを問題として数えない。
    **朝は発売前のレースがあるのが正常である。** 既定の True のままだと、
    発売前の180レースがそのまま180件の異常になり、通知が毎朝鳴る。
    「通知が来なければ正常」という運用前提のほうが先に壊れる。

    miss_streak_limit を正の値にすると、オッズがその回数連続で取れなかった
    時点でその周を終える。発売前の時間帯に全レースを叩き切らないための歯止めで、
    公式サイトへの無駄な往復を数百回分削る。

    sync_every を正の値にすると、その本数ごとにDBへ取り込む。**取れていても
    DBに入るまでは画面に出ない。** 1周が長いときに、締切の早いレースが
    画面へ出ないまま締切を過ぎるのを防ぐ（MORNING_ODDS_SYNC_EVERY を見ること）。

    strict=False にすると欠損があっても異常終了せず、問題の一覧を返すだけにする。
    ループ実行の途中で落とすと、その日の残り時間の収集がまるごと失われるため。

    **締切を過ぎてから取得したレースは問題として報告する。** 予測が締切後に
    入っても誰も使えないので、これは「取れた」ではなく劣化である。通知は
    失敗時にしか飛ばないため、ここで問題に数えないと気づけない。
    report_late=False にすると数えるだけで報告しない。ループの1周目は、
    起動が遅れた時点で手遅れのレースが混ざるのが構造上避けられないため、
    そこだけ外す（2周目以降の手遅れは、こちらの取り方の問題である）。
    """
    date_str = date_str or _today()
    data = _load(date_str)
    now = datetime.now()
    deadline = now + timedelta(minutes=window_min)

    # 0場と「締切が近いレースが0」は別物。後者は正常（時間帯によっては
    # 対象が無い）だが、前者は異常なので、targets が空になる前に切り分ける。
    schedule = _close_schedule(date_str)
    if not schedule:
        problem = f"{date_str}: {NO_VENUE_HINT}"
        print(f"[異常] {problem}")
        if strict:
            sys.exit(1)
        return [problem]

    targets = []
    for venue, times in schedule:
        for rno, hhmm in times.items():
            close_at = datetime.combine(now.date(), datetime.strptime(hhmm, "%H:%M").time())
            if not now <= close_at <= deadline:
                continue
            if only_missing and _has_odds(_find_slot(data, venue["code"], rno)):
                continue
            targets.append((close_at, venue, rno, hhmm))

    # **締切の早い順に取る。** 場ごとに並べたままだと、2分後に締切のレースが
    # 10レース待ちの最後尾に回ることがある。1レースあたり数秒かかるので、
    # 締切を過ぎてからオッズが入る。実測（2026-09-09）で、その日オッズが
    # 取れた90レースのうち5レースが締切後、11レースが締切5分前だった。
    # 締切を過ぎた予測は、画面に出ても誰も使えない。
    targets.sort(key=lambda t: t[0])
    targets = [(venue, rno, hhmm) for _, venue, rno, hhmm in targets]

    print(f"[{date_str}] 対象 {len(targets)}レース (締切{window_min}分以内・締切順)")
    if not targets:
        return []

    late = []
    leads = []
    odds_got = 0
    trio_got = 0
    visited = []
    misses = 0
    for venue, rno, hhmm in targets:
        visited.append((venue, rno, hhmm))
        slot = _race_slot(data, venue, rno)
        slot["closes_at"] = hhmm

        # 対象に選んだ時点では締切前でも、順番待ちの間に過ぎることがある。
        # 取りに行く直前に測り直す。
        close_at = datetime.combine(now.date(), datetime.strptime(hhmm, "%H:%M").time())
        lead = (close_at - datetime.now()).total_seconds() / 60
        leads.append(lead)
        if lead < 0:
            late.append(f"{venue['name']} {rno}R: 締切{hhmm} を"
                        f"{-lead:.0f}分過ぎてから取得した")

        # morningが失敗していると出走表が無く、展示タイムのマージ先も
        # 予測の入力も存在しないまま黙って空データが積み上がる。
        # 1リクエスト増えるだけなので、無ければここで取り直す。
        if not slot.get("racers"):
            racelist = get_racelist(date_str, venue["code"], rno)
            if racelist:
                slot["racers"] = racelist["racers"]
                print(f"  ! {venue['name']} {rno}R: 出走表が無かったため取得した")

        # 展示タイムは一度出れば動かないので、揃っている行は取り直さない。
        # **ただし締切間際は必ず取り直す。** 風速と波高は開催中に変わるし、
        # モデルはその2つを特徴量に使っている。揃った時点の気象で固定すると、
        # 最後の予測が30分前の水面を見て出されることになる。
        # **締切がまだ遠いレースには取りに行かない。** 展示も気象もその時刻には
        # 出ていないので、空振りに1リクエスト使うだけになる。朝の一括取得で効く。
        need_before = (
            (not _has_beforeinfo(slot)) and lead <= BEFOREINFO_MAX_LEAD_MIN
        ) or lead <= BEFOREINFO_REFRESH_MIN
        before = get_beforeinfo(date_str, venue["code"], rno) if need_before else None
        if before:
            slot["conditions"] = {
                k: before[k] for k in (
                    "weather", "temperature", "water_temp",
                    "wind_speed", "wind_dir_code", "wave_height",
                )
            }
            merge_into_racers(slot.get("racers", []), before)

        market_prob = None
        odds = get_odds(date_str, venue["code"], rno)
        if odds:
            market_prob = odds["market_prob"]
            slot["market_prob"] = market_prob
            slot["overround"] = odds["overround"]
            slot["odds"] = odds["odds"]
            odds_got += 1
            misses = 0
        else:
            misses += 1

        # 三連複は別ページなので1リクエスト増える。**ここで例外を握るのは、
        # 三連複が取れないことで三連単の予測まで失わせないため。** 買い目の
        # 本体は三連単側にあり、締切前にそれを出すことのほうが優先する。
        # 握ったまま静かに壊れ続けないよう、1パスで一度も取れなければ
        # 下でまとめて問題に数える（組版が変わった印）。
        try:
            trio = get_trio_odds(date_str, venue["code"], rno)
        except Exception as exc:               # noqa: BLE001
            trio = None
            print(f"  ! {venue['name']} {rno}R: 三連複オッズを取得できなかった: {exc}")
        if trio:
            slot["trio_odds"] = trio
            trio_got += 1

        scores = score_race(slot.get("racers", []), market_prob, venue["code"],
                            slot.get("conditions"), slot.get("odds"),
                            slot.get("trio_odds"))
        if scores:
            slot.update(scores)
            # 前日に暫定として出した行を、当日の予測で上書きしている。
            # **印を消さないと「暫定」の表示が当日まで残る。** 当日の予測は
            # 市場へ引き戻し済みで展示も気象も入っているので、別物である。
            if market_prob:
                slot.pop("provisional", None)
            # その予測を出したモデルが市場オッズを上回っていたかの記録。
            # 2026-09-07 まではこれが公開の門番を兼ねていたが、予想を出す
            # 方針に変わったので、今は後から成績を追うための印として残す。
            slot["calibrated"] = CALIBRATED

        print(f"  {venue['name']} {rno}R (締切{hhmm}) 取得完了")
        _save(data)

        # **締切の早い順に取っているので、途中で取り込むほど早く画面へ出る。**
        # 1周の終わりまで待つと、最初に取ったレースが最も長く待たされる。
        if sync_every and len(visited) % sync_every == 0:
            print(f"  {_sync_to_db(date_str)}（{len(visited)}レース時点）")

        # **発売前に全レースを叩き切らない。** 対象は締切の早い順なので、
        # 先頭が発売前なら後ろはもっと発売前である。ここで畳んで次の周に回す。
        if miss_streak_limit and misses >= miss_streak_limit:
            print(f"  オッズが{misses}レース続けて取れないので、この周は"
                  f"ここで畳む（残り{len(targets) - len(visited)}レース）。"
                  f"まだ発売前とみなす。")
            break

    # 締切を過ぎたレースの結果を、同じパスの中で取り込む。画面へ出るまでの
    # 遅れが「夜まで」から「巡回の間隔」に縮まる。
    finished = collect_finished(data, date_str, schedule)
    if finished:
        _save(data)
        print(f"  結果を{finished}レース取り込んだ")

    if leads:
        ordered = sorted(leads)
        print(f"直前情報取得完了: {len(visited)}レース "
              f"(締切までの余裕 中央値{ordered[len(ordered) // 2]:.0f}分 / "
              f"最小{ordered[0]:.0f}分)")
    else:
        print(f"直前情報取得完了: {len(visited)}レース")
    # 畳んだ周では、回らなかったレースを検査対象にしない。行っていない
    # レースを「取れていない」と数えると、問題の件数が実態とずれる。
    problems = _healthcheck(data, visited, require_odds=require_odds)
    # 三連単が取れているのに三連複が1件も取れないのは、通信の問題ではなく
    # odds3f の組版が変わった印。上の except が個々の失敗を握るので、
    # ここで数えないと三連複の買い目が静かに画面から消え続ける。
    # ただし朝の一括取得（require_odds=False）では数えない。**三連単のほうが
    # 三連複より先に発売される。** 2026-09-20 の実測で、07:06のパスは三連単だけ
    # 1レース取れて三連複は0件だった。組版の変化ではなく発売の時間差である。
    # 発売前と壊れたを区別できない以上、ここで鳴らすと毎朝の定例になり、
    # 本物の組版変化が埋もれる。通常の巡回では従来どおり数える。
    if require_odds and odds_got and not trio_got:
        problems.append(f"三連単は{odds_got}レース取れたが三連複が1件も取れない。"
                        "odds3f の組版が変わった可能性がある。")
        print(f"  [異常] {problems[-1]}")
    if late:
        for line in late:
            print(f"  [劣化] {line}")
        if report_late:
            problems.extend(late)
    if problems and strict:
        sys.exit(1)
    return problems


def _find_slot(data: dict, venue_code: str, race_no: int) -> dict | None:
    """会場・レースの入れ物を探す。無くても作らない（_race_slot との違い）。"""
    venue = next((v for v in data["venues"] if v["code"] == venue_code), None)
    if venue is None:
        return None
    return next((r for r in venue["races"] if r["race_no"] == race_no), None)


def _has_odds(slot: dict | None) -> bool:
    """
    そのレースの三連単・三連複オッズが両方そろっているか。

    **片方だけでは「取れた」としない。** 三連複は別ページなので片方だけ
    取れることがあり、そこで打ち切ると三連複の買い目が一日中欠けたままになる。
    """
    if not slot:
        return False
    return bool(slot.get("odds")) and bool(slot.get("trio_odds"))


def _has_beforeinfo(slot: dict) -> bool:
    """直前情報が揃っているか。気象と、全艇の展示タイムが入っていること。"""
    if not slot.get("conditions"):
        return False
    racers = slot.get("racers") or []
    return bool(racers) and all(r.get("exhibit_time") is not None for r in racers)


def _racer_problems(label: str, racers: list) -> list:
    """
    出走表の値が、その列にありえない値になっていないか検査する。

    **列がずれても例外は出ない。** racelist の _int / _float はパースに
    失敗しても 0 を返すだけなので、公式サイトが成績欄に列を1つ足すと、
    勝率の欄に3連対率(例 54.95)がそのまま入る。数値としては正常なので
    どこも引っかからず、race_entries に嘘の値が入り、モデルはそれを
    特徴量として使う。overround は無関係なので既存の健全性チェックも
    反応しない。READMEが「最も起きやすく最も気づきにくい」と書いている
    失敗が、実行時には無防備だった。

    見るのは上限だけにしてある。**列ずれの署名は「値が別の列の値域に
    落ちること」**で、それは上限で捕まる。一方ゼロは正当にありうる
    （当地成績の無い選手の当地勝率、デビュー直後の平均ST）ので、
    下限で落とすと本物でない通知が増える。通知が来たら本物、という
    運用前提を壊すほうが害が大きい。
    """
    problems = []
    for r in racers:
        lane = r.get("lane")
        def bad(what):
            problems.append(f"{label} {lane}号艇: {what}")

        # 勝率は10点満点。3連対率(0-100)が流れ込むと必ず超える。
        for key, cap in (("win_rate_all", 10.0), ("win_rate_venue", 10.0)):
            if (r.get(key) or 0.0) > cap:
                bad(f"{key}が{r[key]}（{cap}点満点）")
        # 平均STは1秒未満。勝率(0-10)が流れ込むと超える。
        if (r.get("avg_st") or 0.0) >= 1.0:
            bad(f"avg_stが{r['avg_st']}（1秒未満のはず）")
        # 各種の率は百分率
        for key in ("in2_rate_all", "in3_rate_all", "in2_rate_venue",
                    "in3_rate_venue", "motor_in2_rate", "motor_in3_rate",
                    "boat_in2_rate", "boat_in3_rate"):
            if (r.get(key) or 0.0) > 100.0:
                bad(f"{key}が{r[key]}（百分率のはず）")
        for key in ("motor_no", "boat_no"):
            if (r.get(key) or 0) >= 200:
                bad(f"{key}が{r[key]}（番号としてありえない）")
        if r.get("class") and r["class"] not in ("A1", "A2", "B1", "B2"):
            bad(f"級別が{r['class']!r}")
        # 氏名の欄に数字が来るのは、選手情報の列がまるごとずれた印
        if r.get("name") and r["name"].replace(" ", "").isdigit():
            bad(f"氏名が数字 {r['name']!r}")
        if r.get("racer_id") and not str(r["racer_id"]).isdigit():
            bad(f"登録番号が{r['racer_id']!r}")
    return problems


def _healthcheck(data: dict, targets: list, require_odds: bool = True) -> list:
    """
    取得できたはずの項目が欠けていないか検証し、問題の一覧を返す。
    ジョブが例外なく完走しても中身が空、という劣化を検知するのが目的。
    ワークフローは失敗時にだけ通知するので、最終的にどこかで
    異常終了させないと気づけない。落とす判断は呼び出し側に委ねる。
    """
    problems = []
    for venue, rno, _ in targets:
        slot = next(
            (r for v in data["venues"] if v["code"] == venue["code"]
             for r in v["races"] if r["race_no"] == rno),
            None,
        )
        if slot is None:
            problems.append(f"{venue['name']} {rno}R: レースデータそのものが無い")
            continue
        if len(slot.get("racers", [])) != 6:
            problems.append(f"{venue['name']} {rno}R: 出走表が{len(slot.get('racers', []))}艇")
        problems += _racer_problems(f"{venue['name']} {rno}R", slot.get("racers", []))
        if not slot.get("market_prob"):
            if require_odds:
                problems.append(f"{venue['name']} {rno}R: オッズ未取得")
        else:
            # 正常値は約1.334(=1/0.75)。外れていればオッズの取りこぼし。
            over = slot.get("overround") or 0
            if not 1.25 <= over <= 1.45:
                problems.append(f"{venue['name']} {rno}R: overround異常 {over}")

    if problems:
        print("\n[異常] 取得内容に欠損があります:")
        for p in problems[:20]:
            print(f"  - {p}")
        if len(problems) > 20:
            print(f"  ... 他{len(problems) - 20}件")
    else:
        print("健全性チェック: 問題なし")

    return problems


def _sync_to_db(date_str: str) -> str:
    """
    その日のJSONをSupabaseへ取り込む。DATABASE_URL が無ければ何もしない。

    ループの各パスの直後に呼ぶ。ワークフローの最後にまとめて取り込む形だと、
    4時間走るジョブが終わるまで画面が更新されず、しかも健全性チェックで
    異常終了した場合はその日の収集がまるごとDBに入らないまま捨てられる。
    """
    import os

    if not os.environ.get("DATABASE_URL"):
        return "DB未設定のため取り込みをスキップ"
    from db.loader import load_pipeline_output

    load_pipeline_output(_path(date_str))
    return "取り込み完了"


# 通信エラーが何パス連続したら「一過性ではない」と見なすか。
# 公式サイトの読み取りタイムアウトは散発的に起きるが、連続するときは
# サイト側か回線が本当に落ちている。巡回間隔15分なので3連続は約45分。
LOOP_OUTAGE_STREAK = 3


def prerace_loop(until_hhmm: str = "21:40", interval_min: int = 15,
                 window_min: int = 30, date_str: str = None):
    """
    prerace を指定時刻まで繰り返す。本番のスケジュールはこれを使う。

    GitHubのcronは実測で1日1〜2回しか発火せず、1〜4時間ずれた。毎時の発火を
    前提にすると締切前のオッズがほとんど取れない。実際、稼働2日でオッズが
    取れたのは10レースだけだった。1回の起動でループさせ、発火回数への依存を断つ。

    副次的な利点として、窓を30分と狭く取れる。締切に近いオッズほど市場の
    最終的な評価に近いので、毎時発火を前提に75分まで広げていたときより
    データとしての質が上がる。

    各パスの直後にDBへ取り込むので、画面は20分ごとに新しくなる。
    """
    # **窓に対して間隔が粗いと、締切前に一度しか見ないレースが出る。**
    # 1周に数分かかるので、その一度が順番待ちで締切を過ぎると手遅れになる。
    # 2回は見られる設定でなければ、そもそも起動しない。
    if interval_min * 2 > window_min:
        print(f"[異常] 巡回間隔 {interval_min}分 が窓 {window_min}分 に対して粗い。"
              f" 締切前に一度しか見ないレースが出るため起動しない。"
              f" 間隔は窓の半分以下にすること。")
        sys.exit(1)

    date_str = date_str or _today()
    now = datetime.now()
    end = datetime.combine(now.date(), datetime.strptime(until_hhmm, "%H:%M").time())
    if end <= now:
        print(f"終了時刻 {until_hhmm} を既に過ぎているため何もしない")
        return

    # 最終レースの締切を過ぎたら指定時刻を待たずに切り上げる。
    # 走らせ続けても取るものが無く、ランナーを占有するだけのため。
    closes = [
        datetime.combine(now.date(), datetime.strptime(hhmm, "%H:%M").time())
        for _, times in _close_schedule(date_str) for hhmm in times.values()
    ]
    if closes:
        # 最終レースの結果を取り込んでから終わる。締切の5分後に切り上げると、
        # その日の最後のレースだけ着順が22時まで出ないことになる。
        # RESULT_WAIT_MIN より長く取る。
        end = min(end, max(closes) + timedelta(minutes=RESULT_WAIT_MIN + 9))

    # 開催スケジュールの取得だけで1〜2分かかる。now を取り直さないと
    # 「開始時刻はまだ終了時刻より前」に見えるのに1パスも回らない、
    # という分かりにくい終わり方をする。
    now = datetime.now()
    if end <= now:
        print(f"終了時刻 {end:%H:%M} を既に過ぎているため何もしない "
              f"(現在 {now:%H:%M})")
        return

    print(f"[{date_str}] ループ開始 {now:%H:%M} → {end:%H:%M} "
          f"({interval_min}分ごと・締切{window_min}分以内が対象)")

    passes = 0
    data_problems = []      # 取り方の問題。1件でも失敗にする
    pass_errors = []        # パスごと落ちた通信エラー。連続したときだけ失敗にする
    consecutive = 0
    worst_streak = 0
    while datetime.now() < end:
        passes += 1
        print()
        print(f"--- pass {passes} ({datetime.now():%H:%M}) ---")
        try:
            # 1パスの失敗でループを止めると、その日の残り時間の収集が
            # すべて失われる。記録だけして次のパスへ進む。
            # 1周目の手遅れは起動の遅れによるもので、こちらの取り方の問題では
            # ない。2周目以降で手遅れが出たら、それは順番か間隔の問題である。
            problems = prerace(window_min, date_str, strict=False,
                               report_late=passes > 1)
            data_problems.extend(f"pass {passes}: {x}" for x in problems)
            if problems:
                print("  ※ 欠損があるが、収集は続行する")
            print(f"  {_sync_to_db(date_str)}")
            consecutive = 0
        except Exception as e:
            print(f"[警告] pass {passes} が失敗した: {e}")
            pass_errors.append(f"pass {passes} が例外で失敗: {e}")
            consecutive += 1
            worst_streak = max(worst_streak, consecutive)

        remaining = (end - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(interval_min * 60, remaining))

    print()
    succeeded = passes - len(pass_errors)
    print(f"ループ終了: {passes}パス実行（成功 {succeeded}） /"
          f" 取り方の問題 {len(data_problems)}件 /"
          f" 通信エラー {len(pass_errors)}件（最長連続 {worst_streak}）")

    _report(data_problems, "取り方の問題")
    _report(pass_errors, "通信エラー")

    # **一過性の通信断と、本当の劣化を分けて判定する。**
    #
    # 以前は問題が1件でもあれば失敗にしていた。公式サイトへの読み取りが
    # 15秒でタイムアウトするのは日常的に起きるので、20パス中2〜4パスが
    # 落ちただけの実行まで失敗として通知していた（2026-09-09 の失敗2件は
    # どちらもこれ）。通知が日常化すると、本当の欠測が埋もれる。
    #
    # 一方で「通知が来なければ正常」という運用前提は捨てられないので、
    # 落とす条件は次の3つに限定する。取りこぼしの疑いが残る側に倒してある。
    reasons = []
    if data_problems:
        # 締切後の取得や欠損は、取り方の問題であって相手側の都合ではない。
        # 1件でも出たら直す対象なので、従来どおり必ず失敗にする。
        reasons.append(f"取り方の問題が {len(data_problems)}件")
    if passes and succeeded == 0:
        reasons.append(f"{passes}パスすべてが失敗（1件も取れていない）")
    if worst_streak >= LOOP_OUTAGE_STREAK:
        reasons.append(f"通信エラーが{worst_streak}パス連続"
                       f"（{LOOP_OUTAGE_STREAK}以上は一過性ではない）")

    if reasons:
        # 通知は失敗時にしか飛ばないので、ここで落とさないと劣化に気づけない。
        # データは各パスで取り込み済みなので、落としても失われない。
        print("[異常] " + " / ".join(reasons))
        sys.exit(1)

    if pass_errors:
        print(f"[警告] 通信エラー {len(pass_errors)}件は一過性とみなした"
              f"（連続 {worst_streak} < {LOOP_OUTAGE_STREAK}、"
              f"成功 {succeeded}パス）。失敗にはしない。")


def morning_odds(interval_min: int = 20, date_str: str = None,
                 until_hhmm: str = None) -> None:
    """
    その日の第1レースが始まる前に、全レースのオッズを揃える。

    通常の巡回（prerace-loop）は締切30分前の窓でしか取らない。締切間際の
    オッズほど市場の最終評価に近いという理由でそうしてあり、その方針は
    変えない。**このジョブが足すのは「朝の時点の一枚」である。**
    オッズは追記専用の時系列なので、朝の一枚を足しても締切前の一枚は
    そのまま入り、画面は常に最新を出す。

    朝のオッズは投票が薄く、締切前とは別の数字になる。それでも入れるのは、
    第1レースが始まる時点で、その日の全レースの買い目が画面に出ている
    状態を作るため（2026-09-19、ユーザーの指定）。

    **落とすのは「相手が答えなかった」ときだけで、「取れなかった」ときではない。**
    発売前のレースがあるのは正常であり、1レースも取れない朝もありうる
    （2026-09-19 に置き換えた。以前は取得0件を異常として落としていた）。
    オッズの発売が第1レースの締切より後に始まるなら、その判定では毎朝失敗し、
    「通知が来なければ正常」という運用前提のほうが先に壊れる。
    **オッズページが壊れた場合は同じ日の prerace-loop が必ず失敗する**ので、
    不具合の検知はそちらが担う。ここでの0件は不具合の印ではなく、
    「朝に取れる」という前提が外れている印である。前提が外れているなら、
    毎朝鳴らすのではなく cron から降ろすのが正しい対応になる。

    終了条件は2つ。全レース揃ったら即座に抜ける（揃った後も回り続けると
    ランナーを占有するだけ）。揃わなければ、第1レースの締切
    MORNING_ODDS_MARGIN_MIN 分前まで繰り返す。起動がそれより遅れていた
    場合は1周だけ回して終える（遅れて起動されても、取れるものは取る）。
    """
    date_str = date_str or _today()
    schedule = _close_schedule(date_str)
    if not schedule:
        print(f"[異常] {date_str}: {NO_VENUE_HINT}")
        sys.exit(1)

    today = datetime.now().date()
    closes = [
        datetime.combine(today, datetime.strptime(hhmm, "%H:%M").time())
        for _, times in schedule for hhmm in times.values()
    ]
    if until_hhmm:
        end = datetime.combine(today, datetime.strptime(until_hhmm, "%H:%M").time())
    else:
        end = min(closes) - timedelta(minutes=MORNING_ODDS_MARGIN_MIN)

    # **第1レースの締切を過ぎてから起動されたら何もしない。** cronは実測で
    # 1〜4時間遅れるので、04:23指定でも開催中に発火しうる。そこから1周
    # 回すと、168レースで約76分（2026-09-20 実測）を開催時間帯に使い、
    # 締切前の収集を担う prerace-loop を後ろへ待たせる（concurrency が
    # 直列化するため、同時アクセスではなく遅延として出る）。締切を過ぎた
    # 時点でこの仕事の目的（第1レース前に買い目を出す）は達成できず、
    # その日のオッズは prerace-loop が締切前に取る。
    # 手で --until を渡したときは意図した実行なので止めない。
    if not until_hhmm and datetime.now() >= min(closes):
        print(f"[{date_str}] 第1レースの締切 {min(closes):%H:%M} を過ぎているので"
              f"何もしない (現在 {datetime.now():%H:%M})。"
              f"この時間帯のオッズは prerace-loop が締切前に取る。")
        return

    print(f"[{date_str}] 朝の一括取得 {len(closes)}レース / "
          f"第1レース締切 {min(closes):%H:%M} / 目標 {end:%H:%M}")

    passes = 0
    errors = []
    consecutive = 0
    worst_streak = 0
    first_odds_at = None
    got = 0
    pending = []
    while True:
        passes += 1
        # **パスの開始時刻を控える。** 1周は168レースで約76分かかる
        # （2026-09-20 実測）。取得できた時刻をパスの終了後に採ると、
        # 発売開始を1時間以上あとにずらして記録することになる。
        pass_started = datetime.now()
        print()
        print(f"--- 一括取得 pass {passes} ({pass_started:%H:%M}) ---")
        try:
            prerace(window_min=24 * 60, date_str=date_str, strict=False,
                    report_late=False, only_missing=True, require_odds=False,
                    miss_streak_limit=MORNING_ODDS_MISS_STREAK,
                    sync_every=MORNING_ODDS_SYNC_EVERY)
            print(f"  {_sync_to_db(date_str)}")
            consecutive = 0
        except Exception as e:                      # noqa: BLE001
            print(f"[警告] pass {passes} が失敗した: {e}")
            errors.append(f"pass {passes} が例外で失敗: {e}")
            consecutive += 1
            worst_streak = max(worst_streak, consecutive)

        data = _load(date_str)
        now = datetime.now()
        pending = [
            (venue["name"], rno, hhmm)
            for venue, times in schedule for rno, hhmm in times.items()
            if datetime.combine(today, datetime.strptime(hhmm, "%H:%M").time()) > now
            and not _has_odds(_find_slot(data, venue["code"], rno))
        ]
        got = sum(
            1 for venue, times in schedule for rno in times
            if _has_odds(_find_slot(data, venue["code"], rno))
        )
        if got and first_odds_at is None:
            first_odds_at = pass_started
        print(f"  取得済み {got}レース / 未取得（締切前）{len(pending)}レース")

        if not pending:
            print("全レース揃ったので終了する")
            break
        remaining = (end - datetime.now()).total_seconds()
        if remaining <= 0:
            print(f"目標 {end:%H:%M} を過ぎたので終了する")
            break
        time.sleep(min(interval_min * 60, remaining))

    succeeded = passes - len(errors)
    first = f"{first_odds_at:%H:%M}" if first_odds_at else "なし"
    print()
    print(f"一括取得終了: {passes}パス（成功 {succeeded}） / 取得 {got}レース /"
          f" 初めて取れた時刻 {first} /"
          f" 通信エラー {len(errors)}件（最長連続 {worst_streak}）")

    _report(errors, "通信エラー")
    if pending:
        print(f"[注意] {len(pending)}レースがまだ発売前か取得できていない:")
        for name, rno, hhmm in pending[:10]:
            print(f"    - {name} {rno}R (締切{hhmm})")

    # **「朝に取れるか」を毎日測って残す。** オッズの発売開始時刻は実測して
    # いない。失敗にしない代わりにここへ書き溜める。0件の日が続くなら、
    # この仕事は目的を果たせていないので cron から降ろす判断材料になる。
    data = _load(date_str)
    data["morning_sweep"] = {
        "passes": passes,
        "succeeded": succeeded,
        "got": got,
        "first_odds_at": f"{first_odds_at:%H:%M}" if first_odds_at else None,
        "ended_at": f"{datetime.now():%H:%M}",
    }
    _save(data)

    # **落とす条件は「相手が答えなかった」ことに限る。** prerace-loop の
    # 3条件と同じ形だが、「取り方の問題」に当たるものがここには無い。
    # 締切後の取得は起こりえず（朝は締切のはるか前）、オッズの欠落は
    # 発売前と区別できないためである。区別できない以上、疑わしきを
    # 失敗にすると毎朝鳴る（2026-09-19、それで0件失敗を取り消した）。
    reasons = []
    if passes and succeeded == 0:
        reasons.append(f"{passes}パスすべてが失敗（サイトへ一度も到達できていない）")
    if worst_streak >= LOOP_OUTAGE_STREAK:
        reasons.append(f"通信エラーが{worst_streak}パス連続"
                       f"（{LOOP_OUTAGE_STREAK}以上は一過性ではない）")

    if reasons:
        print("[異常] " + " / ".join(reasons))
        sys.exit(1)


def _report(items: list, label: str) -> None:
    """問題の一覧を出す。件数が多いときは頭だけ。"""
    if not items:
        return
    print(f"  [{label}] {len(items)}件:")
    for x in items[:20]:
        print(f"    - {x}")
    if len(items) > 20:
        print(f"    ... 他{len(items) - 20}件")


def _target_result_date() -> str:
    """
    結果を取りに行くべき開催日を返す。

    resultsは22:00 JSTに走る想定だが、GitHub Actionsのスケジュールは
    数時間遅れることがある。実際に4時間遅れて翌02:00に走り、
    「まだ開催していない当日」の結果を取りに行って0件で終わった。

    深夜から昼までに走った場合は、直前の開催日（前日）を対象にする。
    12時を境にするのは、遅延が12時間を超えることは考えにくく、
    かつ当日の全レースが終わるのは概ね21時以降だから。
    """
    now = datetime.now()
    target = now if now.hour >= 12 else now - timedelta(days=1)
    return target.strftime("%Y%m%d")


def _job_date(cmd: str) -> str:
    """
    そのジョブが対象とすべき開催日。

    ワークフローが収集と取り込みで同じ日付を使えるよう、外から引ける形にしてある。
    以前は取り込み側がシェルの date +%Y%m%d で当日を組み立てていたため、
    resultsが遅延して前日を対象にしたとき、収集は前日のファイルを書くのに
    取り込みは存在しない当日のファイルを見に行き、
    「取り込むデータなし」と表示して正常終了していた。
    """
    if cmd == "results":
        return _target_result_date()
    if cmd == "tomorrow":
        # 収集側と同じ日付を返す。ここがずれると、収集は翌日のファイルを書くのに
        # 取り込みは別の日を見に行き、「取り込むデータなし」で正常終了する。
        return _tomorrow_date()
    return _today()


RESULT_WAIT_MIN = 6  # 締切から結果が出るまでの目安。レースは締切の数分後に発走する


def _store_result(slot: dict, date_str: str, venue_code: str, rno: int) -> bool:
    """結果ページを取り、行に入れる。取れなければ False。

    **中止は「取れなかった」ではない。** 中止のレースには着順が永遠に入らない
    ので、取り直しの対象から外し、行に印を残す。印が無いと、収集の失敗と
    見分けがつかないまま欠測として数え続けることになる。
    """
    result = get_result(date_str, venue_code, rno)
    if result and result.get("cancelled"):
        slot["cancelled"] = True
        return False
    if not result or not result.get("winner_lane"):
        return False
    slot["result"] = {
        "winner_lane": result["winner_lane"],
        "finish": result["finish"],
        "kimarite": result["kimarite"],
        "payouts": result["payouts"],
        # 進入コースと本番ST。同じページに載っているので取得は増えない。
        # ここに残しておくと backtest.py import-daily がそのまま使え、
        # バックテスト用に結果ページを取り直さずに済む。
        "start": result.get("start") or [],
    }
    return True


def collect_finished(data: dict, date_str: str, schedule: list) -> int:
    """
    締切を過ぎたレースの結果を取り込む。**まだ結果を持たない行だけ。**

    以前は1日1回 results ジョブでまとめて取っていたので、朝のレースの着順が
    画面に出るのは夜になってからだった。prerace のパスごとにここを通せば、
    レース終了からおよそ15分（巡回の間隔）で画面に出る。

    **取得量は増えない。** 1レースにつき結果ページを1回取るのは以前と同じで、
    取る時刻が夜からレース直後に移るだけである。既に結果を持つ行は飛ばす。
    """
    now = datetime.now()
    got = 0
    for venue, times in schedule:
        for rno, hhmm in times.items():
            close_at = datetime.combine(now.date(),
                                        datetime.strptime(hhmm, "%H:%M").time())
            if now < close_at + timedelta(minutes=RESULT_WAIT_MIN):
                continue
            slot = _race_slot(data, venue, rno)
            if slot.get("result"):
                continue
            if _store_result(slot, date_str, venue["code"], rno):
                got += 1
                print(f"  結果 {venue['name']} {rno}R 取得")
    return got


def results(date_str: str = None):
    """その日の確定結果を取得する。全レース終了後に1回走らせる。"""
    date_str = date_str or _target_result_date()
    data = _load(date_str)
    venues = get_active_venues(date_str)
    if not venues:
        print(f"[異常] {date_str}: {NO_VENUE_HINT}")
        sys.exit(1)

    count = 0
    already = 0
    for venue in venues:
        for rno in range(1, RACE_COUNT + 1):
            slot = _race_slot(data, venue, rno)
            # **既に持っている行は取りに行かない。** prerace のパスがレース直後に
            # 取り込んでいるので、ここで全レースを取り直すと同じページを二度
            # 取ることになる。このジョブは取りこぼしの受け皿として残す。
            if slot.get("result"):
                already += 1
                continue
            if slot.get("cancelled"):
                continue
            if _store_result(slot, date_str, venue["code"], rno):
                count += 1
        _save(data)
        print(f"  {venue['name']} 完了 (累計{count}レース)")

    cancelled = sum(1 for v in data["venues"] for r in v.get("races", [])
                    if r.get("cancelled"))
    print(f"結果取得完了: {count}レース"
          f"（取得済みで飛ばした {already}レース / 中止 {cancelled}レース）")

    # **0件でも、既に持っている行があるなら正常。** prerace のパスが
    # レース直後に取り込んでいるので、このジョブが何もすることが無いのは
    # 望ましい状態である。一方、新規も既存も0なら、その日の結果が1つも
    # 無いということなので異常。通知は失敗時にしか飛ばない。
    # 中止も「結果が確定した」うちに数える。中止しかない日を異常として
    # 落とすと、通知が本当の欠測と区別できなくなる。
    if count == 0 and already == 0 and cancelled == 0:
        print(f"[異常] {date_str}: 結果が1レースも無い。"
              " 結果ページの体裁が変わったか、収集が丸ごと失敗している。")
        sys.exit(1)


if __name__ == "__main__":
    _use_utf8_stdio()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]

    def opt(name, default):
        return args[args.index(name) + 1] if name in args else default

    window = int(opt("--window", 40 if cmd == "prerace" else 30))
    interval = int(opt("--interval", 15))
    until = opt("--until", "21:40")
    positional = [a for a in args[1:] if a.isdigit() and len(a) == 8]
    date_arg = positional[0] if positional else None

    if cmd == "target-date":
        print(_job_date(args[1] if len(args) > 1 else ""))
    elif cmd == "morning":
        morning(date_arg)
    elif cmd == "prerace":
        prerace(window, date_arg)
    elif cmd == "morning-odds":
        morning_odds(int(opt("--interval", "20")), date_arg,
                     opt("--until", None))
    elif cmd == "prerace-loop":
        prerace_loop(until, interval, window, date_arg)
    elif cmd == "tomorrow":
        tomorrow(date_arg)
    elif cmd == "results":
        results(date_arg)
    else:
        print(__doc__)
