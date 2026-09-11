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

from scraper.scoring import BLEND_WEIGHT


DATASET = Path("output/backtest.jsonl")

COURSE_BASE = {1: 0.55, 2: 0.145, 3: 0.12, 4: 0.105, 5: 0.055, 6: 0.025}

# 級別は選手の実力を表す最も強い単一指標だが、現行モデルは使っていない。
# 全国勝率と相関はあるが、勝率は出走数の少ない選手ほどぶれるため、
# 級別が独立した情報を持つ可能性がある。
CLASS_STRENGTH = {"A1": 1.0, "A2": 0.72, "B1": 0.5, "B2": 0.35}


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



# ---------------------------------------------------------------- 条件付きロジット
#
# 現行モデルは「コース基準 × 平均比の累乗」を手で決めた重みで掛け合わせている。
# 形もパラメータも人が決めており、データから当てはめていない。市場オッズに
# 明確に負けている原因が「形が悪い」のか「特徴量が足りない」のかを切り分ける。
#
# 6艇のうち1着が1つ選ばれる構造なので、条件付きロジット（レース内ソフトマックス）が
# 素直な当てはめになる。
#
#   P(i が1着) = exp(offset_i + x_i・β) / Σ_j exp(offset_j + x_j・β)
#
# offset にはコース別1着率の対数を置く。コース効果はデータから学ばせず既定値に
# 固定する。以前、コース別1着率を実測で置き換えても改善しなかった（差が
# 標準誤差の範囲だった）ので、ここを自由にするとノイズを拾うだけになる。
#
# 特徴量はレース内で中心化する。レース間の絶対水準ではなく、同じレースに
# 出ている6人の中での相対差だけが勝敗を決めるため。
#
# 依存を増やさないよう numpy は使わず、9次元のニュートン法を自前で解く。
# 勾配降下だと収束に数千反復かかるが、ヘッセ行列が9×9と小さいので
# ニュートン法なら10回程度で止まる。

FEATURES_CURRENT = ["win_rate_all", "class", "win_rate_venue", "st", "motor_in2_rate"]
FEATURES_ALL = FEATURES_CURRENT + [
    "boat_in2_rate", "weight", "f_count", "in2_rate_all",
]
# 当日の情報。出走表からは分からない、その日の艇と水面の状態。
FEATURES_TODAY = FEATURES_CURRENT + ["exhibit"]
FEATURES_TODAY_FULL = FEATURES_ALL + ["exhibit", "tilt", "wind_inner", "wave_inner"]

# スタート展示から作る特徴量。締切前に分かるのに、いままで使っていなかった。
#
#   ex_st    展示のST。小さいほど良いので符号を反転する。
#            **展示のフライングは失格ではない。** beforeinfo は早すぎたSTを
#            負で持つので、反転すると大きな正になり「最良」として扱われる。
#            本番のSTと違って罰は無いため、これは意図した扱いだが、向きが
#            正しいかは検証で確かめること（本番STの向きとは前提が違う）。
#   ex_gain  枠番から進入コースへ何コース内に入ったか。正なら前づけが通った艇。
#            0は「枠なり」で、欠損ではなく最頻の正当な値。
#
# スタート展示は予想の材料として広く見られている（周回展示の展示タイムと並ぶ
# 直前情報の柱）が、展示STと本番STの相関は r = 0.121 と弱い。
#
# **2,304レースでは有望。ただしまだ採用しない。**
#
#   主分割  -0.0017 ± 0.0035  誤差の範囲
#   12分割  すべて符号が負（改善方向）。2SEを超えたのは1つだけ
#           20260827 -0.0025 → 20260905 -0.0073 → 20260906 -0.0105 ± 0.0047
#
# **学習データが増えるほど効果が大きくなる。** 履歴特徴量が「窓を広げるほど
# 小さくなる」挙動だったのと正反対で、信号がある側の振る舞いに見える。
# 次にデータが増えたとき、最初に見る候補がこれ。
FEATURES_EXHIBITION = ["ex_st", "ex_gain"]

# 機力の急変。直前情報ページの「プロペラ」「部品交換」列から作る。
# backtest.py backfill-machine がキャッシュから各艇に書き込む。
#
# 他の特徴量は期別の集計値（勝率・平均ST）か、その日の状態（展示タイム・
# チルト・気象）しかなく、**節の途中で機力が変わったことを映すものが無い。**
# 部品交換はそれを直接示す。向きは事前に決めない。整備で上向くのか、
# 不調だから交換したのかは、当てはめに決めさせる。
#
# **2,304レースでは効果が見えなかった。ただし「効かない」とは言えない。**
#
#   主分割  +0.0004 ± 0.0008  誤差の範囲（符号は悪化側）
#   観測    部品交換 713艇 (5.2%) / プロペラ新品 72艇 (0.5%)
#
# 延べ13,824艇のうち交換が5.2%では、検出できる効果の下限が大きすぎる。
# 情報が無いのか情報に価値が無いのかを区別できていないので、データが
# 数倍になってから再判定する。
FEATURES_MACHINE = ["parts", "prop_new"]

