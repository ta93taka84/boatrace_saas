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
_last_request_at = 0.0


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

    _wait_turn()
    resp = get_session().get(BASE_URL + path, params=params, timeout=15)
    resp.raise_for_status()

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(resp.content)

    return resp.content


def _wait_turn() -> None:
    """
    前のリクエストを出してから SLEEP_SEC 経つまで待つ。

    **待ちはリクエストの前に置く。** 以前は取得のあとに固定で2秒眠っていたが、
    それだと「応答待ち + 解析 + 2秒」が実際の間隔になり、実測で1件2.4秒
    かかっていた。起点から数えれば、応答と解析にかかった時間はそのまま
    待ち時間に吸収される。**サイトから見た間隔は2秒のままで、こちらだけが
    17%速くなる。**

    失敗時の防御もこの形のほうが強い。以前は finally で眠らせていたが、
    呼び出し側が例外を握って次に進む経路では、待ちが「前の失敗の直後」に
    しか効かなかった。いまは次のリクエストを出す側で必ず待つので、
    例外を誰がどう握っても間隔が縮まらない。サイトが5xxを返している間に
    待ち時間ゼロで連射する事故は、こちらでも起きない。

    プロセスをまたいだ調整はしない。**収集を2本同時に走らせると、
    サイトから見た間隔は半分になる。** 並行して回さないこと。
    """
    global _last_request_at
    wait = SLEEP_SEC - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


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
