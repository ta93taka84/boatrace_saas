import Link from "next/link";

function label(date: string) {
  return `${date.slice(4, 6)}/${date.slice(6, 8)}`;
}

/**
 * 取得済みの日付を新しい順に並べる。データのある日だけを出すので、
 * 空の日付を開いてしまうことがない。
 *
 * 見た目は参考サイト（chariloto.com）の開催場・レース選択と同じタブ帯。
 * 四角い枠を隙間なく並べ、選択中だけ赤ベタに白文字で反転させる。
 *
 * 選択中の色にはチャートの系列色ではなくUIのアクセントを使う。逐次色と
 * 同じ色で塗ると、選択されたタブが「値の大きい棒」に見えて操作とデータの
 * 区別がつかなくなるため。
 */
export function DateNav({ dates, current }: { dates: string[]; current: string }) {
  if (dates.length <= 1) return null;

  return (
    <nav className="tabs" aria-label="日付">
      <span className="tabs-label">日付</span>
      {dates.slice(0, 14).map((d) => (
        <Link
          key={d}
          href={`/?date=${d}`}
          aria-current={d === current ? "page" : undefined}
        >
          {label(d)}
        </Link>
      ))}
    </nav>
  );
}
