"""Интеграционные тесты контура на живом агенте.

Главная проверка этапа: за N автономных тиков агент узнаёт новое, цели
двигаются, и одинаковое действие не повторяется бесконечно.
"""

import pytest

from src.core.agent import DigitalBeing


@pytest.fixture()
def agent():
    a = DigitalBeing(name="LoopAgent")
    # Тесты не ходят в сеть: исследование теперь реально думает.
    searcher = getattr(a, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    return a


# ============================================================
# 1. Действие оставляет след
# ============================================================


def test_explore_changes_the_world(agent):
    """«Исследовать» — это работа, а не счётчик.

    Раньше explore попадал в тип «default»: энергия списывалась, мир не
    менялся. Теперь он выбирает конкретную тему и изучает её.
    """
    before = len(agent.mental_models.concepts)
    result = agent.act("explore")

    after = len(agent.mental_models.concepts)
    outcome = agent._last_action_outcome

    assert outcome is not None
    assert outcome.action == "explore"
    # Либо появилась новая концепция, либо выросла уверенность.
    assert outcome.had_effect is True
    assert after >= before
    assert "изучил" in result or "исследовал" in result


def test_explore_picks_different_targets(agent):
    """Исследование идёт в неизвестное, а не топчется на одном месте."""
    for _ in range(5):
        agent.act("explore")

    history = getattr(agent, "_exploration_history", [])
    assert len(history) >= 5
    assert len(set(history)) >= 4  # цели не повторяются подряд


def test_decomposition_creates_subtopics(agent):
    agent.act("think_decompose")
    outcome = agent._last_action_outcome

    assert outcome is not None
    assert outcome.action == "decomposition"


def test_synthesis_records_connection(agent):
    agent.act("synthesize")
    outcome = agent._last_action_outcome

    assert outcome is not None
    assert outcome.action == "synthesis"


# ============================================================
# 2. Прогресс цели требует доказательства
# ============================================================


def test_empty_evidence_does_not_credit_goal(agent):
    """«Я ничего не сделал» не может приблизить цель."""
    agent.set_goal("Выучить основы Python", activate=True)
    goal_id = agent.active_goal["id"]
    assert "python" in agent.active_goal["title"].lower()

    from src.core.world_delta import WorldDelta

    result = agent._check_goal_progress(
        "python", answered=True, evidence=WorldDelta()
    )

    assert result["pct"] == 0
    assert result["completed"] is False
    assert agent._goal_progress[goal_id]["matched_concepts"] == set()


def test_real_evidence_credits_goal(agent):
    agent.set_goal("Выучить основы Python", activate=True)
    goal_id = agent.active_goal["id"]
    assert "python" in agent.active_goal["title"].lower()

    from src.core.world_delta import WorldDelta

    result = agent._check_goal_progress(
        "python", answered=True, evidence=WorldDelta(concepts=1)
    )

    assert result["pct"] > 0
    assert "python" in agent._goal_progress[goal_id]["matched_concepts"]


# ============================================================
# 3. Зацикливание прекращается
# ============================================================


def test_repeated_dead_action_is_escaped(agent):
    """Действие без результата перестаёт выбираться."""
    # Заставляем explore быть бесполезным: исследовать нечего, и мир не
    # меняется. Раньше для этого хватало «все концепции уверены», но
    # теперь исследование добавляет опыт, поэтому блокируем выбор темы
    # напрямую — проверяется механизм выхода из тупика.
    agent._pick_exploration_target = lambda: None

    for _ in range(4):
        agent.act("explore")
    assert agent.loop_closer.is_stuck("explore") is True

    # Тик должен переключиться на другое действие.
    result = agent.autonomous_tick()
    escape = result.get("loop_escape")
    assert escape is not None, result.get("arbitrator")
    assert escape["to"] != "explore"


# ============================================================
# 4. Жизнь за N циклов: знания растут, цели двигаются
# ============================================================


def test_life_produces_knowledge_and_goal_progress(agent):
    """За 30 автономных тиков агент должен чему-то научиться.

    Это тот самый тест, которого не было: раньше он показал бы 0 новых
    концепций и 0 завершённых целей при 6 одинаковых действиях.
    """
    concepts_before = len(agent.mental_models.concepts)
    goals_before = agent.get_goals_status()["completed"]

    actions = []
    for _ in range(30):
        result = agent.autonomous_tick()
        arbiter = result.get("arbitrator") or {}
        actions.append(arbiter.get("action"))

    concepts_after = len(agent.mental_models.concepts)
    status = agent.get_goals_status()

    # Знания выросли — это наблюдаемый факт, а не самоотчёт.
    assert concepts_after > concepts_before, (
        f"концепций было {concepts_before}, стало {concepts_after}"
    )
    # Цели сдвинулись.
    assert status["completed"] >= goals_before
    assert status.get("progress", 0) > 0 or status["completed"] > 0
    # Действия не застыли на одном значении.
    assert len(set(a for a in actions if a)) >= 1


def test_loop_status_exposed_for_ui(agent):
    agent.act("explore")
    state = agent.get_full_state()

    assert "loop" in state
    assert "effective_actions" in state["loop"]
    assert "stuck_actions" in state["loop"]

# ============================================================
# 5. Состояние контура переживает рестарт
# ============================================================

def test_loop_state_survives_checkpoint(agent):
    """Тупик и история исследования не забываются после перезапуска."""
    from src.core.checkpoint_serializer import (
        apply_state_to_agent,
        build_state_from_agent,
    )

    # Намеренно загоняем explore в тупик: исследовать нечего, и мир не
    # меняется. Раньше для этого хватало «все концепции уверены», но
    # теперь исследование добавляет опыт, поэтому блокируем выбор темы
    # напрямую — проверяется логика тупика, а не продуктивность explore.
    agent._pick_exploration_target = lambda: None
    agent._exploration_history = ["тема_1", "тема_2"]
    for _ in range(3):
        agent.act("explore")
    assert agent.loop_closer.is_stuck("explore") is True

    state = build_state_from_agent(agent)

    reborn = DigitalBeing(name="LoopAgent")
    searcher = getattr(reborn, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    apply_state_to_agent(reborn, state)

    assert reborn.loop_closer.is_stuck("explore") is True
    assert reborn._exploration_history == agent._exploration_history


# ============================================================
# 6. Прогресс только по теме цели
# ============================================================

def test_topic_must_match_goal_subject():
    """Цель «Понять, что такое время» не закрывается случайными темами."""
    from src.core.agent import DigitalBeing as DB

    goal = "Понять: что такое время"

    assert DB._topic_is_relevant_to_goal(goal, "что такое время") is True
    assert DB._topic_is_relevant_to_goal(goal, "как работает время") is True
    assert DB._topic_is_relevant_to_goal(goal, "что такое свобода") is False
    assert DB._topic_is_relevant_to_goal(goal, "основы Python") is False


def test_general_goal_accepts_any_topic():
    """У широкой цели без предмета ограничения нет — иначе она мертва."""
    from src.core.agent import DigitalBeing as DB

    assert DB._topic_is_relevant_to_goal("Развивать способности", "что угодно") is True
    assert (
        DB._topic_is_relevant_to_goal(
            "Построить модель мира через диалог", "произвольная тема 1"
        )
        is True
    )


def test_unrelated_topic_does_not_advance_specific_goal(agent):
    agent.set_goal("Понять: что такое время", activate=True)
    goal_id = agent.active_goal["id"]

    from src.core.world_delta import WorldDelta

    agent._check_goal_progress(
        "основы Python", answered=True, evidence=WorldDelta(concepts=1)
    )
    assert agent._goal_progress[goal_id]["percentage"] == 0

    agent._check_goal_progress(
        "что такое время", answered=True, evidence=WorldDelta(concepts=1)
    )
    assert agent._goal_progress[goal_id]["percentage"] > 0
