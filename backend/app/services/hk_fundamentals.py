"""Independent, bounded statement cache so financial feeds cannot block chart loading."""

import hashlib
import threading
import time
from copy import deepcopy

from app import secrets_store
from app.data_providers.research_hk_fundamentals import fetch_financials

_CACHE = {}
_LOCK = threading.Lock()


def snapshot(symbol, force=False):
    identity = hashlib.sha256(
        (
            (secrets_store.get_tickflow_key() or "")
            + "\0"
            + (secrets_store.load().get("tickflow_base_url") or "")
        ).encode()
    ).hexdigest()
    key = symbol, identity
    with _LOCK:
        saved = _CACHE.get(key)
    if saved and not force and time.monotonic() - saved[0] < 1800:
        return deepcopy(saved[1])
    result = fetch_financials(symbol)
    if saved and sum(bool(t["reports"]) for t in result["tables"].values()) < sum(
        bool(t["reports"]) for t in saved[1]["tables"].values()
    ):
        previous = deepcopy(saved[1])
        previous["status"] = "stale"
        previous["last_attempts"] = result["attempts"]
        previous["warnings"].append("本次刷新失败，保留上次成功财报；抓取时间仍为原时间。")
        return previous
    with _LOCK:
        if len(_CACHE) >= 32:
            _CACHE.clear()
        _CACHE[key] = time.monotonic(), deepcopy(result)
    return result
