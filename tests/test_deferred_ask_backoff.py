"""Тесты TICKET-2: вечное отложенное намерение и ложные тревоги.

Наблюдение (сессии DeepSeek/BigPickle, 2026-11-05): 75 из 121 цикла —
ask_user с результатом «отложен (не сейчас)», намерение не закрывается
и не теряет вес; «⚠️ Нарушен гомеостаз: 2 тревоги» — каждый цикл.

Причины: тревоги считались отклонением от оптимума (стартовые уровни
энергии и памяти — вечные две ложные тревоги); у отложенного вопроса
не было паузы — он выбирался заново на следующем же цикле.

Решение: тревога — выход за жизнеспособную полосу [min, max];
отложенный ask_user получает экспоненциальный backoff (5,10,20,40,50).
"""
from types import SimpleNamespace

from src.core.agent import DigitalBeing
from src.emotion.survival_instincts import SurvivalInstincts


# ---------------- гомеостаз ----------------

def test_default_levels_raise_no_phantom_alarms():
    instincts = SurvivalInstincts()
    report = instincts.check_homeostasis()
    assert report["homeostasis_maintained"] is True
    assert report["alarms"] == []


def test_full_energy_is_not_an_alarm():
    instincts = SurvivalInstincts()
    instincts.homeostasis_state["energy"]["level"] = 100.0
    assert instincts.check_homeostasis()["alarms"] == []


def test_real_violation_still_alarms():
    instincts = SurvivalInstincts()
    instincts.homeostasis_state["energy"]["level"] = 10.0  # ниже min=20
    report = instincts.check_homeostasis()
    assert report["homeostasis_maintained"] is False
    assert report["alarms"][0]["resource"] == "energy"


# ---------------- backoff отложенного вопроса ----------------

class _BusyInteraction:
    """Вопрос нельзя задать: пауза/лимит (status != queued)."""

    def ask_user(self, **kwargs):
        return {"status": "failed", "reason": "пауза"}


class _OpenInteraction:
    def __init__(self):
        self.asked = []

    def ask_user(self, **kwargs):
        self.asked.append(kwargs["question"])
        return {"status": "queued", "id": 1}


def _agent(interaction, cycle=100):
    return SimpleNamespace(
        cycle_count=cycle,
        user_interaction=interaction,
        _deferred_intentions={},
        _is_learnable=lambda target: True,
        _recently_explained_by_user=lambda target: False,
        _record_will=lambda *args: None,
        _META_TOPIC_WORDS=frozenset(),
    )


def test_deferred_question_gets_exponential_backoff():
    interaction = _BusyInteraction()
    agent = _agent(interaction, cycle=100)

    DigitalBeing._act_ask_user(agent, "обучение")
    until, count = agent._deferred_intentions[("ask_user", "обучение")]
    assert (until, count) == (105, 1)

    agent.cycle_count = 105
    DigitalBeing._act_ask_user(agent, "обучение")
    until, count = agent._deferred_intentions[("ask_user", "обучение")]
    assert (until, count) == (115, 2)

    # Backoff растёт, но ограничен 50 циклами.
    for cycle in (115, 135, 175, 225, 275):
        agent.cycle_count = cycle
        DigitalBeing._act_ask_user(agent, "обучение")
    until, count = agent._deferred_intentions[("ask_user", "обучение")]
    assert until - 275 <= 50


def test_successful_question_resets_backoff():
    busy = _BusyInteraction()
    agent = _agent(busy, cycle=100)
    DigitalBeing._act_ask_user(agent, "обучение")
    assert ("ask_user", "обучение") in agent._deferred_intentions

    agent.user_interaction = _OpenInteraction()
    DigitalBeing._act_ask_user(agent, "обучение")
    assert ("ask_user", "обучение") not in agent._deferred_intentions


def test_continuation_skips_deferred_topic():
    """Пока backoff жив, continuation не предлагает тему заново."""
    from src.cognition.intention_continuation import continuation_candidate

    entry = {
        "id": 1, "action": "ask_user", "target": "обучение",
        "status": "performed", "cycle": 90, "outcome": {"had_effect": False},
    }
    agent = SimpleNamespace(
        cycle_count=100,
        _waiting_intentions={},
        _intention_history=[entry],
        _deferred_intentions={("ask_user", "обучение"): (150, 1)},
        _normalize_action=lambda a: a,
        _is_candidate_available=lambda candidate: True,
        loop_closer=SimpleNamespace(is_stuck=lambda action: False),
    )
    assert continuation_candidate(agent) is None

    # Пауза вышла — тема снова может быть предложена.
    agent.cycle_count = 150
    candidate = continuation_candidate(agent)
    assert candidate is not None
    assert candidate["action"] == "ask_user"
