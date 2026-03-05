#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import html
import json
import logging
import os
import platform
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import deque
from datetime import date, datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    Y,
    Button,
    Entry,
    Frame,
    Label,
    Listbox,
    PanedWindow,
    Scrollbar,
    Spinbox,
    StringVar,
    Text,
    Tk,
    messagebox,
)
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Optional: Google Calendar
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False
    HttpError = Exception

# Optional: Dashboard (Flask)
try:
    from flask import Flask, jsonify, redirect, request

    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

# Optional: Tray icon
try:
    import pystray
    from PIL import Image, ImageDraw

    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# Optional: Pillow screenshot backend
try:
    from PIL import ImageGrab

    HAS_IMAGEGRAB = True
except ImportError:
    HAS_IMAGEGRAB = False

# Optional: Telegram bot
try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import Application as TelegramApplication
    from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False

# Optional: Python screenshot backend
try:
    import mss
    import mss.tools

    HAS_MSS = True
except ImportError:
    HAS_MSS = False

from assistant_app.config import apply_env_map, collect_secret_values, load_dotenv_file, redact_sensitive_text
from assistant_app.install.linux_autostart import install_linux_autostart, uninstall_linux_autostart
from assistant_app.install.windows_autostart import install_windows_task, uninstall_windows_task
from assistant_app.migrations import apply_v2_migrations
from assistant_app.platform import get_platform_adapter
from assistant_app.runtime_state import SensitiveActionStore
from assistant_app.services.scoring import calculate_daily_score, format_score_text

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
GOOGLE_TOKEN_PATH = BASE_DIR / "token.json"
LEGACY_QURAN_STATE_PATH = BASE_DIR / "quran_state.json"
DOTENV_PATH = BASE_DIR / ".env"

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

DEFAULT_CONFIG: Dict[str, Any] = {
    "user_name": "jooexploit",
    "timezone": "Africa/Cairo",
    "log_file": str(BASE_DIR / "assistant.log"),
    "db_path": str(BASE_DIR / "assistant.db"),
    "http": {
        "timeout_seconds": 15,
        "retries": 4,
        "backoff_factor": 0.7,
    },
    "workday_limit_hours": 8,
    "location": {
        "city": "Cairo",
        "country": "EG",
        "method": 5,
    },
    "prayers": {
        "enabled": True,
        "remind_before_minutes": 15,
        "last_call_minutes": 5,
        "window_minutes": {
            "fajr": 60,
            "dhuhr": 60,
            "asr": 60,
            "maghrib": 60,
            "isha": 60,
        },
        "mosque_mode": {
            "enabled": True,
            "iqama_offsets_minutes": {
                "fajr": 20,
                "dhuhr": 15,
                "asr": 15,
                "maghrib": 10,
                "isha": 20,
            },
        },
    },
    "ramadan": {
        "enabled": True,
        "auto_detect": True,
        "force_ramadan": False,
        "suhoor_minutes_before_fajr": 45,
        "taraweeh_minutes_after_isha": 35,
    },
    "jumuah": {
        "enabled": True,
        "khutbah_time": "12:30",
        "khutbah_remind_before_minutes": 40,
        "early_departure_minutes_before": 55,
    },
    "pomodoro": {
        "enabled": True,
        "work_minutes": 50,
        "short_break_minutes": 10,
        "long_break_minutes": 25,
        "cycles_before_long_break": 4,
    },
    "health": {
        "water_interval_minutes": 60,
        "stretch_interval_minutes": 90,
    },
    "eye_strain": {
        "enabled": True,
        "interval_minutes": 20,
        "followup_after_seconds": 20,
    },
    "google_calendar": {
        "enabled": True,
        "credentials_path": str(BASE_DIR / "credentials.json"),
        "notify_before_minutes": 10,
        "meeting_prep_minutes": 30,
        "auto_focus_before_minutes": 20,
        "auto_focus_after_minutes": 10,
        "poll_seconds": 60,
        "max_events": 40,
    },
    "focus_mode": {
        "enabled": False,
        "work_blocklist_apps": ["discord", "steam", "spotify"],
        "work_blocklist_websites": ["youtube.com", "twitter.com", "tiktok.com"],
        "silent_notifications": True,
        "hosts_backup_path": "/etc/hosts.productivity_backup",
    },
    "features": {
        "telegram_inline_panel": True,
        "calendar_auto_focus": False,
        "daily_score": True,
        "quran_goals": True,
        "prayer_recovery_flow": True,
        "weekly_report_push": True,
        "telegram_sensitive_confirm": True,
        "personal_modes": True,
    },
    "security": {
        "require_env_secrets": True,
        "redact_secrets_in_logs": True,
    },
    "personal_modes": {
        "default_mode": "workday",
        "profiles": {
            "workday": {
                "pomodoro.work_minutes": 50,
                "health.water_interval_minutes": 60,
                "health.stretch_interval_minutes": 90,
            },
            "light": {
                "pomodoro.work_minutes": 35,
                "health.water_interval_minutes": 75,
                "health.stretch_interval_minutes": 110,
            },
            "ramadan": {
                "pomodoro.work_minutes": 40,
                "health.water_interval_minutes": 70,
                "health.stretch_interval_minutes": 100,
            },
        },
    },
    "daily_report": {
        "enabled": True,
        "report_time": "23:30",
    },
    "quran_khatma": {
        "enabled": True,
        "mode": "rub",
        "start_rub": 1,
        "start_hizb": 1,
        "start_juz": 1,
        "start_page": 1,
        "start_unit": 1,
        "daily_target_units": 1,
        "restart_on_complete": False,
        "resume_progress": True,
        "force_arabic_reshaper": True,
        "arabic_text_variant": "uthmani",
        "arabic_font_size": 42,
        "show_side_panel": True,
        "side_panel_width": 430,
        "start_fullscreen": True,
        "always_on_top": True,
        "allow_exit": True,
        "client_id": "",
        "client_secret": "",
        "auth_url": "https://oauth2.quran.foundation/oauth2/token",
        "api_base": "https://apis.quran.foundation/content/api/v4",
        "translation_id": "131",
        "tafsir_id": "169",
        "audio_url_template": "https://everyayah.com/data/Alafasy_128kbps/{surah3}{ayah3}.mp3",
        "audio_repeat_default": 1,
    },
    "dashboard": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 5099,
        "auto_open_on_start": True,
        "auto_open_wait_seconds": 2,
        "auto_open_timeout_seconds": 25,
    },
    "tray": {
        "enabled": False,
    },
    "telegram_bot": {
        "enabled": False,
        "token": "",
        "allowed_chat_ids": [],
        "default_focus_minutes": 90,
        "default_snooze_minutes": 15,
        "allow_desktop_observe": True,
        "allow_shell_commands": False,
        "shell_allowlist": [
            "ls",
            "pwd",
            "whoami",
            "date",
            "uptime",
            "df -h",
            "free -h",
            "ps aux",
            "wmctrl -l",
            "xdotool getactivewindow getwindowname",
        ],
        "max_command_output_chars": 3500,
        "allow_power_commands": False,
        "require_allowed_chat_ids_for_control": True,
    },
}

QURAN_MODE_META = {
    "rub": {"count": 240, "endpoints": ["by_rub"]},
    "hizb": {"count": 60, "endpoints": ["by_hizb"]},
    "juz": {"count": 30, "endpoints": ["by_juz"]},
    "page": {"count": 604, "endpoints": ["by_page", "by_page_number"]},
}

SURAH_NAMES = {
    1: "الفاتحة",
    2: "البقرة",
    3: "آل عمران",
    4: "النساء",
    5: "المائدة",
    6: "الأنعام",
    7: "الأعراف",
    8: "الأنفال",
    9: "التوبة",
    10: "يونس",
    11: "هود",
    12: "يوسف",
    13: "الرعد",
    14: "إبراهيم",
    15: "الحجر",
    16: "النحل",
    17: "الإسراء",
    18: "الكهف",
    19: "مريم",
    20: "طه",
    21: "الأنبياء",
    22: "الحج",
    23: "المؤمنون",
    24: "النور",
    25: "الفرقان",
    26: "الشعراء",
    27: "النمل",
    28: "القصص",
    29: "العنكبوت",
    30: "الروم",
    31: "لقمان",
    32: "السجدة",
    33: "الأحزاب",
    34: "سبأ",
    35: "فاطر",
    36: "يس",
    37: "الصافات",
    38: "ص",
    39: "الزمر",
    40: "غافر",
    41: "فصلت",
    42: "الشورى",
    43: "الزخرف",
    44: "الدخان",
    45: "الجاثية",
    46: "الأحقاف",
    47: "محمد",
    48: "الفتح",
    49: "الحجرات",
    50: "ق",
    51: "الذاريات",
    52: "الطور",
    53: "النجم",
    54: "القمر",
    55: "الرحمن",
    56: "الواقعة",
    57: "الحديد",
    58: "المجادلة",
    59: "الحشر",
    60: "الممتحنة",
    61: "الصف",
    62: "الجمعة",
    63: "المنافقون",
    64: "التغابن",
    65: "الطلاق",
    66: "التحريم",
    67: "الملك",
    68: "القلم",
    69: "الحاقة",
    70: "المعارج",
    71: "نوح",
    72: "الجن",
    73: "المزمل",
    74: "المدثر",
    75: "القيامة",
    76: "الإنسان",
    77: "المرسلات",
    78: "النبأ",
    79: "النازعات",
    80: "عبس",
    81: "التكوير",
    82: "الانفطار",
    83: "المطففين",
    84: "الانشقاق",
    85: "البروج",
    86: "الطارق",
    87: "الأعلى",
    88: "الغاشية",
    89: "الفجر",
    90: "البلد",
    91: "الشمس",
    92: "الليل",
    93: "الضحى",
    94: "الشرح",
    95: "التين",
    96: "العلق",
    97: "القدر",
    98: "البينة",
    99: "الزلزلة",
    100: "العاديات",
    101: "القارعة",
    102: "التكاثر",
    103: "العصر",
    104: "الهمزة",
    105: "الفيل",
    106: "قريش",
    107: "الماعون",
    108: "الكوثر",
    109: "الكافرون",
    110: "النصر",
    111: "المسد",
    112: "الإخلاص",
    113: "الفلق",
    114: "الناس",
}

STOP_EVENT = threading.Event()
CONTROL_LOCK = threading.Lock()
RUNTIME_LOCK = threading.Lock()
THREAD_LOCK = threading.Lock()
TOKEN_LOCK = threading.Lock()

CONTROL_STATE: Dict[str, Any] = {
    "pause_until": None,
    "snooze_until": None,
    "focus_override_until": None,
    "feature_toggles": {},
}

THREAD_STATUS: Dict[str, Dict[str, Any]] = {}
RUNTIME_STATE: Dict[str, Any] = {
    "next_prayer": None,
    "last_api_success": {},
    "last_errors": deque(maxlen=40),
}

LOGGER = logging.getLogger("assistant")
APP_CONFIG: Dict[str, Any] = {}
APP_TZ = ZoneInfo("UTC")
HTTP = requests.Session()
DB: Optional["AssistantDB"] = None
APP_STARTED_AT = datetime.now(timezone.utc)
DASHBOARD_BROWSER_OPEN_SCHEDULED = threading.Event()

QURAN_TOKEN_CACHE: Dict[str, Any] = {
    "token": None,
    "expires_at": None,
}

FOCUS_MANAGER: Optional["FocusModeManager"] = None
PLATFORM_ADAPTER = get_platform_adapter()
SENSITIVE_ACTIONS = SensitiveActionStore()
ACTIVE_MODE = "workday"
SECRET_VALUES: List[str] = []


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_mode(mode: str) -> str:
    m = (mode or "rub").strip().lower()
    if m not in QURAN_MODE_META:
        return "rub"
    return m


def now_local() -> datetime:
    return datetime.now(APP_TZ)


def day_key(dt: Optional[datetime] = None) -> str:
    target = dt or now_local()
    return target.strftime("%Y-%m-%d")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_hhmm_today(time_str: str) -> datetime:
    hh, mm = map(int, time_str.split(":"))
    n = now_local()
    return n.replace(hour=hh, minute=mm, second=0, microsecond=0)


def in_trigger_window(now_dt: datetime, target: datetime, window_seconds: int = 30) -> bool:
    return target <= now_dt < target + timedelta(seconds=window_seconds)


def responsive_sleep(seconds: float, granularity: float = 1.0) -> bool:
    end_at = time.time() + max(0.0, seconds)
    while time.time() < end_at:
        if STOP_EVENT.is_set():
            return False
        time.sleep(min(granularity, max(0.0, end_at - time.time())))
    return not STOP_EVENT.is_set()


def register_error(source: str, message: str):
    msg = str(message)
    if APP_CONFIG.get("security", {}).get("redact_secrets_in_logs", True):
        msg = redact_sensitive_text(msg, SECRET_VALUES)
    with RUNTIME_LOCK:
        RUNTIME_STATE["last_errors"].append(
            {
                "ts": utc_now_iso(),
                "source": source,
                "message": msg,
            }
        )


def mark_thread(name: str, status: str, error: str = ""):
    with THREAD_LOCK:
        THREAD_STATUS[name] = {
            "status": status,
            "error": error,
            "updated_at": utc_now_iso(),
        }


def set_next_prayer_runtime(name: Optional[str], at_dt: Optional[datetime]):
    payload = None
    if name and at_dt:
        payload = {
            "name": name,
            "at": at_dt.isoformat(),
        }
    with RUNTIME_LOCK:
        RUNTIME_STATE["next_prayer"] = payload


def set_last_api_success(name: str):
    with RUNTIME_LOCK:
        RUNTIME_STATE["last_api_success"][name] = utc_now_iso()


def is_feature_enabled(feature: str) -> bool:
    with CONTROL_LOCK:
        return CONTROL_STATE["feature_toggles"].get(feature, True)


def set_feature_enabled(feature: str, enabled: bool):
    with CONTROL_LOCK:
        CONTROL_STATE["feature_toggles"][feature] = enabled


def toggle_feature(feature: str) -> bool:
    with CONTROL_LOCK:
        current = CONTROL_STATE["feature_toggles"].get(feature, True)
        CONTROL_STATE["feature_toggles"][feature] = not current
        return not current


def init_feature_toggles(config: Dict[str, Any]):
    fcfg = config.get("features", {})
    initial = {
        "prayers": bool(config.get("prayers", {}).get("enabled", False)),
        "pomodoro": bool(config.get("pomodoro", {}).get("enabled", False)),
        "health": True,
        "eye_strain": bool(config.get("eye_strain", {}).get("enabled", False)),
        "calendar": bool(config.get("google_calendar", {}).get("enabled", False)),
        "focus_mode": bool(config.get("focus_mode", {}).get("enabled", False)),
        "dashboard": bool(config.get("dashboard", {}).get("enabled", False)),
        "telegram": bool(config.get("telegram_bot", {}).get("enabled", False)),
        "daily_score": bool(fcfg.get("daily_score", True)),
        "calendar_auto_focus": bool(fcfg.get("calendar_auto_focus", False)),
        "quran_goals": bool(fcfg.get("quran_goals", True)),
        "prayer_recovery_flow": bool(fcfg.get("prayer_recovery_flow", True)),
        "weekly_report_push": bool(fcfg.get("weekly_report_push", True)),
        "telegram_inline_panel": bool(fcfg.get("telegram_inline_panel", True)),
        "telegram_sensitive_confirm": bool(fcfg.get("telegram_sensitive_confirm", True)),
        "personal_modes": bool(fcfg.get("personal_modes", True)),
    }
    with CONTROL_LOCK:
        CONTROL_STATE["feature_toggles"].update(initial)


def set_pause(minutes: int):
    until = now_local() + timedelta(minutes=max(1, minutes))
    with CONTROL_LOCK:
        CONTROL_STATE["pause_until"] = until
    notify("Control", f"All reminders paused until {until.strftime('%H:%M')}", force=True)


def set_snooze(minutes: int):
    until = now_local() + timedelta(minutes=max(1, minutes))
    with CONTROL_LOCK:
        CONTROL_STATE["snooze_until"] = until
    notify("Control", f"Next reminders snoozed until {until.strftime('%H:%M')}", force=True)


def clear_pause():
    with CONTROL_LOCK:
        CONTROL_STATE["pause_until"] = None


def clear_snooze():
    with CONTROL_LOCK:
        CONTROL_STATE["snooze_until"] = None


def is_notifications_muted(category: str = "general") -> bool:
    if not is_feature_enabled(category):
        return True
    with CONTROL_LOCK:
        pause_until = CONTROL_STATE.get("pause_until")
        snooze_until = CONTROL_STATE.get("snooze_until")
    n = now_local()
    if pause_until and n < pause_until:
        return True
    if snooze_until and n < snooze_until:
        return True
    return False


def notify(
    title: str,
    body: str,
    urgency: str = "normal",
    category: str = "general",
    force: bool = False,
):
    if not force and is_notifications_muted(category):
        LOGGER.info("notification_suppressed", extra={"title": title, "category": category})
        return

    if DB:
        DB.log_event(category, title, body)

    try:
        PLATFORM_ADAPTER.notify(title=title, body=body, urgency=urgency)
    except Exception as exc:
        register_error("notify", str(exc))
        LOGGER.exception("notify_failed")


def big_alert(message: str):
    notify("BIG ALERT", message, urgency="critical", category="general", force=True)


def ask_yes_no(question: str) -> bool:
    try:
        return PLATFORM_ADAPTER.ask_yes_no(question)
    except Exception as exc:
        register_error("ask_yes_no", str(exc))
        LOGGER.exception("ask_yes_no_failed")
    return False


def strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def fix_arabic_text(text: str) -> str:
    if not text:
        return text

    qcfg = APP_CONFIG.get("quran_khatma", {}) if isinstance(APP_CONFIG, dict) else {}
    force_from_config = bool(qcfg.get("force_arabic_reshaper", True))
    force_from_env = os.getenv("ASSISTANT_FORCE_ARABIC_RESHAPER", "0").strip() == "1"
    if not (force_from_config or force_from_env):
        # Optional bypass if your Tk build already renders Arabic correctly.
        return text

    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        # Keep harakat/tashkeel; default arabic_reshaper config removes them.
        reshaper = arabic_reshaper.ArabicReshaper(
            configuration={
                "delete_harakat": False,
                "shift_harakat_position": False,
                "support_ligatures": True,
            }
        )
        reshaped_text = reshaper.reshape(text)
        bidi_text = get_display(reshaped_text, base_dir="R")
        return bidi_text
    except ImportError:
        return text


def to_arabic_digits(value: Any) -> str:
    digits_map = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
    return str(value).translate(digits_map)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if APP_CONFIG.get("security", {}).get("redact_secrets_in_logs", True):
            msg = redact_sensitive_text(msg, SECRET_VALUES)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": msg,
        }
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            payload["exc"] = redact_sensitive_text(exc_text, SECRET_VALUES)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_path: str):
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()

    file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)


def build_http_session(http_cfg: Dict[str, Any]) -> requests.Session:
    retries = int(http_cfg.get("retries", 4))
    backoff_factor = float(http_cfg.get("backoff_factor", 0.7))

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        allowed_methods=frozenset(["GET", "POST"]),
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=backoff_factor,
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def apply_env_overrides(cfg: Dict[str, Any]):
    tz_env = os.getenv("ASSISTANT_TIMEZONE")
    if tz_env:
        cfg["timezone"] = tz_env

    qcfg = cfg.setdefault("quran_khatma", {})
    qcfg["client_id"] = os.getenv("QURAN_CLIENT_ID", qcfg.get("client_id", ""))
    qcfg["client_secret"] = os.getenv("QURAN_CLIENT_SECRET", qcfg.get("client_secret", ""))

    tcfg = cfg.setdefault("telegram_bot", {})
    tcfg["token"] = os.getenv("TELEGRAM_BOT_TOKEN", tcfg.get("token", ""))

    mode_env = os.getenv("ASSISTANT_DEFAULT_MODE")
    if mode_env:
        cfg.setdefault("personal_modes", {})["default_mode"] = mode_env.strip().lower()


