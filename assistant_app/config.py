from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable


SENSITIVE_KEYS = {
    "token",
    "client_secret",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "password",
}


def load_dotenv_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, val = text.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            data[key] = val
    return data


def apply_env_map(env_map: Dict[str, str]) -> None:
    for key, val in env_map.items():
        os.environ.setdefault(key, val)


def redact_sensitive_text(message: str, values: Iterable[str]) -> str:
    text = str(message)
    for val in values:
        if val and len(val) >= 6:
            text = text.replace(val, "***REDACTED***")
    return text


def collect_secret_values(config: Dict) -> list[str]:
    vals: list[str] = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = str(k).lower()
                if isinstance(v, str) and any(tag in key for tag in SENSITIVE_KEYS):
                    vals.append(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(config)
    for env_key in ["TELEGRAM_BOT_TOKEN", "QURAN_CLIENT_SECRET", "QURAN_CLIENT_ID"]:
        if os.getenv(env_key):
            vals.append(os.getenv(env_key, ""))

    return [x for x in vals if x]
