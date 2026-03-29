from __future__ import annotations

import asyncio
import functools
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

_client = httpx.AsyncClient(timeout=10.0)

def with_retry(attempts: int, backoff: float) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt == attempts - 1:
                        break
                    delay = backoff ** attempt
                    log.warning(
                        "webhook_retry",
                        attempt=attempt + 1,
                        next_delay=round(delay, 2),
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
            log.error("webhook_failed_permanently", error=str(last_exc))
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


@with_retry(attempts=3, backoff=2.0)
async def send_webhook(url: str, payload: dict[str, Any]) -> None:
    if not is_safe_url(url):
        log.error("ssrf_attempt_blocked", url=url)
        return
    
    response = await _client.post(url, json=payload)
    response.raise_for_status()
    log.info("webhook_sent", url=url, status_code=response.status_code)



def is_safe_url(url: str) -> bool:
    """Простая проверка на SSRF: запрещаем локальные и частные IP."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        
        hostname = parsed.hostname
        if not hostname:
            return False

        ip_address = socket.gethostbyname(hostname)
        
        forbidden_prefixes = ("127.", "10.", "172.16.", "192.168.", "169.254.", "0.0.0.0")
        return not any(ip_address.startswith(prefix) for prefix in forbidden_prefixes)
    except Exception:
        return False
