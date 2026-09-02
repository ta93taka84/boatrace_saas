import Link from "next/link";

function label(date: string) {
  return `${date.slice(4, 6)}/${date.slice(6, 8)}`;
}

/**
 * 取得済みの日付を新しい順に並べる。データのある日だけを出すので、
 * 空の日付を開いてしまうことがない。
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
              border: `1px solid ${active ? "var(--seq-strong)" : "var(--grid)"}`,
              background: active ? "var(--seq-strong)" : "transparent",
              color: active ? "#fff" : "var(--text-secondary)",
            }}
          >
            {label(d)}
          </Link>
        );
      })}
    </nav>
  );
}
