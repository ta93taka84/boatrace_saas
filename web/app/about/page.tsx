import Link from "next/link";

export const metadata = { title: "データについて｜ボートレース データビュー" };

export default function About() {
  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/">レース一覧</Link> ＞ データについて
      </p>
      <h1>データについて</h1>

      <div className="card">
        <h2>市場勝率</h2>
        <p style={{ marginTop: 0 }}>
          公式サイトの三連単オッズ120通りから、各艇が1着になる確率を逆算しています。
          ある艇が1着になる組み合わせは20通りあるので、その
          インプライド確率（1÷オッズ）を合計し、全体で正規化します。
        </p>
        <p style={{ marginBottom: 0 }}>
          正規化前の合計は約 <strong className="num">1.334</strong> です。控除率25%の
          逆数にあたり、各レースの画面には「控除前オッズ総和」として出しています。
        </p>
      </div>

      <div className="card">
        <h2>コース標準との差</h2>
        <p style={{ marginTop: 0 }}>
          コース別の1着率には全国平均の目安があります（1コース約55%、2コース約15%、
          3コース約12%、4コース約11%、5コース約6%、6コース約3%）。
          市場勝率がこの目安からどちらにどれだけ振れているかを示したものです。
        </p>
        <p style={{ marginBottom: 0 }}>
          1号艇が大きく左（橙）に振れているレースは、標準どおりのイン逃げには
          なりにくいと市場が見ていることを表します。
        </p>
      </div>

      <div className="card">
        <h2>展示タイム</h2>
        <p style={{ marginTop: 0, marginBottom: 0 }}>
          6艇が0.1秒程度の幅に収まります。差の大きさが分かるよう、
          共通の軸に点を置き、軸の実際のレンジを併記しています。
        </p>
      </div>

      <div className="card" style={{ borderColor: "var(--warning)" }}>
        <h2>予測モデル</h2>
        <p style={{ marginTop: 0 }}>
          コース別の基準に、選手の級別・勝率・平均ST・展示タイム・気象で補正を
          かけて各艇の勝率を推定しています。ただし
          <strong>市場オッズより精度が低い</strong>ため、期待値は画面に出していません。
        </p>
        <p>
          検証612レース（2026年8月29日〜9月1日）での成績です。
          LogLossとBrierは小さいほど良い値です。
        </p>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th className="l">予測</th>
                <th>LogLoss</th>
                <th>Brier</th>
                <th>的中率</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="l">市場オッズ</td>
                <td className="num">1.167</td>
                <td className="num">0.579</td>
                <td className="num">56.4%</td>
              </tr>
              <tr>
                <td className="l">当モデル</td>
                <td className="num">1.266</td>
                <td className="num">0.614</td>
                <td className="num">55.1%</td>
              </tr>
              <tr>
                <td className="l muted">コース基準のみ</td>
                <td className="num muted">1.426</td>
                <td className="num muted">0.679</td>
                <td className="num muted">51.8%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p style={{ marginBottom: 0, marginTop: 14 }}>
          市場を下回るモデルの期待値は優位性を示しません。
          検証で上回った時点で公開します。
        </p>
      </div>

      <div className="card">
        <h2>データの取得</h2>
        <p style={{ marginTop: 0, marginBottom: 0 }}>
          公式サイトから2秒間隔で取得しています。出走表は朝に1回、
          展示タイムとオッズは締切30分以内のレースを20分ごと、結果は全レース終了後に1回。
          オッズは締切に向けて動くため、表示は最後に取得した時点の値です。
        </p>
      </div>
    </main>
  );
}
