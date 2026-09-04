"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * 全幅の金の帯のグローバルナビ。参考サイト（chariloto.com）と同じ作りで、
 * 項目を等幅に並べ、細い黒罫で区切る。
 *
 * 現在地の判定にパスが要るのでクライアントコンポーネントにしている。
 * レース詳細は一覧の下位なので、そちらも「レース一覧」を現在地として扱う。
 */
const ITEMS = [
  { href: "/", label: "レース一覧" },
  { href: "/stats", label: "実績集計" },
  { href: "/about", label: "データについて" },
];

export function SiteNav() {
  const path = usePathname();

  const current = (href: string) =>
    href === "/" ? path === "/" || path.startsWith("/race") : path.startsWith(href);

  return (
    <nav className="gnav" aria-label="メイン">
      <div className="gnav-inner">
        {ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={current(item.href) ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
