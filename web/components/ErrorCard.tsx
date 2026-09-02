/**
 * データ取得に失敗したときに出す。
 *
 * データ層の不調でページ全体を500にすると、利用者には何も伝わらず、
 * 運用側も本番ログを見に行くまで原因が分からない。落とさずに
 * 「何が起きたか」を画面に出す。
 *
 * 表示するのはエラーメッセージだけで、接続情報や鍵は含めない。
 */
export function ErrorCard({ where, error }: { where: string; error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);

  return (
    <div className="card" style={{ borderColor: "var(--critical)" }}>
      <h3 style={{ color: "var(--critical)" }}>データを取得できませんでした</h3>
      <p style={{ marginTop: 0 }}>
        {where}の読み込みに失敗しました。時間をおいて再度お試しください。
      </p>
      <pre
        className="scroll-x"
        style={{
          background: "var(--page)",
          padding: 12,
          borderRadius: 6,
          fontSize: 12,
          margin: 0,
          color: "var(--text-secondary)",
        }}
      >
        {message}
      </pre>
    </div>
  );
}
