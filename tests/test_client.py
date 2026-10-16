from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from ozon_seller_api_mini import (
    AuthError,
    NotFoundError,
    ObsoleteMethodError,
    OzonAPIError,
    OzonClient,
    RateLimitError,
    format_time,
)

BASE = "https://api-seller.ozon.ru"


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(sleeps):
    c = OzonClient("123456", "test-api-key", max_retries=3, backoff=1.0, jitter=0.0, sleep=sleeps.append)
    yield c
    c.close()


def body(call) -> dict:
    return json.loads(call.request.content)


@respx.mock
def test_auth_headers_sent(client):
    route = respx.post(f"{BASE}/v3/product/list").respond(json={"result": {"items": [], "last_id": ""}})
    list(client.iter_products())
    req = route.calls.last.request
    assert req.headers["Client-Id"] == "123456"
    assert req.headers["Api-Key"] == "test-api-key"
    assert req.headers["User-Agent"].startswith("ozon-seller-api-mini/")


@respx.mock
def test_products_paginate_by_last_id(client):
    route = respx.post(f"{BASE}/v3/product/list").mock(side_effect=[
        httpx.Response(200, json={"result": {"items": [
            {"product_id": 1, "offer_id": "A"}, {"product_id": 2, "offer_id": "B"}], "last_id": "p2", "total": 3}}),
        httpx.Response(200, json={"result": {"items": [
            {"product_id": 3, "offer_id": "C", "archived": True}], "last_id": "p3", "total": 3}}),
    ])
    items = list(client.iter_products(limit=2))
    assert [i.offer_id for i in items] == ["A", "B", "C"]
    assert items[2].archived
    assert [body(c)["last_id"] for c in route.calls] == ["", "p2"]
    assert body(route.calls[0])["filter"] == {"visibility": "ALL"}


@respx.mock
def test_product_info_chunks_and_sku_fallback(client):
    def reply(request):
        ids = json.loads(request.content)["offer_id"]
        items = [{"id": i, "offer_id": o, "name": f"Товар {o}", "sources": [{"sku": 9000 + i, "source": "sds"}],
                  "price": "499.0000", "barcodes": ["4600000000001"], "primary_image": ["https://cdn/x.jpg"],
                  "statuses": {"status": "price_sent"}} for i, o in enumerate(ids)]
        return httpx.Response(200, json={"items": items})

    route = respx.post(f"{BASE}/v3/product/info/list").mock(side_effect=reply)
    offers = [f"OF-{n}" for n in range(250)]
    info = client.get_product_info(offer_ids=offers)
    assert len(route.calls) == 3
    assert [len(body(c)["offer_id"]) for c in route.calls] == [100, 100, 50]
    assert len(info) == 250
    first = info[0]
    assert first.sku == 9000 and first.price == 499.0
    assert first.primary_image == "https://cdn/x.jpg" and first.status == "price_sent"


@respx.mock
def test_stocks_v4_cursor(client):
    route = respx.post(f"{BASE}/v4/product/info/stocks").mock(side_effect=[
        httpx.Response(200, json={"items": [{"product_id": 1, "offer_id": "A", "stocks": [
            {"type": "fbo", "present": 10, "reserved": 2, "sku": 111, "warehouse_ids": []},
            {"type": "fbs", "present": 5, "reserved": 1, "sku": 111, "warehouse_ids": []}]}],
            "cursor": "c1", "total": 2}),
        httpx.Response(200, json={"items": [{"product_id": 2, "offer_id": "B", "stocks": []}], "cursor": "", "total": 2}),
    ])
    stocks = list(client.iter_stocks(offer_ids=["A", "B"]))
    assert [s.offer_id for s in stocks] == ["A", "B"]
    assert stocks[0].present("fbo") == 10 and stocks[0].reserved("fbs") == 1
    assert stocks[0].stocks[0].free == 8
    assert body(route.calls[0])["filter"]["offer_id"] == ["A", "B"]
    assert body(route.calls[1])["cursor"] == "c1"


@respx.mock
def test_fbs_stocks_by_warehouse(client):
    row = {"offer_id": "A", "sku": 111, "product_id": 1, "warehouse_id": 77, "warehouse_name": "Склад 1",
           "present": 7, "reserved": 2, "free_stock": 5}
    route = respx.post(f"{BASE}/v2/product/info/stocks-by-warehouse/fbs").mock(side_effect=[
        httpx.Response(200, json={"products": [row], "cursor": "n1", "has_next": True}),
        httpx.Response(200, json={"products": [{**row, "warehouse_id": 78, "warehouse_name": "Склад 2",
                                                 "free_stock": None}], "cursor": "", "has_next": False}),
    ])
    rows = list(client.iter_fbs_stocks_by_warehouse([111]))
    assert [(r.warehouse_name, r.free_stock) for r in rows] == [("Склад 1", 5), ("Склад 2", 5)]
    first, second = body(route.calls[0]), body(route.calls[1])
    assert first == {"sku": ["111"], "limit": 1000}
    assert second["cursor"] == "n1"
    with pytest.raises(ValueError):
        list(client.iter_fbs_stocks_by_warehouse([1], limit=0))


@respx.mock
def test_ozon_warehouse_stocks_offset(client):
    rows = [{"sku": i, "item_code": f"A{i}", "item_name": "x", "warehouse_name": "ХОРУГВИНО",
             "free_to_sell_amount": 3, "promised_amount": 0, "reserved_amount": 1} for i in range(3)]
    route = respx.post(f"{BASE}/v2/analytics/stock_on_warehouses").mock(side_effect=[
        httpx.Response(200, json={"result": {"rows": rows[:2]}}),
        httpx.Response(200, json={"result": {"rows": rows[2:]}}),
    ])
    out = list(client.iter_ozon_warehouse_stocks(limit=2))
    assert [r.offer_id for r in out] == ["A0", "A1", "A2"]
    assert [body(c)["offset"] for c in route.calls] == [0, 2]
    assert body(route.calls[0])["warehouse_type"] == "ALL"


