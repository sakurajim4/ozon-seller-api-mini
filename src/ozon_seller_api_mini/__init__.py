"""Маленький типизированный клиент Ozon Seller API."""

__version__ = "0.1.0"

from .client import OzonClient, format_time
from .errors import AuthError, NotFoundError, ObsoleteMethodError, OzonAPIError, RateLimitError
from .models import (
    FbsWarehouseStock,
    OzonWarehouseStock,
    Posting,
    PostingProduct,
    ProductInfo,
    ProductListItem,
    ProductStocks,
    StockEntry,
)

__all__ = [
    "AuthError",
    "FbsWarehouseStock",
    "NotFoundError",
    "ObsoleteMethodError",
    "OzonAPIError",
    "OzonClient",
    "OzonWarehouseStock",
    "Posting",
    "PostingProduct",
    "ProductInfo",
    "ProductListItem",
    "ProductStocks",
    "RateLimitError",
    "StockEntry",
    "format_time",
]
