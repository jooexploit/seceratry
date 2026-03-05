from __future__ import annotations

from typing import Any, Callable, Optional


def enable(enable_fn: Callable[[Optional[int]], Any], minutes: Optional[int] = None):
    return enable_fn(minutes)


def disable(disable_fn: Callable[[], Any]):
    return disable_fn()
