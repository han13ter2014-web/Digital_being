"""Этап 5: смысл действий и честность метрик.

Проверяем не «красиво ли», а измеримые инварианты:

* прогресс цели накапливается, а не застревает на фиксированной доле;
* цель завершается ровно один раз;
* счётчик завершённых целей целый и синхронизирован с подсистемой;
* энергия не превышает ``ENERGY_MAX``;
* у целей без специального правила есть общий прогресс (иначе тупик);
* чекпоинт сохраняет и восстанавливает процент прогресса;
* CLI обновляет ``agent.cycle_count``, а не только локальную переменную;
* тип действия измеряется и виден в полном состоянии;
* декомпозиция ставит под-вопросы в очередь, а служебная аннотация
  стратегии не попадает в анализ.
"""

import re
from pathlib import Path

import pytest

from config.simulation_config import LR_CONFIG

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def agent():
    from src.core.agent import DigitalBeing

    instance = DigitalBeing("Stage5Probe")
    instance.thinking.web_searcher = None
    return instance


def _goal_by_title(agent, title):
    return next(g for g in agent.goals if g["title"] == title)


def _activate(agent, goal):
    goal["status"] = "active"
    agent.active_goal = goal
    agent.goal_subsystem.active_goal = goal


def _reset_progress(agent, goal):
    agent._goal_progress[goal["id"]] = {
        "matched_concepts": set(),
        "percentage": 0,
        "last_update_cycle": 0,
    }


# ============================================================
# 1. Прогресс цели
# ============================================================
def test_goal_progress_accumulates_and_completes_once(agent):
    goal = _goal_by_title(agent, "Выучить основы Python")
    _activate(agent, goal)
    _reset_progress(agent, goal)

    topics = [
        "что такое функция",
        "класс object",
        "команда import",
        "модуль",
        "словарь",
    ]
    percentages = [
        agent._check_goal_progress(topic, answered=True)["pct"]
        for topic in topics
    ]

    assert percentages == [20, 40, 60, 80, 100]
    assert goal["status"] == "completed"
    assert agent.completed_goals == 1
    assert agent.goal_subsystem.completed_goals == 1

    # Повторное завершение не должно увеличивать счётчик.
    assert agent.complete_goal(goal["id"]) == 0
    assert agent.completed_goals == 1
    assert agent.goal_subsystem.completed_goals == 1


def test_python_goal_requires_real_answer(agent):
    goal = _goal_by_title(agent, "Выучить основы Python")
    _activate(agent, goal)
    _reset_progress(agent, goal)

    # Встретил вопрос, но ответа нет — это не «выучил».
    assert agent._check_goal_progress("что такое функция")["pct"] == 0
    assert agent._check_goal_progress("что такое функция", answered=True)["pct"] == 20


def test_goal_energy_bonus_is_clamped(agent):
    goal = _goal_by_title(agent, "Выучить основы Python")
    _activate(agent, goal)
    _reset_progress(agent, goal)
    for topic in ["функция", "класс", "import", "объект"]:
        agent._check_goal_progress(topic, answered=True)

    agent.energy = LR_CONFIG.ENERGY_MAX - 1
    result = agent._check_goal_progress("генератор", answered=True)

    assert result["completed"] is True
    assert agent.energy == LR_CONFIG.ENERGY_MAX


def test_short_keyword_does_not_match_inside_words(agent):
    from src.core.agent import DigitalBeing

    rule = {"match_topic_keywords": ["я"]}
    assert DigitalBeing._topic_matches_rule("кто я", rule) is True
    assert DigitalBeing._topic_matches_rule("функция def", rule) is False

    goal = _goal_by_title(agent, "Понять, кто я")
    _activate(agent, goal)
    _reset_progress(agent, goal)

    # «функция» содержит букву «я», но не является темой самопонимания.
    assert agent._check_goal_progress("что такое функция")["pct"] == 0


def test_goal_without_rule_has_general_progress(agent):
    goal = _goal_by_title(agent, "Построить модель мира через диалог")
    _activate(agent, goal)
    _reset_progress(agent, goal)

    percentages = [
        agent._check_goal_progress(f"произвольная тема {i}")["pct"]
        for i in range(1, 6)
    ]

    assert percentages == [20, 40, 60, 80, 100]
    assert goal["status"] == "completed"
    assert agent.completed_goals == 1


# ============================================================
# 2. GoalSubsystem: без дробных счётчиков
# ============================================================
def test_subsystem_progress_is_integer_and_idempotent(agent):
    subsystem = agent.goal_subsystem
    goal = _goal_by_title(agent, "Собрать 10 фактов о мире")
    subsystem.active_goal = goal
    _reset_progress(agent, goal)

    results = [
        subsystem.check_progress(f"факт {i}", progress_knowledge_matches=10)
        for i in range(10)
    ]

    assert [item["pct"] for item in results] == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert results[-1]["completed"] is True
    assert isinstance(subsystem.completed_goals, int)
    assert subsystem.completed_goals == 1
    assert subsystem.complete_goal(goal["id"]) == 0
    assert subsystem.completed_goals == 1


