from __future__ import annotations

import ctypes
import os
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


class WindowsAdapter(PlatformAdapter):
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
        # Best effort Windows notification using PowerShell script call.
        if shutil.which("powershell"):
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                "$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02;"
                "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template);"
                "$nodes = $xml.GetElementsByTagName('text');"
                f"$nodes.Item(0).AppendChild($xml.CreateTextNode('{title.replace("'", "") }')) > $null;"
                f"$nodes.Item(1).AppendChild($xml.CreateTextNode('{body.replace("'", "") }')) > $null;"
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);"
                "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PersonalAssistant');"
                "$notifier.Show($toast);"
            )
            self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=10)
            return
        print(f"[NOTIFY] {title}: {body}")

    def ask_yes_no(self, question: str) -> bool:
        # Non-blocking conservative default for headless/service mode.
        return False

    def capture_screenshot(self, path: Path) -> Tuple[bool, str]:
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

        return False, "No screenshot backend available on Windows."

    def list_open_windows(self, limit: int = 25) -> List[str]:
        if not shutil.which("powershell"):
            return []
        ps = (
            "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
            "Select-Object -First %d ProcessName,MainWindowTitle | "
            "ForEach-Object {\"$($_.ProcessName) | $($_.MainWindowTitle)\"}" % max(1, limit)
        )
        rc, out, _ = self._run(["powershell", "-NoProfile", "-Command", ps], timeout=12)
        if rc != 0 or not out:
            return []
        return [x.strip() for x in out.splitlines() if x.strip()][: max(1, limit)]

    def get_active_window_title(self) -> str:
        if not shutil.which("powershell"):
            rows = self.list_open_windows(limit=1)
            return rows[0] if rows else "Active window not available."

        ps = (
            "$sig='[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();"
            "$sig2='[DllImport(\"user32.dll\", SetLastError=true, CharSet=CharSet.Auto)] "
            "public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);';"
            "Add-Type -MemberDefinition $sig -Name Native1 -Namespace Win32 > $null;"
            "Add-Type -MemberDefinition $sig2 -Name Native2 -Namespace Win32 > $null;"
            "$h=[Win32.Native1]::GetForegroundWindow();"
            "$sb=New-Object System.Text.StringBuilder 1024;"
            "[Win32.Native2]::GetWindowText($h,$sb,$sb.Capacity) > $null;"
            "$sb.ToString();"
        )
        rc, out, err = self._run(["powershell", "-NoProfile", "-Command", ps], timeout=8)
        if rc == 0 and out:
            return out.strip()
        return err or "Active window not available."

    def lock_screen(self) -> Tuple[bool, str]:
        try:
            ok = ctypes.windll.user32.LockWorkStation()
            if ok:
                return True, "LockWorkStation executed."
            return False, "LockWorkStation returned failure."
        except Exception as exc:
            return False, str(exc)

    def suspend(self) -> Tuple[bool, str]:
        if not shutil.which("rundll32"):
            return False, "rundll32 not found."
        rc, _, err = self._run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], timeout=15)
        if rc == 0:
            return True, "Suspend command sent."
        return False, err or f"rundll32 returned {rc}"

    def power_action(self, action: str, value: Optional[str]) -> Tuple[bool, str]:
        action = action.lower()
        if not shutil.which("shutdown"):
            return False, "shutdown command not found."

        if action == "cancel":
            rc, _, err = self._run(["shutdown", "/a"], timeout=10)
            if rc == 0:
                return True, "Scheduled shutdown/reboot canceled."
            return False, err or f"shutdown /a returned {rc}"

        if (value or "now").strip().lower() in {"now", "0"}:
            seconds = 0
        else:
            try:
                seconds = max(60, min(86400, int(value) * 60))
            except Exception:
                seconds = 60

        if action == "shutdown":
            cmd = ["shutdown", "/s", "/t", str(seconds)]
        elif action == "reboot":
            cmd = ["shutdown", "/r", "/t", str(seconds)]
        else:
            return False, "Unsupported power action."

        rc, _, err = self._run(cmd, timeout=10)
        if rc == 0:
            return True, f"{action} scheduled in {seconds} seconds."
        return False, err or f"{' '.join(cmd)} returned {rc}"

    def apply_focus_web_block(self, domains: List[str], backup_path: str) -> Tuple[bool, str]:
        if not domains:
            return True, "No domains to block."
        hosts = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "drivers" / "etc" / "hosts"
        backup = Path(backup_path)
        try:
            if not backup.exists() and hosts.exists():
                shutil.copy2(hosts, backup)
            text = hosts.read_text(encoding="utf-8") if hosts.exists() else ""
            if "# assistant-focus-mode START" not in text:
                block = ["# assistant-focus-mode START"]
                for d in domains:
                    block.append(f"127.0.0.1 {d}")
                block.append("# assistant-focus-mode END")
                hosts.write_text(text.rstrip() + "\n\n" + "\n".join(block) + "\n", encoding="utf-8")
            return True, "Hosts block applied."
        except PermissionError:
            return False, "No permission to edit Windows hosts file."
        except Exception as exc:
            return False, str(exc)

    def revert_focus_web_block(self, backup_path: str) -> Tuple[bool, str]:
        hosts = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "drivers" / "etc" / "hosts"
        backup = Path(backup_path)
        try:
            if hosts.exists():
                text = hosts.read_text(encoding="utf-8")
                if "# assistant-focus-mode START" in text and "# assistant-focus-mode END" in text:
                    import re

                    pattern = re.compile(
                        re.escape("# assistant-focus-mode START")
                        + r".*?"
                        + re.escape("# assistant-focus-mode END")
                        + r"\n?",
                        flags=re.S,
                    )
                    hosts.write_text(re.sub(pattern, "", text).strip() + "\n", encoding="utf-8")
                    return True, "Hosts block removed."
            if backup.exists():
                shutil.copy2(backup, hosts)
                return True, "Hosts restored from backup."
            return True, "No hosts block to revert."
        except PermissionError:
            return False, "No permission to restore Windows hosts file."
        except Exception as exc:
            return False, str(exc)

    def apply_focus_app_block(self, apps: List[str]) -> Tuple[bool, str]:
        if not apps:
            return True, "No apps to block."
        for app in apps:
            self._run(["taskkill", "/F", "/IM", f"{app}.exe"], timeout=8)
        return True, "Applied app blocklist."

    def capabilities(self) -> Dict[str, bool]:
        return {
            "notify": bool(shutil.which("powershell")),
            "ask_yes_no": False,
            "screenshot": bool(HAS_MSS or HAS_IMAGEGRAB),
            "window_list": bool(shutil.which("powershell")),
            "lock": True,
            "suspend": bool(shutil.which("rundll32")),
            "power": bool(shutil.which("shutdown")),
            "focus_hosts": True,
            "focus_app_kill": bool(shutil.which("taskkill")),
        }
