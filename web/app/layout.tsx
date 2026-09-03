import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";

/*
 * 数字と英字を等幅にする。表の桁が揃い、オッズや勝率を縦に読み比べられる。
 * 日本語グリフは持たないので、日本語は globals.css 側のフォールバックが描く。
 * next/font はビルド時にフォントを取得して自前で配信するため、
 * 外部CDNへのリクエストは発生しない。
 */
const geistMono = Geist_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "ボートレース データビュー",
  description: "全場のレースデータを集約して比較する",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja" className={geistMono.variable}>
      <body>{children}</body>
    </html>
  );
}
