import time
import threading
from typing import Any, Optional


class LRUCache:
    """LRU cache with TTL support. Thread-safe."""

    def __init__(self, capacity: int = 1000, ttl: int = 3600):
        self.capacity = capacity
        self.ttl = ttl
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._cache[key]
                return None
            # Move to end (most recently used)
            del self._cache[key]
            self._cache[key] = (value, expires_at)
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            if len(self._cache) >= self.capacity:
                # Evict least recently used (first inserted key)
                self._cache.pop(next(iter(self._cache)))
            expires_at = time.monotonic() + (ttl if ttl is not None else self.ttl)
            self._cache[key] = (value, expires_at)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
