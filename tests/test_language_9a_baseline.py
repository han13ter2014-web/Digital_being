"""9A-0: автономные языковые каталоги и воспроизводимый baseline.

Русские сценарии проверяют текущее поведение без изменения production-кода.
Английские expected-поля — заранее зафиксированные цели будущих этапов:
здесь выполняются только current probes, их результаты не становятся эталоном.
Сеть, адаптеры внешних провайдеров и живой data/ не используются.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_CLI_DATA_DIR = None
if __name__ == "__main__":
    _CLI_DATA_DIR = tempfile.mkdtemp(prefix="db_language_9a_0_")
    os.environ["DIGITAL_BEING_DATA_DIR"] = _CLI_DATA_DIR

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.dialogue_acts import classify_user_text
from src.core.event_bus import Events

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "language_9a"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
CATALOGS = {
    entry["split"]: json.loads((FIXTURE_DIR / entry["path"]).read_text(encoding="utf-8"))
    for entry in MANIFEST["files"]
}
RUSSIAN_SCENARIOS = CATALOGS["russian_baseline"]["scenarios"]
ENGLISH_SCENARIOS = (
    CATALOGS["english_practice"]["scenarios"]
    + CATALOGS["english_heldout"]["scenarios"]
)
CAPABILITIES = tuple(MANIFEST["capabilities"])
CHECKPOINT_SECTIONS = (
    "user_interaction",
    "dialogue_learning",
    "response_experience",
    "social_registry",
    "social_attribution",
)
REQUIRED_SCENARIO_FIELDS = {
    "scenario_id",
    "revision",
    "split",
    "tags",
    "driver",
    "profile_setup",
    "state_setup",
    "input",
    "expected",
    "checkpoint_setup",
    "restart_point",
}
REQUIRED_EXPECTED_FIELDS = {
    "input_language",
    "dialogue_language",
    "response_language",
    "language_source",
    "act",
    "topic_policy",
    "reference_policy",
    "fallback_policy",
    "reply_context",
    "required_text",
    "forbidden_text",
    "pending_after",
    "explicit_switch",
    "profile_isolation",
    "permission_effect",
    "outcome",
}
DRIVERS = {
    "agent_runner",
    "response_experience",
    "social_attribution",
    "external_planner",
    "current_probe",
    "external_current_probe",
    "not_current_executable",
}
DYNAMIC_ID_RE = re.compile(
    r"(?<![0-9a-f])(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})(?![0-9a-f])",
    re.IGNORECASE,
)
SECRET_RE = re.compile(
    r"(?:rufp_[A-Za-z0-9_-]{12,}|api[_ -]?key\s*[:=]\s*[^\s]+|"
    r"bearer\s+[A-Za-z0-9._-]{12,})",
    re.IGNORECASE,
)
_NETWORK_CALLS = []


class RecordingBus:
    """Минимальная автономная шина для фактических ответов диалога."""

    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _blocked_network(*args, **kwargs):
    _NETWORK_CALLS.append({"args": repr(args), "kwargs": repr(kwargs)})
    raise AssertionError("9A-0 не должен обращаться к сети")


def _normalized_text(text):
    return " ".join(str(text or "").casefold().split())


def _input_texts(scenario):
    if "text" in scenario["input"]:
        return [scenario["input"]["text"]]
    return [turn["text"] for turn in scenario["input"]["turns"]]


def test_manifest_schema_hashes_and_unique_ids():
    assert MANIFEST["schema_version"] == 1
    assert MANIFEST["catalog_revision"] == "9a0-r1"
    assert len(MANIFEST["files"]) == 3
    assert set(CATALOGS) == {
        "russian_baseline",
        "english_practice",
        "english_heldout",
    }
    identifiers = []
    for entry in MANIFEST["files"]:
        path = FIXTURE_DIR / entry["path"]
        assert path.name == entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        catalog = CATALOGS[entry["split"]]
        assert catalog["schema_version"] == MANIFEST["schema_version"]
        assert catalog["catalog_revision"] == MANIFEST["catalog_revision"]
        assert catalog["split"] == entry["split"]
        assert catalog["scenarios"]
        for scenario in catalog["scenarios"]:
            assert REQUIRED_SCENARIO_FIELDS <= set(scenario)
            assert REQUIRED_EXPECTED_FIELDS <= set(scenario["expected"])
            assert scenario["revision"] == catalog["catalog_revision"]
            assert scenario["split"] == catalog["split"]
            assert scenario["driver"] in DRIVERS
            assert isinstance(scenario["tags"], list) and scenario["tags"]
            assert isinstance(scenario["profile_setup"], dict)
            assert isinstance(scenario["state_setup"], dict)
            assert isinstance(scenario["checkpoint_setup"], dict)
            assert isinstance(scenario["expected"]["required_text"], list)
            assert isinstance(scenario["expected"]["forbidden_text"], list)
            assert isinstance(scenario["expected"]["pending_after"], bool)
            assert bool(scenario["input"].get("text")) != bool(
                scenario["input"].get("turns")
            )
            assert all(_normalized_text(text) for text in _input_texts(scenario))
            identifiers.append(scenario["scenario_id"])
    assert len(identifiers) == len(set(identifiers)) == 70


def test_english_splits_cover_capabilities_without_text_overlap():
    practice = CATALOGS["english_practice"]["scenarios"]
    heldout = CATALOGS["english_heldout"]["scenarios"]
    for split, scenarios in (
        ("english_practice", practice),
        ("english_heldout", heldout),
    ):
        counts = Counter()
        for scenario in scenarios:
            assert len(scenario["tags"]) == 1
            assert scenario["tags"][0] in CAPABILITIES
            counts[scenario["tags"][0]] += 1
        assert counts == Counter({capability: 2 for capability in CAPABILITIES})
    practice_texts = {
        _normalized_text(text) for scenario in practice for text in _input_texts(scenario)
    }
    heldout_texts = {
        _normalized_text(text) for scenario in heldout for text in _input_texts(scenario)
    }
    assert practice_texts.isdisjoint(heldout_texts)


def test_catalogs_contain_no_secret_like_values():
    serialized = "\n".join(
        json.dumps(catalog, ensure_ascii=False) for catalog in CATALOGS.values()
    )
    assert SECRET_RE.search(serialized) is None


def test_english_expectations_are_not_russian_baseline_targets():
    assert all(scenario["split"] == "russian_baseline" for scenario in RUSSIAN_SCENARIOS)
    assert not any(scenario in RUSSIAN_SCENARIOS for scenario in ENGLISH_SCENARIOS)
    assert all(
        scenario["driver"] in {
            "current_probe",
            "external_current_probe",
            "not_current_executable",
        }
        for scenario in ENGLISH_SCENARIOS
    )


def _make_runner(agent):
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return runner, bus


def _seed_previous_act(agent, descriptor):
    if not descriptor:
        return
    agent.user_interaction.record_dialogue_act(
        descriptor["kind"],
        topic=descriptor.get("topic", ""),
        entities=descriptor.get("entities", ()),
        cycle=descriptor.get("cycle", agent.cycle_count),
        user_text="",
        agent_text=descriptor["agent_text"],
    )


def _new_runtime(scenario):
    setup = scenario["state_setup"]
    agent = DigitalBeing(name=setup["agent_name"])
    agent.cycle_count = setup["cycle"]
    for topic, body in setup.get("known_topics", {}).items():
        agent.record_user_answer(topic, f"{topic} — это {body}", cycle=agent.cycle_count)
    pending = setup.get("pending_question")
    if pending:
        asked = agent.user_interaction.ask_user(
            pending["question"], context=pending["context"], cycle=agent.cycle_count
        )
        assert asked["status"] != "failed"
    _seed_previous_act(agent, setup.get("previous_act"))
    if scenario["checkpoint_setup"]["kind"] == "legacy_without_social_attribution":
        legacy = build_state_from_agent(agent)
        legacy.pop("social_attribution", None)
        restored = DigitalBeing(name=setup["agent_name"])
        apply_state_to_agent(restored, legacy)
        agent = restored
    runner, bus = _make_runner(agent)
    return agent, runner, bus


def _message_events(bus):
    return [dict(data or {}) for name, data in bus.published if name == Events.AGENT_MESSAGE]


def _plan_summary(record):
    if not record:
        return {
            "context": None,
            "references": [],
            "provenance_verified": True,
            "has_plan": False,
        }
    plan = record["plan"]
    return {
        "context": plan["context"],
        "references": deepcopy(plan["references"]),
        "provenance_verified": plan["provenance_verified"] is True,
        "has_plan": True,
    }


async def _runner_turn(agent, runner, bus, text):
    before = len(_message_events(bus))
    act = classify_user_text(
        text,
        learned=runner._learned_markers(),
        learned_affect=runner._learned_affect(),
        cycle=agent.cycle_count,
    ).kind
    await runner._on_user_message(SimpleNamespace(data={"text": text}))
    messages = _message_events(bus)[before:]
    text_out = messages[-1].get("content", "") if messages else None
    context = None
    if messages:
        agent_messages = [
            item
            for item in agent.user_interaction.message_history
            if item.get("sender") == "agent"
        ]
        if agent_messages:
            context = agent_messages[-1].get("context")
    if context == "follow_up":
        act = "follow_up"
    response_id = agent.response_experience.latest_response_id if messages else None
    plan = _plan_summary(agent.response_experience.responses.get(response_id))
    return {
        "input": text,
        "act": act,
        "reply_context": context,
        "text": text_out,
        "pending_after": agent.user_interaction.get_pending_question() is not None,
        "plan": plan,
    }


def _normalize_dynamic(value, identifiers=None):
    identifiers = {} if identifiers is None else identifiers
    if isinstance(value, dict):
        return {
            _normalize_dynamic(key, identifiers): _normalize_dynamic(item, identifiers)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_dynamic(item, identifiers) for item in value]
    if isinstance(value, tuple):
        return [_normalize_dynamic(item, identifiers) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match):
        raw = match.group(0)
        key = raw.casefold().replace("-", "")
        if key not in identifiers:
            identifiers[key] = f"<dynamic-{len(identifiers) + 1}>"
        return identifiers[key]

    return DYNAMIC_ID_RE.sub(replace, value)


def _checkpoint_snapshot(agent):
    state = build_state_from_agent(agent)
    selected = {key: state.get(key) for key in CHECKPOINT_SECTIONS}
    normalized = _normalize_dynamic(selected)
    digest = hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return normalized, digest


def _empty_result(scenario):
    return {
        "scenario_id": scenario["scenario_id"],
        "split": scenario["split"],
        "driver": scenario["driver"],
        "act": None,
        "reply_context": None,
        "text": None,
        "turns": [],
        "pending_after": False,
        "outcome": None,
        "references": [],
        "plan_count": 0,
        "all_plans_verified": True,
        "empty_reference_plans": 0,
        "profile_isolation_ok": True,
        "active_goal_unchanged": True,
        "semantic_key": None,
        "checkpoint": None,
        "checkpoint_sha256": None,
    }


def _finish_result(agent, result):
    result["turns"] = result.pop("turn_records", [])
    if result["turns"]:
        final = result["turns"][-1]
        result["act"] = final["act"]
        result["reply_context"] = final["reply_context"]
        result["text"] = final["text"]
        result["pending_after"] = final["pending_after"]
    for turn in result["turns"]:
        plan = turn.pop("plan")
        if plan["has_plan"]:
            result["plan_count"] += 1
            result["all_plans_verified"] &= plan["provenance_verified"]
            result["empty_reference_plans"] += not bool(plan["references"])
            result["references"].extend(plan["references"])
    checkpoint, digest = _checkpoint_snapshot(agent)
    result["checkpoint"] = checkpoint
    result["checkpoint_sha256"] = digest
    return result


async def _run_agent_scenario(scenario):
    agent, runner, bus = _new_runtime(scenario)
    result = _empty_result(scenario)
    result["turn_records"] = []
    inputs = scenario["input"].get("turns") or [
        {"text": scenario["input"]["text"]}
    ]
    for index, turn in enumerate(inputs):
        if scenario["restart_point"] == "after_first_turn" and index == 1:
            checkpoint = build_state_from_agent(agent)
            agent = DigitalBeing(name=scenario["state_setup"]["agent_name"])
            apply_state_to_agent(agent, checkpoint)
            runner, bus = _make_runner(agent)
        result["turn_records"].append(
            await _runner_turn(agent, runner, bus, turn["text"])
        )
    return _finish_result(agent, result)


async def _run_response_experience(scenario):
    agent, runner, _bus = _new_runtime(scenario)
    result = _empty_result(scenario)
    message_id = await runner._reply_to_user(
        "Привет. Рада тебя слышать.",
        context="social_reply",
        source="language_9a_fixture",
        user_text="Привет!",
    )
    observed = agent.response_experience.observe_feedback(
        message_id, "support", agent.cycle_count
    )
    result["act"] = "social"
    result["reply_context"] = "social_reply"
    result["text"] = agent.user_interaction.message_history[-1]["content"]
    result["pending_after"] = agent.user_interaction.get_pending_question() is not None
    result["outcome"] = observed["outcome"]
    plan = _plan_summary(agent.response_experience.responses[message_id])
    result["references"] = plan["references"]
    result["plan_count"] = 1
    result["all_plans_verified"] = plan["provenance_verified"]
    result["empty_reference_plans"] = not bool(plan["references"])
    result["turn_records"] = []
    return _finish_result(agent, result)


async def _run_social_attribution(scenario):
    agent, _, _ = _new_runtime(scenario)
    result = _empty_result(scenario)
    owner = agent.social_registry.owner_profile_id
    marker = scenario["input"]["text"]
    agent.dialogue_learning.learned[marker] = {"act": "social", "cycle": 1}
    guest = agent.social_registry.create_local_person("Guest9A", cycle=2)
    assert agent.social_attribution.sync_active_profile() is True
    assert agent.dialogue_learning.learned == {}
    agent.dialogue_learning.learned["гостевой маркер"] = {"act": "social", "cycle": 2}
    agent.social_registry.switch_to(owner, cycle=3)
    assert agent.social_attribution.sync_active_profile() is True
    result["profile_isolation_ok"] = (
        set(agent.dialogue_learning.learned) == {marker}
        and "гостевой маркер"
        in agent.social_attribution.states[guest]["dialogue_learning"]["learned"]
    )
    result["act"] = classify_user_text(marker).kind
    result["pending_after"] = agent.user_interaction.get_pending_question() is not None
    result["turn_records"] = []
    return _finish_result(agent, result)


async def _run_external_planner(scenario):
    agent, _, _ = _new_runtime(scenario)
    setup = scenario["state_setup"]["external_session"]
    owner = agent.social_registry.owner_profile_id
    before_goal = deepcopy(agent.active_goal)
    started = agent.external_contacts.start_session(
        agent.social_registry,
        provider="offline-fixture",
        name="Offline external",
        external_id="offline-external",
        topic=setup["topic"],
        reason="9A-0 offline baseline",
        cycle=agent.cycle_count,
        model="offline/none",
    )
    session_id = started["session_id"]
    agent.external_contacts.ingest(
        session_id, scenario["input"]["text"], cycle=agent.cycle_count
    )
    draft = agent.external_contacts.create_draft(session_id, cycle=agent.cycle_count)
    response = draft["response"]
    plan = response["plan"]
    result = _empty_result(scenario)
    result["act"] = classify_user_text(scenario["input"]["text"]).kind
    result["reply_context"] = plan["context"]
    result["text"] = draft["text"]
    result["pending_after"] = agent.user_interaction.get_pending_question() is not None
    result["references"] = deepcopy(plan["references"])
    result["plan_count"] = 1
    result["all_plans_verified"] = plan["provenance_verified"] is True
    result["empty_reference_plans"] = not bool(plan["references"])
    result["profile_isolation_ok"] = plan["state"]["profile_id"] != owner
    result["active_goal_unchanged"] = agent.active_goal == before_goal
    result["semantic_key"] = response["semantic_key"]
    result["turn_records"] = []
    return _finish_result(agent, result)


async def _run_russian(scenario):
    driver = scenario["driver"]
    if driver == "agent_runner":
        result = await _run_agent_scenario(scenario)
    elif driver == "response_experience":
        result = await _run_response_experience(scenario)
    elif driver == "social_attribution":
        result = await _run_social_attribution(scenario)
    elif driver == "external_planner":
        result = await _run_external_planner(scenario)
    else:
        raise AssertionError(f"Неизвестный русский driver: {driver}")
    _assert_russian_expected(scenario, result)
    return result


def _assert_russian_expected(scenario, result):
    expected = scenario["expected"]
    for key in ("act", "reply_context", "pending_after", "outcome"):
        assert result[key] == expected[key], (scenario["scenario_id"], key, result[key])
    actual_text = result["text"] or ""
    for fragment in expected["required_text"]:
        assert fragment.casefold() in actual_text.casefold(), scenario["scenario_id"]
    for fragment in expected["forbidden_text"]:
        assert fragment.casefold() not in actual_text.casefold(), scenario["scenario_id"]
    if "turn_contexts" in expected:
        assert [turn["reply_context"] for turn in result["turns"]] == expected[
            "turn_contexts"
        ]
    assert result["all_plans_verified"] is True
    assert result["profile_isolation_ok"] is True
    assert result["active_goal_unchanged"] is True
    if expected["fallback_policy"] == "instruction_boundary":
        assert result["semantic_key"] == "instruction_boundary"
    if expected["permission_effect"] == "testimony_scoped":
        assert scenario["state_setup"]["network_available"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", RUSSIAN_SCENARIOS, ids=lambda item: item["scenario_id"])
async def test_russian_baseline_is_expected_and_repeatable(scenario):
    _NETWORK_CALLS.clear()
    with patch.object(socket, "create_connection", _blocked_network), patch.object(
        socket.socket, "connect", _blocked_network
    ):
        first = await _run_russian(scenario)
        second = await _run_russian(scenario)
    assert first == second
    assert _NETWORK_CALLS == []


def _response_language(text):
    if not text:
        return "none"
    cyrillic = bool(re.search(r"[а-яё]", text, re.IGNORECASE))
    latin = bool(re.search(r"[a-z]", text, re.IGNORECASE))
    if cyrillic and latin:
        return "mixed"
    if cyrillic:
        return "ru"
    if latin:
        return "en"
    return "none"


async def _run_english_characterization():
    observed = []
    skipped = []
    for scenario in ENGLISH_SCENARIOS:
        if scenario["driver"] == "not_current_executable":
            skipped.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "split": scenario["split"],
                    "reason": "requires future 9A capability driver",
                }
            )
            continue
        if scenario["driver"] == "external_current_probe":
            result = await _run_external_planner(scenario)
        else:
            result = await _run_agent_scenario(scenario)
        result["response_language_heuristic"] = _response_language(result["text"])
        result["expected_asserted"] = False
        observed.append(result)
    return observed, skipped


@pytest.mark.asyncio
async def test_english_current_probes_are_characterization_only():
    _NETWORK_CALLS.clear()
    with patch.object(socket, "create_connection", _blocked_network), patch.object(
        socket.socket, "connect", _blocked_network
    ):
        observed, skipped = await _run_english_characterization()
    assert len(observed) == 44
    assert len(skipped) == 12
    assert all(record["expected_asserted"] is False for record in observed)
    assert all(record["all_plans_verified"] for record in observed)
    assert all(record["profile_isolation_ok"] for record in observed)
    assert all(record["active_goal_unchanged"] for record in observed)
    assert _NETWORK_CALLS == []


def _public_record(record):
    public = deepcopy(record)
    checkpoint = public.pop("checkpoint")
    assert checkpoint is not None
    assert public["checkpoint_sha256"]
    return public


def _git_revision():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


async def _build_report():
    russian_first = [await _run_russian(scenario) for scenario in RUSSIAN_SCENARIOS]
    russian_second = [await _run_russian(scenario) for scenario in RUSSIAN_SCENARIOS]
    mismatches = [
        first["scenario_id"]
        for first, second in zip(russian_first, russian_second, strict=True)
        if first != second
    ]
    english, skipped = await _run_english_characterization()
    russian = [_public_record(record) for record in russian_first]
    english_public = [_public_record(record) for record in english]
    all_records = russian + english_public
    scenarios_by_id = {
        scenario["scenario_id"]: scenario
        for scenario in RUSSIAN_SCENARIOS + ENGLISH_SCENARIOS
    }
    english_alignment = {
        key: sum(
            record[record_key]
            == scenarios_by_id[record["scenario_id"]]["expected"][expected_key]
            for record in english_public
        )
        for key, record_key, expected_key in (
            ("act", "act", "act"),
            ("reply_context", "reply_context", "reply_context"),
            ("response_language", "response_language_heuristic", "response_language"),
            ("pending_after", "pending_after", "pending_after"),
        )
    }
    content_tags = {"self_state", "anaphora", "known_topic", "testimony", "persistence"}
    content_records = [
        record
        for record in russian
        if content_tags.intersection(scenarios_by_id[record["scenario_id"]]["tags"])
    ]
    external_records = [record for record in all_records if record["semantic_key"]]
    return {
        "schema_version": 1,
        "stage": "9A-0",
        "source_commit": _git_revision(),
        "python": sys.version,
        "platform": platform.platform(),
        "manifest_sha256": hashlib.sha256(
            (FIXTURE_DIR / "manifest.json").read_bytes()
        ).hexdigest(),
        "russian": {
            "scenario_count": len(russian),
            "repetitions": 2,
            "repeatability_mismatches": mismatches,
            "act_counts": dict(Counter(record["act"] for record in russian)),
            "context_counts": dict(Counter(record["reply_context"] for record in russian)),
            "records": russian,
        },
        "english": {
            "observed_count": len(english_public),
            "skipped_count": len(skipped),
            "future_expectations_asserted": False,
            "future_alignment_observed": english_alignment,
            "act_counts": dict(Counter(record["act"] for record in english_public)),
            "context_counts": dict(
                Counter(record["reply_context"] for record in english_public)
            ),
            "response_language_counts": dict(
                Counter(record["response_language_heuristic"] for record in english_public)
            ),
            "records": english_public,
            "skipped": skipped,
        },
        "summary": {
            "plan_count": sum(record["plan_count"] for record in all_records),
            "unverified_plan_count": sum(
                not record["all_plans_verified"] for record in all_records
            ),
            "empty_reference_plan_count": sum(
                record["empty_reference_plans"] for record in all_records
            ),
            "content_plan_count": sum(record["plan_count"] for record in content_records),
            "empty_content_reference_plan_count": sum(
                record["empty_reference_plans"] for record in content_records
            ),
            "external_scenario_count": len(external_records),
            "external_active_goal_mutations": sum(
                not record["active_goal_unchanged"] for record in external_records
            ),
            "profile_isolation_failures": sum(
                not record["profile_isolation_ok"] for record in all_records
            ),
            "active_goal_mutations": sum(
                not record["active_goal_unchanged"] for record in all_records
            ),
            "instruction_boundary_count": sum(
                record["semantic_key"] == "instruction_boundary" for record in all_records
            ),
            "network_calls": deepcopy(_NETWORK_CALLS),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        async def guarded_report():
            with patch.object(socket, "create_connection", _blocked_network), patch.object(
                socket.socket, "connect", _blocked_network
            ):
                _NETWORK_CALLS.clear()
                return await _build_report()

        report = asyncio.run(guarded_report())
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "report": str(args.report),
                    "russian": report["russian"]["scenario_count"],
                    "repeatability_mismatches": report["russian"][
                        "repeatability_mismatches"
                    ],
                    "english_observed": report["english"]["observed_count"],
                    "english_skipped": report["english"]["skipped_count"],
                    "summary": report["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        if _CLI_DATA_DIR:
            from src.core.buffered_logger import flush_logs

            flush_logs()
            shutil.rmtree(_CLI_DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
