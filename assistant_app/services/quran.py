from __future__ import annotations

from typing import Dict


def progress_text(done: int, goal: int) -> str:
    return f"{max(0, int(done))}/{max(1, int(goal))}"
