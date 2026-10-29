"""Terminal Effector result closes only its explicitly linked Core intention."""

from types import SimpleNamespace
from unittest.mock import Mock

from src.cognition.intention_history import begin_intention
from src.core.agent import DigitalBeing


def _agent_with_memory():
    agent = DigitalBeing(name="IntentionBridge")
    memory = Mock()
    agent.delamain = SimpleNamespace(runtime=SimpleNamespace(memory=memory))
    return agent, memory


def _result(status="succeeded", *, intention_id="", ok=True, error=None):
    return {"status": status, "request_id": "req-1", "ok": ok, "error": error,
            "detail": {"activity": "creative", "metadata": {
                "intention_id": intention_id, "target": "память", "core_cycle": 4}}}


def test_terminal_success_finishes_linked_intention_and_records_once():
    agent, memory = _agent_with_memory()
    entry = begin_intention(agent, {"action": "create_draft", "source": "activity",
                                    "params": {"topic": "память", "reason": "интерес"}})

    agent._on_effector_result(_result(intention_id=entry["id"]))

    assert entry["status"] == "performed"
    assert entry["outcome"]["result_status"] == "succeeded"
    assert memory.record_life_episode.call_count == 1
    kwargs = memory.record_life_episode.call_args.kwargs
    assert kwargs["intention_id"] == entry["id"]
    assert kwargs["status"] == "performed"

    # Повтор одного terminal результата не создаёт второй эпизод.
    agent._on_effector_result(_result(intention_id=entry["id"]))
    assert memory.record_life_episode.call_count == 1


def test_failure_finishes_linked_intention_as_error():
    agent, memory = _agent_with_memory()
    entry = begin_intention(agent, {"action": "create_draft", "params": {"topic": "x"}})

    agent._on_effector_result(_result("failed", intention_id=entry["id"], ok=False,
                                      error="sandbox stopped"))

    assert entry["status"] == "error"
    assert "sandbox stopped" in entry["outcome"]["error"]
    assert memory.record_life_episode.call_count == 1
    assert memory.record_life_episode.call_args.kwargs["status"] == "error"


def test_rejection_finishes_linked_intention_as_denied():
    agent, memory = _agent_with_memory()
    entry = begin_intention(agent, {"action": "create_draft", "params": {"topic": "x"}})

    agent._on_effector_result(_result("rejected", intention_id=entry["id"], ok=False,
                                      error="не сейчас"))

    assert entry["status"] == "denied"
    assert entry["outcome"]["result_status"] == "rejected"
    assert memory.record_life_episode.call_args.kwargs["status"] == "denied"


def test_unlinked_terminal_result_does_not_create_life_episode():
    agent, memory = _agent_with_memory()
    agent._on_effector_result(_result())

    assert memory.record_life_episode.call_count == 0
    assert not getattr(agent, "_intention_history", [])


def test_queued_result_does_not_close_intention():
    agent, memory = _agent_with_memory()
    entry = begin_intention(agent, {"action": "create_draft", "params": {"topic": "x"}})

    agent._on_effector_result(_result("waiting_approval", intention_id=entry["id"], ok=False))

    assert entry["status"] == "started"
    assert memory.record_life_episode.call_count == 0
