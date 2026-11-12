"""Живые сценарии канонического эмоционального контура.

Используются реальные события EmotionalState и штатный сдвиг кандидатов
DigitalBeing; отдельного тестового эмоционального контура нет.
"""

from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.emotional_state import EMOTIONS, EmotionalState


class _Agent:
    ACTION_ALIASES = DigitalBeing.ACTION_ALIASES
    _normalize_action = DigitalBeing._normalize_action
    _apply_emotional_bias = DigitalBeing._apply_emotional_bias

    def __init__(self, state):
        self.emotional_state = state
        self.cycle_count = 0


def _components(state):
    return {c["emotion"]: c for c in state.mixture()["components"]}


def test_threat_and_support_remain_simultaneous_and_shape_existing_actions():
    state = EmotionalState()
    state.handle_event("abuse", cycle=1, cause="угроза")
    state.handle_event("abuse", cycle=2, cause="угроза")
    for cycle in range(3, 6):
        state.handle_event("user_contact", cycle=cycle, cause="поддержка")

    components = _components(state)
    assert components["fear"]["level"] == pytest.approx(0.9)
    assert components["joy"]["level"] == pytest.approx(0.75)
    assert components["fear"]["cause"] == "угроза"
    assert components["joy"]["cause"] == "поддержка"

    candidates = [
        {"action": "repair", "strength": 0.5},
        {"action": "create_draft", "strength": 0.5},
        {"action": "explore", "strength": 0.5},
    ]
    report = _Agent(state)._apply_emotional_bias(candidates)
    assert len(candidates) == 3
    assert {c["emotion"] for c in report["components"]} == {"fear", "joy"}
    by_action = {c["action"]: c["strength"] for c in candidates}
    assert by_action["repair"] > 0.5
    assert by_action["create_draft"] > 0.5
    assert by_action["explore"] < 0.5


def test_success_after_failures_does_not_erase_negative_history():
    state = EmotionalState()
    state.handle_event("goal_blocked", cycle=1, cause="блокировка")
    state.handle_event("goal_blocked", cycle=2, cause="блокировка")
    state.handle_event("intention_failed", cycle=3, cause="промах")
    state.handle_event("intention_completed", cycle=4, cause="успех")

    assert state.levels["frustration"] == pytest.approx(0.6)
    assert state.levels["sadness"] == pytest.approx(0.25)
    assert state.levels["joy"] == pytest.approx(0.4)
    assert set(_components(state)) == {"frustration", "joy"}
    assert state.last_causes["sadness"][1] == "промах"
    assert state.last_causes["joy"][1] == "успех"

    candidates = [
        {"action": "reflection", "strength": 0.5},
        {"action": "create_draft", "strength": 0.5},
    ]
    _Agent(state)._apply_emotional_bias(candidates)
    assert candidates[0]["strength"] > 0.5
    assert candidates[1]["strength"] > 0.5


def test_separation_mixture_decays_and_survives_restart():
    state = EmotionalState()
    for cycle in (1, 2):
        state.handle_event("long_silence", cycle=cycle, cause="тишина")
        state.handle_event("absent_attachment", cycle=cycle, cause="разлука")
    state.handle_event("prolonged_isolation", cycle=3, cause="изоляция")

    assert set(_components(state)) == {"sadness", "longing"}
    clone = EmotionalState()
    clone.load_from(state.to_dict())
    assert clone.mixture() == state.mixture()
    assert clone.last_causes == state.last_causes

    for cycle in range(4, 104):
        clone.tick(cycle)
    assert clone.levels["longing"] == pytest.approx(0.4)
    assert clone.levels["sadness"] == pytest.approx(0.2)
    assert clone.levels["loneliness"] == pytest.approx(0.1)
    assert set(_components(clone)) == {"longing"}


def test_boundary_violation_and_care_mix_without_hostile_action_creation():
    state = EmotionalState()
    state.handle_event("boundary_violated", cycle=1, cause="граница")
    state.handle_event("care_received", cycle=2, cause="забота")

    components = _components(state)
    assert set(components) == {"anger", "gratitude"}
    assert components["anger"]["cause"] == "граница"
    assert components["gratitude"]["cause"] == "забота"

    candidates = [{"action": "communicate", "strength": 0.5}]
    report = _Agent(state)._apply_emotional_bias(candidates)
    assert report["emotion"] == "anger"
    assert len(candidates) == 1
    assert candidates[0]["action"] == "communicate"
    assert candidates[0]["strength"] > 0.5


def test_zero_intensity_event_does_not_consume_cooldown():
    state = EmotionalState()
    assert state.handle_event("death_risk", cycle=1, scale=0.0) is None
    assert state._cooled_at == {}
    episode = state.handle_event("death_risk", cycle=2, scale=1.0)
    assert episode is not None
    assert state._cooled_at == {"death_risk": 2}


def test_corrupted_checkpoint_fields_are_filtered_instead_of_crashing():
    from src.core.checkpoint_validation import validate_checkpoint_state

    state = EmotionalState()
    state.load_from({
        "last_causes": {
            "joy": [None, "битый цикл"],
            "fear": ["12", "сохранённая причина"],
            "anger": [float("inf"), "битый цикл"],
        },
        "episodes": [
            {"emotion": "anger", "cycle": "8", "event": "boundary_violated",
             "intensity": 1.7},
            {"emotion": "joy", "cycle": "мусор", "intensity": 0.2},
            {"emotion": "fear", "cycle": 2, "intensity": float("nan")},
            {"emotion": "unknown", "cycle": 3, "intensity": 0.2},
            "мусор",
        ],
    })
    assert state.last_causes == {"fear": (12, "сохранённая причина")}
    assert len(state.episodes) == 1
    assert state.episodes[0]["emotion"] == "anger"
    assert state.episodes[0]["intensity"] == 1.0
    validate_checkpoint_state({"emotional_state": state.to_dict()})

    with pytest.raises(ValueError, match=r"episodes\[0\]\.intensity"):
        validate_checkpoint_state({"emotional_state": {
            "levels": {},
            "episodes": [{"emotion": "joy", "cycle": 1,
                          "intensity": float("inf")}],
        }})


def test_every_dominant_emotion_has_a_safe_art_projection(monkeypatch):
    from src.cognition import local_art

    used_palettes = []
    monkeypatch.setattr(local_art, "art_available", lambda state=None, workspace=None: True)

    def fake_step(work, *, palette, theme, richness, workspace=None):
        used_palettes.append(palette)
        return {"id": "test", "theme": theme, "palette": palette,
                "revision": 1, "status": "active"}

    monkeypatch.setattr(local_art, "art_step", fake_step)
    monkeypatch.setattr(local_art, "art_thumbnail", lambda work: "thumb")

    for emotion in EMOTIONS:
        state = EmotionalState()
        state.levels[emotion] = 1.0
        agent = SimpleNamespace(
            emotional_state=state,
            _art_work=None,
            _art_catalog={},
            _pick_art_theme=lambda: "свет",
            _art_richness=lambda: 5,
            _record_will=lambda *args: None,
        )
        result = DigitalBeing._act_draw(agent)
        assert "не получилось" not in result["text"]
        assert agent._art_work["palette"] in local_art.PALETTES

    assert len(used_palettes) == len(EMOTIONS)
    assert set(used_palettes) <= set(local_art.PALETTES)
