"""統一チャット（完全 bot）のルーティングコア。"""

from .routing import (
    BULK_THRESHOLD_CHARS,
    ROUTE_BULK,
    ROUTE_DEDUP,
    ROUTE_PENDING,
    ROUTE_QA,
    ROUTE_REGISTER,
    decide_route,
    main,
)

__all__ = [
    "BULK_THRESHOLD_CHARS",
    "ROUTE_BULK",
    "ROUTE_DEDUP",
    "ROUTE_PENDING",
    "ROUTE_QA",
    "ROUTE_REGISTER",
    "decide_route",
    "main",
]