# 節間の履歴から作る特徴量。attach_history が各艇に書き込む。
#
# READMEは市場オッズとの残り0.10の差を「節間成績や選手の直近の調子など、
# まだ集めていない情報」に見ている。出走表の勝率や平均STは期別の集計なので、
# 節に入ってからの調子は映さない。ここはそれを直接測る。
#
# **効かない。2,304レース(15日分)で測り直して確定した。配備してはいけない。**
#
# 1,236レース時点では「効かない原因はデータ量」と書いていた。2,304レースに
# 増やしてカバレッジも改善したが、効果は出なかった。**データ量の仮説は否定された。**
#
#   カバレッジ  過去走ゼロ 16.5% → 10.5% / 窓(4走)を満たす 40% → 58.4%
#   主分割      -0.0020 ± 0.0020  誤差の範囲
#   12分割      悪化2 / 誤差の範囲10
#
# 節が短いからではなく、出走表の期別勝率と当日の展示タイムが同じ情報を
# 既に持っているのだと考えられる。窓幅を2/3/4/6/10走と変えても、広げるほど
# 効果が小さくなる挙動は変わらない。信号があるなら逆に大きくなるはずで、
# これはノイズを拾っている側の振る舞いである。
#
# 再挑戦するなら、直近の走りそのものではなく、既存の特徴量が持っていない軸
# （同じモーターが節の中でどう変わったか、など）を探すこと。
FEATURES_HISTORY = FEATURES_TODAY_FULL + ["recent_st", "recent_rank", "course_shift"]
# 実際に配備している構成。FEATURES_TODAY_FULL から2つ落としてある。
# wind_inner は2,304レースで当てはめると符号が正へ反転し（風が内枠を助ける
# ことになる）、in2_rate_all はほぼ0。どちらも外しても差が出ない
# （+0.0001 ± 0.0002 と -0.0001 ± 0.0001、12分割すべて誤差の範囲）。
# **誤差に埋もれるなら単純なほうを採る。** scraper/scoring.py の
# LOGIT_WEIGHTS はこの構成で当てはめた係数を持っている。
FEATURES_DEPLOYED = [f for f in FEATURES_TODAY_FULL
                     if f not in ("wind_inner", "in2_rate_all")]

FEATURES_TODAY_MACHINE = FEATURES_TODAY_FULL + FEATURES_MACHINE
FEATURES_TODAY_EXHIBITION = FEATURES_TODAY_FULL + FEATURES_EXHIBITION

# 0が「欠損」ではなく正当な値である特徴量。
# F回数0は「フライング歴が無い」という情報であって、欠測ではない。
# ここを取り違えると、きれいな選手が全員「平均並み」に潰れて信号が消える。
# 風と波の交互作用も、内枠以外は定義上0になる。
ZERO_IS_VALID = {"tilt", "f_count", "l_count", "wind_inner", "wave_inner",
                 "course_shift", "parts", "prop_new", "ex_gain"}


HISTORY_WINDOW = 4


def attach_history(rows, window: int = HISTORY_WINDOW):
    """
    各艇に、そのレースより前の走りから作った特徴量を書き込む。

    **対象レースより厳密に前の走りだけを使う。** 特徴量を計算してから
    そのレースの結果を履歴へ積む、という順にしてあるので、自分の結果が
    自分の特徴量に入ることは構造的に起きない。

    順序は (日付, レース番号)。選手は1日に1場しか出ないので、
    この並びは選手ごとの時系列と一致する。場をまたいだ同時刻の
    レース同士の前後は入れ替わりうるが、同じ選手が両方に出ることは
    無いので履歴には影響しない。

    書き込む特徴量（いずれも大きいほど有利になる向きに符号を揃える）:
      recent_st    直近window走の平均ST。小さいほど良いので反転する。
                   出走表の avg_st は期別の集計なので、節に入ってからの
                   調子は映さない。こちらはそれを直接見る。
      recent_rank  直近window走の平均着順。小さいほど良いので反転する。
      course_shift 枠番から実際の進入コースへどれだけ内に入ったかの平均。
                   正なら前づけする選手。0は「動かない」で、これは
                   欠損ではなく正当な値なので ZERO_IS_VALID に入れてある。
                   履歴が無い選手も0になるが、枠なりが最頻なので
                   既定値として妥当。
    """
    order = sorted(rows, key=lambda r: (r["date"], r["race_no"]))
    hist: dict[str, list] = {}

    for row in order:
        start = {s["lane"]: s for s in (row.get("start") or [])}
        # JSONを往復すると艇番のキーが文字列になる
        finish = {int(k): v for k, v in (row.get("finish") or {}).items()}

        for r in row["racers"]:
            past = hist.get(r.get("racer_id")) or []
            recent = past[-window:]
            # フライングのSTは平均から外す。負の値で持っているので、
            # 符号を反転して「大きいほど良い」に揃えると、失格した走りが
            # 最良のSTに化ける。実測で24件あり、数は少ないが向きが逆になる。
            sts = [p["st"] for p in recent if p["st"] is not None and not p["flying"]]
            ranks = [p["rank"] for p in recent if p["rank"] is not None]
            shifts = [p["shift"] for p in recent if p["shift"] is not None]
            r["hist_n"] = len(past)
            r["recent_st"] = -(sum(sts) / len(sts)) if sts else 0.0
            r["recent_rank"] = -(sum(ranks) / len(ranks)) if ranks else 0.0
            r["course_shift"] = (sum(shifts) / len(shifts)) if shifts else 0.0

        # ここで初めて今回の結果を積む。上の計算より後に置くことが要点。
        for r in row["racers"]:
            s = start.get(r["lane"])
            hist.setdefault(r.get("racer_id"), []).append({
                "st": s["st"] if s else None,
                "flying": bool(s["flying"]) if s else False,
                "shift": (r["lane"] - s["course"]) if s else None,
                "rank": finish.get(r["lane"]),
            })

    return rows


