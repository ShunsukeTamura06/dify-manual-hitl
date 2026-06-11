"""一括取り込み Bot のスプリッターロジック（案A Map-Reduce の Code ノード共用）。"""

from .reduce import merge_window_pages
from .windows import split_into_windows

__all__ = ["merge_window_pages", "split_into_windows"]
