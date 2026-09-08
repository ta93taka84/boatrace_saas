import Link from "next/link";
import { getDay, listDates } from "@/lib/data";
import { LaneBadge } from "@/components/LaneBadge";
import { ErrorCard } from "@/components/ErrorCard";
import { MiniDivergingBar, MiniDivergingScale } from "@/components/Bars";
import { courseDeviation } from "@/lib/course";
import type { Race } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata = { title: "注目レース｜ボートレース データビュー" };

const devFormat = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}pt`;

type Row = {
  venueCode: string;
  venueName: string;
  race: Race;
  deviation: number;
};

/** AI予想が一番手に見ている艇。公開確率（pub_prob）で読む。 */
function topPick(race: Race): number | null {
  const probs = race.pub_prob ?? race.model_prob;
  if (!probs) return null;
  const entries = Object.entries(probs).map(([l, p]) => ({ lane: Number(l), p }));
  if (entries.length === 0) return null;
  return entries.reduce((a, b) => (b.p > a.p ? b : a)).lane;
}

export default async function FeaturedPage() {
  const rows: Row[] = [];
  let date = "";
  let failure: unknown = null;

  try {
    const dates = await listDates();
    date = dates[0] ?? "";
    const day = date ? await getDay(date) : null;
    for (const venue of day?.venues ?? []) {
      for (const race of venue.races) {
        const deviation = courseDeviation(race.market_prob, 1);
        if (deviation == null) continue;
        rows.push({
          venueCode: venue.code,
          venueName: venue.name,
          race,
          deviation,
        });
      }
    }
  } catch (e) {
    failure = e;
  }

  if (failure) {
    return (
      <main className="wrap">
        <h1>注目レース</h1>
        <ErrorCard where="注目レース" error={failure} />
      </main>
    );
  }

  const shown = date
    ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`
    : "";

  // 1号艇の評価がコース標準からどれだけ離れているかで並べる。
  // マイナスが大きいほど「1号艇が信用されていない」＝荒れる目が買われている。
  // 符号でも切る。プラスの行が8本無い日に「手堅い」としてマイナスの行を
  // 並べると、見出しと中身が食い違う。
  const sorted = [...rows].sort((a, b) => a.deviation - b.deviation);
  const rough = sorted.filter((r) => r.deviation < 0).slice(0, 8);
  const solid = sorted.filter((r) => r.deviation > 0).reverse().slice(0, 8);

  const section = (title: string, note: string, list: Row[]) => (
    <div className="card">
      <h3>{title}</h3>
      <p className="sub" style={{ marginTop: 0 }}>
        {note}
      </p>
      {list.length === 0 ? (
        <p className="muted" style={{ fontSize: 13 }}>
          この日のオッズがまだ取れていません。
        </p>
      ) : (
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>締切</th>
                <th className="l">レース</th>
                <th>AI本命</th>
                <th className="l">
                  <MiniDivergingScale
                    label="1号艇 コース標準との差"
                    format={devFormat}
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {list.map(({ venueCode, venueName, race, deviation }) => {
                const pick = topPick(race);
                return (
                  <tr key={`${venueCode}-${race.race_no}`}>
                    <td className="num">{race.closes_at ?? "—"}</td>
                    <td className="l">
                      <Link href={`/race/${date}/${venueCode}/${race.race_no}`}>
                        {venueName} {race.race_no}R
                      </Link>
                    </td>
                    <td>{pick ? <LaneBadge lane={pick} /> : "—"}</td>
                    <td className="l">
                      <MiniDivergingBar value={deviation} format={devFormat} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return (
    <main className="wrap">
      <h1>注目レース</h1>
      <p className="sub">
        {shown} ・ 市場の評価がコース標準から離れているレースを並べています。
      </p>

      {section(
        "荒れそうなレース",
        "1号艇が全国平均より低く評価されているレース。買われているのは1号艇以外です。",
        rough
      )}

      {section(
        "手堅いレース",
        "1号艇が全国平均より高く評価されているレース。逃げの信頼が集まっています。",
        solid
      )}

      <div className="card">
        <h3>この並びの見方</h3>
        <p style={{ marginTop: 0, marginBottom: 0 }}>
          棒は「市場が1号艇に置いた勝率」と「全国平均の1コース勝率(55%)」の差です。
          左に長いほど1号艇が信用されていません。尺度はレースによらず ±30pt に
          固定しているので、棒の長さはそのままレース間で比べられます。
          <strong>これは予想ではなく、市場が何を見ているかの読み出しです。</strong>
        </p>
      </div>
    </main>
  );
}
