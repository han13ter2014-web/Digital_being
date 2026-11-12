"""Q6: разрывы процесса — факты автобиографической памяти, а не UI-реплики."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.agent import DigitalBeing
from src.core.dialogue_acts import is_noise_input
from src.delamain.memory import MemoryStore
from src.ui.diary_view import diary_rows, episode_title
from src.ui.graph_view import build_life_graph
from src.ui.life_snapshot import build_life_snapshot

PLACEHOLDER_LIFE_ID = "00000000-0000-0000-0000-000000000000"
LIFE = PLACEHOLDER_LIFE_ID


def _store(tmp_path):
    return MemoryStore(tmp_path / "biography.sqlite3")


def _episodes(store):
    return list(reversed(store.recent_life_episodes(life_id=LIFE, limit=200)))


def _seams(store):
    return [
        row
        for row in _episodes(store)
        if row["metadata"].get("kind") == "biography_seam"
    ]


def _ordinary_episode(store, intention_id="intention-1"):
    episode_id = store.record_life_episode(
        life_id=LIFE,
        intention_id=intention_id,
        action="reflect",
        target="память",
        outcome={"result": "записано"},
    )
    return next(row for row in _episodes(store) if row["id"] == episode_id)


def test_first_instrumented_run_does_not_rewrite_existing_history(tmp_path):
    store = _store(tmp_path)
    original = _ordinary_episode(store)

    first = store.begin_biography_run(
        life_id=LIFE, run_id="run-1", started_at="2026-11-06T10:00:00+00:00"
    )
    repeated = store.begin_biography_run(
        life_id=LIFE, run_id="run-1", started_at="2026-11-06T10:00:01+00:00"
    )

    assert first["marker_created"] is False
    assert repeated["marker_created"] is False
    assert _episodes(store) == [original]
    assert _seams(store) == []


def test_graceful_restart_records_exactly_one_seam_with_recorded_bounds(tmp_path):
    store = _store(tmp_path)
    store.begin_biography_run(
        life_id=LIFE, run_id="run-1", started_at="2026-11-06T10:00:00+00:00"
    )
    original = _ordinary_episode(store)
    assert store.record_graceful_shutdown(
        life_id=LIFE, run_id="run-1", ended_at="2026-11-06T10:05:00+00:00"
    )
    store.close()

    store = _store(tmp_path)
    restarted = store.begin_biography_run(
        life_id=LIFE, run_id="run-2", started_at="2026-11-06T10:10:00+00:00"
    )
    store.begin_biography_run(
        life_id=LIFE, run_id="run-2", started_at="2026-11-06T10:10:00+00:00"
    )

    seams = _seams(store)
    assert restarted["marker_created"] is True
    assert len(seams) == 1
    seam = seams[0]
    assert seam["output"] == {
        "text": (
            f"Жизнь прерывалась, опыт восстановлен. Разрыв: {original['ts']} — "
            "2026-11-06T10:10:00+00:00. Причина: штатное завершение предыдущего процесса."
        ),
        "gap_started_at": original["ts"],
        "gap_ended_at": "2026-11-06T10:10:00+00:00",
        "reason": "graceful_shutdown",
    }
    assert seam["metadata"]["previous_run_id"] == "run-1"
    assert seam["metadata"]["current_run_id"] == "run-2"


def test_two_restarts_create_two_distinct_seams_without_duplicates(tmp_path):
    store = _store(tmp_path)
    store.begin_biography_run(
        life_id=LIFE, run_id="run-1", started_at="2026-11-06T10:00:00+00:00"
    )
    _ordinary_episode(store)
    store.record_graceful_shutdown(
        life_id=LIFE, run_id="run-1", ended_at="2026-11-06T10:01:00+00:00"
    )
    store.close()

    store = _store(tmp_path)
    store.begin_biography_run(
        life_id=LIFE, run_id="run-2", started_at="2026-11-06T10:02:00+00:00"
    )
    store.record_graceful_shutdown(
        life_id=LIFE, run_id="run-2", ended_at="2026-11-06T10:03:00+00:00"
    )
    store.close()

    store = _store(tmp_path)
    store.begin_biography_run(
        life_id=LIFE, run_id="run-3", started_at="2026-11-06T10:04:00+00:00"
    )
    store.begin_biography_run(
        life_id=LIFE, run_id="run-3", started_at="2026-11-06T10:04:00+00:00"
    )

    seams = _seams(store)
    assert len(seams) == 2
    assert [row["metadata"]["current_run_id"] for row in seams] == ["run-2", "run-3"]
    assert len({row["task_id"] for row in seams}) == 2


def test_hard_interruption_uses_last_saved_episode_not_invented_crash_time(tmp_path):
    store = _store(tmp_path)
    store.begin_biography_run(
        life_id=LIFE, run_id="run-1", started_at="2026-11-06T10:00:00+00:00"
    )
    original = _ordinary_episode(store)
    store.close()  # Никакого graceful shutdown: аналог потери процесса.

    store = _store(tmp_path)
    store.begin_biography_run(
        life_id=LIFE, run_id="run-2", started_at="2026-11-06T11:00:00+00:00"
    )

    seam = _seams(store)[0]
    assert seam["output"]["reason"] == "external_interruption"
    assert seam["output"]["gap_started_at"] == original["ts"]
    assert seam["output"]["gap_ended_at"] == "2026-11-06T11:00:00+00:00"
    assert "внешнее прерывание предыдущего процесса" in seam["output"]["text"]
    assert "время сбоя" not in seam["output"]["text"].casefold()


def test_new_seams_do_not_modify_previous_episode_rows(tmp_path):
    store = _store(tmp_path)
    original = _ordinary_episode(store)
    store.begin_biography_run(
        life_id=LIFE, run_id="run-1", started_at="2026-11-06T10:00:00+00:00"
    )
    store.record_graceful_shutdown(life_id=LIFE, run_id="run-1")
    store.begin_biography_run(
        life_id=LIFE, run_id="run-2", started_at="2026-11-06T10:10:00+00:00"
    )
    store.begin_biography_run(
        life_id=LIFE, run_id="run-3", started_at="2026-11-06T10:20:00+00:00"
    )

    rows = _episodes(store)
    assert next(row for row in rows if row["id"] == original["id"]) == original
    assert len(_seams(store)) == 2


def test_run_journal_is_scoped_to_life(tmp_path):
    store = _store(tmp_path)
    other_life = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    store.begin_biography_run(
        life_id=LIFE, run_id="life-run", started_at="2026-11-06T10:00:00+00:00"
    )
    store.begin_biography_run(
        life_id=other_life, run_id="other-run", started_at="2026-11-06T10:01:00+00:00"
    )

    assert store.record_graceful_shutdown(life_id=other_life, run_id="other-run")
    assert not store.record_graceful_shutdown(life_id=LIFE, run_id="other-run")
    assert store.record_graceful_shutdown(life_id=LIFE, run_id="life-run")


def test_seam_is_visible_in_diary_episodes_and_life_graph(tmp_path):
    store = _store(tmp_path)
    store.begin_biography_run(
        life_id=LIFE, run_id="run-1", started_at="2026-11-06T10:00:00+00:00"
    )
    store.record_graceful_shutdown(life_id=LIFE, run_id="run-1")
    store.begin_biography_run(
        life_id=LIFE, run_id="run-2", started_at="2026-11-06T10:10:00+00:00"
    )
    seam = _seams(store)[0]

    agent = DigitalBeing(name="BiographyView")
    agent.life_id = LIFE
    agent.delamain = SimpleNamespace(runtime=SimpleNamespace(memory=store))
    snapshot = build_life_snapshot(agent)
    diary = diary_rows(snapshot)
    graph = build_life_graph(agent, snapshot)

    assert any(row["id"] == seam["id"] for row in diary)
    assert episode_title(seam) == seam["output"]["text"]
    node = next(
        node for node in graph["nodes"] if node["id"] == f"episode:{seam['id']}"
    )
    assert node["kind"] == "biography_seam"
    assert node["label"] == seam["output"]["text"]
    assert node["detail"]["начало разрыва"] == seam["output"]["gap_started_at"]
    assert node["detail"]["конец разрыва"] == seam["output"]["gap_ended_at"]


def test_seam_text_passes_existing_vocabulary_filters_and_stays_neutral(tmp_path):
    store = _store(tmp_path)
    store.begin_biography_run(life_id=LIFE, run_id="run-1")
    store.begin_biography_run(life_id=LIFE, run_id="run-2")
    text = _seams(store)[0]["output"]["text"]
    agent = DigitalBeing(name="BiographyVocabulary")

    assert not is_noise_input(text)
    assert agent._is_meaningful_topic(text)
    lowered = text.casefold()
    for forbidden in ("смерть", "труп", "умер", "реаним", "боль"):
        assert forbidden not in lowered
