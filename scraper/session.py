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

    resp = get_session().get(BASE_URL + path, params=params, timeout=15)
    resp.raise_for_status()
    time.sleep(SLEEP_SEC)

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(resp.content)

    return resp.content


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
