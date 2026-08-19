"""Caching layer (SRS 38).

An in-process TTL cache behind a narrow interface. Redis drops in by implementing the
same three methods and pointing RRG_REDIS_URL at a server -- no call sites change.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Protocol


class CacheBackend(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...
    def clear(self, prefix: str | None = None) -> int: ...


class TTLCache:
    """Thread-safe LRU cache with per-entry expiry.

    Chosen over Redis for the MVP because it removes an infrastructure dependency
    entirely. The trade-off is real and worth stating: it is per-process, so it buys
    nothing once the API runs multiple workers. That is the point at which Redis
    should replace it.
    """

    def __init__(self, max_entries: int = 512, default_ttl: int = 900) -> None:
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                del self._store[key]
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        with self._lock:
            expires_at = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
            self._store[key] = (expires_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self, prefix: str | None = None) -> int:
        """Drop everything, or just the keys under `prefix`. Returns entries removed."""
        with self._lock:
            if prefix is None:
                removed = len(self._store)
                self._store.clear()
                return removed
            doomed = [k for k in self._store if k.startswith(prefix)]
            for key in doomed:
                del self._store[key]
            return len(doomed)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._store),
                "max_entries": self._max_entries,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else None,
            }


_cache: TTLCache | None = None


def get_cache() -> TTLCache:
    global _cache
    if _cache is None:
        from ..config import get_settings

        settings = get_settings()
        _cache = TTLCache(
            max_entries=settings.cache_max_entries,
            default_ttl=settings.cache_ttl_seconds,
        )
    return _cache


def cache_key(*parts: Any) -> str:
    """Deterministic key. Every input that changes the result must appear here."""
    return "|".join("" if p is None else str(p) for p in parts)
