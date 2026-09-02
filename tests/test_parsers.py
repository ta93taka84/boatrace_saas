"""
パーサーの回帰テスト。

実行:
  py -3 -m unittest discover -s tests

tests/fixtures/ に置いた実際のHTMLを使う。ネットワークに出ないので
いつでも即座に走る。目的は「自分の変更でパーサーを壊さないこと」の担保。

サイト側のHTML変更はフィクスチャが古いままなので、このテストでは
検知できない。そちらは jobs.py の健全性チェックが実行時に見ている
（特にオッズのoverroundが約1.334から外れたら構造変更を疑う）。
"""
import sys
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from scraper import beforeinfo, odds, racelist, result
from scraper.scoring import estimate_win_prob, score_race

FIXTURES = Path(__file__).parent / "fixtures"


def soup_of(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_bytes(), "lxml")


class TestRacelist(unittest.TestCase):
    def setUp(self):
        self.racers = [
            r for r in
            (racelist._parse_racer_row(tb) for tb in soup_of("racelist.html").select("tbody.is-fs12"))
            if r
        ]

    def test_six_racers(self):
        self.assertEqual(len(self.racers), 6)

    def test_lanes_are_one_through_six(self):
        self.assertEqual(sorted(r["lane"] for r in self.racers), [1, 2, 3, 4, 5, 6])

    def test_names_are_japanese_not_numbers(self):
        """1セル3値の構造を取り違えると、氏名欄に登録番号が入る。"""
        for r in self.racers:
            self.assertTrue(r["name"], f"lane {r['lane']} の氏名が空")
            self.assertFalse(
                r["name"].replace(" ", "").isdigit(),
                f"lane {r['lane']} の氏名が数字: {r['name']!r}",
            )

    def test_class_is_a_grade_label(self):
        for r in self.racers:
            self.assertIn(r["class"], ("A1", "A2", "B1", "B2"), f"級別が不正: {r['class']!r}")

    def test_rates_are_in_plausible_range(self):
        """列がずれると勝率欄に3連対率などが入り、値域を外れる。"""
        for r in self.racers:
            self.assertGreater(r["win_rate_all"], 0.0, f"lane {r['lane']} の全国勝率が0")
            self.assertLessEqual(r["win_rate_all"], 10.0, "全国勝率は10点満点")
            self.assertLessEqual(r["in2_rate_all"], 100.0)
            self.assertTrue(0.0 < r["avg_st"] < 1.0, f"平均STが不正: {r['avg_st']}")
            self.assertTrue(0 < r["motor_no"] < 200, f"モーター番号が不正: {r['motor_no']}")
            self.assertLessEqual(r["motor_in2_rate"], 100.0)

    def test_registration_id_is_numeric(self):
        for r in self.racers:
            self.assertTrue(r["racer_id"].isdigit(), f"登録番号が不正: {r['racer_id']!r}")


class TestOdds(unittest.TestCase):
    def setUp(self):
        self.odds_map = odds._parse_trifecta_odds(soup_of("odds3t.html"))

    def test_all_120_combinations(self):
        """rowspanの持ち越しを誤ると組み合わせが欠ける。"""
        self.assertEqual(len(self.odds_map), 120)

    def test_twenty_per_first_lane(self):
        for lane in range(1, 7):
            n = sum(1 for k in self.odds_map if k.startswith(f"{lane}-"))
            self.assertEqual(n, 20, f"{lane}着頭の組み合わせが{n}件")

    def test_combinations_have_no_duplicate_lane(self):
        for combo in self.odds_map:
            lanes = combo.split("-")
            self.assertEqual(len(set(lanes)), 3, f"同じ艇が重複: {combo}")

    def test_overround_matches_takeout_rate(self):
        """
        インプライド確率の合計は控除率25%と整合して約1.334になる。
        取りこぼしがあればこの値が下がるので、最も鋭い検知手段になる。
        """
        _, overround = odds._market_win_prob(self.odds_map)
        self.assertAlmostEqual(overround, 1.0 / 0.75, delta=0.05)

    def test_market_prob_sums_to_one(self):
        market_prob, _ = odds._market_win_prob(self.odds_map)
        self.assertAlmostEqual(sum(market_prob.values()), 1.0, places=3)
        self.assertEqual(sorted(market_prob), [1, 2, 3, 4, 5, 6])


