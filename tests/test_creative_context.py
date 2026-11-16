"""Творческий снимок объясняет текст и не ограничивает срок работы."""

from copy import deepcopy
import hashlib
import json

from src.core.activity_workspace import ActivityWorkspace
from src.core.agent import DigitalBeing
from src.cognition.creative_context import (
    build_creative_context,
    fallback_creative_context,
)
from src.cognition.creative_draft import compose_line, draft_step, validate_draft


def _memory(content="Старый опыт о дороге", context=None):
    context = {"source": "test"} if context is None else context
    provenance = json.dumps(
        {"content": content, "context": context},
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )
    return {
        "content": content,
        "context": context,
        "importance": 0.8,
        "strength": 0.9,
        "relevance": 0.7,
        "sha256": hashlib.sha256(provenance.encode("utf-8")).hexdigest(),
    }


def _emotion(name="joy", valence=0.8, arousal=0.6):
    return {
        "emotion": name,
        "level": 0.4,
        "cause": "test",
        "valence": valence,
        "arousal": arousal,
        "weight": 1.0,
    }


def test_snapshot_contains_only_real_available_sources():
    agent = DigitalBeing(name="CreativeContextSources")
    agent.cycle_count = 12
    agent.active_goal = {"id": 7, "title": "Понять дорогу"}
    agent.emotional_state.handle_event(
        "intention_completed", cycle=11, cause="завершённый поиск"
    )
    agent._open_questions = [
        {
            "source": "self",
            "explorations": [
                {
                    "cycle": 10,
                    "thought": "Дорога сохраняет направление",
                    "strategy": "reflection",
                }
            ],
        }
    ]

    class Memory:
        def recall(self, query, threshold, max_results):
            assert "дорога" in query.lower()
            assert threshold == 0.1
            assert max_results == 5
            return [_memory()]

    agent.long_term_memory = Memory()
    context = build_creative_context(agent, theme="дорога")

    assert context["schema_version"] == 1
    assert context["cycle"] == 12
    assert context["goal"] == {"id": 7, "title": "Понять дорогу"}
    assert context["emotions"][0]["emotion"] == "joy"
    assert context["emotions"][0]["cause"] == "завершённый поиск"
    assert context["memories"][0]["content"] == "Старый опыт о дороге"
    assert context["thoughts"] == [
        {
            "text": "Дорога сохраняет направление",
            "cycle": 10,
            "source": "self",
            "strategy": "reflection",
        }
    ]
    json.dumps(context, allow_nan=False)


def test_same_context_is_reproducible_and_each_material_changes_text():
    base = fallback_creative_context("дорога")
    base["emotions"] = [_emotion()]
    base["memories"] = [_memory()]
    base["thoughts"] = [{"text": "Нужно продолжить путь", "cycle": 4, "source": "self"}]

    assert compose_line(base, 3) == compose_line(deepcopy(base), 3)

    sad = deepcopy(base)
    sad["emotions"] = [_emotion("sadness", -0.7, 0.3)]
    assert compose_line(sad, 3) != compose_line(base, 3)

    other_memory = deepcopy(base)
    other_memory["memories"] = [_memory("Другой сохранённый эпизод")]
    assert "Другой сохранённый эпизод" in compose_line(other_memory, 3)

    other_thought = deepcopy(base)
    other_thought["memories"] = []
    other_thought["thoughts"] = [
        {"text": "Другая реальная мысль", "cycle": 5, "source": "self"}
    ]
    assert "Другая реальная мысль" in compose_line(other_thought, 3)


def test_empty_sources_do_not_invent_material():
    context = fallback_creative_context("тишина")
    line = compose_line(context)
    assert "Тишина" in line
    assert "память:" not in line
    assert "мысль:" not in line


def test_revision_nine_and_later_keep_same_work_open():
    agent = DigitalBeing(name="CreativeLongWork")
    agent.act("create_draft")
    identifier = agent._creative_draft["id"]
    origin = deepcopy(agent._creative_draft["origin_context"])

    for expected in range(2, 13):
        agent.act(
            "create_draft",
            intention={"params": {"draft_mode": "continue", "draft_id": identifier}},
        )
        assert agent._creative_draft["revision"] == expected

    assert agent._creative_draft["id"] == identifier
    assert agent._creative_draft["status"] == "active"
    assert agent._creative_draft["origin_context"] == origin
    assert agent._creative_draft["creative_context"] is not None


def test_file_quota_does_not_become_a_revision_limit(tmp_path):
    workspace = ActivityWorkspace(tmp_path)
    state = draft_step(workspace=workspace)

    for _ in range(149):
        state = draft_step(state, workspace=workspace)

    path = tmp_path / f"{state['id']}.txt"
    assert state["revision"] == 150
    assert state["status"] == "active"
    assert path.stat().st_size <= workspace.sandbox.max_file_bytes
    assert compose_line(state["creative_context"], 150) in path.read_text(
        encoding="utf-8"
    )


def test_legacy_draft_without_context_remains_valid(tmp_path):
    workspace = ActivityWorkspace(tmp_path)
    state = draft_step(workspace=workspace)
    state.pop("origin_context")
    state.pop("creative_context")
    validate_draft(state)

    updated = draft_step(state, workspace=workspace)

    assert updated["revision"] == 2
    assert "origin_context" not in updated
    assert updated["creative_context"]["theme"] == updated["theme"]
