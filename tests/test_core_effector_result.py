"""Core interprets driver result; Delamain remains technical."""

from types import SimpleNamespace

from src.core.agent import DigitalBeing
from src.core.core_effector_result import interpret_result
from src.core.effector_port import EffectorResult, EffectorStatus


def test_core_result_interpretation_preserves_intention_metadata():
    result = EffectorResult("req", EffectorStatus.SUCCEEDED, ok=True,
                            detail={"activity": "creative", "metadata": {
                                "intention_id": "intent-1", "target": "draft", "core_cycle": 4}})
    payload = interpret_result(result)
    assert payload["intention_id"] == "intent-1"
    assert payload["target"] == "draft"
    assert payload["terminal"]


def test_agent_updates_only_terminal_driver_result():
    agent = DigitalBeing(name="CoreResultTest")
    agent._on_effector_result({"result": {"status": "queued", "ok": False,
                                           "detail": {"activity": "creative"}}})
    assert not getattr(agent, "_method_preferences", {})
    agent._on_effector_result({"result": {"status": "succeeded", "ok": True,
                                           "detail": {"activity": "creative",
                                                      "metadata": {"intention_id": "i"}}}})
    assert agent._last_effector_activity_result["status"] == "succeeded"
    assert agent._method_preferences["create_draft"]["effects"] == 1
