"""PJ-I: production prospective journal, выключенный по умолчанию."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import tracemalloc
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.dialogue_acts import (
    ACT_ANSWER,
    ACT_FOLLOW_UP,
    ACT_SOCIAL,
    ACT_UNKNOWN,
)
from src.core.event_bus import Events
from src.core.paths import DATA_DIR_ENV
from src.core.response_experience import RESPONSE_TTL_CYCLES
from src.core.speech_imitation import USE_COOLDOWN_CYCLES
from src.core.response_experience_journal import (
    JOURNAL_FILENAME,
    RESPONSE_JOURNAL_ENV,
    JournalCorruption,
    ResponseExperienceJournal,
)

LIFE_ID = "00000000-0000-4000-8000-000000000001"
OTHER_LIFE_ID = "00000000-0000-4000-8000-000000000002"
ROOT = Path(__file__).resolve().parents[1]


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


@pytest.fixture
def journal_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(root))
    monkeypatch.setenv(RESPONSE_JOURNAL_ENV, "1")
    monkeypatch.setenv("VOICE_CONSOLE_QUIET", "1")
    return root


@pytest.fixture
def runner_factory(journal_root):
    runners = []

    def create(*, life_id=LIFE_ID, name="JournalRunner"):
        agent = DigitalBeing(name=name, life_id=life_id)
        bus = RecordingBus()
        runner = AgentRunner(agent, bus)
        agent.user_interaction.attach_bus(bus)
        runners.append(runner)
        return agent, runner, bus

    yield create
    for runner in runners:
        journal = runner._response_experience_journal
        if journal is not None:
            journal.close()


def _journal_path(root, life_id=LIFE_ID):
    return root / "lives" / life_id / JOURNAL_FILENAME


def _events(runner):
    return runner._response_experience_journal.events()


def _event(runner, kind):
    return next(event for event in _events(runner) if event["event_kind"] == kind)


def _prepare_record(agent, response_id, text="Ответ из состояния."):
    prepared = agent.response_experience.prepare_plan(
        agent,
        text,
        context="social_reply",
        source="core",
        user_text="Вход, который нельзя сохранять",
    )
    return agent.response_experience.register_delivery(
        response_id, prepared["plan"], agent.cycle_count
    )


def _switch(agent, profile_id, cycle):
    agent.social_registry.switch_to(profile_id, cycle=cycle)
    assert agent.social_attribution.sync_active_profile() is True


def _state_differences(left, right, path=""):
    if isinstance(left, dict) and isinstance(right, dict):
        differences = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                differences.append((child, left.get(key), right.get(key)))
            else:
                differences.extend(_state_differences(left[key], right[key], child))
        return differences
    if isinstance(left, list) and isinstance(right, list):
        differences = []
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(left) or index >= len(right):
                differences.append((child, "missing", "different length"))
            else:
                differences.extend(_state_differences(left[index], right[index], child))
        return differences
    return [] if left == right else [(path, left, right)]


@pytest.mark.asyncio
async def test_default_disabled_creates_no_artifact_or_checkpoint_field(
    journal_root, runner_factory, monkeypatch
):
    monkeypatch.delenv(RESPONSE_JOURNAL_ENV)
    agent, runner, _ = runner_factory(name="JournalDisabled")
    checkpoint_keys = set(build_state_from_agent(agent))
    snapshot_keys = set(agent.response_experience.to_dict())

    message_id = await runner._reply_to_user(
        "Обычная доставка.", context="social_reply", source="core"
    )

    assert message_id
    assert runner._response_experience_journal is None
    assert agent.response_experience.transition_observer is None
    assert not _journal_path(journal_root).exists()
    assert runner.get_status()["response_experience_journal"]["status"] == "disabled"
    assert set(build_state_from_agent(agent)) == checkpoint_keys
    assert set(agent.response_experience.to_dict()) == snapshot_keys
    assert "response_experience_journal" not in build_state_from_agent(agent)


@pytest.mark.asyncio
async def test_real_local_turns_link_delivery_and_outcome_by_original_episode(
    runner_factory,
):
    agent, runner, _ = runner_factory(name="JournalTurns")

    async def controlled_input(event):
        if event.data["text"] == "первый вход":
            await runner._reply_to_user(
                "Локальный ответ.",
                context="social_reply",
                source="core",
                user_text=event.data["text"],
            )
        else:
            agent.response_experience.observe_reply(ACT_ANSWER, agent.cycle_count)

    runner._on_user_message_impl = controlled_input
    await runner._on_user_message(SimpleNamespace(data={"text": "первый вход"}))
    await runner._on_user_message(SimpleNamespace(data={"text": "второй вход"}))

    delivery = _event(runner, "delivery")
    outcome = _event(runner, "outcome")
    assert delivery["turn_id"] == "turn-1"
    assert outcome["turn_id"] == "turn-2"
    assert outcome["payload"]["observation_turn_id"] == "turn-2"
    assert outcome["episode_id"] == delivery["episode_id"]
    assert outcome["response_id"] == delivery["response_id"]
    assert outcome["payload"]["delivery_sequence"] == delivery["event_sequence"]
    assert runner._response_journal_turn_id is None
    assert "outcome" not in delivery["payload"]


@pytest.mark.asyncio
async def test_missing_message_id_and_thought_fallback_create_no_delivery(
    runner_factory, monkeypatch
):
    agent, runner, bus = runner_factory(name="JournalNoDelivery")
    monkeypatch.setattr(
        agent.user_interaction, "send_reply", lambda *args, **kwargs: None
    )

    assert (
        await runner._reply_to_user(
            "Не доставлено.", context="social_reply", source="core"
        )
        is None
    )
    agent.user_interaction = None
    assert (
        await runner._reply_to_user(
            "Только мысль.", context="social_reply", source="core"
        )
        is None
    )

    assert [event["event_kind"] for event in _events(runner)] == ["journal_started"]
    assert agent.response_experience.responses == {}
    assert bus.published[-1][0] == Events.AGENT_THOUGHT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("act", "feedback", "expected"),
    [
        (ACT_ANSWER, None, "answer"),
        (ACT_FOLLOW_UP, None, "follow_up"),
        (ACT_UNKNOWN, None, "unclassified_reply"),
        (ACT_SOCIAL, None, "ordinary_reply"),
        (None, "support", "explicit_support"),
        (None, "opposition", "explicit_opposition"),
    ],
)
async def test_all_observed_outcomes_come_from_real_transitions(
    runner_factory, act, feedback, expected
):
    agent, runner, _ = runner_factory(name=f"Journal{expected}")
    response_id = await runner._reply_to_user(
        "Проверяемый ответ.", context="social_reply", source="core"
    )
    if feedback is None:
        observed = agent.response_experience.observe_reply(act, agent.cycle_count)
    else:
        observed = agent.response_experience.observe_feedback(
            response_id, feedback, agent.cycle_count
        )

    outcome = _event(runner, "outcome")
    assert observed["outcome"] == expected
    assert outcome["payload"]["observed_outcome"] == expected
    assert outcome["payload"]["observation_kind"] == (
        "explicit_feedback" if feedback else "ordinary_reply"
    )
    assert runner._response_experience_journal.samples()[0]["outcome"] == expected


@pytest.mark.asyncio
async def test_expiry_is_censored_and_terminal_observation_does_not_repeat(
    runner_factory,
):
    agent, runner, _ = runner_factory(name="JournalExpiry")
    response_id = await runner._reply_to_user(
        "Ожидание реакции.", context="social_reply", source="core"
    )

    assert agent.response_experience.expire(RESPONSE_TTL_CYCLES + 1) == 1
    assert (
        agent.response_experience.observe_feedback(
            response_id, "support", RESPONSE_TTL_CYCLES + 2
        )
        is None
    )

    expired = _event(runner, "expired")
    assert expired["payload"]["observed_outcome"] == "no_observed_reaction"
    assert expired["payload"]["observation_kind"] == "ttl_expired"
    assert expired["payload"]["observation_turn_id"] is None
    assert [event["event_kind"] for event in _events(runner)].count("outcome") == 0
    assert runner._response_experience_journal.samples() == []


@pytest.mark.asyncio
async def test_retry_late_outcome_and_delivery_immutability(runner_factory):
    agent, runner, _ = runner_factory(name="JournalLateOutcome")
    response_id = await runner._reply_to_user(
        "Первый ответ.", context="social_reply", source="core"
    )
    record = agent.response_experience.responses[response_id]
    delivery = deepcopy(_event(runner, "delivery"))

    retry = runner._response_experience_journal.record_delivery(
        agent.response_experience, record, cycle=0, turn_id=None
    )
    assert retry == delivery
    assert len(_events(runner)) == 2

    agent.response_experience.observe_feedback(response_id, "support", 1)
    outcome = _event(runner, "outcome")
    assert _event(runner, "delivery") == delivery
    assert (
        runner._response_experience_journal.samples(
            outcome_before_sequence=outcome["event_sequence"]
        )
        == []
    )
    samples = runner._response_experience_journal.samples(
        outcome_before_sequence=outcome["event_sequence"] + 1
    )
    assert samples[0]["outcome_sequence"] == outcome["event_sequence"]


@pytest.mark.asyncio
async def test_privacy_borrowed_level_and_repeat_origin(runner_factory):
    agent, runner, _ = runner_factory(name="JournalPrivacy")
    profile_id = agent.social_registry.current_profile_id
    secret_expression = "доброе утро"
    for cycle in (1, 2):
        agent.response_experience.imitation.observe(
            secret_expression,
            context="greeting",
            profile_id=profile_id,
            cycle=cycle,
        )
    secret_concept = next(iter(agent.mental_models.concepts))
    agent.cycle_count = 3
    first_id = await runner._reply_to_user(
        "AGENT_RAW_SECRET",
        context="social_reply",
        source="dynamic-private-source",
        user_text="USER_RAW_SECRET",
        response_references=[{"kind": "concept", "id": secret_concept}],
        borrow_context="greeting",
    )
    agent.cycle_count = 3 + USE_COOLDOWN_CYCLES
    second_id = await runner._reply_to_user(
        "AGENT_RAW_SECRET",
        context="social_reply",
        source="dynamic-private-source",
        user_text="USER_RAW_SECRET",
        response_references=[{"kind": "concept", "id": secret_concept}],
        borrow_context="greeting",
    )

    deliveries = [
        event for event in _events(runner) if event["event_kind"] == "delivery"
    ]
    first_features = deliveries[0]["payload"]["features"]
    second_features = deliveries[1]["payload"]["features"]
    assert first_features["source"] == "other"
    assert first_features["borrowed_level"] == "situational"
    assert first_features["reference_kind_counts"] == {"concept": "1-2"}
    assert first_features["repeat_in_retained_window"] is False
    assert second_features["realization_origin_response_id"] == first_id
    assert second_features["repeat_in_retained_window"] is True

    journal = runner._response_experience_journal
    journal.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    stored = journal.path.read_bytes().decode("utf-8", errors="ignore")
    for forbidden in (
        "AGENT_RAW_SECRET",
        "USER_RAW_SECRET",
        secret_expression,
        secret_concept,
        "dynamic-private-source",
        "observed_input",
        "base_text",
        "text_sha256",
        "realization_fingerprint",
    ):
        assert forbidden not in stored
    assert second_id != first_id


@pytest.mark.asyncio
async def test_consolidation_prunes_window_but_not_journal_outcome(
    runner_factory, monkeypatch
):
    agent, runner, _ = runner_factory(name="JournalPruning")
    first = await runner._reply_to_user(
        "Повторяемый ответ.", context="social_reply", source="core"
    )
    second = await runner._reply_to_user(
        "Повторяемый ответ.", context="social_reply", source="core"
    )
    agent.response_experience.observe_feedback(first, "support", 1)
    agent.response_experience.observe_feedback(second, "opposition", 1)
    monkeypatch.setattr("src.core.response_experience.CONSOLIDATED_RESPONSE_HISTORY", 1)

    report = agent.social_attribution.consolidate_language(2)

    assert report["pruned_responses"] == 1
    pruned = _event(runner, "record_pruned")
    delivery = next(
        event
        for event in _events(runner)
        if event["event_kind"] == "delivery" and event["response_id"] == first
    )
    assert pruned["response_id"] == first
    assert pruned["episode_id"] == delivery["episode_id"]
    assert pruned["payload"]["origin_unavailable"] is False
    assert (
        len([event for event in _events(runner) if event["event_kind"] == "outcome"])
        == 2
    )
    deliveries = [
        event for event in _events(runner) if event["event_kind"] == "delivery"
    ]
    assert (
        deliveries[1]["payload"]["features"]["realization_origin_response_id"] == first
    )


@pytest.mark.asyncio
async def test_orphan_outcome_and_pruning_are_explicit_gaps(runner_factory):
    agent, runner, _ = runner_factory(name="JournalOrphans")
    record = _prepare_record(agent, "orphan-response")
    agent.response_experience.observe_feedback("orphan-response", "support", 0)
    pruned = agent.response_experience.responses.pop("orphan-response")
    runner._response_experience_journal.record_transition(
        "record_pruned", pruned, cycle=0, turn_id=None
    )

    gaps = [event for event in _events(runner) if event["event_kind"] == "journal_gap"]
    assert any(
        event["payload"].get("reason") == "orphan_outcome"
        and event["payload"]["completeness"] == "unverified"
        for event in gaps
    )
    event = _event(runner, "record_pruned")
    assert event["response_id"] == record["response_id"]
    assert event["payload"]["origin_unavailable"] is True
    assert runner._response_experience_journal.samples() == []


@pytest.mark.asyncio
async def test_writer_failure_and_hard_budgets_are_fail_open(
    runner_factory, journal_root
):
    agent, runner, _ = runner_factory(name="JournalFailure")
    journal = runner._response_experience_journal
    journal.fail_next_append = True

    response_id = await runner._reply_to_user(
        "Доставка не зависит от журнала.", context="social_reply", source="core"
    )

    assert response_id in agent.response_experience.responses
    assert journal.status == "degraded"
    assert journal.get_status()["dropped_events"] >= 1
    assert any(
        event["event_kind"] == "journal_gap"
        and event["payload"]["reason"] == "injected_append_failure"
        for event in journal.events()
    )

    sequence = journal.get_status()["event_sequence"]
    journal.max_payload_bytes = 1
    await runner._reply_to_user(
        "Слишком большой payload.", context="social_reply", source="core"
    )
    assert journal.get_status()["event_sequence"] == sequence
    assert journal.last_error == "hard_payload_budget"

    journal.max_payload_bytes = None
    journal.max_storage_bytes = journal.get_status()["storage_bytes"]
    await runner._reply_to_user(
        "Storage budget.", context="social_reply", source="core"
    )
    assert journal.last_error == "hard_storage_budget"
    assert len(agent.response_experience.responses) == 3
    assert journal.path == _journal_path(journal_root)


@pytest.mark.asyncio
async def test_event_budget_reserves_one_visible_gap(runner_factory):
    agent, runner, _ = runner_factory(name="JournalEventBudget")
    journal = runner._response_experience_journal
    journal.max_events = journal.get_status()["event_sequence"] + 2
    response_id = await runner._reply_to_user(
        "Последняя обычная запись.", context="social_reply", source="core"
    )
    agent.response_experience.observe_feedback(response_id, "support", 0)

    assert len(agent.response_experience.responses) == 1
    assert agent.response_experience.responses[response_id]["outcome"] == (
        "explicit_support"
    )
    assert journal.get_status()["event_sequence"] == journal.max_events
    assert journal.events()[-1]["event_kind"] == "journal_gap"
    assert journal.events()[-1]["payload"]["reason"] == "hard_event_budget"
    assert journal.status == "degraded"


def test_restart_continues_hash_chain_and_closes_wal(journal_root):
    path = _journal_path(journal_root)
    first = ResponseExperienceJournal(path, LIFE_ID)
    agent = DigitalBeing(name="JournalRestart", life_id=LIFE_ID)
    record = _prepare_record(agent, "restart-response")
    first.record_delivery(agent.response_experience, record, cycle=0, turn_id="turn-1")
    first.close()
    connection = sqlite3.connect(path)
    previous_sequence, previous_hash = connection.execute(
        "SELECT sequence, event_hash FROM head WHERE id=1"
    ).fetchone()
    connection.close()

    assert first.integrity_after_close() == ["ok"]
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()
    second = ResponseExperienceJournal(path, LIFE_ID)
    started = second.events()[-1]
    assert started["event_kind"] == "journal_started"
    assert started["payload"]["previous_shutdown_unclean"] is False
    assert started["payload"]["previous_sequence"] == previous_sequence
    assert started["payload"]["previous_hash"] == previous_hash
    assert second.get_status()["event_sequence"] == previous_sequence + 1
    second.close()


def test_unclean_restart_and_crash_window_are_unverified(journal_root):
    path = _journal_path(journal_root)
    code = f"""
