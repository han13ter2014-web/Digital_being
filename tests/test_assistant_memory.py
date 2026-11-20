"""Переносимая память ассистента: persistence, bounded recall и атомарность."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from assistant_memory import AssistantMemory, MemoryTrace


def test_memory_roundtrip_preserves_types_links_and_consolidation(tmp_path):
    memory = AssistantMemory(tmp_path / "memory")
    consolidated = memory.store(
        "Для полного regression использовать проектную .venv",
        importance=0.9,
        context="Digital Being",
        memory_type="procedural",
    )
    working = memory.store(
        "Полный regression запускать в новой песочнице",
        importance=0.4,
        context="Digital Being",
        memory_type="semantic",
    )
    episode = memory.store("Владелец принял этап 12C", importance=0.6)

    restored = AssistantMemory(tmp_path / "memory")

    assert restored.get_memory_stats()["total_memories"] == 3
    assert restored.get_memory_stats()["long_term_count"] == 1
    assert restored._stores[consolidated] == "long_term"
    assert restored._stores[working] == "short_term"
    assert restored._traces[working].associations == {consolidated}
    assert restored._traces[consolidated].associations == {working}
    assert restored._traces[episode].memory_type == "episodic"
    assert restored.get_recent_episodes()[0]["id"] == episode


def test_recall_is_relevant_persistent_and_strictly_bounded(tmp_path):
    memory = AssistantMemory(tmp_path / "memory")
    memory.store(
        "Тесты используют изолированный DIGITAL_BEING_DATA_DIR без живой data",
        importance=0.9,
        context="правило проекта",
    )
    memory.store("Рецепт яблочного пирога", importance=0.9)

    results = memory.recall("Как запускать тесты без живой data?", max_chars=80)
    context = memory.recall_context("тесты data", max_chars=120)

    assert len(results) == 1
    assert len(results[0]["content"]) <= 80
    assert results[0]["id"].startswith("mem_")
    assert "изолированный" in context
    assert len(context) <= 120
    assert "пирог" not in context

    restored = AssistantMemory(tmp_path / "memory")
    assert restored._traces[results[0]["id"]].access_count == 2


def test_recall_matches_russian_word_forms(tmp_path):
    memory = AssistantMemory(tmp_path / "memory")
    memory.store(
        "Для тестов использовать новую изолированную песочницу",
        importance=0.9,
        context="Digital Being",
        memory_type="procedural",
    )

    context = memory.recall_context("как запускать тесты", max_chars=160)

    assert "изолированную песочницу" in context


def test_decay_consolidates_strong_and_forgets_weak_non_episodic(tmp_path):
    memory = AssistantMemory(tmp_path / "memory", autosave=False)
    strong = memory.store("устойчивое знание", importance=0.4, memory_type="semantic")
    weak = memory.store("слабый след", importance=0.0, memory_type="semantic")
    now = datetime.now(timezone.utc)
    memory._traces[strong].created_at = now - timedelta(days=10)
    memory._traces[strong].access_count = 20
    memory._traces[weak].created_at = now - timedelta(days=200)

    memory.trigger_decay()

    assert memory._stores[strong] == "long_term"
    assert weak not in memory._traces
    assert memory.get_memory_stats()["decay_events"] == 1


def test_explicit_forget_removes_trace_and_association(tmp_path):
    memory = AssistantMemory(tmp_path / "memory")
    first = memory.store("общий устойчивый след", importance=0.9)
    second = memory.store("общий рабочий след", importance=0.4)

    assert memory.forget(first) is True
    assert memory.forget(first) is False
    assert first not in memory._traces[second].associations
    assert (
        AssistantMemory(tmp_path / "memory").get_memory_stats()["total_memories"] == 1
    )


def test_episode_limit_does_not_duplicate_or_delete_consolidated_trace(tmp_path):
    memory = AssistantMemory(tmp_path / "memory", max_episodic=2, max_memories=5)
    ids = [memory.store(f"эпизод {index}", importance=0.9) for index in range(3)]

    assert len(memory._episodic_ids) == 2
    assert len(memory._traces) == 3
    assert all(memory_id in memory._traces for memory_id in ids)


def test_atomic_save_failure_preserves_previous_file(tmp_path, monkeypatch):
    memory = AssistantMemory(tmp_path / "memory")
    memory.store("прежнее воспоминание")
    previous = memory.memory_file.read_bytes()
    memory.autosave = False
    memory.store("новое воспоминание")

    def fail_during_dump(data, stream, **kwargs):
        stream.write('{"partial":')
        raise OSError("disk full")

    monkeypatch.setattr(json, "dump", fail_during_dump)
    with pytest.raises(OSError, match="disk full"):
        memory.save()

    assert memory.memory_file.read_bytes() == previous
    assert not memory.memory_file.with_suffix(".json.tmp").exists()


def test_corrupt_memory_does_not_become_empty_memory(tmp_path):
    path = tmp_path / "memory"
    path.mkdir()
    (path / "memory.json").write_text(
        '{"schema_version": 1, "traces":', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Не удалось прочитать"):
        AssistantMemory(path)


def test_trace_decay_rewards_access_and_validates_time():
    now = datetime.now(timezone.utc)
    trace = MemoryTrace("знание", 0.5, now, now, access_count=4)
    later = now + timedelta(days=1)

    assert trace.decay_strength(now) > trace.decay_strength(later)
    with pytest.raises(ValueError, match="часовой пояс"):
        MemoryTrace("знание", 0.5, datetime.now(), datetime.now())
