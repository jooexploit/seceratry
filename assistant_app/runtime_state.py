from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional


class SensitiveActionStore:
    def __init__(self):
        self.tokens: Dict[str, Dict[str, str]] = {}

    def create(self, action: str, ttl_seconds: int = 90) -> str:
        token = secrets.token_urlsafe(10)
        self.tokens[token] = {
            "action": action,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=max(30, ttl_seconds))).isoformat(),
        }
        return token

    def consume(self, token: str) -> Optional[str]:
        payload = self.tokens.pop(token, None)
        if not payload:
            return None
        exp_raw = payload.get("expires_at")
        try:
            exp = datetime.fromisoformat(exp_raw)
            if datetime.now(timezone.utc) > exp:
                return None
        except Exception:
            return None
        return payload.get("action")
