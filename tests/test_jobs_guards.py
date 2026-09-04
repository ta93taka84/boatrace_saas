"""
収集ジョブの歯止めのテスト。

実行:
  py -3 -m unittest discover -s tests

ネットワークには出ない。get_active_venues と get_close_times を差し替えて、
「開催場が0場」のときに各ジョブが黙って正常終了しないことを確かめる。

ボートレースに開催0の日は無いので、0場は「今日は何も無い」ではなく
「パーサーが静かに空を返した」と読むべきものになる。ワークフローは
失敗時にしか通知しないので、ここで落ちないとその日の収集が丸ごと
失われても誰も気づけない。実際に一度この形で抜けていた。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jobs


class NoActiveVenues(unittest.TestCase):
    """開催場が取れないとき、各ジョブが異常終了すること。"""

    def setUp(self):
        # _close_schedule はプロセス内で使い回されるので、テスト間で持ち越さない
        jobs._SCHEDULE_CACHE.clear()
        self.addCleanup(jobs._SCHEDULE_CACHE.clear)

    def test_morning_exits(self):
        with mock.patch.object(jobs, "get_active_venues", return_value=[]):
            with self.assertRaises(SystemExit) as cm:
                jobs.morning("20260902")
        self.assertEqual(cm.exception.code, 1)

    def test_results_exits(self):
        with mock.patch.object(jobs, "get_active_venues", return_value=[]):
            with self.assertRaises(SystemExit) as cm:
                jobs.results("20260902")
        self.assertEqual(cm.exception.code, 1)

    def test_prerace_strict_exits(self):
        with mock.patch.object(jobs, "get_active_venues", return_value=[]):
            with self.assertRaises(SystemExit) as cm:
                jobs.prerace(30, "20260902", strict=True)
        self.assertEqual(cm.exception.code, 1)

    def test_prerace_loose_reports_problem(self):
        """
        ループ実行では途中で落とさない。落とすとその日の残り時間の収集が
        すべて失われるため。問題として返し、ループが最後にまとめて落とす。
        """
        with mock.patch.object(jobs, "get_active_venues", return_value=[]):
            problems = jobs.prerace(30, "20260902", strict=False)
        self.assertEqual(len(problems), 1)
        self.assertIn("0場", problems[0])

    def test_empty_schedule_is_not_cached(self):
        """
        空をキャッシュすると、一度の失敗でその日の残りのパスが全部それを
        使い回し、サイト側が直っても復帰できなくなる。
        """
        with mock.patch.object(jobs, "get_active_venues", return_value=[]):
            self.assertEqual(jobs._close_schedule("20260902"), [])
        self.assertNotIn("20260902", jobs._SCHEDULE_CACHE)

        venue = {"code": "05", "name": "多摩川"}
        with mock.patch.object(jobs, "get_active_venues", return_value=[venue]), \
             mock.patch.object(jobs, "get_close_times", return_value={1: "11:00"}):
            schedule = jobs._close_schedule("20260902")
        self.assertEqual(schedule, [(venue, {1: "11:00"})])
        self.assertIn("20260902", jobs._SCHEDULE_CACHE)


class NormalEmptyTargets(unittest.TestCase):
    """開催はあるが締切が近いレースが無い、は正常。落としてはならない。"""

    def setUp(self):
        jobs._SCHEDULE_CACHE.clear()
        self.addCleanup(jobs._SCHEDULE_CACHE.clear)

    def test_no_upcoming_race_is_not_a_problem(self):
        venue = {"code": "05", "name": "多摩川"}
        # 締切をありえない時刻に置いて、対象0レースを作る
        with mock.patch.object(jobs, "get_active_venues", return_value=[venue]), \
             mock.patch.object(jobs, "get_close_times", return_value={1: "00:01"}):
            problems = jobs.prerace(1, "20260902", strict=True)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
