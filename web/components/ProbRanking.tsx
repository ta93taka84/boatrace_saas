import Link from "next/link";
import type { Race, TrifectaPick, Venue } from "@/lib/types";

/**
 * その日の全レースを横断した「確率の高い買い目」の並び。
 *
 * **レース詳細の推奨買い目（PickTable）とは別物である。** あちらはEV順、
 * こちらは確率順で、選ばれる目が違う。確率順に並べると当たりやすい代わりに
 * オッズの低い目（多くは1号艇頭）が上に来るので、期待値は1.00を下回るのが
 * 普通になる。**「確率が高い＝得」と読まれないよう、期待値の列を必ず並べる。**
 *
 * 券種ごとに1つのカードを出す。三連単と三連複を同じ表に混ぜない。
 * 的の数が120通りと20通りで違うため、確率の数字を同じ列に並べると
 * 三連複が一方的に上へ来る。それは当たりやすさの差であって、
 * 有利さの差ではない。
 */

export type RankedPick = {
  venueCode: string;
  venueName: string;
  race: Race;
  pick: TrifectaPick;
};

/**
 * 候補レースから確率順の上位を取る。
 *
 * 1レースあたりの候補は収集時に PROB_PICKS 点へ絞ってあるので、
 * ここで並べ替えているのは「各レースの上位数点」の集合である。
 * 全120通りを横断して並べているわけではないが、確率の高い目しか
 * 上位には来ないので、上位10点の顔ぶれは変わらない。
 */
export function rankByProb(
  entries: { venue: Venue; race: Race }[],
  key: "prob_picks" | "trio_prob_picks",
  limit = 10
): RankedPick[] {
  const rows: RankedPick[] = [];
  for (const { venue, race } of entries) {
    for (const pick of race[key] ?? []) {
      rows.push({
        venueCode: venue.code,
        venueName: venue.name,
        race,
        pick,
      });
    }
  }
  rows.sort((a, b) => b.pick.prob - a.pick.prob);
  return rows.slice(0, limit);
}

export function ProbRanking({
  date,
  title,
  note,
  rows,
  empty,
}: {
  date: string;
  title: string;
  note: string;
  rows: RankedPick[];
  empty: string;
}) {
  return (
    <div className="card">
      <h3>{title}</h3>
      <p className="sub" style={{ marginTop: 0 }}>
        {note}
      </p>
      {rows.length === 0 ? (
        <p className="muted" style={{ fontSize: 13, marginBottom: 0 }}>
          {empty}
        </p>
      ) : (
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>締切</th>
                {/* 余った横幅はレース名に吸わせる。数値の列を広げない。 */}
                <th className="l" style={{ width: "100%" }}>
                  レース
                </th>
                <th>買い目</th>
                <th>確率</th>
                <th>オッズ</th>
                <th>期待値</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ venueCode, venueName, race, pick }) => (
                <tr key={`${venueCode}-${race.race_no}-${pick.combo}`}>
                  <td className="num">{race.closes_at ?? "—"}</td>
                  <td className="l">
                    <Link href={`/race/${date}/${venueCode}/${race.race_no}`}>
                      {venueName} {race.race_no}R
                    </Link>
                  </td>
                  <td className="num">{pick.combo}</td>
                  {/*
                    並べ替えの鍵だが太字にしない。太字（.best）は
                    「列の中で最も良い値」の印で、確率の高さは良さではない。
                  */}
                  <td className="num">{(pick.prob * 100).toFixed(1)}%</td>
                  <td className="num">{pick.odds.toFixed(1)}</td>
                  <td className={pick.ev >= 1 ? "num best" : "num"}>
                    {pick.ev.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
