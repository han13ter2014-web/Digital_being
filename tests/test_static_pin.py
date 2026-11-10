"""Мета-тест k16-38: единый пин ruff в pre-commit и dev-зависимостях.

Инцидент k16-37: локальная версия ruff (0.17.4) расходилась с версией
pre-commit-хука (v0.5.7), из-за чего один файл получал разные вердикты.
Канонический статик — ruff из pre-commit-кэша. Этот тест проверяет,
что rev хука в .pre-commit-config.yaml и пин в dev-зависимостях
pyproject.toml совпадают, и тем самым блокирует их рассинхрон.

Тест не запускает ruff и не ходит в сеть — только парсинг двух файлов.
Парсинг YAML требует PyYAML (импорт — модульный importorskip; при его
отсутствии тест скипается, что видно в счётчиках гейта; сам пакет —
в dev-группе pyproject.toml). tomllib — stdlib Python 3.11+; при её
отсутствии тоже модульный скип.
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

try:
    import tomllib
except ImportError:
    pytest.skip("tomllib требует Python >= 3.11", allow_module_level=True)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ruff_pre_commit_rev_matches_dev_dependency_pin():
    # 1) rev ruff-хука из .pre-commit-config.yaml
    pre_commit = yaml.safe_load(
        (PROJECT_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    ruff_revs = [
        repo["rev"]
        for repo in pre_commit["repos"]
        if repo["repo"].endswith("/ruff-pre-commit")
    ]

    # 2) пин ruff из dev-зависимостей pyproject.toml
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
    ruff_pins = [
        dep
        for dep in dev_deps
        if re.fullmatch(r"ruff\s*==\s*\d+\.\d+\.\d+\S*", dep.strip())
    ]

    assert len(ruff_revs) == 1 and len(ruff_pins) == 1, (
        f"ожидался ровно один rev ruff-хука и один пин ruff в dev, "
        f"получено: revs={ruff_revs}, pins={ruff_pins}"
    )

    # Нормализация префикса 'v': rev=v0.5.7, пин=0.5.7.
    rev_version = ruff_revs[0].strip().lstrip("v")
    pin_version = ruff_pins[0].strip().split("==")[-1].lstrip("v")
    assert rev_version == pin_version, (
        f"рассинхрон канона статика: pre-commit rev={ruff_revs[0]!r} "
        f"vs dev-пин={ruff_pins[0]!r}; обновлять ОДНОВРЕМЕННО "
        f"(docs/static_toolchain.md)"
    )
