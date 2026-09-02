import { LaneBadge } from "./LaneBadge";

/**
 * 狭い範囲に密集した値の比較に使うドットプロット。
 *
 * 展示タイムは6艇が0.1秒程度の幅に収まる。これを棒グラフにすると
 * 基準を任意にずらすことになり、わずかな差が棒の長さの何倍もの差に
 * 見えてしまう。共通の軸に点を置けば、差の実際の小ささがそのまま伝わる。
 */
export function DotPlot({
  values,
  format,
  lowerIsBetter = false,
  unit,
}: {
  values: { lane: number; value: number | null }[];
  format: (v: number) => string;
  lowerIsBetter?: boolean;
  unit?: string;
}) {
  const present = values.filter((v) => v.value != null) as { lane: number; value: number }[];
  if (present.length === 0) {
    return <p className="muted" style={{ fontSize: 13 }}>データ未取得</p>;
  }

  const min = Math.min(...present.map((v) => v.value));
  const max = Math.max(...present.map((v) => v.value));
  const span = max - min || 1;
  // 両端に少し余白を取り、点が枠に貼りつかないようにする
  const lo = min - span * 0.15;
  const hi = max + span * 0.15;
  const best = lowerIsBetter ? min : max;

  return (
    <div>
      <div style={{ display: "grid", gap: 6 }}>
        {values.map(({ lane, value }) => {
          const pct = value != null ? ((value - lo) / (hi - lo)) * 100 : 0;
          const isBest = value === best;
          return (
            <div key={lane} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <LaneBadge lane={lane} size={20} />
              <div style={{ flex: 1, position: "relative", height: 14 }}>
                {/* 軸線 */}
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    top: "50%",
                    height: 1,
                    background: "var(--grid)",
                  }}
                />
                {value != null && (
                  <div
                    title={format(value)}
                    style={{
                      position: "absolute",
                      left: `${pct}%`,
                      top: "50%",
                      width: 10,
                      height: 10,
                      marginLeft: -5,
                      marginTop: -5,
                      borderRadius: "50%",
                      background: isBest ? "var(--seq-strong)" : "var(--seq-mid)",
                      // 重なっても輪郭が消えないよう地色のリングを置く
                      boxShadow: "0 0 0 2px var(--surface-1)",
                    }}
                  />
                )}
              </div>
              <span
                className="num"
                style={{
                  minWidth: 60,
                  textAlign: "right",
                  fontSize: 12,
                  fontWeight: isBest ? 700 : 400,
                  color: value != null ? "var(--text-primary)" : "var(--text-muted)",
                }}
              >
                {value != null ? format(value) : "—"}
              </span>
            </div>
          );
        })}
      </div>

      {/* 軸の実レンジを明示する。これが無いと点の位置だけでは差の大きさが分からない。 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginLeft: 30,
          marginRight: 70,
          marginTop: 6,
          fontSize: 11,
          color: "var(--text-muted)",
        }}
        className="num"
      >
        <span>{format(lo)}</span>
        <span>
          幅 {(max - min).toFixed(2)}
          {unit}
        </span>
        <span>{format(hi)}</span>
      </div>
    </div>
  );
}
