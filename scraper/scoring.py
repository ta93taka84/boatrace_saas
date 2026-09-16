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

# 公開する確率を、市場オッズへどれだけ引き戻すか。
# 0.0 なら市場そのまま、1.0 ならモデル単独。
#
# なぜ要るか。三連単のEVは (公開確率 / 市場確率) / 1.335 なので、市場より33%多く
# 確率を置いた買い目はEV1.0を超える。モデル単独（w=1.0）だと市場との1着確率の
# 食い違いが中央値18.3ptあり、推奨1位のEVが軒並み2〜5倍になっていた。
# **その乖離は市場の見落としではなくこちらのずれである。** 三連単の的中目で
# 採点すると、モデル単独は市場に +0.3833 ± 0.0428 で負けている。
#
# 重みごとの検証成績。表示しているのは三連単なので、そちらで決めた。
# 日付で学習と検証に分け、検証1,067レースを採点している（全2,436レース、
# 2026-08-25〜09-10）。データを1,440→2,436レースに増やしても選ばれる点は動かなかった。
#
# **2026-09-11 に測り直した。** 三連単の展開へ着順相関の補正を入れたので、
# 以前の表（着順相関なし）とは別物になっている。同じ検証1,067レースで比べると、
# モデル単独の市場との差は +0.3422 → +0.2104 に縮んだ。
#
#   w     三連単LogLoss  市場との差         補正なしの差        m/k=4 の買い目のEV
#   0.0     3.7043       —                  —                   0.75
#   0.1     3.7041       -0.0002 ± 0.0019   -0.0003 ± 0.0023    0.97
#   0.2     3.7076       +0.0033 ± 0.0037   +0.0048 ± 0.0045    1.20   ← 採用
#   0.3     3.7146       +0.0103 ± 0.0055   +0.0147 ± 0.0066    1.42
#   0.5     3.7390       +0.0347 ± 0.0091   +0.0495 ± 0.0108    1.87
#   1.0     3.9147       +0.2104 ± 0.0241   +0.3422 ± 0.0324    3.00   ← 9/7まではここ
#
# **補正を入れたことで上限は 0.3 まで動いたが、0.2 に据え置いた。** 0.3 の差は
# 標準誤差の1.9倍で境目ぎりぎりであり、学習側で選ばせると相変わらず 0.00、
# つまりデータは「混ぜるな」と言っている。0.2 と 0.3 のどちらが良いかを示す
# 証拠は無く、違うのは画面に出る期待値の大きさだけなので、市場に近いほうを採る。
# 0 にしないのは、AI予想を出すという製品の決定があるため。ここは精度の主張では
# なく、**どこまで市場から離れてよいかの上限**として置いている。
#
# **どの w でも推奨買い目の並び順は変わらない。** EVは (モデル確率/市場確率) の
# 単調増加なので、w は目盛りを決めるだけで順位を動かさない。
#
# **三連複にも同じ w を使う（2026-09-16 に確認）。** 券種ごとに別の重みを置く
# 理由があるかを `experiment.py` の `trio_blend_check`（trifecta_blend_check と
# 同じ実行で出る）で測った。検証1067レース。
#
#   w     三連複LogLoss  市場との差          三連単での差（比較用）
#   0.0     2.2931       —                   —
#   0.1     2.2921       -0.0010 ± 0.0015    -0.0002 ± 0.0019
#   0.2     2.2934       +0.0003 ± 0.0030    +0.0033 ± 0.0037   ← 採用
#   0.4     2.3033       +0.0102 ± 0.0060    +0.0207 ± 0.0073
#   0.5     2.3121       +0.0190 ± 0.0076    +0.0347 ± 0.0091
#   1.0     2.4334       +0.1403 ± 0.0208    +0.2104 ± 0.0241
#
# 三連複のほうが市場から離れても傷が浅い（上限は 0.4 まで誤差の範囲）。的が
# 20通りしかないぶん着順の読み違いが効かないためで、モデルが良くなった
# わけではない。**ゆるいほうに合わせて w を上げないこと。** 同じ model_prob
# から両方を作っている以上、券種ごとに重みを変えると、画面上で同じレースの
# 同じ3艇に2つの異なる確率が並ぶ。0.2 は三連複でも 0.1倍SE と市場並みなので、
# 揃えておいて失うものが無い。
BLEND_WEIGHT = 0.2

