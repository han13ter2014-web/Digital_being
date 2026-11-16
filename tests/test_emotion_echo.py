"""P1 «Эхо эмоций»: диалог, обучение, checkpoint и проактивная забота."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.dialogue_acts import ACT_HUMAN_AFFECT, classify_user_text
from src.core.dialogue_learning import LEARNED_AFFECT_MAX, DialogueLearning
from src.core.dialogue_memory import DialogueActRing
from src.core.event_bus import Events
from src.core.human_affect import extract_static_human_affect
from src.core.subsystems.proactive_communication import ProactiveCommunication
from src.perception.user_interaction import UserInteraction


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _make_runner(name="Эхо"):
    agent = DigitalBeing(name=name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


def _replies(bus):
    return [data for name, data in bus.published if name == Events.AGENT_MESSAGE]


def _questions(bus):
    return [data for name, data in bus.published if name == Events.AGENT_QUESTION]


async def _say(runner, text):
    await runner._on_user_message(SimpleNamespace(data={"text": text}))


@pytest.mark.asyncio
async def test_joy_gets_echo_without_learning_question_or_permanent_trait():
    agent, runner, bus = _make_runner()
    traits_before = deepcopy(agent.user_model.traits)
    promises_before = deepcopy(agent.user_model.promises)

    await _say(runner, "Мне радостно")

    assert _replies(bus)[-1]["context"] == "emotion_echo"
    assert "Я слышу" in _replies(bus)[-1]["content"]
    assert agent.user_interaction.get_pending_question() is None
    assert agent.dialogue_learning.learned_affect == {}
    assert agent.dialogue_learning.buffer == {}
    affect = agent.user_interaction.last_human_affect
    assert affect["components"] == {"joy": 0.7}
    assert affect["evidence"] == "self_report"
    assert agent.user_model.traits == traits_before
    assert agent.user_model.promises == promises_before
    descriptor = agent.user_interaction.dialogue_act_ring.snapshot()[-1]
    assert descriptor["kind"] == "emotion_echo"
    assert descriptor["user_text"] == "Мне радостно"
    assert descriptor["affect"] == dict(affect, marker="радостно", shared_marker=False)


@pytest.mark.asyncio
async def test_mixed_report_has_mixed_echo_and_negative_memory():
    agent, runner, bus = _make_runner()
    await _say(runner, "Мне немного грустно, но я рад, что ты рядом")

    assert _replies(bus)[-1]["context"] == "emotion_echo_mixed"
    assert "грусти" in _replies(bus)[-1]["content"]
    assert "радости" in _replies(bus)[-1]["content"]
    assert agent.user_interaction.last_human_affect["components"] == {
        "sadness": 0.35,
        "joy": 0.7,
    }


@pytest.mark.asyncio
async def test_affect_does_not_answer_or_close_pending_question():
    agent, runner, bus = _make_runner()
    asked = agent.user_interaction.ask_user(
        "Что для тебя означает спокойствие?",
        context="самостоятельный вопрос по теме: спокойствие",
        cycle=0,
    )
    assert asked["status"] == "queued"

    await _say(runner, "Мне грустно")

    pending = agent.user_interaction.get_pending_question()
    assert pending is not None and pending["id"] == asked["id"]
    assert agent.user_interaction.question_history == []
    assert _replies(bus)[-1]["context"] == "emotion_echo"
    assert "остаётся открытым" in _replies(bus)[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "previous_agent_text,previous_user_text,age,text,expected",
    [
        ("Мне радостно.", "", 1, "И мне радостно", "emotion_echo_shared"),
        ("Мне радостно.", "", 1, "Мне радостно", "emotion_echo"),
        ("Я записала новую связь.", "", 1, "И мне радостно", "emotion_echo"),
        ("Мне радостно.", "", 51, "И мне радостно", "emotion_echo"),
        ("Мне радостно.", "Привет", 1, "И мне радостно", "emotion_echo"),
    ],
)
async def test_shared_echo_requires_latest_matching_agent_act(
    previous_agent_text, previous_user_text, age, text, expected
):
    agent, runner, bus = _make_runner()
    agent.cycle_count = 100
    agent.user_interaction.record_dialogue_act(
        "about_self",
        cycle=100 - age,
        user_text=previous_user_text,
        agent_text=previous_agent_text,
    )

    await _say(runner, text)

    assert _replies(bus)[-1]["context"] == expected


@pytest.mark.asyncio
async def test_unrelated_latest_act_blocks_older_shared_match():
    agent, runner, bus = _make_runner()
    ring = agent.user_interaction.dialogue_act_ring
    ring.record("about_self", cycle=1, agent_text="Мне радостно.")
    ring.record("about_self", cycle=2, agent_text="Я записала новую связь.")
    agent.cycle_count = 3

    await _say(runner, "И мне радостно")

    assert _replies(bus)[-1]["context"] == "emotion_echo"


def test_fresh_acts_are_newest_first_bounded_and_attention_weighted():
    ring = DialogueActRing()
    for cycle in range(1, 6):
        ring.record("about_self", cycle=cycle, agent_text=f"Ответ {cycle}")

    fresh = ring.fresh_acts(5, limit=3)
    assert [entry["cycle"] for entry in fresh] == [5, 4, 3]
    assert [entry["attention"] for entry in fresh] == [1.0, 0.5, 0.25]
    assert ring.fresh_acts(106) == []
    assert ring.fresh_acts(5, limit=0) == []
    fresh[0]["agent_text"] = "изменено снаружи"
    assert ring.snapshot()[-1]["agent_text"] == "Ответ 5"


@pytest.mark.asyncio
async def test_explicit_teaching_needs_separate_confirmation_then_works():
    agent, runner, bus = _make_runner()
    await _say(runner, "Запомни: “на душе светло” — это радость")

    learning = agent.dialogue_learning
    assert learning.learned_affect == {}
    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert DialogueLearning.is_affect_proposal_context(pending["context"])
    assert "не безусловный факт" in _questions(bus)[-1]["question"]

    await _say(runner, "да")

    entry = learning.learned_affect["на душе светло"]
    assert entry["components"] == {"joy": 1.0}
    assert entry["evidence"] == "user_taught"
    assert "свидетельство" in _replies(bus)[-1]["content"]
    assert agent.user_interaction.get_pending_question() is None

    await _say(runner, "На душе светло!")
    assert _replies(bus)[-1]["context"] == "emotion_echo"
    assert agent.user_interaction.last_human_affect["evidence"] == "user_taught"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["нет", "не учи", "отмена"])
async def test_rejected_affect_teaching_is_suppressed(answer):
    agent, runner, _ = _make_runner()
    await _say(runner, "Запомни: “на душе светло” — это радость")
    await _say(runner, answer)

    learning = agent.dialogue_learning
    assert learning.learned_affect == {}
    assert "на душе светло" in learning.suppressed_affect
    assert agent.user_interaction.get_pending_question() is None


@pytest.mark.asyncio
async def test_unclear_affect_confirmation_changes_nothing():
    agent, runner, _ = _make_runner()
    await _say(runner, "Запомни: “на душе светло” — это радость")
    await _say(runner, "сложно сказать")

    assert agent.dialogue_learning.learned_affect == {}
    assert agent.dialogue_learning.suppressed_affect == {}


@pytest.mark.asyncio
async def test_old_learning_answer_does_not_become_affect_but_habit_redirects():
    agent, runner, _ = _make_runner()
    phrase = "на душе светло"
    await _say(runner, phrase)
    await _say(runner, "1")
    assert agent.dialogue_learning.learned_affect == {}

    agent.cycle_count += 1300  # cooldown вопроса и нового предложения
    other = "внутри тихий звон"
    await _say(runner, other)
    agent.cycle_count += 60  # новый вопрос после ответа разрешён
    await _say(runner, "Это я так говорю, когда мне радостно")
    pending = agent.user_interaction.get_pending_question()
    assert pending is not None
    assert DialogueLearning.is_affect_proposal_context(pending["context"])
    assert DialogueLearning.affect_from_context(pending["context"]) == (other, "joy")
    assert other not in agent.dialogue_learning.learned


@pytest.mark.asyncio
async def test_correction_requires_new_confirmation_and_forget_removes_both():
    agent, runner, _ = _make_runner()
    await _say(runner, "Запомни: “на душе светло” — это радость")
    await _say(runner, "да")

    agent.cycle_count += 60
    await _say(runner, "Запомни: “на душе светло” — это грусть")
    assert agent.dialogue_learning.learned_affect["на душе светло"]["components"] == {
        "joy": 1.0
    }
    await _say(runner, "подтверждаю")
    assert agent.dialogue_learning.learned_affect["на душе светло"]["components"] == {
        "sadness": 1.0
    }

    await _say(runner, "забудь фразу на душе светло")
    assert "на душе светло" not in agent.dialogue_learning.learned_affect
    assert "на душе светло" in agent.dialogue_learning.suppressed_affect


def test_affect_learning_limit_does_not_evict_and_bad_context_is_inert():
    learning = DialogueLearning()
    for index in range(LEARNED_AFFECT_MAX):
        learning.learned_affect[f"фраза {index}"] = {
            "components": {"joy": 1.0},
            "weight": 0.7,
            "evidence": "user_taught",
            "cycle": index,
        }
    before = deepcopy(learning.learned_affect)
    outcome = learning.resolve_affect("новая фраза", "joy", "да", 500)
    assert outcome["status"] == "limit"
    assert learning.learned_affect == before
    assert learning.resolve_affect("", "unknown", "нет")["status"] == "unclear"
    assert learning.suppressed_affect == {}
    updated = learning.resolve_affect("фраза 0", "sadness", "да", 501)
    assert updated["status"] == "learned"
    assert learning.learned_affect["фраза 0"]["components"] == {"sadness": 1.0}


@pytest.mark.asyncio
async def test_affect_and_learning_survive_checkpoint_roundtrip():
    original, runner, _ = _make_runner()
    original.cycle_count = 40
    await _say(runner, "Запомни: “на душе светло” — это радость")
    await _say(runner, "да")
    await _say(runner, "Мне грустно")

    state = build_state_from_agent(original)
    validate_checkpoint_state(state)
    restored = DigitalBeing(name="Восстановленная")
    apply_state_to_agent(restored, state)

    assert restored.user_interaction.last_human_affect["evidence"] == "self_report"
    assert restored.user_interaction.negative_affect_strength(40) > 0.0
    entry = restored.dialogue_learning.learned_affect["на душе светло"]
    assert entry["evidence"] == "user_taught"
    act = classify_user_text(
        "на душе светло",
        learned_affect=restored.dialogue_learning.affect_classifier_entries(),
        cycle=40,
    )
    assert act.kind == ACT_HUMAN_AFFECT
    ring_entry = restored.user_interaction.dialogue_act_ring.snapshot()[-1]
    assert ring_entry["affect"]["components"] == {"sadness": 0.7}


def test_old_checkpoint_and_direct_corrupt_restore_use_safe_defaults():
    original = DigitalBeing(name="Старый")
    state = build_state_from_agent(original)
    state["user_interaction"].pop("last_human_affect")
    state["dialogue_learning"].pop("learned_affect")
    state["dialogue_learning"].pop("suppressed_affect")
    validate_checkpoint_state(state)
    restored = DigitalBeing(name="Старый")
    apply_state_to_agent(restored, state)
    assert restored.user_interaction.last_human_affect is None
    assert restored.dialogue_learning.learned_affect == {}

    restored.user_interaction.restore_from_checkpoint(
        {"last_human_affect": {"components": {"joy": float("nan")}}}
    )
    assert restored.user_interaction.last_human_affect is None
    restored.dialogue_learning.load_from(
        {
            "learned_affect": {
                "bad": {
                    "components": {"joy": 1.0},
                    "weight": 10**1000,
                    "evidence": "user_taught",
                    "cycle": 1,
                }
            },
            "suppressed_affect": {"nan": float("nan"), "ok": 4, "negative": -1},
        }
    )
    assert restored.dialogue_learning.learned_affect == {}
    assert restored.dialogue_learning.suppressed_affect == {"ok": 4}


@pytest.mark.parametrize(
    "state,path",
    [
        (
            {
                "user_interaction": {
                    "last_human_affect": {
                        "components": {"joy": 0.7},
                        "evidence": "self_report",
                        "testimony_weight": float("nan"),
                        "cycle": 1,
                    }
                }
            },
            "user_interaction.last_human_affect.testimony_weight",
        ),
        (
            {
                "dialogue_learning": {
                    "learned_affect": {
                        "фраза": {
                            "components": {"unknown": 1.0},
                            "weight": 0.7,
                            "evidence": "user_taught",
                            "cycle": 1,
                        }
                    }
                }
            },
            "dialogue_learning.learned_affect.фраза.components.unknown",
        ),
        (
            {
                "user_interaction": {
                    "dialogue_acts": [
                        {
                            "kind": "emotion_echo",
                            "topic": "",
                            "entities": [],
                            "cycle": 1,
                            "user_text": "Мне радостно",
                            "agent_text": "Я слышу",
                            "affect": {
                                "components": {"joy": 0.7},
                                "evidence": "self_report",
                                "testimony_weight": 0.5,
                                "cycle": 1,
                                "shared_marker": False,
                            },
                        }
                    ]
                }
            },
            "user_interaction.dialogue_acts[0].affect.marker",
        ),
    ],
)
def test_validation_rejects_bad_affect_with_exact_path(state, path):
    with pytest.raises(ValueError) as error:
        validate_checkpoint_state(state)
    assert path in str(error.value)


class _SilentUserModel:
    @staticmethod
    def has_silence_tolerance():
        return True


def _proactive_setup(affect=None, affect_cycle=0):
    interaction = UserInteraction()
    interaction._last_user_message_cycle = 0
    if affect is not None:
        interaction.set_human_affect(
            extract_static_human_affect(affect, cycle=affect_cycle)
        )
    agent = SimpleNamespace(
        user_interaction=interaction,
        user_model=_SilentUserModel(),
        presence=None,
        emotional_state=None,
        mind_dream=SimpleNamespace(state="awake"),
        self_termination=SimpleNamespace(_suffering_score=0.0),
    )
    communication = ProactiveCommunication(user_interaction=interaction)
    return agent, communication


def test_proactive_negative_affect_replaces_allowed_message_without_question():
    agent, communication = _proactive_setup("Мне грустно", affect_cycle=90)
    msg = communication.maybe_initiate(agent, cycle=100)
    assert msg is not None
    assert msg["msg_type"] == "care"
    assert msg["tone"] == "cautious"
    assert msg["context"] == "human_negative_affect"
    assert "?" not in msg["content"]
    assert "отвечать не обязательно" in msg["content"]


def test_affect_alone_does_not_initiate_and_expired_record_restores_baseline():
    agent, communication = _proactive_setup("Мне грустно", affect_cycle=90)
    communication._last_proactive_cycle = 100
    assert communication.maybe_initiate(agent, cycle=100) is None

    agent, communication = _proactive_setup("Мне грустно", affect_cycle=0)
    msg = communication.maybe_initiate(agent, cycle=100)
    assert msg is not None
    assert msg["context"] == "silence_with_promise"
