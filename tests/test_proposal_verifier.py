"""Тесты «Эволюция-1»: проба — изолированная проверка предложения.

Верификатор поднимает отдельный процесс Python с временной папкой
данных: рабочая data/ и живой стенд не затрагиваются. Вердикт честный:
«пройдена» только при чистом завершении рабочего процесса.
"""

from pathlib import Path
import subprocess

import pytest

from src.core.paths import DATA_DIR_ENV
from src.evolution.proposal_verifier import verify_config_change


def test_verify_benign_config_change_passes():
    """Безобидный рычаг: проба собирается и проживает такт эволюции."""
    result = verify_config_change("FORGETTING_INTERVAL", 400, cycles=1)
    assert result["ran"] is True
    assert result["passed"] is True, result["log_tail"]


def test_verify_unknown_attr_fails_honestly():
    """Неизвестный рычаг: проба не пройдена, а не «сошлось»."""
    result = verify_config_change("NO_SUCH_TUNABLE", 1, cycles=1)
    assert result["ran"] is True
    assert result["passed"] is False
    assert "неизвестный рычаг" in result["log_tail"]


@pytest.mark.parametrize("outcome", ["success", "timeout", "launch_error"])
def test_verify_removes_temporary_profile_on_every_process_outcome(
    tmp_path, monkeypatch, outcome
):
    sandbox = tmp_path / "probe-profile"
    observed = []

    def make_temp(prefix):
        sandbox.mkdir()
        return str(sandbox)

    def run(*args, **kwargs):
        profile = Path(kwargs["env"][DATA_DIR_ENV])
        observed.append(profile)
        assert profile == sandbox
        (profile / "probe.sqlite3").write_bytes(b"probe")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        if outcome == "launch_error":
            raise OSError("launch failed")
        return subprocess.CompletedProcess(args[0], 0, stdout="VERIFY_OK", stderr="")

    monkeypatch.setattr("src.evolution.proposal_verifier.tempfile.mkdtemp", make_temp)
    monkeypatch.setattr("src.evolution.proposal_verifier.subprocess.run", run)

    result = verify_config_change("FORGETTING_INTERVAL", 400, cycles=1)

    assert observed == [sandbox]
    assert result["ran"] is (outcome != "launch_error")
    assert result["passed"] is (outcome == "success")
    assert not sandbox.exists()


def test_unserializable_spec_returns_honest_failure_and_cleans_profile(
    tmp_path, monkeypatch
):
    sandbox = tmp_path / "invalid-profile"

    def make_temp(prefix):
        sandbox.mkdir()
        return str(sandbox)

    monkeypatch.setattr("src.evolution.proposal_verifier.tempfile.mkdtemp", make_temp)

    result = verify_config_change("FORGETTING_INTERVAL", object(), cycles=1)

    assert result["ran"] is False
    assert result["passed"] is False
    assert result["cycles"] == 0
    assert "подготовить" in result["log_tail"]
    assert not sandbox.exists()
