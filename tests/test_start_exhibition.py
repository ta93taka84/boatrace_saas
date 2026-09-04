"""
直前情報ページのスタート展示のテスト。

実行:
  py -3 -m unittest discover -s tests

**これは締切前に分かる情報。** 本番の進入コースはレースが終わるまで
分からないので、予測の特徴量にできる進入情報はこれだけになる。

本番のスタート（tests/test_start_info.py）とは別物。同じ
.table1_boatImage1 というクラスで描かれているので取り違えやすい。
実際に一度取り違えて、展示のページを結果ページとして数えた。
その区別をここで固定する。
"""
import io
import sys
import unittest
import warnings
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from scraper import beforeinfo as before_mod
from scraper import result as result_mod

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def parse(name: str) -> dict:
    html = (FIXTURES / name).read_bytes()
    with mock.patch.object(before_mod, "fetch", return_value=html):
        return before_mod.get_beforeinfo("20260825", "01", 1)


class StraightEntry(unittest.TestCase):
    """枠なり進入の展示。"""

    def setUp(self):
        self.ex = parse("beforeinfo.html")["start_exhibition"]

    def test_six_boats(self):
        self.assertEqual(len(self.ex), 6)

    def test_course_is_sequential(self):
        self.assertEqual([s["course"] for s in self.ex], [1, 2, 3, 4, 5, 6])

    def test_lane_matches_course(self):
        self.assertEqual([s["lane"] for s in self.ex], [1, 2, 3, 4, 5, 6])

    def test_st_values(self):
        self.assertEqual(
            [s["st"] for s in self.ex], [0.02, 0.19, 0.07, 0.04, 0.07, 0.07]
        )

    def test_nothing_marked_early(self):
        self.assertTrue(all(not s["early"] for s in self.ex))


class MaezukeAndEarly(unittest.TestCase):
    """
    展示で前づけがあり、早出しも出ているレース。

    展示の早出しには罰則が無いのでありふれている。キャッシュ実測で
    展示1,318件に対して本番は24件しかない。ここを本番のフライングと
    同じものとして扱うと、失格でも何でもない艇に印を付けることになる。
    """

    def setUp(self):
        self.ex = parse("beforeinfo_maezuke.html")["start_exhibition"]

    def test_lane_order_differs_from_course_order(self):
        self.assertEqual([s["lane"] for s in self.ex], [1, 2, 3, 5, 4, 6])

    def test_all_lanes_present_exactly_once(self):
        self.assertEqual(sorted(s["lane"] for s in self.ex), [1, 2, 3, 4, 5, 6])

    def test_early_start_is_negative(self):
        early = [s for s in self.ex if s["early"]]
        self.assertEqual(len(early), 2)
        for s in early:
            self.assertLess(s["st"], 0.0)
        self.assertEqual(sorted(s["st"] for s in early), [-0.03, -0.02])

    def test_early_belongs_to_the_right_boat(self):
        by_course = {s["course"]: s for s in self.ex}
        self.assertEqual(by_course[2]["lane"], 2)
        self.assertEqual(by_course[2]["st"], -0.03)
        self.assertEqual(by_course[4]["lane"], 5)
        self.assertEqual(by_course[4]["st"], -0.02)

    def test_swapped_pair_keeps_its_own_st(self):
        """4号艇と5号艇が入れ替わっている。STが相手のものにならないこと。"""
        by_lane = {s["lane"]: s for s in self.ex}
        self.assertEqual(by_lane[5]["course"], 4)
        self.assertEqual(by_lane[4]["course"], 5)
        self.assertEqual(by_lane[4]["st"], 0.07)


class BeforeExhibition(unittest.TestCase):
    """展示がまだ行われていないときは空リスト。落ちないこと。"""

    def test_empty_when_no_start_table(self):
        soup = BeautifulSoup("<html><body><p>まだ</p></body></html>", "lxml")
        self.assertEqual(before_mod._parse_start_exhibition(soup), [])


class NotTheSameAsRaceStart(unittest.TestCase):
    """
    展示と本番を取り違えないこと。

    別のキーで返し、別の名前の印を持つ。展示は early（罰則なし）、
    本番は flying（失格）。
    """

    def test_keys_are_distinct(self):
        ex = parse("beforeinfo.html")
        self.assertIn("start_exhibition", ex)
        self.assertNotIn("start", ex)

        html = (FIXTURES / "raceresult.html").read_bytes()
        with mock.patch.object(result_mod, "fetch", return_value=html):
            race = result_mod.get_result("20260825", "01", 1)
        self.assertIn("start", race)
        self.assertNotIn("start_exhibition", race)

    def test_flags_are_named_differently(self):
        ex = parse("beforeinfo_maezuke.html")["start_exhibition"]
        self.assertIn("early", ex[0])
        self.assertNotIn("flying", ex[0])

        html = (FIXTURES / "raceresult_flying.html").read_bytes()
        with mock.patch.object(result_mod, "fetch", return_value=html):
            start = result_mod.get_result("20260825", "01", 1)["start"]
        self.assertIn("flying", start[0])
        self.assertNotIn("early", start[0])


if __name__ == "__main__":
    unittest.main()
