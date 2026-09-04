"""
結果ページのスタート情報のテスト。

実行:
  py -3 -m unittest discover -s tests

ここが読めると、収集済みの全レースについて「艇番・進入コース・ST・着順」が
揃う。節間成績と直近の調子を、公式サイトを追加で叩かずに組める。

検証しているのは主に進入コースと艇番の対応で、ここがずれると
STと着順が別の艇に付く。前づけのあるレースでしか露見しないので、
通常のレースだけを見ていると気づけない。
"""
import sys
import unittest
import warnings
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from scraper import result as result_mod

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def parse(name: str) -> dict:
    """フィクスチャを get_result に通す。ネットワークには出ない。"""
    html = (FIXTURES / name).read_bytes()
    with mock.patch.object(result_mod, "fetch", return_value=html):
        return result_mod.get_result("20260825", "01", 1)


class NormalRace(unittest.TestCase):
    """枠なり進入（進入コース＝枠番）の通常レース。"""

    def setUp(self):
        self.race = parse("raceresult.html")
        self.start = self.race["start"]

    def test_six_boats(self):
        self.assertEqual(len(self.start), 6)

    def test_course_is_sequential(self):
        self.assertEqual([s["course"] for s in self.start], [1, 2, 3, 4, 5, 6])

    def test_lane_matches_course_when_no_maezuke(self):
        self.assertEqual([s["lane"] for s in self.start], [1, 2, 3, 4, 5, 6])

    def test_st_values(self):
        self.assertEqual(
            [s["st"] for s in self.start], [0.17, 0.24, 0.22, 0.22, 0.21, 0.15]
        )

    def test_kimarite_does_not_leak_into_st(self):
        """1着の要素には決まり手が同居する（'1 .17 逃げ'）。STを汚さないこと。"""
        self.assertEqual(self.race["kimarite"], "逃げ")
        self.assertEqual(self.start[0]["st"], 0.17)

    def test_no_flying(self):
        self.assertTrue(all(not s["flying"] for s in self.start))

    def test_st_in_plausible_range(self):
        for s in self.start:
            self.assertGreater(s["st"], 0.0)
            self.assertLess(s["st"], 1.0)


class Maezuke(unittest.TestCase):
    """
    前づけのあるレース。進入コースと枠番が一致しない。

    キャッシュ済みの結果ページ1,295レースのうち18.1%がこの形なので、
    例外ではない。進入コースを枠番で代用すると、5〜6レースに1回は
    違う艇の値を見ることになる。

    このフィクスチャは6号艇が2コースに入り、5コースの艇が1着になっている。
    """

    def setUp(self):
        self.race = parse("raceresult_maezuke.html")
        self.start = self.race["start"]

    def test_lane_order_differs_from_course_order(self):
        lanes = [s["lane"] for s in self.start]
        self.assertEqual(lanes, [1, 6, 2, 3, 4, 5])
        self.assertNotEqual(lanes, [1, 2, 3, 4, 5, 6])

    def test_course_is_still_sequential(self):
        self.assertEqual([s["course"] for s in self.start], [1, 2, 3, 4, 5, 6])

    def test_all_lanes_present_exactly_once(self):
        self.assertEqual(sorted(s["lane"] for s in self.start), [1, 2, 3, 4, 5, 6])

    def test_st_belongs_to_the_right_boat(self):
        by_lane = {s["lane"]: s for s in self.start}
        self.assertEqual(by_lane[6]["course"], 2)
        self.assertEqual(by_lane[6]["st"], 0.11)
        self.assertEqual(by_lane[2]["course"], 3)
        self.assertEqual(by_lane[2]["st"], 0.25)

    def test_kimarite_does_not_leak_when_winner_is_not_first_course(self):
        """
        決まり手は1着の艇の要素に同居する。この race の1着は5コースの
        4号艇なので、先頭以外の行で混入しないことを確かめる。
        """
        self.assertEqual(self.race["winner_lane"], 4)
        by_lane = {s["lane"]: s for s in self.start}
        self.assertEqual(by_lane[4]["course"], 5)
        self.assertEqual(by_lane[4]["st"], 0.18)


class Flying(unittest.TestCase):
    """
    フライングのあるレース。

    本番のフライングは失格なので、着順表からその艇が落ちる（着順欄が「Ｆ」）。
    スタート情報には残るので、start と finish で艇の集合が一致しない。
    """

    def setUp(self):
        self.race = parse("raceresult_flying.html")
        self.start = self.race["start"]

    def test_flying_st_is_negative(self):
        """
        F は大時計が0になる前に出たという意味なので、STは負で返す。
        符号を落とすと、最も良いSTと最も悪いSTが同じ値になる。
        """
        flying = [s for s in self.start if s["flying"]]
        self.assertEqual(len(flying), 1)
        self.assertEqual(flying[0]["lane"], 4)
        self.assertEqual(flying[0]["st"], -0.03)

    def test_others_are_not_flagged(self):
        normal = [s for s in self.start if not s["flying"]]
        self.assertEqual(len(normal), 5)
        self.assertTrue(all(s["st"] > 0 for s in normal))

    def test_flying_boat_is_dropped_from_finish(self):
        self.assertIn(4, {s["lane"] for s in self.start})
        self.assertNotIn(4, self.race["finish"])
        self.assertEqual(self.race["winner_lane"], 6)


class AbsentBoat(unittest.TestCase):
    """欠場があるレース。欠けた艇は並ばず、残りが上から詰めてコースを取る。"""

    def setUp(self):
        self.start = parse("raceresult_absent.html")["start"]

    def test_five_boats(self):
        self.assertEqual(len(self.start), 5)

    def test_absent_lane_is_missing(self):
        lanes = [s["lane"] for s in self.start]
        self.assertEqual(lanes, [1, 2, 3, 4, 6])
        self.assertNotIn(5, lanes)

    def test_courses_are_packed_without_gap(self):
        """欠場した艇のぶんコースが飛ぶことはない。6号艇は5コース。"""
        self.assertEqual([s["course"] for s in self.start], [1, 2, 3, 4, 5])
        by_lane = {s["lane"]: s["course"] for s in self.start}
        self.assertEqual(by_lane[6], 5)


class Consistency(unittest.TestCase):
    """スタート情報と着順が同じ艇集合を指していること。"""

    def test_start_and_finish_cover_the_same_lanes(self):
        for name in ("raceresult.html", "raceresult_maezuke.html",
                     "raceresult_flying.html", "raceresult_absent.html"):
            with self.subTest(fixture=name):
                race = parse(name)
                start_lanes = {s["lane"] for s in race["start"]}
                finish_lanes = set(race["finish"])
                # 失格は着順から落ちるので、着順はスタートの部分集合になる
                self.assertTrue(finish_lanes <= start_lanes,
                                f"{finish_lanes} ⊄ {start_lanes}")
                self.assertTrue(start_lanes)


if __name__ == "__main__":
    unittest.main()
