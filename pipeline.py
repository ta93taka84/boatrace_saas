"""
ボートレース データ取得パイプライン
使い方:
  python pipeline.py              # 本日のデータを取得
  python pipeline.py 20250901    # 指定日のデータを取得
  python pipeline.py --before    # 直前情報（展示タイム）も取得
"""
import io
import json
import sys
import warnings

# Windows cp932環境でもUTF-8出力を強制
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# lxml HTML警告を抑制（boatrace.jpはHTML、警告は誤検知）
from bs4 import XMLParsedAsHTMLWarning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from datetime import datetime
from pathlib import Path

from scraper.schedule import get_active_venues
from scraper.racelist import get_racelist
from scraper.beforeinfo import get_beforeinfo
from scraper.odds import get_odds
from scraper.scoring import score_race, CALIBRATED

RACE_COUNT = 12  # 通常1場12レース
OUTPUT_DIR = Path("output")


def run(date_str: str, fetch_before: bool = False):
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"[{date_str}] 開催場を取得中...")

    venues = get_active_venues(date_str)
    if not venues:
        print("本日の開催情報が取得できませんでした。")
        return

    print(f"  開催場: {[v['name'] for v in venues]}")

    result = {"date": date_str, "fetched_at": datetime.now().isoformat(), "venues": []}

    for venue in venues:
        code, name = venue["code"], venue["name"]
        print(f"\n[{name}({code})] レース取得中...")
        venue_data = {"code": code, "name": name, "races": []}

        for race_no in range(1, RACE_COUNT + 1):
            print(f"  R{race_no:02d} ", end="", flush=True)

            race_data = {"race_no": race_no}

            # 出走表
            racelist = get_racelist(date_str, code, race_no)
            if racelist:
                race_data["racers"] = racelist["racers"]
                print("出走表✓ ", end="", flush=True)
            else:
                print("出走表- ", end="", flush=True)

            # 直前情報（オプション）
            if fetch_before:
                before = get_beforeinfo(date_str, code, race_no)
                if before:
                    race_data["conditions"] = {
                        k: before[k] for k in (
                            "weather", "temperature", "water_temp",
                            "wind_speed", "wind_dir_code", "wave_height",
                        )
                    }
                    _merge_beforeinfo(race_data, before["racers"])
                    print("直前✓ ", end="", flush=True)

            # オッズ（市場勝率）
            market_prob = None
            odds = get_odds(date_str, code, race_no)
            if odds:
                market_prob = odds["market_prob"]
                race_data["market_prob"] = market_prob
                race_data["overround"] = odds["overround"]
                print("オッズ✓ ", end="", flush=True)
            else:
                print("オッズ- ", end="", flush=True)

            # 予測勝率・期待値
            scores = score_race(race_data.get("racers", []), market_prob, code,
                                race_data.get("conditions"))
            if scores:
                race_data.update(scores)
                if "top_ev" in scores:
                    print(f"EV✓(推奨:{scores['top_lane']}号艇 EV={scores['top_ev']:.2f})", end="")

            print()
            venue_data["races"].append(race_data)

        result["venues"].append(venue_data)

    out_path = OUTPUT_DIR / f"{date_str}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存完了: {out_path}")

    _print_summary(result)


def _merge_beforeinfo(race_data: dict, before_racers: list):
    lane_map = {r["lane"]: r for r in before_racers}
    for racer in race_data.get("racers", []):
        bi = lane_map.get(racer["lane"])
        if not bi:
            continue
        for key in ("exhibit_time", "tilt"):
            if bi.get(key) is not None:
                racer[key] = bi[key]


def _print_summary(result: dict):
    if not CALIBRATED:
        print("")
        print("[警告] モデル未較正。バックテストで市場オッズを上回るまで、")
        print("       EVは参考値であり賭けの根拠にはならない。")
        print("       状況確認: py -3 backtest.py eval")
    print("\n===== 期待値スコア サマリー =====")
    rows = []
    for venue in result["venues"]:
        for race in venue["races"]:
            if "top_ev" in race and race["top_ev"] > 0:
                rows.append({
                    "venue": venue["name"],
                    "race_no": race["race_no"],
                    "top_lane": race.get("top_lane"),
                    "top_ev": race.get("top_ev", 0),
                })

    rows.sort(key=lambda x: x["top_ev"], reverse=True)
    print(f"{'会場':<8} {'R':>3} {'推奨艇':>5} {'EVスコア':>8}")
    print("-" * 30)
    for r in rows[:10]:
        mark = " ★" if r["top_ev"] >= 1.1 else ""
        print(f"{r['venue']:<8} {r['race_no']:>3}R {r['top_lane']:>5}号艇 {r['top_ev']:>8.3f}{mark}")


if __name__ == "__main__":
    args = sys.argv[1:]
    fetch_before = "--before" in args
    args = [a for a in args if not a.startswith("--")]

    date = args[0] if args else datetime.now().strftime("%Y%m%d")
    run(date, fetch_before=fetch_before)
