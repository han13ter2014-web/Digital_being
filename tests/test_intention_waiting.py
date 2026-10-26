"""Вытеснение записи журнала не является новой возможностью исследовать."""

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.intention_history import begin_intention, finish_intention, LIMIT
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_continuation import continuation_candidate
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_wait_survives_eviction_and_profile_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        agent, _ = create_agent(env, "WaitLife", new=True)
        entry = begin_intention(agent, {"action": "explore", "params": {"topic": "память"}})
        finish_intention(entry)
        finish_evidence_goal(agent, entry)
        agent.cycle_count += 1
        retry = begin_intention(agent, continuation_candidate(agent))
        finish_intention(retry)
        finish_evidence_goal(agent, retry)
        for _ in range(LIMIT + 1):
            rest = begin_intention(agent, {"action": "rest"})
            finish_intention(rest)
        agent.cycle_count += 1
        assert retry["id"] not in {e["id"] for e in agent._intention_history}
        assert continuation_candidate(agent) is None
        agent.save_state(force=True)
        PluginRegistry.reset_global()
        restored, _ = create_agent(env, "WaitLife")
        assert continuation_candidate(restored) is None
        restored.knowledge_base["новый материал"] = "Содержательное объяснение"
        proposal = continuation_candidate(restored)
        assert proposal["params"]["topic"] == "память"
        restored.mental_models.encounter_concept("память", "ответ", "Память сохраняет и использует опыт",
            evidence_strength=0.8, evidence_kind="testimony", source="user:new")
        assert continuation_candidate(restored) is None
        assert all(e["evidence_goal"]["status"] == "satisfied" for e in restored._waiting_intentions.values())
    finally:
        PluginRegistry.reset_global()
