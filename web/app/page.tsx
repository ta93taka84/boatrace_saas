import Link from "next/link";
import { getDay, listDates } from "@/lib/data";
import { LaneBadge } from "@/components/LaneBadge";
import { DateNav } from "@/components/DateNav";
import { ErrorCard } from "@/components/ErrorCard";
import {
  DIVERGING_SCALE,
  MiniDivergingBar,
  MiniDivergingScale,
} from "@/components/Bars";
import { COURSE_BASE, courseDeviation } from "@/lib/course";
import type { Race } from "@/lib/types";

export const dynamic = "force-dynamic";

/** レース詳細の「コース標準との差」と同じ書式。同じ数字を同じ形で出す。 */
const devFormat = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}pt`;

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
  // 「まもなく締切」は当日を見ているときだけ意味がある。
  const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" })
    .replace(/-/g, "");
  const nowHM = new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo",
  });
  const upcoming =
    day.date === today
      ? day.venues
          .flatMap((v) =>
            v.races
              .filter((r) => r.closes_at && r.closes_at >= nowHM && !r.result)
              .map((r) => ({ venue: v, race: r }))
          )
          .sort((a, b) => (a.race.closes_at! < b.race.closes_at! ? -1 : 1))
          .slice(0, 12)
      : [];

  // 尺度(±30pt)の外まで届いている棒があるかどうか。あるときだけ矢羽根の説明を出す。
  const anyDevOverflow = upcoming.some(({ race }) => {
    const d = courseDeviation(race.market_prob, 1);
    return d != null && Math.abs(d) > DIVERGING_SCALE;
  });

  return (
    <main className="wrap">
      <p className="crumb">レース一覧</p>
      <h1>{shown} のレース</h1>
      <p className="sub">
        公式サイトの出走表・オッズ・結果を毎日集めて、レースごとにまとめています。
        <br />
        {day.venues.length}場 {totalRaces}レース
        {day.updated_at && (
          <span className="muted"> ・ 更新 {day.updated_at.slice(11, 16)}</span>
        )}
      </p>

      <DateNav dates={dates} current={day.date} />

      <div className="notice">
        市場勝率は三連単オッズから逆算した値です。予測モデルは市場オッズに
        届いていないため、期待値は出していません（<Link href="/about">詳細</Link>）。
      </div>

      {upcoming.length > 0 && (
        <div className="card">
          <h3>まもなく締切</h3>
          <div className="scroll-x">
            <table className="upcoming">
              <thead>
                <tr>
                  <th>締切</th>
                  {/*
                    余った横幅はこの列に吸わせる。そうしないと表の伸びが
                    最後の乖離の列に配分され、棒と数値のまわりに
                    数百pxの空白が空いて、棒が見出しから切り離されて見える。
                  */}
                  <th className="l" style={{ width: "100%" }}>場</th>
                  <th>レース</th>
                  {/*
                    狭い画面ではこの表は .scroll-x の中で横に流れる。差別化にあたる
                    この列を市場評価1位より前に置いて、スクロールしなくても
                    棒が視界に入るようにしている。
                  */}
                  <th>
                    <MiniDivergingScale
                      label="1号艇 コース標準との差"
                      format={devFormat}
                    />
                  </th>
                  <th>市場評価1位</th>
                </tr>
              </thead>
              <tbody>
                {upcoming.map(({ venue, race }) => {
                  const top = marketTop(race);
                  const dev = courseDeviation(race.market_prob, 1);
                  return (
                    <tr key={`${venue.code}-${race.race_no}`}>
                      <td className="time num">{race.closes_at}</td>
                      <td className="venue">{venue.name}</td>
                      <td>
                        <Link href={`/race/${day.date}/${venue.code}/${race.race_no}`}>
                          {race.race_no}R
                        </Link>
                      </td>
                      <td>
                        <MiniDivergingBar value={dev} format={devFormat} />
                      </td>
                      <td>
                        {top ? (
                          <span
                            style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
                          >
                            <LaneBadge lane={top.lane} size={16} />
                            <span className="num">{(top.prob * 100).toFixed(0)}%</span>
                          </span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/*
            この列は誤読されやすい。乖離が大きいレースほど1号艇の1着率は
            確かに下がるが、市場はその無秩序さを既に価格へ織り込んでいて、
            高額配当の出やすさは層別してもほとんど動かない（1万円超の出現率は
            19.1% → 14.7%）。だから「何が言えて、何が言えないか」を
            棒と同じ視界に必ず置く。README「表現に関する注意」。
          */}
          <p className="muted" style={{ fontSize: 12, margin: "10px 0 0" }}>
            「1号艇 コース標準との差」は、市場勝率が1号艇のコース標準（全国平均の
            1着率{(COURSE_BASE[1] * 100).toFixed(0)}%）からどちらへ何pt振れているかです。
            尺度は{devFormat(-DIVERGING_SCALE)}〜{devFormat(DIVERGING_SCALE)}に固定してあるので、
            棒の長さはレースをまたいで比べられます。左（赤）へ長いほど、標準どおりの
            決着になりにくいと市場が見ていることを表します。
            <strong>
              決まりにくさの目安であって、有利・不利や配当の高さを示すものではありません。
            </strong>
            過去1,236レースでは、この差で分けても三連単1万円超の出現率はほとんど
            変わりませんでした。
            {anyDevOverflow &&
              "端が尖った棒は、目盛りの外まで届いています。"}
          </p>
        </div>
      )}

      {/*
        「まもなく締切」にも市場評価1位のチップが並ぶので、この凡例が
        どのチップの話なのかを言い切る。以前は「チップ＝確定1着」とだけ
        書いてあり、締切前のレースに付いた市場評価のチップと矛盾していた。
      */}
      <p className="legend">
        下の一覧でレース番号の右に付く
        <LaneBadge lane={1} size={14} />
        は、確定した1着艇です。結果が出ていないレースには付きません。
      </p>

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
                const winner = race.result?.winner_lane ?? null;
                // チップは確定した1着だけに使う。予想と結果を同じ形で出すと、
                // 締切前のレースで予想を結果として読まれる。
                return (
                  <Link
                    key={race.race_no}
                    href={`/race/${day.date}/${venue.code}/${race.race_no}`}
                    title={
                      winner
                        ? `${race.race_no}R 確定1着 ${winner}号艇`
                        : race.closes_at
                        ? `${race.race_no}R 締切 ${race.closes_at}`
                        : `${race.race_no}R`
                    }
                  >
                    {race.race_no}R
                    {winner && <LaneBadge lane={winner} size={14} />}
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
