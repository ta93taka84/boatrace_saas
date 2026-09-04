/**
 * 艇番チップ。競技標準の艇色（1白2黒3赤4青5黄6緑）を識別に使う。
 * 数字を必ず内側に置くので、色が読めなくても艇番は伝わる。
 *
 * 参考サイト（chariloto.com）の車番表示に合わせて角丸を持たせない。
 * 同サイトも同じ番号色の慣習を四角いチップで表している。
 */
export function LaneBadge({ lane, size = 20 }: { lane: number; size?: number }) {
  return (
    <span
      aria-label={`${lane}号艇`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        background: `var(--lane-${lane}-bg)`,
        color: `var(--lane-${lane}-fg)`,
        border: `1px solid var(--lane-${lane}-br)`,
        fontSize: Math.round(size * 0.6),
        fontWeight: 700,
        fontVariantNumeric: "tabular-nums",
        lineHeight: 1,
      }}
    >
      {lane}
    </span>
  );
}
