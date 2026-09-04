import Link from "next/link";

export const metadata = { title: "ページが見つかりません｜ボートレース データビュー" };

/**
 * 存在しない日付・開催場・レース番号を開いたときに出す。
 *
 * これを置かないと Next.js の既定の404が出る。素の英語1行で、
 * ヘッダもナビも無いため、戻る手段が無い行き止まりになる。
 *
 * 日付や開催場を打ち間違えただけということが多いので、
 * 「データが無い」ことと一覧への戻り口を必ず出す。
 */
export default function NotFound() {
  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/">レース一覧</Link> ＞ ページが見つかりません
      </p>
      <h1>ページが見つかりません</h1>
      <div className="card">
        <p style={{ marginTop: 0 }}>
          指定された日付・開催場・レースのデータがありません。
          開催の無い日や、まだ収集していない日を指しているかもしれません。
        </p>
        <p style={{ marginBottom: 0 }}>
          <Link href="/">レース一覧</Link> から、データのある日付を選んでください。
        </p>
      </div>
    </main>
  );
}
