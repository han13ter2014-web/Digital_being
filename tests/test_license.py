"""Единая AGPLv3 для пакета, репозитория и установщика."""

from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]


def test_repository_and_installer_carry_full_agplv3():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    installer_text = (ROOT / "installer" / "license.txt").read_text(encoding="utf-8")

    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
    assert installer_text.startswith(license_text)
    assert "НЕ УСЛОВИЕ ЛИЦЕНЗИИ" in installer_text
    assert "не являются дополнительными лицензионными условиями" in installer_text


@pytest.mark.skipif(tomllib is None, reason="tomllib требует Python >= 3.11")
def test_package_and_readmes_declare_agpl3_only():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["license"]["text"] == "AGPL-3.0-only"
    for name in ("README.md", "README.en.md", "README.zh-CN.md"):
        assert "AGPL-3.0-only" in (ROOT / name).read_text(encoding="utf-8")