# 推奨買い目として出す三連単の本数。
# 120通りのうちEVの高い順に切る。増やすほど「どれかは当たる」に近づいて
# 見かけの的中率が上がるので、本数を増やして成績を良く見せないこと。
TRIFECTA_PICKS = 5

# 推奨買い目として出す三連複の本数。
# **三連単と同じ5本にしていない。** 的が20通りしかないので、5本は場の4分の1に
# あたる。三連単の5本（120通りのうち4%）と同じ「5本」という見た目で並べると、
# 張る範囲の広さの違いが隠れる。
#
# なお**「三連複のほうが当たりやすいから本数を減らした」ではない。** 推奨は
# EV順に切るので、選ばれるのは確率の高い目ではなく、オッズに対して確率が高い
# 目である。実際、推奨に入った目の確率の合計は三連単5本と三連複3本でほぼ
# 同じだった（ある1レースで 0.029 と 0.031）。「三連複は当たりやすい」が
# 効くのは同じ3艇どうしを比べたときで（trio_probs は三連単6通りの和なので
# 必ず大きい）、推奨の並びどうしの比較ではない。
# いずれにせよ画面では的中しやすさではなく期待値で比べさせること。
TRIO_PICKS = 3

# コース別1着率のベースライン（全場平均の概算値）。
# backtest.py calibrate が scraper/course_rates.json を作ると、
# 実測から縮小推定した値が優先される。
COURSE_BASE_WIN_RATE = {1: 0.55, 2: 0.145, 3: 0.12, 4: 0.105, 5: 0.055, 6: 0.025}

_RATES_PATH = Path(__file__).with_name("course_rates.json")
_rates_cache = None

# 三連単の着順相関の補正表。experiment.py fit-order が書き出す。
# 無ければ空の表になり、展開は補正なしの Plackett-Luce に戻るだけ。
_ORDER_PATH = Path(__file__).with_name("order_corr.json")
_order_cache = None


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


def order_corr() -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
    """
    着順の結びつきの補正表を (2着, 3着) で返す。ファイルが無ければ空の表。

    値は「実測回数 ÷ 独立な展開が与える期待回数」で、1.0なら偏り無し。
    作るのは experiment.py の order_correlation で、配備用に全データから
    取り直すのが `py -3 experiment.py fit-order`。
    """
    global _order_cache
    if _order_cache is None:
        data = {}
        if _ORDER_PATH.exists():
            data = json.loads(_ORDER_PATH.read_text(encoding="utf-8"))

        def table(key):
            out = {}
            for k, v in (data.get(key) or {}).items():
                a, b = k.split("-")
                out[(int(a), int(b))] = float(v)
            return out

        _order_cache = (table("second"), table("third"))
    return _order_cache


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
# **全2,304レース（15日分）で当てはめ直した値。** 判断は日付で分けた検証側で
# 行い、配備するときだけ全データで取り直す。
#
# 2026-09-09 に2つ落とした。以前ここには「wind_inner は当てはめ直すと符号が
# 反転する程度に小さく、in2_rate_all はほぼ0。データが増えた段階で外すかを
# 判断すること」と書いてあった。増えたので判断した。
#
#   -wind_inner      +0.0001 ± 0.0002   誤差の範囲
#   -in2_rate_all    -0.0001 ± 0.0001   誤差の範囲
#   両方外す          +0.0000 ± 0.0003   誤差の範囲
#
# 分割位置を12通りに変えても差は出ない。**誤差に埋もれるなら単純なほうを採る。**
# 実際 wind_inner は2,304レースで当てはめると符号が正に反転しており、風が
# 内枠を助けることになってしまう。信号ではなくノイズだったということ。
# 風そのものは wave_inner（波高×1号艇）が拾っている範囲で残る。
LOGIT_WEIGHTS = {
    "win_rate_all":   0.387559,
    "class":          0.747547,
    "win_rate_venue": 0.081985,
    "st":             7.003693,   # 平均STは値の幅が0.02秒程度なので重みが大きく出る
    "motor_in2_rate": 0.009584,
    "boat_in2_rate":  0.005019,
    "weight":        -0.023938,   # 重いほど不利
    "f_count":       -0.199781,   # フライング歴はスタートを慎重にさせる
    "exhibit":        4.137795,   # 展示タイム（速いほど有利になる向きに符号反転済み）
    "tilt":           0.187405,
    "wave_inner":    -0.050026,   # 波高×1号艇。荒れると内枠の優位が削られる
}

