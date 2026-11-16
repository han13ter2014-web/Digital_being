"""P2, этап 1: память стратегий без изменения диалогового маршрута."""

from copy import deepcopy

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.dialogue_learning import DialogueLearning
from src.core.dialogue_strategies import (
    FEEDBACK_TARGET_TTL_CYCLES,
    RECENT_RESPONSE_IDS_MAX,
    STRATEGY_OUTCOME_HALF_LIFE_CYCLES,
    DialogueStrategyMemory,
)


def _record(memory, response_id, feedback="opposition", cycle=10, weight=1.0):
    memory.register_response(response_id, "learning_question", "unknown", cycle - 1)
    return memory.apply_feedback(response_id, feedback, cycle, testimony_weight=weight)


def test_response_target_is_whitelisted_fresh_and_independent():
    memory = DialogueStrategyMemory()
    registered = memory.register_response(
        "question:1", "learning_question", "unknown", 10
    )
    registered["strategy_id"] = "changed"
    target = memory.current_target(10 + FEEDBACK_TARGET_TTL_CYCLES)
    assert target == {
        "response_id": "question:1",
        "strategy_id": "learning_question",
        "context_key": "unknown",
        "cycle": 10,
    }
    target["response_id"] = "changed"
    assert memory.feedback_target["response_id"] == "question:1"
    assert memory.current_target(11 + FEEDBACK_TARGET_TTL_CYCLES) is None
    assert memory.feedback_target is None


@pytest.mark.parametrize(
    "response_id,strategy,context,cycle",
    [
        ("", "learning_question", "unknown", 1),
        ("q1", "missing", "unknown", 1),
        ("q1", "learning_question", "social", 1),
        ("q1", "unknown_listen", "unknown", True),
        ("q1", "unknown_listen", "unknown", -1),
    ],
)
def test_invalid_response_registration_is_rejected(
    response_id, strategy, context, cycle
):
    memory = DialogueStrategyMemory()
    with pytest.raises(ValueError):
        memory.register_response(response_id, strategy, context, cycle)
    assert memory.feedback_target is None


def test_feedback_requires_matching_immediate_target():
    memory = DialogueStrategyMemory()
    assert memory.apply_feedback("q1", "support", 10)["reason"] == "no_target"

    memory.register_response("q1", "learning_question", "unknown", 9)
    assert memory.apply_feedback("other", "support", 10)["reason"] == "target_mismatch"
    assert memory.feedback_target is None
    assert memory.outcomes == {}

    memory.register_response("q2", "learning_question", "unknown", 9)
    assert memory.apply_feedback("q2", "perhaps", 10)["reason"] == "unknown_feedback"
    assert memory.outcomes == {}


def test_feedback_is_weighted_recorded_once_and_clears_target():
    memory = DialogueStrategyMemory()
    result = _record(memory, "q1", "opposition", cycle=10, weight=0.65)
    assert result == {
        "status": "recorded",
        "response_id": "q1",
        "context_key": "unknown",
        "strategy_id": "learning_question",
        "feedback": "opposition",
        "weight": 0.65,
    }
    assert memory.feedback_target is None
    signal = memory.signal_at("unknown", "learning_question", 10)
    assert signal["opposition"] == pytest.approx(0.65)
    assert signal["response_count"] == 1

    # Повторная регистрация того же ответа не создаёт второе наблюдение.
    duplicate = _record(memory, "q1", "opposition", cycle=10, weight=1.0)
    assert duplicate["status"] == "duplicate"
    assert memory.signal_at("unknown", "learning_question", 10)["response_count"] == 1


@pytest.mark.parametrize("weight", [0.0, 1.1, True, float("nan"), float("inf")])
def test_invalid_feedback_weight_is_rejected(weight):
    memory = DialogueStrategyMemory()
    memory.register_response("q1", "learning_question", "unknown", 9)
    with pytest.raises(ValueError):
        memory.apply_feedback("q1", "support", 10, testimony_weight=weight)
    assert memory.outcomes == {}


