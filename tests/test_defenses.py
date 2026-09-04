"""
CLAUDE.md が名指しで「外すな」と書いている防御のテスト。

実行:
  py -3 -m unittest discover -s tests

対象は2つ。どちらも壊れても症状がすぐには出ず、気づいたときには
公式サイトに負荷をかけた後か、DBに重複が積み上がった後になる。

  1. scraper/session.py の2秒間隔
  2. db/loader.py の _same_odds（オッズの重複防御）

ネットワークにもDBにも出ない。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from db.loader import _same_odds, _str_keys
from scraper import session


class RateLimit(unittest.TestCase):
    """
    2秒間隔が、成功時だけでなく失敗時にも効くこと。

    以前は raise_for_status の後ろに sleep があった。呼び出し側が例外を
    握って次に進む経路（backtest.collect の except Exception）では、
    サイトが5xxを返している間ずっと待ち時間ゼロで連射することになる。
    相手が弱っているときに一番強く叩く形なので、必ず待たせる。
    """

    def _fetch(self, responder):
        """fetch を、ネットワークに出ずに走らせる。戻り値は sleep の呼ばれ方。"""
        fake = mock.Mock()
        fake.get.side_effect = responder
        with mock.patch.object(session, "get_session", return_value=fake), \
             mock.patch.object(session.time, "sleep") as slept:
            try:
                # 当日のパラメータにしてキャッシュ経路に入らないようにする
                session.fetch("/owpc/pc/race/racelist", params={"rno": 1, "jcd": "05"})
            except Exception as e:
                return slept, e
            return slept, None

    def test_sleeps_after_success(self):
        ok = mock.Mock(status_code=200, content=b"<html></html>")
        ok.raise_for_status.return_value = None
        slept, err = self._fetch(lambda *a, **k: ok)
        self.assertIsNone(err)
        slept.assert_called_once_with(session.SLEEP_SEC)

    def test_sleeps_even_when_server_errors(self):
        bad = mock.Mock(status_code=503)
        bad.raise_for_status.side_effect = requests.HTTPError("503")
        slept, err = self._fetch(lambda *a, **k: bad)
        self.assertIsInstance(err, requests.HTTPError)
        slept.assert_called_once_with(session.SLEEP_SEC)

    def test_sleeps_even_on_timeout(self):
        def boom(*a, **k):
            raise requests.Timeout("timed out")
        slept, err = self._fetch(boom)
        self.assertIsInstance(err, requests.Timeout)
        slept.assert_called_once_with(session.SLEEP_SEC)

    def test_cache_hit_does_not_sleep(self):
        """キャッシュから返すときは待たない。サイトを叩いていないため。"""
        fake = mock.Mock()
        with mock.patch.object(session, "get_session", return_value=fake), \
             mock.patch.object(session.time, "sleep") as slept, \
             mock.patch.object(session.Path, "exists", return_value=True), \
             mock.patch.object(session.Path, "read_bytes", return_value=b"cached"):
            got = session.fetch(
                "/owpc/pc/race/racelist",
                params={"rno": 1, "jcd": "05", "hd": "20200101"},
            )
        self.assertEqual(got, b"cached")
        slept.assert_not_called()
        fake.get.assert_not_called()


class OddsDedup(unittest.TestCase):
    """
    _same_odds は odds_snapshots の重複防御そのもの。

    odds_snapshots は追記専用の時系列で、prerace-loop は各パスの直後に
    日次ファイル「全体」を取り込む。そのため一度取得したレースが以降の
    全パスで再投入される。この関数が直前と同じ内容を弾いていないと、
    同じ値のスナップショットが「あとで取得した」顔で積み上がり、
    captured_at が取得時刻を表さなくなって推移が読めなくなる。
    実測で1レースに13件並んだ事故がある。
    """

    def test_no_previous_snapshot_is_not_same(self):
        """1件目は必ず積む。"""
        self.assertFalse(_same_odds(None, 1.334, {"1": 0.5}))

    def test_identical_is_same(self):
        prev = (1.334, {"1": 0.5, "2": 0.3})
        self.assertTrue(_same_odds(prev, 1.334, {"1": 0.5, "2": 0.3}))

    def test_changed_overround_is_not_same(self):
        prev = (1.334, {"1": 0.5})
        self.assertFalse(_same_odds(prev, 1.335, {"1": 0.5}))

    def test_changed_market_prob_is_not_same(self):
        prev = (1.334, {"1": 0.5, "2": 0.3})
        self.assertFalse(_same_odds(prev, 1.334, {"1": 0.51, "2": 0.3}))

    def test_missing_lane_is_not_same(self):
        prev = (1.334, {"1": 0.5, "2": 0.3})
        self.assertFalse(_same_odds(prev, 1.334, {"1": 0.5}))

    def test_none_overround_is_not_same(self):
        """比較できないなら積む側に倒す。取りこぼすより重複のほうがまし。"""
        self.assertFalse(_same_odds((None, {"1": 0.5}), 1.334, {"1": 0.5}))
        self.assertFalse(_same_odds((1.334, {"1": 0.5}), None, {"1": 0.5}))

    def test_difference_below_stored_precision_is_same(self):
        """
        overround は numeric(6,4)、market_prob は6桁で保存される。
        保存すると消える差で「動いた」と判定すると、DBから読み直した値と
        比較するたびに新しい行が積まれ続ける。
        """
        prev = (1.3340001, {"1": 0.5000001})
        self.assertTrue(_same_odds(prev, 1.334, {"1": 0.5}))

    def test_keys_are_normalized_to_str_before_comparison(self):
        """
        DBのJSONBから戻る market_prob はキーが str。取り込み側は艇番を
        int で持っているので、_insert_odds が _str_keys で揃えてから渡す。
        この正規化を外すと、毎回「別物」と判定されて重複が積み上がる。
        """
        prev = (1.334, {"1": 0.5, "2": 0.3})
        self.assertTrue(_same_odds(prev, 1.334, _str_keys({1: 0.5, 2: 0.3})))


if __name__ == "__main__":
    unittest.main()