# 0が「欠損」ではなく正当な値である特徴量。
# F回数0は「フライング歴が無い」という情報であって、欠測ではない。
# ここを取り違えると、きれいな選手が全員「平均並み」に潰れて信号が消える。
# 風と波の交互作用も、内枠以外は定義上0になる。
ZERO_IS_VALID = {"tilt", "f_count", "wave_inner"}


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
               conditions: dict | None = None,
               trifecta_odds: dict[str, float] | None = None,
               trio_odds: dict[str, float] | None = None) -> dict:
    """
    戻り値:
    {
      "model_prob": {1: 0.52, ...},   # 推定勝率（合計1.0）
      "ev": {1: 1.03, ...},            # 期待値（1.0超で理論上プラス）
      "top_lane": 3,                   # 最高EVの艇番
      "top_ev": 1.21,
      "picks": [{"combo": "1-3-5", "prob": 0.041, "odds": 29.5, "ev": 1.21}, ...],
      "trio_picks": [{"combo": "1-3-5", "prob": 0.15, "odds": 7.8, "ev": 1.17}, ...],
    }
    market_prob が無い場合は ev を空で返す。
    trifecta_odds（三連単120通り）が無い場合は picks を返さない。
    trio_odds（三連複20通り）が無い場合は trio_picks を返さない。
    三連単のオッズだけが取れて三連複が取れなかった場合は、picks だけが出る。
    片方の取得失敗でもう片方を落とさないこと。
    conditions（気象）が無い場合は風と波の項が落ちるだけで、他はそのまま効く。
    """
    model_prob = estimate_win_prob(racers, venue_code, conditions)
    if not model_prob:
        return {}

    result = {"model_prob": model_prob}

    # 公開する確率。市場オッズが無い時間帯はモデル単独のまま出すしかない。
    pub_prob = (blend_with_market(model_prob, market_prob, BLEND_WEIGHT)
                if market_prob else model_prob)
    result["pub_prob"] = pub_prob
    result["blend_weight"] = BLEND_WEIGHT

    if market_prob:
        ev = {}
        for lane, mp in pub_prob.items():
            market = market_prob.get(lane, 0.0)
            if market > 0:
                ev[lane] = round(mp / market * THEORETICAL_RETURN, 3)
        if ev:
            top_lane = max(ev, key=ev.get)
            result.update({"ev": ev, "top_lane": top_lane, "top_ev": ev[top_lane]})

    if trifecta_odds:
        picks = recommend_trifecta(model_prob, trifecta_odds, weight=BLEND_WEIGHT)
        if picks:
            result["picks"] = picks

    if trio_odds:
        trio = recommend_trio(model_prob, trio_odds, weight=BLEND_WEIGHT)
        if trio:
            result["trio_picks"] = trio

    return result