def test_recent_ids_are_bounded_without_inflating_unique_count():
    memory = DialogueStrategyMemory()
    for index in range(RECENT_RESPONSE_IDS_MAX + 1):
        _record(memory, f"q{index}", cycle=10)
    entry = memory.outcomes["unknown"]["learning_question"]
    assert entry["response_count"] == RECENT_RESPONSE_IDS_MAX + 1
    assert len(entry["recent_response_ids"]) == RECENT_RESPONSE_IDS_MAX
    assert entry["recent_response_ids"][0] == "q1"
    assert entry["recent_response_ids"][-1] == f"q{RECENT_RESPONSE_IDS_MAX}"


def test_signal_decays_without_mutating_saved_outcome():
    memory = DialogueStrategyMemory()
    _record(memory, "q1", "opposition", cycle=100, weight=1.0)
    before = deepcopy(memory.to_dict())
    signal = memory.signal_at(
        "unknown",
        "learning_question",
        100 + STRATEGY_OUTCOME_HALF_LIFE_CYCLES,
    )
    assert signal["opposition"] == pytest.approx(0.5)
    assert signal["difference"] == pytest.approx(0.5)
    assert memory.to_dict() == before


def test_support_reduces_active_opposition_without_erasing_history():
    memory = DialogueStrategyMemory()
    _record(memory, "q1", "opposition", cycle=10, weight=0.8)
    _record(memory, "q2", "support", cycle=10, weight=0.3)
    signal = memory.signal_at("unknown", "learning_question", 10)
    assert signal["support"] == pytest.approx(0.3)
    assert signal["opposition"] == pytest.approx(0.8)
    assert signal["difference"] == pytest.approx(0.5)
    assert signal["response_count"] == 2


def test_scoped_preference_requires_confirmation_caller_and_valid_pair():
    memory = DialogueStrategyMemory()
    preference = memory.set_preference("unknown", "unknown_listen", 20)
    assert preference == {
        "strategy": "unknown_listen",
        "evidence": "user_taught",
        "cycle": 20,
    }
    assert memory.preference_for("unknown") == preference
    assert memory.preference_for("social") is None
    with pytest.raises(ValueError):
        memory.set_preference("unknown", "missing", 20)
    assert memory.clear_preference("unknown") is True
    assert memory.clear_preference("unknown") is False


def test_snapshot_is_deeply_independent():
    memory = DialogueStrategyMemory()
    _record(memory, "q1", cycle=10)
    memory.set_preference("unknown", "unknown_listen", 11)
    memory.register_response("q2", "unknown_listen", "unknown", 12)
    snapshot = memory.to_dict()
    snapshot["outcomes"]["unknown"]["learning_question"]["recent_response_ids"].append(
        "fake"
    )
    snapshot["preferences"]["unknown"]["strategy"] = "learning_question"
    snapshot["feedback_target"]["response_id"] = "fake"
    assert memory.outcomes["unknown"]["learning_question"]["recent_response_ids"] == [
        "q1"
    ]
    assert memory.preference_for("unknown")["strategy"] == "unknown_listen"
    assert memory.feedback_target["response_id"] == "q2"


def test_defensive_restore_keeps_only_valid_whitelist_records():
    memory = DialogueStrategyMemory()
    memory.load_from(
        {
            "outcomes": {
                "unknown": {
                    "learning_question": {
                        "support": 0.0,
                        "opposition": 0.7,
                        "response_count": 1,
                        "last_cycle": 5,
                        "recent_response_ids": ["q1"],
                    },
                    "missing": {},
                    "bad": {
                        "support": float("nan"),
                        "opposition": 0.0,
                        "response_count": 0,
                        "last_cycle": 0,
                        "recent_response_ids": [],
                    },
                },
                "social": {"learning_question": {}},
            },
            "preferences": {
                "unknown": {
                    "strategy": "unknown_listen",
                    "evidence": "user_taught",
                    "cycle": 6,
                },
                "social": {
                    "strategy": "unknown_listen",
                    "evidence": "user_taught",
                    "cycle": 6,
                },
            },
            "feedback_target": {
                "response_id": "q2",
                "strategy_id": "unknown",
                "context_key": "unknown",
                "cycle": 7,
            },
        }
    )
    assert list(memory.outcomes) == ["unknown"]
    assert list(memory.outcomes["unknown"]) == ["learning_question"]
    assert memory.preference_for("unknown")["strategy"] == "unknown_listen"
    assert memory.feedback_target is None


