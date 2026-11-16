"""Проверяемый снимок внутреннего материала для творческой работы.

Только чтение существующего состояния: ни новых мыслей, ни искусственных
эмоций, ни вымышленных воспоминаний. Снимок сериализуется в чекпоинт и
остаётся достаточным для объяснения содержания конкретной редакции.
"""

from copy import deepcopy
import hashlib
import json
import math


SCHEMA_VERSION = 1
MAX_MATERIAL_ITEMS = 5
DEFAULT_THEMES = ("тишина", "дорога", "свет", "ожидание")


def _text(value, limit=500):
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


def _number(value, default=0.0):
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _cycle(value):
    return value if type(value) is int and value >= 0 else 0


def _relevance(text, query):
    words = set(text.lower().split())
    query_words = set(query.lower().split())
    if not words or not query_words:
        return 0.0
    return len(words & query_words) / max(len(words | query_words), 1)


def _collect_thoughts(agent, query):
    thoughts = []
    questions = getattr(agent, "_open_questions", None) or []
    for question in questions:
        if not isinstance(question, dict):
            continue
        source = _text(question.get("source") or "open_question", 80)
        for exploration in question.get("explorations", []) or []:
            if not isinstance(exploration, dict):
                continue
            text = _text(exploration.get("thought"))
            if not text:
                continue
            strategy = _text(exploration.get("strategy"), 80)
            item = {
                "text": text,
                "cycle": _cycle(exploration.get("cycle")),
                "source": source,
            }
            if strategy:
                item["strategy"] = strategy
            thoughts.append((_relevance(text, query), item))
    thoughts.sort(
        key=lambda pair: (
            -pair[0],
            -pair[1]["cycle"],
            pair[1]["text"],
            pair[1]["source"],
            pair[1].get("strategy", ""),
        )
    )
    return [item for _, item in thoughts[:MAX_MATERIAL_ITEMS]]


def _collect_memories(agent, query):
    memory = getattr(agent, "long_term_memory", None)
    recall = getattr(memory, "recall", None)
    if not query or not callable(recall):
        return []
    try:
        found = recall(query, threshold=0.1, max_results=MAX_MATERIAL_ITEMS)
    except (TypeError, ValueError, OverflowError):
        return []
    memories = []
    for item in found or []:
        if not isinstance(item, dict):
            continue
        content = _text(item.get("content"))
        if not content:
            continue
        context = deepcopy(item.get("context"))
        try:
            provenance = json.dumps(
                {"content": content, "context": context},
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError, OverflowError):
            continue
        memories.append(
            {
                "content": content,
                "context": context,
                "importance": _number(item.get("importance")),
                "strength": _number(item.get("strength")),
                "relevance": _number(item.get("relevance")),
                "sha256": hashlib.sha256(provenance.encode("utf-8")).hexdigest(),
            }
        )
    return memories


def _collect_emotions(agent):
    emotional_state = getattr(agent, "emotional_state", None)
    mixture = getattr(emotional_state, "mixture", None)
    if not callable(mixture):
        return []
    result = []
    for item in mixture().get("components", []):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("emotion"), 80)
        if not name:
            continue
        result.append(
            {
                "emotion": name,
                "level": _number(item.get("level")),
                "cause": _text(item.get("cause"), 500),
                "valence": _number(item.get("valence")),
                "arousal": _number(item.get("arousal")),
                "weight": _number(item.get("weight")),
            }
        )
    return result


