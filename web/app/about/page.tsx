import Link from "next/link";

export const metadata = { title: "データについて｜ボートレース データビュー" };

export default function About() {
  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/">レース一覧</Link> ＞ データについて
      </p>
      <h1>データについて</h1>
      <p className="sub">何を出しているか、何を出していないか。</p>

      <div className="card">
        <h2>市場勝率</h2>
        <p style={{ marginTop: 0 }}>
          公式サイトの三連単オッズ120通りから、各艇が1着になる確率を逆算しています。
          ある艇が1着になる組み合わせは20通りあるので、その
          インプライド確率（1÷オッズ）を合計し、全体で正規化します。
        </p>
        <p>
          正規化前の合計は約 <strong className="num">1.334</strong> になります。
          これは控除率25%の逆数（1÷0.75）と一致し、オッズを取りこぼしなく
          読めていることの裏づけになります。各レースの画面に
          「控除前オッズ総和」として出しているのがこの値です。
          1.33前後から外れていたら取得に問題があります。
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
          1号艇が大きく左（赤）に振れているレースは、
          「標準どおりのイン逃げにはなりにくい」と市場が見ているということです。
          荒れる可能性を市場がどう織り込んでいるかが、数字を追わずに読み取れます。
        </p>
      </div>

      <div className="card">
        <h2>展示タイムの見せ方</h2>
        <p style={{ marginTop: 0, marginBottom: 0 }}>
          展示タイムは6艇が0.1秒程度の幅に収まります。これを棒グラフにすると
          基準を任意の位置にずらすことになり、0.08秒の差が棒の長さでは
          何倍もの差に見えてしまいます。誤読を招くので、共通の軸に点を置く
          ドットプロットで描き、軸の実際のレンジを併記しています。
        </p>
      </div>

      <div className="card" style={{ borderColor: "var(--warning)" }}>
        <h2>予測モデルについて（現状は非公開）</h2>
        <p style={{ marginTop: 0 }}>
          コース別の基準に選手の級別・全国勝率・モーター・スタートタイミングで
          補正をかけた予測モデルを持っていますが、
          <strong>現時点では市場オッズより精度が低い</strong>ため、
          期待値の推奨は画面に出していません。
        </p>
        <p>
          1236レース（2026年8月25日〜9月1日）での検証結果です。
          LogLossとBrierはどちらも小さいほど良い指標です。
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
                <td className="num">1.160</td>
                <td className="num">0.574</td>
                <td className="num">57.3%</td>
              </tr>
              <tr>
                <td className="l">当モデル</td>
                <td className="num">1.265</td>
                <td className="num">0.615</td>
                <td className="num">55.5%</td>
              </tr>
              <tr>
                <td className="l muted">コース基準のみ</td>
                <td className="num muted">1.407</td>
                <td className="num muted">0.669</td>
                <td className="num muted">53.0%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p style={{ marginBottom: 0, marginTop: 14 }}>
          市場より予測が悪いモデルの期待値は、優位性ではなく単なる誤差です。
          検証で市場を上回ったときに初めて公開します。
        </p>
      </div>

      <div className="card">
        <h2>データの取得</h2>
        <p style={{ marginTop: 0, marginBottom: 0 }}>
          公式サイトから2秒間隔で取得しています。出走表は朝に1回、
          直前情報とオッズは締切が近いレースのみ30分ごと、結果は全レース終了後に1回。
          オッズは締切に向けて動くため、表示している値は最後に取得した時点のものです。
        </p>
      </div>
    </main>
  );
}
