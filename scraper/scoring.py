"""
出走表と直前情報から各艇の勝率を推定し、市場オッズと比較して期待値を算出する。

考え方:
  市場勝率だけでは期待値は出せない（定義上どの艇も控除率ぶんのマイナスになる）。
  独立した予測勝率 model_prob を作り、市場が過小評価している艇を探す。

  EV = model_prob / market_prob * (1 - 控除率)
  EV > 1.0 なら理論上プラス期待値。
"""
import json
import math
from pathlib import Path

# バックテストでモデルが市場オッズを上回るまで False。
# False の間、EVは参考値であり賭けの根拠にしてはならない。
#
# 現状: 検証612レースで LogLoss 1.2661 に対し市場は 1.1671。
# 対応のある比較で -0.0989 ± 0.015 程度、まだ明確に負けている。
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


# 級別を数値化した相対強度。等級の実力差の目安。
CLASS_STRENGTH = {"A1": 1.0, "A2": 0.72, "B1": 0.5, "B2": 0.35}


# ---------------------------------------------------------------- 予測モデル
#
# 6艇のうち1着が1つ選ばれる構造なので、条件付きロジット（レース内ソフトマックス）
# で推定する。
#
#   P(i が1着) ∝ コース別1着率(i) × exp(Σ 特徴量(i)の偏差 × 重み)
#
# 特徴量はレース内で中心化する。レース間の絶対水準ではなく、同じレースに出ている
# 6人の中での相対差だけが勝敗を決めるため。コース効果はオフセットに固定し、
# データからは学ばせない（実測への置き換えは改善しなかった＝ノイズを拾うだけ）。
#
# 以前は「平均比の累乗を手で決めた重みで掛ける」形だった。最尤で当てはめ直しても
# 差は -0.0104 ± 0.0074 で誤差の範囲、つまり形は問題ではなかった。効いたのは
# 当日の情報を足したこと。
#
#   出走表だけの当てはめ    -0.0104 ± 0.0074   誤差の範囲
#   ＋展示タイム           -0.0135 ± 0.0086   誤差の範囲
#   ＋展示・チルト・気象     -0.0229 ± 0.0094   改善      ← これを採用
#
# 分割位置を5通りに変えても符号と大きさが安定していたので、多重比較で
# たまたま拾った差ではない。学習データが増えるほど差は広がった。
#
# 係数は標準偏差で割る前の生の値に対する重み（当てはめ時の係数÷尺度）。
# 全1236レースで当てはめ直した値。判断は日付で分けた検証側で行い、
# 配備するときだけ全データで取り直す。
#
# 注意: wind_inner は当てはめ直すと符号が反転する程度に小さく、
#       in2_rate_all はほぼ0。どちらも寄与は無いに等しい。データが増えた
#       段階で外すかどうかを判断すること。今は検証した構成のまま出す。
LOGIT_WEIGHTS = {
    "win_rate_all":   0.361216,
    "class":          0.683208,
    "win_rate_venue": 0.102112,
    "st":             8.232190,   # 平均STは値の幅が0.02秒程度なので重みが大きく出る
    "motor_in2_rate": 0.013806,
    "boat_in2_rate":  0.003394,
    "weight":        -0.041846,   # 重いほど不利
    "f_count":       -0.223917,   # フライング歴はスタートを慎重にさせる
    "in2_rate_all":   0.000332,
    "exhibit":        3.530421,   # 展示タイム（速いほど有利になる向きに符号反転済み）
    "tilt":           0.180521,
    "wind_inner":    -0.019717,   # 風×1号艇
    "wave_inner":    -0.049856,   # 波高×1号艇。荒れると内枠の優位が削られる
}

# 0が「欠損」ではなく正当な値である特徴量。
# F回数0は「フライング歴が無い」という情報であって、欠測ではない。
# ここを取り違えると、きれいな選手が全員「平均並み」に潰れて信号が消える。
# 風と波の交互作用も、内枠以外は定義上0になる。
ZERO_IS_VALID = {"tilt", "f_count", "wind_inner", "wave_inner"}


def _feature(racer: dict, name: str, conditions: dict | None) -> float:
    """1艇ぶんの特徴量。大きいほど有利になる向きに符号を揃える。"""
    if name == "class":
        return CLASS_STRENGTH.get(racer.get("class"), 0.5)
    if name == "st":
        # 平均STは小さいほど良いので符号を反転する
        return -(racer.get("avg_st") or 0.0)
    if name == "exhibit":
        # 展示タイムも小さいほど速い
        return -(racer.get("exhibit_time") or 0.0)
    if name in ("wind_inner", "wave_inner"):
        # 風と波は1レースで共通の値なので、そのままでは正規化で打ち消し合って
        # 何も効かない。効くとすれば「荒れると内枠の優位が削られる」という形なので、
        # 1号艇との交互作用として入れる。
        if racer["lane"] != 1:
            return 0.0
        cond = conditions or {}
        key = "wind_speed" if name == "wind_inner" else "wave_height"
        return cond.get(key) or 0.0
    return racer.get(name) or 0.0


def score_race(racers: list[dict], market_prob: dict[int, float] | None,
               venue_code: str | None = None,
               conditions: dict | None = None) -> dict:
    """
    戻り値:
    {
      "model_prob": {1: 0.52, ...},   # 推定勝率（合計1.0）
      "ev": {1: 1.03, ...},            # 期待値（1.0超で理論上プラス）
      "top_lane": 3,                   # 最高EVの艇番
      "top_ev": 1.21,
    }
    market_prob が無い場合は ev を空で返す。
    conditions（気象）が無い場合は風と波の項が落ちるだけで、他はそのまま効く。
    """
    model_prob = estimate_win_prob(racers, venue_code, conditions)
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


def estimate_win_prob(racers: list[dict], venue_code: str | None = None,
                      conditions: dict | None = None) -> dict[int, float]:
    """コース別1着率を土台に、レース内で中心化した特徴量の重み付き和で補正する。"""
    if not racers:
        return {}

    # 進入固定外でコースが入れ替わる場合は actual_course を優先
    def course_of(r):
        return r.get("actual_course") or r["lane"]

    # レース内での偏差を取る。欠損は平均に置き換える＝その艇だけ補正なしになる。
    deviations = {}
    for name in LOGIT_WEIGHTS:
        values = [_feature(r, name, conditions) for r in racers]
        if name in ZERO_IS_VALID:
            mean = sum(values) / len(values)
        else:
            present = [v for v in values if v]
            mean = sum(present) / len(present) if present else 0.0
            values = [v if v else mean for v in values]
        deviations[name] = [v - mean for v in values]

    base_rates = course_rates(venue_code)
    utilities = []
    for i, r in enumerate(racers):
        base = max(base_rates.get(course_of(r), 0.05), 1e-6)
        u = math.log(base)
        for name, weight in LOGIT_WEIGHTS.items():
            u += deviations[name][i] * weight
        utilities.append(u)

    # exp の桁あふれを避けるため最大値を引いてから指数を取る
    top = max(utilities)
    exps = [math.exp(u - top) for u in utilities]
    total = sum(exps)
    if total <= 0:
        return {}

    return {r["lane"]: round(exps[i] / total, 4) for i, r in enumerate(racers)}
