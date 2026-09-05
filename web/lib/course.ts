/**
 * コース別1着率の全国平均。市場評価との比較基準に使う。
 * scraper/scoring.py の COURSE_BASE_WIN_RATE と同じ値。
 *
 * トップ・レース詳細・実績集計の3画面が同じ基準を出すので、1か所に置く。
 * ここがずれると、同じ「コース標準との差」が画面ごとに違う値になる。
 */
export const COURSE_BASE: Record<number, number> = {
  1: 0.55,
  2: 0.145,
  3: 0.12,
  4: 0.105,
  5: 0.055,
  6: 0.025,
};

/**
 * 市場勝率がコース標準からどちらへどれだけ振れているか（確率の差、単位は1.0＝100pt）。
 * オッズが未取得のレースは null を返す。
 */
export function courseDeviation(
  market: Record<string, number> | undefined,
  lane: number
): number | null {
  const p = market?.[String(lane)];
  if (p == null) return null;
  const base = COURSE_BASE[lane];
  if (base == null) return null;
  return p - base;
}
