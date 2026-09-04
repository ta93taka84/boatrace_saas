import { promises as fs } from "fs";
import path from "path";
import { getSupabase } from "./supabase";
import type { DayData, Race, Venue } from "./types";

/**
 * データ取得層。
 *
 * Supabaseの環境変数が設定されていればDBを、無ければ収集ジョブが書く
 * output/<YYYYMMDD>.json を読む。本番はDB、手元はファイル、という
 * 使い分けを画面側に意識させない。
 *
 * 画面が触るのはこのファイルの3関数だけなので、保存先を変えても
 * app/ 以下は書き換えずに済む。
 */

const OUTPUT_DIR = path.join(process.cwd(), "..", "output");

// ---------------------------------------------------------------- 公開API

export async function listDates(): Promise<string[]> {
  const db = getSupabase();
  if (db) {
    const { data, error } = await db
      .from("races")
      .select("race_date")
      .order("race_date", { ascending: false })
      .limit(2000);
    if (error) throw new Error(`listDates: ${error.message}`);
    const seen = new Set<string>();
    for (const row of data ?? []) seen.add(compact(row.race_date));
    return [...seen].sort().reverse();
  }
  return listDatesFromFiles();
}

export async function getDay(date: string): Promise<DayData | null> {
  const db = getSupabase();
  if (!db) return getDayFromFile(date);

  const { data, error } = await db
    .from("races")
    .select(
      `race_no, race_date, venue_code, closes_at,
       venues ( name ),
       race_entries ( * ),
       race_results ( winner_lane, finish, kimarite, payouts ),
       odds_snapshots ( overround, market_prob, captured_at ),
       predictions ( model_prob, ev, top_lane, top_ev, calibrated )`
    )
    .eq("race_date", iso(date))
    .order("race_no");
  if (error) throw new Error(`getDay: ${error.message}`);
  if (!data || data.length === 0) return null;

  const venues = new Map<string, Venue>();
  for (const row of data) {
    const code = row.venue_code as string;
    if (!venues.has(code)) {
      venues.set(code, {
        code,
        name: firstOf<{ name: string }>(row.venues)?.name ?? code,
        races: [],
      });
    }
    venues.get(code)!.races.push(toRace(row));
  }

  return {
    date,
    venues: [...venues.values()].sort((a, b) => a.code.localeCompare(b.code)),
  };
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

// ------------------------------------------------------------ DB行の変換

/* eslint-disable @typescript-eslint/no-explicit-any */
function toRace(row: any): Race {
  // オッズは締切に向けて動くので複数スナップショットが並ぶ。最新を採る。
  const snapshots = (row.odds_snapshots ?? []) as any[];
  const latest = snapshots.length
    ? snapshots.reduce((a, b) =>
        new Date(b.captured_at) > new Date(a.captured_at) ? b : a
      )
    : null;

  const result = firstOf(row.race_results);
  const prediction = firstOf(row.predictions);

  const race: Race = {
    race_no: row.race_no,
    racers: (row.race_entries ?? []).sort((a: any, b: any) => a.lane - b.lane),
  };

  // DBは time 型なので "11:29:00" で返る。表示に使うのは時分だけ。
  if (row.closes_at) race.closes_at = String(row.closes_at).slice(0, 5);

  if (row.weather || row.wind_speed != null) {
    race.conditions = {
      weather: row.weather ?? null,
      temperature: row.temperature ?? null,
      water_temp: row.water_temp ?? null,
      wind_speed: row.wind_speed ?? null,
      wind_dir_code: row.wind_dir_code ?? null,
      wave_height: row.wave_height ?? null,
    };
  }

  if (latest) {
    race.market_prob = latest.market_prob ?? undefined;
    race.overround = latest.overround ?? undefined;
    if (latest.captured_at) {
      race.odds_at = new Date(latest.captured_at).toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Tokyo",
      });
    }
  }

  // 未較正の予測はRLSで返らない想定だが、念のため画面側でも出さない。
  if (prediction?.calibrated) {
    race.model_prob = prediction.model_prob ?? undefined;
    race.ev = prediction.ev ?? undefined;
    race.top_lane = prediction.top_lane ?? undefined;
    race.top_ev = prediction.top_ev ?? undefined;
  }

  if (result) {
    race.result = {
      winner_lane: result.winner_lane,
      finish: result.finish ?? {},
      kimarite: result.kimarite,
      payouts: result.payouts ?? {},
    };
  }

  return race;
}

/** Supabaseは1対1の関連もオブジェクトか配列で返すため、どちらでも受ける。 */
function firstOf<T>(v: T | T[] | null | undefined): T | null {
  if (!v) return null;
  return Array.isArray(v) ? v[0] ?? null : v;
}

function iso(yyyymmdd: string): string {
  return `${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`;
}

function compact(isoDate: string): string {
  return isoDate.slice(0, 10).replace(/-/g, "");
}

// --------------------------------------------------- ローカルファイル読み

async function listDatesFromFiles(): Promise<string[]> {
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

async function getDayFromFile(date: string): Promise<DayData | null> {
  try {
    const raw = await fs.readFile(path.join(OUTPUT_DIR, `${date}.json`), "utf-8");
    return stripUncalibrated(JSON.parse(raw) as DayData);
  } catch {
    return null;
  }
}

/**
 * 未較正の予測を落とす。
 *
 * DB経路は predictions.calibrated で門番を通し、schema.sql のRLSでも
 * 未較正の行を返さないようにしてある。ファイル経路にはその門番が無く、
 * JSONに入っているEVがそのまま画面まで届いていた。Supabaseの環境変数を
 * 設定し忘れた状態がまさにこの経路なので、同じ門番をここにも置く。
 *
 * 較正が済むまでEVを出さないのはプロジェクトの決まり（CLAUDE.md）。
 * jobs.py が各レースに calibrated を刻んでいる。印が無い古いファイルは
 * 未較正として扱う。
 */
function stripUncalibrated(day: DayData): DayData {
  for (const venue of day.venues ?? []) {
    for (const race of venue.races ?? []) {
      if (!(race as { calibrated?: boolean }).calibrated) {
        delete race.model_prob;
        delete race.ev;
        delete race.top_lane;
        delete race.top_ev;
      }
    }
  }
  return day;
}
