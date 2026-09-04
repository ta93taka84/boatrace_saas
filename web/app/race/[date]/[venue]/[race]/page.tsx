import Link from "next/link";
import { notFound } from "next/navigation";
import { getRace } from "@/lib/data";
import { LaneBadge } from "@/components/LaneBadge";
import { ProbBars, DivergingBars } from "@/components/Bars";
import { DotPlot } from "@/components/DotPlot";
import { ErrorCard } from "@/components/ErrorCard";

export const dynamic = "force-dynamic";

/**
 * コース別1着率の全国平均。市場評価との比較基準に使う。
 * scraper/scoring.py の COURSE_BASE_WIN_RATE と同じ値。
 */
const COURSE_BASE: Record<number, number> = {
  1: 0.55, 2: 0.145, 3: 0.12, 4: 0.105, 5: 0.055, 6: 0.025,
};

const LANES = [1, 2, 3, 4, 5, 6];

export default async function RacePage({
  params,
}: {
  params: Promise<{ date: string; venue: string; race: string }>;
}) {
  const { date, venue: venueCode, race: raceNo } = await params;

  let found = null;
  let failure: unknown = null;
  try {
    found = await getRace(date, venueCode, Number(raceNo));
  } catch (e) {
    failure = e;
  }

  if (failure) {
    return (
      <main className="wrap">
        <h1>レース詳細</h1>
        <ErrorCard where="レースデータ" error={failure} />
      </main>
    );
  }
  if (!found) notFound();

  const { venue, race } = found;
  const racers = race.racers ?? [];
  const byLane = new Map(racers.map((r) => [r.lane, r]));
  const market = race.market_prob;

  const shown = `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`;

  const marketValues = LANES.map((lane) => ({
    lane,
    value: market ? market[String(lane)] ?? null : null,
  }));

  // 市場評価がコース標準からどれだけ離れているか。
  const deviation = LANES.map((lane) => ({
    lane,
    value: market && market[String(lane)] != null
      ? market[String(lane)] - COURSE_BASE[lane]
      : null,
  }));

  const exhibit = LANES.map((lane) => ({
    lane,
    value: byLane.get(lane)?.exhibit_time ?? null,
  }));
  const exhibitPresent = exhibit.filter((e) => e.value != null);

  const cond = race.conditions;

  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/">レース一覧</Link> ＞ {venue.name} ＞ {race.race_no}R
      </p>
      <h1>
        {venue.name} {race.race_no}R
      </h1>
      <p className="sub">
        {shown}
        {race.closes_at && ` ・ 締切 ${race.closes_at}`}
        {race.overround && (
          <span className="muted"> ・ 控除前オッズ総和 {race.overround.toFixed(3)}</span>
        )}
      </p>

      {cond && (cond.weather || cond.wind_speed != null) && (
        <div className="card">
          <h3>コンディション</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 20, fontSize: 13 }}>
            {cond.weather && <span>天候 {cond.weather}</span>}
            {cond.temperature != null && <span>気温 {cond.temperature}℃</span>}
            {cond.water_temp != null && <span>水温 {cond.water_temp}℃</span>}
            {cond.wind_speed != null && <span>風速 {cond.wind_speed}m</span>}
            {cond.wave_height != null && <span>波高 {cond.wave_height}cm</span>}
          </div>
        </div>
      )}

      <div className="grid2">
        <div className="card">
          <h3>市場勝率</h3>
          <ProbBars
            values={marketValues}
            max={1}
            format={(v) => `${(v * 100).toFixed(1)}%`}
          />
        </div>

        <div className="card">
          <h3>コース標準との差</h3>
          <DivergingBars
            values={deviation}
            format={(v) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}pt`}
          />
          <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 10 }}>
            右が全国平均より高い評価、左が低い評価。
          </p>
        </div>
      </div>

      {exhibitPresent.length > 0 && (
        <div className="card">
          <h3>展示タイム</h3>
          <DotPlot
            values={exhibit}
            lowerIsBetter
            unit="秒"
            format={(v) => `${v.toFixed(2)}秒`}
          />
        </div>
      )}

      <div className="card">
        <h3>出走表</h3>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th className="l">艇</th>
                <th className="l">選手</th>
                <th>級別</th>
                <th>全国勝率</th>
                <th>当地勝率</th>
                <th>平均ST</th>
                <th>F/L</th>
                <th>モーター</th>
                <th>ボート</th>
                <th>展示</th>
              </tr>
            </thead>
            <tbody>
              {LANES.map((lane) => {
                const r = byLane.get(lane);
                if (!r) {
                  return (
                    <tr key={lane} className={`lane-${lane}`}>
                      <td className="l"><LaneBadge lane={lane} /></td>
                      <td className="l muted" colSpan={9}>未取得</td>
                    </tr>
                  );
                }
                return (
                  <tr key={lane} className={`lane-${lane}`}>
                    <td className="l"><LaneBadge lane={lane} /></td>
                    <td className="l">
                      {r.name}
                      <span className="muted" style={{ fontSize: 11, marginLeft: 6 }}>
                        {r.branch} {r.age}歳
                      </span>
                    </td>
                    <td>{r.class}</td>
                    <td className="num">{r.win_rate_all.toFixed(2)}</td>
                    <td className="num">
                      {r.win_rate_venue > 0 ? r.win_rate_venue.toFixed(2) : "—"}
                    </td>
                    <td className="num">{r.avg_st > 0 ? r.avg_st.toFixed(2) : "—"}</td>
                    <td className="num">
                      {r.f_count}/{r.l_count}
                    </td>
                    <td className="num">
                      {r.motor_no}
                      <span className="muted"> ({r.motor_in2_rate.toFixed(1)}%)</span>
                    </td>
                    <td className="num">
                      {r.boat_no}
                      <span className="muted"> ({r.boat_in2_rate.toFixed(1)}%)</span>
                    </td>
                    <td className="num">
                      {r.exhibit_time ? r.exhibit_time.toFixed(2) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {race.result && (
        <div className="card">
          <h3>結果</h3>
          <p style={{ marginTop: 0 }}>
            1着 <LaneBadge lane={race.result.winner_lane ?? 0} />{" "}
            {race.result.kimarite && (
              <span className="muted">決まり手 {race.result.kimarite}</span>
            )}
          </p>
          {race.result.payouts?.["3連単"] && (
            <p className="num" style={{ marginBottom: 0 }}>
              3連単 {race.result.payouts["3連単"].combo} ¥
              {race.result.payouts["3連単"].payout.toLocaleString()}
            </p>
          )}
        </div>
      )}
    </main>
  );
}