# ============================================================
# 3. Чекпоинт: процент и синхронизация подсистемы
# ============================================================
def test_checkpoint_restores_percentage_and_syncs_subsystem(agent):
    from src.core.agent import DigitalBeing
    from src.core.checkpoint_serializer import (
        apply_state_to_agent,
        build_state_from_agent,
    )

    goal_id = agent.active_goal["id"]
    agent._goal_progress[goal_id]["matched_concepts"] = {"тема 1", "тема 2"}
    agent._goal_progress[goal_id]["percentage"] = 40
    agent.completed_goals = 2

    state = build_state_from_agent(agent)
    restored = DigitalBeing("Stage5Restored")
    apply_state_to_agent(restored, state)

    assert restored._goal_progress[goal_id]["percentage"] == 40
    assert restored._goal_progress[goal_id]["matched_concepts"] == {"тема 1", "тема 2"}
    assert restored.completed_goals == 2
    assert restored.goal_subsystem.completed_goals == 2
    assert restored.goal_subsystem.goals is restored.goals


def test_checkpoint_accepts_old_goal_progress_format(agent):
    from src.core.checkpoint_serializer import apply_state_to_agent

    state = {
        "energy": 100,
        "cycle_count": 7,
        "completed_goals": 0,
        "goals": [{"id": 1, "title": "X", "status": "active"}],
        "active_goal": "X",
        "_goal_progress": {"1": ["тема A", "тема B"]},
    }
    apply_state_to_agent(agent, state)

    assert agent._goal_progress[1]["matched_concepts"] == {"тема A", "тема B"}
    assert agent._goal_progress[1]["percentage"] == 0


# ============================================================
# 4. Циклы и типы действий
# ============================================================
def test_agent_owns_cycle_count():
    """Счётчик циклов принадлежит агенту, а не внешнему циклу.

    Раньше консольный цикл вёл локальную переменную и писал её в агента
    каждой итерацией; агентский счётчик при этом оставался нулевым, и
    чекпоинты/эволюция ломались. Теперь счётчик увеличивает раннер
    (``agent.cycle_count += 1``), а точка входа своей переменной не
    держит — синхронизировать нечего.

    Поведение (шаг = +1 цикл) проверяется в
    ``tests/test_runner_speed.py::test_step_once_advances_exactly_one_cycle``.
    """
    entry_source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "cycle_count = cycle_count" not in entry_source
    assert "cycle_count += 1" not in entry_source

    runner_source = (
        PROJECT_ROOT / "src" / "core" / "agent_runner.py"
    ).read_text(encoding="utf-8")
    assert "self.agent.cycle_count += 1" in runner_source


def test_action_types_are_counted(agent):
    agent.act("[Гипотеза] это возможно")
    agent.act("[Декомпозиция] разбиваю на части")
    agent.act("Знаю ответ: 42")
    agent.act("Не нашел информацию по 'x'")

    counts = agent._action_type_counts
    assert counts["hypothesis"] == 1
    assert counts["decomposition"] == 1
    assert counts["know_answer"] == 1
    assert counts["search_miss"] == 1
    assert sum(counts.values()) == 4

    state = agent.get_full_state()
    assert state["agent"]["action_types"] == counts


# ============================================================
# 5. Внутренняя мотивация не создаёт «цель без id»
# ============================================================
def test_intrinsic_goal_has_id_and_is_synced(agent):
    goal = agent.internal_motivation.force_generate_goal("curiosity")
    assert goal is not None

    active = agent.active_goal
    assert active.get("id") is not None
    assert active["source"] == "intrinsic"
    assert active["status"] == "active"
    assert active in agent.goals
    assert agent.goal_subsystem.active_goal is active
    assert sum(1 for g in agent.goals if g["status"] == "active") == 1

    # Прогресс пишется в id цели, а не в None.
    assert active["id"] in agent._goal_progress
    assert agent._check_goal_progress("произвольная тема")["pct"] > 0


# ============================================================
# 6. Декомпозиция даёт следующий шаг
# ============================================================
def test_decomposition_enqueues_one_open_question(agent):
    thought = agent.think("трансформер архитектура")

    assert thought.startswith("[Декомпозиция]")
    texts = [q["text"] for q in agent.get_open_questions()]
    assert texts == ["что такое трансформер"]
    assert all("стратегия=" not in text for text in texts)

    # Повторная декомпозиция не должна дублировать уже поставленный вопрос
    # и не должна снова разбирать тот же запрос.
    second = agent.think("трансформер архитектура")
    assert not second.startswith("[Декомпозиция]")
    assert "трансформер архитектура" in agent.thinking._decomposed_queries
    assert [q["text"] for q in agent.get_open_questions()] == texts


def test_noun_phrase_is_not_split_into_separate_words(agent):
    pipeline = agent.thinking

    assert pipeline._decompose_query("компьютерное зрение") is None
    assert pipeline._decompose_query("обучение с учителем") is None
    assert pipeline._decompose_query("в чем смысл жизни") is None
    assert pipeline._decompose_query("как работает мышление") is None

    parts = pipeline._decompose_query("жизнь и смерть") or []
    assert set(parts) == {"что такое жизнь", "что такое смерть"}


def test_strategy_annotation_is_not_decomposed(agent):
    stimulus = (
        "вопрос: что такое сознание "
        "[стратегия=mental_model_lookup, попытка 1/5]"
    )
    thought = agent.think(stimulus)

    assert "mental_model_lookup" not in thought
    assert "Декомпозиция" not in thought
    assert not any(
        "mental_model_lookup" in q["text"]
        for q in agent.get_open_questions()
    )