def _raw_feature(r, name, row):
    """1艇ぶんの特徴量。大きいほど有利になる向きに符号を揃える。"""
    if name in ("ex_st", "ex_gain"):
        shown = {e["lane"]: e for e in (row.get("start_exhibition") or [])}
        e = shown.get(r["lane"])
        if not e:
            return 0.0
        if name == "ex_st":
            st = e.get("st")
            return -st if st is not None else 0.0
        course = e.get("course")
        return float(r["lane"] - course) if course else 0.0
    if name == "parts":
        # 部品交換があったか。何を何個換えたかまでは見ない。
        # 品目ごとに分けると、1つあたりの観測が数十件に落ちる。
        return 1.0 if r.get("parts") else 0.0
    if name == "prop_new":
        return 1.0 if r.get("propeller_new") else 0.0
    if name == "class":
        return CLASS_STRENGTH.get(r.get("class"), 0.5)
    if name == "st":
        # STは小さいほど良いので符号を反転する
        return -(r.get("avg_st") or 0.0)
    if name == "exhibit":
        # 展示タイムも小さいほど速い
        return -(r.get("exhibit_time") or 0.0)
    if name in ("wind_inner", "wave_inner"):
        # 風と波は1レースで共通の値なので、そのままではソフトマックスで
        # 打ち消し合って何も効かない。効くとすれば「荒れると内枠の
        # 優位が削られる」という形なので、1号艇との交互作用として入れる。
        if r["lane"] != 1:
            return 0.0
        cond = row.get("conditions") or {}
        key = "wind_speed" if name == "wind_inner" else "wave_height"
        return cond.get(key) or 0.0
    return r.get(name) or 0.0


def _race_matrix(row, names):
    """
    レース1本ぶんの (艇番リスト, 中心化済み特徴量行列, オフセット) を返す。

    欠損値は0で入るが、その艇だけ極端な値にならないよう、中心化の平均は
    有効な値だけから取り、欠損艇は平均に置き換えてから引く（＝寄与0）。
    """
    racers = row["racers"]
    if not racers:
        return [], [], []
    lanes = [r["lane"] for r in racers]
    cols = []
    for name in names:
        vals = [_raw_feature(r, name, row) for r in racers]
        if name in ZERO_IS_VALID:
            m = sum(vals) / len(vals)
            cols.append([v - m for v in vals])
        else:
            valid = [v for v in vals if v]
            m = sum(valid) / len(valid) if valid else 0.0
            cols.append([(v if v else m) - m for v in vals])
    rows_ = [[cols[j][i] for j in range(len(names))] for i in range(len(racers))]
    offset = [math.log(max(COURSE_BASE.get(l, 0.05), 1e-6)) for l in lanes]
    return lanes, rows_, offset


def _scales(rows, names):
    """各特徴量の標準偏差。桁が違うままだとニュートン法の条件数が悪化する。"""
    acc = [[] for _ in names]
    for row in rows:
        _, x, _ = _race_matrix(row, names)
        for r in x:
            for j, v in enumerate(r):
                acc[j].append(v)
    out = []
    for col in acc:
        if not col:
            out.append(1.0)
            continue
        m = sum(col) / len(col)
        var = sum((v - m) ** 2 for v in col) / max(len(col) - 1, 1)
        out.append(math.sqrt(var) or 1.0)
    return out


