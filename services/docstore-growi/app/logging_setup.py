"""ログ設定。

会社端末での実行結果を持ち帰りやすくするため、ファイルにも出力する。

重要: シークレット（API トークン等）は決してログに出さない。
このモジュールはハンドラ設定のみ。各所のログ文に秘密情報を含めないことは
呼び出し側の責任（settings は base_url のみログ、token は出さない）。
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(service_name: str, log_dir: str, level: str) -> None:
    """コンソール + ローテーションファイルにログを出す。

    Args:
        service_name: ログファイル名に使うサービス名
        log_dir: ログ出力ディレクトリ（無ければ作成）
        level: ログレベル文字列（INFO 等）
    """
    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # 既存ハンドラを除去（多重設定防止）
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path / f"{service_name}.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:
        # ファイルに出せなくてもコンソールは生きている
        root.warning("ログファイルを開けませんでした (%s): %s", log_dir, exc)
