"""
docs/article_market_deviation.md に書いた数値を再現するスクリプト。

公開する記事に数字を書く以上、あとから誰でも（自分を含めて）同じ数字を
出し直せる必要がある。記事の数値を直すときは、必ずこの出力から写すこと。

区切りは ±5pt / ±15pt。これは web の DIVERGING_SCALE(±30pt) とは別物で、
層別の境界として選んだもの。変えると記事の表の数字が全部変わる。

使い方:
  py -3 article_stats.py
"""
import io
import json
import math
import statistics
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

DATASET = Path("output/backtest.jsonl")
COURSE_BASE = {1: 0.55, 2: 0.145, 3: 0.12, 4: 0.105, 5: 0.055, 6: 0.025}
# 層の境界（1号艇の乖離、確率の差）。記事の表と同じ。
EDGES = [-9.0, -0.15, -0.05, 0.05, 0.15, 9.0]
BIG_PAYOUT = 10000


def load():
    rows = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if r.get("market_prob") and r.get("winner_lane")]


def rate(hits, n):
    """割合と標準誤差。nが小さい層で差を語らないために必ず併記する。"""
    p = hits / n if n else 0.0
    return p, math.sqrt(p * (1 - p) / n) if n else 0.0


def main():
    races = load()
    dates = sorted({r["date"] for r in races})
    print("レース数 %d / %d日間 (%s〜%s) / %d場"
          % (len(races), len(dates), dates[0], dates[-1], len({r["venue"] for r in races})))

    # 全艇の乖離の分布。±30pt の尺度を決めた根拠でもある。
    devs = sorted(
        abs(r["market_prob"][str(lane)] - COURSE_BASE[lane])
        for r in races for lane in range(1, 7)
        if r["market_prob"].get(str(lane)) is not None
    )
    n = len(devs)
    pct = lambda p: devs[int(p * n)] * 100
    print("延べ %d艇 / |乖離| 中央値 %.1fpt, 90%%点 %.1fpt, 95%%点 %.1fpt, ±30pt超 %.1f%%"
          % (n, pct(0.5), pct(0.9), pct(0.95), sum(1 for d in devs if d > 0.30) / n * 100))

    win_all, _ = rate(sum(1 for r in races if r["winner_lane"] == 1), len(races))
    payouts = [r["trifecta_payout"] for r in races if r.get("trifecta_payout")]
    print("1号艇1着率 %.1f%% / 三連単中央値 %d円 / 1万円超 %.1f%%"
          % (win_all * 100, statistics.median(payouts),
             sum(1 for p in payouts if p > BIG_PAYOUT) / len(payouts) * 100))

    print()
    print("%-16s %6s %8s %8s %10s" % ("1号艇の乖離", "n", "1着率", "配当中央値", "1万円超"))
    strata = []
    for lo, hi in zip(EDGES, EDGES[1:]):
        group = [r for r in races if lo <= r["market_prob"]["1"] - COURSE_BASE[1] < hi]
        pay = [r["trifecta_payout"] for r in group if r.get("trifecta_payout")]
        win = rate(sum(1 for r in group if r["winner_lane"] == 1), len(group))
        big = rate(sum(1 for p in pay if p > BIG_PAYOUT), len(pay))
        strata.append((win, big, len(group)))
        print("%6.0f 〜 %6.0f pt %6d %7.1f%% %8d円 %9.1f%%"
              % (lo * 100 if lo > -9 else -99, hi * 100 if hi < 9 else 99,
                 len(group), win[0] * 100, statistics.median(pay), big[0] * 100))

    # 両端の層の差。標準誤差の2倍を超えなければ差があるとは言わない。
    print()
    for label, idx in (("1着率", 0), ("1万円超", 1)):
        a, b = strata[0][idx], strata[-1][idx]
        diff = a[0] - b[0]
        se = math.sqrt(a[1] ** 2 + b[1] ** 2)
        print("両端の差 %-8s %+.1fpt (SE %.1fpt, %.1f倍) → %s"
              % (label, diff * 100, se * 100, abs(diff) / se,
                 "差があると言える" if abs(diff) > 2 * se else "差があるとは言えない"))


if __name__ == "__main__":
    main()
