"""Осознанное переименование: переспрос при принятом имени, отказ сохраняет имя.

Покрывает ступень 3.1 (PATCH_WORK_STATUS: «Согласие на альтернативное имя
... требуют отдельной проверки»):
- classify_confirmation: короткие «да/нет» vs обычная речь;
- offer_rename / confirm_rename / cancel_rename (решение за Core, 30% отказ);
- чинёный accept_alternative + decline_alternative;
- гейт AgentRunner по фазам (awaiting/considering/renaming_pending/completed).
"""

import random as _random

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from src.core.agent_runner import AgentRunner
from src.core.subsystems.naming_dialogue import (
    NamingDialogue,
    classify_confirmation,
)


def _interaction():
    ui = Mock()
    ui.send_message.return_value = "msg-1"
    return ui


def _dialogue(agent_name="Тэсс"):
    return NamingDialogue(agent_name=agent_name, user_interaction=_interaction())


class _NamingAgent(SimpleNamespace):
    """Минимальный агент: propose_name делегирует в NamingDialogue."""

    def propose_name(self, name, cycle=0):
        return self.naming_dialogue.process_name_proposal(
            name, agent=self, cycle=cycle,
        )


def _runner(agent):
    runner = AgentRunner.__new__(AgentRunner)
    runner.name = agent.name
    runner.agent = agent
    runner.bus = SimpleNamespace(publish=AsyncMock(), publish_sync=Mock())
    return runner


# ============================================================
# classify_confirmation
# ============================================================

@pytest.mark.parametrize("text,expected", [
    ("да", "affirmative"),
    ("Хорошо.", "affirmative"),
    ("Давай!", "affirmative"),
    ("Ок", "affirmative"),
    ("Пусть будет так", "affirmative"),
    ("нет", "negative"),
    ("Не надо", "negative"),
    ("Оставь как есть", "negative"),
    ("не знаю", "unknown"),
    ("Зовут Кот", "unknown"),
    ("Да, я тебя слышу и стараюсь понять.", "unknown"),
    ("", "unknown"),
])
def test_classify_confirmation(text, expected):
    assert classify_confirmation(text) == expected


# ============================================================
# Осознанное переименование (NamingDialogue)
# ============================================================

def _completed_dialogue(agent_name="Тэсс"):
    nd = _dialogue(agent_name)
    nd.phase = NamingDialogue.PHASE_COMPLETED
    return nd


def test_offer_rename_asks_confirmation_and_keeps_name():
    nd = _completed_dialogue()
    agent = SimpleNamespace(name="Тэсс", attachment=None)

    result = nd.offer_rename("Омелла", agent=agent, cycle=5)

    assert result["status"] == "rename_confirmation"
    assert result["candidate"] == "Омелла"
    assert result["awaiting_user_decision"] is True
    assert nd.phase == NamingDialogue.PHASE_RENAMING_PENDING
    assert nd._rename_candidate == "Омелла"
    assert agent.name == "Тэсс"
    nd.user_interaction.send_message.assert_called_once()
    assert nd.user_interaction.send_message.call_args.kwargs["context"] == \
        "rename_confirmation"


def test_completed_phase_proposal_routes_to_confirmation():
    """«/name X» и естественная речь в фазе completed не меняют имя молча."""
    nd = _completed_dialogue()
    agent = SimpleNamespace(name="Тэсс", attachment=None)

    result = nd.process_name_proposal("Омелла", agent=agent, cycle=6)

    assert result["status"] == "rename_confirmation"
    assert agent.name == "Тэсс"
    assert nd.phase == NamingDialogue.PHASE_RENAMING_PENDING


def test_offer_rename_same_name_rejected():
    nd = _completed_dialogue()
    agent = SimpleNamespace(name="Тэсс", attachment=None)

    result = nd.offer_rename("Тэсс", agent=agent, cycle=1)

    assert result["status"] == "rejected"
    assert nd.phase == NamingDialogue.PHASE_COMPLETED


