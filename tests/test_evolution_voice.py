"""Тесты «Эволюция-1»: голос — решение человека по предложению.

Дверь «одобри/отклони» срабатывает только при живом ожидающем
предложении; обычная речь не перехватывается. Решение пишется в файл.
Новые проверенные config_change исполняются ограниченно; старые записи
без закреплённого рычага задним числом не исполняются.
"""

import json
import os
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import Events
from src.core.paths import data_path
from src.evolution.self_coding import draft_config_change


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
async def test_legacy_approval_is_not_executed_retroactively():
    agent, runner, bus = _make_runner()
    created = agent.architecture_proposal.propose(
        "config_change", "Тестовый рычаг", "проверка двери", cycle=1
    )
    pid = created["proposal_id"]

    await runner._on_user_message(SimpleNamespace(data={"text": f"одобри {pid}"}))

    stored = _read_proposal(agent, pid)
    assert stored["status"] == "approved"
    assert "decided_at" in stored
    assert stored["execution"]["ok"] is False
    assert agent._safe_config_overrides == {}
    texts = [d.get("content", "") for d in _replies(bus)]
    assert any("Одобрение записала" in t for t in texts)
    assert any("не удалось" in t and "Прежнее значение сохранено" in t for t in texts)


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


def _propose_executable(agent):
    draft = draft_config_change("energy_efficiency", agent)
    created = agent.architecture_proposal.propose(
        "config_change",
        draft["title"],
        "Проверенное изменение порога отдыха",
        code_snippet=draft["diff"],
        cycle=agent.cycle_count,
        extra={**draft, "verification": {"ran": True, "passed": True, "cycles": 5}},
    )
    return created["proposal_id"], draft


@pytest.mark.asyncio
async def test_approve_latest_without_id_executes_safe_config_change():
    agent, runner, bus = _make_runner("EvoExecute")
    proposal_id, draft = _propose_executable(agent)

    await runner._on_user_message(SimpleNamespace(data={"text": "одобри"}))

    stored = _read_proposal(agent, proposal_id)
    assert stored["status"] == "implemented"
    assert stored["execution"]["ok"] is True
    assert agent._safe_config_overrides[draft["attr"]] == draft["new"]
    texts = [d.get("content", "") for d in _replies(bus)]
    assert any("одобрено и применено" in text for text in texts)
    assert any("будет восстановлено после перезапуска" in text for text in texts)


@pytest.mark.asyncio
async def test_approved_unsupported_type_is_not_executed():
    agent, runner, bus = _make_runner("EvoUnsupported")
    created = agent.architecture_proposal.propose(
        "method_add", "Новый метод", "Свободный код не исполняем", cycle=1
    )
    proposal_id = created["proposal_id"]

    await runner._on_user_message(SimpleNamespace(data={"text": "одобри"}))

    assert _read_proposal(agent, proposal_id)["status"] == "approved"
    assert agent._safe_config_overrides == {}
    texts = [d.get("content", "") for d in _replies(bus)]
    assert any("не исполняю сама" in text for text in texts)


@pytest.mark.asyncio
async def test_execution_failure_never_promises_success(monkeypatch):
    agent, runner, bus = _make_runner("EvoFailure")
    proposal_id, _draft = _propose_executable(agent)
    monkeypatch.setattr(
        agent.architecture_proposal,
        "apply_approved",
        lambda proposal_id, overrides: {
            "applied": False,
            "supported": True,
            "reason": "диск недоступен",
        },
    )

    await runner._on_user_message(SimpleNamespace(data={"text": "одобри"}))

    assert _read_proposal(agent, proposal_id)["status"] == "approved"
    texts = [d.get("content", "") for d in _replies(bus)]
    assert any("диск недоступен" in text for text in texts)
    assert not any("одобрено и применено" in text for text in texts)
