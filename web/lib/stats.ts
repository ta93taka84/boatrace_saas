import { promises as fs } from "fs";
import path from "path";

/**
 * バックテスト用に収集した過去レースを集計する。
 *
 * 公式サイトは1レース単位の情報しか出さないため、
 * 「コースごとに実際どれだけ勝っているか」「決まり手の内訳」
 * 「配当がどれくらいの水準か」は自分で集計しないと分からない。
 * ここが集約サイトとしての価値になる。
 */

const DATASET = path.join(process.cwd(), "..", "output", "backtest.jsonl");

interface BacktestRow {
  date: string;
  venue: string;
  venue_name: string;
  race_no: number;
  winner_lane: number;
  kimarite: string | null;
  trifecta_payout: number | null;
}

export interface Stats {
  races: number;
  dates: string[];
  courseWinRate: { lane: number; rate: number; wins: number }[];
  byVenue: { code: string; name: string; races: number; lane1Rate: number }[];
  kimarite: { name: string; count: number; share: number }[];
  payout: {
    median: number;
    p25: number;
    p75: number;
    max: number;
    /** 1万円以上になった割合 */
    bigShare: number;
  } | null;
}

export async function getStats(): Promise<Stats | null> {
  let text: string;
  try {
    text = await fs.readFile(DATASET, "utf-8");
  } catch {
    return null;
  }

  const rows: BacktestRow[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      const r = JSON.parse(line);
      if (r.winner_lane) rows.push(r);
    } catch {
      // 収集中はファイル末尾が書き途中のことがある。壊れた行は捨てる。
    }
  }
  if (rows.length === 0) return null;

  const wins = new Map<number, number>();
  for (let l = 1; l <= 6; l++) wins.set(l, 0);
  for (const r of rows) wins.set(r.winner_lane, (wins.get(r.winner_lane) ?? 0) + 1);

  const courseWinRate = [1, 2, 3, 4, 5, 6].map((lane) => ({
    lane,
    wins: wins.get(lane) ?? 0,
    rate: (wins.get(lane) ?? 0) / rows.length,
  }));

  const venueMap = new Map<string, { name: string; races: number; lane1: number }>();
  for (const r of rows) {
    const v = venueMap.get(r.venue) ?? { name: r.venue_name, races: 0, lane1: 0 };
    v.races += 1;
    if (r.winner_lane === 1) v.lane1 += 1;
    venueMap.set(r.venue, v);
  }
  const byVenue = [...venueMap.entries()]
    .map(([code, v]) => ({
      code,
      name: v.name,
      races: v.races,
      lane1Rate: v.lane1 / v.races,
    }))
    .sort((a, b) => b.lane1Rate - a.lane1Rate);

  const kimariteMap = new Map<string, number>();
  for (const r of rows) {
    if (!r.kimarite) continue;
    kimariteMap.set(r.kimarite, (kimariteMap.get(r.kimarite) ?? 0) + 1);
  }
  const kimariteTotal = [...kimariteMap.values()].reduce((a, b) => a + b, 0);
  const kimarite = [...kimariteMap.entries()]
    .map(([name, count]) => ({ name, count, share: count / kimariteTotal }))
    .sort((a, b) => b.count - a.count);

  const payouts = rows
    .map((r) => r.trifecta_payout)
    .filter((p): p is number => typeof p === "number" && p > 0)
    .sort((a, b) => a - b);

  const pick = (q: number) => payouts[Math.floor(payouts.length * q)] ?? 0;
  const payout = payouts.length
    ? {
        median: pick(0.5),
        p25: pick(0.25),
        p75: pick(0.75),
        max: payouts[payouts.length - 1],
        bigShare: payouts.filter((p) => p >= 10000).length / payouts.length,
      }
    : null;

  return {
    races: rows.length,
    dates: [...new Set(rows.map((r) => r.date))].sort(),
    courseWinRate,
    byVenue,
    kimarite,
    payout,
  };
}
