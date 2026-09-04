"""直前情報（展示タイム・気象）を取得する。締切の30〜40分前から値が入る。"""
import re
from bs4 import BeautifulSoup
from .session import fetch


def get_beforeinfo(date_str: str, venue_code: str, race_no: int) -> dict | None:
    """
    直前情報を返す。展示前は各値が None のまま返る。
    戻り値:
    {
      "race_no": 1,
      "weather": "曇り", "temperature": 27.0, "water_temp": 27.0,
      "wind_speed": 0, "wind_dir_code": 17, "wave_height": 2,
      "racers": [
        {"lane": 1, "exhibit_time": 6.72, "tilt": -0.5, "weight": 55.1}, ...
      ]
    }
    """
    params = {"rno": race_no, "jcd": venue_code, "hd": date_str}
    html = fetch("/owpc/pc/race/beforeinfo", params=params)
    soup = BeautifulSoup(html, "lxml")

    racers = _parse_racers(soup)
    if not racers:
        return None

    return {
        "race_no": race_no,
        **_parse_weather(soup),
        "racers": racers,
        "start_exhibition": _parse_start_exhibition(soup),
    }


def _parse_start_exhibition(soup) -> list[dict]:
    """
    スタート展示。進入コース順に艇番と展示STが並ぶ。

    戻り値: [{"course": 1, "lane": 1, "st": 0.02, "early": False}, ...]
    展示前はまだ出ていないので空リストになる。

    **これは締切前に分かる。** 本番の進入コースはレースが終わるまで
    分からないが、展示の進入はここで読める。scoring の actual_course に
    渡せる唯一の事前情報がこれになる。

    **本番のスタート（result.get_result の "start"）とは別物。** 混同しないこと。
    同じ .table1_boatImage1 というクラスで描かれているが、キャッシュ実測で
    前づけ率は本番18.1%に対して展示13.1%、早出しは本番24件に対して
    展示1,318件と、桁が違う。展示では早く出ても罰則が無いので、
    F は失格ではなく「大時計より早く出た」という情報でしかない。
    そのため flying ではなく early という名前にしている。

    STは大時計が0になってから何秒後か。早出しは0より前なので負で返す。
    """
    exhibition = []
    for course, div in enumerate(soup.select(".table1_boatImage1"), 1):
        m = re.match(r"^(\d)\s+(F?)\.(\d+)", div.get_text(" ", strip=True))
        if not m:
            continue
        lane = int(m.group(1))
        if not 1 <= lane <= 6:
            continue
        early = m.group(2) == "F"
        st = float("0." + m.group(3))
        exhibition.append({
            "course": course,
            "lane": lane,
            "st": round(-st if early else st, 2),
            "early": early,
        })
    return exhibition


def _parse_racers(soup) -> list[dict]:
    """
    展示テーブルの列順は thead 準拠:
      枠 / 写真 / ボートレーサー / 体重 / 展示タイム / チルト / プロペラ / 部品交換 / 前走成績
    1選手 = 1 tbody（4行）。展示前は空文字なので None を入れる。
    """
    table = soup.select_one("table.is-w748")
    if not table:
        return []

    racers = []
    for tbody in table.select("tbody"):
        tds = tbody.find_all("td")
        if len(tds) < 6:
            continue
        lane = _int(tds[0].get_text(strip=True))
        if not 1 <= lane <= 6:
            continue
        racers.append({
            "lane": lane,
            "weight": _float(tds[3].get_text(strip=True)),
            "exhibit_time": _float(tds[4].get_text(strip=True)),
            "tilt": _float(tds[5].get_text(strip=True), signed=True),
        })

    return racers


def _parse_weather(soup) -> dict:
    """
    div.weather1_bodyUnit の修飾クラスで項目を判別する。
    風向は表示テキストを持たず is-windNN のクラス番号で表される（17は無風）。
    """
    result = {
        "weather": None, "temperature": None, "water_temp": None,
        "wind_speed": None, "wind_dir_code": None, "wave_height": None,
    }

    for unit in soup.select("div.weather1_bodyUnit"):
        classes = unit.get("class") or []
        text = unit.get_text(" ", strip=True)

        if "is-weather" in classes:
            result["weather"] = text or None
        elif "is-direction" in classes:
            result["temperature"] = _float(text)
        elif "is-waterTemperature" in classes:
            result["water_temp"] = _float(text)
        elif "is-wind" in classes:
            result["wind_speed"] = _float(text)
        elif "is-wave" in classes:
            result["wave_height"] = _float(text)
        elif "is-windDirection" in classes:
            img = unit.select_one("[class*='is-wind']")
            if img:
                m = re.search(r"is-wind(\d+)", " ".join(img.get("class") or []))
                if m:
                    result["wind_dir_code"] = int(m.group(1))

    return result


def _int(s: str) -> int | None:
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else None


def _float(s: str, signed: bool = False) -> float | None:
    pattern = r"-?\d+(?:\.\d+)?" if signed else r"\d+(?:\.\d+)?"
    m = re.search(pattern, s or "")
    return float(m.group()) if m else None