def test_confirm_rename_accepts_and_changes_name(monkeypatch):
    monkeypatch.setattr(_random, "random", lambda: 0.99)
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_RENAMING_PENDING
    nd._rename_candidate = "Омелла"
    agent = SimpleNamespace(name="Тэсс", attachment=None)

    result = nd.confirm_rename(agent=agent, cycle=7)

    assert result["status"] == "accepted"
    assert result["new_name"] == "Омелла"
    assert agent.name == "Омелла"
    assert nd.phase == NamingDialogue.PHASE_COMPLETED
    assert nd.user_interaction.agent_name == "Омелла"
    entry = nd._name_history[-1]
    assert entry["source"] == "rename"
    assert entry["old_name"] == "Тэсс"


def test_confirm_rename_refusal_keeps_name(monkeypatch):
    """30% отказ Core: прежнее имя сохраняется, это не молчаливая смена."""
    monkeypatch.setattr(_random, "random", lambda: 0.1)
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_RENAMING_PENDING
    nd._rename_candidate = "Омелла"
    agent = SimpleNamespace(name="Тэсс", attachment=None)

    result = nd.confirm_rename(agent=agent, cycle=7)

    assert result["status"] == "rename_declined"
    assert result["kept_name"] == "Тэсс"
    assert agent.name == "Тэсс"
    assert nd.phase == NamingDialogue.PHASE_COMPLETED
    assert nd._rename_candidate == ""


def test_cancel_rename_keeps_name():
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_RENAMING_PENDING
    nd._rename_candidate = "Омелла"
    agent = SimpleNamespace(name="Тэсс", attachment=None)

    result = nd.cancel_rename(agent=agent, cycle=8)

    assert result["status"] == "rename_cancelled"
    assert result["kept_name"] == "Тэсс"
    assert agent.name == "Тэсс"
    assert nd.phase == NamingDialogue.PHASE_COMPLETED


def test_confirm_rename_without_pending_is_safe():
    """Фаза из чекпоинта без кандидата не должна зависнуть."""
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_RENAMING_PENDING
    nd._rename_candidate = ""
    agent = SimpleNamespace(name="Тэсс", attachment=None)

    result = nd.confirm_rename(agent=agent, cycle=1)

    assert result["status"] == "no_rename_pending"
    assert nd.phase == NamingDialogue.PHASE_COMPLETED


# ============================================================
# Альтернативное имя: починенный accept + новый decline
# ============================================================

def test_accept_alternative_applies_agent_alternative():
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_CONSIDERING
    nd._proposed_name = "Малютка"
    nd._alternative_name = "Alpha Jr."
    agent = SimpleNamespace(name="Alpha", attachment=None)

    result = nd.accept_alternative(agent=agent, cycle=9)

    assert result["status"] == "alternative_accepted"
    assert result["new_name"] == "Alpha Jr."
    assert agent.name == "Alpha Jr."
    assert nd.phase == NamingDialogue.PHASE_COMPLETED
    assert nd._name_history[-1]["source"] == "alternative"


def test_decline_alternative_keeps_user_name():
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_CONSIDERING
    nd._proposed_name = "Малютка"
    nd._alternative_name = "Alpha Jr."
    agent = SimpleNamespace(name="Alpha", attachment=None)

    result = nd.decline_alternative(agent=agent, cycle=9)

    assert result["status"] == "accepted"
    assert agent.name == "Малютка"
    assert nd._name_history[-1]["source"] == "user"


def test_alternative_decision_without_pending():
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_CONSIDERING
    agent = SimpleNamespace(name="Alpha", attachment=None)

    assert nd.accept_alternative(agent=agent)["status"] == "no_alternative_pending"
    assert nd.decline_alternative(agent=agent)["status"] == "no_alternative_pending"


def test_propose_alternative_stores_alternative(monkeypatch):
    monkeypatch.setattr(_random, "random", lambda: 0.1)  # 30% ветка
    monkeypatch.setattr(_random, "choice", lambda seq: seq[0])
    nd = _dialogue()
    nd.phase = NamingDialogue.PHASE_AWAITING_NAME
    agent = SimpleNamespace(name="Alpha", attachment=None)

    result = nd.process_name_proposal("Малютка", agent=agent, cycle=2)

    assert result["status"] == "alternative_proposed"
    assert nd._alternative_name == result["agent_alternative"]
    assert nd._alternative_name == "Alpha Jr."
    assert nd.phase == NamingDialogue.PHASE_CONSIDERING


