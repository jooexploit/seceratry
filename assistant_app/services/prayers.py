from __future__ import annotations

from typing import Dict


def prayer_completion_ratio(metrics: Dict[str, int]) -> float:
    planned = int(metrics.get("prayers_planned", 0) or 0)
    prayed = int(metrics.get("prayers_prayed", 0) or 0)
    if planned <= 0:
        return 1.0
    return max(0.0, min(1.0, prayed / planned))
