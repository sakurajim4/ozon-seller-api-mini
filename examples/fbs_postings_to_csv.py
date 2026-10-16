"""Отправления FBS «ожидают сборки» за последние 7 дней → CSV."""

import csv
from datetime import datetime, timedelta, timezone

from ozon_seller_api_mini import OzonClient

now = datetime.now(timezone.utc)
with OzonClient.from_env() as ozon, open("fbs_postings.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["Отправление", "Статус", "Отгрузить до", "Склад", "Артикул", "Кол-во", "Цена"])
    n = 0
    for p in ozon.iter_fbs_postings(now - timedelta(days=7), now, status="awaiting_packaging"):
        for item in p.products:
            w.writerow([p.posting_number, p.status, p.shipment_date, p.warehouse_name,
                        item.offer_id, item.quantity, item.price])
        n += 1
print(f"Отправлений: {n} → fbs_postings.csv")
