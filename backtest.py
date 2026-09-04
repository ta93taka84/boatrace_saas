"""
過去レースでモデルを評価・較正する。

使い方:
  py -3 backtest.py collect   20260825 20260901  # 期間データを cache/ に収集
  py -3 backtest.py eval      20260825 20260901  # 収集済みデータで評価
  py -3 backtest.py calibrate 20260825 20260901  # 場別コース勝率を書き出す

collect は過去日のみキャッシュされるため、eval と calibrate は
サイトを叩き直さずに何度でも再実行できる。較正のパラメータを
いじりながら評価を回す作業がスクレイピング待ちにならない。
"""
import io
import json
import math
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
from bs4 import XMLParsedAsHTMLWarning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from scraper.schedule import get_active_venues
from scraper.racelist import get_racelist
from scraper.odds import get_odds
from scraper.beforeinfo import get_beforeinfo
from scraper.result import get_result
from scraper.scoring import estimate_win_prob, COURSE_BASE_WIN_RATE

DATASET = Path("output/backtest.jsonl")
RACE_COUNT = 12


def daterange(start: str, end: str):
    d = datetime.strptime(start, "%Y%m%d")
    last = datetime.strptime(end, "%Y%m%d")
    while d <= last:
        yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


def collect(start: str, end: str):
    DATASET.parent.mkdir(exist_ok=True)
    seen = _existing_keys()
    written = 0

    with DATASET.open("a", encoding="utf-8") as f:
        for date_str in daterange(start, end):
            venues = get_active_venues(date_str)
            print(f"[{date_str}] {len(venues)}場")
            for v in venues:
                for rno in range(1, RACE_COUNT + 1):
                    key = f"{date_str}-{v['code']}-{rno}"
                    if key in seen:
                        continue
                    row = _build_row(date_str, v, rno)
                    if row:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        f.flush()
                        written += 1
                print(f"  {v['name']} 完了 (累計{written}件)")

    print(f"収集完了: {written}件を {DATASET} に追記")


def _build_row(date_str, venue, rno):
    try:
        result = get_result(date_str, venue["code"], rno)
        if not result or not result["winner_lane"]:
            return None
        racelist = get_racelist(date_str, venue["code"], rno)
        if not racelist:
            return None
        odds = get_odds(date_str, venue["code"], rno)
        if not odds:
            return None
    except Exception as e:
        print(f"  ! {date_str} {venue['name']} R{rno}: {e}")
        return None

    return {
        "date": date_str,
        "venue": venue["code"],
        "venue_name": venue["name"],
        "race_no": rno,
        "racers": racelist["racers"],
        "market_prob": odds["market_prob"],
        "winner_lane": result["winner_lane"],
        "trifecta_payout": result["payouts"].get("3連単", {}).get("payout"),
        "kimarite": result.get("kimarite"),
    }


def _existing_keys() -> set:
    if not DATASET.exists():
        return set()
    keys = set()
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            keys.add(f"{r['date']}-{r['venue']}-{r['race_no']}")
        except (json.JSONDecodeError, KeyError):
            continue
    return keys


