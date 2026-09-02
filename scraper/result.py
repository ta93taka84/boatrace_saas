"""レース結果（確定着順・払戻金）を取得する。バックテストの正解データ。"""
import re
from bs4 import BeautifulSoup
from .session import fetch


def get_result(date_str: str, venue_code: str, race_no: int) -> dict | None:
    """
    戻り値:
    {
      "race_no": 1,
      "finish": {1: 1, 6: 2, 2: 3, 3: 4},   # 艇番 -> 着順
      "winner_lane": 1,
      "kimarite": "逃げ",
      "payouts": {"3連単": {"combo": "1-6-2", "payout": 9480, "popularity": 29}, ...},
    }
    中止・不成立などで着順が取れない場合は None。
    """
    params = {"rno": race_no, "jcd": venue_code, "hd": date_str}
    html = fetch("/owpc/pc/race/raceresult", params=params)
    soup = BeautifulSoup(html, "lxml")

    finish = _parse_finish(soup)
    if not finish:
        return None

    winner_lane = next((lane for lane, rank in finish.items() if rank == 1), None)

    return {
        "race_no": race_no,
        "finish": finish,
        "winner_lane": winner_lane,
        "kimarite": _parse_kimarite(soup),
        "payouts": _parse_payouts(soup),
    }


def _parse_finish(soup) -> dict[int, int]:
    """着順表（1つ目の table.is-w495）。列は 着順 / 枠 / 選手 / レースタイム。"""
    table = soup.select_one("table.is-w495")
    if not table:
        return {}

    finish = {}
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        rank = _int(tds[0].get_text(strip=True))   # 全角数字。失格は「妨」等で None
        lane = _int(tds[1].get_text(strip=True))
        if rank and lane and 1 <= lane <= 6:
            finish[lane] = rank

    return finish


def _parse_kimarite(soup) -> str | None:
    table = soup.select_one("table.is-w243.is-h108__3rdadd")
    if not table:
        return None
    text = table.get_text(strip=True).replace("決まり手", "").strip()
    return text or None


def _parse_payouts(soup) -> dict:
    """払戻金テーブル（3連単/3連複/2連単/2連複/拡連複/単勝/複勝）。"""
    payouts = {}
    for table in soup.select("table.is-w495"):
        for tr in table.select("tbody tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) < 3:
                continue
            bet_type, combo, amount = cells[0], cells[1], cells[2]
            if not bet_type or "¥" not in amount:
                continue
            payouts[bet_type] = {
                "combo": combo,
                "payout": _int(amount.replace(",", "")),
                "popularity": _int(cells[3]) if len(cells) > 3 else None,
            }
    return payouts


def _int(s: str) -> int | None:
    if not s:
        return None
    # 全角数字を半角に寄せる
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None
