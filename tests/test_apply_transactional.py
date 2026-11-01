"""П.4B — двухфазное применение чекпоинта.

Раньше ``apply_state_to_agent`` менял агента по мере чтения: к моменту
падения на повреждённой секции (method_preferences, прогресс целей,
недоступная память жизни) имя, энергия, база знаний и цели уже были
заменены — сущность оставалась наполовину восстановленной.

Теперь всё, что может упасть, разбирается и валидируется в фазе 1 до
первой мутации. Повреждённый чекпоинт падает, не тронув агента.
"""

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)


def _snapshot(agent):
    """Снимок ключевых полей для сравнения «до/после»."""
    return {
        "name": agent.name,
        "energy": agent.energy,
        "cycle_count": agent.cycle_count,
        "intelligence": agent.intelligence,
        "goals": [dict(goal) for goal in agent.goals],
        "knowledge_base": dict(agent.knowledge_base),
        "concepts": set(agent.mental_models.concepts.keys()),
        "method_preferences": {
            key: dict(value)
            for key, value in getattr(agent, "_method_preferences", {}).items()
        },
    }


def _assert_untouched(agent, before):
    assert agent.name == before["name"]
    assert agent.energy == before["energy"]
    assert agent.cycle_count == before["cycle_count"]
    assert agent.intelligence == before["intelligence"]
    assert agent.goals == before["goals"]
    assert agent.knowledge_base == before["knowledge_base"]
    assert set(agent.mental_models.concepts.keys()) == before["concepts"]
    assert (
        {
            key: dict(value)
            for key, value in getattr(agent, "_method_preferences", {}).items()
        }
        == before["method_preferences"]
    )


def _make_agent_and_state():
    agent = DigitalBeing(name="TxApply")
    agent.cycle_count = 33
    agent.knowledge_base["транзакционная тема"] = "определение"
    agent._known_definitions["транзакционная тема"] = "определение"
    state = build_state_from_agent(agent)
    return agent, state


def test_valid_state_still_applies():
    """Контроль: валидный снимок применяется как раньше."""
    original, state = _make_agent_and_state()
    restored = DigitalBeing(name="TxApply")

    apply_state_to_agent(restored, state)

    assert restored.name == original.name
    assert restored.cycle_count == 33
    assert restored.knowledge_base == original.knowledge_base
    assert "транзакционная тема" in restored._known_definitions


def test_corrupted_method_preferences_leave_agent_untouched():
    agent, state = _make_agent_and_state()
    fresh = DigitalBeing(name="TxApply")
    before = _snapshot(fresh)

    state["method_preferences"] = {
        "explore": {
            "attempts": -5,
            "effects": 0,
            "failures": 0,
            "leaves": 0,
        },
    }

    with pytest.raises(ValueError):
        apply_state_to_agent(fresh, state)

    _assert_untouched(fresh, before)


def test_corrupted_goal_progress_leaves_agent_untouched():
    agent, state = _make_agent_and_state()
    fresh = DigitalBeing(name="TxApply")
    before = _snapshot(fresh)

    state["_goal_progress"] = {"abc": "мусор"}

    with pytest.raises((ValueError, TypeError)):
        apply_state_to_agent(fresh, state)

    _assert_untouched(fresh, before)


def test_missing_life_memory_fails_before_mutation():
    agent, state = _make_agent_and_state()
    state["life_id"] = "11111111-1111-1111-1111-111111111111"

    fresh = DigitalBeing(name="TxApply")
    fresh._profile_managed = True
    fresh.long_term_memory = None
    before = _snapshot(fresh)

    with pytest.raises(ValueError):
        apply_state_to_agent(fresh, state)

    _assert_untouched(fresh, before)
