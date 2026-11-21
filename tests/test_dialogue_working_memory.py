"""Т5: ограниченная рабочая память диалога и разрешение анафоры."""

import inspect
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.event_bus import Events


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(name="Ring"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


def _replies(bus):
    return [
        dict(data or {}) for name, data in bus.published if name == Events.AGENT_MESSAGE
    ]


async def _say(runner, text):
    await runner._on_user_message(SimpleNamespace(data={"text": text}))


def _last_context(agent):
    return agent.user_interaction.message_history[-1]["context"]


@pytest.mark.asyncio
async def test_anaphora_after_about_self_uses_previous_act_metadata():
    agent, runner, bus = _make_runner("Афродита")
    await _say(runner, "Чем занимаешься?")

    await _say(runner, "Почему?")

    assert agent.user_interaction.get_pending_question() is None
    assert _last_context(agent) == "follow_up"
    reply = _replies(bus)[-1]["content"]
    assert "предыдущ" in reply.lower()
    assert "Афродита" in reply
    assert (
        agent.user_interaction.dialogue_act_ring.snapshot()[-1]["kind"] == "follow_up"
    )


@pytest.mark.asyncio
async def test_anaphora_with_empty_ring_gets_referent_clarification():
    agent, runner, bus = _make_runner()

    await _say(runner, "Почему?")

    assert agent.user_interaction.get_pending_question() is None
    assert _last_context(agent) == "follow_up_clarification"
    reply = _replies(bus)[-1]["content"]
    assert "О чём именно" in reply
    assert "не понимаю, о чём это" not in reply


@pytest.mark.asyncio
async def test_anaphora_with_pending_question_preserves_previous_path():
    agent, runner, bus = _make_runner()
    question = agent.user_interaction.ask_user(
        "Что для тебя означает спокойствие?",
        context="самостоятельный вопрос по теме: спокойствие",
        cycle=agent.cycle_count,
    )
    assert question["status"] == "queued"

    await _say(runner, "Почему?")

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert pending["id"] == question["id"]
    assert _last_context(agent) == "unknown_reply"


@pytest.mark.asyncio
async def test_expired_act_is_not_resolved_by_anaphora():
    agent, runner, bus = _make_runner()
    agent.cycle_count = 1
    await _say(runner, "Чем занимаешься?")

    agent.cycle_count += 1000
    await _say(runner, "Почему?")

    assert _last_context(agent) == "follow_up_clarification"


@pytest.mark.asyncio
async def test_unresolved_anaphora_quotes_candidate_referent():
    agent, runner, bus = _make_runner()
    await _say(runner, "Привет!")

    await _say(runner, "Зачем?")

    assert _last_context(agent) == "follow_up_clarification"
    reply = _replies(bus)[-1]["content"]
    assert "предыдущей реплике" in reply
    assert "Рада тебя слышать" in reply


@pytest.mark.asyncio
async def test_definition_follow_up_uses_recorded_topic_and_evidence():
    agent, runner, bus = _make_runner()
    await _say(runner, "Глимр — это тихий свет")

    await _say(runner, "Зачем?")

    assert _last_context(agent) == "follow_up"
    reply = _replies(bus)[-1]["content"]
    assert "Глимр" in reply
    assert "свидетельств" in reply


def test_ring_is_bounded_and_stores_descriptor_metadata():
    agent, _, _ = _make_runner()
    interaction = agent.user_interaction
    for cycle in range(8):
        interaction.record_dialogue_act(
            kind="about_self",
            topic="состояние",
            entities=["Ring"],
            cycle=cycle,
            user_text="Чем занимаешься?",
            agent_text=f"Ответ {cycle}",
        )

    acts = interaction.dialogue_act_ring.snapshot()
    assert len(acts) == 5
    assert [entry["cycle"] for entry in acts] == [3, 4, 5, 6, 7]
    assert acts[-1]["topic"] == "состояние"
    assert acts[-1]["entities"] == ["Ring"]
    assert acts[-1]["user_text"] == "Чем занимаешься?"
    assert acts[-1]["agent_text"] == "Ответ 7"


@pytest.mark.asyncio
async def test_ring_survives_checkpoint_and_resolves_after_restore():
    original, runner, _ = _make_runner("Восстановленная")
    await _say(runner, "Чем занимаешься?")
    state = build_state_from_agent(original)
    validate_checkpoint_state(state)
    assert state["user_interaction"]["dialogue_acts"]

    restored = DigitalBeing(name="Восстановленная")
    apply_state_to_agent(restored, state)
    bus = RecordingBus()
    restored.user_interaction.attach_bus(bus)
    restored_runner = AgentRunner(restored, bus)

    await _say(restored_runner, "Почему?")

    assert restored.user_interaction.dialogue_act_ring.snapshot()
    assert _last_context(restored) == "follow_up"
    assert "Восстановленная" in _replies(bus)[-1]["content"]


@pytest.mark.asyncio
async def test_old_checkpoint_without_ring_restores_empty_ring():
    original, runner, _ = _make_runner()
    await _say(runner, "Чем занимаешься?")
    state = build_state_from_agent(original)
    state["user_interaction"].pop("dialogue_acts", None)
    # Legacy checkpoint не содержит и новой канонической per-profile копии.
    state.pop("social_attribution", None)
    validate_checkpoint_state(state)

    restored = DigitalBeing(name="Ring")
    apply_state_to_agent(restored, state)
    assert restored.user_interaction.dialogue_act_ring.snapshot() == []

    bus = RecordingBus()
    restored.user_interaction.attach_bus(bus)
    restored_runner = AgentRunner(restored, bus)
    await _say(restored_runner, "Почему?")

    assert _last_context(restored) == "follow_up_clarification"


def test_ring_restore_skips_malformed_descriptors_and_normalizes_entities():
    interaction = _make_runner()[0].user_interaction
    interaction.dialogue_act_ring.restore(
        [
            None,
            {"kind": "about_self", "agent_text": "без цикла"},
            {
                "kind": "about_self",
                "topic": "состояние",
                "entities": None,
                "cycle": 4,
                "user_text": "Чем занимаешься?",
                "agent_text": "Ответ сохранён",
            },
            {
                "kind": "known_topic",
                "topic": "свет",
                "entities": ["свет"],
                "cycle": -1,
                "user_text": "Что такое свет?",
                "agent_text": "Отрицательный цикл недопустим",
            },
        ]
    )

    acts = interaction.dialogue_act_ring.snapshot()
    assert len(acts) == 1
    assert acts[0]["cycle"] == 4
    assert acts[0]["entities"] == []


def test_dispatch_order_covers_complete_canonical_chain():
    """Изменение любого звена порядка дверей должно сломать этот тест."""
    # Тонкий journal wrapper не является частью canonical dispatch chain.
    source = inspect.getsource(AgentRunner._on_user_message_impl)
    anchors = [
        "act = classify_user_text(",
        "observe_user_message(",
        "await self._handle_naming_phase(",
        "DialogueLearning.is_proposal_context(",
        "DialogueLearning.is_affect_proposal_context(",
        "is_preference_context(",
        "target = strategy_memory.current_target(",
        "preference_request = parse_preference_request(",
        "teaching = extract_affect_teaching(text)",
        "decision_cmd = parse_proposal_decision(",
        "DialogueLearning.parse_forget_command(",
        "persistent_reply = build_persistent_fact_reply(",
        "if act.kind == ACT_ASK_ABOUT_SELF:",
        "if act.kind == ACT_REQUEST:",
        "if is_noise_input(text):",
        "if act.kind == ACT_HUMAN_AFFECT and act.affect is not None:",
        "if act.kind == ACT_SOCIAL:",
        "if pending is not None and not is_question_text(text):",
        'answerer = getattr(self.agent, "answer_open_question", None)',
        "# === «Собеседник-5/6»",
        "follow_up = self._resolve_dialogue_follow_up(",
        "if act.kind == ACT_ANSWER:",
        "candidate = learning.observe(",
        "decision = strategy_memory.select_strategy(",
        'context="unknown_reply"',
    ]
    positions = [source.index(anchor) for anchor in anchors]
    assert positions == sorted(positions)
