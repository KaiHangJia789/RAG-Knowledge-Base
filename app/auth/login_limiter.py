"""
登录失败限流（进程内，按客户端 IP）。

单实例部署足够；多实例需改用 Redis。
成功登录会清空该 IP 的失败记录。
"""
import threading
import time

from app.config import settings


class LoginLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        window_start = now - settings.AUTH_LOGIN_WINDOW_SECONDS
        recent = [t for t in self._failures.get(key, []) if t > window_start]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def is_blocked(self, key: str, *, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            return len(self._recent(key, now)) >= settings.AUTH_LOGIN_MAX_FAILURES

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            self._recent(key, now)
            self._failures.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_limiter = LoginLimiter()
