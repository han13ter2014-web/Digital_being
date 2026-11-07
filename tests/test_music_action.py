"""Тесты участка «Музыка»: орган local_music и действие compose_music.

Орган: детерминированная нотная запись (seed = тема|настроение, редакция
достраивает, а не переписывает), чужие правки файла не затираются (sha256),
квота на папку и лимит редакций, WAV читается стандартным ``wave``.
Действие: мелодия из доминирующей эмоции, волевой акт music_works,
лимит редакций → честное «оставить с причиной», чекпоинт переживает
рестарт.
"""
import wave
from pathlib import Path

import pytest

from src.cognition.local_music import (
    MAX_MUSIC,
    MOODS,
    MUSIC_LIMIT,
    _compose_score,
    leave_music,
    music_available,
    music_notation,
    music_step,
    validate_music,
)
from src.core.activity_workspace import ActivityWorkspace
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.paths import data_path


# ----------------------------------------------------------------------
# Орган: нотная запись и синтез
# ----------------------------------------------------------------------


def _read_wav(path: Path):
    with wave.open(str(path), "rb") as wav:
        return {
            "channels": wav.getnchannels(),
            "sampwidth": wav.getsampwidth(),
            "framerate": wav.getframerate(),
            "nframes": wav.getnframes(),
        }


