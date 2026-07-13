"""Retry utilities for unstable operations such as external API calls."""

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar
import logging
import time


P = ParamSpec("P")
R = TypeVar("R")


def retry(
    max_attempts: int,
    delay_seconds: float,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    logger: logging.Logger | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry a function when the configured exceptions are raised."""
    # max_attemptsは「最初の1回 + やり直し回数」を含む合計試行回数。
    if max_attempts < 1:
        raise ValueError("max_attempts must be greater than or equal to 1.")

    # retry(...)を関数の上に付けるため、関数を包むdecoratorを返す。
    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # 外部APIの一時的な失敗だけを想定し、指定回数まで同じ処理を再試行する。
            for attempt in range(1, max_attempts + 1):
                try:
                    return function(*args, **kwargs)
                except exceptions as error:
                    # 最終試行でも失敗した場合は、呼び出し元で処理できるよう例外を戻す。
                    if attempt == max_attempts:
                        raise

                    if logger is not None:
                        # 途中の失敗はwarningログに残し、何回目の再試行か分かるようにする。
                        logger.warning(
                            "Retrying %s after error: %s (%s/%s)",
                            function.__name__,
                            error,
                            attempt,
                            max_attempts,
                        )

                    # すぐ再実行せず少し待つことで、APIの一時的な混雑を避けやすくする。
                    time.sleep(delay_seconds)

            raise RuntimeError("Retry loop exited unexpectedly.")

        return wrapper

    return decorator
