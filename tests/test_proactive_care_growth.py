# -*- coding: utf-8 -*-
"""«Собеседник-8»: care-орган растёт из социального опыта.

Проверяем композицию заботы (proactive_communication):
- формулировки опираются на реальный записанный опыт (тема диалога,
  выученные человеком фразы) — и честно общие, когда опыта нет;
- ротация детерминированная: подряд одинаковых реплик нет;
- обещание человека («не тревожься») сохраняется во всех вариантах.

Триггеры, пороги и воля здесь не проверяются — только текст заботы.
"""
from types import SimpleNamespace

from src.core.subsystems.proactive_communication import ProactiveCommunication

TOPIC = "тихое мерцание северного сияния"
LEARNED = "теплый свет над северной рекой"


class _Interaction:
    def __init__(self, history):
        self._history = history

    def get_history(self, limit):
        return self._history[-limit:]


class _UserModel:
    def __init__(self, tolerance):
        self._tolerance = tolerance

    def has_silence_tolerance(self):
        return self._tolerance


def _agent(history=(), learned=None, tolerance=False):
    interaction = _Interaction(
        [{"sender": "user", "content": text} for text in history]
    )
    return SimpleNamespace(
        user_interaction=interaction,
        user_model=_UserModel(tolerance),
        dialogue_learning=SimpleNamespace(learned=learned or {}),
    )


def _comm(agent):
    return ProactiveCommunication(
        agent_name="Тэсс",
        user_interaction=agent.user_interaction,
        attachment=None,
    )


def test_care_without_experience_is_honest_general():
    agent = _agent()
    comm = _comm(agent)
    msg = comm._compose_care_message(agent, 100)
    assert msg["msg_type"] == "care"
    assert msg["context"] == "silence_detected"
    # Нет записанного опыта — нет выдуманных отсылок.
    assert "«" not in msg["content"]
    assert "научил" not in msg["content"]


def test_care_uses_dialogue_topic():
    agent = _agent(history=[TOPIC])
    comm = _comm(agent)
    msg = comm._compose_care_message(agent, 100)
    assert TOPIC[:20] in msg["content"]


def test_care_uses_learned_social_phrase():
    agent = _agent(learned={LEARNED: {"act": "social", "cycle": 5}})
    comm = _comm(agent)
    seen = {
        comm._compose_care_message(agent, 100 + i * 60)["content"]
        for i in range(3)
    }
    assert any(LEARNED[:20] in text for text in seen)
    assert any("научил" in text for text in seen)


def test_care_ignores_non_social_learned():
    agent = _agent(learned={LEARNED: {"act": "request", "cycle": 5}})
    comm = _comm(agent)
    seen = {
        comm._compose_care_message(agent, 100 + i * 60)["content"]
        for i in range(5)
    }
    assert all(LEARNED[:20] not in text for text in seen)


def test_care_rotation_has_no_immediate_repeats():
    agent = _agent(
        history=[TOPIC],
        learned={LEARNED: {"act": "social", "cycle": 5}},
    )
    comm = _comm(agent)
    sequence = [
        comm._compose_care_message(agent, 100 + i * 60)["content"]
        for i in range(10)
    ]
    for previous, current in zip(sequence, sequence[1:]):
        assert previous != current


def test_care_rotation_is_deterministic():
    def run():
        agent = _agent(
            history=[TOPIC],
            learned={LEARNED: {"act": "social", "cycle": 5}},
        )
        comm = _comm(agent)
        return [
            comm._compose_care_message(agent, 100 + i * 60)["content"]
            for i in range(6)
        ]

    assert run() == run()


def test_promise_care_keeps_promise_and_rotates():
    agent = _agent(
        history=[TOPIC],
        learned={LEARNED: {"act": "social", "cycle": 5}},
        tolerance=True,
    )
    comm = _comm(agent)
    sequence = [
        comm._compose_care_with_promise(agent, 100 + i * 60)
        for i in range(8)
    ]
    for msg in sequence:
        assert msg["context"] == "silence_with_promise"
        assert "не тревожу" in msg["content"]
    contents = [m["content"] for m in sequence]
    for previous, current in zip(contents, contents[1:]):
        assert previous != current
    # Опыт используется: и тема, и выученная фраза встречаются в серии.
    assert any(TOPIC[:20] in text for text in contents)
    assert any(LEARNED[:20] in text for text in contents)


def test_promise_care_without_experience_stays_honest():
    agent = _agent(tolerance=True)
    comm = _comm(agent)
    msg = comm._compose_care_with_promise(agent, 100)
    assert "не тревожу" in msg["content"]
    assert "«" not in msg["content"]
