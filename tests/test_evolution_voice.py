"""Тесты «Эволюция-1»: голос — решение человека по предложению.

Дверь «одобри/отклони» срабатывает только при живом ожидающем
предложении; обычная речь не перехватывается. Решение пишется в файл
предложения, применения кода не происходит никогда.
"""

import json
import os
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import Events
from src.core.paths import data_path


@pytest.fixture(autouse=True)
def _clean_proposals_dir():
    """Папка предложений изолирована per-session, чистим перед каждым тестом."""
    d = data_path("architecture_proposals")
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        if f.endswith(".json"):
            os.remove(os.path.join(d, f))
    yield


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(name="EvoDoor"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


def _replies(bus):
    return [
        dict(data or {}) for name, data in bus.published if name == Events.AGENT_MESSAGE
    ]


def _read_proposal(agent, proposal_id):
    path = os.path.join(
        agent.architecture_proposal.proposals_dir, f"{proposal_id}.json"
    )
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.asyncio
async def test_approve_by_id_changes_status_only():
    agent, runner, bus = _make_runner()
    created = agent.architecture_proposal.propose(
        "config_change", "Тестовый рычаг", "проверка двери", cycle=1
    )
    pid = created["proposal_id"]

    await runner._on_user_message(SimpleNamespace(data={"text": f"одобри {pid}"}))

    stored = _read_proposal(agent, pid)
    assert stored["status"] == "approved"
    assert "decided_at" in stored
    # Код не применён: предложение остаётся письмом, внедряет человек.
    texts = [d.get("content", "") for d in _replies(bus)]
    assert any("одобрено" in t for t in texts)
    assert any("не меняю" in t for t in texts)


@pytest.mark.asyncio
async def test_reject_latest_without_id():
    agent, runner, bus = _make_runner()
    created = agent.architecture_proposal.propose(
        "config_change", "Второй рычаг", "проверка отклонения", cycle=1
    )
    pid = created["proposal_id"]

    await runner._on_user_message(SimpleNamespace(data={"text": "отклони"}))

    assert _read_proposal(agent, pid)["status"] == "rejected"
    texts = [d.get("content", "") for d in _replies(bus)]
    assert any("отклонено" in t for t in texts)


@pytest.mark.asyncio
async def test_decision_door_is_silent_without_pending():
    """«Одобряю твой поступок» в обычной речи — не команда решения."""
    agent, runner, bus = _make_runner()

    await runner._on_user_message(SimpleNamespace(data={"text": "Одобряю твой выбор."}))

    # Дверь не сработала: ответа «одобрено/отклонено» нет.
    texts = [d.get("content", "") for d in _replies(bus)]
    assert not any("одобрено" in t and "предложение" in t for t in texts)
    assert agent.architecture_proposal.list_pending() == []


@pytest.mark.asyncio
async def test_decide_twice_refused_honestly():
    agent, runner, bus = _make_runner("EvoDoorTwice")
    created = agent.architecture_proposal.propose(
        "config_change", "Рычаг", "повторное решение", cycle=1
    )
    pid = created["proposal_id"]

    await runner._on_user_message(SimpleNamespace(data={"text": f"одобри {pid}"}))
    await runner._on_user_message(SimpleNamespace(data={"text": f"отклони {pid}"}))

    assert _read_proposal(agent, pid)["status"] == "approved"
    texts = [d.get("content", "") for d in _replies(bus)]
    assert any("уже решено" in t for t in texts)
