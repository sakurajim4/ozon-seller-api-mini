# ozon-seller-api-mini

[![tests](https://github.com/sakurajim4/ozon-seller-api-mini/actions/workflows/tests.yml/badge.svg)](https://github.com/sakurajim4/ozon-seller-api-mini/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)
![typed](https://img.shields.io/badge/mypy-strict-informational)
![license](https://img.shields.io/badge/license-MIT-green)

Маленький типизированный клиент **Ozon Seller API** на `httpx`. Только то, что чаще всего нужно в автоматизации магазина: товары, остатки (в том числе **по каждому складу продавца**), отправления FBS. Пагинация спрятана в итераторы, на `429` и `5xx` — повтор с паузой.

## Установка

```bash
pip install git+https://github.com/sakurajim4/ozon-seller-api-mini
```

## Быстрый старт

```python
from datetime import datetime, timedelta, timezone
from ozon_seller_api_mini import OzonClient

with OzonClient(client_id="...", api_key="...") as ozon:      # или OzonClient.from_env()
    for p in ozon.iter_products():                            # все товары, пагинация внутри
        print(p.product_id, p.offer_id)

    info = ozon.get_product_info(offer_ids=["ART-1", "ART-2"])  # карточки: name, sku, price, barcodes…
    skus = [i.sku for i in info if i.sku]

    for row in ozon.iter_fbs_stocks_by_warehouse(skus):       # остаток FBS на каждом складе продавца
        print(row.warehouse_name, row.offer_id, row.present, row.reserved, row.free_stock)

    now = datetime.now(timezone.utc)
    for posting in ozon.iter_fbs_postings(now - timedelta(days=3), now, status="awaiting_packaging"):
        print(posting.posting_number, posting.shipment_date, [(i.offer_id, i.quantity) for i in posting.products])
```

`OzonClient.from_env()` берёт ключи из `OZON_CLIENT_ID` и `OZON_API_KEY`. Ключи не попадают в логи и исключения.

## Методы

| Метод клиента | Endpoint | Что возвращает |
|---|---|---|
| `iter_products(visibility="ALL")` | `/v3/product/list` | `ProductListItem` — все товары, пагинация по `last_id` |
| `get_product_info(offer_ids=, product_ids=, skus=)` | `/v3/product/info/list` | `ProductInfo` — название, SKU, цена, штрихкоды, статус; запросы пачками по 100 |
| `iter_stocks(offer_ids=)` | `/v4/product/info/stocks` | `ProductStocks` — остаток FBO/FBS **по магазину в целом**, пагинация по `cursor` |
| `iter_fbs_stocks_by_warehouse(skus)` | `/v2/product/info/stocks-by-warehouse/fbs` | `FbsWarehouseStock` — строка на пару «товар + склад продавца»: `present`, `reserved`, `free_stock` |
| `iter_ozon_warehouse_stocks()` | `/v2/analytics/stock_on_warehouses` | `OzonWarehouseStock` — остатки на **складах Ozon** (FBO), пагинация по `offset` |
| `iter_fbs_postings(since, to, status=, financial_data=, analytics_data=)` | `/v3/posting/fbs/list` | `Posting` с товарами; `financial_data=True` — комиссии по позициям |
| `post(path, body)` | любой | сырой JSON с теми же ретраями и ошибками — для методов, которых нет в обёртке |

У всех моделей есть поле `raw` с исходным ответом — если нужного поля нет в модели, оно там.

## Что важно знать про остатки

- `/v4/product/info/stocks` отдаёт остаток **агрегированно**: `warehouse_ids` там пустой, по складам продавца не разбить.
- Остаток FBS по конкретному складу продавца — только `/v2/product/info/stocks-by-warehouse/fbs` (на вход SKU, `limit` обязателен и не больше 1000, дальше `cursor` + `has_next`). Версия `v1` этого метода отключена и отвечает `obsolete method cannot be used`.
- `/v2/analytics/stock_on_warehouses` показывает только склады Ozon (FBO); по складам продавца там пусто.

## Ретраи и ошибки

- `429`, `500`, `502`, `503`, `504` и сетевые ошибки повторяются до `max_retries` раз (по умолчанию 5). Пауза — `Retry-After` из ответа, иначе `backoff × 2^попытка` (1, 2, 4, 8… с), не больше `max_backoff`, плюс небольшой разброс `jitter`.
- Остальные ошибки не повторяются и превращаются в исключения: `AuthError` (401/403), `NotFoundError` (404), `ObsoleteMethodError` (версия метода отключена), `RateLimitError` (429 не отпустил), базовое `OzonAPIError` с `status_code`, `code`, `message`, `details`.

```python
ozon = OzonClient(cid, key, max_retries=8, backoff=2.0, max_backoff=60, timeout=60)
```

## Примеры

- [`examples/products_and_stocks.py`](examples/products_and_stocks.py) — товары и суммарные остатки FBO/FBS;
- [`examples/fbs_stock_by_warehouse.py`](examples/fbs_stock_by_warehouse.py) — остатки по каждому складу продавца;
- [`examples/fbs_postings_to_csv.py`](examples/fbs_postings_to_csv.py) — отправления «ожидают сборки» в CSV для Excel.

```bash
export OZON_CLIENT_ID=... OZON_API_KEY=...
python examples/fbs_stock_by_warehouse.py
```

## Разработка

```bash
pip install -e ".[dev]"
pytest          # все запросы замоканы через respx, ключи не нужны
mypy            # strict
```

## Лицензия

MIT. Проект не связан с Ozon; названия методов и поля — из публичной документации Seller API.

---

## English

**ozon-seller-api-mini** is a small typed (mypy-strict) Python client for the Ozon Seller API built on `httpx`. It covers products (`/v3/product/list`, `/v3/product/info/list`), stocks — aggregated (`/v4/product/info/stocks`), per seller warehouse for FBS (`/v2/product/info/stocks-by-warehouse/fbs`) and Ozon warehouses (`/v2/analytics/stock_on_warehouses`) — and FBS postings (`/v3/posting/fbs/list`). Pagination is wrapped in iterators; `429`/`5xx`/network errors are retried with `Retry-After` or capped exponential backoff; other errors raise typed exceptions. Tests mock every request with respx, so no real keys are needed.

```python
from ozon_seller_api_mini import OzonClient
with OzonClient.from_env() as ozon:           # OZON_CLIENT_ID / OZON_API_KEY
    for row in ozon.iter_fbs_stocks_by_warehouse([123456789]):
        print(row.warehouse_name, row.free_stock)
```
