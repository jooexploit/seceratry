from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional


def event_delta_minutes(event_dt: Optional[datetime], now_dt: datetime) -> Optional[float]:
    if event_dt is None:
        return None
    return (event_dt - now_dt).total_seconds() / 60.0