import os
from src.core.agent import DigitalBeing
from src.core.response_experience_journal import ResponseExperienceJournal
agent = DigitalBeing(name='JournalCrash', life_id={LIFE_ID!r})
journal = ResponseExperienceJournal({str(path)!r}, {LIFE_ID!r})
prepared = agent.response_experience.prepare_plan(
    agent, 'Доставлено до crash', context='social_reply', source='core'
)
agent.response_experience.register_delivery('crash-response', prepared['plan'], 0)
os._exit(0)
"""
    environment = os.environ.copy()
    environment[DATA_DIR_ENV] = str(journal_root)
    environment["VOICE_CONSOLE_QUIET"] = "1"
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        check=True,
        timeout=30,
    )

    restarted = ResponseExperienceJournal(path, LIFE_ID)
    kinds = [event["event_kind"] for event in restarted.events()]
    assert "delivery" not in kinds
    assert any(
        event["event_kind"] == "journal_gap"
        and event["payload"]["reason"] == "previous_shutdown_unclean"
        and event["payload"]["completeness"] == "unverified"
        for event in restarted.events()
    )
    assert restarted.samples() == []
    assert restarted.status == "degraded"
    restarted.close()


@pytest.mark.asyncio
async def test_corruption_is_quarantined_before_append_and_life_continues(
    journal_root,
):
    path = _journal_path(journal_root)
    writer = ResponseExperienceJournal(path, LIFE_ID)
    writer.close()
    connection = sqlite3.connect(path)
    connection.execute("DROP TRIGGER events_append_only_update")
    connection.execute(
        "UPDATE events SET event_hash=? WHERE event_sequence=1", ("0" * 64,)
    )
    corrupted_rows = connection.execute(
        "SELECT event_id, event_hash FROM events ORDER BY event_sequence"
    ).fetchall()
    connection.commit()
    connection.close()

    with pytest.raises(JournalCorruption, match="event_hash_mismatch"):
        ResponseExperienceJournal(path, LIFE_ID)
    agent = DigitalBeing(name="JournalCorruption", life_id=LIFE_ID)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    journal = runner._response_experience_journal
    assert journal.status == "quarantine"
    assert journal.connection is None
    assert journal.events() == []

    response_id = await runner._reply_to_user(
        "Жизнь продолжается без журнала.", context="social_reply", source="core"
    )
    assert response_id in agent.response_experience.responses
    connection = sqlite3.connect(path)
    assert (
        connection.execute(
            "SELECT event_id, event_hash FROM events ORDER BY event_sequence"
        ).fetchall()
        == corrupted_rows
    )
    connection.close()
    await runner.stop()


@pytest.mark.asyncio
async def test_second_life_has_isolated_sequence_and_repeat_graph(runner_factory):
    first_agent, first_runner, _ = runner_factory(name="JournalFirstLife")
    second_agent, second_runner, _ = runner_factory(
        life_id=OTHER_LIFE_ID, name="JournalSecondLife"
    )

    await first_runner._reply_to_user(
        "Одинаковый текст.", context="social_reply", source="core"
    )
    await second_runner._reply_to_user(
        "Одинаковый текст.", context="social_reply", source="core"
    )

    first_events = _events(first_runner)
    second_events = _events(second_runner)
    assert {event["life_id"] for event in first_events} == {LIFE_ID}
    assert {event["life_id"] for event in second_events} == {OTHER_LIFE_ID}
    assert [event["event_sequence"] for event in second_events] == [1, 2]
    second_delivery = _event(second_runner, "delivery")
    assert second_delivery["payload"]["features"]["repeat_in_retained_window"] is False
    assert (
        second_delivery["payload"]["features"]["realization_origin_response_id"] is None
    )
    assert second_agent.response_experience.latest_response_id not in {
        event["response_id"] for event in first_events
    }


@pytest.mark.asyncio
async def test_core_restore_does_not_roll_back_or_rewrite_journal(runner_factory):
    agent, runner, _ = runner_factory(name="JournalRestore")
    response_id = await runner._reply_to_user(
        "Ответ до snapshot.", context="social_reply", source="core"
    )
    agent.response_experience.observe_feedback(response_id, "support", 0)
    before = deepcopy(_events(runner))
    state = build_state_from_agent(agent)

    apply_state_to_agent(agent, state)

    after = _events(runner)
    assert after[: len(before)] == before
    assert after[-1]["event_kind"] == "journal_gap"
    assert after[-1]["payload"] == {
        "completeness": "unverified",
        "reason": "core_restore_divergence",
    }
    assert agent.response_experience.responses[response_id]["outcome"] == (
        "explicit_support"
    )


@pytest.mark.asyncio
async def test_disabled_enabled_controlled_differential(
    journal_root, runner_factory, monkeypatch
):
    monkeypatch.setattr(
        "src.perception.user_interaction.uuid4", lambda: SimpleNamespace(hex="fixed")
    )
    monkeypatch.delenv(RESPONSE_JOURNAL_ENV)
    disabled_agent, disabled_runner, disabled_bus = runner_factory(name="SameLife")
    template = build_state_from_agent(disabled_agent)
    apply_state_to_agent(disabled_agent, template)
    disabled_id = await disabled_runner._reply_to_user(
        "Одинаковый ответ.", context="social_reply", source="core"
    )
    disabled_agent.response_experience.observe_feedback(disabled_id, "support", 0)
    disabled_state = build_state_from_agent(disabled_agent)

    monkeypatch.setenv(RESPONSE_JOURNAL_ENV, "1")
    monkeypatch.setenv(DATA_DIR_ENV, str(journal_root / "enabled"))
    enabled_agent, enabled_runner, enabled_bus = runner_factory(name="SameLife")
    apply_state_to_agent(enabled_agent, template)
    enabled_id = await enabled_runner._reply_to_user(
        "Одинаковый ответ.", context="social_reply", source="core"
    )
    enabled_agent.response_experience.observe_feedback(enabled_id, "support", 0)
    enabled_state = build_state_from_agent(enabled_agent)

    assert enabled_id == disabled_id
    disabled_state.pop("saved_at")
    enabled_state.pop("saved_at")
    assert _state_differences(enabled_state, disabled_state) == []
    assert enabled_bus.published == disabled_bus.published
    assert enabled_runner._response_experience_journal is not None
    assert disabled_runner._response_experience_journal is None


@pytest.mark.asyncio
async def test_inactive_profile_consolidation_keeps_observer(runner_factory):
    agent, runner, _ = runner_factory(name="JournalInactive")
    response_id = await runner._reply_to_user(
        "Ожидание неактивного профиля.", context="social_reply", source="core"
    )
    owner = agent.social_registry.current_profile_id
    guest = agent.social_registry.create_local_person("Inactive guest", cycle=1)
    _switch(agent, guest, 1)

    report = agent.social_attribution.consolidate_language(RESPONSE_TTL_CYCLES + 1)

    assert report["expired_responses"] == 1
    expired = _event(runner, "expired")
    assert expired["response_id"] == response_id
    assert expired["profile_id"] == owner


def test_external_session_scoped_registration_is_not_local_delivery(runner_factory):
    agent, runner, _ = runner_factory(name="JournalExternalBoundary")
    prepared = agent.response_experience.prepare_plan(
        agent,
        "Внешний ответ.",
        context="social_reply",
        source="core",
        profile_id="external-ai",
        expire_pending=False,
    )
    agent.response_experience.register_delivery(
        "external-session-response", prepared["plan"], 0
    )

    assert [event["event_kind"] for event in _events(runner)] == ["journal_started"]


def test_concurrent_writers_and_append_only_database(journal_root):
    path = _journal_path(journal_root)
    first = ResponseExperienceJournal(path, LIFE_ID)
    second = ResponseExperienceJournal(path, LIFE_ID)
    agent = DigitalBeing(name="JournalConcurrent", life_id=LIFE_ID)
    first_record = _prepare_record(agent, "concurrent-first", "Первый ответ.")
    second_record = _prepare_record(agent, "concurrent-second", "Второй ответ.")

    first_turn = first.begin_turn()
    second_turn = second.begin_turn()
    first_event = first.record_delivery(
        agent.response_experience, first_record, cycle=0, turn_id=first_turn
    )
    second_event = second.record_delivery(
        agent.response_experience, second_record, cycle=0, turn_id=second_turn
    )
    retry = second.record_delivery(
        agent.response_experience, first_record, cycle=0, turn_id=first_turn
    )

    assert {first_turn, second_turn} == {"turn-1", "turn-2"}
    assert retry == first_event
    assert second_event["event_sequence"] == first_event["event_sequence"] + 1
    assert [event["event_sequence"] for event in second.events()] == [1, 2, 3, 4]
    with pytest.raises(sqlite3.IntegrityError, match="events_append_only"):
        first.connection.execute("DELETE FROM events WHERE event_sequence=1")
    first.close()
    second.close()
    assert first.integrity_after_close() == ["ok"]
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_closes_writer_before_running(runner_factory):
    _, runner, _ = runner_factory(name="JournalShutdown")
    journal = runner._response_experience_journal
    path = journal.path

    assert runner._running is False
    await runner.stop()
    await runner.stop()

    assert journal.connection is None
    assert journal.get_status()["open"] is False
    assert journal.integrity_after_close() == ["ok"]
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()
    connection = sqlite3.connect(path)
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_kind='journal_stopped'"
        ).fetchone()[0]
        == 1
    )
    connection.close()


def test_production_resource_budget(journal_root, capsys):
    path = _journal_path(journal_root)
    journal = ResponseExperienceJournal(path, LIFE_ID)
    agent = DigitalBeing(name="JournalResources", life_id=LIFE_ID)
    latencies = []
    started = time.perf_counter()
    tracemalloc.start()
    for index in range(40):
        record = _prepare_record(agent, f"resource-{index}")
        before = time.perf_counter()
        journal.record_delivery(
            agent.response_experience, record, cycle=index, turn_id=None
        )
        agent.response_experience.observe_feedback(
            record["response_id"], "support", index
        )
        journal.record_transition(
            "outcome",
            agent.response_experience.responses[record["response_id"]],
            cycle=index,
            turn_id=None,
        )
        latencies.append(time.perf_counter() - before)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    journal.close()
    elapsed = time.perf_counter() - started
    artifact = path.stat().st_size
    ordered = sorted(latencies)
    report = {
        "deliveries": 40,
        "events": 82,
        "elapsed_seconds": round(elapsed, 6),
        "mean_write_pair_ms": round(sum(latencies) / len(latencies) * 1000, 3),
        "p95_write_pair_ms": round(ordered[int(len(ordered) * 0.95) - 1] * 1000, 3),
        "max_write_pair_ms": round(max(latencies) * 1000, 3),
        "artifact_bytes": artifact,
        "tracemalloc_current_bytes": current,
        "tracemalloc_peak_bytes": peak,
    }
    print(f"PJ-I-RESOURCE {json.dumps(report, sort_keys=True)}")

    assert elapsed < 30.0
    assert report["p95_write_pair_ms"] < 250.0
    assert report["max_write_pair_ms"] < 1000.0
    assert artifact < 4 * 1024 * 1024
    assert peak < 16 * 1024 * 1024
    assert journal.integrity_after_close() == ["ok"]
    captured = capsys.readouterr()
    assert "PJ-I-RESOURCE" in captured.out
