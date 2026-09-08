"""
三連単の確率と推奨買い目の組み立てを固定する。

**ここは静かに間違う。** 確率の展開も期待値の式も、値域はもっともらしいまま
中身だけが狂う。実際に起こりうるのは次の3つで、どれも画面上は普通に見える。

1. 順序を無視して組み合わせの確率にしてしまう（1-2-3 と 3-2-1 が同じ値になる）
2. 期待値に控除率を掛けてしまう（オッズには既に控除が入っているので二重に引く）
3. 推奨をEV順でなく確率順に並べてしまう（本命ばかり並び、推奨の意味が消える）

実行:
  py -3 -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.scoring import (BLEND_WEIGHT, blend_with_market,
                             recommend_trifecta, score_race, trifecta_probs)

PROB = {1: 0.45, 2: 0.18, 3: 0.14, 4: 0.12, 5: 0.07, 6: 0.04}


class TrifectaProbsTest(unittest.TestCase):
    def test_covers_all_120_and_sums_to_one(self):
        probs = trifecta_probs(PROB)
        self.assertEqual(len(probs), 120)
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=9)

    def test_order_matters(self):
        """並びの違う同じ3艇が同じ確率になってはいけない。"""
        probs = trifecta_probs(PROB)
        self.assertGreater(probs["1-2-3"], probs["3-2-1"])

    def test_stronger_boat_first_is_more_likely(self):
        probs = trifecta_probs(PROB)
        self.assertGreater(probs["1-2-3"], probs["2-1-3"])

    def test_first_place_probability_is_preserved(self):
        """1着で足し上げると、元の1着確率に戻る。"""
        probs = trifecta_probs(PROB)
        for lane, p in PROB.items():
            total = sum(v for k, v in probs.items() if k.startswith(f"{lane}-"))
            self.assertAlmostEqual(total, p, places=9)


class RecommendTest(unittest.TestCase):
    def _odds(self):
        # 各買い目のオッズを「モデル確率どおり・控除率25%」に置く。
        # この状態ではEVが全部0.75になるので、1本だけ厚くした買い目が
        # 必ず先頭に来なければならない。
        probs = trifecta_probs(PROB)
        odds = {k: 0.75 / v for k, v in probs.items()}
        odds["4-5-6"] = odds["4-5-6"] * 3
        return odds

    def test_expected_value_is_prob_times_odds(self):
        """
        控除率を重ねて掛けないこと。オッズに既に入っている。

        prob は表示用に丸めてあるので、突き合わせは緩い許容で行う。
        見たいのは0.75が余分に掛かっていないかで、下3桁の一致ではない。
        """
        odds = self._odds()
        picks = recommend_trifecta(PROB, odds, limit=120)
        for pick in picks:
            self.assertAlmostEqual(pick["ev"], pick["prob"] * pick["odds"], delta=0.02)
            self.assertNotAlmostEqual(pick["ev"],
                                      pick["prob"] * pick["odds"] * 0.75, delta=0.02)

    def test_sorted_by_ev_not_by_probability(self):
        odds = self._odds()
        picks = recommend_trifecta(PROB, odds, limit=5)
        self.assertEqual(picks[0]["combo"], "4-5-6")
        evs = [p["ev"] for p in picks]
        self.assertEqual(evs, sorted(evs, reverse=True))

    def test_limit_is_respected(self):
        self.assertEqual(len(recommend_trifecta(PROB, self._odds(), limit=3)), 3)

    def test_skips_combos_without_odds(self):
        """オッズが欠けた買い目を、確率だけで推奨してはいけない。"""
        odds = {"1-2-3": 9.6}
        picks = recommend_trifecta(PROB, odds, limit=5)
        self.assertEqual([p["combo"] for p in picks], ["1-2-3"])


class BlendTest(unittest.TestCase):
    """
    公開する確率を市場へ引き戻す処理。

    **ここを壊すと、画面のEVだけが静かに大きくなる。** モデル単独に戻っても
    確率の合計は1.0のままで、表示も普通に見えるので気づけない。
    """
    MODEL = {1: 0.60, 2: 0.20, 3: 0.10, 4: 0.05, 5: 0.03, 6: 0.02}
    MARKET = {1: 0.40, 2: 0.25, 3: 0.15, 4: 0.10, 5: 0.06, 6: 0.04}

    def test_zero_weight_is_market(self):
        got = blend_with_market(self.MODEL, self.MARKET, 0.0)
        for lane, p in self.MARKET.items():
            self.assertAlmostEqual(got[lane], p, places=3)

    def test_full_weight_is_model(self):
        got = blend_with_market(self.MODEL, self.MARKET, 1.0)
        for lane, p in self.MODEL.items():
            self.assertAlmostEqual(got[lane], p, places=3)

    def test_sums_to_one(self):
        got = blend_with_market(self.MODEL, self.MARKET, BLEND_WEIGHT)
        self.assertAlmostEqual(sum(got.values()), 1.0, places=3)

    def test_pulled_toward_market(self):
        got = blend_with_market(self.MODEL, self.MARKET, 0.2)
        self.assertLess(got[1], self.MODEL[1])
        self.assertGreater(got[1], self.MARKET[1])


class BlendedPicksTest(unittest.TestCase):
    """買い目側の引き戻し。順位は動かさず、EVの目盛りだけを変える。"""

    def _odds(self):
        # 市場が「モデルどおり」ではない状態を作る。1本だけモデルが厚く見る目。
        probs = trifecta_probs(PROB)
        odds = {k: 0.75 / v for k, v in probs.items()}
        odds["4-5-6"] = odds["4-5-6"] * 4
        return odds

    def test_blending_shrinks_expected_value(self):
        odds = self._odds()
        full = recommend_trifecta(PROB, odds, limit=1, weight=1.0)[0]
        held = recommend_trifecta(PROB, odds, limit=1, weight=0.2)[0]
        self.assertEqual(full["combo"], held["combo"])
        self.assertLess(held["ev"], full["ev"])
        # 市場そのままなら控除率ぶん（1/1.335 ≒ 0.749）に寄る
        flat = recommend_trifecta(PROB, odds, limit=1, weight=0.0)[0]
        self.assertAlmostEqual(flat["ev"], 0.75, delta=0.02)

    def test_order_is_unchanged_by_weight(self):
        odds = self._odds()
        a = [p["combo"] for p in recommend_trifecta(PROB, odds, limit=10, weight=1.0)]
        b = [p["combo"] for p in recommend_trifecta(PROB, odds, limit=10, weight=0.2)]
        self.assertEqual(a, b)


class ScoreRaceTest(unittest.TestCase):
    RACERS = [
        {"lane": i, "class": "B1", "win_rate_all": 5.0, "win_rate_venue": 5.0,
         "avg_st": 0.16, "motor_in2_rate": 35.0, "boat_in2_rate": 35.0,
         "weight": 52.0, "f_count": 0, "in2_rate_all": 30.0}
        for i in range(1, 7)
    ]

    def test_picks_absent_without_odds(self):
        scores = score_race(self.RACERS, None)
        self.assertNotIn("picks", scores)

    def test_picks_present_with_odds(self):
        scores = score_race(self.RACERS, None, trifecta_odds={"1-2-3": 9.6})
        self.assertEqual(scores["picks"][0]["combo"], "1-2-3")

    def test_pub_prob_is_pulled_toward_market(self):
        """画面に出るのは pub_prob。市場が無い時間帯だけモデル単独になる。"""
        market = {1: 0.30, 2: 0.20, 3: 0.20, 4: 0.15, 5: 0.10, 6: 0.05}
        scores = score_race(self.RACERS, market)
        self.assertEqual(scores["blend_weight"], BLEND_WEIGHT)
        self.assertAlmostEqual(sum(scores["pub_prob"].values()), 1.0, places=2)
        raw = scores["model_prob"][1]
        self.assertLess(abs(scores["pub_prob"][1] - market[1]), abs(raw - market[1]))

    def test_pub_prob_falls_back_to_model_without_market(self):
        scores = score_race(self.RACERS, None)
        self.assertEqual(scores["pub_prob"], scores["model_prob"])


if __name__ == "__main__":
    unittest.main()
