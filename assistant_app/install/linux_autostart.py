from __future__ import annotations

from pathlib import Path


def autostart_path() -> Path:
    return Path.home() / ".config" / "autostart" / "personal_assistant.desktop"


def install_linux_autostart(entry_cmd: str) -> Path:
    path = autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Exec={entry_cmd}\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Name=Personal Assistant\n"
        "Comment=Runs your productivity assistant on startup\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def uninstall_linux_autostart() -> bool:
    path = autostart_path()
    if path.exists():
        path.unlink()
        return True
    return False
