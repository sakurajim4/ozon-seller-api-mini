"""Минимальный синхронный клиент Ozon Seller API на httpx."""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import datetime, timezone
from typing import Any, TypeVar

import httpx

from . import __version__
from .errors import AuthError, NotFoundError, ObsoleteMethodError, OzonAPIError, RateLimitError
from .models import (
    FbsWarehouseStock,
    Json,
    OzonWarehouseStock,
    Posting,
    ProductInfo,
    ProductListItem,
    ProductStocks,
)

BASE_URL = "https://api-seller.ozon.ru"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
T = TypeVar("T")


def _chunks(items: Sequence[T], size: int) -> Iterator[list[T]]:
    for i in range(0, len(items), size):
        yield list(items[i:i + size])


def format_time(value: datetime | str) -> str:
    """datetime → RFC 3339 в UTC (наивное время считается UTC)."""
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class OzonClient:
    """Клиент Seller API.

    Повторяет запрос при 429 и 5xx, а также при сетевых ошибках: ждёт
    ``Retry-After`` из ответа, если он есть, иначе экспоненциально
    (``backoff × 2^попытка``, не дольше ``max_backoff``) с небольшим разбросом.
    """

    def __init__(
        self,
        client_id: str | int,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 5,
        backoff: float = 1.0,
        max_backoff: float = 60.0,
        jitter: float = 0.1,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not client_id or not api_key:
            raise ValueError("нужны client_id и api_key")
        self.max_retries = max_retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.jitter = jitter
        self._sleep = sleep
        headers = {
            "Client-Id": str(client_id),
            "Api-Key": api_key,
            "Content-Type": "application/json",
            "User-Agent": f"ozon-seller-api-mini/{__version__}",
        }
        if http is None:
            self._http = httpx.Client(base_url=base_url, timeout=timeout, headers=headers)
            self._owns_http = True
        else:
            http.headers.update(headers)
            self._http = http
            self._owns_http = False

    @classmethod
    def from_env(cls, **kwargs: Any) -> OzonClient:
        """Ключи из переменных окружения ``OZON_CLIENT_ID`` и ``OZON_API_KEY``."""
        client_id = os.environ.get("OZON_CLIENT_ID", "")
        api_key = os.environ.get("OZON_API_KEY", "")
        if not client_id or not api_key:
            raise RuntimeError("задайте переменные окружения OZON_CLIENT_ID и OZON_API_KEY")
        return cls(client_id, api_key, **kwargs)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> OzonClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- transport

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            ra = response.headers.get("Retry-After")
            if ra:
                try:
                    return min(float(ra), self.max_backoff)
                except ValueError:
                    pass
        delay = min(self.backoff * (2.0 ** attempt), self.max_backoff)
        return delay + random.uniform(0, delay * self.jitter) if self.jitter else delay

    def post(self, path: str, body: Json | None = None) -> Json:
        """POST с ретраями. Возвращает JSON-ответ или бросает :class:`OzonAPIError`."""
        attempt = 0
        while True:
            try:
                resp = self._http.post(path, json=body or {})
            except httpx.TransportError:
                if attempt >= self.max_retries:
                    raise
                self._sleep(self._delay(attempt, None))
                attempt += 1
                continue
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                self._sleep(self._delay(attempt, resp))
                attempt += 1
                continue
            if resp.is_success:
                data: Json = resp.json() if resp.content else {}
                return data
            raise self._error(path, resp)

    @staticmethod
    def _error(path: str, resp: httpx.Response) -> OzonAPIError:
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        message = str(data.get("message") or resp.reason_phrase or "error")
        code = data.get("code")
        kw: dict[str, Any] = {"code": int(code) if isinstance(code, int) else None,
                              "details": data.get("details"), "path": path}
        status = resp.status_code
        if "obsolete" in message.lower():
            return ObsoleteMethodError(status, message, **kw)
        if status in (401, 403):
            return AuthError(status, message, **kw)
        if status == 404:
            return NotFoundError(status, message, **kw)
        if status == 429:
            return RateLimitError(status, message, **kw)
        return OzonAPIError(status, message, **kw)

    # -------------------------------------------------------------- products

    def iter_products(self, visibility: str = "ALL", *, limit: int = 1000) -> Iterator[ProductListItem]:
        """Все товары магазина: /v3/product/list с пагинацией по ``last_id``."""
        last_id = ""
        while True:
            data = self.post("/v3/product/list", {"filter": {"visibility": visibility}, "last_id": last_id, "limit": limit})
            result = data.get("result") or {}
            items = result.get("items") or []
            for it in items:
                yield ProductListItem.from_api(it)
            new_last = result.get("last_id") or ""
            if len(items) < limit or not new_last or new_last == last_id:
                return
            last_id = new_last

    def get_product_info(
        self,
        *,
        offer_ids: Iterable[str] = (),
        product_ids: Iterable[int] = (),
        skus: Iterable[int] = (),
        chunk_size: int = 100,
    ) -> list[ProductInfo]:
        """Карточки по offer_id / product_id / sku: /v3/product/info/list, пачками по ``chunk_size``."""
        out: list[ProductInfo] = []
        for key, values in (("offer_id", [str(v) for v in offer_ids]),
                            ("product_id", [int(v) for v in product_ids]),
                            ("sku", [int(v) for v in skus])):
            for chunk in _chunks(values, chunk_size):
                data = self.post("/v3/product/info/list", {key: chunk})
                out.extend(ProductInfo.from_api(it) for it in data.get("items") or [])
        return out

    # ---------------------------------------------------------------- stocks

    def iter_stocks(self, visibility: str = "ALL", *, offer_ids: Sequence[str] = (),
                    limit: int = 1000) -> Iterator[ProductStocks]:
        """Остатки по магазину в целом (FBO/FBS суммарно): /v4/product/info/stocks, пагинация по ``cursor``.

        Разбивки по складам продавца здесь нет — для неё :meth:`iter_fbs_stocks_by_warehouse`.
        """
        flt: Json = {"visibility": visibility}
        if offer_ids:
            flt["offer_id"] = list(offer_ids)
        cursor = ""
        while True:
            data = self.post("/v4/product/info/stocks", {"filter": flt, "limit": limit, "cursor": cursor})
            items = data.get("items") or []
            for it in items:
                yield ProductStocks.from_api(it)
            new_cursor = data.get("cursor") or ""
            if not items or not new_cursor or new_cursor == cursor:
                return
            cursor = new_cursor

    def iter_fbs_stocks_by_warehouse(self, skus: Iterable[int | str], *, limit: int = 1000,
                                     sku_chunk: int = 500) -> Iterator[FbsWarehouseStock]:
        """Остаток FBS на каждом складе продавца: /v2/product/info/stocks-by-warehouse/fbs.

        Одна строка на пару «товар + склад». ``limit`` обязателен (1…1000), дальше —
        ``cursor`` и ``has_next``. SKU берутся из :meth:`get_product_info`.
        """
        if not 0 < limit <= 1000:
            raise ValueError("limit должен быть от 1 до 1000")
        sku_list = [str(s) for s in skus]
        for chunk in _chunks(sku_list, sku_chunk):
            cursor = ""
            while True:
                body: Json = {"sku": chunk, "limit": limit}
                if cursor:
                    body["cursor"] = cursor
                data = self.post("/v2/product/info/stocks-by-warehouse/fbs", body)
                for it in data.get("products") or []:
                    yield FbsWarehouseStock.from_api(it)
                new_cursor = data.get("cursor") or ""
                if not data.get("has_next") or not new_cursor or new_cursor == cursor:
                    break
                cursor = new_cursor

    def iter_ozon_warehouse_stocks(self, warehouse_type: str = "ALL", *,
                                   limit: int = 1000) -> Iterator[OzonWarehouseStock]:
        """Остатки на складах Ozon (FBO): /v2/analytics/stock_on_warehouses, пагинация по ``offset``.

        Склады продавца (FBS) этот метод не показывает.
        """
        offset = 0
        while True:
            data = self.post("/v2/analytics/stock_on_warehouses",
                             {"limit": limit, "offset": offset, "warehouse_type": warehouse_type})
            rows = (data.get("result") or {}).get("rows") or []
            for r in rows:
                yield OzonWarehouseStock.from_api(r)
            if len(rows) < limit:
                return
            offset += limit

    # -------------------------------------------------------------- postings

    def iter_fbs_postings(
        self,
        since: datetime | str,
        to: datetime | str,
        *,
        status: str | None = None,
        warehouse_ids: Sequence[int] = (),
        financial_data: bool = False,
        analytics_data: bool = False,
        limit: int = 1000,
    ) -> Iterator[Posting]:
        """Отправления FBS за период: /v3/posting/fbs/list, пагинация ``offset`` + ``has_next``.

        ``status`` — например ``awaiting_packaging``, ``awaiting_deliver``, ``delivering``.
        """
        flt: Json = {"since": format_time(since), "to": format_time(to)}
        if status:
            flt["status"] = status
        if warehouse_ids:
            flt["warehouse_id"] = list(warehouse_ids)
        offset = 0
        while True:
            body = {
                "dir": "ASC",
                "filter": flt,
                "limit": limit,
                "offset": offset,
                "with": {"financial_data": financial_data, "analytics_data": analytics_data},
            }
            data = self.post("/v3/posting/fbs/list", body)
            result = data.get("result") or {}
            postings = result.get("postings") or []
            for p in postings:
                yield Posting.from_api(p)
            if not result.get("has_next") or not postings:
                return
            offset += len(postings)
