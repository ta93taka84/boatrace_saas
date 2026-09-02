"""出走表（レースカード）を取得・パースする。"""
import re
from bs4 import BeautifulSoup
from .session import fetch


def get_racelist(date_str: str, venue_code: str, race_no: int) -> dict | None:
    """
    1レース分の出走表を返す。
    戻り値:
    {
      "race_no": 1,
      "racers": [
        {
          "lane": 1, "racer_id": "3454", "name": "井川 大作",
          "class": "B1", "branch": "岡山", "age": 55, "weight": 55.1,
          "f_count": 0, "l_count": 0, "avg_st": 0.17,
          "win_rate_all": 5.35, "in2_rate_all": 37.36, "in3_rate_all": 54.95,
          "win_rate_venue": 0.0, "in2_rate_venue": 0.0, "in3_rate_venue": 0.0,
          "motor_no": 71, "motor_in2_rate": 38.30, "motor_in3_rate": 57.45,
          "boat_no": 56, "boat_in2_rate": 38.89, "boat_in3_rate": 51.11,
        }, ...
      ]
    }
    """
    params = {"rno": race_no, "jcd": venue_code, "hd": date_str}
    html = fetch("/owpc/pc/race/racelist", params=params)
    soup = BeautifulSoup(html, "lxml")

    racers = []
    for tbody in soup.select("tbody.is-fs12"):
        racer = _parse_racer_row(tbody)
        if racer:
            racers.append(racer)

    if not racers:
        return None

    return {"race_no": race_no, "racers": racers}


def _parse_racer_row(tbody) -> dict | None:
    """
    1選手 = 1 tbody（4行にまたがる）。主要セルは rowspan=4 で以下の並び。
      td0 艇番 / td2 選手情報 / td3 F・L・平均ST
      td4 全国成績 / td5 当地成績 / td6 モーター / td7 ボート
    td3以降は1セルに3値が <br> 区切りで入る。
    """
    tds = tbody.find_all("td")
    if len(tds) < 8:
        return None

    lane = _int(tds[0].get_text(strip=True))
    if not 1 <= lane <= 6:
        return None

    profile = _parse_profile(tds[2])
    fl = _cells(tds[3])
    national = _cells(tds[4])
    venue = _cells(tds[5])
    motor = _cells(tds[6])
    boat = _cells(tds[7])

    return {
        "lane": lane,
        **profile,
        "f_count": _int(fl[0]) if len(fl) > 0 else 0,
        "l_count": _int(fl[1]) if len(fl) > 1 else 0,
        "avg_st": _float(fl[2]) if len(fl) > 2 else 0.0,
        "win_rate_all": _float(national[0]) if len(national) > 0 else 0.0,
        "in2_rate_all": _float(national[1]) if len(national) > 1 else 0.0,
        "in3_rate_all": _float(national[2]) if len(national) > 2 else 0.0,
        "win_rate_venue": _float(venue[0]) if len(venue) > 0 else 0.0,
        "in2_rate_venue": _float(venue[1]) if len(venue) > 1 else 0.0,
        "in3_rate_venue": _float(venue[2]) if len(venue) > 2 else 0.0,
        "motor_no": _int(motor[0]) if len(motor) > 0 else 0,
        "motor_in2_rate": _float(motor[1]) if len(motor) > 1 else 0.0,
        "motor_in3_rate": _float(motor[2]) if len(motor) > 2 else 0.0,
        "boat_no": _int(boat[0]) if len(boat) > 0 else 0,
        "boat_in2_rate": _float(boat[1]) if len(boat) > 1 else 0.0,
        "boat_in3_rate": _float(boat[2]) if len(boat) > 2 else 0.0,
    }


def _parse_profile(td) -> dict:
    """'3454 /|B1|井川　　大作|岡山/岡山|55歳/55.1kg' を分解する。"""
    parts = _cells(td)
    out = {"racer_id": "", "class": "", "name": "", "branch": "", "age": 0, "weight": 0.0}

    if len(parts) > 0:
        m = re.search(r"\d+", parts[0])
        if m:
            out["racer_id"] = m.group()
    if len(parts) > 1:
        out["class"] = parts[1]
    if len(parts) > 2:
        out["name"] = re.sub(r"[\s　]+", " ", parts[2]).strip()
    if len(parts) > 3:
        out["branch"] = parts[3].split("/")[0]
    if len(parts) > 4:
        age_weight = parts[4].split("/")
        out["age"] = _int(age_weight[0])
        if len(age_weight) > 1:
            out["weight"] = _float(age_weight[1])

    return out


def _cells(td) -> list[str]:
    """<br> 区切りのセルを文字列リストに分解する。"""
    return [p.strip() for p in td.get_text("|", strip=True).split("|") if p.strip()]


def _int(s: str) -> int:
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 0


def _float(s: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else 0.0
