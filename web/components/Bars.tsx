import { LaneBadge } from "./LaneBadge";

/** 艇番バッジ(20px)＋間隔(10px)。軸の目盛りを棒の左端に合わせるために使う。 */
const TRACK_INSET_LEFT = 30;
/** 数値ラベル(54px)＋間隔(10px)。同じく棒の右端に合わせる。 */
const TRACK_INSET_RIGHT = 64;

/**
 * 尺度の外に出た棒の端を削る矢羽根の長さ。
 * 平らに切ると「ちょうど上限の値」と読めてしまい、その先まで届いている棒と
 * 区別がつかない。ProbBars と DivergingBars で同じ形にする。
 */
const OVERFLOW_TIP = 6;

/**
 * 棒の下に敷く目盛り。3等分したグリッドの中央列を中央揃えにするので、
 * 中央のラベルはちょうど 50%（＝ゼロ基準線）の位置に来る。
 *
 * DotPlot が軸の実レンジを併記しているのと同じ理由で置いている。
 * 尺度が書かれていない棒は、読者が「満杯＝100%」と誤読しても気づけない。
 *
 * DotPlot も同じ目盛りを使う。以前は同じ形を自前で描いていたが、
 * flex の space-between だったため中央ラベルの位置が左右ラベルの文字幅に
 * 依存していた（このグリッドは依存しない）。
 */
export function ScaleAxis({
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
 *
 * 上限を超えた値は端で平らに切らず、DivergingBars と同じ矢羽根にする。
 * 平らに切ると「ちょうど上限」と読めてしまう。呼び出し側が
 * max ≧ 観測最大 を渡していれば起きないが、部品としては上限を
 * 外から渡せる以上、超過を表せないほうがおかしい。
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
  const anyOverflow = present.some((v) => v.value > scale);

  return (
    <div>
      <div style={{ display: "grid", gap: 6 }}>
        {values.map(({ lane, value, label }) => {
          const pct = value != null && scale > 0 ? (value / scale) * 100 : 0;
          const overflow = pct > 100;
          const width = Math.min(Math.max(pct, 0), 100);
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
                  title={
                    text == null
                      ? "未取得"
                      : overflow
                        ? `${text}（尺度 ${format(scale)} を超過）`
                        : text
                  }
                  style={{
                    width: `${width}%`,
                    height: "100%",
                    background: strong ? "var(--seq-strong)" : "var(--seq-mid)",
                    clipPath: overflow ? OVERFLOW_CLIP_RIGHT : undefined,
                  }}
                />
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
                {text ?? "—"}
              </span>
            </div>
          );
        })}
      </div>

      {/* 棒の満杯が何%なのかを明示する。長さだけでは読み取れない。 */}
      <ScaleAxis left={format(0)} right={format(scale)} />

      {anyOverflow && (
        <p
          className="muted"
          style={{ fontSize: 11, margin: "6px 0 0", marginLeft: TRACK_INSET_LEFT }}
        >
          端が尖った棒は、目盛り（{format(scale)}）の外まで届いています。
        </p>
      )}
    </div>
  );
}

/** コース標準との差の固定尺度。棒の端＝±30pt（＝±0.30）。 */
export const DIVERGING_SCALE = 0.3;

/** 右端を矢羽根に削る。正の側の振り切れと ProbBars で共有する。 */
const OVERFLOW_CLIP_RIGHT =
  `polygon(0 0, calc(100% - ${OVERFLOW_TIP}px) 0, 100% 50%,` +
  ` calc(100% - ${OVERFLOW_TIP}px) 100%, 0 100%)`;
/** 左端を矢羽根に削る。負の側の振り切れ。 */
const OVERFLOW_CLIP_LEFT =
  `polygon(${OVERFLOW_TIP}px 0, 100% 0, 100% 100%,` +
  ` ${OVERFLOW_TIP}px 100%, 0 50%)`;

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
              ? OVERFLOW_CLIP_RIGHT
              : OVERFLOW_CLIP_LEFT;
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

/*
 * 一覧の行に置く小さな発散指標。
 *
 * トップページの「まもなく締切」は1行が1レースなので、6本の棒は入らない。
 * 1号艇の1本だけを、DivergingBars と同じ ±30pt の固定尺度で描く。
 * 尺度を共有しているので、一覧で見た棒とレース詳細で見た棒は同じ長さになる。
 *
 * 目盛りは行ごとに敷くと12行ぶん重複するので、列見出しに1つだけ置く
 * （MiniDivergingScale）。トラック幅を定数で共有し、見出しの目盛りと
 * 行の棒の左右端が揃うようにしている。
 */

/** 小さな発散指標のトラック幅。目盛りと棒で共有する。 */
const MINI_TRACK = 112;
/** 数値ラベルの幅。 */
const MINI_LABEL = 54;
/** トラックと数値ラベルの間隔。 */
const MINI_GAP = 8;
/** 見出しと行が同じ幅の塊になるよう、合計幅を持つ。 */
const MINI_TOTAL = MINI_TRACK + MINI_GAP + MINI_LABEL;

/**
 * 列見出しに置く見出し＋目盛り。棒と同じ幅のグリッドなので、中央は正確に
 * ゼロに来る。見出しと棒を同じ幅の塊にすることで、目盛りの左右端が
 * 各行の棒の左右端と揃う。
 */
export function MiniDivergingScale({
  label,
  format,
  scale = DIVERGING_SCALE,
}: {
  label: string;
  format: (v: number) => string;
  scale?: number;
}) {
  return (
    <div style={{ width: MINI_TOTAL, margin: "0 auto" }}>
      <div>{label}</div>
      <div
        className="num"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          width: MINI_TRACK,
          marginTop: 3,
          fontSize: 10,
          fontWeight: 400,
          color: "var(--text-muted)",
        }}
      >
        <span style={{ textAlign: "left" }}>{format(-scale)}</span>
        <span style={{ textAlign: "center" }}>0</span>
        <span style={{ textAlign: "right" }}>{format(scale)}</span>
      </div>
    </div>
  );
}

/** 1本ぶんの発散指標。振り切れの表し方は DivergingBars と同じ。 */
export function MiniDivergingBar({
  value,
  format,
  scale = DIVERGING_SCALE,
}: {
  value: number | null;
  format: (v: number) => string;
  scale?: number;
}) {
  const ratio = value != null && scale > 0 ? Math.abs(value) / scale : 0;
  const overflow = ratio > 1;
  const half = Math.min(ratio, 1) * 50;
  const positive = (value ?? 0) >= 0;

  return (
    <div
      style={{
        width: MINI_TOTAL,
        margin: "0 auto",
        display: "flex",
        alignItems: "center",
        gap: MINI_GAP,
      }}
    >
      <div style={{ width: MINI_TRACK, position: "relative", height: 10 }}>
        {/*
          オッズ未取得のときはトラックもゼロ基準線も描かない。1行1本のこの形では、
          地色と中央線だけが残ると「差が0pt」に見えてしまう。行は残して「—」を出す。
          （6本並ぶ DivergingBars は他の艇の棒が基準になるのでトラックを残している）
        */}
        {value != null && (
          <>
            <div
              style={{ position: "absolute", inset: 0, background: "var(--div-mid)" }}
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
                clipPath: overflow
                  ? positive
                    ? OVERFLOW_CLIP_RIGHT
                    : OVERFLOW_CLIP_LEFT
                  : undefined,
              }}
            />
          </>
        )}
      </div>
      <span
        className="num"
        style={{
          width: MINI_LABEL,
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
}