def trifecta_probs(model_prob: dict[int, float],
                   corr: tuple[dict, dict] | None = None) -> dict[str, float]:
    """
    1着確率から三連単120通りの確率を組み、着順の結びつきで補正する。

        P(a⇒b⇒c) = p_a × p_b/(1-p_a) × p_c/(1-p_a-p_b) × r2(a,b) × r3(b,c)

    この式が使えるのは、model_prob をレース内ソフトマックス（条件付きロジット）
    で作っているからである。各艇に強さ s_i があって P(iが1着) = s_i / Σs という形なので、
    1着を抜いた残り5艇に同じ式を当てればそのまま2着の確率になる。
    モデルを作り直さず、既に検証した強さをそのまま展開に使える。

    掛け算だけの展開は着順の相関を持たない。実際には「外が勝つときは外が続き、
    内が沈む」というまくりの道連れがあり、4号艇が1着のとき2着に6号艇が来る目は
    独立な展開の2.92倍、逆に1号艇が来る目は0.59倍だった。その偏りを実測から作った
    表で換算する。分割6通りすべてで改善し、効果は標準誤差の6〜10倍あった
    （experiment.py の `rolling_check_order_correlation`）。

    corr を渡さなければ配備用の表（order_corr()）を使う。**検証から呼ぶときは
    必ず学習側だけから作った表を明示的に渡すこと。** 配備用の表は全データの
    着順から作られているので、それを検証側の採点に使うと答えを見て答え合わせをする
    ことになる。補正を外した素の展開が欲しいときは `({}, {})` を渡す。
    """
    r2, r3 = corr if corr is not None else order_corr()
    lanes = sorted(model_prob)
    out = {}
    for a in lanes:
        pa = model_prob[a]
        rest_a = 1.0 - pa
        if rest_a <= 1e-9:
            continue
        group = {}
        for b in lanes:
            if b == a:
                continue
            rest_b = rest_a - model_prob[b]
            if rest_b <= 1e-9:
                continue
            pb = model_prob[b] / rest_a
            for c in lanes:
                if c == a or c == b:
                    continue
                group[f"{a}-{b}-{c}"] = (pb * (model_prob[c] / rest_b)
                                         * r2.get((a, b), 1.0)
                                         * r3.get((b, c), 1.0))
        # **正規化は1着ごとに行う。** 補正は合計を崩すので均し直しが要るが、
        # 全体で一度に均すと1着の確率まで動いてしまい、画面に出している
        # 勝率と三連単が食い違う。1着ごとに均せば、2着以降の形だけが変わって
        # 1着の確率はモデルのまま残る。成績もこちらが良かった
        # （分割6通りで符号が揃い、4通りで標準誤差の2倍を超える）。
        total = sum(group.values())
        if total <= 0:
            continue
        for combo, v in group.items():
            out[combo] = v / total * pa

    total = sum(out.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in out.items()}


def trio_probs(model_prob: dict[int, float],
               corr: tuple[dict, dict] | None = None) -> dict[str, float]:
    """
    三連複20通りの確率を、三連単120通りから畳んで作る。

        P({a,b,c}) = Σ P(a⇒b⇒c) （6通りの並べ替えすべての和）

    **これは近似ではなく厳密な変換である。** 着順を問わない事象は、着順を
    区別した事象の排反な和そのものなので、三連単の分布が正しければ三連複の
    分布も同じだけ正しい。したがって三連複のためにモデルを作り直す必要はなく、
    検証済みの trifecta_probs（着順相関の補正込み）をそのまま使える。

    corr の扱いは trifecta_probs と同じ。検証から呼ぶときは学習側だけから
    作った表を明示的に渡すこと。
    """
    out: dict[str, float] = {}
    for combo, p in trifecta_probs(model_prob, corr).items():
        key = "-".join(sorted(combo.split("-"), key=int))
        out[key] = out.get(key, 0.0) + p
    return out


def blend_with_market(model_prob: dict[int, float],
                      market_prob: dict[int, float],
                      weight: float) -> dict[int, float]:
    """
    公開する確率を作る。市場とモデルの線形混合。

        p = (1-w)·市場 + w·モデル

    対数線形の混合（幾何平均）も検証したが、選ばれる重みも成績も同じだった。
    線形のほうが「市場から何割動かしたか」として読めるので、こちらを採る。
    """
    lanes = set(model_prob) | set(market_prob)
    out = {l: (1 - weight) * market_prob.get(l, 0.0)
              + weight * model_prob.get(l, 0.0) for l in lanes}
    total = sum(out.values())
    if total <= 0:
        return dict(model_prob)
    return {l: round(v / total, 4) for l, v in out.items()}


