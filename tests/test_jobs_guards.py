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


class DeadlineOrder(unittest.TestCase):
    """
    締切の早いレースから取ること。

    場ごとに並べたままだと、2分後に締切のレースが10レース待ちの最後尾に
    回る。1レースあたり数秒かかるので、締切を過ぎてからオッズが入る。
    実測（2026-09-09）で、その日オッズが取れた90レースのうち5レースが
    締切後、11レースが締切5分前だった。**締切を過ぎた予測は誰も使えない。**
    """

    def setUp(self):
        jobs._SCHEDULE_CACHE.clear()
        self.addCleanup(jobs._SCHEDULE_CACHE.clear)

    def test_targets_are_fetched_in_deadline_order(self):
        from datetime import datetime, timedelta

        now = datetime.now()
        # 場の並び（A→B）と締切の並び（B→A）が逆になるように置く
        far = (now + timedelta(minutes=25)).strftime("%H:%M")
        near = (now + timedelta(minutes=5)).strftime("%H:%M")
        venues = [{"code": "01", "name": "遅い場"}, {"code": "02", "name": "早い場"}]
        times = {"01": {1: far}, "02": {1: near}}

        fetched = []

        def odds(date_str, venue_code, rno):
            fetched.append(venue_code)
            return None

        with mock.patch.object(jobs, "get_active_venues", return_value=venues),              mock.patch.object(jobs, "get_close_times",
                               side_effect=lambda d, code: times[code]),              mock.patch.object(jobs, "get_beforeinfo", return_value=None),              mock.patch.object(jobs, "get_racelist", return_value=None),              mock.patch.object(jobs, "get_odds", side_effect=odds),              mock.patch.object(jobs, "_load", return_value={"venues": []}),              mock.patch.object(jobs, "_save"):
            jobs.prerace(30, "20260909", strict=False)

        self.assertEqual(fetched, ["02", "01"],
                         "締切の早い場より先に、遅い場を取りに行っている")


class SkipCompleteBeforeinfo(unittest.TestCase):
    """
    展示と気象が揃っている行は、直前情報を取り直さないこと。

    展示タイムは一度出れば動かない。巡回の間隔を詰めたときに、
    2周目以降でこれを取り直すと取得量がそのまま倍になる。
    """

    def test_complete_slot_is_skipped(self):
        slot = {
            "conditions": {"weather": "曇り"},
            "racers": [{"lane": i, "exhibit_time": 6.8} for i in range(1, 7)],
        }
        self.assertTrue(jobs._has_beforeinfo(slot))

    def test_missing_exhibit_time_is_not_skipped(self):
        slot = {
            "conditions": {"weather": "曇り"},
            "racers": [{"lane": 1, "exhibit_time": 6.8}, {"lane": 2}],
        }
        self.assertFalse(jobs._has_beforeinfo(slot))

    def test_missing_conditions_is_not_skipped(self):
        slot = {"racers": [{"lane": 1, "exhibit_time": 6.8}]}
        self.assertFalse(jobs._has_beforeinfo(slot))


class LateFetchIsReported(unittest.TestCase):
    """
    締切を過ぎてから取得したレースを、問題として数えること。

    **通知は失敗時にしか飛ばない。** 予測が締切後に入るのは「取れた」ではなく
    劣化だが、ここで問題に数えないと、その日ずっと手遅れのまま誰も気づかない。
    実際に2026-09-09、90レース中5レースが締切後に入っていた。
    """

    def setUp(self):
        jobs._SCHEDULE_CACHE.clear()
        self.addCleanup(jobs._SCHEDULE_CACHE.clear)

    def _run(self, report_late):
        from datetime import datetime as real_datetime, timedelta

        start = real_datetime.now().replace(second=0, microsecond=0)
        close = start + timedelta(minutes=1)

        class FakeDatetime(real_datetime):
            """now() だけ差し替える。combine と strptime は本物のまま使う。"""
            seq = [start, start + timedelta(minutes=3)]

            @classmethod
            def now(cls, tz=None):
                return cls.seq.pop(0) if len(cls.seq) > 1 else cls.seq[0]

        venue = {"code": "05", "name": "多摩川"}
        with mock.patch.object(jobs, "datetime", FakeDatetime),              mock.patch.object(jobs, "get_active_venues", return_value=[venue]),              mock.patch.object(jobs, "get_close_times",
                               return_value={1: close.strftime("%H:%M")}),              mock.patch.object(jobs, "get_beforeinfo", return_value=None),              mock.patch.object(jobs, "get_racelist", return_value=None),              mock.patch.object(jobs, "get_odds", return_value=None),              mock.patch.object(jobs, "_load", return_value={"venues": []}),              mock.patch.object(jobs, "_save"):
            return jobs.prerace(30, "20260909", strict=False,
                                report_late=report_late)

    def test_late_fetch_becomes_a_problem(self):
        problems = self._run(report_late=True)
        self.assertTrue(any("締切" in p and "過ぎてから取得" in p for p in problems),
                        f"締切後の取得が問題に数えられていない: {problems}")

    def test_first_pass_does_not_report(self):
        """1周目の手遅れは起動の遅れによるもので、取り方の問題ではない。"""
        problems = self._run(report_late=False)
        self.assertFalse(any("過ぎてから取得" in p for p in problems))


