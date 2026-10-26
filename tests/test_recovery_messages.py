"""Отказ восстановления объясняется до запуска и регистрации финального сохранения."""

from unittest.mock import Mock

import pytest

import main
from src.app.bootstrap import RecoveryRequiredError


@pytest.mark.parametrize("args", [["--ui", "headless"], ["--maturity-json"]])
def test_recovery_failure_returns_nonzero_without_atexit_save(monkeypatch, capsys, args):
    monkeypatch.setattr("src.app.paths.setup_environment", lambda **kwargs: object())
    monkeypatch.setattr(main, "build_runtime", Mock(side_effect=RecoveryRequiredError("повреждён снимок")))
    register = Mock()
    monkeypatch.setattr(main.atexit, "register", register)
    assert main.main(args) == 3
    assert not register.called
    error = capsys.readouterr().err
    assert "Восстановление жизни остановлено" in error
    assert "--new" in error
    assert "Traceback" not in error
