"""Тесты «Творчество+»: рисунок как артефакт — детерминизм, редакции, гигиена."""

from pathlib import Path

import pytest

from src.cognition.local_art import (
    ART_LIMIT,
    art_available,
    art_step,
    art_thumbnail,
    leave_art,
    render_svg,
    validate_art,
)
from src.core.activity_workspace import ActivityWorkspace


@pytest.fixture()
def workspace(tmp_path):
    return ActivityWorkspace(root=tmp_path / "creative")


def test_art_step_creates_svg_file(workspace):
    state = art_step(None, palette="joy", theme="свет", richness=5, workspace=workspace)
    assert state["revision"] == 1
    assert state["status"] == "active"
    assert state["palette"] == "joy"
    path = Path(workspace.root) / f"{state['id']}.svg"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<svg")
    assert "свет" in text  # тема — в заголовке работы


def test_art_is_deterministic_per_theme_and_palette(workspace):
    first = art_step(
        None, palette="calm", theme="тишина", richness=5, workspace=workspace
    )
    second = art_step(
        None, palette="calm", theme="тишина", richness=5, workspace=workspace
    )
    # Разные файлы (id), но одинаковое содержание: сцена воспроизводима.
    assert first["id"] != second["id"]
    assert first["sha256"] == second["sha256"]


def test_palette_changes_picture(workspace):
    calm = render_svg("след", "calm", 5, 1)
    fear = render_svg("след", "fear", 5, 1)
    assert calm != fear


def test_revision_appends_shapes(workspace):
    state = art_step(
        None, palette="sadness", theme="дорога", richness=4, workspace=workspace
    )
    grown = art_step(state, workspace=workspace)
    assert grown["revision"] == 2
    assert grown["palette"] == "sadness"  # настроение рождения хранится
    first_svg = (Path(workspace.root) / f"{state['id']}.svg").read_text("utf-8")
    # Первая редакция — префикс второй: сцена достраивается, а не переписывается.
    revised = render_svg("дорога", "sadness", 4, 2)
    assert first_svg.splitlines()[:5] == revised.splitlines()[:5]
    assert grown["sha256"] != state["sha256"]


def test_revision_keeps_palette_even_if_caller_changes(workspace):
    state = art_step(None, palette="joy", theme="свет", richness=4, workspace=workspace)
    # Даже если вызывающий передал другую эмоцию, работа хранит свою.
    grown = art_step(state, palette="fear", workspace=workspace)
    assert grown["palette"] == "joy"


def test_external_edit_blocks_rewrite(workspace):
    state = art_step(
        None, palette="calm", theme="берег", richness=4, workspace=workspace
    )
    path = Path(workspace.root) / f"{state['id']}.svg"
    path.write_text("<svg>чужая правка</svg>", encoding="utf-8")
    with pytest.raises(ValueError, match="изменён извне"):
        art_step(state, workspace=workspace)


def test_leave_art_requires_reason(workspace):
    state = art_step(
        None, palette="calm", theme="вопрос", richness=4, workspace=workspace
    )
    with pytest.raises(ValueError):
        leave_art(state, "  ")
    left = leave_art(state, "она закончена")
    assert left["status"] == "left"
    validate_art(left)
    # Оставленную работу нельзя продолжить — только новая.
    nxt = art_step(left, workspace=workspace)
    assert nxt["id"] != left["id"]


def test_validate_art_rejects_bad_state():
    with pytest.raises(ValueError):
        validate_art({"id": "x"})
    with pytest.raises(ValueError):
        validate_art(None)


def test_art_available_full_folder(workspace):
    assert art_available(None, workspace=workspace)
    for index in range(32):
        (Path(workspace.root) / f"filler_{index:02d}.svg").write_text("x")
    assert not art_available(None, workspace=workspace)
    # Черновики не едят квоту рисунков — и наоборот.
    for index in range(32):
        (Path(workspace.root) / f"filler_{index:02d}.svg").unlink()
    assert art_available(None, workspace=workspace)
    for index in range(32):
        (Path(workspace.root) / f"draft_{index:02d}.txt").write_text("x")
    assert art_available(None, workspace=workspace)


def test_thumbnail_shape(workspace):
    state = art_step(
        None, palette="fear", theme="след", richness=6, workspace=workspace
    )
    thumb = art_thumbnail(state)
    lines = thumb.splitlines()
    assert len(lines) == 8
    assert all(len(line) == 24 for line in lines)
    assert any(ch != " " for line in lines for ch in line)


def test_art_limit(workspace):
    state = None
    for _ in range(ART_LIMIT):
        state = art_step(
            state, palette="calm", theme="тишина", richness=3, workspace=workspace
        )
    assert state["revision"] == ART_LIMIT
    # Сверх лимита — только новая работа.
    nxt = art_step(state, workspace=workspace)
    assert nxt["id"] != state["id"]
