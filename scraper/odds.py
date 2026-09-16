"""三連単・三連複オッズを取得し、市場の勝率期待値（インプライド確率）を算出する。"""
from bs4 import BeautifulSoup
from .session import fetch


def get_odds(date_str: str, venue_code: str, race_no: int) -> dict | None:
    """
    三連単オッズと、そこから逆算した各艇の市場勝率を返す。
    戻り値:
    {
      "race_no": 1,
      "odds": {"1-2-3": 9.6, ...},        # 三連単120通り
      "market_prob": {1: 0.358, ...},      # 控除率補正後の市場勝率（合計1.0）
      "overround": 1.335,                  # インプライド確率の総和（≒1/0.75）
    }
    """
    params = {"rno": race_no, "jcd": venue_code, "hd": date_str}
    html = fetch("/owpc/pc/race/odds3t", params=params)
    soup = BeautifulSoup(html, "lxml")

    odds_map = _parse_trifecta_odds(soup)
    if not odds_map:
        return None

    market_prob, overround = _market_win_prob(odds_map)

    return {
        "race_no": race_no,
        "odds": odds_map,
        "market_prob": market_prob,
        "overround": round(overround, 4),
    }


def get_trio_odds(date_str: str, venue_code: str, race_no: int) -> dict[str, float] | None:
    """
    三連複20通りのオッズを返す。取れなければ None。

        {"1-2-3": 4.3, "1-2-4": 2.9, ...}   艇番は昇順

    **三連単から計算で出していない。** 三連複は別勘定の投票で、払戻も別に
    決まる。三連単オッズの逆数を6通り足せば「市場が着順を問わずその3艇と
    見ている確率」は出るが、それは三連複の配当ではない。推奨買い目に添える
    オッズは実際に払い戻される数字でなければ意味がないので、専用ページを引く。

    そのぶん1レースあたり1リクエスト増える。`session.SLEEP_SEC` の2秒間隔は
    守られるので、増えるのは巡回1周にかかる時間である。`prerace-loop` は
    締切の早い順に取るため、この増加は締切間際のレースの取りこぼしに
    直結する。間隔と窓の余裕を削ってまで本数を増やさないこと。
    """
    params = {"rno": race_no, "jcd": venue_code, "hd": date_str}
    html = fetch("/owpc/pc/race/odds3f", params=params)
    soup = BeautifulSoup(html, "lxml")
    return _parse_combo_odds(soup) or None


def _parse_trifecta_odds(soup) -> dict[str, float]:
    """
    三連単オッズ表をパースする。

    表は「1着艇ごとの6列グループ × 20行」構成。2着セルは rowspan=4 で
    4行に1度しか現れないため、グループ内で直前の2着を持ち越す必要がある。
    各グループは td.oddsPoint で終わるので、それを区切りにチャンク分割する。
    """
    return _parse_combo_odds(soup)


def _parse_combo_odds(soup) -> dict[str, float]:
    """
    三連単と三連複の両方のオッズ表をパースする。

    **2つのページは同じ組版である。** どちらも「先頭の艇ごとの6列グループ」で、
    グループ内は rowspan で2番目の艇をまとめ、各行が td.oddsPoint で終わる。
    違うのは行数（三連単は120通り、三連複は20通り）と、三連複では組み合わせが
    常に昇順に並ぶことだけ。パーサーを分けると、公式サイトの組版が変わった
    ときに片方だけ直して気づかない形になるので、一本にしてある。
    """
    table = next((t for t in soup.select("table") if t.select_one("td.oddsPoint")), None)
    if table is None:
        return {}

    odds_map: dict[str, float] = {}
    carried_second: dict[int, str] = {}

    for row in table.select("tr"):
        chunks, cur = [], []
        for td in row.find_all("td"):
            cur.append(td)
            if "oddsPoint" in (td.get("class") or []):
                chunks.append(cur)
                cur = []

        for group_idx, chunk in enumerate(chunks):
            first = group_idx + 1
            if len(chunk) == 3:
                second = chunk[0].get_text(strip=True)
                third = chunk[1].get_text(strip=True)
                carried_second[group_idx] = second
            elif len(chunk) == 2:
                second = carried_second.get(group_idx)
                third = chunk[0].get_text(strip=True)
            else:
                continue

            if not second or not third:
                continue
            try:
                odd = float(chunk[-1].get_text(strip=True))
            except ValueError:
                continue  # 締切前・欠場は "---" 等
            if odd > 0:
                odds_map[f"{first}-{second}-{third}"] = odd

    return odds_map


def _market_win_prob(odds_map: dict[str, float]) -> tuple[dict[int, float], float]:
    """
    三連単オッズから各艇の1着確率を逆算する。
    ある艇が1着の組み合わせ20通りのインプライド確率(1/オッズ)を合計し、
    全体で正規化することで控除率を除去する。
    """
    lane_implied: dict[int, float] = {i: 0.0 for i in range(1, 7)}

    for combo, odd in odds_map.items():
        try:
            first = int(combo.split("-")[0])
        except ValueError:
            continue
        if first in lane_implied:
            lane_implied[first] += 1.0 / odd

    overround = sum(lane_implied.values())
    if overround <= 0:
        return {}, 0.0

    market_prob = {lane: round(p / overround, 4) for lane, p in lane_implied.items()}
    return market_prob, overround
