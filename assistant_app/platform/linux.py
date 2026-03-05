from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


try:
    import mss
    import mss.tools

    HAS_MSS = True
except Exception:
    HAS_MSS = False

try:
    from PIL import ImageGrab

    HAS_IMAGEGRAB = True
except Exception:
    HAS_IMAGEGRAB = False

from .base import PlatformAdapter


class LinuxAdapter(PlatformAdapter):
    def _run(self, cmd: List[str], timeout: int = 20) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
            return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
        except subprocess.TimeoutExpired:
            return 124, "", f"Timed out after {timeout}s"
        except FileNotFoundError:
            return 127, "", f"Command not found: {cmd[0]}"
        except Exception as exc:
            return 1, "", str(exc)

    def notify(self, title: str, body: str, urgency: str = "normal") -> None:
        if shutil.which("notify-send"):
            level = "critical" if urgency == "critical" else "normal"
            subprocess.run(["notify-send", "-u", level, title, body], check=False)
            return
        if shutil.which("zenity"):
            flag = "--warning" if urgency == "critical" else "--info"
            subprocess.Popen(
                ["zenity", flag, "--width=420", "--height=180", "--title", title, "--text", body],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        print(f"[NOTIFY] {title}: {body}")

    def ask_yes_no(self, question: str) -> bool:
        if shutil.which("zenity"):
            result = subprocess.run(["zenity", "--question", "--text", question], check=False)
            return result.returncode == 0
        return False

    def capture_screenshot(self, path: Path) -> Tuple[bool, str]:
        session_type = (os.environ.get("XDG_SESSION_TYPE", "") or "").strip().lower()
        is_wayland = session_type == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))

        def cmd_backend(command: List[str], label: str) -> Tuple[bool, str]:
            if not shutil.which(command[0]):
                return False, ""
            rc, _, err = self._run(command, timeout=20)
            if rc == 0 and path.exists() and path.stat().st_size > 0:
                return True, label
            return False, err or label

        if is_wayland:
            for command, label in [
                (["grim", str(path)], "grim"),
                (["grimshot", "save", "screen", str(path)], "grimshot"),
                (["gnome-screenshot", "-f", str(path)], "gnome-screenshot"),
            ]:
                ok, msg = cmd_backend(command, label)
                if ok:
                    return True, msg

        if HAS_MSS:
            try:
                with mss.mss() as sct:
                    shot = sct.grab(sct.monitors[0])
                    mss.tools.to_png(shot.rgb, shot.size, output=str(path))
                if path.exists() and path.stat().st_size > 0:
                    return True, "mss"
            except Exception:
                pass

        if HAS_IMAGEGRAB:
            try:
                img = ImageGrab.grab(all_screens=True)
                img.save(path, format="PNG")
                if path.exists() and path.stat().st_size > 0:
                    return True, "Pillow ImageGrab"
            except Exception:
                pass

        for command, label in [
            (["gnome-screenshot", "-f", str(path)], "gnome-screenshot"),
            (["scrot", str(path)], "scrot"),
            (["import", "-window", "root", str(path)], "import"),
        ]:
            ok, msg = cmd_backend(command, label)
            if ok:
                return True, msg

        return False, f"No screenshot backend available (session={session_type or 'unknown'})."

    def list_open_windows(self, limit: int = 25) -> List[str]:
        rows: List[str] = []
        if shutil.which("wmctrl"):
            rc, out, _ = self._run(["wmctrl", "-lx"], timeout=10)
            if rc == 0 and out:
                for line in out.splitlines():
                    parts = line.split(None, 4)
                    if len(parts) >= 5:
                        rows.append(f"{parts[3]} | {parts[4].strip()}")
        if not rows and shutil.which("xdotool"):
            rc, out, _ = self._run(["xdotool", "search", "--onlyvisible", "--name", "."], timeout=10)
            if rc == 0 and out:
                for win_id in out.splitlines()[: max(limit * 4, 80)]:
                    rc1, title, _ = self._run(["xdotool", "getwindowname", win_id.strip()], timeout=6)
                    rc2, wclass, _ = self._run(["xdotool", "getwindowclassname", win_id.strip()], timeout=6)
                    if rc1 == 0 and title:
                        rows.append(f"{(wclass.strip() if rc2 == 0 and wclass else 'window')} | {title.strip()}")
                        if len(rows) >= limit:
                            break
        if not rows and shutil.which("xwininfo"):
            rc, out, _ = self._run(["xwininfo", "-root", "-tree"], timeout=10)
            if rc == 0 and out:
                for line in out.splitlines():
                    match = re.search(r'"([^"]+)"', line)
                    if match:
                        rows.append(f"window | {match.group(1).strip()}")
                        if len(rows) >= limit:
                            break
        return rows[: max(1, limit)]

    def get_active_window_title(self) -> str:
        if shutil.which("xdotool"):
            rc, out, err = self._run(["xdotool", "getactivewindow", "getwindowname"], timeout=8)
            if rc == 0 and out:
                return out
            if err:
                return f"Error: {err}"
        rows = self.list_open_windows(limit=1)
        return rows[0] if rows else "Active window not available."

    def lock_screen(self) -> Tuple[bool, str]:
        for cmd in [["loginctl", "lock-session"], ["gnome-screensaver-command", "-l"], ["dm-tool", "lock"]]:
            if not shutil.which(cmd[0]):
                continue
            rc, _, err = self._run(cmd, timeout=10)
            if rc == 0:
                return True, f"Lock command executed: {' '.join(cmd)}"
            if err:
                return False, err
        return False, "No lock command available on this system."

    def suspend(self) -> Tuple[bool, str]:
        if not shutil.which("systemctl"):
            return False, "systemctl not found."
        rc, _, err = self._run(["systemctl", "suspend"], timeout=10)
        if rc == 0:
            return True, "Suspend command sent."
        return False, err or f"systemctl returned {rc}"

    def power_action(self, action: str, value: Optional[str]) -> Tuple[bool, str]:
        if not shutil.which("shutdown"):
            return False, "shutdown command not found."

        action = action.lower()
        if action == "cancel":
            rc, _, err = self._run(["shutdown", "-c"], timeout=10)
            if rc == 0:
                return True, "Scheduled shutdown/reboot canceled."
            return False, err or f"shutdown -c returned {rc}"

        delay = (value or "now").strip().lower()
        if delay in ("now", "0"):
            delay_arg = "now"
        else:
            try:
                delay_min = max(1, min(1440, int(delay)))
            except Exception:
                delay_min = 1
            delay_arg = f"+{delay_min}"

        if action == "shutdown":
            cmd = ["shutdown", "-h", delay_arg]
        elif action == "reboot":
            cmd = ["shutdown", "-r", delay_arg]
        else:
            return False, "Unsupported power action."

        rc, _, err = self._run(cmd, timeout=10)
        if rc == 0:
            when = "now" if delay_arg == "now" else delay_arg
            return True, f"{action} scheduled {when}."
        return False, err or f"{' '.join(cmd)} returned {rc}"

    def apply_focus_web_block(self, domains: List[str], backup_path: str) -> Tuple[bool, str]:
        if not domains:
            return True, "No domains to block."
        try:
            backup = Path(backup_path)
            hosts_path = Path("/etc/hosts")
            if not backup.exists() and hosts_path.exists():
                shutil.copy2(hosts_path, backup)
            text = hosts_path.read_text(encoding="utf-8") if hosts_path.exists() else ""
            if "# assistant-focus-mode START" not in text:
                block_lines = ["# assistant-focus-mode START"]
                for domain in domains:
                    block_lines.append(f"127.0.0.1 {domain}")
                block_lines.append("# assistant-focus-mode END")
                text = text.rstrip() + "\n\n" + "\n".join(block_lines) + "\n"
                hosts_path.write_text(text, encoding="utf-8")
            return True, "Hosts block applied."
        except PermissionError:
            return False, "No permission to edit /etc/hosts"
        except Exception as exc:
            return False, str(exc)

    def revert_focus_web_block(self, backup_path: str) -> Tuple[bool, str]:
        try:
            hosts = Path("/etc/hosts")
            if not hosts.exists():
                return True, "Hosts file not found."
            text = hosts.read_text(encoding="utf-8")
            if "# assistant-focus-mode START" in text and "# assistant-focus-mode END" in text:
                pattern = re.compile(
                    re.escape("# assistant-focus-mode START")
                    + r".*?"
                    + re.escape("# assistant-focus-mode END")
                    + r"\n?",
                    flags=re.S,
                )
                text = re.sub(pattern, "", text)
                hosts.write_text(text.strip() + "\n", encoding="utf-8")
                return True, "Hosts block removed."
            backup = Path(backup_path)
            if backup.exists():
                shutil.copy2(backup, hosts)
                return True, "Hosts restored from backup."
            return True, "No focus hosts block to remove."
        except PermissionError:
            return False, "No permission to restore /etc/hosts"
        except Exception as exc:
            return False, str(exc)

    def apply_focus_app_block(self, apps: List[str]) -> Tuple[bool, str]:
        for app in apps:
            try:
                subprocess.run(["pkill", "-f", app], check=False)
            except Exception:
                pass
        return True, "Applied app blocklist."

    def capabilities(self) -> Dict[str, bool]:
        return {
            "notify": bool(shutil.which("notify-send") or shutil.which("zenity")),
            "ask_yes_no": bool(shutil.which("zenity")),
            "screenshot": bool(HAS_MSS or HAS_IMAGEGRAB or shutil.which("gnome-screenshot") or shutil.which("scrot")),
            "window_list": bool(shutil.which("wmctrl") or shutil.which("xdotool") or shutil.which("xwininfo")),
            "lock": bool(shutil.which("loginctl") or shutil.which("gnome-screensaver-command") or shutil.which("dm-tool")),
            "suspend": bool(shutil.which("systemctl")),
            "power": bool(shutil.which("shutdown")),
            "focus_hosts": True,
            "focus_app_kill": bool(shutil.which("pkill")),
        }