def test_first_revision_creates_valid_wav(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    state = music_step(None, mood="calm", theme="тишина", workspace=workspace)

    validate_music(state)
    assert state["revision"] == 1
    assert state["mood"] == "calm"
    assert state["theme"] == "тишина"

    meta = _read_wav(tmp_path / f"{state['id']}.wav")
    assert meta["channels"] == 1
    assert meta["sampwidth"] == 2
    assert meta["framerate"] == 22050
    assert meta["nframes"] > 0


def test_revision_appends_without_rewriting_beginning(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    first = music_step(None, mood="joy", theme="свет", workspace=workspace)
    second = music_step(first, workspace=workspace)

    assert second["id"] == first["id"]
    assert second["revision"] == 2
    # Начало воспроизводимо: первый такт редакции 2 — нота в ноту такт редакции 1.
    one_bar = _compose_score("свет", "joy", 1)
    two_bars = _compose_score("свет", "joy", 2)
    assert two_bars[0] == one_bar[0]
    assert len(two_bars) == 2
    # Вторая редакция длиннее первой как звук.
    grown = _read_wav(tmp_path / f"{first['id']}.wav")
    assert grown["nframes"] > 0


def test_seed_is_deterministic(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    one = music_step(None, mood="sadness", theme="дорога", workspace=workspace)
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    two = music_step(None, mood="sadness", theme="дорога",
                     workspace=ActivityWorkspace(root=other_dir))
    assert one["sha256"] == two["sha256"]
    assert _compose_score("дорога", "sadness", 1) == _compose_score("дорога", "sadness", 1)


def test_mood_changes_character(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    # Лад и темп — из настроения: одна тема звучит по-разному.
    assert _compose_score("свет", "joy", 2) != _compose_score("свет", "fear", 2)
    for mood in MOODS:
        state = music_step(None, mood=mood, theme="тема", workspace=workspace)
        validate_music(state)
    with pytest.raises(ValueError):
        music_step(None, mood="восторг", theme="тема", workspace=workspace)


def test_tampered_file_is_not_overwritten(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    state = music_step(None, mood="calm", theme="след", workspace=workspace)
    target = tmp_path / f"{state['id']}.wav"
    target.write_bytes(target.read_bytes() + b"intruder")

    with pytest.raises(ValueError, match="изменена извне"):
        music_step(state, workspace=workspace)
    # Чужая правка на месте — орган её не затёр.
    assert target.read_bytes().endswith(b"intruder")


def test_leave_requires_reason_and_keeps_it(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    state = music_step(None, mood="calm", theme="берег", workspace=workspace)

    with pytest.raises(ValueError):
        leave_music(state, "   ")
    left = leave_music(state, "мелодия сказала всё")
    assert left["status"] == "left"
    assert left["leave_reason"] == "мелодия сказала всё"
    # Повторное оставление не затирает первую причину.
    again = leave_music(left, "другая причина")
    assert again["leave_reason"] == "мелодия сказала всё"


def test_quota_blocks_new_works(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    for index in range(MAX_MUSIC):
        (tmp_path / f"foreign_{index:02d}.wav").write_bytes(b"RIFF")

    assert not music_available(None, workspace=workspace)
    with pytest.raises(ValueError, match="заполнена"):
        music_step(None, mood="calm", theme="вопрос", workspace=workspace)


def test_limit_revision_starts_new_work(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    state = music_step(None, mood="calm", theme="тема", workspace=workspace)
    exhausted = {**state, "revision": MUSIC_LIMIT}

    fresh = music_step(exhausted, workspace=workspace)
    assert fresh["id"] != state["id"]
    assert fresh["revision"] == 1
    # Старая работа на лимите недоступна для продолжения, но место ещё есть.
    assert music_available(exhausted, workspace=workspace)


def test_notation_is_human_readable(tmp_path):
    workspace = ActivityWorkspace(root=tmp_path)
    state = music_step(None, mood="joy", theme="свет", workspace=workspace)
    text = music_notation(state)
    assert isinstance(text, str) and text
    # Есть имена нот и границы тактов.
    assert "|" in text or any(name[:1] in text for name in ("C", "D", "E", "F", "G", "A", "B"))


# ----------------------------------------------------------------------
# Действие compose_music у настоящего агента
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_music_artifacts():
    """Тесты не оставляют мелодий в общей папке существ."""
    root = Path(data_path("delamain", "workspace", "creative"))
    root.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in root.iterdir() if p.is_file()}
    yield
    for path in root.iterdir():
        if path.is_file() and path.name not in before:
            path.unlink()


def test_compose_music_action_creates_melody():
    agent = DigitalBeing(name="MusicTest")
    result = agent.act("compose_music")

    assert "сочинила мелодию" in result
    work = agent._music_work
    assert work is not None
    assert work["revision"] == 1
    path = Path(data_path("delamain", "workspace", "creative")) / f"{work['id']}.wav"
    assert path.is_file()
    # Мелодия — не знание: база не тронута.
    assert work["theme"] not in agent.knowledge_base
    # Волевой акт засчитан.
    stats = agent.will_registry.get_stats()
    assert stats["by_type"]["music_works"] == 1


def test_music_revision_grows_same_work():
    agent = DigitalBeing(name="MusicTest2")
    agent.act("compose_music")
    first = dict(agent._music_work)
    agent.act("compose_music")

    assert agent._music_work["id"] == first["id"]
    assert agent._music_work["revision"] == 2
    works = agent.list_music_works()
    assert any(w["id"] == first["id"] for w in works)


def test_music_mood_follows_emotion():
    agent = DigitalBeing(name="MusicMood")
    agent.emotional_state.handle_event("abuse", cycle=0)
    agent.act("compose_music")

    assert agent._music_work["mood"] == "fear"


def test_music_limit_leaves_work_with_reason():
    agent = DigitalBeing(name="MusicLimit")
    agent.act("compose_music")
    first = dict(agent._music_work)
    # Доводим работу до предела редакций.
    agent._music_work = {**first, "revision": MUSIC_LIMIT}
    agent._music_catalog[first["id"]] = dict(agent._music_work)

    result = agent.act("compose_music")
    assert "сочинила мелодию" in result
    # Начата новая работа, старая оставлена с честной причиной.
    assert agent._music_work["id"] != first["id"]
    works = {w["id"]: w for w in agent.list_music_works()}
    assert works[first["id"]]["status"] == "left"
    assert works[first["id"]]["leave_reason"]


def test_music_survives_checkpoint_roundtrip():
    agent = DigitalBeing(name="MusicRestart")
    agent.act("compose_music")
    work = dict(agent._music_work)

    state = build_state_from_agent(agent)
    restored = DigitalBeing(name="MusicRestart")
    apply_state_to_agent(restored, state)

    assert restored._music_work["id"] == work["id"]
    assert restored._music_work["sha256"] == work["sha256"]
    assert any(w["id"] == work["id"] for w in restored.list_music_works())


def test_compose_music_availability():
    agent = DigitalBeing(name="MusicAvail")
    assert agent._is_action_available("compose_music")
    # Работа на лимите и без места в папке — недоступно.
    agent._music_work = {
        "id": "0" * 32, "theme": "тема", "mood": "calm",
        "revision": MUSIC_LIMIT, "status": "active",
        "sha256": "0" * 64, "score": [],
    }
    root = Path(data_path("delamain", "workspace", "creative"))
    created = []
    try:
        for index in range(MAX_MUSIC):
            filler = root / f"quota_probe_{index:02d}.wav"
            filler.write_bytes(b"RIFF")
            created.append(filler)
        assert not agent._is_action_available("compose_music")
    finally:
        for filler in created:
            filler.unlink(missing_ok=True)
