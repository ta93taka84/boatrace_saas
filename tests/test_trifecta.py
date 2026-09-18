"""
三連単の確率と推奨買い目の組み立てを固定する。

**ここは静かに間違う。** 確率の展開も期待値の式も、値域はもっともらしいまま
中身だけが狂う。実際に起こりうるのは次の3つで、どれも画面上は普通に見える。

1. 順序を無視して組み合わせの確率にしてしまう（1-2-3 と 3-2-1 が同じ値になる）
2. 期待値に控除率を掛けてしまう（オッズには既に控除が入っているので二重に引く）
3. 推奨をEV順でなく確率順に並べてしまう（本命ばかり並び、推奨の意味が消える）

三連複を足したことで、同じ性質の落とし穴が2つ増えた。どちらも画面は普通に見える。

4. 三連複の確率を、三連単の一部（例えば 1-2-3 の並びだけ）で作ってしまう。
   6通りの和にならないので、当たる確率を6分の1近くまで小さく見積もる。
5. 三連複のオッズを三連単から計算で作ってしまう。別勘定の投票なので、
   画面に出る配当が実際に払い戻される額と食い違う。

実行:
  py -3 -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.scoring import (BLEND_WEIGHT, blend_with_market, order_corr,
                             recommend_trifecta, recommend_trio, score_race,
                             trifecta_probs, trio_probs)

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


class OrderCorrelationTest(unittest.TestCase):
    """
    着順相関の補正。**ここが壊れても画面は普通に見える。**

    補正表は「実測回数 ÷ 独立な展開が与える期待回数」で、1.0なら偏り無し。
    表が読めなくなれば黙って補正なしに戻り、正規化を落とせば確率の合計が
    1でなくなる。どちらも値域はもっともらしいままなので、ここで固定する。
    """

    NONE = ({}, {})

    def test_empty_table_is_the_plain_expansion(self):
        """表が空なら素の Plackett-Luce に戻る。壊れずに素通りすること。"""
        probs = trifecta_probs(PROB, self.NONE)
        self.assertEqual(len(probs), 120)
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=9)
        # P(1⇒2⇒3) = 0.45 × 0.18/0.55 × 0.14/0.37
        self.assertAlmostEqual(probs["1-2-3"],
                               0.45 * (0.18 / 0.55) * (0.14 / 0.37), places=9)

    def test_correction_shifts_second_place(self):
        """補正を掛けた組み合わせが、掛けていない組み合わせより厚くなる。"""
        plain = trifecta_probs(PROB, self.NONE)
        fixed = trifecta_probs(PROB, ({(1, 2): 2.0}, {}))
        self.assertGreater(fixed["1-2-3"] / plain["1-2-3"],
                           fixed["1-3-2"] / plain["1-3-2"])

    def test_missing_pairs_are_treated_as_no_bias(self):
        """表に無い組み合わせは1.0。全部欠けていれば素の展開と一致する。"""
        plain = trifecta_probs(PROB, self.NONE)
        partial = trifecta_probs(PROB, ({(1, 2): 1.0}, {(2, 3): 1.0}))
        for combo, p in plain.items():
            self.assertAlmostEqual(partial[combo], p, places=9)

    def test_normalization_survives_a_lopsided_table(self):
        """偏った表でも合計は1のまま。"""
        r2 = {(a, b): 5.0 for a in range(1, 7) for b in range(1, 7) if a != b and b > 3}
        probs = trifecta_probs(PROB, (r2, {}))
        self.assertEqual(len(probs), 120)
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=9)

    def test_first_place_probability_survives_correction(self):
        """
        **補正は2着以降の形だけを変える。1着の確率は動かしてはいけない。**
        画面には勝率と三連単の両方を出しているので、ここがずれると
        同じレースについて食い違う数字を並べることになる。
        """
        r2 = {(a, b): 3.0 for a in range(1, 7) for b in range(1, 7) if a != b and b > 3}
        probs = trifecta_probs(PROB, (r2, {(2, 3): 4.0}))
        for lane, p in PROB.items():
            total = sum(v for k, v in probs.items() if k.startswith(f"{lane}-"))
            self.assertAlmostEqual(total, p, places=9)


class DeployedTableTest(unittest.TestCase):
    """
    配備されている補正表そのものを見る。

    このファイルが消えると三連単は黙って補正なしに戻る。検証で
    標準誤差の6〜10倍の改善が出ている部分なので、消失を失敗として拾う。
    作り直しは `py -3 experiment.py fit-order`。
    """

    def test_table_is_present_and_well_formed(self):
        second, third = order_corr()
        self.assertTrue(second, "scraper/order_corr.json が無い（fit-order で作る）")
        self.assertTrue(third)
        for table in (second, third):
            for key, value in table.items():
                self.assertEqual(len(key), 2)
                self.assertTrue(all(1 <= lane <= 6 for lane in key), key)
                self.assertGreater(value, 0.0, key)
                self.assertLess(value, 10.0, key)

    def test_deployed_table_is_used_by_default(self):
        """corr を渡さなければ配備の表が効く。素の展開に戻っていないこと。"""
        self.assertNotEqual(trifecta_probs(PROB), trifecta_probs(PROB, ({}, {})))

    def test_outer_boats_follow_each_other(self):
        """
        補正の向きを固定する。4号艇が1着のとき、2着は6号艇が来やすく
        1号艇は沈む。符号が反転していたら、表の作り方か読み方が壊れている。
        """
        second, _ = order_corr()
        self.assertGreater(second[(4, 6)], 1.5)
        self.assertLess(second[(4, 1)], 1.0)


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


class TrioProbsTest(unittest.TestCase):
    """三連複の確率は、三連単を着順ごとに畳んだものでなければならない。"""

    def test_covers_all_20_and_sums_to_one(self):
        probs = trio_probs(PROB)
        self.assertEqual(len(probs), 20)
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=9)

    def test_is_exactly_the_folded_trifecta(self):
        """
        **ここが三連複の核心。** 着順を問わない的の確率は、着順を区別した
        6通りの確率の和そのものである。近似ではないので、一致は厳密でよい。
        片方だけ別の組み立て方に変えたら、ここで落ちる。
        """
        tri = trifecta_probs(PROB)
        folded = {}
        for combo, p in tri.items():
            key = "-".join(sorted(combo.split("-"), key=int))
            folded[key] = folded.get(key, 0.0) + p
        got = trio_probs(PROB)
        self.assertEqual(sorted(got), sorted(folded))
        for key, want in folded.items():
            self.assertAlmostEqual(got[key], want, places=12, msg=key)

    def test_combos_are_ascending(self):
        for combo in trio_probs(PROB):
            lanes = [int(x) for x in combo.split("-")]
            self.assertEqual(lanes, sorted(lanes), f"昇順でない: {combo}")

    def test_bigger_than_any_single_order(self):
        """
        着順を問わないぶん、必ずどの並び単独よりも当たりやすい。
        三連単の1本をそのまま三連複として出す間違いは、ここで落ちる。
        """
        tri = trifecta_probs(PROB)
        trio = trio_probs(PROB)
        for combo, p in trio.items():
            a, b, c = combo.split("-")
            self.assertGreater(p, tri[f"{a}-{b}-{c}"], combo)

    def test_first_place_probability_is_not_disturbed(self):
        """
        畳んでも1着の確率は動かない。ある艇を含む的の確率の和は、
        その艇が3着以内に入る確率になる（1着率ではない）ので、
        ここでは三連単側の総和との一致だけを見る。
        """
        tri = trifecta_probs(PROB)
        trio = trio_probs(PROB)
        self.assertAlmostEqual(sum(tri.values()), sum(trio.values()), places=12)


class RecommendTrioTest(unittest.TestCase):
    def _odds(self):
        # 三連複20通りを「モデル確率どおり・控除率25%」に置く。
        # EVが全部0.75になるので、1本だけ厚くした目が先頭に来るはず。
        probs = trio_probs(PROB)
        odds = {k: 0.75 / v for k, v in probs.items()}
        odds["4-5-6"] = odds["4-5-6"] * 3
        return odds

    def test_expected_value_is_prob_times_odds(self):
        """控除率を重ねて掛けないこと。オッズに既に入っている。"""
        picks = recommend_trio(PROB, self._odds(), limit=20)
        self.assertEqual(len(picks), 20)
        for pick in picks:
            self.assertAlmostEqual(pick["ev"], pick["prob"] * pick["odds"], delta=0.02)
            self.assertNotAlmostEqual(pick["ev"],
                                      pick["prob"] * pick["odds"] * 0.75, delta=0.02)

    def test_sorted_by_ev_not_by_probability(self):
        picks = recommend_trio(PROB, self._odds(), limit=3)
        self.assertEqual(picks[0]["combo"], "4-5-6")
        evs = [p["ev"] for p in picks]
        self.assertEqual(evs, sorted(evs, reverse=True))

    def test_limit_is_respected(self):
        self.assertEqual(len(recommend_trio(PROB, self._odds(), limit=3)), 3)

    def test_skips_combos_without_odds(self):
        """オッズが欠けた買い目を、確率だけで推奨してはいけない。"""
        picks = recommend_trio(PROB, {"1-2-3": 4.3}, limit=5)
        self.assertEqual([p["combo"] for p in picks], ["1-2-3"])

    def test_blends_against_the_trio_market(self):
        """
        **引き戻す相手は三連複のオッズでなければならない。** 三連単を畳んだ
        確率で引き戻すと、画面のEVがどの市場に対する値か分からなくなる。

        三連複だけを一方向に歪めたオッズ表を渡し、混合後の確率がその歪みの
        向きへ動くことを見る。三連単側を見ていたら動かない。
        """
        odds = self._odds()
        # 1-2-3 のオッズだけ極端に薄くする＝市場はこの目を本命と見ている
        odds["1-2-3"] = 1.01
        full = recommend_trio(PROB, odds, limit=20, weight=1.0)
        blended = recommend_trio(PROB, odds, limit=20, weight=0.2)
        p_full = next(p["prob"] for p in full if p["combo"] == "1-2-3")
        p_blend = next(p["prob"] for p in blended if p["combo"] == "1-2-3")
        self.assertGreater(p_blend, p_full)

    def test_blending_shrinks_expected_value(self):
        odds = self._odds()
        full = recommend_trio(PROB, odds, limit=1, weight=1.0)
        blended = recommend_trio(PROB, odds, limit=1, weight=BLEND_WEIGHT)
        self.assertLess(blended[0]["ev"], full[0]["ev"])


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


class ProbRankingTest(unittest.TestCase):
    """
    トップページの確率ランキング用の並び（by="prob"）を固定する。

    **推奨買い目（EV順）と取り違えると、どちらの画面も静かに壊れる。**
    確率順は当たりやすい目が並ぶので、推奨として出すと本命ばかりになり、
    EV順をランキングに出すと「最も確率の高い買い目」と称して穴目が並ぶ。
    どちらも値域はもっともらしく、画面上は普通に見える。
    """

    def _odds(self):
        # RecommendTest と同じ置き方。EVが全部0.75の中で 4-5-6 だけ厚い。
        # 確率順ならこの細工は効かないので、先頭は本命のままでなければならない。
        probs = trifecta_probs(PROB)
        odds = {k: 0.75 / v for k, v in probs.items()}
        odds["4-5-6"] = odds["4-5-6"] * 3
        return odds

    def test_prob_order_differs_from_ev_order(self):
        odds = self._odds()
        by_ev = recommend_trifecta(PROB, odds, limit=5, by="ev")
        by_prob = recommend_trifecta(PROB, odds, limit=5, by="prob")
        self.assertEqual(by_ev[0]["combo"], "4-5-6")
        self.assertNotEqual(by_prob[0]["combo"], "4-5-6")
        probs = [p["prob"] for p in by_prob]
        self.assertEqual(probs, sorted(probs, reverse=True))

    def test_default_stays_ev(self):
        """既定を確率順に倒さないこと。推奨買い目はEV順である。"""
        odds = self._odds()
        self.assertEqual(recommend_trifecta(PROB, odds, limit=1)[0]["combo"], "4-5-6")
        self.assertEqual(recommend_trio(PROB, {"4-5-6": 200.0, "1-2-3": 1.1},
                                        limit=1)[0]["combo"], "4-5-6")

    def test_trio_prob_order(self):
        odds = {k: 0.75 / v for k, v in trio_probs(PROB).items()}
        picks = recommend_trio(PROB, odds, limit=20, by="prob")
        self.assertEqual(len(picks), 20)
        probs = [p["prob"] for p in picks]
        self.assertEqual(probs, sorted(probs, reverse=True))

    def test_score_race_carries_both_orders(self):
        racers = ScoreRaceTest.RACERS
        tri = {k: 0.75 / v for k, v in trifecta_probs(PROB).items()}
        trio = {k: 0.75 / v for k, v in trio_probs(PROB).items()}
        scores = score_race(racers, None, trifecta_odds=tri, trio_odds=trio)
        for key in ("picks", "prob_picks", "trio_picks", "trio_prob_picks"):
            self.assertIn(key, scores)
        self.assertEqual([p["combo"] for p in scores["prob_picks"]],
                         [p["combo"] for p in
                          recommend_trifecta(scores["model_prob"], tri,
                                             limit=len(scores["prob_picks"]),
                                             weight=BLEND_WEIGHT, by="prob")])

    def test_prob_picks_absent_without_odds(self):
        """オッズが無ければランキングにも出さない。確率だけで並べない。"""
        scores = score_race(ScoreRaceTest.RACERS, None)
        self.assertNotIn("prob_picks", scores)
        self.assertNotIn("trio_prob_picks", scores)

    def test_same_blend_as_recommendations(self):
        """
        ランキングと推奨で同じ目に違う確率を出さないこと。
        引き戻しの重みが片方だけずれると、同じレースの同じ買い目が
        トップページと詳細画面で違う確率になる。
        """
        tri = {k: 0.75 / v for k, v in trifecta_probs(PROB).items()}
        scores = score_race(ScoreRaceTest.RACERS, None, trifecta_odds=tri)
        by_combo = {p["combo"]: p["prob"] for p in scores["picks"]}
        shared = [p for p in scores["prob_picks"] if p["combo"] in by_combo]
        for pick in shared:
            self.assertEqual(pick["prob"], by_combo[pick["combo"]])


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

    def test_trio_picks_absent_without_trio_odds(self):
        scores = score_race(self.RACERS, None, trifecta_odds={"1-2-3": 9.6})
        self.assertNotIn("trio_picks", scores)

    def test_trio_picks_present_with_trio_odds(self):
        scores = score_race(self.RACERS, None, trio_odds={"1-2-3": 4.3})
        self.assertEqual(scores["trio_picks"][0]["combo"], "1-2-3")

    def test_each_ticket_type_survives_the_other_failing(self):
        """
        **片方のオッズが取れなくても、もう片方の買い目を落とさないこと。**
        三連単と三連複は別ページなので、片方だけ取れる経路が実際にある。
        ここで巻き添えにすると、締切前に出せたはずの買い目が消える。
        """
        only_tri = score_race(self.RACERS, None, trifecta_odds={"1-2-3": 9.6})
        self.assertIn("picks", only_tri)
        self.assertNotIn("trio_picks", only_tri)

        only_trio = score_race(self.RACERS, None, trio_odds={"1-2-3": 4.3})
        self.assertIn("trio_picks", only_trio)
        self.assertNotIn("picks", only_trio)

        both = score_race(self.RACERS, None, trifecta_odds={"1-2-3": 9.6},
                          trio_odds={"1-2-3": 4.3})
        self.assertIn("picks", both)
        self.assertIn("trio_picks", both)

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
