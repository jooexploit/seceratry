from __future__ import annotations

from typing import Any, Callable


def emit(notify_fn: Callable[..., Any], title: str, body: str, **kwargs):
    return notify_fn(title, body, **kwargs)
