from __future__ import annotations

import asyncio
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client = httpx.AsyncClient(timeout=10.0)


async def send_webhook(url: str, payload: dict[str, Any]) -> None:
    """Отправляет webhook с экспоненциальным backoff из настроек."""
    if not is_safe_url(url):
        log.error("ssrf_attempt_blocked", url=url)
        return

    attempts = settings.webhook_retry_attempts
    backoff = settings.webhook_retry_backoff
    last_exc: Exception | None = None

    for attempt in range(attempts):
        try:
            response = await _client.post(url, json=payload)
            response.raise_for_status()
            log.info("webhook_sent", url=url, status_code=response.status_code)
            return
        except Exception as exc:
            last_exc = exc
            if attempt == attempts - 1:
                break
            delay = backoff ** attempt  # 1s, 2s, 4s при backoff=2.0
            log.warning(
                "webhook_retry",
                attempt=attempt + 1,
                next_delay=round(delay, 2),
                error=str(exc),
            )
            await asyncio.sleep(delay)

    log.error("webhook_failed_permanently", url=url, error=str(last_exc))
    raise last_exc  # type: ignore[misc]


def is_safe_url(url: str) -> bool:
    """Проверка на SSRF: запрещаем локальные и частные IP-адреса."""
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
    