import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ボートレース データビュー",
  description: "全場のレースデータを集約して比較する",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
