from __future__ import annotations

import subprocess
from typing import Tuple


TASK_NAME = "PersonalAssistantOnLogon"


def install_windows_task(entry_cmd: str) -> Tuple[bool, str]:
    cmd = [
        "schtasks",
        "/Create",
        "/SC",
        "ONLOGON",
        "/TN",
        TASK_NAME,
        "/TR",
        entry_cmd,
        "/F",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return True, "Windows startup task installed."
    return False, (proc.stderr or proc.stdout or "Failed to install startup task.").strip()


def uninstall_windows_task() -> Tuple[bool, str]:
    cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return True, "Windows startup task removed."
    return False, (proc.stderr or proc.stdout or "Failed to remove startup task.").strip()
