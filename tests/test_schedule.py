"""
開催場一覧と締切時刻のパーサーのテスト。

実行:
  py -3 -m unittest discover -s tests

**この2つは全ジョブの起点である。** どのレースを、どの順で、いつまでに
取りに行くかは、すべてここの戻り値から決まる。にもかかわらず、これまで
実際のHTMLに対する回帰テストが無く、jobs側のテストでは常にモックしていた。

静かに空を返す壊れ方が一番怖い。開催場0は「今日は開催が無い」ではなく
「パーサーが空を返した」であり（ボートレースに開催0の日は無い）、締切時刻が
取れなければ巡回の対象が0レースになる。どちらも例外を投げないので、
上流で気づけない。ここで実HTMLに固定しておく。

tests/fixtures/index.html      2026-08-25 の開催場一覧（本日のレース）
tests/fixtures/raceindex.html  同日 桐生のレース一覧（締切時刻）
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scraper.schedule as schedule
from scraper.schedule import VENUES, get_active_venues, get_close_times

FIXTURES = Path(__file__).parent / "fixtures"


def _with(name):
    """ネットワークへは出ない。fetch を固定したHTMLに差し替える。"""
    html = (FIXTURES / name).read_bytes() if name else b"<html></html>"
    return mock.patch.object(schedule, "fetch", return_value=html)


class ActiveVenues(unittest.TestCase):
    def test_parses_the_venues_holding_races(self):
        with _with("index.html"):
            venues = get_active_venues("20260825")
        self.assertEqual([v["code"] for v in venues],
                         ["01", "03", "06", "08", "09", "10", "13",
                          "15", "17", "18", "20", "21", "22"])
        for v in venues:
            self.assertEqual(v["name"], VENUES[v["code"]])

    def test_navigation_links_are_not_counted_as_venues(self):
        """
        ページの上部には全24場へのリンクが並んでいる。それを開催場として
        数えると、開催していない場の出走表を取りに行き、1日あたり
        130リクエストほどを空振りに使う。
        """
        with _with("index.html"):
            venues = get_active_venues("20260825")
        self.assertLess(len(venues), 24, "ナビゲーションのリンクを数えている")

    def test_no_duplicates(self):
        with _with("index.html"):
            codes = [v["code"] for v in get_active_venues("20260825")]
        self.assertEqual(len(codes), len(set(codes)))

    def test_empty_page_returns_empty(self):
        """
        空を返すこと自体は正しい。**異常だと判断するのは呼び出し側**で、
        jobs.py が「開催場0は異常」として落とす（tests/test_jobs_guards.py）。
        ここで例外を投げると、その判断が二重になる。
        """
        with _with(None):
            self.assertEqual(get_active_venues("20260825"), [])


class CloseTimes(unittest.TestCase):
    def setUp(self):
        with _with("raceindex.html"):
            self.times = get_close_times("20260825", "01")

    def test_twelve_races(self):
        self.assertEqual(sorted(self.times), list(range(1, 13)))

    def test_values_are_hhmm(self):
        for rno, t in self.times.items():
            self.assertRegex(t, r"^\d{1,2}:\d{2}$", f"{rno}R")

    def test_times_increase_with_race_number(self):
        """
        締切順に取るしくみが、この並びに依存している。逆順や欠番が入ると
        締切間際のレースが順番待ちの最後尾に回る。
        """
        ordered = [self.times[r] for r in range(1, 13)]
        self.assertEqual(ordered, sorted(ordered))

    def test_intervals_are_plausible(self):
        """
        2列目を読み違えて別の時刻（発走時刻や本日の日付）を拾っていないか。
        レース間隔は20〜60分に収まる。
        """
        mins = [int(h) * 60 + int(m)
                for h, m in (t.split(":") for t in
                             (self.times[r] for r in range(1, 13)))]
        gaps = [b - a for a, b in zip(mins, mins[1:])]
        for g in gaps:
            self.assertTrue(20 <= g <= 60, f"レース間隔が {g}分")

    def test_empty_page_returns_empty(self):
        with _with(None):
            self.assertEqual(get_close_times("20260825", "01"), {})


if __name__ == "__main__":
    unittest.main()
