"""
日次ファイルからバックテスト用の行を作る経路のテスト。

**この経路は「通信しない」ことが存在理由である。** 毎日のジョブが取ったページを
collect が取り直すのは、公式サイトへの無駄な負荷であり、CLAUDE.md の
「同じ情報を二度取りに行かない」に反する。ここが壊れていると、静かに
取り直しへ戻る（collect がその行を未収集とみなすため）。

実行:
  py -3 -m unittest discover -s tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backtest


def daily(date="20260906", with_result=True, with_odds=True):
    race = {
        "race_no": 1,
        "closes_at": "11:00",
        "racers": [
            {"lane": i, "name": f"選手{i}", "ex_course": i, "ex_st": 0.15}
            for i in range(1, 7)
        ],
        "conditions": {"weather": "曇り", "wind_speed": 2},
    }
    if with_odds:
        race["market_prob"] = {str(i): 1 / 6 for i in range(1, 7)}
    if with_result:
        race["result"] = {
            "winner_lane": 1,
            "finish": {"1": 1, "2": 2, "3": 3},
            "kimarite": "逃げ",
            "start": [{"course": 1, "lane": 1, "st": 0.14, "flying": False}],
            "payouts": {"3連単": {"combo": "1-2-3", "payout": 980, "popularity": 1}},
        }
    return {"date": date, "venues": [{"code": "05", "name": "多摩川", "races": [race]}]}


class ImportDaily(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = Path(self.dir.name)
        self.dataset = root / "backtest.jsonl"
        patches = [
            mock.patch.object(backtest, "OUTPUT_DIR", root),
            mock.patch.object(backtest, "DATASET", self.dataset),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _write(self, day):
        (Path(self.dir.name) / f"{day['date']}.json").write_text(
            json.dumps(day, ensure_ascii=False), encoding="utf-8")

    def _rows(self):
        if not self.dataset.exists():
            return []
        return [json.loads(l) for l in self.dataset.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_imports_a_complete_race(self):
        self._write(daily())
        backtest.import_daily()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["date"], row["venue"], row["race_no"]), ("20260906", "05", 1))
        self.assertEqual(row["winner_lane"], 1)
        self.assertEqual(row["trifecta_payout"], 980)
        self.assertEqual(len(row["start_exhibition"]), 6)

    def test_is_idempotent(self):
        """**二度取り込んでも増えないこと。** 増えると同じレースが重複して学習に入る。"""
        self._write(daily())
        backtest.import_daily()
        backtest.import_daily()
        self.assertEqual(len(self._rows()), 1)

    def test_skips_race_without_odds(self):
        """オッズが無い行は取り込まない。市場勝率が無いと比較の基準が作れない。"""
        self._write(daily(with_odds=False))
        backtest.import_daily()
        self.assertEqual(self._rows(), [])

    def test_skips_race_without_result(self):
        self._write(daily(with_result=False))
        backtest.import_daily()
        self.assertEqual(self._rows(), [])


if __name__ == "__main__":
    unittest.main()
