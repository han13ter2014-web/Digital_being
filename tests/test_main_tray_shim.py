"""Legacy main_tray entry point delegates to the unified main.py runtime."""

import main_tray
import pytest


def test_tray_shim_adds_tray_mode(monkeypatch):
    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(main_tray, "main", fake_main)
    monkeypatch.setattr(main_tray.sys, "argv", ["main_tray.py"])

    with pytest.warns(DeprecationWarning, match="устарел"):
        assert main_tray.run() == 0
    assert captured["argv"][:2] == ["--ui", "tray"]


def test_tray_shim_preserves_explicit_headless(monkeypatch):
    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(main_tray, "main", fake_main)
    monkeypatch.setattr(main_tray.sys, "argv", ["main_tray.py", "--headless"])

    with pytest.warns(DeprecationWarning, match="устарел"):
        main_tray.run()
    assert captured["argv"] == ["--headless"]
