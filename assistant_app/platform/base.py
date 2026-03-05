from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class PlatformAdapter(ABC):
    @abstractmethod
    def notify(self, title: str, body: str, urgency: str = "normal") -> None:
        ...

    @abstractmethod
    def ask_yes_no(self, question: str) -> bool:
        ...

    @abstractmethod
    def capture_screenshot(self, path: Path) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def list_open_windows(self, limit: int = 25) -> List[str]:
        ...

    @abstractmethod
    def get_active_window_title(self) -> str:
        ...

    @abstractmethod
    def lock_screen(self) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def suspend(self) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def power_action(self, action: str, value: Optional[str]) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def apply_focus_web_block(self, domains: List[str], backup_path: str) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def revert_focus_web_block(self, backup_path: str) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def apply_focus_app_block(self, apps: List[str]) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def capabilities(self) -> Dict[str, bool]:
        ...
