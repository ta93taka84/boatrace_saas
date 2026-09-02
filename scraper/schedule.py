import re
"""当日の開催場一覧を取得する。"""
from bs4 import BeautifulSoup
from .session import fetch

# 全24場のコードと名称
VENUES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
    "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
    "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}


def get_active_venues(date_str: str) -> list[dict]:
    """
    開催中の会場コードリストを返す。
    date_str: 'YYYYMMDD'
    戻り値: [{"code": "04", "name": "平和島", "race_count": 12}, ...]
    """
    html = fetch("/owpc/pc/race/index", params={"hd": date_str})
    soup = BeautifulSoup(html, "lxml")

    active = []
    # トップページの開催場リンクから会場コード(jcd)を抽出
    for a in soup.select("a[href*='jcd=']"):
        href = a.get("href", "")
        if "raceindex" not in href and "racelist" not in href:
            continue
        jcd = _extract_param(href, "jcd")
        if jcd and jcd in VENUES and not any(v["code"] == jcd for v in active):
            active.append({"code": jcd, "name": VENUES[jcd]})

    # リンクから取れない場合はレース一覧ページをフォールバック確認
    if not active:
        active = _fallback_from_schedule(date_str)

    return active


def _extract_param(href: str, key: str) -> str | None:
    for part in href.split("?")[-1].split("&"):
        k, _, v = part.partition("=")
        if k == key:
            return v
    return None


def _fallback_from_schedule(date_str: str) -> list[dict]:
    """月間スケジュールページから開催場を探す。"""
    ym = date_str[:6]  # YYYYMM
    html = fetch("/owpc/pc/race/monthlyschedule", params={"ym": ym})
    soup = BeautifulSoup(html, "lxml")

    day = int(date_str[6:8])
    active = []

    for td in soup.select("td.is-arrow1"):
        # 日付セルから対象日を特定しリンク取得
        date_el = td.find_previous("th")
        if date_el and date_el.get_text(strip=True).startswith(str(day)):
            for a in td.select("a[href*='jcd=']"):
                jcd = _extract_param(a["href"], "jcd")
                if jcd and jcd in VENUES:
                    active.append({"code": jcd, "name": VENUES[jcd]})

    return active


def get_close_times(date_str: str, venue_code: str) -> dict[int, str]:
    """
    1場ぶんの締切予定時刻を返す。 {1: "11:29", 2: "12:00", ...}

    「締切直前のレースだけオッズを取りに行く」ためのスケジューラ用。
    全レースのオッズを毎時取り直すとGitHub Actionsの無料枠を使い切るので、
    この時刻を見て対象を絞り込む。
    """
    html = fetch("/owpc/pc/race/raceindex", params={"jcd": venue_code, "hd": date_str})
    soup = BeautifulSoup(html, "lxml")

    table = soup.select_one("table")
    if not table:
        return {}

    times = {}
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        m_race = re.match(r"(\d+)R", tds[0].get_text(strip=True))
        m_time = re.match(r"(\d{1,2}:\d{2})", tds[1].get_text(strip=True))
        if m_race and m_time:
            times[int(m_race.group(1))] = m_time.group(1)

    return times
