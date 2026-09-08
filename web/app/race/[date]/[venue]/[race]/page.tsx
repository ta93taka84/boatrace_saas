import Link from "next/link";
import { notFound } from "next/navigation";
import { getRace } from "@/lib/data";
import { LaneBadge } from "@/components/LaneBadge";
import { ProbBars, DivergingBars } from "@/components/Bars";
import { DotPlot } from "@/components/DotPlot";
import { ErrorCard } from "@/components/ErrorCard";
import { courseDeviation } from "@/lib/course";

export const dynamic = "force-dynamic";

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

  // 市場評価がコース標準からどれだけ離れているか。トップページの一覧と
  // 同じ基準・同じ尺度で出すので、基準は lib/course.ts に置いてある。
  const deviation = LANES.map((lane) => ({
    lane,
    value: courseDeviation(market, lane),
  }));

  const exhibit = LANES.map((lane) => ({
    lane,
    value: byLane.get(lane)?.exhibit_time ?? null,
  }));
  const exhibitPresent = exhibit.filter((e) => e.value != null);

  // スタート展示。進入コース順に並べる。枠なり進入なら 1〜6 の順に揃う。
  // **枠番と進入は別物。** 前づけがあるとここで並びが崩れ、それがそのまま
  // 展開の読みになる（実測では結果ページの18.1%が枠番と一致しない）。
  const exhibition = racers
    .filter((r) => r.ex_course != null)
    .sort((a, b) => (a.ex_course ?? 0) - (b.ex_course ?? 0));
  const hasExhibition = exhibition.length > 0;
  const maezuke = exhibition.some((r) => r.ex_course !== r.lane);
  const exStValues = exhibition
    .map((r) => r.ex_st)
    .filter((v): v is number => v != null);
  const bestExSt = exStValues.length ? Math.min(...exStValues) : null;

  // 今節の前走。節の初日は全艇とも空になるので、その日は列ごと出さない。
  const hasPrev = racers.some((r) => r.prev_race_no != null);

  const cond = race.conditions;

  // 列ごとの最良値。10列の数字が均一に並ぶと、どこを見ればよいか手がかりが無い。
  // 該当セルだけ太字にする（色は足さない。すでに艇色と系列色があるため）。
  const best = (
    pick: (r: (typeof racers)[number]) => number | null | undefined,
    lowerIsBetter = false
  ) => {
    const vals = racers.map(pick).filter((v): v is number => v != null && v > 0);
    if (vals.length === 0) return null;
    return lowerIsBetter ? Math.min(...vals) : Math.max(...vals);
  };
  const bestWinAll = best((r) => r.win_rate_all);
  const bestWinVenue = best((r) => r.win_rate_venue);
  const bestSt = best((r) => r.avg_st, true);
  const bestMotor = best((r) => r.motor_in2_rate);
  const bestBoat = best((r) => r.boat_in2_rate);
  const bestExhibit = best((r) => r.exhibit_time, true);

  // 展示タイムが1つも無い日は列ごと出さない。「—」が6個並ぶと壊れて見える。
  const hasExhibit = exhibitPresent.length > 0;

  const cell = (isBest: boolean) => (isBest ? "num best" : "num");

  // モーターとボートは「番号（2連対率）」を1セルに詰めている。比較しているのは
  // 率のほうなので、太字は率だけに付ける。セル全体を太字にすると、隣り合う
  // 番号のほうが先に目に入り、番号が最良の値だと読めてしまう。
  const partCell = (no: number, rate: number, isBest: boolean) => (
    <td className="num">
      {no}
      <span
        className={isBest ? undefined : "muted"}
        style={isBest ? { fontWeight: 700 } : undefined}
      >
        {" "}
        ({rate.toFixed(1)}%)
      </span>
    </td>
  );

  // 着順は {艇番: 着順} で入っている。表示は着順の順に並べ替える。

  const finishOrder = race.result
    ? Object.entries(race.result.finish ?? {})
        .map(([lane, pos]) => ({ lane: Number(lane), pos: Number(pos) }))
        .filter((x) => x.pos >= 1 && x.pos <= 3)
        .sort((a, b) => a.pos - b.pos)
    : [];

  // AI予想。model_prob は6艇の1着確率、picks は三連単の推奨買い目。
  // 尺度は市場勝率の棒と同じ0〜100%に固定する。別々の尺度で描くと、
  // 隣り合う2枚の棒の長さを比べられなくなる（DESIGN.md の決まり）。
  // 画面に出すのは公開確率（市場オッズへ引き戻したもの）。古いデータには
  // pub_prob が無いので、その場合だけモデル単独の値に落とす。
  const model = race.pub_prob ?? race.model_prob;
  const modelValues = LANES.map((lane) => ({
    lane,
    value: model ? model[String(lane)] ?? null : null,
  }));
  const hasModel = modelValues.some((v) => v.value != null);
  const topPick = hasModel
    ? modelValues.reduce((a, b) => ((b.value ?? -1) > (a.value ?? -1) ? b : a))
    : null;
  const picks = race.picks ?? [];

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
        {race.odds_at && (
          <span className="muted"> ・ オッズ {race.odds_at} 時点</span>
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

      {race.result && (
        <div className="card">
          <h3>結果</h3>
          <p style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 14 }}>
            {finishOrder.map(({ lane, pos }) => (
              <span
                key={lane}
                style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
              >
                <span className="muted" style={{ fontSize: 12 }}>
                  {pos}着
                </span>
                <LaneBadge lane={lane} />
              </span>
            ))}
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
      {hasModel && (
        <div className="card">
          <h3>AI予想</h3>
          {topPick?.value != null && (
            <p
              style={{
                marginTop: 0,
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 15,
              }}
            >
              <span className="muted" style={{ fontSize: 12 }}>
                本命
              </span>
              <LaneBadge lane={topPick.lane} />
              <span className="num" style={{ fontWeight: 700 }}>
                {(topPick.value * 100).toFixed(1)}%
              </span>
            </p>
          )}

          <div className="grid2">
            <div>
              <p className="sub">予測1着率</p>
              <ProbBars
                values={modelValues}
                max={1}
                emphasize={topPick?.lane}
                format={(v) => `${(v * 100).toFixed(1)}%`}
              />
              <p
                className="muted"
                style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}
              >
                棒の尺度は下の「市場勝率」と同じ0〜100%です。
                並べて長さをそのまま比べられます。
              </p>
            </div>

            <div>
              <p className="sub">推奨買い目（3連単）</p>
              {picks.length > 0 ? (
                <div className="scroll-x">
                  <table>
                    <thead>
                      <tr>
                        <th className="l">買い目</th>
                        <th>予測確率</th>
                        <th>オッズ</th>
                        <th>期待値</th>
                      </tr>
                    </thead>
                    <tbody>
                      {picks.map((pick) => (
                        <tr key={pick.combo}>
                          <td className="l num">{pick.combo}</td>
                          <td className="num">{(pick.prob * 100).toFixed(1)}%</td>
                          <td className="num">{pick.odds.toFixed(1)}</td>
                          <td className={pick.ev >= 1 ? "num best" : "num"}>
                            {pick.ev.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="muted" style={{ fontSize: 13 }}>
                  オッズが取れていないため算出していません
                </p>
              )}
              <p
                className="muted"
                style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}
              >
                期待値は 予測確率 × オッズ です。1.00 を超えると理論上プラスに
                なりますが、オッズは締切に向けて動くため、購入時の値とは異なります。
                並んでいるのは当たりやすい順ではなく、
                <strong>オッズに対して確率が高い順</strong>です。本命が頭に
                入らない買い目もあります。
              </p>
            </div>
          </div>

          <p
            className="muted"
            style={{ fontSize: 12, marginTop: 14, marginBottom: 0 }}
          >
            AI予想は統計モデルによる推定であり、的中や利益を保証するものでは
            ありません。舟券の購入はご自身の判断と責任でお願いします。20歳未満の
            方は舟券を購入できません。
            <Link href="/terms"> 免責事項</Link>
          </p>
        </div>
      )}

      {hasExhibition && (
        <div className="card">
          <h3>スタート展示</h3>
          <p className="sub" style={{ marginTop: 0 }}>
            左が1コース。カッコ内は展示のスタートタイミングです。
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
            {exhibition.map((r) => (
              <span
                key={r.lane}
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <span className="muted" style={{ fontSize: 11 }}>
                  {r.ex_course}
                </span>
                <LaneBadge lane={r.lane} />
                <span
                  className="num"
                  style={{
                    fontSize: 13,
                    fontWeight: r.ex_st != null && r.ex_st === bestExSt ? 700 : 400,
                  }}
                >
                  {r.ex_st != null
                    ? `(${r.ex_st < 0 ? "F" : ""}${Math.abs(r.ex_st).toFixed(2)})`
                    : "(—)"}
                </span>
              </span>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
            {maezuke
              ? "枠番と違う並びです。前づけがあり、枠なり進入になっていません。"
              : "枠なり進入です。1号艇から順に並んでいます。"}
            {" "}展示のスタートは本番と一致するとは限りません（相関 r = 0.12）。
          </p>
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
                {hasExhibit && <th>展示</th>}
                {hasPrev && <th>前走</th>}
              </tr>
            </thead>
            <tbody>
              {LANES.map((lane) => {
                const r = byLane.get(lane);
                if (!r) {
                  return (
                    <tr key={lane} className={`lane-${lane}`}>
                      <td className="l"><LaneBadge lane={lane} /></td>
                      <td className="l muted" colSpan={8 + (hasExhibit ? 1 : 0) + (hasPrev ? 1 : 0)}>
                        未取得
                      </td>
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
                    <td className={cell(r.win_rate_all === bestWinAll)}>
                      {r.win_rate_all.toFixed(2)}
                    </td>
                    <td className={cell(r.win_rate_venue === bestWinVenue)}>
                      {r.win_rate_venue > 0 ? r.win_rate_venue.toFixed(2) : "—"}
                    </td>
                    <td className={cell(r.avg_st === bestSt)}>
                      {r.avg_st > 0 ? r.avg_st.toFixed(2) : "—"}
                    </td>
                    <td className="num">
                      {r.f_count}/{r.l_count}
                    </td>
                    {partCell(r.motor_no, r.motor_in2_rate, r.motor_in2_rate === bestMotor)}
                    {partCell(r.boat_no, r.boat_in2_rate, r.boat_in2_rate === bestBoat)}
                    {hasExhibit && (
                      <td className={cell(r.exhibit_time === bestExhibit)}>
                        {r.exhibit_time ? r.exhibit_time.toFixed(2) : "—"}
                      </td>
                    )}
                    {hasPrev && (
                      <td className="num">
                        {r.prev_race_no != null ? (
                          <>
                            {r.prev_course != null && `${r.prev_course}コース `}
                            <span style={{ fontWeight: 700 }}>
                              {r.prev_foul ?? (r.prev_rank != null ? `${r.prev_rank}着` : "—")}
                            </span>
                            {r.prev_st != null && (
                              <span className="muted">
                                {" "}
                                {r.prev_st < 0 ? "F" : ""}
                                {Math.abs(r.prev_st).toFixed(2)}
                              </span>
                            )}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h3>市場勝率</h3>
          <ProbBars
            values={marketValues}
            max={1}
            format={(v) => `${(v * 100).toFixed(1)}%`}
          />
          {race.overround != null && (
            <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 10 }}>
              控除前オッズ総和{" "}
              <span className="num">{race.overround.toFixed(3)}</span>
              （控除率25%なら約1.334）
            </p>
          )}
        </div>

        <div className="card">
          <h3>コース標準との差</h3>
          <DivergingBars
            values={deviation}
            format={(v) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}pt`}
          />
          <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 10 }}>
            右が全国平均より高い評価、左が低い評価。尺度はレースによらず
            ±30pt に固定しているので、棒の長さはそのままレース間で比べられます。
            棒の半分が ±15pt です。
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

    </main>
  );
}