# ============================================================
# Гейт AgentRunner по фазам
# ============================================================

@pytest.mark.asyncio
async def test_gate_completed_name_proposal_asks_confirmation():
    nd = _completed_dialogue()
    agent = _NamingAgent(
        name="Тэсс", cycle_count=7, attachment=None, naming_dialogue=nd,
    )
    runner = _runner(agent)

    await runner._on_user_message(
        SimpleNamespace(data={"text": "Пусть тебя зовут Омелла"})
    )

    assert agent.name == "Тэсс"
    assert nd.phase == NamingDialogue.PHASE_RENAMING_PENDING
    runner.bus.publish.assert_awaited_once()
    assert runner.bus.publish.call_args.args[0] == "agent_thought"
    assert "Омелла" in runner.bus.publish.call_args.args[1]["text"]
    assert "да" in runner.bus.publish.call_args.args[1]["text"]


@pytest.mark.asyncio
async def test_gate_completed_confirm_yes_renames(monkeypatch):
    monkeypatch.setattr(_random, "random", lambda: 0.99)
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_RENAMING_PENDING
    nd._rename_candidate = "Омелла"
    agent = _NamingAgent(
        name="Тэсс", cycle_count=8, attachment=None, naming_dialogue=nd,
    )
    runner = _runner(agent)

    await runner._on_user_message(SimpleNamespace(data={"text": "да"}))

    assert agent.name == "Омелла"
    assert runner.name == "Омелла"
    runner.bus.publish_sync.assert_called_once()
    assert runner.bus.publish_sync.call_args.args[0] == "agent_name_changed"
    assert runner.bus.publish_sync.call_args.args[1]["new_name"] == "Омелла"


@pytest.mark.asyncio
async def test_gate_completed_confirm_no_keeps_name():
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_RENAMING_PENDING
    nd._rename_candidate = "Омелла"
    agent = _NamingAgent(
        name="Тэсс", cycle_count=8, attachment=None, naming_dialogue=nd,
    )
    runner = _runner(agent)

    await runner._on_user_message(SimpleNamespace(data={"text": "нет"}))

    assert agent.name == "Тэсс"
    assert nd.phase == NamingDialogue.PHASE_COMPLETED
    runner.bus.publish.assert_awaited_once()
    assert "Тэсс" in runner.bus.publish.call_args.args[1]["text"]


@pytest.mark.asyncio
async def test_gate_considering_yes_accepts_alternative():
    nd = _completed_dialogue()
    nd.phase = NamingDialogue.PHASE_CONSIDERING
    nd._proposed_name = "Малютка"
    nd._alternative_name = "Alpha Jr."
    agent = _NamingAgent(
        name="Alpha", cycle_count=9, attachment=None, naming_dialogue=nd,
    )
    runner = _runner(agent)

    await runner._on_user_message(SimpleNamespace(data={"text": "да"}))

    assert agent.name == "Alpha Jr."
    runner.bus.publish_sync.assert_called_once()
    assert runner.bus.publish_sync.call_args.args[0] == "agent_name_changed"


@pytest.mark.asyncio
async def test_gate_completed_confirmation_words_are_normal_speech():
    """«да/нет/хорошо/не знаю» без активного диалога не перехватываются."""
    nd = _completed_dialogue()
    agent = _NamingAgent(
        name="Тэсс", cycle_count=3, attachment=None, naming_dialogue=nd,
    )

    assert await agent_naming_gate(agent, "хорошо") is False
    assert await agent_naming_gate(agent, "не знаю") is False
    assert nd.phase == NamingDialogue.PHASE_COMPLETED


@pytest.mark.asyncio
async def test_gate_completed_renames_only_on_real_proposal():
    """Осмысленное имя в фазе completed перехватывается, обычная речь — нет."""
    nd = _completed_dialogue()
    agent = _NamingAgent(
        name="Тэсс", cycle_count=3, attachment=None, naming_dialogue=nd,
    )

    assert await agent_naming_gate(agent, "Пусть тебя зовут Омелла") is True
    assert nd.phase == NamingDialogue.PHASE_RENAMING_PENDING


async def agent_naming_gate(agent, text):
    runner = _runner(agent)
    return await runner._handle_naming_phase(agent.naming_dialogue, text)
