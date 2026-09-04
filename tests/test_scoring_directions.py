"""
予測モデルの各特徴量が、正しい向きに効いていることを固定する。

実行:
  py -3 -m unittest discover -s tests

**符号の間違いは静かに通る。** 値域も合計も正しいまま、予測だけが逆を向く。
実際に experiment.py で直近STの符号を取り違えて、フライング（失格）した
走りが「最良のST」に化けた。同じ種類の事故が scaper/scoring.py で起きても、
これまでのテストは全部緑のままだった。

見るのは _feature 単体ではなく estimate_win_prob の出力。そうすると
_feature の符号反転と LOGIT_WEIGHTS の符号の両方を同時に守れる。

特徴量はレース内で中心化されるので、1艇だけ値を動かしてその艇の確率が
どちらへ動くかで向きを判定する。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.scoring import LOGIT_WEIGHTS, ZERO_IS_VALID, estimate_win_prob

# 中心化されるので、全艇に同じ値を入れておかないと「1艇だけ動かした」
# 比較にならない。0は「欠損」として平均に置き換えられる特徴量があるため、
# 既定値はすべて非0にしてある。
BASE = {
    "class": "B1",
    "win_rate_all": 5.0,
    "win_rate_venue": 5.0,
    "avg_st": 0.16,
    "motor_in2_rate": 35.0,
    "boat_in2_rate": 35.0,
    "weight": 52.0,
    "f_count": 0,
    "in2_rate_all": 30.0,
    "exhibit_time": 6.80,
    "tilt": -0.5,
}

TARGET = 3   # 内でも外でもない艇で見る


def racers(**patch):
    out = [dict(BASE, lane=i) for i in range(1, 7)]
    out[TARGET - 1].update(patch)
    return out


def prob(patch=None, conditions=None, lane=TARGET):
    return estimate_win_prob(racers(**(patch or {})), None, conditions)[lane]


class FeatureDirections(unittest.TestCase):
    """値を良い方へ動かしたら確率が上がること。逆なら下がること。"""

    def assertRaises_prob(self, patch, msg):
        self.assertGreater(prob(patch), prob(), msg)

    def assertLowers_prob(self, patch, msg):
        self.assertLess(prob(patch), prob(), msg)

    # --- 大きいほど有利 ---

    def test_win_rate_all(self):
        self.assertRaises_prob({"win_rate_all": 7.0}, "全国勝率が高いほど有利")

    def test_win_rate_venue(self):
        self.assertRaises_prob({"win_rate_venue": 7.0}, "当地勝率が高いほど有利")

    def test_motor(self):
        self.assertRaises_prob({"motor_in2_rate": 55.0}, "モーターが良いほど有利")

    def test_boat(self):
        self.assertRaises_prob({"boat_in2_rate": 55.0}, "ボートが良いほど有利")

    def test_in2_rate_all(self):
        self.assertRaises_prob({"in2_rate_all": 60.0}, "2連対率が高いほど有利")

    def test_class(self):
        self.assertRaises_prob({"class": "A1"}, "A1はB1より有利")
        self.assertLowers_prob({"class": "B2"}, "B2はB1より不利")

    def test_tilt(self):
        self.assertRaises_prob({"tilt": 0.5}, "チルトは正の重み")

    # --- 小さいほど有利（符号を反転している。ここが今回の要点） ---

    def test_average_st_smaller_is_better(self):
        """
        平均STは小さいほど良い。_feature が符号を反転しているので、
        反転を外すと逆を向く。重みが8.23と最大級なので影響も大きい。
        """
        self.assertRaises_prob({"avg_st": 0.10}, "平均STが小さいほど有利")
        self.assertLowers_prob({"avg_st": 0.22}, "平均STが大きいほど不利")

    def test_exhibit_time_smaller_is_better(self):
        """
        展示タイムも小さいほど速い。重みは3.53で2番目に大きい。
        ここを逆にするとモデル全体が逆を向くが、値域も合計も正しいままなので
        他のテストでは気づけない。
        """
        self.assertRaises_prob({"exhibit_time": 6.60}, "展示タイムが速いほど有利")
        self.assertLowers_prob({"exhibit_time": 7.00}, "展示タイムが遅いほど不利")

    # --- 大きいほど不利 ---

    def test_weight_heavier_is_worse(self):
        self.assertLowers_prob({"weight": 58.0}, "重いほど不利")

    def test_flying_history_is_worse(self):
        self.assertLowers_prob({"f_count": 2}, "フライング歴があるほど不利")


class ZeroIsValid(unittest.TestCase):
    """
    0が「欠損」ではなく正当な値である特徴量。

    ここを取り違えると、F歴の無いきれいな選手が全員「平均並み」に潰れて
    信号が消える。数字は正しく見えるので気づけない。
    """

    def test_zero_f_count_is_an_advantage_not_missing(self):
        self.assertIn("f_count", ZERO_IS_VALID)
        # 全艇がF1本の中で、1艇だけF0なら、その艇が有利になる
        dirty = [dict(BASE, lane=i, f_count=1) for i in range(1, 7)]
        dirty[TARGET - 1]["f_count"] = 0
        clean_prob = estimate_win_prob(dirty, None, None)[TARGET]
        allsame = [dict(BASE, lane=i, f_count=1) for i in range(1, 7)]
        self.assertGreater(clean_prob, estimate_win_prob(allsame, None, None)[TARGET],
                           "F0は欠損ではなく「フライング歴が無い」という情報")

    def test_zero_tilt_is_valid(self):
        self.assertIn("tilt", ZERO_IS_VALID)


class InnerInteraction(unittest.TestCase):
    """
    風と波は1レースで共通の値なので、そのままでは正規化で打ち消し合う。
    1号艇との交互作用としてだけ入れている。
    """

    def _p(self, conditions):
        return estimate_win_prob(racers(), None, conditions)

    def test_wind_and_wave_only_touch_lane_one(self):
        """
        2〜6号艇どうしの比は変わらない。

        中心化すると1号艇は +5w/6、他は全員 -w/6 で同じだけ動くので、
        ソフトマックスを通しても2〜6号艇の相対関係は保たれる。もし
        1号艇限定の条件が外れると、風がそのまま全艇に乗って比が崩れる。

        比そのものではなく比の比を見るのは estimate_win_prob が確率を
        小数4桁に丸めるため。6号艇のように確率が0.025程度だと、丸めの
        影響が比例して大きく出る（比にして0.5%程度）。1号艇限定の条件が
        外れると、波の重み×波高の差がそのまま効いて比は数十%動くので、
        1%の許容でも十分に捕まる。
        """
        calm = self._p({"wind_speed": 1.0, "wave_height": 1.0})
        rough = self._p({"wind_speed": 8.0, "wave_height": 12.0})
        for lane in range(3, 7):
            ratio = (rough[2] / rough[lane]) / (calm[2] / calm[lane])
            self.assertAlmostEqual(
                ratio, 1.0, delta=0.01,
                msg=f"風と波が2号艇と{lane}号艇の相対関係を変えている",
            )

    def test_rough_water_reduces_inner_advantage(self):
        """荒れると内枠の優位が削られる。重みは両方とも負。"""
        calm = self._p({"wind_speed": 1.0, "wave_height": 1.0})
        rough = self._p({"wind_speed": 8.0, "wave_height": 12.0})
        self.assertLess(rough[1], calm[1], "荒れたら1号艇の確率は下がる")

    def test_missing_conditions_do_not_crash(self):
        """気象が無い日は風と波の項が落ちるだけで、他はそのまま効く。"""
        p = estimate_win_prob(racers(), None, None)
        self.assertAlmostEqual(sum(p.values()), 1.0, places=6)


class WeightsCoverage(unittest.TestCase):
    """LOGIT_WEIGHTS に項目を足したら、向きのテストも足すこと。"""

    TESTED = {
        "win_rate_all", "class", "win_rate_venue", "st", "motor_in2_rate",
        "boat_in2_rate", "weight", "f_count", "in2_rate_all", "exhibit",
        "tilt", "wind_inner", "wave_inner",
    }

    def test_every_weight_has_a_direction_test(self):
        missing = set(LOGIT_WEIGHTS) - self.TESTED
        self.assertEqual(
            missing, set(),
            f"向きのテストが無い特徴量がある: {sorted(missing)}。"
            "符号の間違いは値域にも合計にも現れないので、必ず足すこと。",
        )


if __name__ == "__main__":
    unittest.main()
