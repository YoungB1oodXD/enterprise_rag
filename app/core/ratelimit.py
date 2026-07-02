"""
简单的内存中速率限制器

基于客户端 IP + 时间窗口实现，无外部依赖。
重启后计数器重置（非持久化），适用于防止暴力破解和滥用。

用法:
    from app.core.ratelimit import check_rate_limit
    from fastapi import Request

    @router.post("/login")
    def login(request: Request, ...):
        check_rate_limit(request, max_requests=10, window_seconds=60)
        ...
"""
import time
from collections import defaultdict
from fastapi import HTTPException, Request


class _RateLimiter:
    def __init__(self):
        self._records: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        records = self._records[key]
        self._records[key] = [t for t in records if t > cutoff]
        if len(self._records[key]) >= max_requests:
            return False
        self._records[key].append(now)
        return True


_limiter = _RateLimiter()


def check_rate_limit(request: Request, max_requests: int = 10, window_seconds: int = 60) -> None:
    """检查请求频率，超过限制则抛出 429 HTTPException"""
    client_ip = request.client.host if request.client else "unknown"
    if not _limiter.check(client_ip, max_requests, window_seconds):
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁，请稍后再试",
        )