def _solve(a, b):
    """部分ピボット付きガウス消去。次元が小さいので素直な実装で足りる。"""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r == c:
                continue
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_logit(rows, names, l2=1.0, iters=25):
    """
    条件付きロジットを最尤で当てはめる。L2で軽く縮小する。

    l2 は学習側だけで決める。検証側を見て選ぶと、検証が学習の一部になり
    「学習に使っていないレースで比べる」という前提が崩れる。
    """
    scales = _scales(rows, names)
    data = []
    for row in rows:
        lanes, x, off = _race_matrix(row, names)
        if not lanes or row["winner_lane"] not in lanes:
            continue
        x = [[v / scales[j] for j, v in enumerate(r)] for r in x]
        data.append((x, off, lanes.index(row["winner_lane"])))

    k = len(names)

    def loglik(b):
        total = 0.0
        for x, off, wi in data:
            u = [off[i] + sum(x[i][j] * b[j] for j in range(k)) for i in range(len(x))]
            mx = max(u)
            total += u[wi] - mx - math.log(sum(math.exp(v - mx) for v in u))
        return total - l2 * sum(v * v for v in b)

    beta = [0.0] * k
    cur = loglik(beta)
    for _ in range(iters):
        grad = [0.0] * k
        hess = [[0.0] * k for _ in range(k)]
        for x, off, wi in data:
            u = [off[i] + sum(x[i][j] * beta[j] for j in range(k)) for i in range(len(x))]
            mx = max(u)
            e = [math.exp(v - mx) for v in u]
            tot = sum(e)
            p = [v / tot for v in e]
            xbar = [sum(p[i] * x[i][j] for i in range(len(x))) for j in range(k)]
            for j in range(k):
                grad[j] += x[wi][j] - xbar[j]
            for a in range(k):
                for b in range(k):
                    ex = sum(p[i] * x[i][a] * x[i][b] for i in range(len(x)))
                    hess[a][b] -= ex - xbar[a] * xbar[b]
        for j in range(k):
            grad[j] -= 2 * l2 * beta[j]
            hess[j][j] -= 2 * l2
        # 最大化のニュートン法は beta - H^-1 g。Hは負定値なので
        # この向きが上りになる。符号を取り違えると発散する。
        step = _solve(hess, grad)
        if step is None:
            break

        # 直線探索。ニュートン法は初期値が悪いと1歩で飛びすぎるので、
        # 対数尤度が実際に上がるまで歩幅を半分にする。
        t = 1.0
        for _ in range(30):
            cand = [beta[j] - t * step[j] for j in range(k)]
            if loglik(cand) > cur:
                break
            t /= 2.0
        else:
            break

        beta = cand
        cur = loglik(beta)
        if max(abs(t * v) for v in step) < 1e-8:
            break

    return {"names": names, "beta": beta, "scales": scales}


def make_logit(model):
    """当てはめ済みの係数から予測関数を作る。"""
    names, beta, scales = model["names"], model["beta"], model["scales"]

    def predict(row):
        lanes, x, off = _race_matrix(row, names)
        if not lanes:
            return {}
        u = []
        for i in range(len(lanes)):
            u.append(off[i] + sum(x[i][j] / scales[j] * beta[j] for j in range(len(names))))
        mx = max(u)
        e = [math.exp(v - mx) for v in u]
        tot = sum(e)
        return {lanes[i]: e[i] / tot for i in range(len(lanes))}

    return predict


def report_coefficients(model, label):
    print(f"  {label} の係数（標準化後・符号は大きいほど有利に揃えてある）")
    pairs = sorted(zip(model["names"], model["beta"]), key=lambda t: -abs(t[1]))
    for name, b in pairs:
        print(f"    {name:<16} {b:>+8.4f}")
    print()


def rolling_check(rows, names, ref_fn, label):
    """
    分割位置を変えて同じ比較を繰り返す。

    候補を複数試して一番良いものを採ると、多重比較のぶん偶然通ることがある。
    分割を変えても符号と大きさが安定していれば、たまたま拾った差ではないと言える。
    学習と検証の境目は必ず日付で切り、検証側は学習より後の日だけにする。
    """
    dates = sorted({r["date"] for r in rows})
    print(f"--- {label}: 分割位置を変えた再確認 ---")
    print(f"  {'学習':>10} {'検証':>10} {'差':>9} {'±SE':>8} {'判定':>10}")
    print("  " + "-" * 52)
    for cut in range(3, len(dates)):
        train = [r for r in rows if r["date"] < dates[cut]]
        test = [r for r in rows if r["date"] >= dates[cut]]
        if len(test) < 100:
            continue
        model = fit_logit(train, names)
        diff, se, n = paired_diff(test, make_logit(model), ref_fn)
        if se == 0:
            continue
        verdict = "改善" if diff < -2 * se else ("悪化" if diff > 2 * se else "誤差の範囲")
        print(f"  {len(train):>10} {len(test):>10} {diff:>+9.4f} {se:>8.4f} {verdict:>10}")
    print()


def rolling_check_history(rows, label="ロジット+履歴 vs ロジット+当日全部"):
    """
    履歴を足した効果を、分割位置を変えて確認する。

    2,304レース時点では、最も古い2つの分割で有意に悪化し、残りはすべて
    誤差の範囲に収まる。データを増やしても効果が現れないことの確認になっている。
    """
    rolling_check_pair(rows, FEATURES_HISTORY, FEATURES_TODAY_FULL, label)


def rolling_check_machine(rows, label="ロジット+機力 vs ロジット+当日全部"):
    """部品交換・プロペラを足した効果を、分割位置を変えて確認する。"""
    rolling_check_pair(rows, FEATURES_TODAY_MACHINE, FEATURES_TODAY_FULL, label)


def rolling_check_exhibition(rows, label="ロジット+展示ST vs ロジット+当日全部"):
    """スタート展示を足した効果を、分割位置を変えて確認する。"""
    rolling_check_pair(rows, FEATURES_TODAY_EXHIBITION, FEATURES_TODAY_FULL, label)


