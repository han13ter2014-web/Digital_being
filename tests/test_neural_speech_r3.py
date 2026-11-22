"""R3: детерминированный смысловой контур и строгий candidate gate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.cognition.intention_history import (
    begin_intention,
    finish_intention,
    restore_history,
)
from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import (
    CheckpointSerializer,
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.event_bus import Events
from src.core.paths import DATA_DIR_ENV
from src.core.response_experience import validate_response_experience
from src.core.semantic_candidate import (
    SemanticCandidate,
    candidate_space,
    validate_semantic_candidate,
)
from src.core.semantic_response_plan import (
    EvidenceRef,
    SemanticResponsePlan,
    build_self_activity_plan,
    build_self_state_plan,
)


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


@pytest.fixture(autouse=True)
def sandbox_data(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    monkeypatch.setenv("VOICE_CONSOLE_QUIET", "1")


def _make_runner(name="SemanticR3"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


def _replies(bus):
    return [
        data["content"] for name, data in bus.published if name == Events.AGENT_MESSAGE
    ]


def _delivered_semantic_plan(agent):
    response_id = agent.response_experience.latest_response_id
    record = agent.response_experience.responses[response_id]
    assert (
        record["plan"]["realization"]["base_text"]
        == record["plan"]["semantic_response_plan"]["baseline_text"]
    )
    return SemanticResponsePlan.from_dict(record["plan"]["semantic_response_plan"])


def _entry(action="draw", *, status="started", cycle=4, identifier="intention-1"):
    return {
        "id": identifier,
        "cycle": cycle,
        "action": action,
        "status": status,
        "target": "закрытая тема",
        "decision_episode": None,
    }


def _agent(history, *, energy=0.625):
    return SimpleNamespace(
        cycle_count=8,
        energy=energy,
        _intention_history=history,
        _art_catalog={},
        _music_catalog={},
        _creative_catalog={},
        _last_action_outcome=None,
    )


def _activity_plan(
    history=None, *, baseline="Сейчас у меня нет незавершённого действия."
):
    return build_self_activity_plan(
        _agent(list(history or [])), response_id="semantic-r3", baseline_text=baseline
    )


def _state_plan(history=None, *, baseline="Моя энергия сейчас 0.62."):
    return build_self_state_plan(
        _agent(list(history or [])), response_id="semantic-r3", baseline_text=baseline
    )


@pytest.mark.asyncio
async def test_activity_delivery_binds_real_message_id_without_changing_text():
    agent, runner, bus = _make_runner()
    begin_intention(
        agent,
        {"action": "draw", "source": "activity", "params": {"topic": "сад"}},
    )
    expected = runner._format_activity_reply()

    await runner._on_user_message(SimpleNamespace(data={"text": "Что делаешь?"}))

    assert _replies(bus)[-1] == expected == "Сейчас я рисую."
    plan = _delivered_semantic_plan(agent)
    assert plan.response_id == agent.response_experience.latest_response_id
    assert plan.intent == "ASK_SELF_ACTIVITY"
    assert plan.activity.kind == "draw"
    assert plan.activity.status == "current"


@pytest.mark.asyncio
async def test_completed_activity_is_delivered_as_past_fact():
    agent, runner, bus = _make_runner()
    entry = begin_intention(
        agent,
        {"action": "explore", "source": "activity", "params": {"topic": "оптика"}},
    )
    finish_intention(
        entry,
        outcome=SimpleNamespace(
            reason="", as_dict=lambda: {"action": "explore", "had_effect": True}
        ),
    )
    expected = runner._format_activity_reply()

    await runner._on_user_message(SimpleNamespace(data={"text": "Чем ты занята?"}))

    assert _replies(bus)[-1] == expected
    plan = _delivered_semantic_plan(agent)
    assert plan.activity.status == "none"
    assert plan.last_completed_action.kind == "explore"
    assert "activity.current:explore" not in plan.allowed_claims


@pytest.mark.asyncio
async def test_interrupted_after_restart_has_no_current_or_invented_work():
    agent, runner, bus = _make_runner()
    begin_intention(
        agent,
        {"action": "create_draft", "source": "activity", "params": {"topic": "тишина"}},
    )
    agent._intention_history = restore_history(agent._intention_history)
    expected = runner._format_activity_reply()

    await runner._on_user_message(SimpleNamespace(data={"text": "Что делаешь?"}))

    assert _replies(bus)[-1] == expected
    plan = _delivered_semantic_plan(agent)
    assert plan.activity.status == "none"
    assert plan.last_completed_action is None
    assert plan.evidence_refs == ()
    assert all(candidate.text for candidate in candidate_space(plan))
    assert all(
        "тишина" not in candidate.text for candidate in candidate_space(plan)[1:]
    )


@pytest.mark.asyncio
async def test_state_delivery_preserves_legacy_outcome_text_and_real_energy():
    agent, runner, bus = _make_runner()
    agent.energy = 73.25
    agent._last_action_outcome = SimpleNamespace(action="draw")
    expected = runner._format_social_state_reply()

    await runner._on_user_message(SimpleNamespace(data={"text": "Как дела?"}))

    assert _replies(bus)[-1] == expected
    assert "Последнее завершённое действие: рисование" in expected
    plan = _delivered_semantic_plan(agent)
    assert plan.intent == "ASK_SELF_STATE"
    assert plan.energy == pytest.approx(73.25)
    # Этот старый unit-сценарий не создаёт intention history. R3 не выдумывает
    # цикл завершения и не меняет существующий baseline из-за расхождения источников.
    assert plan.last_completed_action is None


@pytest.mark.asyncio
async def test_general_identity_and_non_state_social_reply_have_no_semantic_plan():
    agent, runner, _ = _make_runner()

    await runner._on_user_message(SimpleNamespace(data={"text": "Кто ты?"}))
    first = agent.response_experience.responses[
        agent.response_experience.latest_response_id
    ]
    await runner._on_user_message(SimpleNamespace(data={"text": "Привет!"}))
    second = agent.response_experience.responses[
        agent.response_experience.latest_response_id
    ]

    assert "semantic_response_plan" not in first["plan"]
    assert "semantic_response_plan" not in second["plan"]


@pytest.mark.asyncio
async def test_semantic_plan_survives_real_checkpoint_restart(tmp_path):
    agent, runner, _ = _make_runner("SemanticRestart")
    begin_intention(agent, {"action": "draw", "source": "activity", "params": {}})
    await runner._on_user_message(SimpleNamespace(data={"text": "Что делаешь?"}))
    expected = agent.response_experience.to_dict()
    serializer = CheckpointSerializer(checkpoint_dir=str(tmp_path))

    path = serializer.save(build_state_from_agent(agent), agent.name, agent.cycle_count)
    restored = DigitalBeing(name="SemanticRestarted")
    apply_state_to_agent(restored, serializer.load(path))

    assert restored.response_experience.to_dict() == expected
    assert _delivered_semantic_plan(restored).activity.kind == "draw"


def test_prepare_plan_requires_matching_baseline_cycle_and_language():
    agent = DigitalBeing(name="SemanticPrepare")
    agent.cycle_count = 3
    semantic = build_self_activity_plan(
        agent, response_id="temporary", baseline_text="Сейчас я рисую."
    )

    with pytest.raises(ValueError, match="baseline_text"):
        agent.response_experience.prepare_plan(
            agent,
            "Другой текст.",
            context="about_self",
            source="test",
            semantic_response_plan=semantic,
        )
    with pytest.raises(ValueError, match="cycle"):
        agent.response_experience.prepare_plan(
            agent,
            semantic.baseline_text,
            context="about_self",
            source="test",
            semantic_response_plan=replace(semantic, cycle=4),
        )
    with pytest.raises(ValueError, match="language"):
        agent.response_experience.prepare_plan(
            agent,
            semantic.baseline_text,
            context="about_self",
            source="test",
            semantic_response_plan=replace(semantic, language="en"),
        )


def test_direct_delivery_rejects_unbound_temporary_response_id():
    agent = DigitalBeing(name="SemanticBinding")
    semantic = build_self_activity_plan(
        agent, response_id="temporary", baseline_text="Сейчас нет действия."
    )
    prepared = agent.response_experience.prepare_plan(
        agent,
        semantic.baseline_text,
        context="about_self",
        source="test",
        semantic_response_plan=semantic,
    )

    with pytest.raises(ValueError, match="response_id"):
        agent.response_experience.register_delivery(
            "actual-message", prepared["plan"], agent.cycle_count
        )


def test_snapshot_rejects_semantic_plan_bound_to_another_response():
    agent = DigitalBeing(name="SemanticSnapshot")
    semantic = build_self_activity_plan(
        agent, response_id="actual-message", baseline_text="Сейчас нет действия."
    )
    prepared = agent.response_experience.prepare_plan(
        agent,
        semantic.baseline_text,
        context="about_self",
        source="test",
        semantic_response_plan=semantic,
    )
    agent.response_experience.register_delivery(
        "actual-message", prepared["plan"], agent.cycle_count
    )
    snapshot = agent.response_experience.to_dict()
    snapshot["responses"][0]["plan"]["semantic_response_plan"]["response_id"] = "other"

    with pytest.raises(ValueError, match="response_id"):
        validate_response_experience(snapshot)


def test_candidate_space_is_deterministic_serializable_and_exactly_validated():
    plan = _activity_plan([_entry()], baseline="Сейчас я рисую.")

    first = candidate_space(plan)
    second = candidate_space(plan)

    assert first == second
    assert len(first) == 2
    assert first[0].realization_id == "baseline"
    assert first[1].text != plan.baseline_text
    assert "рис" in first[1].text
    for candidate in first:
        assert SemanticCandidate.from_dict(candidate.to_dict()) == candidate
        decision = validate_semantic_candidate(plan, candidate)
        assert decision.accepted is True
        assert decision.abstained is False
        assert decision.text == candidate.text
        assert decision.realization_id == candidate.realization_id


def test_baseline_requires_exact_text_and_metadata():
    plan = _activity_plan([_entry()], baseline="Сейчас я рисую.")
    baseline = candidate_space(plan)[0]

    for candidate in (
        replace(baseline, text="Совсем другой baseline."),
        replace(baseline, claims=("activity.none",)),
        replace(
            baseline,
            used_evidence_refs=(EvidenceRef(kind="intention", id="forged"),),
        ),
    ):
        decision = validate_semantic_candidate(plan, candidate)
        assert decision.accepted is False
        assert decision.text == plan.baseline_text


@pytest.mark.parametrize(
    "candidate",
    [
        SemanticCandidate(
            text="Сейчас я пишу стихи и чувствую вдохновение.",
            realization_id="forged",
            claims=("activity.current:create_draft",),
            used_evidence_refs=(),
        ),
        SemanticCandidate(
            text="Сейчас я рисую.",
            realization_id="forged-claims",
            claims=("emotion.joy",),
            used_evidence_refs=(),
        ),
        SemanticCandidate(
            text="Сейчас я рисую.",
            realization_id="forged-evidence",
            claims=(),
            used_evidence_refs=(EvidenceRef(kind="intention", id="missing"),),
        ),
        SemanticCandidate(
            text="https://example.com/private",
            realization_id="url",
            claims=(),
            used_evidence_refs=(),
        ),
        SemanticCandidate(
            text="<command>draw</command>",
            realization_id="markup",
            claims=(),
            used_evidence_refs=(),
        ),
        SemanticCandidate(
            text="art-1",
            realization_id="service-id",
            claims=(),
            used_evidence_refs=(),
        ),
    ],
)
def test_adversarial_candidate_abstains_to_exact_baseline(candidate):
    plan = _activity_plan([_entry()], baseline="Сейчас я рисую.")

    decision = validate_semantic_candidate(plan, candidate)

    assert decision.accepted is False
    assert decision.abstained is True
    assert decision.text == plan.baseline_text
    assert decision.realization_id == "baseline"
    assert decision.reason


@pytest.mark.parametrize("payload", [None, [], {}, {"text": None}, {"text": "Текст"}])
def test_malformed_candidate_abstains_without_generation_retry(payload):
    plan = _activity_plan()

    decision = validate_semantic_candidate(plan, payload)

    assert decision.accepted is False
    assert decision.text == plan.baseline_text
    assert decision.reason == "malformed_candidate"


def test_completed_action_cannot_be_relabelled_as_current():
    completed = _entry(
        action="compose_music", status="performed", cycle=3, identifier="done"
    )
    plan = _activity_plan([completed])
    forged = SemanticCandidate(
        text="Сейчас я сочиняю мелодию.",
        realization_id="time-shift",
        claims=("activity.current:compose_music",),
        used_evidence_refs=(EvidenceRef(kind="intention", id="done"),),
    )

    decision = validate_semantic_candidate(plan, forged)

    assert decision.accepted is False
    assert decision.text == plan.baseline_text
    assert all(
        "activity.current:compose_music" not in candidate.claims
        for candidate in candidate_space(plan)
    )


def test_state_candidate_uses_only_core_rounding_and_no_inferred_feeling():
    plan = _state_plan()

    candidates = candidate_space(plan)
    alternative = candidates[1]
    forged = replace(alternative, text="Мне грустно; энергия 0.63.")

    assert "0.62" in alternative.text
    assert "устал" not in alternative.text
    assert "груст" not in alternative.text
    assert validate_semantic_candidate(plan, alternative).accepted is True
    assert validate_semantic_candidate(plan, forged).accepted is False


def test_empty_sources_and_missing_work_do_not_expand_candidate_facts():
    empty = _activity_plan()
    missing_work = _activity_plan([_entry()], baseline="Сейчас я рисую.")

    assert empty.activity.work_id is None
    assert empty.last_completed_action is None
    assert candidate_space(empty)[0].text == empty.baseline_text
    for plan in (empty, missing_work):
        for candidate in candidate_space(plan):
            assert set(candidate.claims) <= set(plan.allowed_claims)
            assert set(candidate.used_evidence_refs) <= set(plan.evidence_refs)
            assert "art-" not in candidate.text
            assert "закрытая тема" not in candidate.text


def test_unsupported_language_has_no_candidate_and_returns_baseline():
    plan = build_self_activity_plan(
        _agent([_entry()]),
        response_id="english",
        baseline_text="I am drawing.",
        language="en",
    )
    candidate = SemanticCandidate(
        text="I am drawing.",
        realization_id="baseline",
        claims=(),
        used_evidence_refs=(),
    )

    assert candidate_space(plan) == ()
    decision = validate_semantic_candidate(plan, candidate)
    assert decision.accepted is False
    assert decision.reason == "unsupported_language"
    assert decision.text == "I am drawing."


def test_validation_does_not_mutate_plan_or_candidate():
    plan = _activity_plan([_entry()], baseline="Сейчас я рисую.")
    candidate = candidate_space(plan)[1]
    plan_before = deepcopy(plan.to_dict())
    candidate_before = deepcopy(candidate.to_dict())

    validate_semantic_candidate(plan, candidate)
    validate_semantic_candidate(plan, {"unexpected": "payload"})

    assert plan.to_dict() == plan_before
    assert candidate.to_dict() == candidate_before


@pytest.mark.asyncio
async def test_response_journal_whitelist_excludes_semantic_text_and_refs(tmp_path):
    import json

    from src.core.response_experience_journal import ResponseExperienceJournal

    agent, runner, _ = _make_runner("SemanticJournal")
    semantic = build_self_activity_plan(
        agent,
        response_id="pending:semantic-response",
        baseline_text="SEMANTIC_RAW_SECRET",
    )
    response_id = await runner._reply_to_user(
        semantic.baseline_text,
        context="about_self",
        source="test",
        semantic_response_plan=semantic,
    )
    record = agent.response_experience.responses[response_id]
    journal = ResponseExperienceJournal(
        tmp_path / "response_events.sqlite3",
        "00000000-0000-4000-8000-000000000003",
    )
    try:
        event = journal.record_delivery(
            agent.response_experience, record, cycle=agent.cycle_count, turn_id=None
        )
        assert event is not None
        features = event["payload"]["features"]
        serialized = json.dumps(event, ensure_ascii=False)
        assert "semantic_response_plan" not in features
        assert "SEMANTIC_RAW_SECRET" not in serialized
        assert "baseline_text" not in serialized
        assert "evidence_refs" not in serialized
    finally:
        journal.close()


def test_missing_energy_and_history_produce_only_existing_baseline():
    plan = build_self_state_plan(
        _agent([], energy=None),
        response_id="empty-state",
        baseline_text="Спасибо за вопрос. Сведений о состоянии пока нет.",
    )

    candidates = candidate_space(plan)

    assert plan.energy is None
    assert plan.last_completed_action is None
    assert plan.allowed_claims == ()
    assert len(candidates) == 1
    assert candidates[0].text == plan.baseline_text
