"""
モデル改良の候補を、収集済みデータで比較する実験用スクリプト。

同じデータで較正して同じデータで評価すると成績は必ず良く見えるため、
日付で前半/後半に分けて「学習に使っていないレース」で比べる。
これをやらないと、ノイズへの過剰適合を改善と誤認する。

使い方:
  py -3 experiment.py
"""
import io
import json
import math
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

DATASET = Path("output/backtest.jsonl")

COURSE_BASE = {1: 0.55, 2: 0.145, 3: 0.12, 4: 0.105, 5: 0.055, 6: 0.025}

# 級別は選手の実力を表す最も強い単一指標だが、現行モデルは使っていない。
# 全国勝率と相関はあるが、勝率は出走数の少ない選手ほどぶれるため、
# 級別が独立した情報を持つ可能性がある。
CLASS_STRENGTH = {"A1": 1.0, "A2": 0.72, "B1": 0.5, "B2": 0.35}


def load():
    rows = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _mean(values):
    valid = [v for v in values if v and v > 0]
    return sum(valid) / len(valid) if valid else 0.0


def _ratio(value, mean, lo=0.5, hi=2.0):
    if not value or not mean or value <= 0 or mean <= 0:
        return 1.0
    return min(max(value / mean, lo), hi)


def _normalize(d):
    total = sum(d.values())
    return {k: v / total for k, v in d.items()} if total > 0 else {}


def make_model(w_racer=1.0, w_motor=0.5, w_st=0.5, w_class=0.0, w_venue=0.0):
    """重みを指定してモデル関数を作る。"""
    def predict(row):
        racers = row["racers"]
        if not racers:
            return {}
        mean_win = _mean([r.get("win_rate_all", 0) for r in racers])
        mean_motor = _mean([r.get("motor_in2_rate", 0) for r in racers])
        mean_st = _mean([r.get("avg_st", 0) for r in racers])
        mean_venue = _mean([r.get("win_rate_venue", 0) for r in racers])
        mean_class = _mean([CLASS_STRENGTH.get(r.get("class"), 0.5) for r in racers])

        raw = {}
        for r in racers:
            score = COURSE_BASE.get(r["lane"], 0.05)
            score *= _ratio(r.get("win_rate_all", 0), mean_win) ** w_racer
            score *= _ratio(r.get("motor_in2_rate", 0), mean_motor) ** w_motor
            score *= _ratio(mean_st, r.get("avg_st", 0)) ** w_st
            if w_class:
                score *= _ratio(CLASS_STRENGTH.get(r.get("class"), 0.5), mean_class) ** w_class
            if w_venue:
                score *= _ratio(r.get("win_rate_venue", 0), mean_venue) ** w_venue
            raw[r["lane"]] = score
        return _normalize(raw)
    return predict


def market(row):
    return {int(k): v for k, v in row["market_prob"].items()}


def course_only(row):
    return _normalize({r["lane"]: COURSE_BASE.get(r["lane"], 0.05) for r in row["racers"]})


def per_race_logloss(rows, predict) -> list[float]:
    """レースごとの -log(勝者の予測確率)。対応のある比較に使う。"""
    out = []
    for row in rows:
        probs = predict(row)
        if not probs:
            out.append(None)
            continue
        p = max(probs.get(row["winner_lane"], 1e-6), 1e-6)
        out.append(-math.log(p))
    return out


def score(rows, predict):
    ll = brier = 0.0
    hits = n = 0
    for row in rows:
        probs = predict(row)
        if not probs:
            continue
        w = row["winner_lane"]
        p = max(probs.get(w, 1e-6), 1e-6)
        ll += -math.log(p)
        brier += sum((probs.get(l, 0) - (1 if l == w else 0)) ** 2 for l in range(1, 7))
        if max(probs, key=probs.get) == w:
            hits += 1
        n += 1
    return (ll / n, brier / n, hits / n, n) if n else (0, 0, 0, 0)


