from __future__ import annotations

from typing import Any


class OzonAPIError(Exception):
    """Ошибка ответа Seller API."""

    def __init__(self, status_code: int, message: str, *, code: int | None = None,
                 details: Any = None, path: str = "") -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.path = path
        super().__init__(f"{path}: HTTP {status_code}" + (f", code {code}" if code is not None else "") + f": {message}")


class AuthError(OzonAPIError):
    """401/403 — неверные Client-Id/Api-Key или у ключа нет прав на метод."""


class NotFoundError(OzonAPIError):
    """404 — метода нет (часто: устаревшая версия)."""


class RateLimitError(OzonAPIError):
    """429 — лимит запросов не отпустил за все попытки."""


class ObsoleteMethodError(OzonAPIError):
    """Ozon отключил эту версию метода («obsolete method cannot be used»)."""