def test_old_dialogue_learning_snapshot_resets_strategy_memory():
    learning = DialogueLearning()
    learning.strategy_memory.set_preference("unknown", "unknown_listen", 10)
    learning.load_from({})
    assert learning.strategy_memory.to_dict() == {
        "outcomes": {},
        "preferences": {},
        "feedback_target": None,
    }


def test_strategy_memory_survives_full_checkpoint_without_side_effects():
    original = DigitalBeing(name="Стратегии")
    _record(original.dialogue_learning.strategy_memory, "q1", cycle=10, weight=0.7)
    original.dialogue_learning.strategy_memory.set_preference(
        "unknown", "unknown_listen", 11
    )
    original.dialogue_learning.strategy_memory.register_response(
        "q2", "unknown_listen", "unknown", 12
    )
    traits_before = deepcopy(original.user_model.traits)
    methods_before = deepcopy(getattr(original, "_method_preferences", {}))

    state = build_state_from_agent(original)
    validate_checkpoint_state(state)
    restored = DigitalBeing(name="Восстановленная")
    apply_state_to_agent(restored, state)

    memory = restored.dialogue_learning.strategy_memory
    assert memory.signal_at("unknown", "learning_question", 12)[
        "opposition"
    ] == pytest.approx(0.7 * 0.5 ** (2 / STRATEGY_OUTCOME_HALF_LIFE_CYCLES))
    assert memory.preference_for("unknown")["strategy"] == "unknown_listen"
    assert memory.current_target(12)["response_id"] == "q2"
    assert restored.user_model.traits == traits_before
    assert getattr(restored, "_method_preferences", {}) == methods_before


def test_old_full_checkpoint_clears_previous_strategy_state():
    original = DigitalBeing(name="Старый")
    state = build_state_from_agent(original)
    state["dialogue_learning"].pop("dialogue_strategies")
    validate_checkpoint_state(state)

    restored = DigitalBeing(name="Старый")
    restored.dialogue_learning.strategy_memory.set_preference(
        "unknown", "unknown_listen", 1
    )
    apply_state_to_agent(restored, state)
    assert restored.dialogue_learning.strategy_memory.preferences == {}


def _valid_strategy_state():
    return {
        "outcomes": {
            "unknown": {
                "learning_question": {
                    "support": 0.0,
                    "opposition": 0.7,
                    "response_count": 1,
                    "last_cycle": 5,
                    "recent_response_ids": ["q1"],
                }
            }
        },
        "preferences": {
            "unknown": {
                "strategy": "unknown_listen",
                "evidence": "user_taught",
                "cycle": 6,
            }
        },
        "feedback_target": {
            "response_id": "q2",
            "strategy_id": "unknown_listen",
            "context_key": "unknown",
            "cycle": 7,
        },
    }


@pytest.mark.parametrize(
    "mutate,path",
    [
        (
            lambda state: state["feedback_target"].update(strategy_id="missing"),
            "dialogue_learning.dialogue_strategies.feedback_target.strategy_id",
        ),
        (
            lambda state: state["outcomes"]["unknown"]["learning_question"].update(
                support=float("nan")
            ),
            "dialogue_learning.dialogue_strategies.outcomes.unknown.learning_question.support",
        ),
        (
            lambda state: state["preferences"]["unknown"].update(evidence="fact"),
            "dialogue_learning.dialogue_strategies.preferences.unknown.evidence",
        ),
        (
            lambda state: state["outcomes"]["unknown"]["learning_question"].update(
                recent_response_ids=[{}]
            ),
            "dialogue_learning.dialogue_strategies.outcomes.unknown.learning_question.recent_response_ids[0]",
        ),
        (
            lambda state: state["outcomes"]["unknown"]["learning_question"].update(
                response_count=True
            ),
            "dialogue_learning.dialogue_strategies.outcomes.unknown.learning_question.response_count",
        ),
        (
            lambda state: state["outcomes"]["unknown"]["learning_question"].update(
                recent_response_ids=["q1", "q1"]
            ),
            "dialogue_learning.dialogue_strategies.outcomes.unknown.learning_question.recent_response_ids",
        ),
    ],
)
def test_validation_rejects_bad_strategy_state_with_exact_path(mutate, path):
    strategies = _valid_strategy_state()
    mutate(strategies)
    with pytest.raises(ValueError) as error:
        validate_checkpoint_state(
            {"dialogue_learning": {"dialogue_strategies": strategies}}
        )
    assert path in str(error.value)