def paired_diff(rows, predict_a, predict_b) -> tuple[float, float, int]:
    """
    同じレース群で2つの予測器のLogLossを対応づけて比較する。

    2つのモデルは同じレース・同じ勝者を見ているため誤差が強く相関する。
    それぞれの平均LogLossの標準誤差から差の有意性を判断すると、
    相関を無視するぶん閾値を過大に見積もり、本当は意味のある改善を
    誤差として切り捨ててしまう。差の分布そのものを見る必要がある。

    戻り値: (平均差 a-b, 差の標準誤差, 件数)
    """
    a = per_race_logloss(rows, predict_a)
    b = per_race_logloss(rows, predict_b)
    diffs = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    n = len(diffs)
    if n < 2:
        return 0.0, 0.0, n
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    return mean, math.sqrt(var / n), n


def split_by_date(rows):
    """
    日付で前半(学習)と後半(検証)に分ける。
    候補の優劣は必ず検証側で判断する。学習側の成績は、そのデータに
    合わせて選んだぶんだけ良く出るため、比較の根拠にならない。
    """
    dates = sorted({r["date"] for r in rows})
    if len(dates) < 2:
        return rows, []
    cut = dates[len(dates) // 2]
    train = [r for r in rows if r["date"] < cut]
    test = [r for r in rows if r["date"] >= cut]
    return train, test


def main():
    rows = load()
    if not rows:
        print("データがありません。backtest.py collect を先に実行してください。")
        return

    train, test = split_by_date(rows)
    print(f"全{len(rows)}レース (学習{len(train)} / 検証{len(test)})\n")

    candidates = {
        "市場オッズ":            market,
        "コース基準のみ":         course_only,
        "現行モデル":            make_model(),
        "+級別":               make_model(w_class=1.0),
        "+級別(強)":            make_model(w_class=2.0),
        "+級別 -勝率":          make_model(w_racer=0.0, w_class=2.0),
        "+級別 +当地":          make_model(w_class=1.0, w_venue=0.5),
        "モーター無し":          make_model(w_motor=0.0, w_class=1.0),
        "ST無し":              make_model(w_st=0.0, w_class=1.0),
    }

    if not test:
        print("[警告] 1日分しかないため学習/検証に分割できない。")
        print("       以下は全データでの成績であり、候補の優劣を判断する根拠にならない。\n")
        _table(rows, candidates, "全データ")
        _noise_note(len(rows))
        return

    _table(train, candidates, f"学習 {len(train)}レース (参考)")
    _table(test, candidates, f"検証 {len(test)}レース (こちらで判断する)")
    _noise_note(len(test))


def _table(rows, candidates, label):
    print(f"--- {label} ---")
    print(f"{'予測器':<16} {'LogLoss':>9} {'Brier':>9} {'的中率':>8}")
    print("-" * 46)
    results = {}
    for name, fn in candidates.items():
        ll, brier, hit, n = score(rows, fn)
        results[name] = ll
        print(f"{name:<16} {ll:>9.4f} {brier:>9.4f} {hit:>7.1%}")

    print()
    _paired_table(rows, candidates, "現行モデル")
    # 級別を入れた時点を基準に取り直す。現行モデル基準のままだと
    # 「モーターを外した」効果に級別追加の効果が混ざり、
    # 外したこと自体が効いたように見えてしまう。
    _paired_table(rows, candidates, "+級別")


def _paired_table(rows, candidates, ref_name):
    """
    指定した基準モデルと各候補の差を、対応のある比較で示す。
    差がその標準誤差の2倍を超えて初めて「効いている」と言える。
    """
    baseline = candidates.get(ref_name)
    if baseline is None:
        return

    print(f"  {ref_name}との差（対応のある比較、マイナスが改善）")
    print(f"  {'候補':<16} {'差':>9} {'±SE':>8} {'判定':>10}")
    print("  " + "-" * 46)
    for name, fn in candidates.items():
        if name == ref_name:
            continue
        diff, se, n = paired_diff(rows, fn, baseline)
        if n < 2:
            continue
        if se == 0:
            verdict = "-"
        elif abs(diff) < 2 * se:
            verdict = "誤差の範囲"
        else:
            verdict = "改善" if diff < 0 else "悪化"
        print(f"  {name:<16} {diff:>+9.4f} {se:>8.4f} {verdict:>10}")
    print()


def _noise_note(n: int):
    print(f"[判断の目安] 候補の採否は上の対応のある比較で判断する。")
    print(f"       差が標準誤差の2倍を超えなければ優劣は言えない。")
    print(f"       誤差に埋もれるうちは、単純なほうを採ること。")


if __name__ == "__main__":
    main()
