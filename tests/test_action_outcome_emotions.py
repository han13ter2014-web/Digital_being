"""Проводка исходов синхронных действий в эмоциональном состоянии.

Каждый исполненный продукт act() исход окрашивает состояние сущности
существующими событиями контура: успех с эффектом — joy
(intention_completed), промах после исполнения — sadness
(intention_failed), исключение во время исполнения — sadness.
Отказ до исполнения (denied: энергия/бюджет) не переживается —
эмоция окрашивает факт, а не намерение. Детерминизм: уровни из
таблицы EVENT_EMOTIONS, никакого random.
"""

from types import SimpleNamespace

from src.core.agent import DigitalBeing
from src.core.emotional_state import EmotionalState


def _satisfied(agent):
    """Сытые потребности: motivation-ответчики не вмешиваются в замер."""
    for need in agent.motivation_system.needs.values():
        need.current_level = need.base_level


def test_success_with_effect_yields_joy():
    agent = DigitalBeing(name="WiredSuccess")
    _satisfied(agent)
    before = agent.emotional_state.levels["joy"]

    # play подтверждает результат сам (confirmed_result) — честный успех.
    agent.act("play")

    assert agent.emotional_state.levels["joy"] > before
    episode = agent.emotional_state.episodes[-1]
    assert episode["event"] == "intention_completed"
    assert episode["emotion"] == "joy"


def test_executed_miss_yields_sadness():
    agent = DigitalBeing(name="WiredMiss")
    _satisfied(agent)
    before = agent.emotional_state.levels["sadness"]

    # explore по несуществующей теме: действие исполнилось, мир не изменился.
    agent._pick_exploration_target = lambda: None
    agent.act("explore")

    assert agent.emotional_state.levels["sadness"] > before
    episode = agent.emotional_state.episodes[-1]
    assert episode["event"] == "intention_failed"
    assert episode["emotion"] == "sadness"


def test_denied_yields_no_episode():
    agent = DigitalBeing(name="WiredDenied")
    _satisfied(agent)
    # Энергия ниже стоимости действия: отклонение до исполнения (denied).
    agent._action_costs["explore"] = 10**6
    episodes_before = list(agent.emotional_state.episodes)
    joy_before = agent.emotional_state.levels["joy"]
    sadness_before = agent.emotional_state.levels["sadness"]

    reply = agent.act("explore")

    assert "устала" in reply
    assert agent.emotional_state.episodes == episodes_before
    assert agent.emotional_state.levels["joy"] == joy_before
    assert agent.emotional_state.levels["sadness"] == sadness_before


def test_exception_during_execution_yields_sadness():
    """Исключение в исполнении окрашивает состояние как sadness."""
    from src.core.agent_act import _wire_execution_exception_emotion

    agent = SimpleNamespace(
        emotional_state=EmotionalState(),
        cycle_count=42,
    )
    _wire_execution_exception_emotion(agent, "web_search")

    episode = agent.emotional_state.episodes[-1]
    assert episode["event"] == "intention_failed"
    assert episode["emotion"] == "sadness"
    assert episode["cycle"] == 42


def test_light_object_without_emotional_state_does_not_crash():
    """act() работает и без emotional_state (лёгкие тестовые объекты)."""
    from src.core.agent_act import _wire_action_outcome_emotion

    agent = SimpleNamespace(emotional_state=None, cycle_count=5)
    _wire_action_outcome_emotion(agent, "explore", SimpleNamespace(had_effect=True))
    _wire_action_outcome_emotion(agent, "explore", SimpleNamespace(had_effect=False))
    # Не упало — проводка с guard'ом.


def _hunt_searcher(result):
    searcher = SimpleNamespace(is_enabled=True, queries=[])

    def search(query):
        searcher.queries.append(query)
        return dict(result)

    searcher.search = search
    return searcher


def test_successful_hunt_yields_joy_through_real_action_outcome():
    agent = DigitalBeing(name="HuntEmotionSuccess")
    _satisfied(agent)
    target = "электротелеграф"
    agent.web_searcher = _hunt_searcher(
        {
            "found": True,
            "title": "Электротелеграф",
            "extract": (
                "Электротелеграф — устройство для передачи сообщений "
                "электрическими сигналами на расстояние."
            ),
        }
    )
    joy_before = agent.emotional_state.levels["joy"]

    agent.act("web_search", intention={"params": {"target": target}})

    outcome = agent._last_action_outcome
    assert outcome.had_effect
    assert outcome.delta.knowledge_entries == 1
    assert agent.web_searcher.queries == [target]
    assert agent.emotional_state.levels["joy"] > joy_before
    episode = agent.emotional_state.episodes[-1]
    assert episode["event"] == "intention_completed"
    assert episode["emotion"] == "joy"
    assert agent.emotional_state.last_causes[episode["emotion"]] == (
        agent.cycle_count,
        "web_search",
    )


def test_missed_hunt_yields_sadness_through_real_action_outcome():
    agent = DigitalBeing(name="HuntEmotionMiss")
    _satisfied(agent)
    target = "несуществующая тема k16"
    agent.web_searcher = _hunt_searcher({"found": False, "error": "no_pages"})
    sadness_before = agent.emotional_state.levels["sadness"]

    agent.act("web_search", intention={"params": {"target": target}})

    outcome = agent._last_action_outcome
    assert not outcome.had_effect
    assert outcome.delta.is_empty
    assert agent._hunt_misses[target] == agent.cycle_count
    assert agent.emotional_state.levels["sadness"] > sadness_before
    episode = agent.emotional_state.episodes[-1]
    assert episode["event"] == "intention_failed"
    assert episode["emotion"] == "sadness"
    assert agent.emotional_state.last_causes[episode["emotion"]] == (
        agent.cycle_count,
        "web_search",
    )


def test_denied_hunt_has_no_search_and_no_emotional_episode():
    agent = DigitalBeing(name="HuntEmotionDenied")
    _satisfied(agent)
    agent.web_searcher = _hunt_searcher({"found": False, "error": "no_pages"})
    agent._action_costs["web_search"] = 10**6
    episodes_before = list(agent.emotional_state.episodes)

    reply = agent.act(
        "web_search", intention={"params": {"target": "недоступная охота"}}
    )

    assert "устала" in reply
    assert agent.web_searcher.queries == []
    assert agent.emotional_state.episodes == episodes_before
