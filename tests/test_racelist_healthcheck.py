"""
出走表の列ずれを実行時に検知できることのテスト。

実行:
  py -3 -m unittest discover -s tests

**列がずれても例外は出ない。** racelist の _int / _float はパースに失敗しても
0 を返すだけなので、公式サイトが成績欄に列を1つ足すと、勝率の欄に
3連対率(例 54.95)がそのまま入る。数値としては正常なのでどこも引っかからず、
DBに嘘の値が入り、モデルはそれを特徴量として使う。

tests/test_parsers.py の値域アサーションは固定フィクスチャにしか効かない。
サイト側が変わったときに気づけるのは実行時の検査だけなので、そちらを
ここで固定する。

誤検知しないことも同じくらい重要。通知は失敗時にしか飛ばないので、
本物でない通知が増えると「通知が来たら本物」という運用前提が壊れる。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jobs

# 正常な1艇分。ここから1項目だけ壊して検知を確かめる。
GOOD = {
    "lane": 1, "racer_id": "3590", "name": "神田 郁夫", "class": "A1",
    "branch": "福岡", "age": 52, "weight": 54.4,
    "f_count": 0, "l_count": 0, "avg_st": 0.14,
    "win_rate_all": 7.03, "in2_rate_all": 48.28, "in3_rate_all": 65.52,
    "win_rate_venue": 7.30, "in2_rate_venue": 60.00, "in3_rate_venue": 80.00,
    "motor_no": 60, "motor_in2_rate": 44.38, "motor_in3_rate": 58.13,
    "boat_no": 57, "boat_in2_rate": 41.21, "boat_in3_rate": 54.55,
}


def check(**broken):
    return jobs._racer_problems("常滑 1R", [dict(GOOD, **broken)])


class NoFalseAlarms(unittest.TestCase):
    """正常なデータと、正当にゼロになりうる値では鳴らないこと。"""

    def test_healthy_racer_is_clean(self):
        self.assertEqual(check(), [])

    def test_no_local_record_is_not_a_problem(self):
        """当地成績の無い選手は当地勝率が0.0になる。これは正常。"""
        self.assertEqual(
            check(win_rate_venue=0.0, in2_rate_venue=0.0, in3_rate_venue=0.0), []
        )

    def test_debut_racer_with_no_starts_is_not_a_problem(self):
        """デビュー直後は平均STも勝率も0になりうる。"""
        self.assertEqual(check(avg_st=0.0, win_rate_all=0.0), [])

    def test_hundred_percent_is_allowed(self):
        """率は百分率なので100はありうる。"""
        self.assertEqual(check(in2_rate_all=100.0, motor_in2_rate=100.0), [])

    def test_all_six_healthy_racers_are_clean(self):
        racers = [dict(GOOD, lane=i) for i in range(1, 7)]
        self.assertEqual(jobs._racer_problems("常滑 1R", racers), [])


class DetectsColumnShift(unittest.TestCase):
    """
    列が1つずれたときの署名は「値が別の列の値域に落ちる」こと。
    上限側で捕まえる。
    """

    def test_third_place_rate_landing_in_win_rate(self):
        """成績欄に列が増えると、勝率(10点満点)に3連対率(0-100)が入る。"""
        p = check(win_rate_all=54.95)
        self.assertEqual(len(p), 1)
        self.assertIn("win_rate_all", p[0])

    def test_win_rate_landing_in_average_st(self):
        """平均ST(1秒未満)に勝率(0-10)が入る。"""
        p = check(avg_st=7.03)
        self.assertEqual(len(p), 1)
        self.assertIn("avg_st", p[0])

    def test_rate_over_hundred(self):
        p = check(motor_in2_rate=458.0)
        self.assertEqual(len(p), 1)
        self.assertIn("motor_in2_rate", p[0])

    def test_venue_win_rate_over_ten(self):
        p = check(win_rate_venue=60.0)
        self.assertEqual(len(p), 1)
        self.assertIn("win_rate_venue", p[0])

    def test_impossible_motor_number(self):
        p = check(motor_no=5495)
        self.assertEqual(len(p), 1)
        self.assertIn("motor_no", p[0])

    def test_name_column_holding_a_number(self):
        """選手情報の列がまるごとずれると、氏名の欄に数字が来る。"""
        p = check(name="3590")
        self.assertEqual(len(p), 1)
        self.assertIn("氏名", p[0])

    def test_bad_class_label(self):
        p = check(**{"class": "7.03"})
        self.assertEqual(len(p), 1)
        self.assertIn("級別", p[0])

    def test_non_numeric_registration_id(self):
        p = check(racer_id="神田")
        self.assertEqual(len(p), 1)
        self.assertIn("登録番号", p[0])

    def test_shift_affects_every_boat(self):
        """
        列ずれはレース単位で起きるので、6艇すべてに現れる。
        1艇だけの異常より件数が多いことが、ずれの手がかりになる。
        """
        racers = [dict(GOOD, lane=i, win_rate_all=54.95) for i in range(1, 7)]
        self.assertEqual(len(jobs._racer_problems("常滑 1R", racers)), 6)


class WiredIntoHealthcheck(unittest.TestCase):
    """_healthcheck から実際に呼ばれていること。"""

    def _data(self, racers):
        return {"venues": [{"code": "08", "name": "常滑", "races": [
            {"race_no": 1, "racers": racers,
             "market_prob": {1: 0.5}, "overround": 1.334},
        ]}]}

    def _targets(self):
        return [({"code": "08", "name": "常滑"}, 1, "11:00")]

    def test_healthy_race_has_no_problems(self):
        racers = [dict(GOOD, lane=i) for i in range(1, 7)]
        self.assertEqual(jobs._healthcheck(self._data(racers), self._targets()), [])

    def test_shifted_race_is_reported(self):
        racers = [dict(GOOD, lane=i, avg_st=7.03) for i in range(1, 7)]
        problems = jobs._healthcheck(self._data(racers), self._targets())
        self.assertEqual(len(problems), 6)
        self.assertTrue(all("avg_st" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
