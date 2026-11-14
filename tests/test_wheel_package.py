"""Собранный wheel должен содержать весь runtime и неизменяемые ресурсы."""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contains_runtime_packages_and_bootstrap_resources(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for directory in ("src", "config", "data_bootstrap"):
        shutil.copytree(PROJECT_ROOT / directory, source / directory)
    for filename in ("main.py", "main_tray.py", "pyproject.toml", "README.md"):
        shutil.copy2(PROJECT_ROOT / filename, source / filename)

    live_data = source / "data"
    live_data.mkdir()
    (live_data / "do_not_ship.json").write_text("{}", encoding="utf-8")

    dist = tmp_path / "dist"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(dist),
            str(source),
        ],
        cwd=source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheels = list(dist.glob("digital_being-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        entry_points = wheel.read(
            "digital_being-0.1.5.1.dist-info/entry_points.txt"
        ).decode("utf-8")

    expected = {
        "src/app/bootstrap.py",
        "src/metrics/i18n.py",
        "src/core/motivation/__init__.py",
        "data_bootstrap/knowledge_base.json",
        "data_bootstrap/initial_knowledge.json",
        "data_bootstrap/i18n/ru.json",
        "data_bootstrap/i18n/en.json",
    }
    assert expected <= names, f"В wheel отсутствуют: {sorted(expected - names)}"
    assert not any(name.startswith("data/") for name in names)
    assert "digital-being = main:run_long_living_agent" in entry_points