def evaluate(start: str = None, end: str = None):
    rows = _load(start, end)
    if not rows:
        print("データがありません。先に collect を実行してください。")
        return

    train, test = _split_by_date(rows)
    if not test:
        print(f"{len(rows)}レースは1日分しかなく、学習と検証に分けられません。")
        print("collect で日数を増やしてから評価してください。")
        return

    # 基準率は学習側だけから推定する。
    #
    # calibrate が書く course_rates.json は全データの勝者から作られる。
    # それを使って同じデータを採点すると、自分で作った答えで答え合わせを
    # することになり、「較正後に再評価すると良くなる」のはその自己成就を
    # かなり含む。CLAUDE.md の「判断は必ず分割で行う」はこのため。
    table = _fit_course_rates(train)

    def rates_of(r):
        return _rates_for(table, r["venue"])

    print(f"全{len(rows)}レース (学習{len(train)} / 検証{len(test)})")
    print(f"採点するのは検証側の{len(test)}レースだけ。基準率は学習側から推定した。\n")

    predictors = {
        "コース基準のみ": lambda r: _normalize(
            {x["lane"]: rates_of(r).get(x["lane"], 0.05) for x in r["racers"]}
        ),
        "モデル(現行)": lambda r: estimate_win_prob(
            r["racers"], r["venue"], r.get("conditions"), base_rates=rates_of(r)),
        "市場オッズ": lambda r: {int(k): v for k, v in r["market_prob"].items()},
    }

    print(f"{'予測器':<16} {'LogLoss':>9} {'Brier':>9} {'的中率':>8}")
    print("-" * 46)
    for name, fn in predictors.items():
        ll, brier, hit = _score(test, fn)
        print(f"{name:<16} {ll:>9.4f} {brier:>9.4f} {hit:>7.1%}")

    print("\n(LogLoss・Brierは小さいほど良い。市場オッズに勝てなければ賭ける根拠はない)")
    print("(的中率は「1号艇を常に選ぶ」だけで約50%出る。これで判断しないこと)")
    print()
    print("[注意] 基準率の漏れは塞いだが、モデルの数字はまだ楽観側に寄っている。")
    print("       scoring.py の LOGIT_WEIGHTS は全データで当てはめた係数なので、")
    print("       検証側にもその情報が入っている。候補の採否は experiment.py の")
    print("       対応のある比較で判断すること。ここは配備前の健全性確認に使う。")
    print()

    _calibration_table(test, predictors["モデル(現行)"], "モデル(現行)")
    _calibration_table(test, predictors["市場オッズ"], "市場オッズ")
    _course_actuals(rows)


def _load(start, end):
    if not DATASET.exists():
        return []
    rows = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if start and r["date"] < start:
            continue
        if end and r["date"] > end:
            continue
        rows.append(r)
    return rows


