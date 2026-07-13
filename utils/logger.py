"""Logging utilities for the affiliate system."""

from pathlib import Path
import logging


def setup_logging(log_level: str, log_file: Path | None = None) -> None:
    """Configure console and optional file logging."""
    # .envのLOG_LEVEL文字列をlogging.INFOなどの実際のログレベルに変換する。
    # 不正な値の場合はINFOとして扱い、ログが出なくなる事故を避ける。
    level = getattr(logging, log_level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    # log_fileが指定された場合は、コンソールとファイルの両方へ同じログを出す。
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    # force=Trueで、再実行時にもこのアプリ用のログ設定を確実に反映する。
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
