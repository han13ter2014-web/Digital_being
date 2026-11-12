"""Контракт обязательных CI-gates и отдельного multi-seed soak."""

from configparser import ConfigParser
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _runs(workflow, job):
    return "\n".join(step.get("run", "") for step in workflow["jobs"][job]["steps"])


def test_static_gates_are_mandatory_and_pyflakes_is_removed():
    workflow = _workflow("ci.yml")
    runs = _runs(workflow, "static")
    assert "python -m ruff check src/ config/ tests/ main.py main_tray.py" in runs
    assert (
        "python -m ruff format --check src/ config/ tests/ main.py main_tray.py" in runs
    )
    assert "--explicit-package-bases --no-site-packages --follow-imports=skip" in runs
    assert "main.py main_tray.py" in runs
    assert (
        "python -m bandit -r src/ config/ main.py main_tray.py -ll --skip B101,B601"
        in runs
    )
    assert "pyflakes" not in runs
    assert "|| true" not in runs


def test_windows_runs_the_same_full_regression_as_linux():
    workflow = _workflow("ci.yml")
    test_job = workflow["jobs"]["test"]
    assert "windows-latest" in test_job["strategy"]["matrix"]["os"]
    full_steps = [
        step for step in test_job["steps"] if step.get("name") == "Run full regression"
    ]
    assert len(full_steps) == 1
    assert full_steps[0]["run"] == "python -m pytest -q"
    assert "matrix.os != 'ubuntu-latest'" in full_steps[0]["if"]
    assert "not slow" not in _runs(workflow, "test")
    assert "not long_run" not in _runs(workflow, "test")


def test_coverage_gate_includes_branches():
    workflow = _workflow("ci.yml")
    coverage = _runs(workflow, "test")
    assert "--cov=src --cov=config --cov-branch" in coverage
    assert "--cov-fail-under=$COVERAGE_FAIL_UNDER" in coverage
    parser = ConfigParser()
    parser.read(PROJECT_ROOT / ".coveragerc", encoding="utf-8")
    assert parser.getboolean("run", "branch") is True


def test_soak_is_separate_multi_seed_and_uploads_json():
    workflow = _workflow("soak.yml")
    job = workflow["jobs"]["soak"]
    assert job["strategy"]["matrix"]["seed"] == [1, 7, 23]
    runs = _runs(workflow, "soak")
    assert "tools/manual/autonomous_life_measure.py" in runs
    assert "--cycles \"${{ inputs.cycles || '250' }}\"" in runs
    assert '--seed "${{ matrix.seed }}"' in runs
    assert '--report "soak-reports/seed-${{ matrix.seed }}.json"' in runs
    uploads = [
        step
        for step in job["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
    ]
    assert len(uploads) == 1
    assert uploads[0]["with"]["if-no-files-found"] == "error"
    assert uploads[0]["with"]["path"] == "soak-reports/seed-${{ matrix.seed }}.json"
