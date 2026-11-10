"""
滑动窗口限流（进程内，按任意 key 计数）。单实例部署足够；多实例需改用 Redis。
"""
import threading
import time


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, limit: int, window_seconds: int, *, now: float | None = None) -> bool:
        """记录一次请求并返回是否放行；窗口内已达 limit 次则拒绝且不计入"""
        current = now if now is not None else time.time()
        start = current - window_seconds
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > start]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(current)
            self._hits[key] = hits
            return True


account_rate_limiter = SlidingWindowLimiter()
