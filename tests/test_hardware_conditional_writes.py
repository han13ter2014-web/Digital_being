"""11B/11C: sanitized per-life опыт условной записи и ограниченный advisor."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from config.simulation_config import SIM_CONFIG
from src.core.agent_handlers import _act_explore_impl, _act_web_search_impl
from src.core.agent_persistence import _save_knowledge_base_impl
from src.core.hardware_conditional_behavior import conditional_write_behavior_report
from src.core.hardware_interoception import HardwareInteroception


_EXTRACT = "Достаточно длинное и содержательное определение тестового понятия."


def _resources():
    return {
        "available": True,
        "host_cpu_percent": 10.0,
        "process_cpu_percent": 5.0,
        "host_memory_percent": 20.0,
        "process_rss_mb": 50.0,
        "process_rss_ratio": 0.1,
        "cycle_duration_ms": 10.0,
        "source": "test",
    }


def _storage(free_ratio):
    return {
        "available": True,
        "total_bytes": 1000,
        "free_bytes": int(1000 * free_ratio),
        "source": "test",
    }


def _confirmed_storage():
    observer = HardwareInteroception()
    for cycle in range(5):
        observer.observe(
            _resources(), cycle=cycle, storage_status=_storage(0.01), physical_status={}
        )
    return observer


def _found(target):
    return {
        "found": True,
        "extract": _EXTRACT,
        "title": target,
        "url": "https://private.invalid/query",
    }


class _ActionAgent:
    def __init__(self, tmp_path, *, managed=False):
        self.hardware_interoception = HardwareInteroception()
        self.knowledge_file = str(tmp_path / "knowledge.json")
        self.knowledge_base = {}
        self._known_definitions = {}
        self._last_kb_save_ts = 0.0
        self._last_kb_save_size = 0
        self._profile_managed = managed
        self.cycle_count = 10
        self._hunt_misses = {}
        self.mental_models = SimpleNamespace(concepts={})
        self.results = []
        self.external_explore = False
        self.web_searcher = SimpleNamespace(is_enabled=True, search=self._search)

    def _search(self, target):
        return self.results.pop(0)

    def _save_knowledge_base(self):
        return _save_knowledge_base_impl(self)

    def _prune_knowledge_base(self):
        pass

    def _record_will(self, *args):
        pass

    def _is_learnable(self, target):
        return True

    def _is_meta_topic(self, target):
        return False

    def think(self, query):
        if self.external_explore:
            self.knowledge_base["external"] = _EXTRACT
            self._known_definitions["external"] = _EXTRACT
            self._save_knowledge_base()
        return "Результат исследования без дополнительных записей"

    def web(self, target):
        try:
            return _act_web_search_impl(self, target)
        finally:
            self.cycle_count += 1

    def explore(self, target="concept"):
        try:
            return _act_explore_impl(self, target)
        finally:
            self.cycle_count += 1


def test_web_search_records_immediate_and_no_result_without_private_data(tmp_path):
    agent = _ActionAgent(tmp_path)
    agent.results = [_found("private-topic"), {"found": False, "error": "not_found"}]

    agent.web("private-topic")
    agent.web("private-topic")

    status = agent.hardware_interoception.conditional_writes.status()
    assert status["sample_count"] == 2
    assert status["profiles"]["web_search_standalone_immediate"]["write_count"] == 1
    assert status["profiles"]["web_search_no_result"]["sample_count"] == 1
    assert "private-topic" not in str(status)
    assert "private.invalid" not in str(status)
    assert _EXTRACT not in str(status)
    assert agent.hardware_interoception.storage_writes.sample_count == 1


def test_failed_immediate_write_is_not_counted_as_success(tmp_path, monkeypatch):
    import errno

    agent = _ActionAgent(tmp_path)
    agent.results = [_found("private-failure-topic")]

    def deny_replace(*args):
        raise OSError(errno.ENOSPC, "private storage path")

    monkeypatch.setattr("src.core.agent_persistence.os.replace", deny_replace)
    agent.web("private-failure-topic")

    profile = agent.hardware_interoception.conditional_writes.status()["profiles"][
        "web_search_standalone_immediate"
    ]
    assert profile["sample_count"] == 1
    assert profile["write_count"] == 0
    assert profile["failed_count"] == 1
    assert profile["latest"]["outcome"] == "failed"
    assert profile["latest"]["category"] == "no_space"
    assert "private storage path" not in str(profile)
    assert "private-failure-topic" not in str(profile)


def test_debounce_and_managed_are_not_immediate_writes(tmp_path):
    agent = _ActionAgent(tmp_path)
    agent.results = [_found("one"), _found("two"), _found("three")]

    agent.web("one")
    agent.web("two")
    agent._profile_managed = True
    agent._last_kb_save_ts = 0.0
    agent.web("three")

    profiles = agent.hardware_interoception.conditional_writes.status()["profiles"]
    assert profiles["web_search_standalone_immediate"]["sample_count"] == 1
    assert profiles["web_search_standalone_deferred"]["latest"]["outcome"] == (
        "not_written"
    )
    assert profiles["web_search_managed"]["latest"]["write_disposition"] == (
        "managed_only"
    )
    assert agent.hardware_interoception.storage_writes.sample_count == 1


def test_explore_separates_internal_no_write_from_external_conditional(tmp_path):
    agent = _ActionAgent(tmp_path)
    agent.explore()
    agent.external_explore = True
    agent.explore()

    profiles = agent.hardware_interoception.conditional_writes.status()["profiles"]
    assert profiles["explore_standalone_internal"]["latest"]["outcome"] == (
        "not_written"
    )
    assert profiles["explore_standalone_external"]["write_count"] == 1


def test_shadow_report_requires_storage_candidate_and_five_linked_samples(tmp_path):
    agent = _ActionAgent(tmp_path)
    agent.hardware_interoception = _confirmed_storage()
    candidates = [{"action": "web_search", "source": "social", "strength": 0.6}]
    before = deepcopy(candidates)

    for index in range(5):
        agent.results.append(_found(f"topic-{index}"))
        agent._last_kb_save_ts = 0.0
        agent.web(f"topic-{index}")
        report = conditional_write_behavior_report(
            candidates,
            agent.hardware_interoception,
            profile_managed=False,
            normalize_action=lambda action: action,
        )
        assert report["active"] is False
        assert report["adjustments"] == []
        assert candidates == before
        if index < 4:
            assert report["eligible"] is False
            assert report["reason"] == "insufficient_conditional_write_experience"

    assert report["mode"] == "shadow"
    assert report["eligible"] is True
    assert report["reason"] == "shadow_only"
    assert report["profile_class"] == "web_search_standalone_conditional"
    assert report["write_evidence"] == {
        "sample_count": 5,
        "write_count": 5,
        "failed_count": 0,
        "write_ratio": 1.0,
    }
    assert report["risk"] == pytest.approx(0.96)
    assert report["experienced"] == pytest.approx(0.96)
    assert report["confidence"] == pytest.approx(1.0)


def test_shadow_report_fail_closed_reasons_do_not_mutate_candidates(tmp_path):
    candidates = [{"action": "web_search", "strength": 0.6}]
    before = deepcopy(candidates)
    empty = HardwareInteroception()
    report = conditional_write_behavior_report(candidates, empty)
    assert report["reason"] == "no_storage_evidence"

    confirmed = _confirmed_storage()
    assert conditional_write_behavior_report([], confirmed)["reason"] == (
        "no_matching_candidates"
    )
    managed = conditional_write_behavior_report(
        candidates, confirmed, profile_managed=True
    )
    assert managed["reason"] == "profile_not_advisor_eligible"
    unsupported = conditional_write_behavior_report(
        candidates, confirmed, mode="unsupported"
    )
    assert unsupported["reason"] == "unsupported_mode"
    assert unsupported["eligible"] is False
    assert candidates == before


def test_conditional_write_history_is_bounded_and_not_persisted():
    observer = HardwareInteroception()
    checkpoint = deepcopy(observer.to_checkpoint())
    for cycle in range(60):
        token = observer.begin_conditional_write(
            "web_search", managed=False, cycle=cycle
        )
        observer.end_conditional_write(token)

    assert observer.conditional_writes.sample_count == 60
    assert len(observer.conditional_writes.history) == 50
    assert "conditional_writes" not in observer.to_checkpoint()
    assert observer.to_checkpoint() == checkpoint
    restored = HardwareInteroception.from_checkpoint(checkpoint)
    assert restored.conditional_writes.sample_count == 0
    assert restored.conditional_writes.status()["latest"]["outcome"] == "unknown"


def test_autonomous_tick_exposes_only_runtime_shadow_report(monkeypatch, tmp_path):
    from src.core.agent import DigitalBeing
    from src.core.checkpoint_serializer import (
        apply_state_to_agent,
        build_state_from_agent,
    )

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SIM_CONFIG, "HARDWARE_CONDITIONAL_WRITE_MODE", "shadow")
    agent = DigitalBeing(name="ConditionalWriteShadow")
    agent.web_searcher.toggle(False)
    report = agent.autonomous_tick()
    behavior = report["hardware_conditional_write_behavior"]

    assert behavior["mode"] == "shadow"
    assert behavior["active"] is False
    assert behavior["adjustments"] == []
    assert agent.hardware_conditional_write_behavior_last == behavior
    assert agent.hardware_conditional_write_behavior_last is not behavior
    state = build_state_from_agent(agent)
    assert "hardware_conditional_write_behavior_last" not in state
    assert "conditional_writes" not in state["hardware_interoception"]

    restored = DigitalBeing(name="ConditionalWriteShadow")
    apply_state_to_agent(restored, state)
    assert not hasattr(restored, "hardware_conditional_write_behavior_last")
    assert restored.hardware_interoception.conditional_writes.sample_count == 0


def _eligible_conditional_observer(tmp_path, outcomes=(True, True, True, True, True)):
    tmp_path.mkdir(parents=True, exist_ok=True)
    agent = _ActionAgent(tmp_path)
    agent.hardware_interoception = _confirmed_storage()
    for index, succeeded in enumerate(outcomes):
        topic = f"private-conditional-topic-{index}"
        agent.results.append(
            _found(topic) if succeeded else {"found": False, "error": "not_found"}
        )
        agent._last_kb_save_ts = 0.0
        agent.web(topic)
    return agent.hardware_interoception


def test_conditional_advisor_uses_write_ratio_only_for_first_proven_candidate(tmp_path):
    from src.core.hardware_conditional_behavior import apply_conditional_write_advice

    observer = _eligible_conditional_observer(
        tmp_path, outcomes=(True, False, True, False, True)
    )
    candidates = [
        {
            "action": "web_search",
            "source": "first",
            "strength": 0.8,
            "params": {"topic": "private-current-topic"},
        },
        {"action": "explore", "source": "other_action", "strength": 0.7},
        {"action": "web_search", "source": "second", "strength": 0.6},
        {"action": "communicate", "source": "social", "strength": 0.8},
    ]
    original = deepcopy(candidates)
    input_strengths = [candidate["strength"] for candidate in candidates]
    checkpoint = observer.to_checkpoint()

    shadow = conditional_write_behavior_report(
        candidates, observer, normalize_action=lambda action: action
    )
    assert shadow["active"] is False
    assert shadow["eligible"] is True
    assert shadow["factor"] == pytest.approx(1.0 - 0.25 * 0.96 * 0.6)
    assert shadow["adjustments"] == []
    assert candidates == original

    report = apply_conditional_write_advice(
        candidates,
        observer,
        lambda action: action,
        input_strengths=input_strengths,
    )

    assert report["mode"] == "advisor"
    assert report["active"] is True
    assert report["eligible"] is True
    assert report["reason"] == "applied"
    assert report["factor"] == pytest.approx(0.856)
    assert report["write_evidence"]["write_ratio"] == pytest.approx(0.6)
    assert [item["input_index"] for item in report["adjustments"]] == [0]
    assert candidates[0]["strength"] == pytest.approx(0.8 * 0.856)
    assert candidates[0]["strength"] >= 0.8 * 0.75
    assert candidates[1:] == original[1:]
    assert candidates[0]["params"] == original[0]["params"]
    assert "private-current-topic" not in str(report)
    assert observer.to_checkpoint() == checkpoint

    duplicate_candidates = deepcopy(original)
    duplicate = apply_conditional_write_advice(
        duplicate_candidates,
        observer,
        lambda action: action,
        input_strengths=input_strengths,
    )
    assert duplicate["active"] is False
    assert duplicate["eligible"] is True
    assert duplicate["reason"] == "duplicate_cycle"
    assert duplicate["adjustments"] == []
    assert duplicate_candidates == original
    assert observer.to_checkpoint() == checkpoint


def test_conditional_advisor_uses_proven_explore_external_experience(tmp_path):
    from src.core.hardware_conditional_behavior import apply_conditional_write_advice

    agent = _ActionAgent(tmp_path)
    agent.hardware_interoception = _confirmed_storage()
    agent.external_explore = True
    for index in range(5):
        agent._last_kb_save_ts = 0.0
        agent.explore(f"private-explore-topic-{index}")
    candidates = [{"action": "explore", "source": "motivation", "strength": 0.8}]

    report = apply_conditional_write_advice(
        candidates, agent.hardware_interoception, lambda action: action
    )

    assert report["active"] is True
    assert report["profile_class"] == "explore_standalone_conditional"
    assert report["write_evidence"] == {
        "sample_count": 5,
        "write_count": 5,
        "failed_count": 0,
        "write_ratio": 1.0,
    }
    assert report["factor"] == pytest.approx(0.76)
    assert candidates[0]["strength"] == pytest.approx(0.8 * 0.76)
    assert "private-explore-topic" not in str(report)


def test_conditional_advisor_shares_one_budget_with_own_load_and_physical(tmp_path):
    from src.core.hardware_conditional_behavior import apply_conditional_write_advice

    observer = _eligible_conditional_observer(tmp_path)
    candidates = [{"action": "web_search", "source": "probe", "strength": 0.8 * 0.77}]
    report = apply_conditional_write_advice(
        candidates, observer, lambda action: action, input_strengths=[0.8]
    )

    assert report["active"] is True
    assert report["factor"] == pytest.approx(0.76)
    assert candidates[0]["strength"] == pytest.approx(0.8 * 0.76)
    assert candidates[0]["strength"] > 0.8 * 0.77 * 0.76
    assert candidates[0]["strength"] >= 0.8 * 0.75

    already_limited = _eligible_conditional_observer(tmp_path / "limited")
    candidates = [{"action": "web_search", "source": "probe", "strength": 0.6}]
    report = apply_conditional_write_advice(
        candidates,
        already_limited,
        lambda action: action,
        input_strengths=[0.8],
    )
    assert report["active"] is False
    assert report["reason"] == "shared_budget_already_applied"
    assert report["adjustments"] == []
    assert candidates[0]["strength"] == 0.6


def test_conditional_advisor_fail_closed_for_strength_profile_and_normalization(
    tmp_path,
):
    from src.core.hardware_conditional_behavior import apply_conditional_write_advice

    observer = _eligible_conditional_observer(tmp_path)
    for invalid in (True, 0.0, -0.2):
        candidate = {"action": "web_search", "strength": invalid}
        report = apply_conditional_write_advice(
            [candidate],
            observer,
            lambda action: action,
            input_strengths=[0.8],
        )
        assert report["active"] is False
        assert report["reason"] == "invalid_strength"
        assert report["adjustments"] == []
        assert candidate["strength"] == invalid

    candidate = {"action": "web_search", "strength": 0.8}
    invalid_original = float("nan")
    report = apply_conditional_write_advice(
        [candidate],
        observer,
        lambda action: action,
        input_strengths=[invalid_original],
    )
    assert report["active"] is False
    assert report["reason"] == "invalid_strength"
    assert candidate["strength"] == 0.8

    managed = apply_conditional_write_advice(
        [candidate], observer, lambda action: action, profile_managed=True
    )
    assert managed["active"] is False
    assert managed["reason"] == "profile_not_advisor_eligible"
    assert candidate["strength"] == 0.8

    def deny_normalization(action):
        raise ValueError("private normalization failure")

    failed = apply_conditional_write_advice([candidate], observer, deny_normalization)
    assert failed["active"] is False
    assert failed["reason"] == "no_matching_candidates"
    assert failed["adjustments"] == []
    assert candidate["strength"] == 0.8

    no_writes = _eligible_conditional_observer(
        tmp_path / "no-writes", outcomes=(False, False, False, False, False)
    )
    insufficient = apply_conditional_write_advice(
        [candidate], no_writes, lambda action: action
    )
    assert insufficient["active"] is False
    assert insufficient["reason"] == "insufficient_conditional_write_experience"
    assert candidate["strength"] == 0.8


def test_conditional_advisor_blocks_second_hormonal_adjustment(monkeypatch, tmp_path):
    from src.core.agent import DigitalBeing
    from src.cognition import method_feedback

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "tick"))
    monkeypatch.setattr(SIM_CONFIG, "HARDWARE_BEHAVIOR_MODE", "shadow")
    monkeypatch.setattr(SIM_CONFIG, "HARDWARE_CONDITIONAL_WRITE_MODE", "advisor")
    monkeypatch.setattr(SIM_CONFIG, "HORMONAL_BEHAVIOR_MODE", "advisor")
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: _resources(),
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage(0.01)
    )

    original_prepare = method_feedback.prepare_candidates

    def prepare(agent, candidates):
        prepared, feedback = original_prepare(agent, candidates)
        prepared.append(
            {
                "action": "web_search",
                "source": "conditional_advisor_probe",
                "strength": 0.08,
                "params": {"probe": True},
            }
        )
        return prepared, feedback

    monkeypatch.setattr(method_feedback, "prepare_candidates", prepare)
    agent = DigitalBeing(name="ConditionalWriteAdvisor")
    agent.web_searcher.toggle(False)
    agent.hardware_interoception = _eligible_conditional_observer(
        tmp_path / "experience"
    )
    agent.cycle_count = 5
    for name in ("dopamine", "oxytocin", "cortisol"):
        agent.hormonal_system.hormones[name] = 1.0
        agent.hormonal_system.profile.values[name]["sample_count"] = 20

    report = agent.autonomous_tick()

    conditional = report["hardware_conditional_write_behavior"]
    assert conditional["active"] is True
    assert conditional["reason"] == "applied"
    assert [item["action"] for item in conditional["adjustments"]] == ["web_search"]
    assert report["hormonal_behavior"]["mode"] == "advisor"
    assert all(
        item["action"] != "web_search"
        for item in report["hormonal_behavior"]["adjustments"]
    )
    assert agent.hardware_conditional_write_behavior_last == conditional
    assert agent.hardware_conditional_write_behavior_last is not conditional
