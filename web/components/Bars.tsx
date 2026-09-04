import { LaneBadge } from "./LaneBadge";

/**
 * 艇別の大小比較。単一系列なので凡例は置かず、逐次色相1つで塗る。
 * 6本すべてに値を直接書くため、ホバーに頼らず読める。
 */
export function ProbBars({
  values,
  format,
  max,
  emphasize,
}: {
  values: { lane: number; value: number | null; label?: string }[];
  format: (v: number) => string;
  max?: number;
  emphasize?: number;
}) {
  const present = values.filter((v) => v.value != null) as { lane: number; value: number }[];
  if (present.length === 0) {
    return <p className="muted" style={{ fontSize: 13 }}>データ未取得</p>;
  }
  const scale = max ?? Math.max(...present.map((v) => v.value));

  return (
    <div style={{ display: "grid", gap: 6 }}>
      {values.map(({ lane, value, label }) => {
        const pct = value != null && scale > 0 ? (value / scale) * 100 : 0;
        const strong = emphasize === lane;
        const text = value != null ? (label ?? format(value)) : null;
        return (
          <div key={lane} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <LaneBadge lane={lane} size={20} />
            <div
              style={{
                flex: 1,
                height: 14,
                background: "var(--grid)",
                overflow: "hidden",
              }}
            >
              <div
                title={text ?? "未取得"}
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: strong ? "var(--seq-strong)" : "var(--seq-mid)",
                }}
              />
            </div>
            <span
              className="num"
              style={{
                minWidth: 54,
                textAlign: "right",
                fontSize: 12,
                color: value != null ? "var(--text-primary)" : "var(--text-muted)",
              }}
            >
              {text ?? "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * コース標準からの乖離。正負の極性を持つので発散型で描く。
 * 中央が「標準どおり」で、右が市場の高評価、左が低評価。
 * 市場が1号艇以外を本命視しているレースが一目で分かる。
 *
 * 正の側は青、負の側は赤。UIのアクセントは金なので、赤とぶつからない。
 * （アクセントが赤だった頃は負の側を橙にしていた。globals.css に経緯がある）
 */
export function DivergingBars({
  values,
  format,
}: {
  values: { lane: number; value: number | null }[];
  format: (v: number) => string;
}) {
  const present = values.filter((v) => v.value != null) as { lane: number; value: number }[];
  if (present.length === 0) {
    return <p className="muted" style={{ fontSize: 13 }}>データ未取得</p>;
  }
  const scale = Math.max(...present.map((v) => Math.abs(v.value))) || 1;

  return (
    <div style={{ display: "grid", gap: 6 }}>
      {values.map(({ lane, value }) => {
        const half = value != null ? (Math.abs(value) / scale) * 50 : 0;
        const positive = (value ?? 0) >= 0;
        return (
          <div key={lane} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <LaneBadge lane={lane} size={20} />
            <div style={{ flex: 1, position: "relative", height: 14 }}>
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  background: "var(--div-mid)",
                }}
              />
              {/* 中央のゼロ基準線 */}
              <div
                style={{
                  position: "absolute",
                  left: "50%",
                  top: -2,
                  bottom: -2,
                  width: 1,
                  background: "var(--axis)",
                }}
              />
              {value != null && (
                <div
                  title={format(value)}
                  style={{
                    position: "absolute",
                    top: 0,
                    height: "100%",
                    width: `${half}%`,
                    left: positive ? "50%" : `${50 - half}%`,
                    background: positive ? "var(--div-pos)" : "var(--div-neg)",
                  }}
                />
              )}
            </div>
            <span
              className="num"
              style={{
                minWidth: 54,
                textAlign: "right",
                fontSize: 12,
                color: value != null ? "var(--text-primary)" : "var(--text-muted)",
              }}
            >
              {value != null ? format(value) : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