def rolling_check_pair(rows, names_a, names_b, label):
    """
    2つの特徴量セットの差を、分割位置を変えて確認する。

    rolling_check と違い、比較相手も各分割で当てはめ直す。片方の有無だけを
    変えた2つのモデルを、同じ学習データから作って同じ検証データで比べないと、
    差が「その特徴量の効果」なのか「学習量の違い」なのか分からない。
    """
    dates = sorted({r["date"] for r in rows})
    print(f"--- {label}: 分割位置を変えた再確認 ---")
    print(f"  {'分割日':<10} {'学習':>8} {'検証':>8} {'差':>9} {'±SE':>8} {'判定':>10}")
    print("  " + "-" * 58)
    for cut in range(2, len(dates)):
        train = [r for r in rows if r["date"] < dates[cut]]
        test = [r for r in rows if r["date"] >= dates[cut]]
        if len(train) < 150 or len(test) < 150:
            continue
        a = make_logit(fit_logit(train, names_a))
        b = make_logit(fit_logit(train, names_b))
        diff, se, n = paired_diff(test, a, b)
        if se == 0:
            continue
        verdict = "改善" if diff < -2 * se else ("悪化" if diff > 2 * se else "誤差の範囲")
        print(f"  {dates[cut]:<10} {len(train):>8} {len(test):>8} "
              f"{diff:>+9.4f} {se:>8.4f} {verdict:>10}")
    print("  符号が分割位置で反転するなら、それは信号ではない。")
    print()


def main():
    rows = load()
    if not rows:
        print("データがありません。backtest.py collect を先に実行してください。")
        return

    # 節間の履歴を各艇に付ける。分割の前に付けてよい。対象レースより
    # 厳密に前の走りしか見ないので、検証側の行が学習側の特徴量に
    # 混ざることは無い。
    attach_history(rows)
    _history_coverage(rows)

    train, test = split_by_date(rows)
    print(f"全{len(rows)}レース (学習{len(train)} / 検証{len(test)})\n")

    # 係数は学習側だけで当てはめる。検証側を1行も見ずに決めるのが要点。
    fit_rows = train or rows
    m_cur = fit_logit(fit_rows, FEATURES_CURRENT)
    m_all = fit_logit(fit_rows, FEATURES_ALL)
    m_today = fit_logit(fit_rows, FEATURES_TODAY)
    m_full = fit_logit(fit_rows, FEATURES_TODAY_FULL)
    m_hist = fit_logit(fit_rows, FEATURES_HISTORY)
    m_mach = fit_logit(fit_rows, FEATURES_TODAY_MACHINE)
    m_exhi = fit_logit(fit_rows, FEATURES_TODAY_EXHIBITION)
    m_dep = fit_logit(fit_rows, FEATURES_DEPLOYED)
    report_coefficients(m_cur, "ロジット(現行特徴)")
    report_coefficients(m_all, "ロジット(全特徴)")
    report_coefficients(m_today, "ロジット+展示")
    report_coefficients(m_full, "ロジット+当日全部")
    report_coefficients(m_hist, "ロジット+履歴")
    report_coefficients(m_mach, "ロジット+機力")
    report_coefficients(m_exhi, "ロジット+展示ST")

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
        "ロジット(現行特徴)":     make_logit(m_cur),
        "ロジット(全特徴)":       make_logit(m_all),
        "ロジット+展示":          make_logit(m_today),
        "ロジット+当日全部":       make_logit(m_full),
        "ロジット+履歴":          make_logit(m_hist),
        "ロジット+機力":          make_logit(m_mach),
        "ロジット+展示ST":         make_logit(m_exhi),
        "配備構成":               make_logit(m_dep),
    }

    if not test:
        print("[警告] 1日分しかないため学習/検証に分割できない。")
        print("       以下は全データでの成績であり、候補の優劣を判断する根拠にならない。\n")
        _table(rows, candidates, "全データ")
        _noise_note(len(rows))
        return

    _table(train, candidates, f"学習 {len(train)}レース (参考)")
    _table(test, candidates, f"検証 {len(test)}レース (こちらで判断する)")
    rolling_check(rows, FEATURES_TODAY_FULL,
                  make_model(w_class=1.0, w_venue=0.5),
                  "ロジット+当日全部 vs 乗算モデル(+級別 +当地)")
    rolling_check_history(rows)
    rolling_check_machine(rows)
    rolling_check_exhibition(rows)
    _machine_coverage(rows)
    blend_check(rows)
    trifecta_blend_check(rows)
    _noise_note(len(test))


