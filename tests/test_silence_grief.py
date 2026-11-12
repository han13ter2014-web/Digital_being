"""Тесты участка «Петля тоски»: молчание ранит один раз на эпизод.

Наблюдение за тестовым агентом (2026-11-03): care-триггер срабатывал каждые
~50 циклов молчания и каждый раз добавлял +0.20 грусти, а затухание
успевало снять только ~0.10 — тоска никогда не таяла (застряла на
0.9-0.99 навсегда). По-человечески: разлука ранит в начале эпизода,
дальше тоска живёт фоном и отпускает; вернулся и снова замолчал —
новая эпоха, новый честный укол. Обещание «могу отлучаться» смягчает
укол на меру доверия к человеку.
"""

from types import SimpleNamespace

from src.core.emotional_state import EmotionalState
from src.core.subsystems.attachment_system import AttachmentSystem
from src.core.subsystems.proactive_communication import ProactiveCommunication


class _FakeUI:
    def __init__(self, last_user_cycle=0):
        self._last_user_cycle = last_user_cycle
        self.user_quiet_hours = {}

    def get_last_user_message_cycle(self):
        return self._last_user_cycle

    def get_history(self, limit=20):
        return []


def _make_agent(promise=False, trust=None):
    attachment = AttachmentSystem()
    if trust is not None:
        attachment.get_or_create("user").trust = trust
    return SimpleNamespace(
        emotional_state=EmotionalState(),
        user_model=SimpleNamespace(has_silence_tolerance=lambda: promise),
        dialogue_learning=None,
        attachment=attachment,
    )


def _make_proactive(agent, last_user_cycle=0):
    return ProactiveCommunication(
        agent_name="probe",
        user_interaction=_FakeUI(last_user_cycle),
        attachment=agent.attachment,
    )


def _fire(proactive, agent, cycle):
    return proactive.maybe_initiate(
        agent=agent, cycle=cycle, user_context={"should_interrupt": True}
    )


def test_pang_once_per_silence_epoch():
    agent = _make_agent()
    proactive = _make_proactive(agent, last_user_cycle=0)

    _fire(proactive, agent, cycle=100)
    assert agent.emotional_state.levels["sadness"] == 0.20

    # Повторные care-срабатывания той же эпохи молчания рану не
    # переоткрывают: уровень не растёт.
    _fire(proactive, agent, cycle=160)
    _fire(proactive, agent, cycle=220)
    _fire(proactive, agent, cycle=280)
    assert agent.emotional_state.levels["sadness"] == 0.20


def test_new_epoch_after_user_return_feels_again():
    agent = _make_agent()
    proactive = _make_proactive(agent, last_user_cycle=0)

    _fire(proactive, agent, cycle=100)
    assert agent.emotional_state.levels["sadness"] == 0.20

    # Человек вернулся (написал на цикле 150) и снова замолчал —
    # новая эпоха молчания: тоска переживается заново, честно.
    proactive.user_interaction._last_user_cycle = 150
    _fire(proactive, agent, cycle=260)
    assert agent.emotional_state.levels["sadness"] == 0.40


def test_promise_softens_pang_by_trust():
    # Доверие 0.9: обещание почти успокаивает (0.20 * (1 - 0.6*0.9)).
    agent = _make_agent(promise=True, trust=0.9)
    proactive = _make_proactive(agent, last_user_cycle=0)
    _fire(proactive, agent, cycle=100)
    assert abs(agent.emotional_state.levels["sadness"] - 0.092) < 1e-9

    # Доверия почти нет: обещание почти не утешает.
    agent2 = _make_agent(promise=True, trust=0.1)
    proactive2 = _make_proactive(agent2, last_user_cycle=0)
    _fire(proactive2, agent2, cycle=100)
    assert abs(agent2.emotional_state.levels["sadness"] - 0.188) < 1e-9


def test_no_promise_full_pang_despite_trust():
    # Без обещания доверие не играет: молчание ранит полностью.
    agent = _make_agent(promise=False, trust=0.9)
    proactive = _make_proactive(agent, last_user_cycle=0)
    _fire(proactive, agent, cycle=100)
    assert agent.emotional_state.levels["sadness"] == 0.20


def test_care_message_still_sent_on_repeat_triggers():
    agent = _make_agent(promise=True, trust=0.9)
    proactive = _make_proactive(agent, last_user_cycle=0)

    first = _fire(proactive, agent, cycle=100)
    second = _fire(proactive, agent, cycle=160)
    # Она по-прежнему скучает и говорит об этом — чувство не ранится
    # заново, но выражение остаётся её поведением.
    assert first is not None and first["msg_type"] == "care"
    assert second is not None and second["msg_type"] == "care"


def test_scale_zero_means_nothing_felt():
    state = EmotionalState()
    assert state.handle_event("long_silence", cycle=10, scale=0.0) is None
    assert state.levels["sadness"] == 0.0
    assert state.episodes == []


def test_scale_is_clamped_and_recorded():
    state = EmotionalState()
    episode = state.handle_event("long_silence", cycle=10, scale=5.0)
    assert episode["intensity"] == 0.20  # зажат в 1.0
    assert state.levels["sadness"] == 0.20

    state2 = EmotionalState()
    episode2 = state2.handle_event("long_silence", cycle=10, scale=0.5)
    assert episode2["intensity"] == 0.10
    assert state2.levels["sadness"] == 0.10