def _split_by_date(rows):
    """
    日付で前半(学習)と後半(検証)に分ける。experiment.py の split_by_date と同じ
    切り方にしてある。レース単位で無作為に分けると、同じ日・同じ節の情報が
    両側に跨がって漏れるため、切れ目は必ず日付に置く。
    """
    dates = sorted({r["date"] for r in rows})
    if len(dates) < 2:
        return rows, []
    cut = dates[len(dates) // 2]
    train = [r for r in rows if r["date"] < cut]
    test = [r for r in rows if r["date"] >= cut]
    return train, test


def _score(rows, predict):
    ll_sum = brier_sum = 0.0
    hits = n = 0
    for r in rows:
        probs = predict(r)
        if not probs:
            continue
        winner = r["winner_lane"]
        p = max(probs.get(winner, 1e-6), 1e-6)
        ll_sum += -math.log(p)
        brier_sum += sum((probs.get(l, 0) - (1 if l == winner else 0)) ** 2 for l in range(1, 7))
        if max(probs, key=probs.get) == winner:
            hits += 1
        n += 1
    if n == 0:
        return 0.0, 0.0, 0.0
    return ll_sum / n, brier_sum / n, hits / n


def _calibration_table(rows, predict, label):
    """予測確率帯ごとの実際の勝率。理想は予測≒実績。"""
    buckets = {}
    for r in rows:
        probs = predict(r)
        if not probs:
            continue
        for lane, p in probs.items():
            b = min(int(p * 10), 9)
            hit = 1 if lane == r["winner_lane"] else 0
            s = buckets.setdefault(b, [0, 0.0, 0])
            s[0] += 1
            s[1] += p
            s[2] += hit

    print(f"--- 較正: {label} ---")
    print(f"{'予測帯':>10} {'件数':>7} {'平均予測':>9} {'実績勝率':>9} {'ずれ':>8}")
    for b in sorted(buckets):
        n, psum, hits = buckets[b]
        pred, actual = psum / n, hits / n
        print(f"{b*10:>3}-{b*10+10:<6} {n:>7} {pred:>9.3f} {actual:>9.3f} {actual-pred:>+8.3f}")
    print()


def _course_actuals(rows):
    """実データから場ごと・コースごとの1着率を出す。ベースライン較正用。"""
    overall = {i: [0, 0] for i in range(1, 7)}
    by_venue = {}
    for r in rows:
        for lane in range(1, 7):
            overall[lane][0] += 1
            v = by_venue.setdefault(r["venue_name"], {i: [0, 0] for i in range(1, 7)})
            v[lane][0] += 1
        overall[r["winner_lane"]][1] += 1
        by_venue[r["venue_name"]][r["winner_lane"]][1] += 1

    print("--- 実測コース別1着率（全場） ---")
    print(f"{'コース':>6} {'現行値':>8} {'実測':>8} {'件数':>7}")
    for lane in range(1, 7):
        n, w = overall[lane]
        actual = w / n if n else 0
        print(f"{lane:>6} {COURSE_BASE_WIN_RATE[lane]:>8.3f} {actual:>8.3f} {n:>7}")

    print("\n--- 場別1コース1着率 ---")
    for name, v in sorted(by_venue.items(), key=lambda x: -(x[1][1][1] / max(x[1][1][0], 1))):
        n, w = v[1]
        if n >= 12:
            print(f"  {name:<6} {w/n:>6.3f}  ({w}/{n})")


def _normalize(d):
    total = sum(d.values())
    return {k: v / total for k, v in d.items()} if total > 0 else {}


# 場別のコース勝率を素の実測値で使うと、1日分(1場12レース)では
# 偶然の偏りをそのまま学習してしまう。全場平均に引き寄せる縮小推定を行う。
# k は「全場平均をこの件数ぶんの観測とみなす」重み。場別の実測がk件を
# 大きく超えて初めて、場の個性が推定に反映される。
SHRINKAGE_K = 80


def _fit_course_rates(rows) -> dict:
    """
    渡された行だけから場別コース勝率を推定する。戻り値は course_rates.json と
    同じ形（global と venues）。

    評価から呼ぶときは学習側だけを渡すこと。全データを渡して同じデータを
    採点すると in-sample になる。
    """
    global_counts = {lane: [0, 0] for lane in range(1, 7)}
    venue_counts = {}
    for r in rows:
        v = venue_counts.setdefault(r["venue"], {lane: [0, 0] for lane in range(1, 7)})
        for lane in range(1, 7):
            global_counts[lane][0] += 1
            v[lane][0] += 1
        global_counts[r["winner_lane"]][1] += 1
        v[r["winner_lane"]][1] += 1

    global_rate = _normalize(
        {lane: (w / n if n else 0.0) for lane, (n, w) in global_counts.items()}
    )

    venues = {}
    for code, counts in venue_counts.items():
        raw = {}
        for lane, (n, w) in counts.items():
            prior = global_rate[lane]
            raw[lane] = (w + SHRINKAGE_K * prior) / (n + SHRINKAGE_K)
        venues[code] = {str(k): round(v, 4) for k, v in _normalize(raw).items()}

    return {
        "global": {str(k): round(v, 4) for k, v in global_rate.items()},
        "venues": venues,
    }


def _rates_for(table: dict, venue_code: str | None) -> dict[int, float]:
    """_fit_course_rates の出力から、その場で使う {コース: 1着率} を取り出す。"""
    t = (table.get("venues") or {}).get(venue_code) or table.get("global")
    if not t:
        return COURSE_BASE_WIN_RATE
    return {int(k): float(v) for k, v in t.items()}


def calibrate(start: str = None, end: str = None):
    """
    実測から場別コース勝率を推定し scraper/course_rates.json に書き出す。

    これは配備用。全データで取り直すのが正しい。優劣の判断に使ってはならず、
    判断は evaluate の分割（さらに採否は experiment.py）で行う。
    """
    rows = _load(start, end)
    if not rows:
        print("データがありません。先に collect を実行してください。")
        return

    fitted = _fit_course_rates(rows)

    out = {
        "generated_at": datetime.now().isoformat(),
        "races": len(rows),
        "shrinkage_k": SHRINKAGE_K,
        **fitted,
    }
    path = Path("scraper/course_rates.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{len(rows)}レースから較正し {path} に書き出しました。")
    print(f"全場コース別1着率: {out['global']}")
    if len(rows) < 1000:
        print(f"\n[注意] {len(rows)}レースは較正には少なすぎます。")
        print("       場別の推定は縮小推定でほぼ全場平均に寄っています。")
        print("       collect で日数を増やしてから再度 calibrate してください。")

    # 配備側 scoring.estimate_win_prob はこのファイルがあると場別の基準率を
    # オフセットに使う。一方 LOGIT_WEIGHTS を当てはめた experiment.py は
    # 固定の COURSE_BASE を使っている。このファイルを書いた時点で、
    # 「検証したモデル」と「配備されるモデル」の土台が入れ替わる。
    print("\n[重要] このファイルを置くと、配備側のオフセットが場別の基準率に変わる。")
    print("       LOGIT_WEIGHTS は固定の COURSE_BASE を土台に当てはめた係数なので、")
    print("       検証したモデルと配備されるモデルが別物になる。")
    print("       係数を当てはめ直して experiment.py で検証し直すこと。")



BEFORE_KEYS = ("weather", "temperature", "water_temp",
               "wind_speed", "wind_dir_code", "wave_height")


def enrich():
    """
    収集済みの各行に直前情報（展示タイム・チルト・気象）を足す。

    collect は出走表・オッズ・結果しか取っていない。この3つは前日までに
    確定している情報で、市場が持っている「当日の艇と水面の状態」を含まない。
    実験でモデルの形を条件付きロジットに変えても市場オッズとの差が
    ほとんど縮まらなかったので、足りないのは形ではなく情報だと考えられる。
    その仮説を検証するために直前情報を後付けする。

    既に conditions を持つ行は飛ばすので、中断しても再実行すれば続きから進む。
    """
    rows = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]
    todo = [r for r in rows if r.get("conditions") is None]
    print(f"{len(rows)}件のうち {len(todo)}件に直前情報を付ける")

    done = 0
    for row in todo:
        try:
            before = get_beforeinfo(row["date"], row["venue"], row["race_no"])
        except Exception as e:
            print(f"  ! {row['date']} {row['venue_name']} R{row['race_no']}: {e}")
            before = None

        # 取得できなかった行にも空dictを入れる。印が無いと再実行のたびに
        # 同じページを取りに行くことになる。
        row["conditions"] = {k: before[k] for k in BEFORE_KEYS} if before else {}
        if before:
            lane_map = {r["lane"]: r for r in before["racers"]}
            for racer in row["racers"]:
                bi = lane_map.get(racer["lane"])
                if bi:
                    for key in ("exhibit_time", "tilt"):
                        if bi.get(key) is not None:
                            racer[key] = bi[key]

        done += 1
        # 1件2秒かかるので全体では数十分になる。途中で止めても
        # やり直しにならないよう、こまめに書き戻す。
        if done % 50 == 0:
            _write_all(rows)
            print(f"  {done}/{len(todo)}件")

    _write_all(rows)
    got = sum(1 for r in rows if r.get("conditions"))
    print(f"付与完了: {done}件を処理 / 直前情報を持つ行は {got}/{len(rows)}件")


def _write_all(rows):
    with DATASET.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    cmd = args[0]
    start = args[1] if len(args) > 1 else None
    end = args[2] if len(args) > 2 else start
    if cmd == "collect":
        collect(start, end)
    elif cmd == "eval":
        evaluate(start, end)
    elif cmd == "calibrate":
        calibrate(start, end)
    elif cmd == "enrich":
        enrich()
    else:
        print(__doc__)
