"""
GitHub Actionsから呼ぶ収集ジョブ。

フルpipelineを毎時回すと1回あたり約30分かかり、月10,000分を超えて
GitHub Actionsの無料枠(private 2,000分/月)を使い切る。そのため
用途ごとにジョブを分け、直前情報とオッズは「締切が近いレースだけ」に絞る。

  morning  : その日の全レースの出走表を取得（1日1回）
  prerace  : 締切がN分以内のレースだけ直前情報とオッズを取得（毎時）
  results  : 確定結果を取得（1日1回）。実行が深夜〜昼にずれ込んだ場合は
             前日を対象にする。GitHubのスケジュールは数時間遅れうるため。

使い方:
  py -3 jobs.py morning
  py -3 jobs.py prerace --window 40
  py -3 jobs.py results [YYYYMMDD]
  py -3 jobs.py target-date results   # 対象日だけを出力する
"""
import io
import json
import sys
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
from scraper.scoring import score_race

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


def morning(date_str: str = None):
    """当日の全レースの出走表を取得する。"""
    date_str = date_str or _today()
    data = _load(date_str)
    venues = get_active_venues(date_str)
    print(f"[{date_str}] {len(venues)}場")

    count = 0
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
            count += 1
        _save(data)
        print(f"  {venue['name']} 完了 (累計{count}レース)")

    print(f"出走表取得完了: {count}レース")


def prerace(window_min: int = 40, date_str: str = None):
    """締切が window_min 分以内に迫ったレースだけ直前情報とオッズを取る。"""
    date_str = date_str or _today()
    data = _load(date_str)
    now = datetime.now()
    deadline = now + timedelta(minutes=window_min)

    venues = get_active_venues(date_str)
    targets = []
    for venue in venues:
        for rno, hhmm in get_close_times(date_str, venue["code"]).items():
            close_at = datetime.combine(now.date(), datetime.strptime(hhmm, "%H:%M").time())
            if now <= close_at <= deadline:
                targets.append((venue, rno, hhmm))

    print(f"[{date_str}] 対象 {len(targets)}レース (締切{window_min}分以内)")
    if not targets:
        return

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

        scores = score_race(slot.get("racers", []), market_prob, venue["code"])
        if scores:
            slot.update(scores)

        print(f"  {venue['name']} {rno}R (締切{hhmm}) 取得完了")
        _save(data)

    print(f"直前情報取得完了: {len(targets)}レース")
    _healthcheck(data, targets)


def _healthcheck(data: dict, targets: list):
    """
    取得できたはずの項目が欠けていないか検証し、欠けていれば異常終了する。
    ジョブが例外なく完走しても中身が空、という劣化を検知するのが目的。
    ワークフローは失敗時にだけ通知するので、ここで落とさないと気づけない。
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
        sys.exit(1)

    print("健全性チェック: 問題なし")


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
    window = 40
    if "--window" in args:
        window = int(args[args.index("--window") + 1])
    positional = [a for a in args[1:] if a.isdigit() and len(a) == 8]
    date_arg = positional[0] if positional else None

    if cmd == "target-date":
        print(_job_date(args[1] if len(args) > 1 else ""))
    elif cmd == "morning":
        morning(date_arg)
    elif cmd == "prerace":
        prerace(window, date_arg)
    elif cmd == "results":
        results(date_arg)
    else:
        print(__doc__)
