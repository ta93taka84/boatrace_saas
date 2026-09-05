import type { Metadata } from "next";
import Link from "next/link";
import { Analytics } from "@vercel/analytics/next";
import { SiteNav } from "@/components/SiteNav";
import "./globals.css";

/*
 * 書体は globals.css のフォントスタックに任せている。参考サイト（chariloto.com）が
 * メイリオ系の日本語ゴシックを使っており、本文がほぼ日本語のこのサイトでは
 * 端末に入っている書体で足りる。Webフォントを読み込むと、日本語グリフを
 * 持たない欧文フォントのためだけに通信が増えることになる。
 *
 * アクセス解析は Vercel Web Analytics（@vercel/analytics）。
 * cookie も localStorage も使わず、訪問者はリクエストから作るハッシュで
 * 数えられ、24時間で破棄される。ログインもフォームも無いサイトなので、
 * URLに個人情報が乗ることはない。
 *
 * Vercel のダッシュボードで Analytics を有効にしていない間、この部品は
 * 何も送らない（スクリプトの読み込みが404になるだけで、画面は壊れない）。
 * 手元の dev サーバでも送信しない。
 *
 * 何を集めて何を集めないかは /about の「アクセス解析」に書いてある。
 * 集める項目を増やすときは、そちらの記載も必ず直すこと。
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
        <Analytics />
      </body>
    </html>
  );
}
