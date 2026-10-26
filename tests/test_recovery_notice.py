"""Сообщение восстановления не запускает жизнь и не меняет её данные."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import main
from src.app.bootstrap import RecoveryRequiredError
from src.app.recovery_notice import show_recovery_notice


def test_notice_closes_temporary_tk_root(monkeypatch):
    root = Mock()
    error = Mock()
    fake_tk = SimpleNamespace(Tk=Mock(return_value=root), messagebox=SimpleNamespace(showerror=error))
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    assert show_recovery_notice("test")
    root.withdraw.assert_called_once()
    error.assert_called_once()
    root.destroy.assert_called_once()


def test_notice_unavailable_does_not_hide_failure(monkeypatch):
    fake_tk = SimpleNamespace(Tk=Mock(side_effect=RuntimeError("no display")), messagebox=Mock())
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    assert not show_recovery_notice("test")


def test_gui_start_failure_shows_notice_without_atexit_save(monkeypatch):
    monkeypatch.setattr("src.app.paths.setup_environment", lambda **kwargs: object())
    monkeypatch.setattr(main, "build_runtime", Mock(side_effect=RecoveryRequiredError("broken")))
    show = Mock(return_value=True)
    monkeypatch.setattr("src.app.recovery_notice.show_recovery_notice", show)
    register = Mock()
    monkeypatch.setattr(main.atexit, "register", register)
    assert main.main(["--ui", "gui"]) == 3
    show.assert_called_once()
    assert not register.called
