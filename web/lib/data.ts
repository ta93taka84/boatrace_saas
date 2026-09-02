import { promises as fs } from "fs";
import path from "path";
import type { DayData, Race, Venue } from "./types";

/**
 * データ取得層。
 *
 * 現状は収集ジョブが書く output/<YYYYMMDD>.json を直接読む。
 * Supabaseへ切り替えるときは、このファイルの3関数の中身だけを
 * 差し替えればよく、画面側は触らずに済む。
 */

const OUTPUT_DIR = path.join(process.cwd(), "..", "output");

export async function listDates(): Promise<string[]> {
  try {
    const files = await fs.readdir(OUTPUT_DIR);
    return files
      .filter((f) => /^\d{8}\.json$/.test(f))
      .map((f) => f.replace(".json", ""))
      .sort()
      .reverse();
  } catch {
    return [];
  }
}

export async function getDay(date: string): Promise<DayData | null> {
  try {
    const raw = await fs.readFile(path.join(OUTPUT_DIR, `${date}.json`), "utf-8");
    return JSON.parse(raw) as DayData;
  } catch {
    return null;
  }
}

export async function getRace(
  date: string,
  venueCode: string,
  raceNo: number
): Promise<{ venue: Venue; race: Race } | null> {
  const day = await getDay(date);
  if (!day) return null;
  const venue = day.venues.find((v) => v.code === venueCode);
  if (!venue) return null;
  const race = venue.races.find((r) => r.race_no === raceNo);
  if (!race) return null;
  return { venue, race };
}

/** 数値キーのdictをレーン順の配列にする。欠損は0。 */
export function byLane(map?: Record<string, number>): number[] {
  if (!map) return [];
  return [1, 2, 3, 4, 5, 6].map((l) => map[String(l)] ?? 0);
}