class WeatherIsRefreshedNearDeadline(unittest.TestCase):
    """
    展示が揃っていても、締切間際は直前情報を取り直すこと。

    展示タイムは一度出れば動かないので、揃った行を毎周取り直すのは無駄だ。
    **しかし風速と波高は開催中に変わり、モデルはその2つを使っている。**
    揃った時点で固定すると、最後の予測が30分前の水面を見て出される。
    """

    def setUp(self):
        jobs._SCHEDULE_CACHE.clear()
        self.addCleanup(jobs._SCHEDULE_CACHE.clear)

    def _run(self, minutes_to_close):
        from datetime import datetime, timedelta

        close = (datetime.now() + timedelta(minutes=minutes_to_close))
        venue = {"code": "05", "name": "多摩川"}
        data = {"venues": [{
            "code": "05", "name": "多摩川",
            "races": [{
                "race_no": 1,
                "conditions": {"weather": "曇り", "wind_speed": 2},
                "racers": [{"lane": i, "exhibit_time": 6.8} for i in range(1, 7)],
            }],
        }]}
        called = []
        with mock.patch.object(jobs, "get_active_venues", return_value=[venue]),              mock.patch.object(jobs, "get_close_times",
                               return_value={1: close.strftime("%H:%M")}),              mock.patch.object(jobs, "get_beforeinfo",
                               side_effect=lambda *a: called.append(a) or None),              mock.patch.object(jobs, "get_racelist", return_value=None),              mock.patch.object(jobs, "get_odds", return_value=None),              mock.patch.object(jobs, "_load", return_value=data),              mock.patch.object(jobs, "_save"):
            jobs.prerace(30, "20260909", strict=False, report_late=False)
        return called

    def test_refetched_when_close(self):
        self.assertTrue(self._run(5), "締切間際なのに気象を取り直していない")

    def test_skipped_when_far(self):
        self.assertFalse(self._run(25), "揃っている行を遠いうちから取り直している")


class ProvisionalIsClearedOnRaceDay(unittest.TestCase):
    """
    当日の予測で上書きしたら、暫定の印を消すこと。

    **消し忘れると「暫定・直前情報なし」の表示が当日まで残る。** 当日の予測は
    市場へ引き戻し済みで展示も気象も入っており、前日の粗い予測とは別物である。
    """

    def setUp(self):
        jobs._SCHEDULE_CACHE.clear()
        self.addCleanup(jobs._SCHEDULE_CACHE.clear)

    def test_flag_is_removed_when_odds_arrive(self):
        from datetime import datetime, timedelta

        close = datetime.now() + timedelta(minutes=10)
        venue = {"code": "05", "name": "多摩川"}
        racers = [{"lane": i, "class": "B1", "win_rate_all": 5.0,
                   "win_rate_venue": 5.0, "avg_st": 0.16, "motor_in2_rate": 35.0,
                   "boat_in2_rate": 35.0, "weight": 52.0, "f_count": 0,
                   "in2_rate_all": 30.0} for i in range(1, 7)]
        data = {"venues": [{"code": "05", "name": "多摩川", "races": [
            {"race_no": 1, "racers": racers, "provisional": True}]}]}
        odds = {"market_prob": {i: 1 / 6 for i in range(1, 7)},
                "overround": 1.335, "odds": {"1-2-3": 9.6}}

        with mock.patch.object(jobs, "get_active_venues", return_value=[venue]),              mock.patch.object(jobs, "get_close_times",
                               return_value={1: close.strftime("%H:%M")}),              mock.patch.object(jobs, "get_beforeinfo", return_value=None),              mock.patch.object(jobs, "get_racelist", return_value=None),              mock.patch.object(jobs, "get_odds", return_value=odds),              mock.patch.object(jobs, "_load", return_value=data),              mock.patch.object(jobs, "_save"):
            jobs.prerace(30, "20260910", strict=False, report_late=False)

        slot = data["venues"][0]["races"][0]
        self.assertNotIn("provisional", slot)
        self.assertIn("picks", slot)


