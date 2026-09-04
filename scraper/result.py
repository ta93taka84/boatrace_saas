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
      "start": [{"course": 1, "lane": 1, "st": 0.17, "flying": False}, ...],
      "payouts": {"3連単": {"combo": "1-6-2", "payout": 9480, "popularity": 29}, ...},
    }
    中止・不成立などで着順が取れない場合は None。
    """
    params = {"rno": race_no, "jcd": venue_code, "hd": date_str}
    return parse_result(fetch("/owpc/pc/race/raceresult", params=params), race_no)


def result_params(date_str: str, venue_code: str, race_no: int) -> dict:
    """このページのキャッシュを引くためのパラメータ。session.cached に渡す。"""
    return {"rno": race_no, "jcd": venue_code, "hd": date_str}


def parse_result(html: bytes, race_no: int) -> dict | None:
    """取得済みのHTMLから結果を組み立てる。取得と分けてあるのは、
    収集済みの行にキャッシュから項目を足すときサイトを叩かないため。"""
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
        "start": _parse_start(soup),
        "payouts": _parse_payouts(soup),
    }


def _parse_start(soup) -> list[dict]:
    """
    スタート情報（展開図）。進入コース順に艇番とSTが並ぶ。

    戻り値: [{"course": 1, "lane": 1, "st": 0.17, "flying": False}, ...]

    **枠番と進入コースは別物。** 前づけがあると一致せず、キャッシュ済みの
    2,515レースで15.7%がそうだった。ここを取らないと「枠1＝1コース」という
    誤った前提でしか扱えない。scoring.estimate_win_prob の actual_course は
    この値のために用意されている。

    表示の上から順に1コース、2コース…なので、順番そのものが進入コースになる。
    欠場があるとその艇は並ばず、残った艇が上から詰めてコースを取る。

    STは大時計が0になってから何秒後か。フライングは0より前なので負で返す。
    'F.03' は0.03秒早いという意味なので -0.03。符号を落として 0.03 にすると、
    最も良いSTと最も悪いSTが同じ値になる。
    """
    start = []
    for course, div in enumerate(soup.select(".table1_boatImage1"), 1):
        # 1着の枠だけ決まり手が同じ要素に入る（'1 .17 逃げ'）ので先頭だけ見る
        m = re.match(r"^(\d)\s+(F?)\.(\d+)", div.get_text(" ", strip=True))
        if not m:
            continue
        lane = int(m.group(1))
        if not 1 <= lane <= 6:
            continue
        flying = m.group(2) == "F"
        st = float("0." + m.group(3))
        start.append({
            "course": course,
            "lane": lane,
            "st": round(-st if flying else st, 2),
            "flying": flying,
        })
    return start


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
