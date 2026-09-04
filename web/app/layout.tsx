import type { Metadata } from "next";
import Link from "next/link";
import { SiteNav } from "@/components/SiteNav";
import "./globals.css";

/*
 * 書体は globals.css のフォントスタックに任せている。参考サイト（chariloto.com）が
 * メイリオ系の日本語ゴシックを使っており、本文がほぼ日本語のこのサイトでは
 * 端末に入っている書体で足りる。Webフォントを読み込むと、日本語グリフを
 * 持たない欧文フォントのためだけに通信が増えることになる。
 */

export const metadata: Metadata = {
  title: "ボートレース データビュー",
  description: "ボートレース24場の出走表・オッズ・結果。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <header className="site">
          <div className="site-inner">
            <Link href="/" className="site-logo">
              ボートレース データビュー
            </Link>
          </div>
        </header>
        <SiteNav />
        {children}
      </body>
    </html>
  );
}