def blend_check(rows, steps=21):
    """
    公開する確率を「市場オッズとモデルの混合」にしたとき、重みをいくつにすべきか。

    背景。三連単の推奨買い目のEVが軒並み2〜5倍になっていた。EVは
    モデル確率/市場確率/1.335 なので、市場より33%多く確率を置くだけで1.0を超える。
    実測（2026-09-06の30レース）ではモデルと市場の1着確率の食い違いが中央値18.3pt
    あり、3連単のLogLossでは市場に +0.678 ± 0.265 で負けていた。**EVの大きさは
    市場の見落としではなく、こちらのずれの大きさを映していた。**

    混合すれば、ずれの分だけ市場へ引き戻せる。w=0で市場そのもの、w=1でモデル単独。

        線形     p = (1-w)·市場 + w·モデル
        対数線形 p ∝ 市場^(1-w) · モデル^w

    **wは学習側で選び、検証側で採点する。** 検証側で選んで検証側で報告すると、
    21通りの中から一番良かったものを選んだぶんだけ良く見える。
    """
    from scraper.scoring import estimate_win_prob

    cache = []
    for row in rows:
        k = {int(x): v for x, v in row["market_prob"].items()}
        m = estimate_win_prob(row["racers"], row.get("venue"), row.get("conditions"))
        if not k or not m:
            continue
        cache.append((row["date"], k, m, row["winner_lane"]))
    if not cache:
        return

    def blended(k, m, w, kind):
        if kind == "linear":
            p = {l: (1 - w) * k.get(l, 0.0) + w * m.get(l, 0.0) for l in range(1, 7)}
        else:
            p = {l: math.exp((1 - w) * math.log(max(k.get(l, 1e-9), 1e-9))
                             + w * math.log(max(m.get(l, 1e-9), 1e-9)))
                 for l in range(1, 7)}
        total = sum(p.values())
        return {l: v / total for l, v in p.items()} if total > 0 else k

    def losses(part, w, kind):
        return [-math.log(max(blended(k, m, w, kind).get(win, 1e-9), 1e-9))
                for _, k, m, win in part]

    def mean(v):
        return sum(v) / len(v) if v else 0.0

    def paired(a, b):
        d = [x - y for x, y in zip(a, b)]
        n = len(d)
        if n < 2:
            return 0.0, 0.0
        mu = sum(d) / n
        var = sum((x - mu) ** 2 for x in d) / (n - 1)
        return mu, math.sqrt(var / n)

    dates = sorted({d for d, _, _, _ in cache})
    cut = dates[len(dates) // 2]
    train = [c for c in cache if c[0] < cut]
    test = [c for c in cache if c[0] >= cut]
    if not train or not test:
        return

    grid = [i / (steps - 1) for i in range(steps)]
    print(f"[市場との混合] 学習{len(train)} / 検証{len(test)}レース")
    print("  wは学習側で選び、検証側で採点する。")
    print()

    chosen = {}
    for kind, label in (("linear", "線形"), ("log", "対数線形")):
        best = min(grid, key=lambda w: mean(losses(train, w, kind)))
        chosen[kind] = best
        ll_test = losses(test, best, kind)
        ll_market = losses(test, 0.0, kind)
        ll_model = losses(test, 1.0, kind)
        d_market, se_market = paired(ll_test, ll_market)
        d_model, se_model = paired(ll_test, ll_model)
        print(f"  {label}: 学習側で選ばれた w = {best:.2f}")
        print(f"    検証LogLoss  市場 {mean(ll_market):.4f} / "
              f"モデル {mean(ll_model):.4f} / 混合 {mean(ll_test):.4f}")
        print(f"    混合 - 市場   {d_market:+.4f} ± {se_market:.4f}"
              f"   {_verdict(d_market, se_market)}")
        print(f"    混合 - モデル {d_model:+.4f} ± {se_model:.4f}"
              f"   {_verdict(d_model, se_model)}")
        print()

    # 分割位置を変えても同じ重みが選ばれるか。1つの分割で決めた重みは、
    # その分割に合わせただけかもしれない。
    print("  分割位置を変えたときに学習側で選ばれる w")
    for cut_i in range(max(1, len(dates) - 5), len(dates)):
        c = dates[cut_i]
        tr = [x for x in cache if x[0] < c]
        te = [x for x in cache if x[0] >= c]
        if len(tr) < 50 or len(te) < 50:
            continue
        row = [c]
        for kind in ("linear", "log"):
            w = min(grid, key=lambda w: mean(losses(tr, w, kind)))
            row.append(f"{w:.2f}")
        print(f"    {row[0]}  線形 {row[1]}  対数線形 {row[2]}")
    print()


def trifecta_blend_check(rows, steps=21):
    """
    三連単の目の単位で、市場との混合の重みを検証する。

    blend_check は1着の確率で測っている。画面に出しているのは三連単の
    推奨買い目なので、採点も三連単の的中目で行う必要がある。1着で誤差の
    範囲でも、3つの掛け算になると差が開く。

    市場の三連単確率は120通りのオッズの逆数を正規化して作る。**この確率は
    着順の相関を含んでいる**（まくられた艇が3着に残る、といった結びつき）。
    trifecta_probs の Plackett-Luce 展開はそれを持たないので、混合は
    その弱点を埋める働きもする。

    オッズのページはキャッシュ済みのものだけを読む。取りに行かない。
    1400レースぶんの解析に数分かかる。
    """
    from scraper.odds import get_odds
    from scraper.session import cached
    from scraper.scoring import estimate_win_prob, trifecta_probs

    data = []
    for row in rows:
        params = {"rno": row["race_no"], "jcd": row["venue"], "hd": row["date"]}
        if cached("/owpc/pc/race/odds3t", params) is None:
            continue
        fin = row.get("finish") or {}
        top3 = sorted(((int(l), int(pos)) for l, pos in fin.items()
                       if 1 <= int(pos) <= 3), key=lambda t: t[1])
        if len(top3) != 3:
            continue
        odds = get_odds(row["date"], row["venue"], row["race_no"])
        if not odds or not odds["odds"]:
            continue
        inv = {k: 1.0 / v for k, v in odds["odds"].items() if v}
        total = sum(inv.values())
        if total <= 0:
            continue
        market = {k: v / total for k, v in inv.items()}
        m = estimate_win_prob(row["racers"], row.get("venue"), row.get("conditions"))
        if not m:
            continue
        model = trifecta_probs(m)
        combo = "-".join(str(l) for l, _ in top3)
        if combo in market and combo in model:
            data.append((row["date"], market[combo], model[combo]))

    if len(data) < 100:
        print(f"[三連単の混合] キャッシュ済みのオッズが{len(data)}件しかないため省略")
        return

    dates = sorted({d for d, _, _ in data})
    cut = dates[len(dates) // 2]
    train = [d for d in data if d[0] < cut]
    test = [d for d in data if d[0] >= cut]
    if not train or not test:
        return

    def losses(part, w):
        return [-math.log(max((1 - w) * k + w * m, 1e-12)) for _, k, m in part]

    grid = [i / (steps - 1) for i in range(steps)]
    best = min(grid, key=lambda w: sum(losses(train, w)) / len(train))
    base = losses(test, 0.0)
    print(f"[三連単の混合] 学習{len(train)} / 検証{len(test)}レース"
          f"  学習側で選ばれた w = {best:.2f}")
    print(f"  {'w':>4} {'検証LogLoss':>12} {'市場との差':>12} {'':>8} {'判定':>10}")
    for i in range(0, 11):
        w = i / 10
        ll = losses(test, w)
        diff = [a - b for a, b in zip(ll, base)]
        n = len(diff)
        mean = sum(diff) / n
        se = (sum((x - mean) ** 2 for x in diff) / (n * (n - 1))) ** 0.5 if n > 1 else 0.0
        mark = " ← 採用" if abs(w - BLEND_WEIGHT) < 1e-9 else ""
        print(f"  {w:>4.1f} {sum(ll)/n:>12.4f} {mean:>+12.4f} ± {se:.4f}"
              f" {_verdict(mean, se):>10}{mark}")
    print()


def order_correlation(rows, third=True, prior=3.0):
    """
    着順の結びつきを実測する。**三連単の展開を改善する唯一の当たりだった。**

    trifecta_probs の Plackett-Luce 展開は「1着を抜いた残りに同じ強さを当てる」
    独立な形で、着順の相関を持たない。実際には無視できない偏りがある。

      1着5 → 2着6   PLの想定の 3.21倍
      1着4 → 2着6   2.92倍
      1着4 → 2着1   0.59倍   ← 4号艇がまくると1号艇は沈む

    外が勝つときは外が続き、内が沈む。まくりの道連れという物理的に筋の通る構造。

    戻り値は (2着の補正表, 3着の補正表)。どちらも
    「実測回数 ÷ PLが与える期待回数」を、観測の薄い組み合わせのために
    prior で縮小したもの。1.0なら偏り無し。

    **必ず学習側だけから作ること。** 検証側の着順から作った表で検証側を
    採点すると、答えを見て答え合わせをすることになる。
    """
    from scraper.scoring import estimate_win_prob

    n2, d2, n3, d3 = {}, {}, {}, {}
    for row in rows:
        order = _finish_order(row)
        probs = estimate_win_prob(row["racers"], row.get("venue"),
                                  row.get("conditions"))
        if not order or not probs:
            continue
        first, second = order[0], order[1]
        rest = 1.0 - probs.get(first, 0.0)
        if rest <= 1e-6:
            continue
        for lane in probs:
            if lane == first:
                continue
            d2[(first, lane)] = d2.get((first, lane), 0.0) + probs[lane] / rest
            if lane == second:
                n2[(first, lane)] = n2.get((first, lane), 0.0) + 1.0
        if not third:
            continue
        rest3 = rest - probs.get(second, 0.0)
        if rest3 <= 1e-6:
            continue
        for lane in probs:
            if lane in (first, second):
                continue
            d3[(second, lane)] = d3.get((second, lane), 0.0) + probs[lane] / rest3
            if lane == order[2]:
                n3[(second, lane)] = n3.get((second, lane), 0.0) + 1.0

    def ratios(num, den):
        return {k: (num.get(k, 0.0) + prior) / (v + prior)
                for k, v in den.items() if v > 0}

    return ratios(n2, d2), ratios(n3, d3)


def _finish_order(row):
    """上位3艇を着順に並べる。揃っていなければ None。"""
    finish = {int(k): int(v) for k, v in (row.get("finish") or {}).items()}
    top = sorted([(pos, lane) for lane, pos in finish.items() if 1 <= pos <= 3])
    return [lane for _, lane in top] if len(top) == 3 else None


def rolling_check_order_correlation(rows):
    """
    着順相関の補正を、分割位置を変えて確認する。

    2026-09-11 の実測（2,436レース）。分割6通りすべてで改善し、学習データが
    増えるほど効果が大きい。標準誤差の6〜10倍あり、これまで試した候補の中で
    唯一はっきり効いた。

      分割日      2着の補正            2着+3着
      20260828   -0.0442 ± 0.0058    -0.0950 ± 0.0096
      20260901   -0.0461 ± 0.0085    -0.1127 ± 0.0141
      20260905   -0.0577 ± 0.0108    -0.1252 ± 0.0188
      20260907   -0.0590 ± 0.0149    -0.1284 ± 0.0248

    市場の三連単との差0.33のうち、およそ4割を埋める。
    """
    from scraper.scoring import estimate_win_prob, trifecta_probs

    def predict(row, r2, r3):
        probs = estimate_win_prob(row["racers"], row.get("venue"),
                                  row.get("conditions"))
        if not probs:
            return None
        out = {}
        for combo, p in trifecta_probs(probs).items():
            a, b, c = (int(x) for x in combo.split("-"))
            out[combo] = p * r2.get((a, b), 1.0) * r3.get((b, c), 1.0)
        total = sum(out.values())
        return {k: v / total for k, v in out.items()} if total > 0 else None

    usable = [r for r in rows if r.get("finish")]
    dates = sorted({r["date"] for r in usable})
    print("--- 着順相関の補正: 分割位置を変えた再確認 ---")
    print(f"  {'分割日':<10} {'学習':>6} {'検証':>6} {'差':>10} {'±SE':>8} {'判定':>10}")
    for cut in range(3, len(dates), 2):
        train = [r for r in usable if r["date"] < dates[cut]]
        test = [r for r in usable if r["date"] >= dates[cut]]
        if len(train) < 300 or len(test) < 300:
            continue
        r2, r3 = order_correlation(train)
        diffs = []
        for row in test:
            order = _finish_order(row)
            base = predict(row, {}, {})
            fixed = predict(row, r2, r3)
            if not order or not base or not fixed:
                continue
            combo = "-".join(str(l) for l in order)
            diffs.append(-math.log(max(fixed.get(combo, 1e-9), 1e-9))
                         + math.log(max(base.get(combo, 1e-9), 1e-9)))
        n = len(diffs)
        if n < 2:
            continue
        mean = sum(diffs) / n
        se = (sum((x - mean) ** 2 for x in diffs) / (n * (n - 1))) ** 0.5
        print(f"  {dates[cut]:<10} {len(train):>6} {len(test):>6} "
              f"{mean:>+10.4f} {se:>8.4f} {_verdict(mean, se):>10}")
    print()


def _verdict(diff, se):
    if se == 0:
        return "-"
    if abs(diff) < 2 * se:
        return "誤差の範囲"
    return "改善" if diff < 0 else "悪化"


def _machine_coverage(rows):
    """
    部品交換とプロペラ交換がどれだけ観測されているか。

    これが薄いと、効かなくても「情報が無いのか、情報に価値が無いのか」を
    区別できない。履歴特徴量で一度その判断を間違えかけたので、先に見る。
    """
    boats = [r for row in rows for r in row["racers"]]
    if not boats:
        return
    n = len(boats)
    parts = sum(1 for r in boats if r.get("parts"))
    prop = sum(1 for r in boats if r.get("propeller_new"))
    print(f"[機力] 延べ{n}艇  部品交換 {parts} ({parts/n*100:.1f}%)  "
          f"プロペラ新品 {prop} ({prop/n*100:.1f}%)")
    if parts == 0 and prop == 0:
        print("       付いていない。py -3 backtest.py backfill-machine を先に走らせること。")
    print()


def _history_coverage(rows):
    """
    履歴がどれだけ積み上がっているかを出す。

    これが薄いと、履歴特徴量が効かなくても「情報が無いのか、情報に
    価値が無いのか」を区別できない。解釈のために必ず先に見る。
    """
    counts = [r.get("hist_n", 0) for row in rows for r in row["racers"]]
    if not counts:
        return
    counts.sort()
    n = len(counts)
    zero = sum(1 for c in counts if c == 0)
    print(f"[節間履歴] 延べ{n}艇 / 過去走が無い艇 {zero} ({zero/n*100:.1f}%)")
    print(f"           平均 {sum(counts)/n:.2f}走  中央値 {counts[n//2]}走  "
          f"最大 {counts[-1]}走")
    enough = sum(1 for c in counts if c >= HISTORY_WINDOW)
    print(f"           窓({HISTORY_WINDOW}走)を満たす艇 {enough} ({enough/n*100:.1f}%)")
    print()


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
    # 「+級別 +当地」は、条件付きロジットへ切り替える前の乗算モデルと同じ構成。
    # **いま配備されているのはロジットのほう**（scoring.py の LOGIT_WEIGHTS）で、
    # 成績は「ロジット+当日全部」に近い。乗算モデルとの差は、ロジット化と
    # 当日情報を入れたことの効果を読むための基準として残してある。
    _paired_table(rows, candidates, "+級別 +当地")


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
    _use_utf8_stdio()
    main()
