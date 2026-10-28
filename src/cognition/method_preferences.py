"""Мягкая история способов: опыт меняет тягу, не превращаясь в запрет."""

from copy import deepcopy

LIMIT = 100


def _key(action):
    return str(action or "").strip().lower()


def observe(agent, action, *, outcome="performed", had_effect=False, emotional_valence=0.0):
    key = _key(action)
    if not key:
        return
    history = getattr(agent, "_method_preferences", None)
    if history is None:
        history = agent._method_preferences = {}
    entry = history.setdefault(key, {"attempts": 0, "effects": 0, "failures": 0, "leaves": 0, "valence_sum": 0.0})
    entry.setdefault("valence_sum", 0.0)
    if isinstance(emotional_valence, (int, float)) and not isinstance(emotional_valence, bool):
        entry["valence_sum"] += max(-1.0, min(1.0, float(emotional_valence)))
    entry["attempts"] += 1
    if had_effect:
        entry["effects"] += 1
    if outcome in {"error", "denied"}:
        entry["failures"] += 1
    if outcome == "left":
        entry["leaves"] += 1
    if len(history) > LIMIT:
        oldest = next(iter(history))
        if oldest != key:
            del history[oldest]


def strength(agent, action):
    entry = getattr(agent, "_method_preferences", {}).get(_key(action))
    if not entry or not entry["attempts"]:
        return 1.0
    # Мягкое влияние: результативность меняет силу максимум в пределах 0.5..1.2.
    rate = entry["effects"] / entry["attempts"]
    penalty = min(0.35, entry["failures"] * 0.1 + entry["leaves"] * 0.04)
    return max(0.5, min(1.2, 0.7 + 0.5 * rate - penalty))


def apply(agent, candidates):
    result = []
    for candidate in candidates:
        item = dict(candidate)
        item["strength"] = float(item.get("strength", 0.5)) * strength(agent, item.get("action"))
        result.append(item)
    return result


def validate(history):
    if not isinstance(history, dict) or len(history) > LIMIT:
        raise ValueError("method_preferences")
    for action, entry in history.items():
        if not isinstance(action, str) or not isinstance(entry, dict):
            raise ValueError("method_preferences.entry")
        for field in ("attempts", "effects", "failures", "leaves"):
            if type(entry.get(field)) is not int or entry[field] < 0:
                raise ValueError(f"method_preferences.{field}")
        valence = entry.get("valence_sum", 0.0)
        if not isinstance(valence, (int, float)) or isinstance(valence, bool) or not -entry["attempts"] <= valence <= entry["attempts"]:
            raise ValueError("method_preferences.valence_sum")
        if entry["effects"] > entry["attempts"] or entry["failures"] > entry["attempts"]:
            raise ValueError("method_preferences.counts")
