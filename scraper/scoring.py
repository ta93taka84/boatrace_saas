"""
出走表データから各艇の勝率を推定し、市場オッズと比較して期待値を算出する。

考え方:
  市場勝率だけでは期待値は出せない（定義上どの艇も控除率ぶんのマイナスになる）。
  独立した予測勝率 model_prob を作り、市場が過小評価している艇を探す。

  EV = model_prob / market_prob * (1 - 控除率)
  EV > 1.0 なら理論上プラス期待値。
"""
import json
from pathlib import Path

# バックテストでモデルが市場オッズを上回るまで False。
# False の間、EVは参考値であり賭けの根拠にしてはならない。
CALIBRATED = False

TAKEOUT_RATE = 0.25
THEORETICAL_RETURN = 1.0 - TAKEOUT_RATE

# コース別1着率のベースライン（全場平均の概算値）。
# backtest.py calibrate が scraper/course_rates.json を作ると、
# 実測から縮小推定した値が優先される。
COURSE_BASE_WIN_RATE = {1: 0.55, 2: 0.145, 3: 0.12, 4: 0.105, 5: 0.055, 6: 0.025}

_RATES_PATH = Path(__file__).with_name("course_rates.json")
_rates_cache = None


def _load_rates() -> dict | None:
    global _rates_cache
    if _rates_cache is None:
        if not _RATES_PATH.exists():
            _rates_cache = {}
        else:
            _rates_cache = json.loads(_RATES_PATH.read_text(encoding="utf-8"))
    return _rates_cache or None


def course_rates(venue_code: str | None = None) -> dict[int, float]:
    """
    使うコース別1着率を返す。較正済みファイルがあればそれを、
    無ければ組み込みの概算値を使う。場別が無い場合は全場平均に落とす。
    """
    rates = _load_rates()
    if not rates:
        return COURSE_BASE_WIN_RATE

    table = None
    if venue_code:
        table = rates.get("venues", {}).get(venue_code)
    table = table or rates.get("global")
    if not table:
        return COURSE_BASE_WIN_RATE

    return {int(k): float(v) for k, v in table.items()}


# 各補正の効き具合。
#
# W_CLASS は144レースの検証で LogLoss を 1.323 -> 1.266 に改善した。
# 誤差水準(約0.02)を大きく超えるため「級別が効く」ことは確かだが、
# 重み2.0のほうが数値上はわずかに良かったものの、その差は誤差の範囲。
# データに合わせて選ぶと過剰適合になるので控えめな1.0を採る。
# 他の重みはバックテスト未実施の暫定値であり、要キャリブレーション。
W_RACER = 1.0   # 全国勝率
W_MOTOR = 0.5   # モーター2連対率
W_ST = 0.5      # 平均スタートタイミング
W_CLASS = 1.0   # 級別（A1/A2/B1/B2）

# 級別を数値化した相対強度。等級の実力差の目安。
CLASS_STRENGTH = {"A1": 1.0, "A2": 0.72, "B1": 0.5, "B2": 0.35}


def score_race(racers: list[dict], market_prob: dict[int, float] | None,
               venue_code: str | None = None) -> dict:
    """
    戻り値:
    {
      "model_prob": {1: 0.52, ...},   # 推定勝率（合計1.0）
      "ev": {1: 1.03, ...},            # 期待値（1.0超で理論上プラス）
      "top_lane": 3,                   # 最高EVの艇番
      "top_ev": 1.21,
    }
    market_prob が無い場合は ev を空で返す。
    """
    model_prob = estimate_win_prob(racers, venue_code)
    if not model_prob:
        return {}

    result = {"model_prob": model_prob}

    if market_prob:
        ev = {}
        for lane, mp in model_prob.items():
            market = market_prob.get(lane, 0.0)
            if market > 0:
                ev[lane] = round(mp / market * THEORETICAL_RETURN, 3)
        if ev:
            top_lane = max(ev, key=ev.get)
            result.update({"ev": ev, "top_lane": top_lane, "top_ev": ev[top_lane]})

    return result


def estimate_win_prob(racers: list[dict], venue_code: str | None = None) -> dict[int, float]:
    """コース別ベースラインに選手・モーター・STの相対補正を掛けて正規化する。"""
    if not racers:
        return {}

    # 進入固定外でコースが入れ替わる場合は actual_course を優先
    def course_of(r):
        return r.get("actual_course") or r["lane"]

    mean_win = _mean([r.get("win_rate_all", 0) for r in racers])
    mean_motor = _mean([r.get("motor_in2_rate", 0) for r in racers])
    mean_st = _mean([r.get("avg_st", 0) for r in racers])
    mean_class = _mean([CLASS_STRENGTH.get(r.get("class"), 0.5) for r in racers])

    base_rates = course_rates(venue_code)
    raw = {}
    for r in racers:
        base = base_rates.get(course_of(r), 0.05)
        score = base
        score *= _ratio(r.get("win_rate_all", 0), mean_win) ** W_RACER
        score *= _ratio(r.get("motor_in2_rate", 0), mean_motor) ** W_MOTOR
        # STは小さいほど良いので比を反転
        score *= _ratio(mean_st, r.get("avg_st", 0)) ** W_ST
        score *= _ratio(CLASS_STRENGTH.get(r.get("class"), 0.5), mean_class) ** W_CLASS
        raw[r["lane"]] = score

    total = sum(raw.values())
    if total <= 0:
        return {}

    return {lane: round(v / total, 4) for lane, v in raw.items()}


def _mean(values: list[float]) -> float:
    valid = [v for v in values if v and v > 0]
    return sum(valid) / len(valid) if valid else 0.0


def _ratio(value: float, mean: float) -> float:
    """平均比。データ欠損時は補正なし(1.0)に落とす。極端な値は 0.5〜2.0 に丸める。"""
    if not value or not mean or value <= 0 or mean <= 0:
        return 1.0
    return min(max(value / mean, 0.5), 2.0)
