import Link from "next/link";
import { getStats } from "@/lib/stats";
import { ProbBars } from "@/components/Bars";
import { LaneBadge } from "@/components/LaneBadge";
import { ErrorCard } from "@/components/ErrorCard";

export const dynamic = "force-dynamic";
export const metadata = { title: "実績集計｜ボートレース データビュー" };

/** 全国平均の目安。実測と並べて比較する。 */
const COURSE_BASE: Record<number, number> = {
  1: 0.55, 2: 0.145, 3: 0.12, 4: 0.105, 5: 0.055, 6: 0.025,
};

/** 標準誤差。n件の割合pのばらつきの目安。 */
function se(p: number, n: number) {
  return n > 0 ? Math.sqrt((p * (1 - p)) / n) : 0;
}

export default async function StatsPage() {
  let stats = null;
  let failure: unknown = null;
  try {
    stats = await getStats();
  } catch (e) {
    failure = e;
  }

  if (failure) {
    return (
      <main className="wrap">
        <h1>実績集計</h1>
        <ErrorCard where="過去レースの集計" error={failure} />
      </main>
    );
  }

  if (!stats) {
    return (
      <main className="wrap">
        <p className="crumb">
          <Link href="/">レース一覧</Link> ＞ 実績集計
        </p>
        <h1>実績集計</h1>
        <div className="card">
          <p style={{ margin: 0 }}>
            過去データがまだありません。
            <code> py -3 backtest.py collect 開始日 終了日 </code>
            で収集してください。
          </p>
        </div>
      </main>
    );
  }

  const { races, dates, courseWinRate, byVenue, kimarite, payout } = stats;
  const span =
    dates.length > 1 ? `${dates[0]}〜${dates[dates.length - 1]}` : dates[0];

  // サンプルが少ない場ほど数字が振れる。判断を誤らせないよう閾値を持つ。
  const RELIABLE = 60;
  const reliable = byVenue.filter((v) => v.races >= RELIABLE);
  const thin = byVenue.filter((v) => v.races < RELIABLE);

  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/">レース一覧</Link> ＞ 実績集計
      </p>
      <h1>実績集計</h1>
      <p className="sub">
        {span} ・ <span className="num">{races}</span>レース
      </p>

      <div className="notice">
        標本は{races}レース。割合の標準誤差は概ね ±
        {(se(0.5, races) * 100).toFixed(1)}pt で、この幅の差は偶然と区別できません。
      </div>

      <div className="grid2">
        <div className="card">
          <h3>コース別1着率（実測）</h3>
          <ProbBars
            values={courseWinRate.map((c) => ({
              lane: c.lane,
              value: c.rate,
              label: `${(c.rate * 100).toFixed(1)}%`,
            }))}
            max={Math.max(...courseWinRate.map((c) => c.rate))}
            format={(v) => `${(v * 100).toFixed(1)}%`}
          />
        </div>

        <div className="card">
          <h3>全国平均の目安との比較</h3>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th className="l">コース</th>
                  <th>実測</th>
                  <th>目安</th>
                  <th>差</th>
                  <th>±SE</th>
                </tr>
              </thead>
              <tbody>
                {courseWinRate.map((c) => {
                  const diff = c.rate - COURSE_BASE[c.lane];
                  const err = se(c.rate, races);
                  // 差が標準誤差の2倍を超えなければ、目安とのずれとは言えない。
                  const meaningful = Math.abs(diff) > 2 * err;
                  return (
                    <tr key={c.lane}>
                      <td className="l">
                        <LaneBadge lane={c.lane} size={18} />
                      </td>
                      <td className="num">{(c.rate * 100).toFixed(1)}%</td>
                      <td className="num muted">
                        {(COURSE_BASE[c.lane] * 100).toFixed(1)}%
                      </td>
                      <td
                        className="num"
                        style={{
                          color: meaningful ? "var(--text-primary)" : "var(--text-muted)",
                          fontWeight: meaningful ? 700 : 400,
                        }}
                      >
                        {diff >= 0 ? "+" : ""}
                        {(diff * 100).toFixed(1)}
                      </td>
                      <td className="num muted">{(err * 100).toFixed(1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 10 }}>
            差が標準誤差の2倍を超えた行だけ濃く表示しています。
          </p>
        </div>
      </div>

      <div className="card">
        <h3>決まり手の内訳</h3>
        <div style={{ display: "grid", gap: 6 }}>
          {kimarite.map((k) => (
            <div key={k.name} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ minWidth: 78, fontSize: 13 }}>{k.name}</span>
              <div
                style={{
                  flex: 1,
                  height: 14,
                  background: "var(--grid)",
                  borderRadius: 4,
                  overflow: "hidden",
                }}
              >
                <div
                  title={`${k.count}件 ${(k.share * 100).toFixed(1)}%`}
                  style={{
                    width: `${k.share * 100}%`,
                    height: "100%",
                    background: "var(--seq-mid)",
                    borderRadius: 4,
                  }}
                />
              </div>
              <span className="num" style={{ minWidth: 84, textAlign: "right", fontSize: 12 }}>
                {(k.share * 100).toFixed(1)}%
                <span className="muted"> ({k.count})</span>
              </span>
            </div>
          ))}
        </div>
      </div>

      {payout && (
        <div className="card">
          <h3>三連単配当の水準</h3>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 16,
            }}
          >
            {[
              { label: "中央値", value: `¥${payout.median.toLocaleString()}` },
              { label: "下位25%", value: `¥${payout.p25.toLocaleString()}` },
              { label: "上位25%", value: `¥${payout.p75.toLocaleString()}` },
              { label: "1万円以上", value: `${(payout.bigShare * 100).toFixed(0)}%` },
              { label: "最高", value: `¥${payout.max.toLocaleString()}` },
            ].map((s) => (
              <div key={s.label}>
                <div className="muted" style={{ fontSize: 11 }}>{s.label}</div>
                <div className="num" style={{ fontSize: 20, fontWeight: 700 }}>
                  {s.value}
                </div>
              </div>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 14 }}>
            半数は約{Math.round(payout.median / 100)}倍以下、
            {(payout.bigShare * 100).toFixed(0)}%が100倍超。平均は高額配当に
            引っ張られるため、中央値のほうが実態に近くなります。
          </p>
        </div>
      )}

      <div className="card">
        <h3>場別の1コース1着率</h3>
        {reliable.length > 0 ? (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th className="l">場</th>
                  <th>1コース1着率</th>
                  <th>レース数</th>
                </tr>
              </thead>
              <tbody>
                {reliable.map((v) => (
                  <tr key={v.code}>
                    <td className="l">{v.name}</td>
                    <td className="num">{(v.lane1Rate * 100).toFixed(1)}%</td>
                    <td className="num muted">{v.races}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted" style={{ marginTop: 0 }}>
            各場 {RELIABLE} レース以上たまると、場ごとの傾向を出します。
          </p>
        )}

        {thin.length > 0 && (
          <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 12 }}>
            {thin.length}場は標本が{RELIABLE}レース未満のため表示していません。
            十数レースの1コース1着率は偶然で0.2〜0.7に散らばります。
          </p>
        )}
      </div>
    </main>
  );
}
