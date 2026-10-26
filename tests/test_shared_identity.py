"""Рассмотрение вариантов не создаёт вторую личность или новое переживание."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.agent import DigitalBeing
from src.core.subsystem_base import PluginRegistry


def test_arbitrator_shares_identity_and_only_reads_it():
    agent = DigitalBeing(name="SharedIdentity")
    identity = agent.soul.get("self")
    assert identity is not None
    assert agent.decision_arbitrator._systems["self"] is identity
    before = deepcopy(identity.to_dict())
    with patch.object(identity, "synthesize", side_effect=AssertionError("candidate is not lived experience")) as synthesize:
        agent.decision_arbitrator.choose_action([
            {"source": "test", "action": "rest", "strength": 0.5},
            {"source": "test", "action": "explore", "strength": 0.6},
        ], {})
    synthesize.assert_not_called()
    assert identity.to_dict() == before


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_identity_survives_normal_startup(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "IdentityLife", new=True)
        identity = first.soul.get("self")
        identity.core_identity = "Моё сохранённое самоописание"
        identity.core_values = []
        identity.identity_stability_score = 0.0
        identity.history = ["значимый пересмотр"]
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, _ = create_agent(env, "IdentityLife")
        restored = second.soul.get("self")
        assert restored.to_dict() == identity.to_dict()
        assert second.decision_arbitrator._systems["self"] is restored
    finally:
        PluginRegistry.reset_global()
