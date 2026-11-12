"""Единые пины и область статических проверок в локальной среде и CI."""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

try:
    import tomllib
except ImportError:
    pytest.skip("tomllib требует Python >= 3.11", allow_module_level=True)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _pre_commit():
    return yaml.safe_load(
        (PROJECT_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )


def _dependency_groups():
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return pyproject["project"]["optional-dependencies"]


@pytest.mark.parametrize(
    ("package", "repo_suffix"),
    [
        ("ruff", "/ruff-pre-commit"),
        ("mypy", "/mirrors-mypy"),
        ("bandit", "/bandit"),
    ],
)
def test_pre_commit_rev_matches_dependency_pins(package, repo_suffix):
    pre_commit = _pre_commit()
    revisions = [
        repo["rev"]
        for repo in pre_commit["repos"]
        if repo["repo"].endswith(repo_suffix)
    ]
    groups = _dependency_groups()
    pattern = rf"{re.escape(package)}\s*==\s*\d+\.\d+\.\d+\S*"
    pins = {
        group: [dep for dep in deps if re.fullmatch(pattern, dep.strip())]
        for group, deps in groups.items()
        if group in {"dev", "all"}
    }

    assert len(revisions) == 1
    assert set(pins) == {"dev", "all"}
    assert all(len(group_pins) == 1 for group_pins in pins.values())
    expected = revisions[0].strip().lstrip("v")
    for group, group_pins in pins.items():
        actual = group_pins[0].strip().split("==")[-1].lstrip("v")
        assert actual == expected, f"{package}: рассинхрон pre-commit и {group}"


def test_mypy_hook_uses_the_public_entry_point_gate():
    pre_commit = _pre_commit()
    hooks = [
        hook
        for repo in pre_commit["repos"]
        if repo["repo"].endswith("/mirrors-mypy")
        for hook in repo["hooks"]
        if hook["id"] == "mypy"
    ]
    assert len(hooks) == 1
    hook = hooks[0]
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False
    assert hook["args"] == [
        "--config-file",
        "pyproject.toml",
        "--explicit-package-bases",
        "--no-site-packages",
        "--follow-imports=skip",
        "main.py",
        "main_tray.py",
    ]


def test_ruff_hooks_cover_the_same_paths_as_ci():
    pre_commit = _pre_commit()
    hooks = [
        hook
        for repo in pre_commit["repos"]
        if repo["repo"].endswith("/ruff-pre-commit")
        for hook in repo["hooks"]
        if hook["id"] in {"ruff", "ruff-format"}
    ]
    expected = r"^(src/|config/|tests/|main[.]py$|main_tray[.]py$)"
    assert len(hooks) == 2
    assert all(hook["files"] == expected for hook in hooks)
