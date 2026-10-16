"""Остаток FBS на каждом складе продавца.

/v4/product/info/stocks отдаёт остаток по магазину в целом, а разбивку по складам
продавца даёт только /v2/product/info/stocks-by-warehouse/fbs (по SKU).
"""

from collections import defaultdict

from ozon_seller_api_mini import OzonClient

with OzonClient.from_env() as ozon:
    offer_ids = [p.offer_id for p in ozon.iter_products()]
    skus = [i.sku for i in ozon.get_product_info(offer_ids=offer_ids) if i.sku]

    by_warehouse: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in ozon.iter_fbs_stocks_by_warehouse(skus):
        if row.present:
            by_warehouse[row.warehouse_name].append((row.offer_id, row.free_stock))

    for warehouse, rows in by_warehouse.items():
        print(f"\n{warehouse}: {len(rows)} позиций, свободно {sum(q for _, q in rows)} шт")
        for offer_id, free in sorted(rows):
            print(f"  {offer_id:<30} {free:>5}")
