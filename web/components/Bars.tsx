import { LaneBadge } from "./LaneBadge";

/** 艇番バッジ(20px)＋間隔(10px)。軸の目盛りを棒の左端に合わせるために使う。 */
const TRACK_INSET_LEFT = 30;
/** 数値ラベル(54px)＋間隔(10px)。同じく棒の右端に合わせる。 */
const TRACK_INSET_RIGHT = 64;

/**
 * 棒の下に敷く目盛り。3等分したグリッドの中央列を中央揃えにするので、
 * 中央のラベルはちょうど 50%（＝ゼロ基準線）の位置に来る。
 *
 * DotPlot が軸の実レンジを併記しているのと同じ理由で置いている。
 * 尺度が書かれていない棒は、読者が「満杯＝100%」と誤読しても気づけない。
 */
function ScaleAxis({
  left,
  center,
  right,
}: {
  left: string;
  center?: string;
  right: string;
}) {
  return (
    <div
      className="num"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        marginLeft: TRACK_INSET_LEFT,
        marginRight: TRACK_INSET_RIGHT,
        marginTop: 6,
        fontSize: 11,
        color: "var(--text-muted)",
      }}
    >
      <span style={{ textAlign: "left" }}>{left}</span>
      <span style={{ textAlign: "center" }}>{center ?? ""}</span>
      <span style={{ textAlign: "right" }}>{right}</span>
    </div>
  );
}

/**
 * 艇別の大小比較。単一系列なので凡例は置かず、逐次色相1つで塗る。
 * 6本すべてに値を直接書くため、ホバーに頼らず読める。
 *
 * ゼロ基点なので棒の長さは値に比例する。ただし「棒の満杯が何を指すか」は
 * 長さだけでは分からないので、軸の上限を必ず下に書く（ScaleAxis）。
 * これが無いと、最大値でスケールした棒が「100%」と読まれる。
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
    <div>
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

      {/* 棒の満杯が何%なのかを明示する。長さだけでは読み取れない。 */}
      <ScaleAxis left={format(0)} right={format(scale)} />
    </div>
  );
}

/** コース標準との差の固定尺度。棒の端＝±30pt（＝±0.30）。 */
const DIVERGING_SCALE = 0.3;
/** 振り切れを示す矢羽根の長さ。 */
const OVERFLOW_TIP = 6;

/**
 * コース標準からの乖離。正負の極性を持つので発散型で描く。
 * 中央が「標準どおり」で、右が市場の高評価、左が低評価。
 * 市場が1号艇以外を本命視しているレースが一目で分かる。
 *
 * 正の側は青、負の側は赤。UIのアクセントは金なので、赤とぶつからない。
 * （アクセントが赤だった頃は負の側を橙にしていた。globals.css に経緯がある）
 *
 * **尺度はレースごとに正規化せず ±30pt に固定する。** 以前は
 * `max(|値|)` で正規化していたため、乖離±1ptの平凡なレースと±25ptの
 * 異常なレースがまったく同じ長さの棒になり、数字を読まないと区別できなかった。
 * この指標は絶対値に意味がある（±5pt / ±15pt の層で1号艇1着率が
 * 23.5% → 41.3% → 59.1% → 68.7% → 79.6% と単調に動き、隣接層が2SEで分離する）。
 * 正規化はその意味を捨てていた。
 *
 * ±30pt という値は実データ1,236レース・延べ7,416艇の分布から決めている。
 * |乖離| の中央値5.2pt / 90%点19.2pt / 95%点26.2pt。この尺度なら境界として
 * 意味のある±15ptがちょうど棒の半分になり、振り切れるのは3.3%だけになる。
 *
 * 振り切れた棒は端で切らず、外側を矢羽根に削って「まだ先がある」ことを示す。
 * 平らに切ると「ちょうど±30pt」と読めてしまい、±58ptのレースと区別がつかない。
 */
export function DivergingBars({
  values,
  format,
  scale = DIVERGING_SCALE,
}: {
  values: { lane: number; value: number | null }[];
  format: (v: number) => string;
  scale?: number;
}) {
  const present = values.filter((v) => v.value != null) as { lane: number; value: number }[];
  if (present.length === 0) {
    return <p className="muted" style={{ fontSize: 13 }}>データ未取得</p>;
  }
  const anyOverflow = present.some((v) => Math.abs(v.value) > scale);

  return (
    <div>
      <div style={{ display: "grid", gap: 6 }}>
        {values.map(({ lane, value }) => {
          const ratio = value != null && scale > 0 ? Math.abs(value) / scale : 0;
          const overflow = ratio > 1;
          const half = Math.min(ratio, 1) * 50;
          const positive = (value ?? 0) >= 0;
          // 振り切れた棒は外側の端を三角に削る。平らな端＝「尺度の内側で
          // ちょうど端まで来た」と区別できるようにするため。
          const clip = !overflow
            ? undefined
            : positive
              ? `polygon(0 0, calc(100% - ${OVERFLOW_TIP}px) 0, 100% 50%, calc(100% - ${OVERFLOW_TIP}px) 100%, 0 100%)`
              : `polygon(${OVERFLOW_TIP}px 0, 100% 0, 100% 100%, ${OVERFLOW_TIP}px 100%, 0 50%)`;
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
                    title={
                      overflow
                        ? `${format(value)}（尺度 ${format(scale)} を超過）`
                        : format(value)
                    }
                    style={{
                      position: "absolute",
                      top: 0,
                      height: "100%",
                      width: `${half}%`,
                      left: positive ? "50%" : `${50 - half}%`,
                      background: positive ? "var(--div-pos)" : "var(--div-neg)",
                      clipPath: clip,
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
                  fontWeight: overflow ? 700 : 400,
                  color: value != null ? "var(--text-primary)" : "var(--text-muted)",
                }}
              >
                {value != null ? format(value) : "—"}
              </span>
            </div>
          );
        })}
      </div>

      {/* 固定尺度なので、その範囲を書かないと棒の長さが何ptなのか分からない。 */}
      <ScaleAxis left={format(-scale)} center="0（標準）" right={format(scale)} />

      {anyOverflow && (
        <p
          className="muted"
          style={{ fontSize: 11, margin: "6px 0 0", marginLeft: TRACK_INSET_LEFT }}
        >
          端が尖った棒は、目盛り（{format(-scale)}〜{format(scale)}）の外まで
          届いています。

        </p>
      )}
    </div>
  );
}