def recommend_trifecta(model_prob: dict[int, float],
                       trifecta_odds: dict[str, float],
                       limit: int = TRIFECTA_PICKS,
                       weight: float = 1.0) -> list[dict]:
    """
    三連単のオッズと照らし合わせて、EVの高い順に買い目を返す。

        EV = 公開確率 × 三連単オッズ

    1着のEV（予測勝率 / 市場勝率 × 0.75）とは式が違うことに注意。
    オッズには控除率が既に含まれているので、ここで THEORETICAL_RETURN を
    掛けると二重に引くことになる。

    weight を1.0未満にすると、各買い目の確率を市場のオッズが示す確率へ
    引き戻す。**引き戻しは三連単の目の単位で行う。** 1着の確率だけを混ぜて
    そこから展開すると、市場のオッズが持っている着順の相関（まくられた艇が
    3着に残る、といった結びつき）を捨ててしまう。trifecta_probs は補正表で
    その相関を持つようになったが、市場の120通りのほうがまだ精しい。
    """
    probs = trifecta_probs(model_prob)
    if weight < 1.0:
        inv = {k: 1.0 / o for k, o in trifecta_odds.items() if o}
        total = sum(inv.values())
        if total > 0:
            market = {k: v / total for k, v in inv.items()}
            probs = {k: (1 - weight) * market.get(k, 0.0) + weight * p
                     for k, p in probs.items()}
    picks = []
    for combo, p in probs.items():
        odds = trifecta_odds.get(combo)
        if not odds:
            continue
        picks.append({
            "combo": combo,
            "prob": round(p, 5),
            "odds": float(odds),
            "ev": round(p * float(odds), 3),
        })
    picks.sort(key=lambda x: (-x["ev"], -x["prob"]))
    return picks[:limit]


def recommend_trio(model_prob: dict[int, float],
                   trio_odds: dict[str, float],
                   limit: int = TRIO_PICKS,
                   weight: float = 1.0) -> list[dict]:
    """
    三連複のオッズと照らし合わせて、EVの高い順に買い目を返す。

        EV = 公開確率 × 三連複オッズ

    recommend_trifecta と同じ形。確率は trio_probs（三連単を畳んだもの）で作り、
    weight で市場へ引き戻す。**引き戻しの相手は三連複のオッズが示す確率である。**
    三連単のオッズを畳んだものを使ってはならない。別勘定の投票なので、同じ3艇
    でも2つの市場の見立てはずれる。買うのは三連複のほうなので、合わせる相手も
    三連複でなければ、画面に出るEVがどの市場に対するものか分からなくなる。
    """
    probs = trio_probs(model_prob)
    if weight < 1.0:
        inv = {k: 1.0 / o for k, o in trio_odds.items() if o}
        total = sum(inv.values())
        if total > 0:
            market = {k: v / total for k, v in inv.items()}
            probs = {k: (1 - weight) * market.get(k, 0.0) + weight * p
                     for k, p in probs.items()}
    picks = []
    for combo, p in probs.items():
        odds = trio_odds.get(combo)
        if not odds:
            continue
        picks.append({
            "combo": combo,
            "prob": round(p, 5),
            "odds": float(odds),
            "ev": round(p * float(odds), 3),
        })
    picks.sort(key=lambda x: (-x["ev"], -x["prob"]))
    return picks[:limit]


def estimate_win_prob(racers: list[dict], venue_code: str | None = None,
                      conditions: dict | None = None,
                      base_rates: dict[int, float] | None = None) -> dict[int, float]:
    """
    コース別1着率を土台に、レース内で中心化した特徴量の重み付き和で補正する。

    base_rates を渡すと course_rates() の代わりにそれを使う。検証で使うため。
    course_rates() が読む course_rates.json は全データから作られるので、
    それを検証側の採点に使うと、答えを見て作った基準で答え合わせをすることになる。
    分割して評価する側が、学習側だけで推定した基準率をここに渡す。
    """
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

    if base_rates is None:
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
