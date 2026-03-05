from __future__ import annotations

import platform

from .base import PlatformAdapter
from .linux import LinuxAdapter
from .windows import WindowsAdapter


def get_platform_adapter() -> PlatformAdapter:
    system = (platform.system() or "").strip().lower()
    if system == "windows":
        return WindowsAdapter()
    return LinuxAdapter()
