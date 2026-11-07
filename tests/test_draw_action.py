"""Тесты привязки рисования: действие draw у настоящего агента."""
from pathlib import Path

import pytest

from src.core.agent import DigitalBeing
from src.core.paths import data_path


@pytest.fixture(autouse=True)
def _clean_art_artifacts():
    """Тесты не оставляют рисунков в общей папке существ."""
    root = Path(data_path("delamain", "workspace", "creative"))
    root.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in root.iterdir() if p.is_file()}
    yield
    for path in root.iterdir():
        if path.is_file() and path.name not in before:
            path.unlink()


def test_draw_action_creates_artwork():
    agent = DigitalBeing(name="DrawTest")
    result = agent.act("draw")
    assert "нарисовала" in result
    work = agent._art_work
    assert work is not None
    assert work["revision"] == 1
    path = Path(data_path("delamain", "workspace", "creative")) / f"{work['id']}.svg"
    assert path.is_file()
    # Рисунок — не знание: база и ментальные модели не тронуты.
    assert work["theme"] not in agent.knowledge_base


def test_draw_revision_grows_same_work():
    agent = DigitalBeing(name="DrawTest2")
    agent.act("draw")
    first = dict(agent._art_work)
    agent.act("draw")
    assert agent._art_work["id"] == first["id"]
    assert agent._art_work["revision"] == 2
    # Каталог знает работу.
    works = agent.list_art_works()
    assert any(w["id"] == first["id"] for w in works)


def test_play_alternates_to_guess_game():
    agent = DigitalBeing(name="PlayTest")
    # Крестики-нолики уже «сыграны» (round=1): вторая игра отстаёт.
    agent._local_play = {"board": ["."] * 9, "turns": 0, "round": 1, "result": None}
    result = agent.act("play")
    assert "угадываю число" in result
    assert agent._local_guess is not None
    assert agent._local_guess["attempts"] == 1
