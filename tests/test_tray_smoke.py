"""Smoke-тест трея: агент стартует headless и пишет лог в изолированную папку.

Раньше это был скрипт с побочными эффектами на уровне модуля: он запускался
при сборе тестов, писал в ``data/logs`` рабочей копии и не был pytest-тестом
(0 collected, exit code 5).

Теперь это обычный тест. Он поднимает GUI/трей, поэтому по умолчанию
пропускается; запуск:

    $env:RUN_TRAY_SMOKE="1"; python -m pytest tests/test_tray_smoke.py -q
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_TRAY_SMOKE") != "1",
    reason="GUI/трей-тест запускается явно: RUN_TRAY_SMOKE=1",
)


def _stop(proc: subprocess.Popen, timeout: float = 5.0):
    """Аккуратно останавливает процесс: terminate → kill."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


def test_tray_headless_writes_isolated_log(tmp_path):
    data_dir = tmp_path / "data"
    log_path = data_dir / "logs" / "tray_agent.log"

    env = os.environ.copy()
    env["DIGITAL_BEING_DATA_DIR"] = str(data_dir)
    env["DIGITAL_BEING_TEST_MODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [sys.executable, "main_tray.py", "--headless", "--new"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        # Ждём, пока трей создаст лог, и даём агенту пару секунд пожить.
        deadline = time.time() + 25
        while time.time() < deadline and proc.poll() is None:
            if log_path.exists() and log_path.stat().st_size > 0:
                time.sleep(2)
                break
            time.sleep(0.25)
    finally:
        _stop(proc)

    output, _ = proc.communicate(timeout=5)

    assert log_path.exists(), (
        f"Трей не создал лог в изолированной папке {log_path}. "
        f"Вывод процесса:\n{output}"
    )
    assert log_path.stat().st_size > 0, "Лог трея пуст"

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    # Лог создан именно в изолированной папке — путь виден в первой строке.
    assert str(data_dir) in log_text
    assert "Создаю агента" in log_text or "AgentRunner" in log_text
