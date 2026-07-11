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
    if max_attempts < 1:
        raise ValueError("max_attempts must be greater than or equal to 1.")

    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, max_attempts + 1):
                try:
                    return function(*args, **kwargs)
                except exceptions as error:
                    if attempt == max_attempts:
                        raise

                    if logger is not None:
                        logger.warning(
                            "Retrying %s after error: %s (%s/%s)",
                            function.__name__,
                            error,
                            attempt,
                            max_attempts,
                        )

                    time.sleep(delay_seconds)

            raise RuntimeError("Retry loop exited unexpectedly.")

        return wrapper

    return decorator
