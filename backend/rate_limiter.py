from slowapi import Limiter
from slowapi.util import get_remote_address

_limiter: Limiter | None = None


def get_limiter() -> Limiter:
    global _limiter
    if _limiter is None:
        _limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    return _limiter
