"""Тесты «Эволюция-1»: живой тик глаз → рука → проба → голос.

Проба (subprocess) в этих тестах подменена: скорость тут не важна,
а изолированный запуск честно проверен в test_proposal_verifier.py.
Здесь проверяются пороги, кулдаун и голос.
"""

from src.core.agent import DigitalBeing

import os

import pytest

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


def _make_agent(name="EvoTick"):
    agent = DigitalBeing(name=name)
    # Даём сигнал «энергия тратится неэффективно»: много циклов без
    # целей и концепций.
    agent.cycle_count = 100000
    agent.energy = 100
    return agent


def _pending(agent):
    return agent.architecture_proposal.list_pending()


def _fake_verify_ok(attr, value, cycles=5, timeout=120):
    return {"ran": True, "passed": True, "cycles": cycles, "log_tail": "ok"}


def _tick(agent, cycle, monkeypatch):
    monkeypatch.setattr(
        "src.evolution.proposal_verifier.verify_config_change",
        _fake_verify_ok,
    )
    return agent._evolution_tick(cycle)


def test_tick_outside_interval_is_silent():
    agent = _make_agent()
    assert agent._evolution_tick(151) is None
    assert agent._evolution_tick(0) is None


def test_signal_ripens_into_proposal(monkeypatch):
    agent = _make_agent()
    _tick(agent, 150, monkeypatch)
    _tick(agent, 300, monkeypatch)
    assert _pending(agent) == []
    result = _tick(agent, 450, monkeypatch)
    pending = _pending(agent)
    assert len(pending) == 1
    assert result["ripe_signal"] == "energy_efficiency"
    assert result["proposal_id"] == pending[0]["id"]
    assert pending[0]["verification"]["passed"] is True
    assert pending[0]["category"] == "energy_efficiency"
    assert "REST_FATIGUE_THRESHOLD" in pending[0]["diff"]
    # diff честный: старое значение — живое из конфига
    from config.simulation_config import LR_CONFIG

    expected = f"-    REST_FATIGUE_THRESHOLD = {LR_CONFIG.REST_FATIGUE_THRESHOLD!r}"
    assert expected in pending[0]["diff"]


def test_voice_message_sent_on_proposal(monkeypatch):
    agent = _make_agent("EvoVoice")
    for i in (1, 2, 3):
        _tick(agent, 150 * i, monkeypatch)
    messages = [
        m
        for m in agent.user_interaction.message_history
        if (m.get("context") or "").startswith("evolution_proposal:")
    ]
    assert len(messages) == 1
    assert "одобри" in messages[0]["content"]
    assert "отклони" in messages[0]["content"]


def test_pending_blocks_new_proposal(monkeypatch):
    agent = _make_agent("EvoPend")
    for i in (1, 2, 3):
        _tick(agent, 150 * i, monkeypatch)
    assert len(_pending(agent)) == 1
    # Стрик собирается заново; на третьем анализе — ripe, но ожидающее
    # предложение уже есть: человек не должен тонуть в письмах.
    _tick(agent, 600, monkeypatch)
    _tick(agent, 750, monkeypatch)
    result = _tick(agent, 900, monkeypatch)
    assert result.get("skipped") == "есть ожидающее предложение"
    assert len(_pending(agent)) == 1


def test_cooldown_blocks_immediate_reproposal(monkeypatch):
    agent = _make_agent("EvoCool")
    for i in (1, 2, 3):
        _tick(agent, 150 * i, monkeypatch)
    proposal = _pending(agent)[0]
    agent.architecture_proposal.decide(proposal["id"], approved=False)
    assert _pending(agent) == []
    # Новый стрик: 600, 750, 900. На 900 сигнал дозрел, но кулдаун
    # (500 циклов от предложения на 450) ещё держит.
    _tick(agent, 600, monkeypatch)
    _tick(agent, 750, monkeypatch)
    result = _tick(agent, 900, monkeypatch)
    assert result.get("skipped") == "кулдаун"
    assert _pending(agent) == []


def test_failed_verification_still_proposes_honestly(monkeypatch):
    agent = _make_agent("EvoFail")
    monkeypatch.setattr(
        "src.evolution.proposal_verifier.verify_config_change",
        lambda *a, **k: {"ran": True, "passed": False, "cycles": 1, "log_tail": "boom"},
    )
    for i in (1, 2, 3):
        agent._evolution_tick(150 * i)
    pending = _pending(agent)
    assert len(pending) == 1
    assert pending[0]["verification"]["passed"] is False
    messages = [
        m
        for m in agent.user_interaction.message_history
        if (m.get("context") or "").startswith("evolution_proposal:")
    ]
    assert "НЕ пройдена" in messages[0]["content"]
