"""
GitHub Actionsから呼ぶ収集ジョブ。

フルpipelineを毎時回すと1回あたり約30分かかり、月10,000分を超えて
GitHub Actionsの無料枠(private 2,000分/月)を使い切る。そのため
用途ごとにジョブを分け、直前情報とオッズは「締切が近いレースだけ」に絞る。

  morning      : その日の全レースの出走表を取得（1日1回）
  prerace      : 締切がN分以内のレースだけ直前情報とオッズを取得（1回だけ）
  prerace-loop : preraceを指定時刻まで繰り返す。本番のスケジュールはこちら。
  results      : 確定結果を取得（1日1回）。実行が深夜〜昼にずれ込んだ場合は
                 前日を対象にする。GitHubのスケジュールは数時間遅れうるため。

本番で prerace ではなく prerace-loop を使うのは、GitHubのcronが
発火しないため。実測では30分毎に設定しても1日1〜2回しか発火せず、
しかも1〜4時間ずれた。「毎時発火する」前提の設計は成立しない。
1回起動したらプロセス内でループし、発火回数に依存しない形にする。

使い方:
  py -3 jobs.py morning
  py -3 jobs.py prerace --window 40
  py -3 jobs.py prerace-loop --until 21:40 --interval 20 --window 30
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

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from scraper.schedule import get_active_venues, get_close_times
from scraper.racelist import get_racelist
from scraper.beforeinfo import get_beforeinfo
from scraper.odds import get_odds
from scraper.result import get_result
from scraper.scoring import score_race, CALIBRATED

OUTPUT_DIR = Path("output")
RACE_COUNT = 12


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _path(date_str: str) -> Path:
    return OUTPUT_DIR / f"{date_str}.json"


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


def prerace(window_min: int = 40, date_str: str = None, strict: bool = True) -> list:
    """
    締切が window_min 分以内に迫ったレースだけ直前情報とオッズを取る。

    strict=False にすると欠損があっても異常終了せず、問題の一覧を返すだけにする。
    ループ実行の途中で落とすと、その日の残り時間の収集がまるごと失われるため。
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
            if now <= close_at <= deadline:
                targets.append((venue, rno, hhmm))

    print(f"[{date_str}] 対象 {len(targets)}レース (締切{window_min}分以内)")
    if not targets:
        return []

    for venue, rno, hhmm in targets:
        slot = _race_slot(data, venue, rno)
        slot["closes_at"] = hhmm

        # morningが失敗していると出走表が無く、展示タイムのマージ先も
        # 予測の入力も存在しないまま黙って空データが積み上がる。
        # 1リクエスト増えるだけなので、無ければここで取り直す。
        if not slot.get("racers"):
            racelist = get_racelist(date_str, venue["code"], rno)
            if racelist:
                slot["racers"] = racelist["racers"]
                print(f"  ! {venue['name']} {rno}R: 出走表が無かったため取得した")

        before = get_beforeinfo(date_str, venue["code"], rno)
        if before:
            slot["conditions"] = {
                k: before[k] for k in (
                    "weather", "temperature", "water_temp",
                    "wind_speed", "wind_dir_code", "wave_height",
                )
            }
            lane_map = {r["lane"]: r for r in before["racers"]}
            for racer in slot.get("racers", []):
                bi = lane_map.get(racer["lane"])
                if bi:
                    for key in ("exhibit_time", "tilt"):
                        if bi.get(key) is not None:
                            racer[key] = bi[key]

        market_prob = None
        odds = get_odds(date_str, venue["code"], rno)
        if odds:
            market_prob = odds["market_prob"]
            slot["market_prob"] = market_prob
            slot["overround"] = odds["overround"]
            slot["odds"] = odds["odds"]

        scores = score_race(slot.get("racers", []), market_prob, venue["code"],
                            slot.get("conditions"))
        if scores:
            slot.update(scores)
            # DB側は loader が predictions.calibrated に同じ印を刻み、RLSが
            # 未較正の予測を公開画面から隠している。日次JSONにも同じ印を残す。
            # これが無いと、Supabaseの環境変数が未設定でファイルを読む経路
            # （手元と、Vercelで設定を忘れた状態）だけ門番を素通りする。
            slot["calibrated"] = CALIBRATED

        print(f"  {venue['name']} {rno}R (締切{hhmm}) 取得完了")
        _save(data)

    print(f"直前情報取得完了: {len(targets)}レース")
    problems = _healthcheck(data, targets)
    if problems and strict:
        sys.exit(1)
    return problems


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


def _healthcheck(data: dict, targets: list) -> list:
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


def prerace_loop(until_hhmm: str = "21:40", interval_min: int = 20,
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
        end = min(end, max(closes) + timedelta(minutes=5))

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
    failures = []
    while datetime.now() < end:
        passes += 1
        print()
        print(f"--- pass {passes} ({datetime.now():%H:%M}) ---")
        try:
            # 1パスの失敗でループを止めると、その日の残り時間の収集が
            # すべて失われる。記録だけして次のパスへ進む。
            problems = prerace(window_min, date_str, strict=False)
            failures.extend(f"pass {passes}: {x}" for x in problems)
            if problems:
                print("  ※ 欠損があるが、収集は続行する")
            print(f"  {_sync_to_db(date_str)}")
        except Exception as e:
            print(f"[警告] pass {passes} が失敗した: {e}")
            failures.append(f"pass {passes} が例外で失敗: {e}")

        remaining = (end - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(interval_min * 60, remaining))

    print()
    print(f"ループ終了: {passes}パス実行 / 問題 {len(failures)}件")
    if failures:
        # 通知は失敗時にしか飛ばないので、ここで落とさないと劣化に気づけない。
        # データは各パスで取り込み済みなので、落としても失われない。
        print("[異常] ループ中に次の問題が出た:")
        for f in failures[:20]:
            print(f"  - {f}")
        if len(failures) > 20:
            print(f"  ... 他{len(failures) - 20}件")
        sys.exit(1)


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
    return _target_result_date() if cmd == "results" else _today()


def results(date_str: str = None):
    """その日の確定結果を取得する。全レース終了後に1回走らせる。"""
    date_str = date_str or _target_result_date()
    data = _load(date_str)
    venues = get_active_venues(date_str)
    if not venues:
        print(f"[異常] {date_str}: {NO_VENUE_HINT}")
        sys.exit(1)

    count = 0
    for venue in venues:
        for rno in range(1, RACE_COUNT + 1):
            result = get_result(date_str, venue["code"], rno)
            if not result:
                continue
            slot = _race_slot(data, venue, rno)
            slot["result"] = {
                "winner_lane": result["winner_lane"],
                "finish": result["finish"],
                "kimarite": result["kimarite"],
                "payouts": result["payouts"],
            }
            count += 1
        _save(data)
        print(f"  {venue['name']} 完了 (累計{count}レース)")

    print(f"結果取得完了: {count}レース")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]

    def opt(name, default):
        return args[args.index(name) + 1] if name in args else default

    window = int(opt("--window", 40 if cmd == "prerace" else 30))
    interval = int(opt("--interval", 20))
    until = opt("--until", "21:40")
    positional = [a for a in args[1:] if a.isdigit() and len(a) == 8]
    date_arg = positional[0] if positional else None

    if cmd == "target-date":
        print(_job_date(args[1] if len(args) > 1 else ""))
    elif cmd == "morning":
        morning(date_arg)
    elif cmd == "prerace":
        prerace(window, date_arg)
    elif cmd == "prerace-loop":
        prerace_loop(until, interval, window, date_arg)
    elif cmd == "results":
        results(date_arg)
    else:
        print(__doc__)
