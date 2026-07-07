"""統一チャット v1 の決定的ルーティングコア。"""

from .routing import BULK_THRESHOLD_CHARS, decide_route, main

__all__ = ["BULK_THRESHOLD_CHARS", "decide_route", "main"]