def validate_config(cfg: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    try:
        ZoneInfo(cfg.get("timezone", "UTC"))
    except Exception:
        errors.append(f"Invalid timezone: {cfg.get('timezone')}")

    def positive_int(path: str, value: Any):
        if not isinstance(value, int) or value <= 0:
            errors.append(f"{path} must be a positive integer")

    positive_int("workday_limit_hours", cfg.get("workday_limit_hours"))

    positive_int("pomodoro.work_minutes", cfg.get("pomodoro", {}).get("work_minutes"))
    positive_int("pomodoro.short_break_minutes", cfg.get("pomodoro", {}).get("short_break_minutes"))
    positive_int("pomodoro.long_break_minutes", cfg.get("pomodoro", {}).get("long_break_minutes"))

    positive_int("health.water_interval_minutes", cfg.get("health", {}).get("water_interval_minutes"))
    positive_int("health.stretch_interval_minutes", cfg.get("health", {}).get("stretch_interval_minutes"))

    positive_int("eye_strain.interval_minutes", cfg.get("eye_strain", {}).get("interval_minutes"))

    qcfg = cfg.get("quran_khatma", {})
    mode = normalize_mode(qcfg.get("mode", "rub"))
    if mode != qcfg.get("mode", "rub"):
        warnings.append(f"quran_khatma.mode unsupported; using '{mode}'")

    if qcfg.get("enabled") and (not qcfg.get("client_id") or not qcfg.get("client_secret")):
        warnings.append("Quran API credentials are missing. Set QURAN_CLIENT_ID/QURAN_CLIENT_SECRET.")

    gcfg = cfg.get("google_calendar", {})
    if gcfg.get("enabled") and not HAS_GOOGLE:
        warnings.append("Google Calendar enabled but required libraries are not installed.")

    if cfg.get("dashboard", {}).get("enabled") and not HAS_FLASK:
        warnings.append("Dashboard enabled but Flask is not installed.")

    if cfg.get("tray", {}).get("enabled") and not HAS_TRAY:
        warnings.append("Tray enabled but pystray/Pillow are not installed.")

    if cfg.get("telegram_bot", {}).get("enabled") and not HAS_TELEGRAM:
        warnings.append("Telegram bot enabled but python-telegram-bot is not installed.")

    tcfg = cfg.get("telegram_bot", {})
    if tcfg.get("enabled") and tcfg.get("allow_desktop_observe", True):
        has_screenshot_tool = HAS_MSS or HAS_IMAGEGRAB or any(
            shutil.which(x)
            for x in [
                "ffmpeg",
                "gnome-screenshot",
                "scrot",
                "grim",
                "grimshot",
                "spectacle",
                "xfce4-screenshooter",
                "import",
            ]
        )
        if not has_screenshot_tool:
            warnings.append(
                "Telegram screenshot commands enabled but no screenshot backend found "
                "(install mss/Pillow or ffmpeg/gnome-screenshot/scrot/grim/spectacle/imagemagick)."
            )

    if (
        tcfg.get("enabled")
        and tcfg.get("require_allowed_chat_ids_for_control", True)
        and not tcfg.get("allowed_chat_ids")
    ):
        warnings.append(
            "telegram_bot.allowed_chat_ids is empty; control commands will be blocked "
            "until at least one chat id is configured."
        )

    scfg = cfg.get("security", {})
    require_env_secrets = bool(scfg.get("require_env_secrets", True))
    if require_env_secrets and tcfg.get("enabled", False) and not os.getenv("TELEGRAM_BOT_TOKEN"):
        errors.append("security.require_env_secrets=true but TELEGRAM_BOT_TOKEN is not set.")

    if require_env_secrets and qcfg.get("enabled", False):
        if not os.getenv("QURAN_CLIENT_ID"):
            errors.append("security.require_env_secrets=true but QURAN_CLIENT_ID is not set.")
        if not os.getenv("QURAN_CLIENT_SECRET"):
            errors.append("security.require_env_secrets=true but QURAN_CLIENT_SECRET is not set.")

    return errors, warnings


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.json not found at {CONFIG_PATH}")

    env_map = load_dotenv_file(DOTENV_PATH)
    apply_env_map(env_map)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw_cfg = json.load(f)

    merged = deep_merge(DEFAULT_CONFIG, raw_cfg)
    apply_env_overrides(merged)
    global SECRET_VALUES
    SECRET_VALUES = collect_secret_values(merged)
    return merged


class AssistantDB:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _exec(self, sql: str, params: Tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def _query_one(self, sql: str, params: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
        with self.lock:
            cur = self.conn.execute(sql, params)
            return cur.fetchone()

    def _query_all(self, sql: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
        with self.lock:
            cur = self.conn.execute(sql, params)
            return cur.fetchall()

    def _init_schema(self):
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    day TEXT PRIMARY KEY,
                    pomodoro_sessions INTEGER DEFAULT 0,
                    total_focus_minutes INTEGER DEFAULT 0,
                    water_reminders INTEGER DEFAULT 0,
                    stretch_reminders INTEGER DEFAULT 0,
                    eye_breaks INTEGER DEFAULT 0,
                    prayers_planned INTEGER DEFAULT 0,
                    prayers_prayed INTEGER DEFAULT 0,
                    prayers_missed INTEGER DEFAULT 0,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS prayer_log (
                    day TEXT,
                    prayer_name TEXT,
                    status TEXT,
                    context TEXT,
                    ts TEXT,
                    PRIMARY KEY(day, prayer_name)
                );

                CREATE TABLE IF NOT EXISTS quran_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT
                );

                CREATE TABLE IF NOT EXISTS quran_notes (
                    verse_key TEXT PRIMARY KEY,
                    note TEXT DEFAULT '',
                    bookmarked INTEGER DEFAULT 0,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS app_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT,
                    category TEXT,
                    title TEXT,
                    body TEXT
                );

                CREATE TABLE IF NOT EXISTS calendar_sync (
                    sync_key TEXT PRIMARY KEY,
                    sync_value TEXT
                );
                """
            )
            apply_v2_migrations(self.conn)
            self.conn.commit()

    def ensure_day(self, day: Optional[str] = None):
        d = day or day_key()
        self._exec(
            """
            INSERT INTO daily_metrics(day, updated_at)
            VALUES(?, ?)
            ON CONFLICT(day) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (d, utc_now_iso()),
        )

    def increment_metric(self, field: str, amount: int = 1, day: Optional[str] = None):
        allowed = {
            "pomodoro_sessions",
            "total_focus_minutes",
            "water_reminders",
            "stretch_reminders",
            "eye_breaks",
            "prayers_planned",
            "prayers_prayed",
            "prayers_missed",
        }
        if field not in allowed:
            raise ValueError(f"Unsupported metric field: {field}")

        d = day or day_key()
        self.ensure_day(d)
        self._exec(
            f"UPDATE daily_metrics SET {field}=COALESCE({field},0)+?, updated_at=? WHERE day=?",
            (amount, utc_now_iso(), d),
        )

    def set_prayers_planned(self, day: str, planned: int):
        self.ensure_day(day)
        self._exec(
            "UPDATE daily_metrics SET prayers_planned=?, updated_at=? WHERE day=?",
            (planned, utc_now_iso(), day),
        )

    def upsert_prayer_status(self, day: str, prayer_name: str, status: str, context: str):
        self._exec(
            """
            INSERT INTO prayer_log(day, prayer_name, status, context, ts)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(day, prayer_name)
            DO UPDATE SET status=excluded.status, context=excluded.context, ts=excluded.ts
            """,
            (day, prayer_name, status, context, utc_now_iso()),
        )
        self.rebuild_prayer_counts(day)

    def rebuild_prayer_counts(self, day: str):
        self.ensure_day(day)
        row = self._query_one(
            """
            SELECT
                SUM(CASE WHEN status='prayed' THEN 1 ELSE 0 END) AS prayed,
                SUM(CASE WHEN status='missed' THEN 1 ELSE 0 END) AS missed
            FROM prayer_log
            WHERE day=?
            """,
            (day,),
        )
        prayed = int((row["prayed"] if row and row["prayed"] is not None else 0))
        missed = int((row["missed"] if row and row["missed"] is not None else 0))
        self._exec(
            "UPDATE daily_metrics SET prayers_prayed=?, prayers_missed=?, updated_at=? WHERE day=?",
            (prayed, missed, utc_now_iso(), day),
        )

    def get_day_metrics(self, day: Optional[str] = None) -> Dict[str, Any]:
        d = day or day_key()
        self.ensure_day(d)
        row = self._query_one("SELECT * FROM daily_metrics WHERE day=?", (d,))
        return dict(row) if row else {}

    def get_week_compliance(self, days: int = 7) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        today = now_local().date()
        for i in range(days - 1, -1, -1):
            dt = today - timedelta(days=i)
            dkey = dt.strftime("%Y-%m-%d")
            row = self._query_one("SELECT * FROM daily_metrics WHERE day=?", (dkey,))
            if not row:
                result.append({"day": dkey, "planned": 0, "prayed": 0, "missed": 0})
                continue
            result.append(
                {
                    "day": dkey,
                    "planned": int(row["prayers_planned"] or 0),
                    "prayed": int(row["prayers_prayed"] or 0),
                    "missed": int(row["prayers_missed"] or 0),
                }
            )
        return result

    def get_prayer_streak(self) -> int:
        rows = self._query_all(
            """
            SELECT day, prayers_planned, prayers_prayed, prayers_missed
            FROM daily_metrics
            WHERE prayers_planned > 0
            ORDER BY day DESC
            LIMIT 365
            """
        )
        streak = 0
        for row in rows:
            planned = int(row["prayers_planned"] or 0)
            prayed = int(row["prayers_prayed"] or 0)
            missed = int(row["prayers_missed"] or 0)
            if planned > 0 and prayed >= planned and missed == 0:
                streak += 1
            else:
                break
        return streak

    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._query_one("SELECT state_value FROM quran_state WHERE state_key=?", (key,))
        if not row:
            return default
        return row["state_value"]

    def set_state(self, key: str, value: str):
        self._exec(
            """
            INSERT INTO quran_state(state_key, state_value)
            VALUES(?, ?)
            ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value
            """,
            (key, value),
        )

    def get_quran_note(self, verse_key: str) -> Tuple[str, bool]:
        row = self._query_one("SELECT note, bookmarked FROM quran_notes WHERE verse_key=?", (verse_key,))
        if not row:
            return "", False
        return row["note"] or "", bool(row["bookmarked"])

    def save_quran_note(self, verse_key: str, note: str, bookmarked: bool):
        self._exec(
            """
            INSERT INTO quran_notes(verse_key, note, bookmarked, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(verse_key)
            DO UPDATE SET note=excluded.note, bookmarked=excluded.bookmarked, updated_at=excluded.updated_at
            """,
            (verse_key, note, int(bookmarked), utc_now_iso()),
        )

    def list_bookmarks(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self._query_all(
            """
            SELECT verse_key, note, bookmarked, updated_at
            FROM quran_notes
            WHERE bookmarked = 1
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in rows]

    def log_event(self, category: str, title: str, body: str):
        self._exec(
            "INSERT INTO app_events(ts, category, title, body) VALUES(?, ?, ?, ?)",
            (utc_now_iso(), category, title, body),
        )

    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._query_all(
            "SELECT ts, category, title, body FROM app_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def get_sync_token(self, key: str) -> Optional[str]:
        row = self._query_one("SELECT sync_value FROM calendar_sync WHERE sync_key=?", (key,))
        if not row:
            return None
        return row["sync_value"]

    def set_sync_token(self, key: str, value: str):
        self._exec(
            """
            INSERT INTO calendar_sync(sync_key, sync_value)
            VALUES(?, ?)
            ON CONFLICT(sync_key) DO UPDATE SET sync_value=excluded.sync_value
            """,
            (key, value),
        )

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._query_one("SELECT value FROM app_settings WHERE key=?", (key,))
        if not row:
            return default
        return row["value"]

    def set_setting(self, key: str, value: str):
        self._exec(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, utc_now_iso()),
        )

    def is_weekly_report_sent(self, week_key: str) -> bool:
        row = self._query_one("SELECT week_key FROM weekly_report_log WHERE week_key=?", (week_key,))
        return bool(row)

    def mark_weekly_report_sent(self, week_key: str, payload: str):
        self._exec(
            """
            INSERT INTO weekly_report_log(week_key, sent_at, payload)
            VALUES(?, ?, ?)
            ON CONFLICT(week_key) DO UPDATE SET sent_at=excluded.sent_at, payload=excluded.payload
            """,
            (week_key, utc_now_iso(), payload),
        )

    def close(self):
        with self.lock:
            self.conn.close()


def build_compliance_chart_lines(week_rows: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for row in week_rows:
        planned = int(row.get("planned", 0))
        prayed = int(row.get("prayed", 0))
        ratio = 0.0 if planned == 0 else prayed / planned
        filled = int(round(ratio * 10))
        bar = "█" * filled + "░" * (10 - filled)
        lines.append(f"{row['day']} [{bar}] {prayed}/{planned}")
    return lines


def current_mode() -> str:
    if DB:
        stored = DB.get_setting("active_mode")
        if stored:
            return stored
    return APP_CONFIG.get("personal_modes", {}).get("default_mode", "workday")


def set_mode(mode: str) -> bool:
    m = (mode or "").strip().lower()
    profiles = APP_CONFIG.get("personal_modes", {}).get("profiles", {})
    if m not in profiles:
        return False

    profile = profiles.get(m, {})
    if "pomodoro.work_minutes" in profile:
        APP_CONFIG.setdefault("pomodoro", {})["work_minutes"] = int(profile["pomodoro.work_minutes"])
    if "health.water_interval_minutes" in profile:
        APP_CONFIG.setdefault("health", {})["water_interval_minutes"] = int(profile["health.water_interval_minutes"])
    if "health.stretch_interval_minutes" in profile:
        APP_CONFIG.setdefault("health", {})["stretch_interval_minutes"] = int(profile["health.stretch_interval_minutes"])
    if DB:
        DB.set_setting("active_mode", m)
    global ACTIVE_MODE
    ACTIVE_MODE = m
    return True


def get_quran_daily_goal() -> int:
    default_goal = int(APP_CONFIG.get("quran_khatma", {}).get("daily_target_units", 1))
    if not DB:
        return max(1, default_goal)
    val = DB.get_setting("quran_daily_goal")
    if val is None:
        return max(1, default_goal)
    try:
        return max(1, int(val))
    except Exception:
        return max(1, default_goal)


def set_quran_daily_goal(units: int) -> int:
    value = max(1, min(60, int(units)))
    if DB:
        DB.set_setting("quran_daily_goal", str(value))
    APP_CONFIG.setdefault("quran_khatma", {})["daily_target_units"] = value
    return value


def get_quran_daily_progress(mode: str) -> Dict[str, int]:
    goal = get_quran_daily_goal()
    if not DB:
        return {"goal": goal, "done": 0}
    today = day_key()
    marker = DB.get_setting(f"quran_progress_marker:{today}:{mode}")
    if marker is None:
        return {"goal": goal, "done": 0}
    try:
        done = max(0, int(marker))
    except Exception:
        done = 0
    return {"goal": goal, "done": done}


def set_quran_daily_progress(mode: str, done: int):
    if DB:
        DB.set_setting(f"quran_progress_marker:{day_key()}:{mode}", str(max(0, done)))


def compute_daily_score_payload(metrics: Dict[str, Any], streak: int) -> Dict[str, Any]:
    score = calculate_daily_score(metrics, streak)
    return {
        "total": score.total,
        "focus": score.focus,
        "prayers": score.prayers,
        "health": score.health,
        "consistency": score.consistency,
        "text": format_score_text(score),
    }


def runtime_snapshot() -> Dict[str, Any]:
    today_metrics = DB.get_day_metrics(day_key()) if DB else {}
    week = DB.get_week_compliance(7) if DB else []
    chart = build_compliance_chart_lines(week)
    streak = DB.get_prayer_streak() if DB else 0
    daily_score = compute_daily_score_payload(today_metrics, streak)
    bookmarks = DB.list_bookmarks(limit=8) if DB else []
    recent_events = DB.get_recent_events(limit=25) if DB else []
    qcfg = APP_CONFIG.get("quran_khatma", {}) if isinstance(APP_CONFIG, dict) else {}
    quran_mode = normalize_mode(qcfg.get("mode", "rub"))
    quran_start_key = f"start_{quran_mode}"
    try:
        quran_current_unit = int(qcfg.get(quran_start_key, qcfg.get("start_unit", 1)))
    except Exception:
        quran_current_unit = 1
    if DB:
        quran_state_val = DB.get_state(f"quran_{quran_mode}_current")
        if quran_state_val is not None:
            try:
                quran_current_unit = int(quran_state_val)
            except Exception:
                pass
    quran_current_unit = max(1, min(int(QURAN_MODE_META[quran_mode]["count"]), quran_current_unit))
    quran_goal = get_quran_daily_goal()
    quran_progress = get_quran_daily_progress(quran_mode)

    with CONTROL_LOCK:
        pause_until = CONTROL_STATE.get("pause_until")
        snooze_until = CONTROL_STATE.get("snooze_until")
        focus_override_until = CONTROL_STATE.get("focus_override_until")
        toggles = dict(CONTROL_STATE.get("feature_toggles", {}))

    with THREAD_LOCK:
        threads = dict(THREAD_STATUS)

    with RUNTIME_LOCK:
        next_prayer = RUNTIME_STATE.get("next_prayer")
        last_api_success = dict(RUNTIME_STATE.get("last_api_success", {}))
        last_errors = list(RUNTIME_STATE.get("last_errors", []))

    return {
        "now": now_local().isoformat(),
        "uptime_seconds": int((datetime.now(timezone.utc) - APP_STARTED_AT).total_seconds()),
        "pause_until": pause_until.isoformat() if pause_until else None,
        "snooze_until": snooze_until.isoformat() if snooze_until else None,
        "focus_override_until": focus_override_until.isoformat() if focus_override_until else None,
        "focus_mode_active": bool(FOCUS_MANAGER and FOCUS_MANAGER.active),
        "feature_toggles": toggles,
        "threads": threads,
        "today_metrics": today_metrics,
        "prayer_streak": streak,
        "daily_score": daily_score,
        "weekly_compliance": week,
        "weekly_compliance_chart": chart,
        "next_prayer": next_prayer,
        "last_api_success": last_api_success,
        "last_errors": last_errors,
        "bookmarks": bookmarks,
        "recent_events": recent_events,
        "quran_mode": quran_mode,
        "quran_current_unit": quran_current_unit,
        "quran_daily_goal": quran_goal,
        "quran_daily_progress": quran_progress,
        "active_mode": current_mode(),
        "capabilities": PLATFORM_ADAPTER.capabilities(),
        "quran_resume_progress": bool(qcfg.get("resume_progress", True)),
    }


def format_snapshot_text(snap: Dict[str, Any]) -> str:
    metrics = snap.get("today_metrics", {})
    score = snap.get("daily_score", {})
    lines = [
        f"Now: {snap.get('now')}",
        f"Next prayer: {snap.get('next_prayer')}",
        f"Prayer streak: {snap.get('prayer_streak')} days",
        f"Daily score: {score.get('total', 0)}/100",
        f"Pomodoro sessions: {metrics.get('pomodoro_sessions', 0)}",
        f"Focus minutes: {metrics.get('total_focus_minutes', 0)}",
        f"Water reminders: {metrics.get('water_reminders', 0)}",
        f"Stretch reminders: {metrics.get('stretch_reminders', 0)}",
        f"Eye breaks: {metrics.get('eye_breaks', 0)}",
        f"Prayers: {metrics.get('prayers_prayed', 0)}/{metrics.get('prayers_planned', 0)}",
        f"Quran daily goal: {snap.get('quran_daily_progress', {}).get('done', 0)}/{snap.get('quran_daily_goal', 1)}",
        f"Mode: {snap.get('active_mode', 'workday')}",
    ]
    return "\n".join(lines)


def build_weekly_summary_text() -> str:
    if not DB:
        return "No database available."
    rows = DB.get_week_compliance(7)
    chart = build_compliance_chart_lines(rows)
    today_metrics = DB.get_day_metrics(day_key())
    streak = DB.get_prayer_streak()
    score = compute_daily_score_payload(today_metrics, streak)
    lines = [
        f"Weekly summary ({day_key()}):",
        f"- Streak: {streak} days",
        f"- Daily score now: {score.get('total', 0)}/100",
        "",
        "Compliance:",
    ]
    lines.extend(chart)
    return "\n".join(lines)


def format_duration_short(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def print_status_cli():
    snap = runtime_snapshot()
    print(format_snapshot_text(snap))
    print("\nWeekly compliance:")
    for line in snap.get("weekly_compliance_chart", []):
        print(f"  {line}")


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def safe_subprocess_env() -> Dict[str, str]:
    """
    Remove SNAP runtime variables for child processes.
    This avoids GLIBC symbol clashes when running from VSCode Snap sessions.
    """
    env = dict(os.environ)

    # Prefer host user home when running from SNAP-packaged apps.
    real_home = env.get("SNAP_REAL_HOME")
    if real_home:
        env["HOME"] = real_home

    # Restore pre-snap data dirs when VSCode exposes them.
    if env.get("XDG_DATA_DIRS_VSCODE_SNAP_ORIG"):
        env["XDG_DATA_DIRS"] = env["XDG_DATA_DIRS_VSCODE_SNAP_ORIG"]

    to_drop = set()
    for key in list(env.keys()):
        if key == "SNAP" or key.startswith("SNAP_"):
            to_drop.add(key)

    # These vars often point to SNAP-specific GTK/GDK modules and break host binaries.
    to_drop.update(
        {
            "SNAP_LIBRARY_PATH",
            "SNAP_COOKIE",
            "GTK_EXE_PREFIX",
            "GTK_PATH",
            "GDK_PIXBUF_MODULEDIR",
            "GDK_PIXBUF_MODULE_FILE",
            "GIO_MODULE_DIR",
            "GSETTINGS_SCHEMA_DIR",
            "GTK_IM_MODULE_FILE",
            "LOCPATH",
            "XDG_DATA_HOME",
            "PYTHONHOME",
            "PYTHONPATH",
        }
    )

    for key in to_drop:
        env.pop(key, None)
    return env


def run_command_capture(command: List[str], timeout: int = 20) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=safe_subprocess_env(),
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"Timed out after {timeout}s"
    except FileNotFoundError:
        return 127, "", f"Command not found: {command[0]}"
    except Exception as exc:
        return 1, "", str(exc)


def parse_int_arg(value: Optional[str], default: int, min_value: int = 1, max_value: int = 10_000) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def normalize_local_dashboard_host(host: str) -> str:
    h = (host or "127.0.0.1").strip()
    if h in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return h


def schedule_dashboard_browser_open(config: Dict[str, Any], reason: str = "startup"):
    dcfg = config.get("dashboard", {})
    if not dcfg.get("enabled", False):
        return
    if not bool(dcfg.get("auto_open_on_start", True)):
        return
    if DASHBOARD_BROWSER_OPEN_SCHEDULED.is_set():
        return

    DASHBOARD_BROWSER_OPEN_SCHEDULED.set()
    host = normalize_local_dashboard_host(str(dcfg.get("host", "127.0.0.1")))
    port = parse_int_arg(str(dcfg.get("port", "5099")), default=5099, min_value=1, max_value=65535)
    wait_seconds = parse_int_arg(
        str(dcfg.get("auto_open_wait_seconds", "2")),
        default=2,
        min_value=0,
        max_value=60,
    )
    timeout_seconds = parse_int_arg(
        str(dcfg.get("auto_open_timeout_seconds", "25")),
        default=25,
        min_value=4,
        max_value=180,
    )
    base_url = f"http://{host}:{port}"
    ping_url = f"{base_url}/api/status"

    def _worker():
        if wait_seconds:
            time.sleep(wait_seconds)

        deadline = time.time() + timeout_seconds
        while time.time() < deadline and not STOP_EVENT.is_set():
            try:
                resp = requests.get(ping_url, timeout=1.8)
                if resp.status_code < 500:
                    break
            except Exception:
                pass
            time.sleep(0.8)

        try:
            opened = webbrowser.open(base_url, new=2, autoraise=True)
            if opened:
                LOGGER.info("dashboard_auto_opened", extra={"url": base_url, "reason": reason})
            else:
                LOGGER.warning("dashboard_auto_open_no_browser_handler: %s", base_url)
        except Exception as exc:
            register_error("dashboard_auto_open", str(exc))

    t = threading.Thread(target=_worker, name="DashboardAutoOpen", daemon=True)
    t.start()


def command_is_allowlisted(raw_command: str, allowlist: List[str]) -> bool:
    try:
        tokens = shlex.split(raw_command)
    except Exception:
        return False

    if not tokens:
        return False

    for allowed in allowlist:
        try:
            allowed_tokens = shlex.split(str(allowed))
        except Exception:
            continue
        if not allowed_tokens:
            continue
        if tokens[: len(allowed_tokens)] == allowed_tokens:
            return True
    return False


def run_allowlisted_shell_command(raw_command: str, tcfg: Dict[str, Any]) -> Tuple[bool, str]:
    if not tcfg.get("allow_shell_commands", False):
        return False, "Shell commands are disabled in config."

    allowlist = [str(x).strip() for x in tcfg.get("shell_allowlist", []) if str(x).strip()]
    if not allowlist:
        return False, "No shell allowlist configured."

    if not command_is_allowlisted(raw_command, allowlist):
        return False, "Command is not allowlisted."

    try:
        tokens = shlex.split(raw_command)
    except Exception as exc:
        return False, f"Could not parse command: {exc}"

    timeout = parse_int_arg(str(tcfg.get("command_timeout_seconds", 25)), default=25, min_value=5, max_value=180)
    rc, out, err = run_command_capture(tokens, timeout=timeout)
    max_chars = parse_int_arg(
        str(tcfg.get("max_command_output_chars", 3500)),
        default=3500,
        min_value=300,
        max_value=20_000,
    )

    body = f"$ {' '.join(tokens)}\nexit_code={rc}"
    if out:
        body += f"\n\nstdout:\n{truncate_text(out, max_chars)}"
    if err:
        body += f"\n\nstderr:\n{truncate_text(err, max_chars)}"
    return True, body


def list_open_windows(limit: int = 25) -> List[str]:
    try:
        return PLATFORM_ADAPTER.list_open_windows(limit=max(1, limit))
    except Exception as exc:
        register_error("windows_list", str(exc))
        return []


def list_browser_tab_like_titles(limit: int = 20) -> List[str]:
    markers = ("firefox", "chrome", "chromium", "brave", "opera", "vivaldi", "edge")
    windows = list_open_windows(limit=200)
    browser_rows = [w for w in windows if any(marker in w.lower() for marker in markers)]
    return browser_rows[: max(1, limit)]


def get_active_window_title() -> str:
    try:
        return PLATFORM_ADAPTER.get_active_window_title()
    except Exception as exc:
        register_error("active_window", str(exc))
        return "Active window not available."


def guess_x11_screen_size(default_size: str = "1920x1080") -> str:
    if shutil.which("xdpyinfo"):
        rc, out, _ = run_command_capture(["xdpyinfo"], timeout=8)
        if rc == 0 and out:
            match = re.search(r"dimensions:\s+(\d+x\d+)\s+pixels", out)
            if match:
                return match.group(1)
    return default_size


def screenshot_is_mostly_black(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return True
    try:
        from PIL import Image, ImageStat

        with Image.open(path) as img:
            sample = img.convert("L")
            sample.thumbnail((320, 320))
            stat = ImageStat.Stat(sample)
            mean = float(stat.mean[0]) if stat.mean else 0.0
            extrema = sample.getextrema()
            min_px = float(extrema[0]) if extrema else 0.0
            max_px = float(extrema[1]) if extrema else 0.0
            if max_px <= 5:
                return True
            if mean <= 8 and (max_px - min_px) <= 20:
                return True
            return False
    except Exception:
        # If Pillow analysis is unavailable, do not classify as black.
        return False


def capture_screenshot(path: Path) -> Tuple[bool, str]:
    try:
        return PLATFORM_ADAPTER.capture_screenshot(path)
    except Exception as exc:
        register_error("screenshot", str(exc))
        return False, str(exc)


def execute_lock_screen() -> Tuple[bool, str]:
    try:
        return PLATFORM_ADAPTER.lock_screen()
    except Exception as exc:
        register_error("lock_screen", str(exc))
        return False, str(exc)


def execute_suspend() -> Tuple[bool, str]:
    try:
        return PLATFORM_ADAPTER.suspend()
    except Exception as exc:
        register_error("suspend", str(exc))
        return False, str(exc)


def execute_power_action(action: str, value: Optional[str]) -> Tuple[bool, str]:
    try:
        return PLATFORM_ADAPTER.power_action(action, value)
    except Exception as exc:
        register_error("power_action", str(exc))
        return False, str(exc)


def get_top_processes(limit: int = 10) -> str:
    limit = max(1, min(40, limit))
    if platform.system().lower() == "windows":
        rc, out, err = run_command_capture(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {limit} Id,ProcessName,CPU,PM",
            ],
            timeout=12,
        )
    else:
        rc, out, err = run_command_capture(
            ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"],
            timeout=12,
        )
    if rc != 0:
        return err or "Failed to query processes."
    lines = out.splitlines()
    header = lines[0] if lines else "PID COMMAND %CPU %MEM"
    top = lines[1 : 1 + limit]
    return "\n".join([header] + top)


class FocusModeManager:
    BLOCK_START = "# assistant-focus-mode START"
    BLOCK_END = "# assistant-focus-mode END"

    def __init__(self):
        self.lock = threading.Lock()
        self.active = False
        self.dnd_changed = False

    def apply(self, config: Dict[str, Any]):
        with self.lock:
            if self.active:
                return

            fcfg = config.get("focus_mode", {})
            websites = fcfg.get("work_blocklist_websites", [])
            backup_path = fcfg.get("hosts_backup_path", "/etc/hosts.productivity_backup")

            if websites:
                ok, msg = PLATFORM_ADAPTER.apply_focus_web_block(websites, backup_path)
                if not ok:
                    register_error("focus_mode", msg)
                    LOGGER.warning("focus_apply_hosts_failed: %s", msg)

            if fcfg.get("silent_notifications", True):
                try:
                    if platform.system().lower() == "linux":
                        subprocess.run(
                            [
                                "gsettings",
                                "set",
                                "org.gnome.desktop.notifications",
                                "show-banners",
                                "false",
                            ],
                            check=False,
                        )
                        self.dnd_changed = True
                except Exception as exc:
                    register_error("focus_mode", str(exc))
                    LOGGER.warning("Could not toggle GNOME notifications")

            self.active = True
            notify("Focus Mode", "وضع التركيز مفعّل", category="focus_mode", force=True)

    def revert(self, config: Dict[str, Any]):
        with self.lock:
            if not self.active:
                return

            fcfg = config.get("focus_mode", {})
            backup_path = fcfg.get("hosts_backup_path", "/etc/hosts.productivity_backup")

            ok, msg = PLATFORM_ADAPTER.revert_focus_web_block(backup_path)
            if not ok:
                register_error("focus_mode", msg)
                LOGGER.warning("focus_revert_hosts_failed: %s", msg)

            if self.dnd_changed:
                try:
                    if platform.system().lower() == "linux":
                        subprocess.run(
                            [
                                "gsettings",
                                "set",
                                "org.gnome.desktop.notifications",
                                "show-banners",
                                "true",
                            ],
                            check=False,
                        )
                except Exception:
                    pass

            self.active = False
            self.dnd_changed = False
            notify("Focus Mode", "وضع التركيز اتقفل", category="focus_mode", force=True)


def enable_focus_mode(minutes: Optional[int] = None):
    if not FOCUS_MANAGER:
        return
    FOCUS_MANAGER.apply(APP_CONFIG)
    if minutes:
        with CONTROL_LOCK:
            CONTROL_STATE["focus_override_until"] = now_local() + timedelta(minutes=minutes)


def disable_focus_mode():
    if not FOCUS_MANAGER:
        return
    FOCUS_MANAGER.revert(APP_CONFIG)
    with CONTROL_LOCK:
        CONTROL_STATE["focus_override_until"] = None


def check_focus_override_timeout():
    with CONTROL_LOCK:
        until = CONTROL_STATE.get("focus_override_until")
    if until and now_local() >= until:
        disable_focus_mode()


def fetch_prayer_times(city: str, country: str, method: int = 5) -> Tuple[Optional[Dict[str, str]], Dict[str, Any]]:
    try:
        timeout = int(APP_CONFIG.get("http", {}).get("timeout_seconds", 15))
        params = {
            "city": city,
            "country": country,
            "method": method,
        }
        resp = HTTP.get("https://api.aladhan.com/v1/timingsByCity", params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        timings = data["data"]["timings"]

        wanted = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
        out: Dict[str, str] = {}
        for key in wanted:
            raw = timings.get(key, "")
            hhmm = raw.split(" ")[0][:5]
            out[key.lower()] = hhmm

        hijri_month = int(data["data"]["date"]["hijri"]["month"]["number"])
        set_last_api_success("aladhan_prayer")
        return out, {"hijri_month": hijri_month}
    except Exception as exc:
        register_error("prayer_api", str(exc))
        LOGGER.exception("fetch_prayer_times_failed")
        return None, {}


def get_google_service(credentials_path: str):
    if not HAS_GOOGLE:
        LOGGER.warning("Google libraries are not installed")
        return None

    creds = None
    if GOOGLE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                if GOOGLE_TOKEN_PATH.exists():
                    GOOGLE_TOKEN_PATH.unlink()
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    try:
        return build("calendar", "v3", credentials=creds)
    except Exception as exc:
        register_error("google_service", str(exc))
        LOGGER.exception("google_service_build_failed")
        return None


def migrate_legacy_quran_state(db: AssistantDB):
    if not LEGACY_QURAN_STATE_PATH.exists():
        return

    if db.get_state("quran_rub_current") is not None:
        return

    try:
        raw = json.loads(LEGACY_QURAN_STATE_PATH.read_text(encoding="utf-8"))
        current_rub = int(raw.get("current_rub") or 1)
        db.set_state("quran_rub_current", str(current_rub))
        LOGGER.info("Migrated legacy quran_state.json to SQLite")
    except Exception as exc:
        register_error("quran_migration", str(exc))


def get_quran_current_unit(mode: str, config: Dict[str, Any], db: AssistantDB) -> int:
    m = normalize_mode(mode)
    key = f"quran_{m}_current"
    qcfg = config.get("quran_khatma", {})
    start_key = f"start_{m}"
    start = int(qcfg.get(start_key, qcfg.get("start_unit", 1)))
    resume_progress = bool(qcfg.get("resume_progress", True))

    if resume_progress:
        val = db.get_state(key)
        val_int = int(val) if val is not None else start
    else:
        val_int = start

    max_count = QURAN_MODE_META[m]["count"]
    val_int = max(1, min(max_count, val_int))
    db.set_state(key, str(val_int))
    return val_int


def set_quran_current_unit(mode: str, unit: int, db: AssistantDB):
    m = normalize_mode(mode)
    max_count = QURAN_MODE_META[m]["count"]
    final_unit = max(1, min(max_count, unit))
    db.set_state(f"quran_{m}_current", str(final_unit))


def quran_get_access_token(config: Dict[str, Any]) -> str:
    qcfg = config.get("quran_khatma", {})
    url = qcfg.get("auth_url")
    client_id = qcfg.get("client_id")
    client_secret = qcfg.get("client_secret")

    if not url or not client_id or not client_secret:
        raise RuntimeError("Quran OAuth2 config missing (auth_url / client_id / client_secret)")

    with TOKEN_LOCK:
        token = QURAN_TOKEN_CACHE.get("token")
        expires_at = QURAN_TOKEN_CACHE.get("expires_at")
        if token and expires_at and now_local() < expires_at - timedelta(seconds=60):
            return token

    timeout = int(APP_CONFIG.get("http", {}).get("timeout_seconds", 15))
    resp = HTTP.post(
        url,
        data={"grant_type": "client_credentials", "scope": "content"},
        auth=(client_id, client_secret),
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 3600))

    if not token:
        raise RuntimeError(f"No access token in response: {payload}")

    with TOKEN_LOCK:
        QURAN_TOKEN_CACHE["token"] = token
        QURAN_TOKEN_CACHE["expires_at"] = now_local() + timedelta(seconds=expires_in)

    set_last_api_success("quran_auth")
    return token


def fetch_quran_segment(unit: int, mode: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    qcfg = config.get("quran_khatma", {})
    api_base = qcfg.get("api_base")
    client_id = qcfg.get("client_id")
    translation_id = qcfg.get("translation_id")
    tafsir_id = qcfg.get("tafsir_id")
    arabic_variant = str(qcfg.get("arabic_text_variant", "uthmani")).strip().lower()

    if not api_base or not client_id:
        raise RuntimeError("Missing quran_khatma.api_base or quran_khatma.client_id")

    token = quran_get_access_token(config)
    headers = {
        "Accept": "application/json",
        "x-auth-token": token,
        "x-client-id": client_id,
    }

    params: Dict[str, Any] = {
        "language": "ar",
        "words": "false",
        "per_page": 300,
        "fields": "text_uthmani,text_indopak,text_imlaei",
    }
    if translation_id:
        params["translations"] = translation_id
    if tafsir_id:
        params["tafsirs"] = tafsir_id

    m = normalize_mode(mode)
    endpoints = QURAN_MODE_META[m]["endpoints"]
    timeout = int(APP_CONFIG.get("http", {}).get("timeout_seconds", 15))

    response_payload: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None

    for endpoint in endpoints:
        url = f"{api_base}/verses/{endpoint}/{unit}"
        try:
            resp = HTTP.get(url, headers=headers, params=params, timeout=timeout)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            response_payload = resp.json()
            break
        except Exception as exc:
            last_error = exc
            continue

    if response_payload is None:
        raise RuntimeError(f"Failed to fetch Quran segment for mode={m}, unit={unit}: {last_error}")

    verses = response_payload.get("verses")
    if verses is None and isinstance(response_payload.get("data"), dict):
        verses = response_payload["data"].get("verses")

    if not verses:
        raise RuntimeError(f"No verses returned for mode={m}, unit={unit}")

    result: List[Dict[str, Any]] = []
    field_priority = {
        "uthmani": ["text_uthmani", "text_indopak", "text_imlaei"],
        "indopak": ["text_indopak", "text_uthmani", "text_imlaei"],
        "imlaei": ["text_imlaei", "text_uthmani", "text_indopak"],
    }
    preferred_fields = field_priority.get(arabic_variant, field_priority["uthmani"])

    for verse in verses:
        text = ""
        for field_name in preferred_fields:
            candidate = verse.get(field_name)
            if candidate:
                text = candidate
                break
        if not text:
            continue

        key = verse.get("verse_key", "0:0")
        parts = key.split(":")
        surah = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
        ayah = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

        translation = ""
        tafsir = ""

        translations = verse.get("translations")
        if isinstance(translations, list) and translations:
            translation = strip_html(translations[0].get("text", ""))

        tafsirs = verse.get("tafsirs")
        if isinstance(tafsirs, list) and tafsirs:
            tafsir = strip_html(tafsirs[0].get("text", ""))

        result.append(
            {
                "key": key,
                "surah": surah,
                "ayah": ayah,
                "text": text,
                "translation": translation,
                "tafsir": tafsir,
            }
        )

    set_last_api_success("quran_content")
    return result


def build_audio_url(verse: Dict[str, Any], config: Dict[str, Any]) -> str:
    qcfg = config.get("quran_khatma", {})
    template = qcfg.get(
        "audio_url_template",
        "https://everyayah.com/data/Alafasy_128kbps/{surah3}{ayah3}.mp3",
    )
    surah = int(verse.get("surah", 0))
    ayah = int(verse.get("ayah", 0))
    return template.format(
        surah=surah,
        ayah=ayah,
        surah3=f"{surah:03d}",
        ayah3=f"{ayah:03d}",
        key=verse.get("key", "0:0"),
    )


def find_audio_player() -> Optional[str]:
    for bin_name in ["mpv", "ffplay", "cvlc"]:
        if shutil.which(bin_name):
            return bin_name
    return None


def play_audio_url(url: str, stop_event: threading.Event):
    player = find_audio_player()
    if not player:
        notify("Quran Audio", "No audio player found (mpv/ffplay/cvlc).", category="quran")
        return

    if player == "mpv":
        cmd = ["mpv", "--no-video", "--really-quiet", url]
    elif player == "ffplay":
        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", url]
    else:
        cmd = ["cvlc", "--play-and-exit", "--quiet", url]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=safe_subprocess_env(),
        )
        while proc.poll() is None:
            if STOP_EVENT.is_set() or stop_event.is_set():
                proc.terminate()
                break
            time.sleep(0.1)
    except Exception as exc:
        register_error("audio", str(exc))
        LOGGER.exception("audio_playback_failed")


def show_quran_gate(config: Dict[str, Any], db: AssistantDB):
    qcfg = config.get("quran_khatma", {})
    if not qcfg.get("enabled", False):
        return

    mode = normalize_mode(qcfg.get("mode", "rub"))
    unit = get_quran_current_unit(mode, config, db)

    try:
        verses = fetch_quran_segment(unit, mode, config)
    except Exception as exc:
        register_error("quran_gate", str(exc))
        LOGGER.exception("quran_gate_fetch_failed")
        notify("الختمة القرآنية", "تعذّر تحميل مقطع القرآن حالياً.", category="quran")
        return

    root = Tk()
    root.title(f"الختمة القرآنية - {mode} {to_arabic_digits(unit)}")
    root.configure(bg="#0f172a")
    root.minsize(1080, 680)

    start_fullscreen = bool(qcfg.get("start_fullscreen", True))
    always_on_top = bool(qcfg.get("always_on_top", True))
    allow_exit = bool(qcfg.get("allow_exit", True))
    initial_panel_visible = bool(qcfg.get("show_side_panel", True))
    side_panel_width = int(qcfg.get("side_panel_width", 430))
    arabic_font_size = int(qcfg.get("arabic_font_size", 42))

    fullscreen_state = {"value": start_fullscreen}
    panel_state = {"visible": initial_panel_visible}

    if always_on_top:
        root.attributes("-topmost", True)
    if start_fullscreen:
        try:
            root.attributes("-fullscreen", True)
        except Exception:
            pass
        try:
            root.state("zoomed")
        except Exception:
            pass

    result = {"action": None}
    audio_stop_event = threading.Event()
    audio_thread: Optional[threading.Thread] = None

    def choose_font(candidates: List[str], fallback: str) -> str:
        try:
            families = set(root.tk.call("font", "families"))
        except Exception:
            return fallback
        for candidate in candidates:
            if candidate in families:
                return candidate
        return fallback

    quran_font = choose_font(
        [
            "KFGQPC Uthmanic Script HAFS",
            "Amiri Quran",
            "Scheherazade New",
            "Scheherazade",
            "Noto Naskh Arabic",
            "Noto Sans Arabic",
            "Traditional Arabic",
            "Arial",
        ],
        "Scheherazade",
    )
    arabic_ui_font = choose_font(
        ["Noto Naskh Arabic", "Noto Sans Arabic", "Amiri", "Traditional Arabic", "Arial"],
        "Arial",
    )
    latin_ui_font = choose_font(["Segoe UI", "Inter", "Arial"], "Arial")

    def close_gate(action: str = "snooze"):
        result["action"] = action
        root.destroy()

    def reset_to_start_action():
        title = "إعادة البدء"
        prompt = "البدء من أول المقطع؟ سيتم ضبط التقدم على الوحدة ١."
        if messagebox.askyesno(title, prompt):
            set_quran_current_unit(mode, 1, db)
            if mode == "rub":
                LEGACY_QURAN_STATE_PATH.write_text(
                    json.dumps({"current_rub": 1}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            close_gate("restart_from_start")

    def on_close_request():
        if not allow_exit:
            notify("الختمة القرآنية", "الإغلاق معطّل من الإعدادات.", category="quran")
            return
        decision = messagebox.askyesnocancel(
            "إغلاق الختمة",
            "نعم: إنهاء مع حفظ التقدم (تمّت القراءة)\n"
            "لا: إغلاق مع تأجيل (بدون تقدم)\n"
            "إلغاء: رجوع بدون إغلاق",
        )
        if decision is True:
            close_gate("read")
        elif decision is False:
            close_gate("snooze")
        else:
            return

    root.protocol("WM_DELETE_WINDOW", on_close_request)

    # ---------- Header ----------
    top = Frame(root, bg="#0f172a")
    top.pack(side="top", fill="x", padx=12, pady=(10, 8))

    title_label = Label(
        top,
        text=fix_arabic_text(f"الختمة القرآنية - {mode} رقم {to_arabic_digits(unit)}"),
        font=(arabic_ui_font, 24, "bold"),
        fg="#f8fafc",
        bg="#0f172a",
    )
    title_label.pack(side="left")

    shortcuts_label = Label(
        top,
        text=fix_arabic_text("F2: اللوحة  |  F11: ملء الشاشة  |  Ctrl+Home: من البداية  |  Ctrl+Q: إغلاق"),
        font=(latin_ui_font, 10),
        fg="#94a3b8",
        bg="#0f172a",
    )
    shortcuts_label.pack(side="left", padx=18)

    controls = Frame(top, bg="#0f172a")
    controls.pack(side="right")

    main_container = Frame(root, bg="#0f172a")
    main_container.pack(fill=BOTH, expand=True, padx=12, pady=(0, 10))

    paned = PanedWindow(main_container, sashwidth=8, bg="#0f172a", bd=0, relief="flat")
    paned.pack(fill=BOTH, expand=True)

    left_frame = Frame(paned, bg="#f8f3e7", bd=0, relief="flat")
    right_frame = Frame(paned, bg="#eef2f7", width=side_panel_width)
    paned.add(left_frame, stretch="always", minsize=720)
    if panel_state["visible"]:
        paned.add(right_frame, minsize=320)

    text_scroll = Scrollbar(left_frame, troughcolor="#d6d3d1")
    text_scroll.pack(side=RIGHT, fill=Y)

    text_widget = Text(
        left_frame,
        wrap="word",
        font=(quran_font, arabic_font_size),
        spacing1=10,
        spacing2=5,
        spacing3=16,
        bg="#f8f3e7",
        fg="#1f1b16",
        yscrollcommand=text_scroll.set,
        padx=34,
        pady=24,
        relief="flat",
        borderwidth=0,
    )
    text_widget.pack(fill=BOTH, expand=True)
    text_scroll.config(command=text_widget.yview)

    text_widget.tag_configure(
        "surah",
        font=(arabic_ui_font, 20, "bold"),
        justify="center",
        foreground="#6d4c41",
        spacing1=18,
        spacing3=10,
    )
    text_widget.tag_configure(
        "verse",
        font=(quran_font, arabic_font_size),
        justify="right",
        lmargin1=14,
        lmargin2=14,
        rmargin=16,
        spacing3=12,
    )

    # ---------- Side Panel ----------
    right_title = Label(
        right_frame,
        text=fix_arabic_text("لوحة الآيات"),
        bg="#eef2f7",
        fg="#0f172a",
        font=(arabic_ui_font, 16, "bold"),
    )
    right_title.pack(anchor="w", padx=12, pady=(12, 6))

    list_label = Label(
        right_frame,
        text=fix_arabic_text("الآيات"),
        bg="#eef2f7",
        fg="#0f172a",
        font=(arabic_ui_font, 12, "bold"),
    )
    list_label.pack(anchor="w", padx=10, pady=(10, 2))

    verse_list = Listbox(
        right_frame,
        height=16,
        font=(arabic_ui_font, 11),
        bg="#ffffff",
        activestyle="dotbox",
    )
    verse_list.pack(fill="x", padx=10)

    selected_var = StringVar(value="")
    selected_label = Label(
        right_frame,
        textvariable=selected_var,
        bg="#eef2f7",
        fg="#111827",
        font=(latin_ui_font, 11, "bold"),
    )
    selected_label.pack(anchor="w", padx=10, pady=(8, 4))

    detail_label = Label(
        right_frame,
        text=fix_arabic_text("الترجمة / التفسير"),
        bg="#eef2f7",
        fg="#111827",
        font=(arabic_ui_font, 11, "bold"),
    )
    detail_label.pack(anchor="w", padx=10)

    detail_text = Text(
        right_frame,
        height=11,
        wrap="word",
        font=(latin_ui_font, 10),
        bg="#ffffff",
        relief="solid",
        borderwidth=1,
    )
    detail_text.pack(fill="both", expand=False, padx=10, pady=4)

    notes_label = Label(
        right_frame,
        text=fix_arabic_text("الملاحظات"),
        bg="#eef2f7",
        fg="#111827",
        font=(arabic_ui_font, 11, "bold"),
    )
    notes_label.pack(anchor="w", padx=10)

    notes_text = Text(
        right_frame,
        height=6,
        wrap="word",
        font=(latin_ui_font, 10),
        bg="#ffffff",
        relief="solid",
        borderwidth=1,
    )
    notes_text.pack(fill="both", expand=False, padx=10, pady=4)

    bookmark_var = StringVar(value="Bookmark: OFF")
    bookmark_label = Label(
        right_frame,
        textvariable=bookmark_var,
        bg="#eef2f7",
        fg="#1f2937",
        font=(latin_ui_font, 10, "bold"),
    )
    bookmark_label.pack(anchor="w", padx=10)

    current_surah = None
    for verse in verses:
        key = verse["key"]
        surah_id = verse["surah"]
        ayah_num = verse["ayah"]

        display = fix_arabic_text(
            f"{SURAH_NAMES.get(surah_id, str(surah_id))} | {to_arabic_digits(surah_id)}:{to_arabic_digits(ayah_num)}"
        )
        verse_list.insert(END, display)

        if surah_id != current_surah:
            sname = fix_arabic_text(f"﴿ {SURAH_NAMES.get(surah_id, f'سورة {surah_id}')} ﴾")
            text_widget.insert(END, f"\n{sname}\n", "surah")
            current_surah = surah_id

        verse_number = to_arabic_digits(ayah_num)
        verse_text = str(verse["text"]).strip()
        verse_line = fix_arabic_text(f"{verse_text}  ۝{verse_number}")
        text_widget.insert(END, f"{verse_line}\n\n", "verse")

    text_widget.config(state="disabled")

    def maybe_fix_arabic(raw: str) -> str:
        if re.search(r"[\u0600-\u06FF]", raw or ""):
            return fix_arabic_text(raw)
        return raw

    def load_verse_details(index: int):
        if index < 0 or index >= len(verses):
            return

        verse = verses[index]
        key = verse["key"]
        selected_var.set(f"Selected: {key}  ({SURAH_NAMES.get(verse['surah'], '')})")

        detail_lines = []
        if verse.get("translation"):
            detail_lines.append("Translation:")
            detail_lines.append(maybe_fix_arabic(verse["translation"]))
            detail_lines.append("")
        if verse.get("tafsir"):
            detail_lines.append("Tafsir:")
            detail_lines.append(maybe_fix_arabic(verse["tafsir"]))

        detail_text.config(state="normal")
        detail_text.delete("1.0", END)
        detail_text.insert(END, "\n".join(detail_lines) if detail_lines else "No translation/tafsir available.")
        detail_text.config(state="disabled")

        note, bookmarked = db.get_quran_note(key)
        notes_text.delete("1.0", END)
        notes_text.insert(END, note)
        bookmark_var.set("Bookmark: ON" if bookmarked else "Bookmark: OFF")

    def get_selected_index() -> int:
        sel = verse_list.curselection()
        if not sel:
            return 0
        return int(sel[0])

    def save_note_action():
        idx = get_selected_index()
        verse = verses[idx]
        key = verse["key"]
        note_text = notes_text.get("1.0", END).strip()
        _, bookmarked = db.get_quran_note(key)
        db.save_quran_note(key, note_text, bookmarked)
        notify("Quran", f"Saved note for {key}", category="quran")

    def toggle_bookmark_action():
        idx = get_selected_index()
        verse = verses[idx]
        key = verse["key"]
        note_text = notes_text.get("1.0", END).strip()
        _, bookmarked = db.get_quran_note(key)
        db.save_quran_note(key, note_text, not bookmarked)
        bookmark_var.set("Bookmark: ON" if not bookmarked else "Bookmark: OFF")

    audio_controls = Frame(right_frame, bg="#eef2f7")
    audio_controls.pack(fill="x", padx=10, pady=6)

    Label(audio_controls, text=fix_arabic_text("تكرار التلاوة"), bg="#eef2f7", font=(arabic_ui_font, 10, "bold")).pack(side=LEFT)
    repeat_var = StringVar(value=str(int(qcfg.get("audio_repeat_default", 1))))
    repeat_box = Spinbox(audio_controls, from_=1, to=20, textvariable=repeat_var, width=5)
    repeat_box.pack(side=LEFT, padx=6)

    def play_selected_audio():
        nonlocal audio_thread
        idx = get_selected_index()
        verse = verses[idx]
        try:
            repeats = max(1, int(repeat_var.get()))
        except Exception:
            repeats = 1

        audio_stop_event.clear()
        url = build_audio_url(verse, config)

        def runner():
            for _ in range(repeats):
                if STOP_EVENT.is_set() or audio_stop_event.is_set():
                    break
                play_audio_url(url, audio_stop_event)

        audio_thread = threading.Thread(target=runner, daemon=True)
        audio_thread.start()

    def stop_audio_action():
        audio_stop_event.set()

    Button(audio_controls, text=fix_arabic_text("تشغيل"), command=play_selected_audio).pack(side=LEFT, padx=4)
    Button(audio_controls, text=fix_arabic_text("إيقاف"), command=stop_audio_action).pack(side=LEFT, padx=4)

    note_actions = Frame(right_frame, bg="#eef2f7")
    note_actions.pack(fill="x", padx=10, pady=(2, 10))

    Button(note_actions, text=fix_arabic_text("حفظ الملاحظة"), command=save_note_action).pack(side=LEFT, padx=4)
    Button(note_actions, text=fix_arabic_text("تبديل المرجعية"), command=toggle_bookmark_action).pack(side=LEFT, padx=4)

    def apply_fullscreen_state():
        try:
            root.attributes("-fullscreen", fullscreen_state["value"])
        except Exception:
            pass
        if fullscreen_state["value"]:
            try:
                root.state("zoomed")
            except Exception:
                pass
            fullscreen_btn.config(text=fix_arabic_text("وضع نافذة"))
        else:
            fullscreen_btn.config(text=fix_arabic_text("ملء الشاشة"))

    def toggle_fullscreen(_event=None):
        fullscreen_state["value"] = not fullscreen_state["value"]
        apply_fullscreen_state()
        return "break"

    def apply_panel_state():
        if panel_state["visible"]:
            try:
                paned.add(right_frame, minsize=320)
            except Exception:
                pass
            try:
                root.update_idletasks()
                paned.sash_place(0, max(540, root.winfo_width() - side_panel_width), 1)
            except Exception:
                pass
            panel_btn.config(text=fix_arabic_text("إخفاء اللوحة"))
        else:
            try:
                paned.forget(right_frame)
            except Exception:
                pass
            panel_btn.config(text=fix_arabic_text("إظهار اللوحة"))

    def toggle_panel(_event=None):
        panel_state["visible"] = not panel_state["visible"]
        apply_panel_state()
        return "break"

    panel_btn = Button(
        controls,
        text=fix_arabic_text("إخفاء اللوحة"),
        font=(latin_ui_font, 10, "bold"),
        bg="#334155",
        fg="#f8fafc",
        relief="flat",
        padx=10,
        pady=4,
        command=toggle_panel,
    )
    panel_btn.pack(side=LEFT, padx=4)

    fullscreen_btn = Button(
        controls,
        text=fix_arabic_text("وضع نافذة"),
        font=(latin_ui_font, 10, "bold"),
        bg="#334155",
        fg="#f8fafc",
        relief="flat",
        padx=10,
        pady=4,
        command=toggle_fullscreen,
    )
    fullscreen_btn.pack(side=LEFT, padx=4)

    quick_done_btn = Button(
        controls,
        text=fix_arabic_text("✅ تمّت القراءة"),
        font=(arabic_ui_font, 10, "bold"),
        bg="#16a34a",
        fg="#ffffff",
        relief="flat",
        padx=10,
        pady=4,
        command=lambda: close_gate("read"),
    )
    quick_done_btn.pack(side=LEFT, padx=4)

    quick_snooze_btn = Button(
        controls,
        text=fix_arabic_text("⏰ تأجيل"),
        font=(arabic_ui_font, 10, "bold"),
        bg="#ca8a04",
        fg="#111827",
        relief="flat",
        padx=10,
        pady=4,
        command=lambda: close_gate("snooze"),
    )
    quick_snooze_btn.pack(side=LEFT, padx=4)

    restart_btn = Button(
        controls,
        text=fix_arabic_text("من الفاتحة"),
        font=(arabic_ui_font, 10, "bold"),
        bg="#0ea5e9",
        fg="#082f49",
        relief="flat",
        padx=10,
        pady=4,
        command=reset_to_start_action,
    )
    restart_btn.pack(side=LEFT, padx=4)

    close_btn = Button(
        controls,
        text=fix_arabic_text("إغلاق"),
        font=(arabic_ui_font, 10, "bold"),
        bg="#dc2626",
        fg="#ffffff",
        relief="flat",
        padx=10,
        pady=4,
        command=on_close_request,
        state="normal" if allow_exit else "disabled",
    )
    close_btn.pack(side=LEFT, padx=4)

    apply_panel_state()
    apply_fullscreen_state()

    # ---------- Bottom actions ----------
    bottom = Frame(root, bg="#0f172a")
    bottom.pack(side="bottom", fill="x", pady=(0, 14), padx=12)

    def on_read():
        close_gate("read")

    def on_snooze():
        close_gate("snooze")

    Button(
        bottom,
        text=fix_arabic_text("✅ تمّت القراءة"),
        font=(arabic_ui_font, 18, "bold"),
        command=on_read,
        bg="#16a34a",
        fg="#ffffff",
        relief="flat",
    ).pack(
        side="left", expand=True, padx=16, ipady=10
    )
    Button(
        bottom,
        text=fix_arabic_text("⏰ تأجيل"),
        font=(arabic_ui_font, 18, "bold"),
        command=on_snooze,
        bg="#ca8a04",
        fg="#111827",
        relief="flat",
    ).pack(
        side="right", expand=True, padx=16, ipady=10
    )

    def on_select(_event=None):
        load_verse_details(get_selected_index())

    def on_ctrl_q(_event=None):
        on_close_request()
        return "break"

    def on_escape(_event=None):
        if fullscreen_state["value"]:
            toggle_fullscreen()
        else:
            on_close_request()
        return "break"

    root.bind("<F2>", toggle_panel)
    root.bind("<F11>", toggle_fullscreen)
    root.bind("<Control-Home>", lambda _e: reset_to_start_action() or "break")
    root.bind("<Control-q>", on_ctrl_q)
    root.bind("<Escape>", on_escape)

    verse_list.bind("<<ListboxSelect>>", on_select)
    verse_list.selection_set(0)
    load_verse_details(0)

    root.mainloop()
    audio_stop_event.set()
    if result["action"] is None:
        result["action"] = "snooze"

    if result["action"] == "restart_from_start":
        show_quran_gate(config, db)
        return

    if result["action"] == "read":
        max_count = QURAN_MODE_META[mode]["count"]
        next_unit = unit + 1
        if next_unit > max_count:
            next_unit = 1 if qcfg.get("restart_on_complete", False) else max_count
        set_quran_current_unit(mode, next_unit, db)
        progress = get_quran_daily_progress(mode)
        set_quran_daily_progress(mode, progress.get("done", 0) + 1)
        if mode == "rub":
            LEGACY_QURAN_STATE_PATH.write_text(json.dumps({"current_rub": next_unit}, ensure_ascii=False, indent=2), encoding="utf-8")
    elif result["action"] == "snooze":
        set_quran_current_unit(mode, unit, db)


class ManagedThread(threading.Thread):
    def __init__(self, name: str, config: Dict[str, Any], db: AssistantDB):
        super().__init__(daemon=True, name=name)
        self.config = config
        self.db = db

    def run(self):
        mark_thread(self.name, "running")
        try:
            self.loop()
            mark_thread(self.name, "stopped")
        except Exception as exc:
            register_error(self.name, str(exc))
            LOGGER.exception("thread_failed", extra={"thread": self.name})
            mark_thread(self.name, "failed", str(exc))

    def loop(self):
        raise NotImplementedError

    def sleep(self, seconds: float) -> bool:
        return responsive_sleep(seconds)


class PrayerReminderThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("PrayerReminderThread", config, db)
        self.last_fetch_date: Optional[date] = None
        self.today_times: Dict[str, str] = {}
        self.today_meta: Dict[str, Any] = {}

        self.prayer_order = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
        self.flags: Dict[str, bool] = {}
        self.status_cache: Dict[str, str] = {}

    def _flag_key(self, label: str, prayer: str) -> str:
        return f"{label}:{prayer}"

    def _done(self, label: str, prayer: str) -> bool:
        return self.flags.get(self._flag_key(label, prayer), False)

    def _set_done(self, label: str, prayer: str):
        self.flags[self._flag_key(label, prayer)] = True

    def _display_prayer_name(self, prayer: str) -> str:
        if prayer == "dhuhr" and self.config.get("jumuah", {}).get("enabled", True) and now_local().weekday() == 4:
            return "الجمعة"
        return prayer

    def _mark_status(self, prayer: str, status: str, context: str):
        day = day_key()
        self.status_cache[prayer] = status
        self.db.upsert_prayer_status(day, prayer, status, context)

    def _update_next_prayer(self):
        n = now_local()
        candidates: List[Tuple[str, datetime]] = []
        for prayer, tstr in self.today_times.items():
            dt = parse_hhmm_today(tstr)
            if dt > n:
                candidates.append((prayer, dt))
        if not candidates:
            set_next_prayer_runtime(None, None)
            return
        next_name, next_dt = min(candidates, key=lambda x: x[1])
        set_next_prayer_runtime(next_name, next_dt)

    def _is_ramadan_today(self) -> bool:
        rcfg = self.config.get("ramadan", {})
        if not rcfg.get("enabled", False):
            return False
        if rcfg.get("force_ramadan", False):
            return True
        if rcfg.get("auto_detect", True):
            return int(self.today_meta.get("hijri_month", 0)) == 9
        return False

    def _handle_ramadan(self, now_dt: datetime):
        if not self._is_ramadan_today():
            return

        rcfg = self.config.get("ramadan", {})

        fajr = parse_hhmm_today(self.today_times.get("fajr", "00:00"))
        maghrib = parse_hhmm_today(self.today_times.get("maghrib", "00:00"))
        isha = parse_hhmm_today(self.today_times.get("isha", "00:00"))

        suhoor_before = int(rcfg.get("suhoor_minutes_before_fajr", 45))
        taraweeh_after = int(rcfg.get("taraweeh_minutes_after_isha", 35))

        suhoor_key = "ramadan_suhoor"
        if not self._done(suhoor_key, "fajr") and in_trigger_window(now_dt, fajr - timedelta(minutes=suhoor_before)):
            notify("رمضان", "تذكير السحور قبل الفجر", category="prayers")
            self._set_done(suhoor_key, "fajr")

        iftar_key = "ramadan_iftar"
        if not self._done(iftar_key, "maghrib") and in_trigger_window(now_dt, maghrib):
            notify("رمضان", "حان وقت الإفطار - تقبّل الله", urgency="critical", category="prayers")
            self._set_done(iftar_key, "maghrib")

        taraweeh_key = "ramadan_taraweeh"
        taraweeh_time = isha + timedelta(minutes=taraweeh_after)
        if not self._done(taraweeh_key, "isha") and in_trigger_window(now_dt, taraweeh_time):
            notify("رمضان", "موعد صلاة التراويح", category="prayers")
            self._set_done(taraweeh_key, "isha")

    def _handle_jumuah(self, now_dt: datetime):
        if now_dt.weekday() != 4:
            return

        jcfg = self.config.get("jumuah", {})
        if not jcfg.get("enabled", False):
            return

        khutbah_time = parse_hhmm_today(jcfg.get("khutbah_time", "12:30"))
        remind_before = int(jcfg.get("khutbah_remind_before_minutes", 40))
        depart_before = int(jcfg.get("early_departure_minutes_before", 55))

        if not self._done("jumuah_remind", "dhuhr") and in_trigger_window(now_dt, khutbah_time - timedelta(minutes=remind_before)):
            notify("الجمعة", "تذكير بخطبة الجمعة", category="prayers")
            self._set_done("jumuah_remind", "dhuhr")

        if not self._done("jumuah_depart", "dhuhr") and in_trigger_window(now_dt, khutbah_time - timedelta(minutes=depart_before)):
            notify("الجمعة", "وقت التحرك مبكراً للمسجد", category="prayers")
            self._set_done("jumuah_depart", "dhuhr")

    def _handle_prayer_cycle(self, now_dt: datetime):
        pr_cfg = self.config.get("prayers", {})
        mosque_cfg = pr_cfg.get("mosque_mode", {})

        remind_before = int(pr_cfg.get("remind_before_minutes", 15))
        last_call = int(pr_cfg.get("last_call_minutes", 5))
        window_minutes = pr_cfg.get("window_minutes", {})
        iqama_enabled = bool(mosque_cfg.get("enabled", False))
        iqama_offsets = mosque_cfg.get("iqama_offsets_minutes", {})

        for name in self.prayer_order:
            if name not in self.today_times:
                continue

            display_name = self._display_prayer_name(name)
            prayer_time = parse_hhmm_today(self.today_times[name])
            prayer_window_m = int(window_minutes.get(name, 60))
            end_window = prayer_time + timedelta(minutes=prayer_window_m)

            pre_t = prayer_time - timedelta(minutes=remind_before)
            if not self._done("pre", name) and in_trigger_window(now_dt, pre_t):
                notify("تذكير صلاة", f"قرب ميعاد صلاة {display_name}", category="prayers")
                self._set_done("pre", name)

            if not self._done("adhan", name) and in_trigger_window(now_dt, prayer_time):
                notify("الأذان", f"حان الآن موعد صلاة {display_name}", urgency="critical", category="prayers")
                if ask_yes_no(f"هل صليت {display_name}؟"):
                    self._mark_status(name, "prayed", "adhan_confirmation")
                self._set_done("adhan", name)

            if iqama_enabled:
                offset = int(iqama_offsets.get(name, 0))
                if offset > 0:
                    iqama_t = prayer_time + timedelta(minutes=offset)
                    if not self._done("iqama", name) and in_trigger_window(now_dt, iqama_t):
                        notify("المسجد", f"موعد إقامة {display_name}", category="prayers")
                        if ask_yes_no(f"هل أدركت إقامة {display_name}؟"):
                            self._mark_status(name, "prayed", "iqama_confirmation")
                        self._set_done("iqama", name)

            if not self._done("last", name) and in_trigger_window(now_dt, end_window - timedelta(minutes=last_call)):
                notify(
                    "آخر فرصة",
                    f"باقي أقل من {last_call} دقيقة على خروج وقت {display_name}",
                    urgency="critical",
                    category="prayers",
                )
                self._set_done("last", name)

            t10 = prayer_time + timedelta(minutes=10)
            if not self._done("post10", name) and in_trigger_window(now_dt, t10):
                if ask_yes_no(f"فات 10 دقائق على {display_name}. هل صليت في المسجد؟"):
                    self._mark_status(name, "prayed", "post10_confirmation")
                self._set_done("post10", name)

            t20 = prayer_time + timedelta(minutes=20)
            if not self._done("post20", name) and in_trigger_window(now_dt, t20):
                if ask_yes_no(f"مر 20 دقيقة على {display_name}. تأكيد للصلاة؟"):
                    self._mark_status(name, "prayed", "post20_confirmation")
                self._set_done("post20", name)

            if name in self.prayer_order:
                idx = self.prayer_order.index(name)
                if idx > 0:
                    prev_name = self.prayer_order[idx - 1]
                    t_minus_60 = prayer_time - timedelta(minutes=60)
                    t_minus_30 = prayer_time - timedelta(minutes=30)

                    if not self._done("pre60", name) and in_trigger_window(now_dt, t_minus_60):
                        ask_yes_no(f"باقي ساعة على {display_name}. هل صليت {prev_name}؟")
                        self._set_done("pre60", name)

                    if not self._done("pre30", name) and in_trigger_window(now_dt, t_minus_30):
                        ask_yes_no(f"باقي نصف ساعة على {display_name}. هل صليت {prev_name}؟")
                        self._set_done("pre30", name)

            if now_dt > end_window and self.status_cache.get(name) != "prayed" and not self._done("missed", name):
                self._mark_status(name, "missed", "window_expired")
                notify("الصلاة", f"تم تسجيل {display_name} كـ فائتة", category="prayers")
                if is_feature_enabled("prayer_recovery_flow"):
                    notify(
                        "Prayer Recovery",
                        (
                            f"Missed {display_name}. Recovery plan:\\n"
                            "1) Pray next prayer on time\\n"
                            "2) Make a 2-minute dua now\\n"
                            "3) Review blockers tonight"
                        ),
                        category="prayers",
                        force=True,
                    )
                self._set_done("missed", name)

    def loop(self):
        pr_cfg = self.config.get("prayers", {})
        if not pr_cfg.get("enabled", False):
            return

        loc = self.config.get("location", {})
        city = loc.get("city", "Cairo")
        country = loc.get("country", "EG")
        method = int(loc.get("method", 5))

        while not STOP_EVENT.is_set():
            check_focus_override_timeout()

            if not is_feature_enabled("prayers"):
                self.sleep(5)
                continue

            n = now_local()
            if self.last_fetch_date != n.date():
                times, meta = fetch_prayer_times(city, country, method=method)
                if times:
                    self.today_times = times
                    self.today_meta = meta
                    self.last_fetch_date = n.date()
                    self.flags = {}
                    self.status_cache = {}
                    self.db.set_prayers_planned(day_key(n), len(times))
                    show_today_prayer_summary(self.today_times)
                    LOGGER.info("prayer_times_loaded")

            if self.today_times:
                self._handle_prayer_cycle(n)
                self._handle_ramadan(n)
                self._handle_jumuah(n)
                self._update_next_prayer()

            self.sleep(15)


class PomodoroThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("PomodoroThread", config, db)

    def loop(self):
        cfg = self.config.get("pomodoro", {})
        if not cfg.get("enabled", False):
            return

        work_m = int(cfg.get("work_minutes", 50))
        short_b = int(cfg.get("short_break_minutes", 10))
        long_b = int(cfg.get("long_break_minutes", 25))
        cycles_before_long = int(cfg.get("cycles_before_long_break", 4))

        cycle = 0
        while not STOP_EVENT.is_set():
            if not is_feature_enabled("pomodoro"):
                self.sleep(10)
                continue

            notify("Pomodoro", f"ابدأ فوكس لمدة {work_m} دقيقة", category="pomodoro")
            start = now_local()
            if not self.sleep(work_m * 60):
                break
            end = now_local()

            focused = max(1, int((end - start).total_seconds() / 60))
            self.db.increment_metric("pomodoro_sessions", 1)
            self.db.increment_metric("total_focus_minutes", focused)

            cycle += 1
            if cycle % cycles_before_long == 0:
                notify("Pomodoro", f"خد بريك طويل {long_b} دقيقة", category="pomodoro")
                if not self.sleep(long_b * 60):
                    break
            else:
                notify("Pomodoro", f"بريك قصير {short_b} دقيقة", category="pomodoro")
                if not self.sleep(short_b * 60):
                    break


class WorkdayLimitThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("WorkdayLimitThread", config, db)

    def loop(self):
        limit_hours = float(self.config.get("workday_limit_hours", 8))
        start_time = now_local()
        today = start_time.date()

        while not STOP_EVENT.is_set():
            n = now_local()
            if n.date() != today:
                today = n.date()
                start_time = n

            worked_h = (n - start_time).total_seconds() / 3600.0
            if worked_h >= limit_hours:
                big_alert(f"عدّيت {limit_hours} ساعة شغل متواصل! خد بريك.")
                if not self.sleep(60 * 30):
                    break
            else:
                if not self.sleep(300):
                    break


class HealthRemindersThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("HealthRemindersThread", config, db)

    def loop(self):
        cfg = self.config.get("health", {})
        water_i = int(cfg.get("water_interval_minutes", 60))
        stretch_i = int(cfg.get("stretch_interval_minutes", 90))

        last_water = now_local()
        last_stretch = now_local()

        while not STOP_EVENT.is_set():
            if not is_feature_enabled("health"):
                self.sleep(5)
                continue

            n = now_local()
            if (n - last_water).total_seconds() >= water_i * 60:
                notify("ماء", "اشرب كباية مياه", category="health")
                self.db.increment_metric("water_reminders", 1)
                last_water = n

            if (n - last_stretch).total_seconds() >= stretch_i * 60:
                notify("تحريك الجسم", "اقف واتحرك دقيقتين", category="health")
                self.db.increment_metric("stretch_reminders", 1)
                last_stretch = n

            self.sleep(30)


class EyeStrainThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("EyeStrainThread", config, db)

    def loop(self):
        cfg = self.config.get("eye_strain", {})
        if not cfg.get("enabled", False):
            return

        interval = int(cfg.get("interval_minutes", 20))
        followup_seconds = int(cfg.get("followup_after_seconds", 20))
        last = now_local()

        while not STOP_EVENT.is_set():
            if not is_feature_enabled("eye_strain"):
                self.sleep(10)
                continue

            n = now_local()
            if (n - last).total_seconds() >= interval * 60:
                notify("20-20-20", "Look 20 feet away for 20 seconds", category="eye_strain")
                self.db.increment_metric("eye_breaks", 1)
                last = n
                self.sleep(followup_seconds)
                notify("20-20-20", "Great. Resume work.", category="eye_strain")

            self.sleep(5)


def parse_event_time(event: Dict[str, Any]) -> Optional[datetime]:
    start = event.get("start", {}).get("dateTime")
    if not start:
        return None
    return datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(APP_TZ)


def build_meeting_prep_message(event: Dict[str, Any]) -> str:
    summary = event.get("summary", "Meeting")
    desc = event.get("description", "")
    location = event.get("location", "")
    hangout_link = event.get("hangoutLink", "")

    links = re.findall(r"https?://\S+", desc)
    agenda_lines = [line.strip() for line in desc.splitlines() if "agenda" in line.lower()]
    action_lines = [
        line.strip()
        for line in desc.splitlines()
        if any(tag in line.lower() for tag in ["todo", "action", "- [", "next step"])
    ]

    lines = [f"Prep for: {summary}"]
    if location:
        lines.append(f"Location: {location}")
    if hangout_link:
        lines.append(f"Call link: {hangout_link}")

    if agenda_lines:
        lines.append("Agenda:")
        lines.extend([f"- {x}" for x in agenda_lines[:3]])

    if links:
        lines.append("Docs:")
        lines.extend([f"- {x}" for x in links[:3]])

    if action_lines:
        lines.append("Action items:")
        lines.extend([f"- {x}" for x in action_lines[:4]])

    return "\n".join(lines)


class GoogleCalendarThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("GoogleCalendarThread", config, db)
        self.notified_events = set()
        self.prep_notified = set()
        self.auto_focus_started = set()

    def loop(self):
        cfg = self.config.get("google_calendar", {})
        if not cfg.get("enabled", False):
            return
        if not HAS_GOOGLE:
            return

        service = get_google_service(cfg.get("credentials_path", ""))
        if not service:
            return

        notify_before = int(cfg.get("notify_before_minutes", 10))
        prep_before = int(cfg.get("meeting_prep_minutes", 30))
        auto_focus_before = int(cfg.get("auto_focus_before_minutes", 20))
        auto_focus_after = int(cfg.get("auto_focus_after_minutes", 10))
        poll_seconds = int(cfg.get("poll_seconds", 60))
        max_events = int(cfg.get("max_events", 40))

        sync_key = "google_calendar_primary_sync"
        sync_token = self.db.get_sync_token(sync_key)

        while not STOP_EVENT.is_set():
            check_focus_override_timeout()

            if not is_feature_enabled("calendar"):
                self.sleep(10)
                continue

            events: List[Dict[str, Any]] = []
            try:
                if sync_token:
                    result = (
                        service.events()
                        .list(
                            calendarId="primary",
                            syncToken=sync_token,
                            singleEvents=True,
                            showDeleted=False,
                        )
                        .execute()
                    )
                else:
                    now_utc = datetime.now(timezone.utc)
                    start = (now_utc - timedelta(hours=6)).isoformat().replace("+00:00", "Z")
                    end = (now_utc + timedelta(days=2)).isoformat().replace("+00:00", "Z")
                    result = (
                        service.events()
                        .list(
                            calendarId="primary",
                            timeMin=start,
                            timeMax=end,
                            maxResults=max_events,
                            singleEvents=True,
                            orderBy="startTime",
                        )
                        .execute()
                    )

                events = result.get("items", [])
                new_sync = result.get("nextSyncToken")
                if new_sync:
                    sync_token = new_sync
                    self.db.set_sync_token(sync_key, new_sync)
                set_last_api_success("google_calendar")
            except HttpError as exc:
                if getattr(exc, "status_code", None) == 410 or "Sync token" in str(exc):
                    sync_token = None
                    self.db.set_sync_token(sync_key, "")
                register_error("calendar", str(exc))
                LOGGER.warning("calendar_sync_error: %s", exc)
            except Exception as exc:
                register_error("calendar", str(exc))
                LOGGER.exception("calendar_fetch_failed")

            n = now_local()
            for event in events:
                event_id = event.get("id")
                if not event_id:
                    continue

                event_dt = parse_event_time(event)
                if not event_dt:
                    continue

                delta_min = (event_dt - n).total_seconds() / 60.0
                summary = event.get("summary", "No title")

                if 0 <= delta_min <= notify_before and event_id not in self.notified_events:
                    notify("اجتماع قريب", f"{summary} بعد {int(delta_min)} دقيقة", category="calendar")
                    self.notified_events.add(event_id)

                if 0 <= delta_min <= prep_before and event_id not in self.prep_notified:
                    prep_msg = build_meeting_prep_message(event)
                    notify("Meeting Prep", prep_msg, category="calendar")
                    self.prep_notified.add(event_id)

                if (
                    is_feature_enabled("calendar_auto_focus")
                    and -auto_focus_after <= delta_min <= auto_focus_before
                    and event_id not in self.auto_focus_started
                ):
                    enable_focus_mode(auto_focus_before + auto_focus_after)
                    notify(
                        "Auto Focus",
                        f"Focus mode auto-enabled around meeting: {summary}",
                        category="calendar",
                        force=True,
                    )
                    self.auto_focus_started.add(event_id)

            self.sleep(poll_seconds)


class FocusModeThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("FocusModeThread", config, db)

    def loop(self):
        cfg = self.config.get("focus_mode", {})
        apps = cfg.get("work_blocklist_apps", [])

        if cfg.get("enabled", False):
            enable_focus_mode()

        while not STOP_EVENT.is_set():
            check_focus_override_timeout()

            feature_enabled = is_feature_enabled("focus_mode")
            with CONTROL_LOCK:
                override_until = CONTROL_STATE.get("focus_override_until")
            override_active = bool(override_until and now_local() < override_until)
            should_be_on = bool(cfg.get("enabled", False) or feature_enabled or override_active)

            if should_be_on and FOCUS_MANAGER and not FOCUS_MANAGER.active:
                FOCUS_MANAGER.apply(self.config)
            if not should_be_on and FOCUS_MANAGER and FOCUS_MANAGER.active:
                FOCUS_MANAGER.revert(self.config)

            if FOCUS_MANAGER and FOCUS_MANAGER.active:
                PLATFORM_ADAPTER.apply_focus_app_block(apps)

            self.sleep(12)


class DailyReportThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("DailyReportThread", config, db)
        self.last_report_date: Optional[date] = None
        self.last_weekly_check: Optional[str] = None

    def loop(self):
        cfg = self.config.get("daily_report", {})
        if not cfg.get("enabled", False):
            return

        hhmm = cfg.get("report_time", "23:30")
        h, m = map(int, hhmm.split(":"))

        while not STOP_EVENT.is_set():
            n = now_local()
            report_dt = n.replace(hour=h, minute=m, second=0, microsecond=0)

            if n >= report_dt and self.last_report_date != n.date():
                self.last_report_date = n.date()
                metrics = self.db.get_day_metrics(day_key(n))
                streak = self.db.get_prayer_streak()
                chart = build_compliance_chart_lines(self.db.get_week_compliance(7))
                score_payload = compute_daily_score_payload(metrics, streak)

                msg_lines = [
                    f"تقرير {day_key(n)}",
                    f"- جلسات بومودورو: {metrics.get('pomodoro_sessions', 0)}",
                    f"- وقت فوكس: {metrics.get('total_focus_minutes', 0)} دقيقة",
                    f"- تذكير مياه: {metrics.get('water_reminders', 0)}",
                    f"- تذكير حركة: {metrics.get('stretch_reminders', 0)}",
                    f"- راحة عين: {metrics.get('eye_breaks', 0)}",
                    f"- الصلوات: {metrics.get('prayers_prayed', 0)}/{metrics.get('prayers_planned', 0)}",
                    f"- Prayer streak: {streak} days",
                    f"- Daily score: {score_payload.get('total', 0)}/100",
                    "",
                    "Weekly compliance:",
                ]
                msg_lines.extend(chart)
                msg = "\n".join(msg_lines)

                notify("تقرير نهاية اليوم", "تم توليد التقرير في التيرمنال", category="general")
                print("\n" + "=" * 45)
                print(msg)
                print("=" * 45 + "\n")

            if is_feature_enabled("weekly_report_push") and n.weekday() == 4 and n.hour >= 21:
                week_key = f"{n.strftime('%Y')}-W{n.strftime('%V')}"
                if not self.db.is_weekly_report_sent(week_key):
                    week_rows = self.db.get_week_compliance(7)
                    chart = build_compliance_chart_lines(week_rows)
                    summary = [f"Weekly Report {week_key}", "", "Weekly compliance:"] + chart
                    payload = "\n".join(summary)
                    notify("Weekly Report", payload, category="general", force=True)
                    self.db.mark_weekly_report_sent(week_key, payload)

            self.sleep(30)


def get_today_calendar_summary_text(config: Dict[str, Any]) -> Tuple[bool, str]:
    gcfg = config.get("google_calendar", {})
    if not gcfg.get("enabled", False):
        return False, "Google Calendar summary is disabled in config."
    if not HAS_GOOGLE:
        return False, "Google Calendar libraries are not installed."

    service = get_google_service(gcfg.get("credentials_path", ""))
    if not service:
        return False, "Could not connect to Google Calendar service."

    now_utc = datetime.now(timezone.utc)
    start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    time_min = start.isoformat().replace("+00:00", "Z")
    time_max = end.isoformat().replace("+00:00", "Z")

    try:
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=int(gcfg.get("max_events", 10)),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
    except Exception as exc:
        register_error("calendar_summary", str(exc))
        return False, f"Calendar summary failed: {exc}"

    if not events:
        return True, "مافيش أحداث في جوجل كاليندر النهارده"

    lines = []
    for event in events:
        summary = event.get("summary", "بدون عنوان")
        start_val = event.get("start", {}).get("dateTime")
        if not start_val:
            lines.append(f"- {summary} (All day)")
            continue

        dt = datetime.fromisoformat(start_val.replace("Z", "+00:00")).astimezone(APP_TZ)
        lines.append(f"- {dt.strftime('%H:%M')} → {summary}")

    return True, "\n".join(lines)


def show_today_calendar_summary(config: Dict[str, Any]):
    ok, summary = get_today_calendar_summary_text(config)
    if not summary:
        return
    title = "ملخص جدول اليوم" if ok else "حالة تقويم اليوم"
    notify(title, summary, category="calendar", force=True)


def show_today_prayer_summary(today_times: Dict[str, str]):
    if not today_times:
        notify("ملخص الصلوات", "تعذّر تحميل أوقات الصلاة اليوم", category="prayers")
        return

    n = now_local()
    prayer_dt: Dict[str, datetime] = {}
    for name, tstr in today_times.items():
        prayer_dt[name] = parse_hhmm_today(tstr)

    next_name = None
    next_dt = None
    for name, dt in sorted(prayer_dt.items(), key=lambda x: x[1]):
        if dt > n:
            next_name = name
            next_dt = dt
            break

    lines = ["أوقات الصلاة اليوم:"]
    for name, dt in prayer_dt.items():
        lines.append(f"- {name}: {dt.strftime('%H:%M')}")

    if next_name and next_dt:
        rem = int((next_dt - n).total_seconds() / 60)
        lines.append(f"\nالصلاة القادمة: {next_name} بعد {rem} دقيقة")

    notify("ملخص الصلوات", "\n".join(lines), category="prayers")


class DashboardThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("DashboardThread", config, db)

    def loop(self):
        dcfg = self.config.get("dashboard", {})
        if not dcfg.get("enabled", False):
            return
        if not HAS_FLASK:
            return

        app = Flask("personal_assistant_dashboard")
        telegram_enabled = bool(self.config.get("telegram_bot", {}).get("enabled", False))
        if not telegram_enabled:
            schedule_dashboard_browser_open(self.config, reason="dashboard_startup")
        action_methods = ["GET", "POST"]

        def parse_bounded_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
            try:
                value = int(str(raw))
            except Exception:
                value = default
            return max(minimum, min(maximum, value))

        def wants_json() -> bool:
            accept = (request.headers.get("Accept") or "").lower()
            explicit_format = str(request.values.get("format", "")).strip().lower() == "json"
            return (
                explicit_format
                or "application/json" in accept
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            )

        def action_response(action: str, message: str, **extra: Any):
            payload = {
                "ok": True,
                "action": action,
                "message": message,
                "status": runtime_snapshot(),
            }
            payload.update(extra)
            if wants_json():
                return jsonify(payload)
            return redirect("/")

        def action_error(message: str, code: int = 400):
            payload = {
                "ok": False,
                "message": message,
            }
            if wants_json():
                return jsonify(payload), code
            notify("Dashboard", message, force=True)
            return redirect("/")

        dashboard_template = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg-a: #081425;
  --bg-b: #0d2438;
  --surface: rgba(250, 252, 255, 0.96);
  --surface-soft: rgba(241, 245, 249, 0.86);
  --line: #d6deea;
  --ink: #10223a;
  --muted: #4b5f79;
  --shadow: 0 18px 34px rgba(4, 20, 40, 0.24);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: "IBM Plex Sans", "Cairo", sans-serif;
  background:
    radial-gradient(1400px 500px at -15% -12%, rgba(16, 185, 129, 0.18), transparent 62%),
    radial-gradient(1200px 520px at 110% 0%, rgba(245, 158, 11, 0.14), transparent 58%),
    linear-gradient(165deg, var(--bg-a), var(--bg-b));
  color: #dbeafe;
}
main {
  width: min(1380px, calc(100% - 24px));
  margin: 18px auto 28px;
}
.card {
  background: var(--surface);
  color: var(--ink);
  border: 1px solid rgba(255, 255, 255, 0.45);
  border-radius: 18px;
  padding: 18px;
  box-shadow: var(--shadow);
  animation: cardIn .34s ease both;
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
  background: linear-gradient(150deg, rgba(14, 116, 144, 0.95), rgba(30, 64, 175, 0.95));
  color: #f8fafc;
}
.top h1 {
  margin: 0;
  font-size: clamp(1.1rem, 2.5vw, 1.6rem);
}
.top p {
  margin: 6px 0 0;
  font-size: 0.95rem;
  color: #dbeafe;
}
.badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
  font-size: 0.83rem;
  font-weight: 700;
}
.badge.ok {
  background: #dcfce7;
  color: #166534;
  border-color: #bbf7d0;
}
.badge.off {
  background: #fee2e2;
  color: #991b1b;
  border-color: #fecaca;
}
.badge.warn {
  background: #fef3c7;
  color: #92400e;
  border-color: #fde68a;
}
.grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 12px;
}
.span-8 { grid-column: span 8; }
.span-6 { grid-column: span 6; }
.span-4 { grid-column: span 4; }
h2 {
  margin: 0 0 12px;
  font-size: 1.06rem;
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.stat {
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px;
}
.stat small {
  color: var(--muted);
  display: block;
  margin-bottom: 6px;
}
.stat strong {
  font-size: 1.02rem;
  word-break: break-word;
}
.label-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
form.inline {
  display: grid;
  grid-template-columns: 1fr 90px 95px;
  gap: 8px;
  margin-bottom: 8px;
}
.field-label {
  display: flex;
  align-items: center;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #f8fafc;
  color: var(--muted);
  font-size: 0.9rem;
  font-weight: 600;
}
input[type='number'],
select {
  width: 100%;
  border: 1px solid var(--line);
  background: #ffffff;
  color: var(--ink);
  border-radius: 10px;
  padding: 9px 10px;
  font-size: 0.95rem;
}
.btn {
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 9px 11px;
  font-weight: 700;
  cursor: pointer;
  transition: transform .12s ease, filter .12s ease;
}
.btn:hover { transform: translateY(-1px); filter: brightness(0.97); }
.btn:active { transform: translateY(0); }
.btn-main { background: #0f766e; color: #ecfeff; border-color: #115e59; }
.btn-soft { background: #e2e8f0; color: #0f172a; border-color: #cbd5e1; }
.btn-warn { background: #fef3c7; color: #92400e; border-color: #f59e0b; }
.btn-danger { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
.btn-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.hint {
  margin: 10px 0 0;
  min-height: 18px;
  color: var(--muted);
  font-size: 0.9rem;
}
.progress-stack { display: grid; gap: 8px; }
.progress-row {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px;
  background: #ffffff;
}
.progress-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 0.9rem;
  color: var(--muted);
}
.track {
  width: 100%;
  height: 9px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #0ea5a4, #22c55e);
}
.list {
  display: grid;
  gap: 7px;
}
.list-item {
  border: 1px solid var(--line);
  background: #ffffff;
  border-radius: 10px;
  padding: 9px 10px;
}
.list-item .head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 0.82rem;
}
.list-item pre {
  margin: 5px 0 0;
  white-space: pre-wrap;
  font-family: "IBM Plex Sans", "Cairo", sans-serif;
}
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.91rem;
}
th, td {
  text-align: left;
  padding: 8px 7px;
  border-bottom: 1px solid var(--line);
}
th {
  color: var(--muted);
  font-weight: 700;
  font-size: 0.85rem;
}
.toggle-row {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #ffffff;
  padding: 8px 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.toggle-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.empty {
  color: var(--muted);
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  padding: 10px;
}
@media (max-width: 1180px) {
  .span-8, .span-6, .span-4 { grid-column: span 12; }
  .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .top { flex-direction: column; align-items: flex-start; }
  .meta-grid { grid-template-columns: 1fr; }
  form.inline { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<main>
  <section class="card top">
    <div>
      <h1>__TITLE__</h1>
      <p>Live control center for reminders, focus, prayers, and Quran tracking.</p>
    </div>
    <div class="label-row">
      <span class="badge" id="focus-pill">Focus OFF</span>
      <span class="badge" id="pause-pill">Pause OFF</span>
      <span class="badge" id="snooze-pill">Snooze OFF</span>
    </div>
  </section>

  <section class="grid">
    <article class="card span-8">
      <h2>Overview</h2>
      <div class="meta-grid">
        <div class="stat"><small>Now</small><strong id="now">-</strong></div>
        <div class="stat"><small>Uptime</small><strong id="uptime">-</strong></div>
        <div class="stat"><small>Next Prayer</small><strong id="next-prayer">-</strong></div>
        <div class="stat"><small>Daily Score</small><strong id="daily-score">0/100</strong></div>
        <div class="stat"><small>Mode</small><strong id="active-mode">workday</strong></div>
        <div class="stat"><small>Pause Until</small><strong id="pause-until">-</strong></div>
        <div class="stat"><small>Snooze Until</small><strong id="snooze-until">-</strong></div>
        <div class="stat"><small>Focus Override Until</small><strong id="focus-until">-</strong></div>
      </div>
      <div class="label-row" id="api-success"></div>
    </article>

    <article class="card span-4">
      <h2>Quick Controls</h2>
      <form class="inline" data-action="/action/pause">
        <span class="field-label">Pause (minutes)</span>
        <input type="number" min="1" max="720" name="minutes" value="30">
        <button class="btn btn-main" type="submit">Pause</button>
      </form>
      <form class="inline" data-action="/action/snooze">
        <span class="field-label">Snooze (minutes)</span>
        <input type="number" min="1" max="720" name="minutes" value="15">
        <button class="btn btn-main" type="submit">Snooze</button>
      </form>
      <form class="inline" data-action="/action/focus">
        <span class="field-label">Focus (minutes)</span>
        <input type="number" min="1" max="720" name="minutes" value="90">
        <button class="btn btn-main" type="submit">Focus</button>
      </form>
      <form class="inline" data-action="/action/quran_reset">
        <select name="mode" id="quran-mode">
          <option value="rub">rub</option>
          <option value="hizb">hizb</option>
          <option value="juz">juz</option>
          <option value="page">page</option>
        </select>
        <input type="number" min="1" max="604" id="quran-unit" name="unit" value="1">
        <button class="btn btn-warn" type="submit">Reset Quran</button>
      </form>
      <form class="inline" data-action="/action/mode">
        <select name="mode" id="mode-select">
          <option value="workday">workday</option>
          <option value="light">light</option>
          <option value="ramadan">ramadan</option>
        </select>
        <span class="field-label">Profile</span>
        <button class="btn btn-main" type="submit">Apply Mode</button>
      </form>
      <form class="inline" data-action="/action/quran_goal">
        <span class="field-label">Quran goal</span>
        <input type="number" min="1" max="60" id="quran-goal-input" name="units" value="1">
        <button class="btn btn-main" type="submit">Set Goal</button>
      </form>
      <div class="btn-row">
        <button class="btn btn-soft" type="button" data-action-button="/action/clear_pause">Clear Pause</button>
        <button class="btn btn-soft" type="button" data-action-button="/action/clear_snooze">Clear Snooze</button>
        <button class="btn btn-danger" type="button" data-action-button="/action/focus_off">Focus Off</button>
        <button class="btn btn-soft" type="button" id="manual-refresh">Refresh</button>
      </div>
      <p class="hint" id="action-feedback"></p>
      <p class="hint">Current Quran: <strong id="quran-state">-</strong></p>
      <p class="hint">Quran Goal: <strong id="quran-goal">0/1</strong></p>
    </article>

    <article class="card span-4">
      <h2>Today Metrics</h2>
      <div class="meta-grid">
        <div class="stat"><small>Pomodoro</small><strong id="pomodoro">0</strong></div>
        <div class="stat"><small>Focus Minutes</small><strong id="focus-minutes">0</strong></div>
        <div class="stat"><small>Water Alerts</small><strong id="water">0</strong></div>
        <div class="stat"><small>Stretch Alerts</small><strong id="stretch">0</strong></div>
        <div class="stat"><small>Eye Breaks</small><strong id="eye">0</strong></div>
        <div class="stat"><small>Prayers</small><strong id="prayer-count">0/0</strong></div>
      </div>
      <div class="label-row">
        <span class="badge ok" id="prayer-streak">0 days</span>
        <span class="badge warn" id="prayer-ratio">0%</span>
      </div>
    </article>

    <article class="card span-4">
      <h2>Weekly Prayer Compliance</h2>
      <div class="progress-stack" id="weekly-bars"></div>
    </article>

    <article class="card span-4">
      <h2>Feature Toggles</h2>
      <div class="list" id="toggles"></div>
    </article>

    <article class="card span-4">
      <h2>Platform Capabilities</h2>
      <div class="list" id="capabilities"></div>
    </article>

    <article class="card span-6">
      <h2>Thread Health</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Thread</th><th>Status</th><th>Updated</th><th>Error</th></tr></thead>
          <tbody id="threads-body"></tbody>
        </table>
      </div>
    </article>

    <article class="card span-6">
      <h2>Recent Events</h2>
      <div class="list" id="events"></div>
    </article>

    <article class="card span-6">
      <h2>Recent Errors</h2>
      <div class="list" id="errors"></div>
    </article>

    <article class="card span-6">
      <h2>Quran Bookmarks</h2>
      <div class="list" id="bookmarks"></div>
    </article>
  </section>
</main>

<script>
"use strict";

const MAX_QURAN_UNIT = {
  rub: 240,
  hizb: 60,
  juz: 30,
  page: 604
};

function $(id) {
  return document.getElementById(id);
}

function asText(value, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function formatIso(isoValue) {
  if (!isoValue) {
    return "-";
  }
  const dt = new Date(isoValue);
  if (Number.isNaN(dt.getTime())) {
    return String(isoValue);
  }
  return dt.toLocaleString();
}

function formatDuration(secondsValue) {
  const total = Math.max(0, Number(secondsValue) || 0);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const mins = Math.floor((total % 3600) / 60);
  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${mins}m`;
  }
  return `${mins}m`;
}

function isFutureIso(isoValue) {
  if (!isoValue) {
    return false;
  }
  const dt = new Date(isoValue);
  if (Number.isNaN(dt.getTime())) {
    return false;
  }
  return dt.getTime() > Date.now();
}

function setBadge(id, text, className) {
  const el = $(id);
  if (!el) {
    return;
  }
  el.textContent = text;
  el.className = "badge";
  if (className) {
    el.classList.add(className);
  }
}

function makeEmpty(text) {
  const div = document.createElement("div");
  div.className = "empty";
  div.textContent = text;
  return div;
}

function setText(id, value) {
  const el = $(id);
  if (!el) {
    return;
  }
  el.textContent = asText(value);
}

function renderApiSuccess(mapObj) {
  const wrap = $("api-success");
  wrap.textContent = "";
  const entries = Object.entries(mapObj || {});
  if (!entries.length) {
    wrap.appendChild(makeEmpty("No API success records yet."));
    return;
  }
  entries.sort((a, b) => a[0].localeCompare(b[0]));
  entries.forEach(([name, iso]) => {
    const chip = document.createElement("span");
    chip.className = "badge";
    chip.textContent = `${name}: ${formatIso(iso)}`;
    wrap.appendChild(chip);
  });
}

function renderWeekly(rows) {
  const wrap = $("weekly-bars");
  wrap.textContent = "";
  if (!Array.isArray(rows) || rows.length === 0) {
    wrap.appendChild(makeEmpty("No compliance data yet."));
    return;
  }
  rows.forEach((row) => {
    const planned = Number(row.planned || 0);
    const prayed = Number(row.prayed || 0);
    const ratio = planned > 0 ? Math.min(1, prayed / planned) : 0;

    const outer = document.createElement("div");
    outer.className = "progress-row";

    const head = document.createElement("div");
    head.className = "progress-head";

    const left = document.createElement("span");
    left.textContent = asText(row.day, "-");
    head.appendChild(left);

    const right = document.createElement("span");
    right.textContent = `${prayed}/${planned}`;
    head.appendChild(right);

    const track = document.createElement("div");
    track.className = "track";

    const fill = document.createElement("div");
    fill.className = "fill";
    fill.style.width = `${Math.round(ratio * 100)}%`;

    track.appendChild(fill);
    outer.appendChild(head);
    outer.appendChild(track);
    wrap.appendChild(outer);
  });
}

function renderToggles(toggleMap) {
  const wrap = $("toggles");
  wrap.textContent = "";
  const entries = Object.entries(toggleMap || {});
  if (!entries.length) {
    wrap.appendChild(makeEmpty("No feature toggles found."));
    return;
  }
  entries.sort((a, b) => a[0].localeCompare(b[0]));
  entries.forEach(([feature, enabled]) => {
    const row = document.createElement("div");
    row.className = "toggle-row";

    const name = document.createElement("strong");
    name.textContent = feature;
    row.appendChild(name);

    const actions = document.createElement("div");
    actions.className = "toggle-actions";

    const state = document.createElement("span");
    state.className = `badge ${enabled ? "ok" : "off"}`;
    state.textContent = enabled ? "ON" : "OFF";
    actions.appendChild(state);

    const onBtn = document.createElement("button");
    onBtn.type = "button";
    onBtn.className = "btn btn-soft";
    onBtn.textContent = "ON";
    onBtn.disabled = !!enabled;
    onBtn.addEventListener("click", () => postAction(`/action/toggle/${encodeURIComponent(feature)}`, { state: "on" }));
    actions.appendChild(onBtn);

    const offBtn = document.createElement("button");
    offBtn.type = "button";
    offBtn.className = "btn btn-soft";
    offBtn.textContent = "OFF";
    offBtn.disabled = !enabled;
    offBtn.addEventListener("click", () => postAction(`/action/toggle/${encodeURIComponent(feature)}`, { state: "off" }));
    actions.appendChild(offBtn);

    row.appendChild(actions);
    wrap.appendChild(row);
  });
}

function renderCapabilities(capabilities) {
  const wrap = $("capabilities");
  if (!wrap) {
    return;
  }
  wrap.textContent = "";
  const entries = Object.entries(capabilities || {});
  if (!entries.length) {
    wrap.appendChild(makeEmpty("No capability data."));
    return;
  }
  entries.sort((a, b) => a[0].localeCompare(b[0]));
  entries.forEach(([name, enabled]) => {
    const row = document.createElement("div");
    row.className = "toggle-row";
    const label = document.createElement("strong");
    label.textContent = name;
    row.appendChild(label);
    const state = document.createElement("span");
    state.className = `badge ${enabled ? "ok" : "off"}`;
    state.textContent = enabled ? "YES" : "NO";
    row.appendChild(state);
    wrap.appendChild(row);
  });
}

function renderThreads(threadsObj) {
  const body = $("threads-body");
  body.textContent = "";
  const rows = Object.entries(threadsObj || {});
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.textContent = "No thread data.";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  rows.sort((a, b) => a[0].localeCompare(b[0]));
  rows.forEach(([threadName, data]) => {
    const tr = document.createElement("tr");

    const tdName = document.createElement("td");
    tdName.textContent = threadName;
    tr.appendChild(tdName);

    const tdStatus = document.createElement("td");
    tdStatus.textContent = asText(data.status, "-");
    tr.appendChild(tdStatus);

    const tdUpdated = document.createElement("td");
    tdUpdated.textContent = formatIso(data.updated_at);
    tr.appendChild(tdUpdated);

    const tdError = document.createElement("td");
    tdError.textContent = asText(data.error, "");
    tr.appendChild(tdError);

    body.appendChild(tr);
  });
}

function renderList(containerId, items, buildFn, emptyText) {
  const wrap = $(containerId);
  wrap.textContent = "";
  if (!Array.isArray(items) || items.length === 0) {
    wrap.appendChild(makeEmpty(emptyText));
    return;
  }
  items.forEach((item) => {
    wrap.appendChild(buildFn(item));
  });
}

function renderEvents(events) {
  renderList("events", events, (event) => {
    const item = document.createElement("div");
    item.className = "list-item";

    const head = document.createElement("div");
    head.className = "head";

    const title = document.createElement("span");
    title.textContent = `${asText(event.category, "general")} | ${asText(event.title, "-")}`;
    head.appendChild(title);

    const ts = document.createElement("span");
    ts.textContent = formatIso(event.ts);
    head.appendChild(ts);

    item.appendChild(head);

    const body = document.createElement("pre");
    body.textContent = asText(event.body, "");
    item.appendChild(body);
    return item;
  }, "No events recorded.");
}

function renderErrors(errors) {
  renderList("errors", errors, (error) => {
    const item = document.createElement("div");
    item.className = "list-item";

    const head = document.createElement("div");
    head.className = "head";

    const source = document.createElement("span");
    source.textContent = asText(error.source, "unknown");
    head.appendChild(source);

    const ts = document.createElement("span");
    ts.textContent = formatIso(error.ts);
    head.appendChild(ts);

    item.appendChild(head);

    const body = document.createElement("pre");
    body.textContent = asText(error.message, "");
    item.appendChild(body);

    return item;
  }, "No runtime errors.");
}

function renderBookmarks(bookmarks) {
  renderList("bookmarks", bookmarks, (bookmark) => {
    const item = document.createElement("div");
    item.className = "list-item";

    const head = document.createElement("div");
    head.className = "head";

    const verse = document.createElement("span");
    verse.textContent = asText(bookmark.verse_key, "-");
    head.appendChild(verse);

    const ts = document.createElement("span");
    ts.textContent = formatIso(bookmark.updated_at);
    head.appendChild(ts);

    item.appendChild(head);

    const note = document.createElement("pre");
    note.textContent = asText(bookmark.note, "(No note)");
    item.appendChild(note);

    return item;
  }, "No bookmarks saved.");
}

function renderSnapshot(snap) {
  const metrics = snap.today_metrics || {};
  const score = snap.daily_score || {};
  const nextPrayer = snap.next_prayer && snap.next_prayer.name
    ? `${snap.next_prayer.name} at ${formatIso(snap.next_prayer.at)}`
    : "-";

  setText("now", formatIso(snap.now));
  setText("uptime", formatDuration(snap.uptime_seconds));
  setText("next-prayer", nextPrayer);
  setText("pause-until", formatIso(snap.pause_until));
  setText("snooze-until", formatIso(snap.snooze_until));
  setText("focus-until", formatIso(snap.focus_override_until));
  setText("daily-score", `${Number(score.total || 0)}/100`);
  setText("active-mode", asText(snap.active_mode, "workday"));
  if ($("mode-select")) {
    $("mode-select").value = asText(snap.active_mode, "workday");
  }

  const quranMode = asText(snap.quran_mode, "rub");
  const quranUnit = Number(snap.quran_current_unit || 1);
  setText("quran-state", `${quranMode} #${quranUnit}`);
  if ($("quran-mode")) {
    $("quran-mode").value = quranMode;
  }
  if ($("quran-unit")) {
    const maxUnit = MAX_QURAN_UNIT[quranMode] || 604;
    $("quran-unit").max = String(maxUnit);
    $("quran-unit").value = String(Math.min(maxUnit, Math.max(1, quranUnit)));
  }
  const quranGoal = Number(snap.quran_daily_goal || 1);
  const quranDone = Number((snap.quran_daily_progress || {}).done || 0);
  setText("quran-goal", `${quranDone}/${quranGoal}`);
  if ($("quran-goal-input")) {
    $("quran-goal-input").value = String(quranGoal);
  }

  setText("pomodoro", metrics.pomodoro_sessions || 0);
  setText("focus-minutes", metrics.total_focus_minutes || 0);
  setText("water", metrics.water_reminders || 0);
  setText("stretch", metrics.stretch_reminders || 0);
  setText("eye", metrics.eye_breaks || 0);

  const prayed = Number(metrics.prayers_prayed || 0);
  const planned = Number(metrics.prayers_planned || 0);
  setText("prayer-count", `${prayed}/${planned}`);
  setText("prayer-streak", `${Number(snap.prayer_streak || 0)} days`);
  setText("prayer-ratio", planned > 0 ? `${Math.round((prayed / planned) * 100)}%` : "0%");

  setBadge("focus-pill", snap.focus_mode_active ? "Focus ON" : "Focus OFF", snap.focus_mode_active ? "ok" : "off");
  setBadge("pause-pill", isFutureIso(snap.pause_until) ? "Pause ON" : "Pause OFF", isFutureIso(snap.pause_until) ? "warn" : "off");
  setBadge("snooze-pill", isFutureIso(snap.snooze_until) ? "Snooze ON" : "Snooze OFF", isFutureIso(snap.snooze_until) ? "warn" : "off");

  renderApiSuccess(snap.last_api_success || {});
  renderWeekly(snap.weekly_compliance || []);
  renderToggles(snap.feature_toggles || {});
  renderCapabilities(snap.capabilities || {});
  renderThreads(snap.threads || {});
  renderEvents(snap.recent_events || []);
  renderErrors(Array.isArray(snap.last_errors) ? [...snap.last_errors].reverse() : []);
  renderBookmarks(snap.bookmarks || []);
}

async function postAction(path, params) {
  const feedback = $("action-feedback");
  feedback.textContent = "Applying action...";
  const body = new URLSearchParams(params || {});
  try {
    const response = await fetch(`${path}?format=json`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: body.toString()
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || `HTTP ${response.status}`);
    }
    feedback.textContent = payload.message || "Action completed.";
    if (payload.status) {
      renderSnapshot(payload.status);
    } else {
      await refreshStatus();
    }
  } catch (err) {
    feedback.textContent = `Failed: ${err.message}`;
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const snap = await response.json();
    renderSnapshot(snap);
    const feedback = $("action-feedback");
    if (feedback.textContent.startsWith("Applying")) {
      feedback.textContent = "";
    }
  } catch (err) {
    $("action-feedback").textContent = `Status refresh failed: ${err.message}`;
  }
}

function wireControls() {
  document.querySelectorAll("form[data-action]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const actionPath = form.getAttribute("data-action");
      const data = {};
      const formData = new FormData(form);
      formData.forEach((value, key) => {
        data[key] = String(value);
      });
      postAction(actionPath, data);
    });
  });

  document.querySelectorAll("button[data-action-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const actionPath = button.getAttribute("data-action-button");
      postAction(actionPath, {});
    });
  });

  $("manual-refresh").addEventListener("click", () => refreshStatus());
  $("quran-mode").addEventListener("change", (event) => {
    const mode = event.target.value;
    if ($("quran-unit")) {
      $("quran-unit").max = String(MAX_QURAN_UNIT[mode] || 604);
    }
  });
}

wireControls();
refreshStatus();
setInterval(refreshStatus, 15000);
</script>
</body>
</html>
"""

        @app.get("/")
        def index():
            title = html.escape(str(dcfg.get("title", "Personal Assistant Dashboard")))
            return dashboard_template.replace("__TITLE__", title)

        @app.get("/api/status")
        def api_status():
            return jsonify(runtime_snapshot())

        @app.get("/api/events")
        def api_events():
            limit = parse_bounded_int(request.args.get("limit", "25"), 25, 1, 200)
            events = DB.get_recent_events(limit=limit) if DB else []
            return jsonify(
                {
                    "limit": limit,
                    "events": events,
                }
            )

        @app.get("/api/errors")
        def api_errors():
            limit = parse_bounded_int(request.args.get("limit", "20"), 20, 1, 100)
            with RUNTIME_LOCK:
                errors = list(RUNTIME_STATE.get("last_errors", []))
            return jsonify(
                {
                    "limit": limit,
                    "errors": list(reversed(errors[-limit:])),
                }
            )

        @app.get("/api/capabilities")
        def api_capabilities():
            return jsonify(
                {
                    "platform": platform.system(),
                    "capabilities": PLATFORM_ADAPTER.capabilities(),
                }
            )

        @app.get("/api/score")
        def api_score():
            snap = runtime_snapshot()
            return jsonify(snap.get("daily_score", {}))

        @app.route("/action/pause", methods=action_methods)
        def action_pause():
            minutes = parse_bounded_int(request.values.get("minutes", "30"), 30, 1, 720)
            set_pause(minutes)
            return action_response("pause", f"Paused reminders for {minutes} minutes.", minutes=minutes)

        @app.route("/action/snooze", methods=action_methods)
        def action_snooze():
            minutes = parse_bounded_int(request.values.get("minutes", "15"), 15, 1, 720)
            set_snooze(minutes)
            return action_response("snooze", f"Snoozed reminders for {minutes} minutes.", minutes=minutes)

        @app.route("/action/clear_pause", methods=action_methods)
        def action_clear_pause():
            clear_pause()
            notify("Control", "Pause cleared.", force=True)
            return action_response("clear_pause", "Pause has been cleared.")

        @app.route("/action/clear_snooze", methods=action_methods)
        def action_clear_snooze():
            clear_snooze()
            notify("Control", "Snooze cleared.", force=True)
            return action_response("clear_snooze", "Snooze has been cleared.")

        @app.route("/action/focus", methods=action_methods)
        def action_focus():
            minutes = parse_bounded_int(request.values.get("minutes", "90"), 90, 1, 720)
            enable_focus_mode(minutes)
            return action_response("focus", f"Focus mode enabled for {minutes} minutes.", minutes=minutes)

        @app.route("/action/focus_off", methods=action_methods)
        def action_focus_off():
            disable_focus_mode()
            return action_response("focus_off", "Focus mode disabled.")

        @app.route("/action/mode", methods=action_methods)
        def action_mode():
            mode = str(request.values.get("mode", "")).strip().lower()
            if not mode:
                return action_error("Mode is required.")
            if not set_mode(mode):
                return action_error("Unknown mode.")
            notify("Mode", f"Active mode set to {mode}.", force=True)
            return action_response("mode", f"Mode switched to {mode}.", mode=mode)

        @app.route("/action/quran_goal", methods=action_methods)
        def action_quran_goal():
            units = parse_bounded_int(request.values.get("units", "1"), 1, 1, 60)
            final = set_quran_daily_goal(units)
            notify("Quran Goal", f"Daily goal set to {final} units.", category="quran", force=True)
            return action_response("quran_goal", f"Daily Quran goal set to {final}.", units=final)

        @app.route("/action/mark_prayer", methods=action_methods)
        def action_mark_prayer():
            prayer = str(request.values.get("prayer", "")).strip().lower()
            status = str(request.values.get("status", "prayed")).strip().lower()
            if prayer not in {"fajr", "dhuhr", "asr", "maghrib", "isha"}:
                return action_error("Unknown prayer name.")
            if status not in {"prayed", "missed"}:
                return action_error("Status must be prayed or missed.")
            if not DB:
                return action_error("Database is not ready.", code=500)
            DB.upsert_prayer_status(day_key(), prayer, status, "dashboard_manual")
            notify("Prayer", f"{prayer} marked as {status}.", category="prayers", force=True)
            return action_response("mark_prayer", f"{prayer} marked as {status}.", prayer=prayer, status=status)

        @app.route("/action/toggle/<feature>", methods=action_methods)
        def action_toggle(feature: str):
            feature_name = re.sub(r"[^a-zA-Z0-9_-]", "", (feature or "").strip().lower())
            with CONTROL_LOCK:
                known_features = set(CONTROL_STATE.get("feature_toggles", {}).keys())

            if not feature_name:
                return action_error("Feature key is empty.")
            if feature_name not in known_features:
                return action_error(
                    f"Unknown feature '{feature_name}'. Available: {', '.join(sorted(known_features))}"
                )

            desired_state = str(request.values.get("state", "")).strip().lower()
            if desired_state in {"on", "true", "1", "enable", "enabled"}:
                set_feature_enabled(feature_name, True)
                new_state = True
            elif desired_state in {"off", "false", "0", "disable", "disabled"}:
                set_feature_enabled(feature_name, False)
                new_state = False
            else:
                new_state = toggle_feature(feature_name)

            notify("Dashboard", f"Feature {feature_name} set to {new_state}", force=True)
            return action_response(
                "toggle",
                f"Feature {feature_name} is now {'ON' if new_state else 'OFF'}.",
                feature=feature_name,
                enabled=new_state,
            )

        @app.route("/action/quran_reset", methods=action_methods)
        def action_quran_reset():
            db_ref = self.db or DB
            if not db_ref:
                return action_error("Database is not ready.", code=500)

            mode = normalize_mode(
                request.values.get("mode", self.config.get("quran_khatma", {}).get("mode", "rub"))
            )
            max_units = int(QURAN_MODE_META[mode]["count"])
            qcfg = self.config.get("quran_khatma", {})
            start_unit = parse_bounded_int(
                qcfg.get(f"start_{mode}", qcfg.get("start_unit", 1)),
                1,
                1,
                max_units,
            )
            custom_unit_raw = request.values.get("unit")
            if custom_unit_raw not in {None, ""}:
                start_unit = parse_bounded_int(custom_unit_raw, start_unit, 1, max_units)

            set_quran_current_unit(mode, start_unit, db_ref)
            if mode == "rub":
                try:
                    LEGACY_QURAN_STATE_PATH.write_text(
                        json.dumps({"current_rub": start_unit}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as exc:
                    register_error("quran_legacy_state_write", str(exc))

            notify("Quran", f"Mode {mode} reset to unit {start_unit}.", category="quran", force=True)
            return action_response(
                "quran_reset",
                f"Quran mode {mode} reset to unit {start_unit}.",
                mode=mode,
                unit=start_unit,
            )

        host = dcfg.get("host", "127.0.0.1")
        port = parse_bounded_int(dcfg.get("port", 5099), 5099, 1, 65535)
        LOGGER.info("Dashboard started at http://%s:%s", host, port)
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


class TrayThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("TrayThread", config, db)

    def loop(self):
        tcfg = self.config.get("tray", {})
        if not tcfg.get("enabled", False):
            return
        if not HAS_TRAY:
            return

        def create_icon_image() -> "Image.Image":
            img = Image.new("RGB", (64, 64), "#0f172a")
            draw = ImageDraw.Draw(img)
            draw.ellipse((8, 8, 56, 56), fill="#38bdf8")
            draw.rectangle((30, 16, 34, 48), fill="#0f172a")
            return img

        def action_status(icon, item):
            snap = runtime_snapshot()
            notify("Status", format_snapshot_text(snap), force=True)

        def action_pause(icon, item):
            set_pause(30)

        def action_snooze(icon, item):
            set_snooze(15)

        def action_focus(icon, item):
            enable_focus_mode(90)

        def action_focus_off(icon, item):
            disable_focus_mode()

        def action_quit(icon, item):
            STOP_EVENT.set()
            disable_focus_mode()
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("Status", action_status),
            pystray.MenuItem("Pause 30m", action_pause),
            pystray.MenuItem("Snooze 15m", action_snooze),
            pystray.MenuItem("Focus 90m", action_focus),
            pystray.MenuItem("Focus Off", action_focus_off),
            pystray.MenuItem("Quit", action_quit),
        )

        icon = pystray.Icon("personal_assistant", create_icon_image(), "Assistant", menu)
        icon.run()


class TelegramBotThread(ManagedThread):
    def __init__(self, config: Dict[str, Any], db: AssistantDB):
        super().__init__("TelegramBotThread", config, db)

    def loop(self):
        tcfg = self.config.get("telegram_bot", {})
        if not tcfg.get("enabled", False):
            return
        if not HAS_TELEGRAM:
            return

        token = tcfg.get("token", "")
        if not token:
            LOGGER.warning("Telegram bot enabled but token is missing")
            return

        allowed_ids = set(int(x) for x in tcfg.get("allowed_chat_ids", []) if str(x).strip())
        default_focus = int(tcfg.get("default_focus_minutes", 90))
        default_snooze = int(tcfg.get("default_snooze_minutes", 15))
        allow_desktop_observe = bool(tcfg.get("allow_desktop_observe", True))
        allow_power_commands = bool(tcfg.get("allow_power_commands", False))
        require_ids_for_control = bool(tcfg.get("require_allowed_chat_ids_for_control", True))

        async def authorized(update: Update, require_control: bool = False) -> bool:
            chat = update.effective_chat
            if not chat:
                return False
            if require_control and require_ids_for_control and not allowed_ids:
                if update.message:
                    await update.message.reply_text(
                        "Control commands are blocked until telegram_bot.allowed_chat_ids is configured."
                    )
                return False
            if not allowed_ids:
                return True
            if chat.id in allowed_ids:
                return True
            if update.message:
                await update.message.reply_text("Unauthorized chat id")
            return False

        async def reply_text_chunked(update: Update, text: str):
            if not update.message:
                return
            chunk_size = 3900
            for i in range(0, len(text), chunk_size):
                await update.message.reply_text(text[i : i + chunk_size])

        async def send_text(update: Update, text: str, reply_markup=None):
            if update.message:
                await update.message.reply_text(text, reply_markup=reply_markup)
                return
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

        def build_control_panel_markup() -> InlineKeyboardMarkup:
            rows = [
                [
                    InlineKeyboardButton("Pause 15m", callback_data="act_pause_15"),
                    InlineKeyboardButton("Snooze 15m", callback_data="act_snooze_15"),
                ],
                [
                    InlineKeyboardButton("Focus 90m", callback_data="act_focus_90"),
                    InlineKeyboardButton("Focus Off", callback_data="act_focus_off"),
                ],
                [
                    InlineKeyboardButton("Prayed Fajr", callback_data="act_mark_prayer_done_fajr"),
                    InlineKeyboardButton("Prayed Dhuhr", callback_data="act_mark_prayer_done_dhuhr"),
                ],
                [
                    InlineKeyboardButton("Prayed Asr", callback_data="act_mark_prayer_done_asr"),
                    InlineKeyboardButton("Prayed Maghrib", callback_data="act_mark_prayer_done_maghrib"),
                ],
                [
                    InlineKeyboardButton("Prayed Isha", callback_data="act_mark_prayer_done_isha"),
                ],
            ]
            return InlineKeyboardMarkup(rows)

        def desktop_observe_allowed() -> Tuple[bool, str]:
            if not allow_desktop_observe:
                return False, "Desktop observe commands are disabled in config."
            return True, ""

        async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            text = format_snapshot_text(runtime_snapshot())
            if update.message:
                await update.message.reply_text(text)

        async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return

            snap_text = format_snapshot_text(runtime_snapshot())
            ok, cal_text = await asyncio.to_thread(get_today_calendar_summary_text, self.config)
            cal_title = "Today's Calendar" if ok else "Calendar Status"
            header = (
                f"أهلاً يا {self.config.get('user_name', 'صاحبي')}!\n"
                f"Today is {now_local().strftime('%A %d-%m-%Y')}"
            )
            text = f"{header}\n\n{snap_text}\n\n{cal_title}:\n{cal_text}"
            await reply_text_chunked(update, text)

        async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            if not is_feature_enabled("telegram_inline_panel"):
                await send_text(update, "Inline panel is disabled by feature flag.")
                return
            await send_text(update, "Control Panel", reply_markup=build_control_panel_markup())

        async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            mode = (context.args[0] if context.args else "").strip().lower()
            if not mode:
                await send_text(update, f"Current mode: {current_mode()}. Usage: /mode <workday|light|ramadan>")
                return
            if not set_mode(mode):
                await send_text(update, "Unknown mode. Use: workday, light, ramadan")
                return
            await send_text(update, f"Mode switched to {mode}.")

        async def cmd_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            if not context.args:
                await send_text(update, f"Quran daily goal: {get_quran_daily_goal()} unit(s). Usage: /goal [units]")
                return
            units = parse_int_arg(context.args[0], default=get_quran_daily_goal(), min_value=1, max_value=60)
            final = set_quran_daily_goal(units)
            await send_text(update, f"Quran daily goal set to {final} unit(s).")

        async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            await send_text(update, build_weekly_summary_text())

        async def cmd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            if not query:
                return
            await query.answer()
            if not await authorized(update, require_control=True):
                return

            data = str(query.data or "")
            if data == "act_pause_15":
                set_pause(15)
                await send_text(update, "Paused for 15 minutes.")
                return
            if data == "act_snooze_15":
                set_snooze(15)
                await send_text(update, "Snoozed for 15 minutes.")
                return
            if data == "act_focus_90":
                enable_focus_mode(90)
                await send_text(update, "Focus mode enabled for 90 minutes.")
                return
            if data == "act_focus_off":
                disable_focus_mode()
                await send_text(update, "Focus mode disabled.")
                return
            if data.startswith("act_mark_prayer_done_"):
                prayer_name = data.replace("act_mark_prayer_done_", "", 1)
                if prayer_name not in {"fajr", "dhuhr", "asr", "maghrib", "isha"}:
                    await send_text(update, "Unknown prayer.")
                    return
                if DB:
                    DB.upsert_prayer_status(day_key(), prayer_name, "prayed", "telegram_panel")
                await send_text(update, f"{prayer_name} marked as prayed.")
                return
            if data.startswith("act_confirm_power:"):
                token_val = data.split(":", 1)[1]
                payload = SENSITIVE_ACTIONS.consume(token_val)
                if not payload:
                    await send_text(update, "Confirmation token expired.")
                    return
                action_name, value = payload.split("|", 1)
                ok, msg = await asyncio.to_thread(execute_power_action, action_name, value)
                await send_text(update, msg if ok else f"{action_name} failed: {msg}")
                return
            if data == "act_cancel_sensitive":
                await send_text(update, "Action canceled.")
                return

        async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            if update.message and update.effective_chat:
                await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")

        async def cmd_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            try:
                minutes = int(context.args[0]) if context.args else default_snooze
            except Exception:
                minutes = default_snooze
            set_snooze(minutes)
            if update.message:
                await update.message.reply_text(f"Snoozed for {minutes} minutes")

        async def cmd_focus(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            try:
                minutes = int(context.args[0]) if context.args else default_focus
            except Exception:
                minutes = default_focus
            enable_focus_mode(minutes)
            if update.message:
                await update.message.reply_text(f"Focus mode enabled for {minutes} minutes")

        async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            try:
                minutes = int(context.args[0]) if context.args else 30
            except Exception:
                minutes = 30
            set_pause(minutes)
            if update.message:
                await update.message.reply_text(f"Paused for {minutes} minutes")

        async def cmd_focus_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            disable_focus_mode()
            if update.message:
                await update.message.reply_text("Focus mode disabled.")

        async def cmd_windows(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            ok, reason = desktop_observe_allowed()
            if not ok:
                if update.message:
                    await update.message.reply_text(reason)
                return

            limit = parse_int_arg(context.args[0] if context.args else None, default=20, min_value=1, max_value=80)
            windows = await asyncio.to_thread(list_open_windows, limit)
            if not windows:
                text = (
                    "No windows found.\n"
                    "Try running under the same desktop session and install one of: wmctrl, xdotool, xwininfo."
                )
            else:
                text = "Open windows:\n" + "\n".join(f"- {w}" for w in windows)
            await reply_text_chunked(update, text)

        async def cmd_tabs(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            ok, reason = desktop_observe_allowed()
            if not ok:
                if update.message:
                    await update.message.reply_text(reason)
                return

            limit = parse_int_arg(context.args[0] if context.args else None, default=20, min_value=1, max_value=80)
            rows = await asyncio.to_thread(list_browser_tab_like_titles, limit)
            if not rows:
                text = (
                    "No browser windows/tabs-like titles found.\n"
                    "Tip: install wmctrl/xdotool. Full tab list is not universally available for all browsers."
                )
            else:
                text = "Browser tab/window titles (best effort):\n" + "\n".join(f"- {x}" for x in rows)
            await reply_text_chunked(update, text)

        async def cmd_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            ok, reason = desktop_observe_allowed()
            if not ok:
                if update.message:
                    await update.message.reply_text(reason)
                return

            title = await asyncio.to_thread(get_active_window_title)
            if update.message:
                await update.message.reply_text(f"Active window:\n{title}")

        async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            ok, reason = desktop_observe_allowed()
            if not ok:
                if update.message:
                    await update.message.reply_text(reason)
                return
            if not update.message:
                return

            temp_file = tempfile.NamedTemporaryFile(prefix="assistant_shot_", suffix=".png", delete=False)
            temp_file.close()
            shot_path = Path(temp_file.name)
            try:
                success, backend = await asyncio.to_thread(capture_screenshot, shot_path)
                if not success:
                    await update.message.reply_text(f"Screenshot failed: {backend}")
                    return
                with shot_path.open("rb") as f:
                    await update.message.reply_photo(photo=f, caption=f"Screenshot captured via {backend}")
            finally:
                try:
                    shot_path.unlink(missing_ok=True)
                except Exception:
                    pass

        async def cmd_ps(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            limit = parse_int_arg(context.args[0] if context.args else None, default=10, min_value=1, max_value=40)
            report = await asyncio.to_thread(get_top_processes, limit)
            await reply_text_chunked(update, f"Top processes:\n{report}")

        async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            raw_command = " ".join(context.args).strip()
            if not raw_command:
                if update.message:
                    await update.message.reply_text("Usage: /run <allowlisted command>")
                return
            ok, output = await asyncio.to_thread(run_allowlisted_shell_command, raw_command, tcfg)
            await reply_text_chunked(update, output)
            if not ok:
                return

        async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            ok, msg = await asyncio.to_thread(execute_lock_screen)
            if update.message:
                await update.message.reply_text(msg if ok else f"Lock failed: {msg}")

        async def cmd_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            ok, msg = await asyncio.to_thread(execute_suspend)
            if update.message:
                await update.message.reply_text(msg if ok else f"Suspend failed: {msg}")

        async def cmd_shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            if not allow_power_commands:
                if update.message:
                    await update.message.reply_text("Power commands are disabled in config.")
                return
            value = context.args[0] if context.args else "now"
            if is_feature_enabled("telegram_sensitive_confirm"):
                token_val = SENSITIVE_ACTIONS.create(f"shutdown|{value}")
                kb = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Confirm Shutdown", callback_data=f"act_confirm_power:{token_val}")],
                        [InlineKeyboardButton("Cancel", callback_data="act_cancel_sensitive")],
                    ]
                )
                if update.message:
                    await update.message.reply_text("Confirm shutdown action:", reply_markup=kb)
                return
            ok, msg = await asyncio.to_thread(execute_power_action, "shutdown", value)
            if update.message:
                await update.message.reply_text(msg if ok else f"Shutdown failed: {msg}")

        async def cmd_reboot(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            if not allow_power_commands:
                if update.message:
                    await update.message.reply_text("Power commands are disabled in config.")
                return
            value = context.args[0] if context.args else "now"
            if is_feature_enabled("telegram_sensitive_confirm"):
                token_val = SENSITIVE_ACTIONS.create(f"reboot|{value}")
                kb = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Confirm Reboot", callback_data=f"act_confirm_power:{token_val}")],
                        [InlineKeyboardButton("Cancel", callback_data="act_cancel_sensitive")],
                    ]
                )
                if update.message:
                    await update.message.reply_text("Confirm reboot action:", reply_markup=kb)
                return
            ok, msg = await asyncio.to_thread(execute_power_action, "reboot", value)
            if update.message:
                await update.message.reply_text(msg if ok else f"Reboot failed: {msg}")

        async def cmd_cancel_power(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            if not allow_power_commands:
                if update.message:
                    await update.message.reply_text("Power commands are disabled in config.")
                return
            ok, msg = await asyncio.to_thread(execute_power_action, "cancel", None)
            if update.message:
                await update.message.reply_text(msg if ok else f"Cancel failed: {msg}")

        async def cmd_quit_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update, require_control=True):
                return
            STOP_EVENT.set()
            if update.message:
                await update.message.reply_text("Assistant shutdown requested.")

        async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            text = (
                "Commands:\n"
                "/today\n"
                "/status\n"
                "/chatid\n"
                "/panel\n"
                "/mode <workday|light|ramadan>\n"
                "/goal [units]\n"
                "/weekly\n"
                "/snooze [min]\n"
                "/pause [min]\n"
                "/focus [min]\n"
                "/focusoff\n"
                "/windows [limit]\n"
                "/tabs [limit]\n"
                "/active\n"
                "/screenshot\n"
                "/ps [limit]\n"
                "/run <command>\n"
                "/lock\n"
                "/sleep\n"
                "/shutdown [now|min]\n"
                "/reboot [now|min]\n"
                "/cancelpower\n"
                "/quitassistant"
            )
            if update.message:
                await update.message.reply_text(text)

        async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await authorized(update):
                return
            await cmd_today(update, context)
            if is_feature_enabled("telegram_inline_panel"):
                await cmd_panel(update, context)
            await cmd_help(update, context)

        async def post_init_notify(application: TelegramApplication):
            if not allowed_ids:
                schedule_dashboard_browser_open(self.config, reason="telegram_startup_no_allowed_ids")
                return
            try:
                snap_text = format_snapshot_text(runtime_snapshot())
                ok, cal_text = await asyncio.to_thread(get_today_calendar_summary_text, self.config)
                cal_title = "Today's Calendar" if ok else "Calendar Status"
                header = (
                    f"Assistant started.\n"
                    f"أهلاً يا {self.config.get('user_name', 'صاحبي')}!\n"
                    f"Today is {now_local().strftime('%A %d-%m-%Y')}"
                )
                text = f"{header}\n\n{snap_text}\n\n{cal_title}:\n{cal_text}"
                chunk_size = 3900
                for chat_id in sorted(allowed_ids):
                    for i in range(0, len(text), chunk_size):
                        await application.bot.send_message(chat_id=chat_id, text=text[i : i + chunk_size])
            except Exception as exc:
                register_error("telegram_startup_notice", str(exc))
            finally:
                schedule_dashboard_browser_open(self.config, reason="telegram_startup_notice")

        builder = TelegramApplication.builder().token(token)
        if allowed_ids:
            builder = builder.post_init(post_init_notify)
        app = builder.build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("today", cmd_today))
        app.add_handler(CommandHandler("chatid", cmd_chatid))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("panel", cmd_panel))
        app.add_handler(CommandHandler("mode", cmd_mode))
        app.add_handler(CommandHandler("goal", cmd_goal))
        app.add_handler(CommandHandler("weekly", cmd_weekly))
        app.add_handler(CommandHandler("snooze", cmd_snooze))
        app.add_handler(CommandHandler("pause", cmd_pause))
        app.add_handler(CommandHandler("focus", cmd_focus))
        app.add_handler(CommandHandler("focusoff", cmd_focus_off))
        app.add_handler(CommandHandler("windows", cmd_windows))
        app.add_handler(CommandHandler("tabs", cmd_tabs))
        app.add_handler(CommandHandler("active", cmd_active))
        app.add_handler(CommandHandler("screenshot", cmd_screenshot))
        app.add_handler(CommandHandler("ps", cmd_ps))
        app.add_handler(CommandHandler("run", cmd_run))
        app.add_handler(CommandHandler("lock", cmd_lock))
        app.add_handler(CommandHandler("sleep", cmd_sleep))
        app.add_handler(CommandHandler("shutdown", cmd_shutdown))
        app.add_handler(CommandHandler("reboot", cmd_reboot))
        app.add_handler(CommandHandler("cancelpower", cmd_cancel_power))
        app.add_handler(CommandHandler("quitassistant", cmd_quit_assistant))
        app.add_handler(CallbackQueryHandler(cmd_callback))

        LOGGER.info("Telegram bot polling started")
        app.run_polling(stop_signals=None, close_loop=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Personal Assistant")
    parser.add_argument("--status", action="store_true", help="Print current status and exit")
    parser.add_argument("--validate-config", action="store_true", help="Validate config and exit")
    parser.add_argument("--install-autostart", action="store_true", help="Install startup task/entry")
    parser.add_argument("--uninstall-autostart", action="store_true", help="Remove startup task/entry")
    parser.add_argument("--print-capabilities", action="store_true", help="Print platform capabilities and exit")
    parser.add_argument("--run-doctor", action="store_true", help="Run diagnostics and exit")
    return parser.parse_args()


def entry_command() -> str:
    script_path = str(BASE_DIR / "personal_assistant.py")
    if platform.system().lower() == "windows":
        return f'"{sys.executable}" "{script_path}"'
    return f"{shlex.quote(sys.executable)} {shlex.quote(script_path)}"


def install_autostart_cli() -> Tuple[bool, str]:
    if platform.system().lower() == "windows":
        return install_windows_task(entry_command())
    path = install_linux_autostart(entry_command())
    return True, f"Linux autostart entry installed at {path}"


def uninstall_autostart_cli() -> Tuple[bool, str]:
    if platform.system().lower() == "windows":
        return uninstall_windows_task()
    removed = uninstall_linux_autostart()
    if removed:
        return True, "Linux autostart entry removed."
    return True, "Linux autostart entry was not present."


def doctor_report(config: Dict[str, Any]) -> str:
    lines = [
        "Assistant doctor report",
        f"- Platform: {platform.system()}",
        f"- Python: {sys.version.split()[0]}",
        f"- Config path: {CONFIG_PATH}",
        f"- DB path: {config.get('db_path', str(BASE_DIR / 'assistant.db'))}",
        f"- Telegram enabled: {bool(config.get('telegram_bot', {}).get('enabled', False))}",
        f"- Calendar enabled: {bool(config.get('google_calendar', {}).get('enabled', False))}",
        f"- Features: {', '.join(sorted(k for k, v in CONTROL_STATE.get('feature_toggles', {}).items() if v))}",
        "- Capabilities:",
    ]
    for key, value in sorted(PLATFORM_ADAPTER.capabilities().items()):
        lines.append(f"  - {key}: {'yes' if value else 'no'}")
    missing_env = []
    if config.get("security", {}).get("require_env_secrets", True):
        if config.get("telegram_bot", {}).get("enabled", False) and not os.getenv("TELEGRAM_BOT_TOKEN"):
            missing_env.append("TELEGRAM_BOT_TOKEN")
        if config.get("quran_khatma", {}).get("enabled", False):
            if not os.getenv("QURAN_CLIENT_ID"):
                missing_env.append("QURAN_CLIENT_ID")
            if not os.getenv("QURAN_CLIENT_SECRET"):
                missing_env.append("QURAN_CLIENT_SECRET")
    if missing_env:
        lines.append(f"- Missing required env vars: {', '.join(missing_env)}")
    else:
        lines.append("- Required env vars: OK")
    return "\n".join(lines)


def install_signal_handlers():
    def _handler(signum, frame):
        LOGGER.info("signal_received", extra={"signal": signum})
        STOP_EVENT.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def build_threads(config: Dict[str, Any], db: AssistantDB) -> List[threading.Thread]:
    return [
        PrayerReminderThread(config, db),
        PomodoroThread(config, db),
        WorkdayLimitThread(config, db),
        HealthRemindersThread(config, db),
        EyeStrainThread(config, db),
        GoogleCalendarThread(config, db),
        FocusModeThread(config, db),
        DailyReportThread(config, db),
        DashboardThread(config, db),
        TrayThread(config, db),
        TelegramBotThread(config, db),
    ]


def main():
    global APP_CONFIG, APP_TZ, HTTP, DB, FOCUS_MANAGER

    args = parse_args()

    if args.print_capabilities:
        print(json.dumps(PLATFORM_ADAPTER.capabilities(), indent=2, ensure_ascii=False))
        return

    if args.install_autostart:
        ok, msg = install_autostart_cli()
        print(msg)
        if not ok:
            raise SystemExit(1)
        return

    if args.uninstall_autostart:
        ok, msg = uninstall_autostart_cli()
        print(msg)
        if not ok:
            raise SystemExit(1)
        return

    config = load_config()
    APP_CONFIG = config

    if args.run_doctor:
        init_feature_toggles(config)
        print(doctor_report(config))
        return

    errors, warnings = validate_config(config)
    if errors:
        print("Config validation errors:")
        for err in errors:
            print(f"- {err}")
        raise SystemExit(1)

    setup_logging(config.get("log_file", str(BASE_DIR / "assistant.log")))

    for warning in warnings:
        LOGGER.warning("config_warning: %s", warning)

    APP_TZ = ZoneInfo(config.get("timezone", "UTC"))
    HTTP = build_http_session(config.get("http", {}))

    DB = AssistantDB(Path(config.get("db_path", str(BASE_DIR / "assistant.db"))))
    migrate_legacy_quran_state(DB)
    init_feature_toggles(config)
    if is_feature_enabled("personal_modes"):
        set_mode(config.get("personal_modes", {}).get("default_mode", "workday"))

    FOCUS_MANAGER = FocusModeManager()

    if args.validate_config:
        print("Config validation: OK")
        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"- {w}")
        return

    if args.status:
        print_status_cli()
        return

    install_signal_handlers()

    user_name = config.get("user_name", "صاحبي")
    greet = f"أهلاً يا {user_name}! النهارده {now_local().strftime('%A %d-%m-%Y')}"
    print(greet)
    notify("Welcome", greet, force=True)

    threads = build_threads(config, DB)
    early_threads = [t for t in threads if t.name == "TelegramBotThread"]
    for t in early_threads:
        t.start()

    show_today_calendar_summary(config)
    show_quran_gate(config, DB)

    for t in threads:
        if t in early_threads:
            continue
        t.start()

    try:
        while not STOP_EVENT.is_set():
            time.sleep(1)
    finally:
        STOP_EVENT.set()
        disable_focus_mode()
        for t in threads:
            if t.is_alive():
                t.join(timeout=2)
        DB.close()


if __name__ == "__main__":
    main()
