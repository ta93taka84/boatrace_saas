import hashlib
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://www.boatrace.jp"
SLEEP_SEC = 2.0  # サーバー負荷配慮
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

_session = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def fetch(path: str, params: dict = None) -> bytes:
    """
    ページを取得する。過去日(hd < 今日)のページは内容が確定しているので
    cache/ にキャッシュし、バックテストの再実行でサイトを叩き直さない。
    """
    cache_path = _cache_path(path, params)
    if cache_path and cache_path.exists():
        return cache_path.read_bytes()

    # 間隔は finally で置く。raise_for_status やタイムアウトの後ろに書くと、
    # 呼び出し側が例外を握って次に進む経路（backtest.collect の
    # except Exception など）で待ち時間がまるごと消える。サイトが5xxを
    # 返している間は全リクエストが失敗するので、相手が弱っているときに
    # 待ち時間ゼロで連射することになる。一番叩いてはいけない状況で
    # 一番強く叩く形なので、成功しても失敗しても必ず待つ。
    try:
        resp = get_session().get(BASE_URL + path, params=params, timeout=15)
        resp.raise_for_status()
    finally:
        time.sleep(SLEEP_SEC)

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(resp.content)

    return resp.content


def cached(path: str, params: dict = None) -> bytes | None:
    """
    キャッシュにあればそれを返し、無ければ None。**サイトは叩かない。**

    収集済みの行に後から項目を足すときに使う。fetch を使うと、キャッシュが
    無い行のぶんだけ黙ってサイトへ出て行く。すでに取ったページから
    読み直すだけの処理は、取りに行く可能性そのものを持たないほうがよい。
    """
    p = _cache_path(path, params)
    return p.read_bytes() if p and p.exists() else None


def _cache_path(path: str, params: dict | None) -> Path | None:
    """過去日のリクエストにだけキャッシュパスを割り当てる。"""
    if not params:
        return None
    hd = str(params.get("hd", ""))
    if len(hd) != 8 or not hd.isdigit():
        return None
    if hd >= datetime.now().strftime("%Y%m%d"):
        return None  # 当日・未来はオッズが動くのでキャッシュしない

    key = f"{path}?{sorted(params.items())}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return CACHE_DIR / hd / f"{digest}.html"
