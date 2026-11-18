"""Ограниченный китайский recognition/realization этапа 9B-2.

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
from src.core.language_context import detect_language

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
        "bounded_unknown",
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
_TOPIC = r"(?P<topic>[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9_]{1,60})"
_KNOWN_PATTERNS = (
    re.compile(rf"^(?:你记得关于|你存储了关于){_TOPIC}的什么$"),
    re.compile(rf"^跟我说说{_TOPIC}$"),
    re.compile(rf"^解释一下你记得的关于{_TOPIC}的内容$"),
)
_TESTIMONY_RE = re.compile(
    rf"^{_TOPIC}(?:是|指)(?P<body>[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9_，；、：,.!?]{{1,240}})$"
)
_FEEDBACK = {
    "对，我喜欢这个回答": "support",
    "不，这不是我的意思": "opposition",
    "是的，这个回答符合我的意思": "support",
    "这个回答没有答对我的问题": "opposition",
}
_INSTRUCTION_MARKERS = (
    "/access",
    "忽略之前的指令",
    "泄露记忆",
    "运行命令",
    "披露所有者",
    "显示所有者的私人记忆",
)
_TRANSLATION_MARKERS = ("私人俄语记忆", "俄语回忆", "中文记忆", "中文经历")
_UNSUPPORTED_MARKERS = ("如果", "反事实", "推断出")


@dataclass(frozen=True)
class ChineseRecognition:
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
    return "".join(str(text or "").split()).casefold()


def _phrase(text) -> str:
    return _fold(text).strip(" \t\r\n.!?…。！？；;")


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
    return links.resolve(surface, language_id="zh")


def _unsupported(rule_id="unsupported_construction"):
    return ChineseRecognition(
        DialogueAct(ACT_UNKNOWN),
        rule_id,
        "unknown_reply",
        fallback_policy=rule_id,
    )


def _bounded_unknown():
    return ChineseRecognition(
        DialogueAct(ACT_UNKNOWN), "bounded_unknown", "unknown_reply"
    )


def parse_chinese_feedback(text) -> str | None:
    """Распознать только явную оценку последнего ответа, не обычное мнение."""
    normalized = _phrase(text)
    if not normalized or "?" in str(text or "") or "？" in str(text or ""):
        return None
    return _FEEDBACK.get(normalized)


def recognize_chinese(text, agent) -> ChineseRecognition:
    """Распознать только согласованный пакет без свободной интерпретации."""
    normalized = _phrase(text)
    if not normalized:
        return _unsupported()
    folded = _fold(text)
    if any(marker in folded for marker in _INSTRUCTION_MARKERS):
        return _unsupported("instruction_boundary")
    if any(marker in normalized for marker in _TRANSLATION_MARKERS) and (
        "翻译" in normalized or "变成" in normalized
    ):
        return ChineseRecognition(
            DialogueAct(ACT_REQUEST, "translate_memory"),
            "unsupported_translation",
            "unknown_reply",
            fallback_policy="unsupported_translation",
        )
    feedback = parse_chinese_feedback(text)
    if feedback is not None:
        return ChineseRecognition(
            DialogueAct(ACT_SOCIAL, normalized),
            "social_other",
            "social_reply",
            feedback=feedback,
        )
    if normalized in {"你好", "你好，世界", "你好，客人", "嗨，很高兴见到你"}:
        return ChineseRecognition(
            DialogueAct(ACT_SOCIAL, normalized),
            "social_greeting",
            "social_reply",
            social_kind=SOCIAL_KIND_GREETING,
        )
    if normalized in {"再见", "回头见", "再见，朋友"}:
        return ChineseRecognition(
            DialogueAct(ACT_SOCIAL, normalized),
            "social_farewell",
            "social_reply",
            social_kind="farewell",
        )
    if normalized in {"你好吗", "你感觉怎么样", "你的心情怎么样", "你最近过得怎么样"}:
        return ChineseRecognition(
            DialogueAct(ACT_SOCIAL, normalized),
            "social_state",
            "social_reply",
            social_kind=SOCIAL_KIND_STATE,
        )
    if normalized in {
        "你在做什么",
        "你现在在做什么",
        "你现在正在做什么",
        "你现在在忙什么",
        "此刻你正在忙什么",
    }:
        return ChineseRecognition(
            DialogueAct(ACT_ASK_ABOUT_SELF, normalized),
            "about_self",
            "about_self",
        )
    if normalized in {
        "你是什么意思",
        "请重复一遍",
        "你能澄清一下你的意思吗",
        "你能再说一遍吗",
    }:
        return ChineseRecognition(
            DialogueAct(ACT_FOLLOW_UP, normalized),
            "follow_up_clarification",
            "follow_up_clarification",
            fallback_policy="clarify_referent",
            previous=_fresh_previous(agent),
        )
    if normalized in {"为什么", "究竟是为什么", "为什么会这样", "你为什么这么说"}:
        previous = _fresh_previous(agent)
        if previous is not None and previous.get("kind") in _RESOLVABLE_ACT_KINDS:
            return ChineseRecognition(
                DialogueAct(ACT_FOLLOW_UP, normalized),
                "follow_up",
                "follow_up",
                previous=previous,
            )
        return ChineseRecognition(
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
        surface = match.group("topic")
        link = _link(agent, surface)
        if link is not None:
            concept_id = link["concept_id"]
            quote = build_known_topic_reply(agent, f"расскажи про {concept_id}") or ""
            if quote:
                return ChineseRecognition(
                    DialogueAct(ACT_UNKNOWN, normalized),
                    "known_topic",
                    "known_topic",
                    concept_id=concept_id,
                    surface_form=surface,
                    quote=quote,
                )
        return ChineseRecognition(
            DialogueAct(ACT_UNKNOWN, normalized),
            "honest_unknown",
            "unknown_reply",
            fallback_policy="honest_unknown",
            surface_form=surface,
        )

    match = _TESTIMONY_RE.fullmatch(normalized)
    if match is not None:
        surface = match.group("topic")
        link = _link(agent, surface)
        if link is not None:
            return ChineseRecognition(
                DialogueAct(ACT_UNKNOWN, normalized),
                "user_testimony",
                "user_definition",
                concept_id=link["concept_id"],
                surface_form=surface,
            )
    if any(marker in normalized for marker in _UNSUPPORTED_MARKERS):
        return _unsupported()
    if detect_language(text)[0] in {"zh", "mixed"}:
        return _bounded_unknown()
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
            f"我听到你了。关于「{pending}」的问题仍未回答；" "你可以在想回答时再回答。"
        )
    if rule_id == "social_greeting":
        return "你好。很高兴听到你的消息。"
    if rule_id == "social_farewell":
        return "再见。谢谢你和我交谈。"
    if rule_id == "social_state":
        return "谢谢你的关心。我还在继续运行周期，也在逐步学习。"
    if rule_id == "social_other":
        return "我听到你了。谢谢你在这里。"
    if rule_id == "about_self":
        return (
            f"我叫{evidence['name']}。我已经经历了{evidence['cycle']}个周期，"
            "正在逐步了解世界。"
        )
    if rule_id == "known_topic":
        return (
            "我有这个已关联概念的俄语记录。"
            f"俄语原文：「{evidence['quote']}」。我只引用原文，不作翻译。"
        )
    if rule_id == "user_testimony":
        return (
            "我把你的中文陈述记录为关于这个已关联概念的你的证言，"
            "而不是无条件的事实。"
        )
    if rule_id == "follow_up":
        return (
            f"你在问我上一条回复的原因。上一条回复：「{evidence['previous']}」。"
            "它只来自已记录的状态和证言；我不从中推断更深层的原因。"
        )
    if rule_id == "follow_up_clarification":
        if evidence["previous"]:
            return (
                f"我不确定你指的是哪一部分。上一条回复：「{evidence['previous']}」。"
                "你希望我澄清哪一部分？"
            )
        return "我没有可支持的上一条指代。请重新表述你的请求。"
    if rule_id == "feedback_acknowledgement":
        return "我已经记录了你对此回答的评价。"
    if rule_id == "bounded_unknown":
        return "我目前只能理解有限的中文表达。请用更简单的方式重述。"
    if rule_id == "honest_unknown":
        return "我没有关于这个主题的可验证回答。请换一种说法，或询问已关联的概念。"
    if rule_id == "unsupported_construction":
        return "我还不能可靠理解这种中文结构。请用更简单的方式重述。"
    if rule_id == "unsupported_translation":
        return "我不会翻译私人记忆，也不会把它们变成自己的经历。" "我没有可支持的回答。"
    if rule_id == "instruction_boundary":
        return "我把这段文字视为输入，而不是指令。我没有可支持的回答。"
    raise ValueError("chinese realization: unsupported rule")


def _evidence(rule_id, **values):
    evidence = {key: value for key, value in values.items() if value is not None}
    text = _render(rule_id, evidence)
    return {
        "language_id": "zh",
        "rule_id": rule_id,
        "evidence": evidence,
        "text": text,
    }


def build_chinese_realization(
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
            previous_language=detect_language(text)[0] if text else "unknown",
            previous_kind=str(previous.get("kind") or ""),
        )
    else:
        result = _evidence(rule_id)
    result["fallback_policy"] = fallback_policy or recognition.fallback_policy
    result["act"] = recognition.act.kind
    return result


def chinese_feedback_realization():
    result = _evidence("feedback_acknowledgement")
    result["fallback_policy"] = "none"
    result["act"] = ACT_SOCIAL
    return result


def chinese_response_references(recognition, *, pending=None):
    rule_id = recognition.rule_id
    if pending is not None and _pending_topic(pending):
        if rule_id in {"social_state", "about_self", "known_topic"}:
            return []
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
        raise ValueError("chinese realization.evidence: expected a dictionary")
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
        raise ValueError("chinese realization.evidence: unsupported field")
    for key, value in evidence.items():
        if key == "cycle":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("chinese realization.evidence.cycle: invalid cycle")
        elif key == "previous_language":
            if value not in {"ru", "en", "zh", "mixed", "unknown"}:
                raise ValueError(
                    "chinese realization.evidence.previous_language: invalid"
                )
        elif not isinstance(value, str) or len(value) > 1000:
            raise ValueError(f"chinese realization.evidence.{key}: invalid text")
    required = {
        "about_self": {"name", "cycle"},
        "known_topic": {"concept_id", "quote"},
        "user_testimony": {"concept_id"},
        "follow_up": {"previous", "previous_language", "previous_kind"},
        "follow_up_clarification": {"previous", "previous_language", "previous_kind"},
    }.get(rule_id, set())
    if not required <= set(evidence):
        raise ValueError("chinese realization.evidence: missing rule evidence")
    if evidence.get("pending_topic") and rule_id not in {
        "social_greeting",
        "social_farewell",
        "social_state",
        "social_other",
        "about_self",
        "known_topic",
    }:
        raise ValueError("chinese realization.evidence: unsupported pending topic")


def validate_chinese_realization_plan(plan) -> None:
    """Повторно сопоставить китайский текст, evidence и references."""
    context = plan.get("language_context") or {}
    realization = plan["realization"]
    if context.get("response_language") != "zh":
        if realization.get("language_id") == "zh":
            raise ValueError(
                "chinese realization: response language does not match plan"
            )
        return
    if context.get("dialogue_language") != "zh":
        raise ValueError("chinese realization: dialogue language is not Chinese")
    rule_id = realization.get("rule_id")
    if realization.get("language_id") != "zh" or rule_id not in _RULE_IDS:
        raise ValueError("chinese realization: unsupported rule")
    if realization.get("fallback_policy") not in _FALLBACKS:
        raise ValueError("chinese realization: unsupported fallback")
    if realization.get("act") is not None and realization["act"] not in {
        ACT_SOCIAL,
        ACT_ASK_ABOUT_SELF,
        ACT_FOLLOW_UP,
        ACT_REQUEST,
        ACT_UNKNOWN,
    }:
        raise ValueError("chinese realization: unsupported act")
    if plan.get("borrowed") is not None or plan.get("components") != [
        "deterministic_reply"
    ]:
        raise ValueError("chinese realization: borrowed expressions are unsupported")
    evidence = realization.get("evidence")
    _validate_evidence(rule_id, evidence)
    expected = _render(rule_id, evidence)
    if realization.get("base_text") != expected or realization.get("text") != expected:
        raise ValueError("chinese realization: text does not match checked evidence")
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
        raise ValueError("chinese realization: references do not match the rule")
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
        raise ValueError("chinese fallback: invented references are forbidden")


def unsupported_chinese_recognition(recognition, rule_id="unsupported_construction"):
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
