import Link from "next/link";
import { getDay, listDates } from "@/lib/data";
import { LaneBadge } from "@/components/LaneBadge";
import { DateNav } from "@/components/DateNav";
import { ErrorCard } from "@/components/ErrorCard";
import type { Race } from "@/lib/types";

export const dynamic = "force-dynamic";

/** 市場が最も高く評価している艇と、その確率。 */
function marketTop(race: Race): { lane: number; prob: number } | null {
  if (!race.market_prob) return null;
  const entries = Object.entries(race.market_prob).map(([l, p]) => ({
    lane: Number(l),
    prob: p,
  }));
  if (entries.length === 0) return null;
  return entries.reduce((a, b) => (b.prob > a.prob ? b : a));
}

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date: requested } = await searchParams;

  // データ層の不調でページ全体を500にせず、画面に原因を出す。
  let dates: string[] = [];
  let day = null;
  let failure: unknown = null;
  try {
    dates = await listDates();
    const date = requested && dates.includes(requested) ? requested : dates[0];
    day = date ? await getDay(date) : null;
  } catch (e) {
    failure = e;
  }

  if (failure) {
    return (
      <main className="wrap">
        <h1>ボートレース データビュー</h1>
        <ErrorCard where="レース一覧" error={failure} />
      </main>
    );
  }

  if (!day) {
    return (
      <main className="wrap">
        <h1>レース一覧</h1>
        <p className="sub">表示できるデータがありません。</p>
      </main>
    );
  }

  const shown = `${day.date.slice(0, 4)}-${day.date.slice(4, 6)}-${day.date.slice(6, 8)}`;
  const totalRaces = day.venues.reduce((n, v) => n + v.races.length, 0);
  const withOdds = day.venues.reduce(
    (n, v) => n + v.races.filter((r) => r.market_prob).length,
    0
  );

  return (
    <main className="wrap">
      <p className="crumb">レース一覧</p>
      <h1>{shown} のレース</h1>
      <p className="sub">
        {day.venues.length}場 {totalRaces}レース
        <span className="muted"> ・ オッズ取得済み {withOdds}</span>
        {day.updated_at && (
          <span className="muted"> ・ 更新 {day.updated_at.slice(11, 16)}</span>
        )}
      </p>

      <DateNav dates={dates} current={day.date} />

      <div className="notice">
        市場勝率は三連単オッズから逆算した値です。予測モデルは市場オッズに
        届いていないため、期待値は出していません（<Link href="/about">詳細</Link>）。
      </div>

      <div className="venue-grid">
        {day.venues.map((venue) => (
          <div className="card" key={venue.code} style={{ marginBottom: 0 }}>
            <h2 style={{ marginBottom: 2 }}>{venue.name}</h2>
            <p className="muted" style={{ margin: 0, fontSize: 12 }}>
              {venue.races.length}レース
              {venue.races.some((r) => r.result) && " ・ 結果確定"}
            </p>
            <div className="race-links">
              {venue.races.map((race) => {
                const top = marketTop(race);
                const winner = race.result?.winner_lane ?? null;
                return (
                  <Link
                    key={race.race_no}
                    href={`/race/${day.date}/${venue.code}/${race.race_no}`}
                    title={
                      winner
                        ? `${race.race_no}R 確定1着 ${winner}号艇`
                        : top
                        ? `${race.race_no}R 市場本命 ${top.lane}号艇 ${(top.prob * 100).toFixed(0)}%`
                        : `${race.race_no}R`
                    }
                    // 確定した1着と、まだ確定していない市場本命は
                    // 同じバッジで出ると区別がつかないため枠線で分ける。
                    style={winner ? { borderColor: "var(--good)" } : undefined}
                  >
                    <span
                      style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                    >
                      {race.race_no}R
                      {/* 結果が出ていれば1着艇、まだなら市場本命を出す */}
                      {winner ? (
                        <LaneBadge lane={winner} size={14} />
                      ) : top ? (
                        <LaneBadge lane={top.lane} size={14} />
                      ) : null}
                    </span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
