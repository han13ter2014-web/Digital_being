"""Read-only снимок жизни: не меняет Core и не выдумывает данные."""

from copy import deepcopy
from types import SimpleNamespace

from src.cognition.intention_history import begin_intention, finish_intention
from src.core.agent import DigitalBeing
from src.ui.life_snapshot import build_life_snapshot, recent_life_episodes


def _agent(name="Snapshot"):
    return DigitalBeing(name=name)


def test_snapshot_does_not_create_lazy_core_fields():
    agent = _agent("NoLazy")
    assert "_intention_history" not in agent.__dict__
    assert "_waiting_intentions" not in agent.__dict__
    assert "_method_preferences" not in agent.__dict__

    build_life_snapshot(agent)

    assert "_intention_history" not in agent.__dict__
    assert "_waiting_intentions" not in agent.__dict__
    assert "_method_preferences" not in agent.__dict__


def test_snapshot_does_not_mutate_agent():
    agent = _agent("Stable")
    entry = begin_intention(agent, {"action": "play", "source": "activity",
                                    "params": {"topic": "партия", "reason": "интерес"}})
    keys_before = set(agent.__dict__)
    cycle_before = agent.cycle_count
    energy_before = agent.energy
    history_before = deepcopy(agent._intention_history)

    first = build_life_snapshot(agent)
    second = build_life_snapshot(agent)

    assert first == second
    assert set(agent.__dict__) == keys_before
    assert agent.cycle_count == cycle_before
    assert agent.energy == energy_before
    assert agent._intention_history == history_before
    assert first["now"]["activity"]["id"] == entry["id"]


def test_snapshot_returns_deep_copies_of_core_data():
    agent = _agent("Copies")
    entry = begin_intention(agent, {"action": "play", "params": {"topic": "игра"}})

    snapshot = build_life_snapshot(agent)
    snapshot["intentions"]["recent"][0]["status"] = "tampered"
    snapshot["now"]["activity"]["target"] = "tampered"

    assert agent._intention_history[0]["status"] == "started"
    assert agent._intention_history[0]["target"] == entry["target"]


def test_snapshot_shows_queued_effector_separately_from_succeeded():
    counts = {"queued": 2, "waiting_approval": 1, "succeeded": 3,
              "failed": 1, "rejected": 0}
    agent = _agent("Effector")
    agent.delamain_effector = SimpleNamespace(enabled=True, status=lambda: {"counts": counts})

    snapshot = build_life_snapshot(agent)

    assert snapshot["effector"]["available"] is True
    assert snapshot["effector"]["counts"]["queued"] == 2
    assert snapshot["effector"]["counts"]["succeeded"] == 3
    assert snapshot["access"]["effector"]["enabled"] is True


def test_snapshot_without_effector_is_honest_about_absence():
    agent = _agent("NoEffector")
    agent.delamain_effector = None
    snapshot = build_life_snapshot(agent)
    assert snapshot["effector"]["available"] is False
    assert snapshot["effector"]["counts"] == {}


def test_broken_subsystem_does_not_break_snapshot():
    agent = _agent("Broken")

    def explode():
        raise RuntimeError("подсистема недоступна")

    agent.motivation_system = SimpleNamespace(get_status=explode)
    snapshot = build_life_snapshot(agent)
    assert snapshot["motivation"] == {}
    assert snapshot["name"] == "Broken"


def test_waiting_intentions_are_listed_only_while_unresolved():
    agent = _agent("Waiting")
    entry = begin_intention(agent, {"action": "explore", "source": "activity",
                                   "params": {"topic": "память", "reason": "нет источников"}})
    entry["evidence_goal"] = {"kind": "new_topic_evidence", "status": "pending",
                              "baseline_sources": [], "new_sources": []}
    entry["continuation_of"] = "previous"
    finish_intention(entry, outcome=None)
    from src.cognition.intention_waiting import remember_wait

    remember_wait(agent, entry)
    assert len(build_life_snapshot(agent)["intentions"]["waiting"]) == 1

    agent._waiting_intentions[next(iter(agent._waiting_intentions))]["resolution"] = {
        "kind": "forgotten", "reason": "источников нет", "cycle": agent.cycle_count}
    snapshot = build_life_snapshot(agent)
    assert snapshot["intentions"]["waiting"] == []
    # Забытое не исчезает: оно уходит в отдельный список для карты.
    assert [row["id"] for row in snapshot["intentions"]["forgotten"]] == [entry["id"]]


def test_life_episodes_are_empty_without_delamain():
    agent = _agent("NoDelamain")
    assert recent_life_episodes(agent) == []


def test_activity_catalog_matches_core_not_filesystem():
    agent = _agent("Catalog")
    snapshot = build_life_snapshot(agent)
    assert snapshot["activities"]["creative"]["count"] == 0
    assert snapshot["activities"]["creative"]["drafts"] == []
    assert snapshot["activities"]["game"] is None
    assert snapshot["diary"]["episodes"] == []


def test_diary_snapshot_reads_episodes_without_mutating_core():
    agent = _agent("DiaryCopies")
    rows = [{"id": 1, "action": "play", "args": {"target": "партия"},
             "metadata": {"status": "performed"}}]
    agent.delamain = SimpleNamespace(runtime=SimpleNamespace(
        memory=SimpleNamespace(recent_life_episodes=lambda **kwargs: rows)
    ))
    before = set(agent.__dict__)
    snapshot = build_life_snapshot(agent)
    snapshot["diary"]["episodes"][0]["args"]["target"] = "изменено"
    assert rows[0]["args"]["target"] == "партия"
    assert set(agent.__dict__) == before
