"""Сохраняем текущие ценности, журнал воли и отношения без новых переживаний."""

from copy import deepcopy
import math


def capture_personal_state(agent):
    result = {}
    registry = getattr(agent, "will_registry", None)
    if registry is not None:
        result["will_registry"] = deepcopy(registry.to_dict())
    values = getattr(agent, "value_evolution", None)
    if values is not None:
        result["values"] = list(values.current_values)
    refusal = getattr(agent, "right_to_refuse", None)
    if refusal is not None:
        result["recent_refusals"] = list(refusal._recent_refusals)
    attachment = getattr(agent, "attachment", None)
    if attachment is not None:
        result["attachments"] = {
            name: deepcopy(record.__dict__)
            for name, record in attachment._attachments.items()
        }
    soul = getattr(agent, "soul", None)
    identity = soul.get("self") if soul is not None else None
    if identity is not None:
        result["identity"] = deepcopy(identity.to_dict())
    return result


def validate_personal_state(data):
    def fail(path):
        raise ValueError(f"personal_state.{path}: недопустимое значение")

    if not isinstance(data, dict):
        fail("root")
    if "identity" in data:
        identity = data["identity"]
        if not isinstance(identity, dict) or not isinstance(identity.get("core_identity"), str):
            fail("identity.core_identity")
        for field in ("core_values", "history"):
            if not isinstance(identity.get(field), list) or any(not isinstance(item, str) for item in identity[field]):
                fail(f"identity.{field}")
        stability = identity.get("identity_stability_score")
        if isinstance(stability, bool) or not isinstance(stability, (int, float)) or not math.isfinite(stability) or not 0 <= stability <= 1:
            fail("identity.identity_stability_score")
    if "values" in data and (not isinstance(data["values"], list)
                             or any(not isinstance(value, str) for value in data["values"])):
        fail("values")
    if "recent_refusals" in data:
        if not isinstance(data["recent_refusals"], list):
            fail("recent_refusals")
        for cycle in data["recent_refusals"]:
            if type(cycle) is not int or cycle < 0:
                fail("recent_refusals")
    if "will_registry" in data:
        registry = data["will_registry"]
        if not isinstance(registry, dict):
            fail("will_registry")
        entries, counters = registry.get("entries", []), registry.get("counters", {})
        if not isinstance(entries, list) or not isinstance(counters, dict):
            fail("will_registry")
        for entry in entries:
            if not isinstance(entry, dict) or type(entry.get("cycle")) is not int or entry["cycle"] < 0:
                fail("will_registry.entries")
            for field in ("type", "topic", "reason", "outcome", "timestamp"):
                if not isinstance(entry.get(field), str):
                    fail(f"will_registry.entries.{field}")
            if not isinstance(entry.get("meta", {}), dict):
                fail("will_registry.entries.meta")
        for key, count in counters.items():
            if not isinstance(key, str) or type(count) is not int or count < 0:
                fail("will_registry.counters")
        last = registry.get("last_value_change_cycle", 0)
        if type(last) is not int or last < 0:
            fail("will_registry.last_value_change_cycle")
    if "attachments" in data:
        if not isinstance(data["attachments"], dict):
            fail("attachments")
        for name, record in data["attachments"].items():
            if not isinstance(name, str) or not isinstance(record, dict) or record.get("name") != name:
                fail("attachments.name")
            if record.get("kind") not in {"user", "source"}:
                fail("attachments.kind")
            for field in ("trust", "familiarity", "intimacy", "valence"):
                value = record.get(field)
                lower = -1 if field == "valence" else 0
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= 1:
                    fail(f"attachments.{field}")
            if type(record.get("interactions")) is not int or record["interactions"] < 0:
                fail("attachments.interactions")
            if not isinstance(record.get("history", []), list):
                fail("attachments.history")
            if record.get("last_interaction") is not None and not isinstance(record["last_interaction"], str):
                fail("attachments.last_interaction")


def restore_personal_state(agent, data):
    validate_personal_state(data)
    # Сохраняем сами экземпляры: адаптеры/модули держат общие ссылки на них.
    if "identity" in data:
        soul = getattr(agent, "soul", None)
        identity = soul.get("self") if soul is not None else None
        if identity is not None:
            saved = data["identity"]
            identity.core_identity = saved["core_identity"]
            identity.core_values = list(saved["core_values"])
            identity.identity_stability_score = saved["identity_stability_score"]
            identity.history = list(saved["history"])
            arbitrator = getattr(agent, "decision_arbitrator", None)
            if arbitrator is not None:
                arbitrator.attach_identity(identity)
    registry = getattr(agent, "will_registry", None)
    if "will_registry" in data and registry is not None:
        saved = data["will_registry"]
        registry.entries = deepcopy(saved.get("entries", []))
        registry._counters = {key: 0 for key in registry._counters} | dict(saved.get("counters", {}))
        registry._last_value_change_cycle = saved.get("last_value_change_cycle", 0)
    if "values" in data and getattr(agent, "value_evolution", None) is not None:
        agent.value_evolution.current_values = list(data["values"])
    if "recent_refusals" in data and getattr(agent, "right_to_refuse", None) is not None:
        agent.right_to_refuse._recent_refusals = list(data["recent_refusals"])
    attachment = getattr(agent, "attachment", None)
    if "attachments" in data and attachment is not None:
        from src.core.subsystems.attachment_system import Attachment

        restored = {}
        for name, record in data["attachments"].items():
            item = Attachment(name, record["kind"])
            item.__dict__.update(deepcopy(record))
            restored[name] = item
        attachment._attachments = restored
