"""Модели ответов. Описаны ключевые поля; весь исходный ответ лежит в ``raw``."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

Json = dict[str, Any]


def _int(v: Any) -> int | None:
    if v in (None, ""):
        return None
    return int(v)


def _float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def _dt(v: Any) -> datetime | None:
    if not v:
        return None
    s = str(v)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@dataclass(frozen=True)
class ProductListItem:
    """Элемент /v3/product/list."""

    product_id: int
    offer_id: str
    archived: bool
    has_fbo_stocks: bool
    has_fbs_stocks: bool
    raw: Json = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Json) -> ProductListItem:
        return cls(
            product_id=int(d["product_id"]),
            offer_id=str(d.get("offer_id", "")),
            archived=bool(d.get("archived", False)),
            has_fbo_stocks=bool(d.get("has_fbo_stocks", False)),
            has_fbs_stocks=bool(d.get("has_fbs_stocks", False)),
            raw=d,
        )


@dataclass(frozen=True)
class ProductInfo:
    """Элемент /v3/product/info/list."""

    product_id: int
    offer_id: str
    name: str
    sku: int | None
    barcodes: list[str]
    price: float | None
    old_price: float | None
    currency_code: str
    primary_image: str | None
    status: str | None
    raw: Json = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Json) -> ProductInfo:
        sku = d.get("sku")
        if not sku:
            sources = d.get("sources") or []
            sku = next((s.get("sku") for s in sources if s.get("sku")), None)
        img = d.get("primary_image")
        if isinstance(img, list):
            img = img[0] if img else None
        if not img and d.get("images"):
            img = d["images"][0]
        statuses = d.get("statuses") or {}
        return cls(
            product_id=int(d.get("id") or d.get("product_id") or 0),
            offer_id=str(d.get("offer_id", "")),
            name=str(d.get("name", "")),
            sku=_int(sku),
            barcodes=[str(b) for b in d.get("barcodes") or []],
            price=_float(d.get("price")),
            old_price=_float(d.get("old_price")),
            currency_code=str(d.get("currency_code", "")),
            primary_image=img or None,
            status=statuses.get("status") if isinstance(statuses, dict) else None,
            raw=d,
        )


@dataclass(frozen=True)
class StockEntry:
    type: str
    present: int
    reserved: int
    sku: int | None
    shipment_type: str | None
    warehouse_ids: list[int]

    @property
    def free(self) -> int:
        return self.present - self.reserved


@dataclass(frozen=True)
class ProductStocks:
    """Элемент /v4/product/info/stocks — остаток по магазину в целом (без разбивки по складам)."""

    product_id: int
    offer_id: str
    stocks: list[StockEntry]
    raw: Json = field(repr=False, compare=False)

    def present(self, stock_type: str) -> int:
        return sum(s.present for s in self.stocks if s.type == stock_type)

    def reserved(self, stock_type: str) -> int:
        return sum(s.reserved for s in self.stocks if s.type == stock_type)

    @classmethod
    def from_api(cls, d: Json) -> ProductStocks:
        return cls(
            product_id=int(d.get("product_id") or 0),
            offer_id=str(d.get("offer_id", "")),
            stocks=[
                StockEntry(
                    type=str(s.get("type", "")),
                    present=int(s.get("present") or 0),
                    reserved=int(s.get("reserved") or 0),
                    sku=_int(s.get("sku")),
                    shipment_type=s.get("shipment_type"),
                    warehouse_ids=[int(w) for w in s.get("warehouse_ids") or []],
                )
                for s in d.get("stocks") or []
            ],
            raw=d,
        )


@dataclass(frozen=True)
class FbsWarehouseStock:
    """Элемент /v2/product/info/stocks-by-warehouse/fbs — остаток на конкретном складе продавца."""

    offer_id: str
    sku: int | None
    product_id: int | None
    warehouse_id: int
    warehouse_name: str
    present: int
    reserved: int
    free_stock: int
    raw: Json = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Json) -> FbsWarehouseStock:
        present = int(d.get("present") or 0)
        reserved = int(d.get("reserved") or 0)
        free = d.get("free_stock")
        return cls(
            offer_id=str(d.get("offer_id", "")),
            sku=_int(d.get("sku")),
            product_id=_int(d.get("product_id")),
            warehouse_id=int(d.get("warehouse_id") or 0),
            warehouse_name=str(d.get("warehouse_name", "")),
            present=present,
            reserved=reserved,
            free_stock=int(free) if free is not None else present - reserved,
            raw=d,
        )


@dataclass(frozen=True)
class OzonWarehouseStock:
    """Строка /v2/analytics/stock_on_warehouses — остаток на складах Ozon (FBO)."""

    sku: int | None
    offer_id: str
    name: str
    warehouse_name: str
    free_to_sell: int
    promised: int
    reserved: int
    raw: Json = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Json) -> OzonWarehouseStock:
        return cls(
            sku=_int(d.get("sku")),
            offer_id=str(d.get("item_code", "")),
            name=str(d.get("item_name", "")),
            warehouse_name=str(d.get("warehouse_name", "")),
            free_to_sell=int(d.get("free_to_sell_amount") or 0),
            promised=int(d.get("promised_amount") or 0),
            reserved=int(d.get("reserved_amount") or 0),
            raw=d,
        )


@dataclass(frozen=True)
class PostingProduct:
    sku: int | None
    offer_id: str
    name: str
    quantity: int
    price: float | None
    currency_code: str


@dataclass(frozen=True)
class Posting:
    """Отправление FBS из /v3/posting/fbs/list."""

    posting_number: str
    order_id: int | None
    order_number: str
    status: str
    substatus: str
    in_process_at: datetime | None
    shipment_date: datetime | None
    delivery_method: str
    warehouse_id: int | None
    warehouse_name: str
    tracking_number: str
    products: list[PostingProduct]
    financial_data: Json | None
    analytics_data: Json | None
    raw: Json = field(repr=False, compare=False)

    @property
    def total(self) -> float:
        return sum((p.price or 0.0) * p.quantity for p in self.products)

    @classmethod
    def from_api(cls, d: Json) -> Posting:
        dm = d.get("delivery_method") or {}
        return cls(
            posting_number=str(d.get("posting_number", "")),
            order_id=_int(d.get("order_id")),
            order_number=str(d.get("order_number", "")),
            status=str(d.get("status", "")),
            substatus=str(d.get("substatus", "")),
            in_process_at=_dt(d.get("in_process_at")),
            shipment_date=_dt(d.get("shipment_date")),
            delivery_method=str(dm.get("name", "")),
            warehouse_id=_int(dm.get("warehouse_id")),
            warehouse_name=str(dm.get("warehouse", "")),
            tracking_number=str(d.get("tracking_number", "")),
            products=[
                PostingProduct(
                    sku=_int(p.get("sku")),
                    offer_id=str(p.get("offer_id", "")),
                    name=str(p.get("name", "")),
                    quantity=int(p.get("quantity") or 0),
                    price=_float(p.get("price")),
                    currency_code=str(p.get("currency_code", "")),
                )
                for p in d.get("products") or []
            ],
            financial_data=d.get("financial_data"),
            analytics_data=d.get("analytics_data"),
            raw=d,
        )
