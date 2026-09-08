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
    return parse_beforeinfo(fetch("/owpc/pc/race/beforeinfo", params=params), race_no)


def beforeinfo_params(date_str: str, venue_code: str, race_no: int) -> dict:
    """このページのキャッシュを引くためのパラメータ。session.cached に渡す。"""
    return {"rno": race_no, "jcd": venue_code, "hd": date_str}


def parse_beforeinfo(html: bytes, race_no: int) -> dict | None:
    """取得済みのHTMLから直前情報を組み立てる。取得と分けてあるのは、
    収集済みの行にキャッシュから項目を足すときサイトを叩かないため。"""
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


# 直前情報から出走表側の各艇へ移す項目。
# **検証で採用した特徴量をここに足し忘れると、バックテストでは効くのに
# 本番では欠測、という形の事故になる。** 取り込む側（jobs.py と pipeline.py）が
# 別々に列を並べていたので、1か所にまとめてある。
MERGE_KEYS = ("exhibit_time", "tilt", "propeller_new", "parts",
              "prev_race_no", "prev_course", "prev_st", "prev_rank", "prev_foul")


def merge_into_racers(racers: list[dict], before: dict) -> None:
    """
    直前情報を出走表側の各艇へ書き込む。破壊的に更新する。

    スタート展示は艇ごとではなく進入順の並びで返るので、艇番で引き直して
    ex_course（展示の進入コース）と ex_st（展示のST）にする。**枠番と進入は
    別物で、実測では結果ページの18.1%が一致しない。** 前づけがあった
    レースかどうかは、この2つを並べて初めて分かる。
    """
    by_lane = {r["lane"]: r for r in before.get("racers") or []}
    exhibition = {e["lane"]: e for e in before.get("start_exhibition") or []}
    for racer in racers:
        source = by_lane.get(racer["lane"])
        if source:
            for key in MERGE_KEYS:
                if source.get(key) is not None:
                    racer[key] = source[key]
        shown = exhibition.get(racer["lane"])
        if shown:
            racer["ex_course"] = shown.get("course")
            racer["ex_st"] = shown.get("st")


def _parse_racers(soup) -> list[dict]:
    """
    展示テーブルの列順は thead 準拠:
      枠 / 写真 / ボートレーサー / 体重 / 展示タイム / チルト / プロペラ / 部品交換 / 前走成績
    1選手 = 1 tbody（4行）。展示前は空文字なので None を入れる。

    プロペラ・部品交換・前走成績は長らく読み捨てていた。**このページは既に
    取得してキャッシュしてあるので、読むのに追加のリクエストは要らない。**
    他の特徴量は期別の集計値か当日の状態しかなく、「節の途中で機力が変わった」
    ことを映すものが1つも無かった。部品交換はそれを直接示す。

    列が増減したら静かにずれる。tbody あたりのセル数が17に満たない場合は
    新しい項目を落とし、展示タイムまでの解釈は変えない。
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
        racer = {
            "lane": lane,
            "weight": _float(tds[3].get_text(strip=True)),
            "exhibit_time": _float(tds[4].get_text(strip=True)),
            "tilt": _float(tds[5].get_text(strip=True), signed=True),
        }
        if len(tds) >= 17:
            racer.update(_parse_machine(tds))
        racers.append(racer)

    return racers


def _parse_machine(tds) -> dict:
    """
    プロペラ・部品交換・前走成績。列の位置は _parse_racers の docstring を参照。

    前走成績は「今節の前の走り」で、進入コース・ST・着順が入る。節の初日は
    どの艇も空になる。
    """
    parts = [li.get_text(strip=True) for li in tds[7].select("li")]

    # **着順の欄はSTの欄より先に読む。** フライングした走りは着順が「Ｆ」に
    # なるが、STの欄には '.01' のように正の値がそのまま入る。着順を見ずに
    # STだけ読むと、失格した走りが「最良のST」として特徴量に入る。
    # 同じ取り違えを experiment.py の直近STで一度やっている。
    rank_text = _ascii(tds[16].get_text(strip=True)).upper()
    rank = _int(rank_text) if rank_text.isdigit() else None
    foul = rank_text if rank_text and not rank_text.isdigit() else None

    return {
        "propeller_new": "新" in tds[6].get_text(strip=True),
        "parts": [p for p in parts if p],
        "prev_race_no": _int(_ascii(tds[9].get_text(strip=True))),
        "prev_course": _int(_ascii(tds[11].get_text(strip=True))),
        "prev_st": _prev_st(tds[14].get_text(strip=True), flying=(foul == "F")),
        "prev_rank": rank,
        # 着順が数字でないときの記号。F=フライング、L=出遅れ、失=失格など。
        "prev_foul": foul,
    }


_TO_ASCII = str.maketrans("０１２３４５６７８９ＦＬ", "0123456789FL")


def _ascii(text: str) -> str:
    """着順や進入は全角で入ることがある（'６' 'Ｆ'）。半角に寄せてから読む。"""
    return text.translate(_TO_ASCII)


def _prev_st(text: str, flying: bool = False) -> float | None:
    """
    前走のST。'.17' のように整数部を省いた形で入る。

    フライングは 'F.02' で、結果ページと同じく負の値で表す。ここを
    正の小さい値として読むと、失格した走りが「最良のST」に化ける。
    """
    text = _ascii(text).strip()
    if not text:
        return None
    flying = flying or text.upper().startswith("F")
    body = text.lstrip("FfLl").strip()
    # 整数部が無い表記なので、先に0を補う。補わないと _float の正規表現が
    # 小数点を跨げず、'.16' を 16.0 として読む。
    if body.startswith("."):
        body = "0" + body
    value = _float(body)
    if value is None:
        return None
    return round(-value if flying else value, 2)


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
            # 気温と水温は符号付きで読む。既定の正規表現はマイナスを拾わないので、
            # 氷点下の日に -1.0℃ が +1.0 になる。冬季の桐生・戸田・びわこで
            # 実際に起きうる。例外も出ず値域の検査も無いので静かに通る。
            # 表示は「気温 28.0℃」の形で他にハイフンが無いため、符号付きにしても
            # 別の数字を拾う心配はない。
            result["temperature"] = _float(text, signed=True)
        elif "is-waterTemperature" in classes:
            result["water_temp"] = _float(text, signed=True)
        elif "is-wind" in classes:
            # 風速と波高は定義上負にならないので符号なしのまま
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
