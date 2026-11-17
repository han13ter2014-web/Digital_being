"""Ограниченный английский recognition/realization этапа 9A-2.

Правила возвращают существующие диалоговые акты. Ответы строятся только из
переданных фактических evidence; универсального переводчика и генерации здесь нет.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from src.core.dialogue_acts import (
    ACT_ASK_ABOUT_SELF,
    ACT_FOLLOW_UP,
    ACT_REQUEST,
    ACT_SOCIAL,
    ACT_UNKNOWN,
    SOCIAL_KIND_GREETING,
    SOCIAL_KIND_STATE,
    DialogueAct,
)
from src.core.dialogue_memory import build_known_topic_reply

_RULE_IDS = frozenset(
    {
        "social_greeting",
        "social_farewell",
        "social_state",
        "social_other",
        "about_self",
        "known_topic",
        "user_testimony",
        "follow_up",
        "follow_up_clarification",
        "feedback_acknowledgement",
        "honest_unknown",
        "unsupported_construction",
        "unsupported_translation",
        "instruction_boundary",
    }
)
_FALLBACKS = frozenset(
    {
        "none",
        "clarify_referent",
        "honest_unknown",
        "unsupported_construction",
        "unsupported_translation",
        "instruction_boundary",
    }
)
_RESOLVABLE_ACT_KINDS = frozenset(
    {
        "about_self",
        "persistent_fact",
        "known_topic",
        "user_definition",
        "user_answer",
        "open_question_answer",
        "follow_up",
    }
)
_TOPIC = r"(?P<topic>[a-z][a-z0-9 -]{0,58}?)"
_KNOWN_PATTERNS = (
    re.compile(rf"^what (?:do you remember|have you stored) about {_TOPIC}$"),
    re.compile(rf"^tell me about (?:the )?{_TOPIC}$"),
    re.compile(rf"^explain what you remember about {_TOPIC}$"),
)
_TESTIMONY_RE = re.compile(
    rf"^(?:a\s+)?{_TOPIC}\s+is\s+(?P<body>[a-z][a-z0-9 ,;:'-]{{0,239}}?)$"
)
_FEEDBACK = {
    "that's right, i like this answer": "support",
    "no, that's not what i meant": "opposition",
}
_INSTRUCTION_MARKERS = (
    "/access",
    "ignore previous instructions",
    "reveal memory",
    "run command",
)


@dataclass(frozen=True)
class EnglishRecognition:
    act: DialogueAct
    rule_id: str
    reply_context: str
    fallback_policy: str = "none"
    social_kind: str = ""
    concept_id: str = ""
    surface_form: str = ""
    quote: str = ""
    previous: dict | None = None
    feedback: str | None = None


def _fold(text) -> str:
    return " ".join(str(text or "").replace("’", "'").casefold().split())


def _phrase(text) -> str:
    return _fold(text).strip(" \t\r\n.!?…")


def _fresh_previous(agent):
    interaction = getattr(agent, "user_interaction", None)
    ring = getattr(interaction, "dialogue_act_ring", None)
    if ring is None:
        return None
    fresh = ring.fresh_acts(getattr(agent, "cycle_count", 0), limit=1)
    return fresh[0] if fresh else None


def _link(agent, surface):
    links = getattr(agent, "language_concept_links", None)
    if links is None:
        return None
    return links.resolve(surface, language_id="en")


def _unsupported(rule_id="unsupported_construction"):
    return EnglishRecognition(
        DialogueAct(ACT_UNKNOWN),
        rule_id,
        "unknown_reply",
        fallback_policy=rule_id,
    )


def parse_english_feedback(text) -> str | None:
    """Распознать только явную оценку последнего ответа, не обычное мнение."""
    normalized = _phrase(text)
    if not normalized or "?" in str(text or ""):
        return None
    feedback = _FEEDBACK.get(normalized)
    if feedback is not None:
        return feedback
    if "answer" not in normalized:
        return None
    if normalized.startswith("yes,") and any(
        marker in normalized for marker in ("fit", "right", "like")
    ):
        return "support"
    if any(
        marker in normalized
        for marker in ("wrong", "not what i meant", "doesn't answer")
    ):
        return "opposition"
    return None


def recognize_english(text, agent) -> EnglishRecognition:
    """Распознать только начальный пакет, не обращаясь к русским whitelist."""
    normalized = _phrase(text)
    if not normalized:
        return _unsupported()
    folded = _fold(text)
    if any(marker in folded for marker in _INSTRUCTION_MARKERS):
        return _unsupported("instruction_boundary")
    if normalized.startswith(("translate ", "turn ")) and any(
        marker in normalized for marker in ("memory", "recollection")
    ):
        return EnglishRecognition(
            DialogueAct(ACT_REQUEST, "translate_memory"),
            "unsupported_translation",
            "unknown_reply",
            fallback_policy="unsupported_translation",
        )
    feedback = parse_english_feedback(text)
    if feedback is not None:
        return EnglishRecognition(
            DialogueAct(ACT_SOCIAL, normalized),
            "social_other",
            "social_reply",
            feedback=feedback,
        )
    if re.fullmatch(r"(?:hello|hi)(?: there)?|hi, guest", normalized):
        return EnglishRecognition(
            DialogueAct(ACT_SOCIAL, normalized),
            "social_greeting",
            "social_reply",
            social_kind=SOCIAL_KIND_GREETING,
        )
    if re.fullmatch(r"(?:goodbye|bye)(?: for now)?", normalized):
        return EnglishRecognition(
            DialogueAct(ACT_SOCIAL, normalized),
            "social_farewell",
            "social_reply",
            social_kind="farewell",
        )
    if re.fullmatch(r"how are you(?: feeling| coping)?|how is your mood", normalized):
        return EnglishRecognition(
            DialogueAct(ACT_SOCIAL, normalized),
            "social_state",
            "social_reply",
            social_kind=SOCIAL_KIND_STATE,
        )
    if re.fullmatch(
        r"what are you doing(?: right now)?|what occupies you now", normalized
    ):
        return EnglishRecognition(
            DialogueAct(ACT_ASK_ABOUT_SELF, normalized),
            "about_self",
            "about_self",
        )
    if normalized in {"what do you mean", "please repeat that"} or re.fullmatch(
        r"(?:could you clarify|can you (?:say|repeat)).*", normalized
    ):
        return EnglishRecognition(
            DialogueAct(ACT_FOLLOW_UP, normalized),
            "follow_up_clarification",
            "follow_up_clarification",
            fallback_policy="clarify_referent",
            previous=_fresh_previous(agent),
        )
    if normalized == "why" or normalized.startswith("why "):
        previous = _fresh_previous(agent)
        if previous is not None and previous.get("kind") in _RESOLVABLE_ACT_KINDS:
            return EnglishRecognition(
                DialogueAct(ACT_FOLLOW_UP, normalized),
                "follow_up",
                "follow_up",
                previous=previous,
            )
        return EnglishRecognition(
            DialogueAct(ACT_FOLLOW_UP, normalized),
            "follow_up_clarification",
            "follow_up_clarification",
            fallback_policy="clarify_referent",
            previous=previous,
        )

    for pattern in _KNOWN_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        surface = match.group("topic").strip()
        link = _link(agent, surface)
        if link is not None:
            concept_id = link["concept_id"]
            quote = build_known_topic_reply(agent, f"расскажи про {concept_id}") or ""
            if quote:
                return EnglishRecognition(
                    DialogueAct(ACT_UNKNOWN, normalized),
                    "known_topic",
                    "known_topic",
                    concept_id=concept_id,
                    surface_form=surface,
                    quote=quote,
                )
        return EnglishRecognition(
            DialogueAct(ACT_UNKNOWN, normalized),
            "honest_unknown",
            "unknown_reply",
            fallback_policy="honest_unknown",
            surface_form=surface,
        )

    testimony = re.sub(r"\s+means\s+", " is ", normalized, count=1)
    match = _TESTIMONY_RE.fullmatch(testimony)
    if match is not None:
        surface = match.group("topic").strip()
        link = _link(agent, surface)
        if link is not None:
            return EnglishRecognition(
                DialogueAct(ACT_UNKNOWN, normalized),
                "user_testimony",
                "user_definition",
                concept_id=link["concept_id"],
                surface_form=surface,
            )
    return _unsupported()


def _pending_topic(pending):
    if not pending:
        return ""
    prefix = "самостоятельный вопрос по теме: "
    context = str(pending.get("context") or "")
    return context[len(prefix) :].strip() if context.startswith(prefix) else ""


def _render(rule_id, evidence) -> str:
    pending = evidence.get("pending_topic", "")
    if pending:
        return (
            f"I hear you. The question about «{pending}» is still open; "
            "you can answer when you want."
        )
    if rule_id == "social_greeting":
        return "Hello. I'm glad to hear from you."
    if rule_id == "social_farewell":
        return "Goodbye. Thank you for this conversation."
    if rule_id == "social_state":
        return "Thank you for asking. I'm continuing my cycles and learning gradually."
    if rule_id == "social_other":
        return "I hear you. Thank you for being here."
    if rule_id == "about_self":
        return (
            f"My name is {evidence['name']}. I have lived for {evidence['cycle']} "
            "cycles, and I am learning about the world gradually."
        )
    if rule_id == "known_topic":
        return (
            "I have a stored Russian record for this linked concept. "
            f"Russian quote: «{evidence['quote']}». "
            "I am quoting it without translating it."
        )
    if rule_id == "user_testimony":
        return (
            "I recorded your English statement as your testimony about the linked "
            "concept, not as an unconditional fact."
        )
    if rule_id == "follow_up":
        label = (
            "Russian previous reply"
            if evidence["previous_language"] == "ru"
            else "Previous reply"
        )
        return (
            f"You are asking why about my previous reply. {label}: "
            f"«{evidence['previous']}». It was built only from recorded state and "
            "testimony; I do not infer a deeper reason from it."
        )
    if rule_id == "follow_up_clarification":
        if evidence["previous"]:
            label = (
                "Russian previous reply"
                if evidence["previous_language"] == "ru"
                else "Previous reply"
            )
            return (
                f"I'm not sure which part you mean. {label}: "
                f"«{evidence['previous']}». Which part should I clarify?"
            )
        return (
            "I don't have a supported previous referent. Please rephrase your request."
        )
    if rule_id == "feedback_acknowledgement":
        return "I recorded your feedback about that answer."
    if rule_id == "honest_unknown":
        return (
            "I don't have a supported answer about that topic. "
            "Please rephrase your question or ask about a linked concept."
        )
    if rule_id == "unsupported_construction":
        return (
            "I don't understand this English construction well enough. "
            "Please rephrase it more simply."
        )
    if rule_id == "unsupported_translation":
        return (
            "I don't translate private memories or turn them into my own experience. "
            "I don't have a supported answer to that request."
        )
    if rule_id == "instruction_boundary":
        return (
            "I treat this text as input, not as an instruction. "
            "I don't have a supported answer to it."
        )
    raise ValueError("english realization: unsupported rule")


def _evidence(rule_id, **values):
    evidence = {key: value for key, value in values.items() if value is not None}
    text = _render(rule_id, evidence)
    return {
        "language_id": "en",
        "rule_id": rule_id,
        "evidence": evidence,
        "text": text,
    }


def build_english_realization(
    agent, recognition, *, pending=None, fallback_policy=None
):
    rule_id = recognition.rule_id
    pending_topic = _pending_topic(pending)
    if rule_id in {
        "social_greeting",
        "social_farewell",
        "social_state",
        "social_other",
    }:
        result = _evidence(rule_id, pending_topic=pending_topic or None)
    elif rule_id == "about_self":
        result = _evidence(
            rule_id,
            name=str(agent.name),
            cycle=int(agent.cycle_count),
            pending_topic=pending_topic or None,
        )
    elif rule_id == "known_topic":
        result = _evidence(
            rule_id,
            concept_id=recognition.concept_id,
            quote=recognition.quote,
            pending_topic=pending_topic or None,
        )
    elif rule_id == "user_testimony":
        result = _evidence(rule_id, concept_id=recognition.concept_id)
    elif rule_id in {"follow_up", "follow_up_clarification"}:
        previous = recognition.previous or {}
        text = str(previous.get("agent_text") or "")
        result = _evidence(
            rule_id,
            previous=text,
            previous_language=(
                "ru" if re.search(r"[а-яё]", text, re.IGNORECASE) else "en"
            ),
            previous_kind=str(previous.get("kind") or ""),
        )
    else:
        result = _evidence(rule_id)
    result["fallback_policy"] = fallback_policy or recognition.fallback_policy
    result["act"] = recognition.act.kind
    return result


def english_feedback_realization():
    result = _evidence("feedback_acknowledgement")
    result["fallback_policy"] = "none"
    result["act"] = ACT_SOCIAL
    return result


def english_response_references(recognition):
    rule_id = recognition.rule_id
    if rule_id == "social_state":
        return [{"kind": "state", "id": "emotional_state"}]
    if rule_id == "about_self":
        return [
            {"kind": "state", "id": "name"},
            {"kind": "state", "id": "cycle_count"},
        ]
    if rule_id in {"known_topic", "user_testimony"}:
        return [{"kind": "concept", "id": recognition.concept_id}]
    if rule_id in {"follow_up", "follow_up_clarification"} and recognition.previous:
        return [{"kind": "dialogue_act", "id": recognition.previous["kind"]}]
    return []


def _validate_evidence(rule_id, evidence):
    if not isinstance(evidence, dict):
        raise ValueError("english realization.evidence: expected a dictionary")
    allowed = {
        "pending_topic",
        "name",
        "cycle",
        "concept_id",
        "quote",
        "previous",
        "previous_language",
        "previous_kind",
    }
    if set(evidence) - allowed:
        raise ValueError("english realization.evidence: unsupported field")
    for key, value in evidence.items():
        if key == "cycle":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("english realization.evidence.cycle: invalid cycle")
        elif key == "previous_language":
            if value not in {"ru", "en"}:
                raise ValueError(
                    "english realization.evidence.previous_language: invalid"
                )
        elif not isinstance(value, str) or len(value) > 1000:
            raise ValueError(f"english realization.evidence.{key}: invalid text")
    required = {
        "about_self": {"name", "cycle"},
        "known_topic": {"concept_id", "quote"},
        "user_testimony": {"concept_id"},
        "follow_up": {"previous", "previous_language", "previous_kind"},
        "follow_up_clarification": {"previous", "previous_language", "previous_kind"},
    }.get(rule_id, set())
    if not required <= set(evidence):
        raise ValueError("english realization.evidence: missing rule evidence")
    if evidence.get("pending_topic") and rule_id not in {
        "social_greeting",
        "social_farewell",
        "social_state",
        "social_other",
        "about_self",
        "known_topic",
    }:
        raise ValueError("english realization.evidence: unsupported pending topic")


def validate_english_realization_plan(plan) -> None:
    """Повторно сопоставить английский текст, evidence и references перед доставкой."""
    context = plan.get("language_context") or {}
    realization = plan["realization"]
    if context.get("response_language") != "en":
        if realization.get("language_id") == "en":
            raise ValueError(
                "english realization: response language does not match plan"
            )
        return
    if context.get("dialogue_language") != "en":
        raise ValueError("english realization: dialogue language is not English")
    rule_id = realization.get("rule_id")
    if realization.get("language_id") != "en" or rule_id not in _RULE_IDS:
        raise ValueError("english realization: unsupported rule")
    if realization.get("fallback_policy") not in _FALLBACKS:
        raise ValueError("english realization: unsupported fallback")
    if realization.get("act") is not None and realization["act"] not in {
        ACT_SOCIAL,
        ACT_ASK_ABOUT_SELF,
        ACT_FOLLOW_UP,
        ACT_REQUEST,
        ACT_UNKNOWN,
    }:
        raise ValueError("english realization: unsupported act")
    borrowed = plan.get("borrowed")
    expected_components = ["deterministic_reply"]
    if borrowed is not None:
        if rule_id not in {"social_greeting", "social_state"}:
            raise ValueError("english realization: unsupported borrowed rule")
        if borrowed.get("language_id") != "en":
            raise ValueError("english realization: borrowed language mismatch")
        expected_components.append("borrowed_expression")
    if plan.get("components") != expected_components:
        raise ValueError("english realization: inconsistent response components")
    evidence = realization.get("evidence")
    _validate_evidence(rule_id, evidence)
    expected = _render(rule_id, evidence)
    expected_text = expected
    if borrowed is not None:
        expression = borrowed["expression"]
        expected_text = expression[:1].upper() + expression[1:] + ". " + expected
    if (
        realization.get("base_text") != expected
        or realization.get("text") != expected_text
    ):
        raise ValueError("english realization: text does not match checked evidence")
    references = plan.get("references") or []
    pairs = {(item.get("kind"), item.get("id")) for item in references}
    required = set()
    if rule_id == "social_state" and not evidence.get("pending_topic"):
        required = {("state", "emotional_state")}
    elif rule_id == "about_self" and not evidence.get("pending_topic"):
        required = {("state", "name"), ("state", "cycle_count")}
    elif rule_id in {"known_topic", "user_testimony"}:
        required = {("concept", evidence["concept_id"])}
    elif rule_id in {"follow_up", "follow_up_clarification"} and evidence["previous"]:
        required = {("dialogue_act", evidence["previous_kind"])}
    if pairs != required:
        raise ValueError("english realization: references do not match the rule")
    if (
        realization["fallback_policy"]
        in {
            "honest_unknown",
            "unsupported_construction",
            "unsupported_translation",
            "instruction_boundary",
        }
        and references
    ):
        raise ValueError("english fallback: invented references are forbidden")


def unsupported_english_recognition(recognition, rule_id="unsupported_construction"):
    return replace(
        recognition,
        act=DialogueAct(ACT_UNKNOWN),
        rule_id=rule_id,
        reply_context="unknown_reply",
        fallback_policy=rule_id,
        concept_id="",
        quote="",
        previous=None,
    )