class LoopIntervalGuard(unittest.TestCase):
    """
    窓に対して間隔が粗い設定では起動しないこと。

    1周に数分かかるので、締切前に一度しか見ないレースは、その一度が
    順番待ちで締切を過ぎると手遅れになる。2回は見られる設定を強制する。
    """

    def test_coarse_interval_exits(self):
        with self.assertRaises(SystemExit) as cm:
            jobs.prerace_loop("21:40", interval_min=20, window_min=30)
        self.assertEqual(cm.exception.code, 1)

    def test_cli_defaults_are_valid(self):
        """
        **既定値そのものが歯止めに引っかかってはいけない。**
        引数なしで prerace-loop を叩いたときに落ちる状態にしない。
        """
        import inspect

        sig = inspect.signature(jobs.prerace_loop)
        interval = sig.parameters["interval_min"].default
        window = sig.parameters["window_min"].default
        self.assertLessEqual(interval * 2, window,
                             "既定の間隔が既定の窓に対して粗い")

    def test_half_of_window_is_allowed(self):
        """間隔が窓の半分ちょうどは通す（2回見られる）。"""
        with mock.patch.object(jobs, "_close_schedule", return_value=[]),              mock.patch.object(jobs, "prerace", return_value=[]),              mock.patch.object(jobs, "_sync_to_db", return_value=""):
            # 終了時刻を過ぎた状態にして、ループ本体には入らせない
            jobs.prerace_loop("00:01", interval_min=15, window_min=30)


class TomorrowJob(unittest.TestCase):
    """
    翌日ぶんの暫定予測。

    **オッズが前日に公開されないので、期待値と買い目は出せない。** 市場へ
    引き戻す先も無いため、公開する確率はモデル単独の生の値になる。当日の
    予測とは質が違うので provisional の印が要る。印が落ちると、質の違う
    2種類が同じ「AI予想」として混ざる。
    """

    def setUp(self):
        jobs._SCHEDULE_CACHE.clear()
        self.addCleanup(jobs._SCHEDULE_CACHE.clear)

    RACERS = [
        {"lane": i, "class": "B1", "win_rate_all": 5.0, "win_rate_venue": 5.0,
         "avg_st": 0.16, "motor_in2_rate": 35.0, "boat_in2_rate": 35.0,
         "weight": 52.0, "f_count": 0, "l_count": 0, "in2_rate_all": 30.0,
         "name": f"選手{i}", "racer_id": str(i), "branch": "東京", "age": 30,
         "motor_no": i, "boat_no": i, "in3_rate_all": 50.0,
         "in2_rate_venue": 30.0, "in3_rate_venue": 50.0}
        for i in range(1, 7)
    ]

    def _run(self):
        data = {"venues": []}
        venue = {"code": "05", "name": "多摩川"}
        with mock.patch.object(jobs, "get_active_venues", return_value=[venue]),              mock.patch.object(jobs, "get_close_times", return_value={1: "11:00"}),              mock.patch.object(jobs, "get_racelist",
                               side_effect=lambda d, v, r: (
                                   {"race_no": r, "racers": self.RACERS}
                                   if r == 1 else None)),              mock.patch.object(jobs, "_load", return_value=data),              mock.patch.object(jobs, "_save"),              mock.patch.object(jobs, "_sync_to_db", return_value="(取り込み省略)"):
            jobs.tomorrow("20260910")
        return data["venues"][0]["races"][0]

    def test_marks_provisional(self):
        self.assertTrue(self._run().get("provisional"))

    def test_has_probabilities_but_no_expected_value(self):
        slot = self._run()
        self.assertAlmostEqual(sum(slot["pub_prob"].values()), 1.0, places=2)
        self.assertNotIn("ev", slot)
        self.assertNotIn("picks", slot)
        self.assertNotIn("top_ev", slot)

    def test_published_probability_is_the_model_itself(self):
        """引き戻す市場が無いので、公開確率はモデル単独の値と一致する。"""
        slot = self._run()
        self.assertEqual(slot["pub_prob"], slot["model_prob"])

    def test_no_venue_exits(self):
        with mock.patch.object(jobs, "get_active_venues", return_value=[]):
            with self.assertRaises(SystemExit) as cm:
                jobs.tomorrow("20260910")
        self.assertEqual(cm.exception.code, 1)

    def test_no_race_exits(self):
        """1レースも取れなければ失敗にする。0件で正常終了させない。"""
        venue = {"code": "05", "name": "多摩川"}
        with mock.patch.object(jobs, "get_active_venues", return_value=[venue]),              mock.patch.object(jobs, "get_close_times", return_value={}),              mock.patch.object(jobs, "get_racelist", return_value=None),              mock.patch.object(jobs, "_load", return_value={"venues": []}),              mock.patch.object(jobs, "_save"),              mock.patch.object(jobs, "_sync_to_db", return_value=""):
            with self.assertRaises(SystemExit) as cm:
                jobs.tomorrow("20260910")
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
