"""Список товаров и суммарные остатки FBO/FBS.

    export OZON_CLIENT_ID=...  OZON_API_KEY=...
    python examples/products_and_stocks.py
"""

from ozon_seller_api_mini import OzonClient

with OzonClient.from_env() as ozon:
    products = list(ozon.iter_products())
    print(f"Товаров: {len(products)}, в архиве: {sum(p.archived for p in products)}")

    for item in ozon.iter_stocks():
        fbo, fbs = item.present("fbo"), item.present("fbs")
        if fbo or fbs:
            print(f"{item.offer_id:<30} FBO {fbo:>5}  FBS {fbs:>5}")