class TestBeforeinfo(unittest.TestCase):
    def setUp(self):
        self.soup = soup_of("beforeinfo.html")

    def test_exhibit_times_are_plausible(self):
        racers = beforeinfo._parse_racers(self.soup)
        self.assertEqual(len(racers), 6)
        for r in racers:
            self.assertIsNotNone(r["exhibit_time"], f"lane {r['lane']} の展示タイムが無い")
            self.assertTrue(
                6.0 < r["exhibit_time"] < 8.0,
                f"展示タイムが値域外: {r['exhibit_time']}",
            )

    def test_weather_fields(self):
        w = beforeinfo._parse_weather(self.soup)
        self.assertTrue(w["weather"], "天候が取れていない")
        self.assertIsNotNone(w["wind_speed"])
        self.assertIsNotNone(w["wave_height"])
        self.assertIsNotNone(w["temperature"])


class TestResult(unittest.TestCase):
    def setUp(self):
        self.soup = soup_of("raceresult.html")

    def test_finish_order(self):
        finish = result._parse_finish(self.soup)
        self.assertGreaterEqual(len(finish), 3, "着順が3艇ぶんも取れていない")
        self.assertIn(1, finish.values(), "1着が存在しない")
        for lane, rank in finish.items():
            self.assertTrue(1 <= lane <= 6)
            self.assertTrue(1 <= rank <= 6)

    def test_payouts(self):
        payouts = result._parse_payouts(self.soup)
        self.assertIn("3連単", payouts)
        tri = payouts["3連単"]
        self.assertGreater(tri["payout"], 0)
        self.assertRegex(tri["combo"], r"^\d-\d-\d$")

    def test_kimarite_has_no_label_prefix(self):
        k = result._parse_kimarite(self.soup)
        if k:
            self.assertNotIn("決まり手", k, "ラベルが除去されていない")


class TestScoring(unittest.TestCase):
    def _racers(self, **overrides):
        base = [
            {"lane": i, "class": "B1", "win_rate_all": 5.0,
             "motor_in2_rate": 35.0, "avg_st": 0.16}
            for i in range(1, 7)
        ]
        for lane, patch in overrides.items():
            base[int(lane) - 1].update(patch)
        return base

    def test_probabilities_sum_to_one(self):
        probs = estimate_win_prob(self._racers())
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=3)

    def test_inner_lane_favoured_when_all_else_equal(self):
        probs = estimate_win_prob(self._racers())
        self.assertGreater(probs[1], probs[2])
        self.assertGreater(probs[2], probs[5])

    def test_class_raises_probability(self):
        """級別を無視していた回帰を防ぐ。A1はB2より高く出るはず。"""
        weak = estimate_win_prob(self._racers(**{"3": {"class": "B2"}}))[3]
        strong = estimate_win_prob(self._racers(**{"3": {"class": "A1"}}))[3]
        self.assertGreater(strong, weak)

    def test_ev_is_ratio_against_market(self):
        """
        EVは予測勝率と市場勝率の比。両者が一致すれば、
        どの艇も控除率ぶん(0.75)に収束しなければならない。
        """
        racers = self._racers()
        model = estimate_win_prob(racers)
        scored = score_race(racers, model)
        for lane, ev in scored["ev"].items():
            self.assertAlmostEqual(ev, 0.75, delta=0.01, msg=f"lane {lane}")

    def test_ev_differs_per_lane(self):
        """
        全艇同値になる計算式の破綻を防ぐ。市場が均等配分なら、
        コース差があるぶんEVは艇ごとに異なるはず。
        """
        racers = self._racers()
        flat_market = {i: 1 / 6 for i in range(1, 7)}
        evs = score_race(racers, flat_market)["ev"]
        self.assertGreater(len(set(evs.values())), 1, "全艇のEVが同じ値になっている")


if __name__ == "__main__":
    unittest.main()
