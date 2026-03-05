import importlib

import assistant_app.platform as platform_mod


def test_platform_selector_linux(monkeypatch):
    monkeypatch.setattr(platform_mod.platform, "system", lambda: "Linux")
    importlib.reload(platform_mod)
    adapter = platform_mod.get_platform_adapter()
    assert adapter.__class__.__name__ == "LinuxAdapter"


def test_platform_selector_windows(monkeypatch):
    monkeypatch.setattr(platform_mod.platform, "system", lambda: "Windows")
    importlib.reload(platform_mod)
    adapter = platform_mod.get_platform_adapter()
    assert adapter.__class__.__name__ == "WindowsAdapter"
