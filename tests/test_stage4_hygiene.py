"""Этап 4: гигиена кода.

Проверяем не «нравится/не нравится», а конкретные инварианты:

* сканер действительно находит известные классы проблем;
* в ``src``/``config`` нет ``except:`` без типа, изменяемых значений по
  умолчанию, повторных определений и пустых модулей;
* локальный поиск по коду работает независимо от текущей папки;
* битый JSON отчётов рефлексии не роняет агента.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN_TARGETS = ("src", "config", "main.py", "main_tray.py")


def _load_scanner():
    """Загружает tools/hygiene_scan.py как модуль (tools — не пакет)."""
    path = PROJECT_ROOT / "tools" / "hygiene_scan.py"
    name = "hygiene_scan_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SCANNER = _load_scanner()


@pytest.fixture(scope="module")
def repo_issues():
    issues = []
    for target in SCAN_TARGETS:
        path = PROJECT_ROOT / target
        files = [path] if path.is_file() else path.rglob("*.py")
        for file in files:
            if "__pycache__" in file.parts:
                continue
            issues.extend(SCANNER.scan_file(file).issues)
    return issues


def test_scanner_detects_known_problem_kinds(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os\n"
        "\n"
        "def duplicate(items=[]):\n"
        "    try:\n"
        "        return items\n"
        "    except:\n"
        "        pass\n"
        "\n"
        "def duplicate():\n"
        "    return 1\n",
        encoding="utf-8",
    )

    kinds = {issue.kind for issue in SCANNER.scan_file(sample).issues}
    assert {
        "unused-import",
        "mutable-default",
        "bare-except",
        "silent-except",
        "duplicate-def",
    } <= kinds


def test_repo_has_no_bare_excepts(repo_issues):
    problems = [str(issue) for issue in repo_issues if issue.kind == "bare-except"]
    assert problems == []


def test_repo_has_no_mutable_defaults(repo_issues):
    problems = [str(issue) for issue in repo_issues if issue.kind == "mutable-default"]
    assert problems == []


def test_repo_has_no_duplicate_definitions(repo_issues):
    problems = [str(issue) for issue in repo_issues if issue.kind == "duplicate-def"]
    assert problems == []


def test_src_has_no_empty_modules():
    empty = [
        str(path)
        for path in (PROJECT_ROOT / "src").rglob("*.py")
        if path.name != "__init__.py" and path.stat().st_size == 0
    ]
    assert empty == []


def test_save_reflection_report_recovers_from_corrupt_json(tmp_path):
    from src.cognition.reflection_engine import ReflectionEngine

    path = tmp_path / "reports.json"
    path.write_text("{ это не json", encoding="utf-8")

    ReflectionEngine().save_reflection_report({"insight": "ok"}, str(path))

    assert json.loads(path.read_text(encoding="utf-8")) == [{"insight": "ok"}]


def test_src_file_index_does_not_depend_on_cwd(tmp_path, monkeypatch):
    from src.cognition.thinking_pipeline import ThinkingPipeline

    ThinkingPipeline._invalidate_src_file_index()
    monkeypatch.chdir(tmp_path)

    index = ThinkingPipeline._get_src_file_index()

    assert "core/agent.py" in index
    assert "cognition/thinking_pipeline.py" in index