@respx.mock
def test_fbs_postings(client):
    posting = {
        "posting_number": "12345678-0001-1", "order_id": 555, "order_number": "12345678-0001",
        "status": "awaiting_packaging", "substatus": "posting_created",
        "in_process_at": "2026-10-16T09:15:00Z", "shipment_date": "2026-10-17T10:00:00Z",
        "delivery_method": {"id": 1, "name": "Доставка Ozon", "warehouse_id": 77, "warehouse": "Склад 1"},
        "products": [{"sku": 111, "offer_id": "A", "name": "Товар", "quantity": 2, "price": "450.0000",
                      "currency_code": "RUB"}],
        "financial_data": {"products": [{"commission_percent": 23}]},
    }
    route = respx.post(f"{BASE}/v3/posting/fbs/list").mock(side_effect=[
        httpx.Response(200, json={"result": {"postings": [posting], "has_next": True}}),
        httpx.Response(200, json={"result": {"postings": [{**posting, "posting_number": "2"}], "has_next": False}}),
    ])
    since = datetime(2026, 10, 10, tzinfo=timezone.utc)
    to = since + timedelta(days=7)
    out = list(client.iter_fbs_postings(since, to, status="awaiting_packaging", financial_data=True))
    assert [p.posting_number for p in out] == ["12345678-0001-1", "2"]
    p = out[0]
    assert p.total == 900.0 and p.warehouse_id == 77 and p.delivery_method == "Доставка Ozon"
    assert p.in_process_at == datetime(2026, 10, 16, 9, 15, tzinfo=timezone.utc)
    assert p.financial_data == {"products": [{"commission_percent": 23}]}
    b0 = body(route.calls[0])
    assert b0["filter"] == {"since": "2026-10-10T00:00:00.000Z", "to": "2026-10-17T00:00:00.000Z",
                            "status": "awaiting_packaging"}
    assert b0["with"] == {"financial_data": True, "analytics_data": False}
    assert body(route.calls[1])["offset"] == 1


@respx.mock
def test_retry_on_429_honours_retry_after(client, sleeps):
    route = respx.post(f"{BASE}/v3/product/list").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"}, json={"code": 8, "message": "rate limit"}),
        httpx.Response(429, json={"code": 8, "message": "rate limit"}),
        httpx.Response(200, json={"result": {"items": [], "last_id": ""}}),
    ])
    assert list(client.iter_products()) == []
    assert route.call_count == 3
    assert sleeps == [7.0, 2.0]


@respx.mock
def test_retry_exhausted_raises_rate_limit(client, sleeps):
    respx.post(f"{BASE}/v3/product/list").respond(429, json={"code": 8, "message": "rate limit"})
    with pytest.raises(RateLimitError) as e:
        list(client.iter_products())
    assert e.value.status_code == 429 and e.value.code == 8
    assert sleeps == [1.0, 2.0, 4.0]


@respx.mock
def test_retry_on_5xx_and_network_error(client, sleeps):
    respx.post(f"{BASE}/v3/product/list").mock(side_effect=[
        httpx.ConnectError("boom"),
        httpx.Response(503),
        httpx.Response(200, json={"result": {"items": [], "last_id": ""}}),
    ])
    assert list(client.iter_products()) == []
    assert sleeps == [1.0, 2.0]


@respx.mock
def test_backoff_is_capped(sleeps):
    c = OzonClient("1", "k", max_retries=4, backoff=10, max_backoff=25, jitter=0.0, sleep=sleeps.append)
    respx.post(f"{BASE}/x").respond(500, json={"message": "internal"})
    with pytest.raises(OzonAPIError):
        c.post("/x")
    assert sleeps == [10, 20, 25, 25]


@respx.mock
@pytest.mark.parametrize("status, payload, exc", [
    (401, {"code": 16, "message": "Invalid Api-Key"}, AuthError),
    (403, {"code": 7, "message": "Permission denied"}, AuthError),
    (404, {"code": 5, "message": "Not Found"}, NotFoundError),
    (404, {"code": 9, "message": "obsolete method cannot be used"}, ObsoleteMethodError),
    (400, {"code": 3, "message": "INVALID_ARGUMENT"}, OzonAPIError),
])
def test_errors_are_not_retried(client, sleeps, status, payload, exc):
    respx.post(f"{BASE}/x").respond(status, json=payload)
    with pytest.raises(exc) as e:
        client.post("/x", {})
    assert e.value.code == payload["code"] and e.value.message == payload["message"]
    assert "/x" in str(e.value)
    assert sleeps == []


@respx.mock
def test_non_json_error_body(client):
    respx.post(f"{BASE}/x").respond(400, text="<html>bad gateway</html>")
    with pytest.raises(OzonAPIError) as e:
        client.post("/x")
    assert e.value.code is None


def test_from_env(monkeypatch):
    monkeypatch.delenv("OZON_CLIENT_ID", raising=False)
    monkeypatch.delenv("OZON_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        OzonClient.from_env()
    monkeypatch.setenv("OZON_CLIENT_ID", "42")
    monkeypatch.setenv("OZON_API_KEY", "k")
    with OzonClient.from_env() as c:
        assert c._http.headers["Client-Id"] == "42"


def test_format_time():
    assert format_time(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05.000Z"
    msk = timezone(timedelta(hours=3))
    assert format_time(datetime(2026, 1, 2, 3, 0, tzinfo=msk)) == "2026-01-02T00:00:00.000Z"
    assert format_time("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00Z"