def build_creative_context(agent, theme=None):
    """Собрать снимок из фактически доступных состояния, памяти и мыслей."""
    cycle = _cycle(getattr(agent, "cycle_count", 0))
    requested_theme = _text(theme, 160)
    goal = getattr(agent, "active_goal", None)
    goal_view = None
    goal_title = ""
    if isinstance(goal, dict):
        goal_title = _text(goal.get("title"), 500)
        if goal_title:
            goal_id = goal.get("id")
            if type(goal_id) is not int and not isinstance(goal_id, str):
                goal_id = None
            goal_view = {"id": goal_id, "title": goal_title}

    query = requested_theme or goal_title
    thoughts = _collect_thoughts(agent, query)
    if not query and thoughts:
        query = thoughts[0]["text"]
    memories = _collect_memories(agent, query)

    selected_theme = requested_theme or goal_title
    if not selected_theme and thoughts:
        selected_theme = thoughts[0]["text"]
    if not selected_theme and memories:
        selected_theme = memories[0]["content"]
    if not selected_theme:
        seed = f"{getattr(agent, 'name', '')}|{cycle}".encode("utf-8")
        index = int.from_bytes(hashlib.sha256(seed).digest(), "big") % len(
            DEFAULT_THEMES
        )
        selected_theme = DEFAULT_THEMES[index]

    context = {
        "schema_version": SCHEMA_VERSION,
        "cycle": cycle,
        "theme": _text(selected_theme, 160),
        "goal": goal_view,
        "emotions": _collect_emotions(agent),
        "memories": memories,
        "thoughts": thoughts,
    }
    validate_creative_context(context)
    return context


def fallback_creative_context(theme="тишина"):
    """Пустой снимок для прямого низкоуровневого вызова без агента."""
    context = {
        "schema_version": SCHEMA_VERSION,
        "cycle": 0,
        "theme": _text(theme, 160) or "тишина",
        "goal": None,
        "emotions": [],
        "memories": [],
        "thoughts": [],
    }
    validate_creative_context(context)
    return context


def _validate_number(value, path, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(path)
    if not math.isfinite(value):
        raise ValueError(path)
    if minimum is not None and value < minimum:
        raise ValueError(path)
    if maximum is not None and value > maximum:
        raise ValueError(path)


def validate_creative_context(context):
    if not isinstance(context, dict) or context.get("schema_version") != 1:
        raise ValueError("creative_context.schema_version")
    if _cycle(context.get("cycle")) != context.get("cycle"):
        raise ValueError("creative_context.cycle")
    if not _text(context.get("theme"), 160):
        raise ValueError("creative_context.theme")
    goal = context.get("goal")
    if goal is not None:
        if not isinstance(goal, dict) or not _text(goal.get("title"), 500):
            raise ValueError("creative_context.goal")
        if goal.get("id") is not None and (
            type(goal.get("id")) is not int and not isinstance(goal.get("id"), str)
        ):
            raise ValueError("creative_context.goal.id")
    for field in ("emotions", "memories", "thoughts"):
        if not isinstance(context.get(field), list):
            raise ValueError(f"creative_context.{field}")
        if len(context[field]) > MAX_MATERIAL_ITEMS and field != "emotions":
            raise ValueError(f"creative_context.{field}")
    for item in context["emotions"]:
        if not isinstance(item, dict) or not isinstance(item.get("emotion"), str):
            raise ValueError("creative_context.emotions")
        if not isinstance(item.get("cause"), str):
            raise ValueError("creative_context.emotions.cause")
        for field in ("level", "arousal", "weight"):
            _validate_number(
                item.get(field),
                f"creative_context.emotions.{field}",
                minimum=0.0,
                maximum=1.0,
            )
        _validate_number(
            item.get("valence"),
            "creative_context.emotions.valence",
            minimum=-1.0,
            maximum=1.0,
        )
    for item in context["memories"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("content"), str)
            or not item["content"]
        ):
            raise ValueError("creative_context.memories.content")
        digest = item.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise ValueError("creative_context.memories.sha256")
        for field in ("importance", "strength", "relevance"):
            _validate_number(item.get(field), f"creative_context.memories.{field}")
        try:
            json.dumps(item.get("context"), allow_nan=False)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("creative_context.memories.context") from exc
    for item in context["thoughts"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("text"), str)
            or not item["text"]
        ):
            raise ValueError("creative_context.thoughts.text")
        if _cycle(item.get("cycle")) != item.get("cycle"):
            raise ValueError("creative_context.thoughts.cycle")
        if not isinstance(item.get("source"), str):
            raise ValueError("creative_context.thoughts.source")
        if "strategy" in item and not isinstance(item["strategy"], str):
            raise ValueError("creative_context.thoughts.strategy")
