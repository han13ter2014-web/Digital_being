"""Поведение: агент отвечает из памяти, когда у него есть основание.

Регрессия: ``thinking_pipeline`` спрашивает у ментальной модели
``can_answer_about``, а тот требует уверенность выше 0.4. Уверенность не
могла вырасти выше 0.1 (см. tests/test_confidence_evidence.py), поэтому
ветка «[Ментальная модель]» не срабатывала НИКОГДА: агент каждый раз
начинал с гипотезы, даже если уже встречал тему восемь раз.
"""

import pytest

from src.core.agent import DigitalBeing


@pytest.fixture()
def agent():
    a = DigitalBeing(name="AnswerAgent")
    searcher = getattr(a, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    return a


def _ground(agent, concept: str, times: int = 3, valence: float = 0.3) -> None:
    """Дать концепции достаточно свидетельств и формулировку."""
    for index in range(times):
        agent.mental_models.encounter_concept(
            concept, f"гипотеза_цикл_{index}", "следы памяти и связи", valence
        )


def test_grounded_concept_is_answered_from_memory(agent):
    _ground(agent, "память")
    assert agent.mental_models.can_answer_about("память")

    thought = agent.think("что такое память")

    assert thought.startswith("[Ментальная модель]"), thought[:120]
    assert "память" in thought


def test_ungrounded_concept_falls_back_to_hypothesis(agent):
    """Одна встреча — не основание отвечать: будет гипотеза."""
    agent.mental_models.encounter_concept(
        "квант", "гипотеза_цикл_1", "неделимость", 0.3
    )
    assert not agent.mental_models.can_answer_about("квант")

    thought = agent.think("что такое квант")

    assert "[Ментальная модель]" not in thought


def test_repeated_meetings_do_not_leave_agent_guessing(agent):
    """Восемь встреч — это знание, а не повод гадать снова.

    Именно этот случай дал замер: 8 встреч, определение 108 символов,
    уверенность 0.100, ответ «[Гипотеза]».
    """
    _ground(agent, "сознание", times=8)

    thought = agent.think("что такое сознание")

    assert thought.startswith("[Ментальная модель]"), thought[:120]
