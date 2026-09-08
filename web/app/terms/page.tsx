import Link from "next/link";

export const metadata = { title: "免責事項｜ボートレース データビュー" };

/**
 * 免責事項。**公開側に必ず置くページ。**
 *
 * 以前は /about の中にあったが、/about は開発者向けの検証データを並べた
 * 画面なので表から下げた。免責事項は利用者向けの情報なので、こちらに移して
 * フッターとAI予想エリアの両方から辿れるようにしている。
 */
export default function TermsPage() {
  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/">レース一覧</Link> ＞ 免責事項
      </p>
      <h1>免責事項</h1>

      <div className="card">
        <h2>情報の正確性について</h2>
        <p style={{ marginTop: 0 }}>
          本サイトは個人が運営するもので、公式発表ではありません。データは
          ボートレース公式サイトから自動で取得していますが、取得の失敗や解析の
          誤りが起こりえます。<strong>内容の正確性・完全性は保証しません。</strong>
          出走表・オッズ・結果は、必ず公式の発表をご確認ください。
        </p>
        <p style={{ marginBottom: 0 }}>
          表示しているオッズは取得した時点の値です。締切に向けて変動するため、
          購入時の値とは異なります。
        </p>
      </div>

      <div className="card">
        <h2>AI予想について</h2>
        <p style={{ marginTop: 0 }}>
          「AI予想」および期待値は、過去のデータから作った統計モデルによる推定です。
          <strong>的中や利益を保証するものではありません。</strong>
          推奨買い目は当たりやすい順ではなく、オッズに対して確率が高い順に
          並べたものです。
        </p>
        <p style={{ marginBottom: 0 }}>
          舟券の購入はご自身の判断と責任で行ってください。本サイトの情報を用いて
          生じたいかなる損害についても、運営者は責任を負いません。
        </p>
      </div>

      <div className="card" style={{ borderColor: "var(--warning)" }}>
        <h2>舟券の購入について</h2>
        <p style={{ marginTop: 0 }}>
          <strong>20歳未満の方は舟券を購入できません。</strong>
        </p>
        <p style={{ marginBottom: 0 }}>
          舟券の購入は余裕資金の範囲で行ってください。のめり込みや生活への支障を
          感じたときは、購入を止めて公的な相談窓口にご相談ください。
        </p>
      </div>
    </main>
  );
}
