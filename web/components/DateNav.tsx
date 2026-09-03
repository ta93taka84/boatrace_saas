import Link from "next/link";

function label(date: string) {
  return `${date.slice(4, 6)}/${date.slice(6, 8)}`;
}

/**
 * 取得済みの日付を新しい順に並べる。データのある日だけを出すので、
 * 空の日付を開いてしまうことがない。
 *
 * 選択中の色にはチャートの系列色ではなくUIのアクセント（--accent）を使う。
 * 逐次色と同じ色で塗ると、選択されたタブが「値の大きい棒」に見えて
 * 操作とデータの区別がつかなくなるため。
 */
export function DateNav({ dates, current }: { dates: string[]; current: string }) {
  if (dates.length <= 1) return null;

  return (
    <nav
      aria-label="日付"
      style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 20 }}
    >
      {dates.slice(0, 14).map((d) => {
        const active = d === current;
        return (
          <Link
            key={d}
            href={`/?date=${d}`}
            aria-current={active ? "page" : undefined}
            className="num"
            style={{
              padding: "4px 10px",
              borderRadius: 6,
              fontSize: 12,
              textDecoration: "none",
              border: `1px solid ${active ? "var(--accent)" : "var(--grid)"}`,
              background: active ? "var(--accent)" : "transparent",
              color: active ? "var(--accent-ink)" : "var(--text-secondary)",
            }}
          >
            {label(d)}
          </Link>
        );
      })}
    </nav>
  );
}
