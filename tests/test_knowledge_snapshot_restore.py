"""П.5A — snapshot-семантика базы знаний при восстановлении чекпоинта.

Раньше ``apply_state_to_agent`` и ``KnowledgeSubsystem.restore_from_checkpoint``
делали ``update()`` поверх уже существующей базы. Записи, удалённые при жизни
существа (чистка мусора, прунинг по лимиту, забытие тем), возвращались после
рестарта: они приходили из DEFAULT_KNOWLEDGE / knowledge_base.json при
рождении, а чекпоинт лишь накатывался сверху.

Теперь база после восстановления равна снимку из чекпоинта, словари
заменяются на месте (алиасы agent <-> subsystem не рвутся), а повреждённая
секция не применяется частично.
"""

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.subsystems.knowledge_base import KnowledgeSubsystem


TOPIC = "тестовая тема"
DEF = "временное определение"


# ============================================================
# apply_state_to_agent (путь life_state.json)
# ============================================================

def test_deleted_before_checkpoint_stays_deleted_after_restore():
    """Тема удалена ДО сохранения чекпоинта — рестарт её не воскрешает."""
    original = DigitalBeing(name="KB")
    original.cycle_count = 20
    original.knowledge_base[TOPIC] = DEF
    original._known_definitions[TOPIC] = DEF

    # Чистка при жизни (аналог clean/prune/forget).
    del original.knowledge_base[TOPIC]
    del original._known_definitions[TOPIC]

    state = build_state_from_agent(original)
    validate_checkpoint_state(state)
    assert TOPIC not in state["knowledge_base"]

    # Новый запуск: тема вернулась из DEFAULT/file-загрузки при рождении.
    restored = DigitalBeing(name="KB")
    restored.knowledge_base[TOPIC] = DEF
    restored._known_definitions[TOPIC] = DEF

    apply_state_to_agent(restored, state)

    assert TOPIC not in restored.knowledge_base
    assert TOPIC not in restored._known_definitions


def test_restore_matches_checkpoint_snapshot_exactly():
    """После рестарта база равна снимку, а не надмножеству снимка."""
    original = DigitalBeing(name="KB")
    original.cycle_count = 10
    original.knowledge_base[TOPIC] = DEF
    original._known_definitions[TOPIC] = DEF

    state = build_state_from_agent(original)

    # После сохранения чекпоинта запись удалили (снимок её уже не содержит).
    del state["knowledge_base"][TOPIC]
    del state["_known_definitions"][TOPIC]

    restored = DigitalBeing(name="KB")
    restored.knowledge_base[TOPIC] = "старое определение"
    restored._known_definitions[TOPIC] = "старое определение"

    apply_state_to_agent(restored, state)

    assert restored.knowledge_base == state["knowledge_base"]
    assert restored._known_definitions == state["_known_definitions"]


def test_restore_keeps_dict_objects():
    """Словари заменяются на месте: ссылки других подсистем не рвутся."""
    agent = DigitalBeing(name="KB")
    kb_obj = agent.knowledge_base
    defs_obj = agent._known_definitions

    apply_state_to_agent(agent, build_state_from_agent(agent))

    assert agent.knowledge_base is kb_obj
    assert agent._known_definitions is defs_obj


def test_corrupted_knowledge_sections_are_rejected():
    """Повреждённая секция отклоняется валидацией до применения.

    apply_state_to_agent сначала валидирует state: мусор вместо
    knowledge_base/—_known_definitions падает с ValueError, и база
    остаётся нетронутой (fail-fast вместо частичного применения).
    """
    agent = DigitalBeing(name="KB")
    before_kb = dict(agent.knowledge_base)
    before_defs = dict(agent._known_definitions)

    state = build_state_from_agent(agent)
    state["knowledge_base"] = "мусор"
    state["_known_definitions"] = 42

    with pytest.raises(ValueError):
        apply_state_to_agent(agent, state)

    assert agent.knowledge_base == before_kb
    assert agent._known_definitions == before_defs


# ============================================================
# KnowledgeSubsystem.restore_from_checkpoint (путь CheckpointManager)
# ============================================================

def _subsystem(tmp_path):
    return KnowledgeSubsystem(
        "Tester", knowledge_file=str(tmp_path / "kb.json")
    )


def test_subsystem_restore_is_snapshot(tmp_path):
    kb = _subsystem(tmp_path)
    kb.knowledge_base[TOPIC] = DEF
    kb._known_definitions[TOPIC] = DEF

    # to_checkpoint_dict отдаёт живые ссылки; в реальном потоке снимок
    # сразу уходит в json.dump. Копируем, повторяя JSON round-trip.
    saved = {k: dict(v) for k, v in kb.to_checkpoint_dict().items()}

    # Записи, появившиеся после снимка, не должны его пережить.
    kb.knowledge_base["поздняя тема"] = "позднее определение"
    kb._known_definitions["поздняя тема"] = "позднее определение"

    kb.restore_from_checkpoint(saved)

    assert kb.knowledge_base == saved["knowledge_base"]
    assert kb._known_definitions == saved["_known_definitions"]
    assert "поздняя тема" not in kb.knowledge_base
    assert "поздняя тема" not in kb._known_definitions


def test_subsystem_restore_preserves_dict_identity(tmp_path):
    kb = _subsystem(tmp_path)
    kb_obj = kb.knowledge_base
    defs_obj = kb._known_definitions

    kb.restore_from_checkpoint(kb.to_checkpoint_dict())

    assert kb.knowledge_base is kb_obj
    assert kb._known_definitions is defs_obj


def test_subsystem_restore_skips_garbage_sections(tmp_path):
    kb = _subsystem(tmp_path)
    before_kb = dict(kb.knowledge_base)

    kb.restore_from_checkpoint(
        {"knowledge_base": "мусор", "_known_definitions": 42}
    )

    assert kb.knowledge_base == before_kb
    assert kb._known_definitions == {}
