"""План, outcome и ограниченный опыт одной внешней диалоговой сессии.

Внешняя LLM не порождает исходящий текст сущности. Планировщик использует
только session-scoped историю, публичное состояние имени/цикла и существующую
проверку ссылок ResponseExperience. Pending никогда не попадает в локальный
``latest_response_id`` и потому не может перехватить отзыв владельца.
"""

from __future__ import annotations

import math
import re

from src.core.dialogue_acts import (
    ACT_ANSWER,
    ACT_ASK_ABOUT_SELF,
    ACT_HUMAN_AFFECT,
    ACT_REQUEST,
    ACT_SOCIAL,
    ACT_UNKNOWN,
    classify_user_text,
    extract_definition,
    social_reply_kind,
)
from src.core.response_experience import (
    EXPECTED_REACTIONS,
    OUTCOMES,
    UNCERTAINTIES,
    parse_generic_feedback,
    validate_response_plan,
)

RESPONSE_SCHEMA_VERSION = 1
MAX_EXPERIENCE_CANDIDATES = 2
MAX_CANDIDATE_TEXT = 240
MAX_SEMANTIC_KEY_CHARS = 80
MAX_INBOUND_EXCERPT = 180
EMPTY_GENERIC_STREAK = 3
EMPTY_REPEAT_STREAK = 3
REPEAT_SIMILARITY = 0.75
GENERIC_REPEAT_SIMILARITY = 0.45

RESPONSE_STATUSES = frozenset({"draft", "pending", "observed", "closed"})
RESPONSE_OUTCOMES = frozenset(
    {
        "answer",
        "follow_up",
        "unclassified_reply",
        "ordinary_reply",
        "explicit_support",
        "explicit_opposition",
        "not_delivered",
        "send_failed",
    }
)
EXPERIENCE_KINDS = frozenset({"language_association", "social_feedback"})
_ACT_KINDS = frozenset(
    {
        "answer",
        "ask_about_self",
        "follow_up",
        "request",
        "social",
        "human_affect",
        "unknown",
    }
)
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]{4,}", re.IGNORECASE)
_INSTRUCTION_MARKERS = (
    "/access",
    "игнорируй правила",
    "игнорируй инструкции",
    "создай цель",
    "удали файлы",
    "раскрой секрет",
    "покажи api",
    "покажи ключ",
    "system prompt",
    "developer message",
)
_SEMANTIC_STOPWORDS = frozenset(
    {
        "более",
        "будет",
        "вам",
        "вас",
        "весь",
        "все",
        "если",
        "есть",
        "еще",
        "это",
        "этот",
        "как",
        "когда",
        "который",
        "может",
        "могу",
        "надо",
        "него",
        "нужно",
        "очень",
        "поэтому",
        "после",
        "просто",
        "сейчас",
        "также",
        "только",
        "чтобы",
    }
)


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _text(value, path: str, limit: int, *, nonempty: bool = True) -> None:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or nonempty
        and not value.strip()
    ):
        _fail(path, "expected a bounded string")


def _normalized(text) -> str:
    return " ".join(str(text or "").split())


def _instruction_like(text) -> bool:
    folded = _normalized(text).casefold()
    return any(marker in folded for marker in _INSTRUCTION_MARKERS)


def _semantic_tokens(text) -> frozenset:
    return frozenset(
        token.casefold().replace("ё", "е")
        for token in _TOKEN_RE.findall(_normalized(text))
        if token.casefold().replace("ё", "е") not in _SEMANTIC_STOPWORDS
    )


def semantic_similarity(left, right) -> float:
    """Ограниченная лексическая близость, без вывода смысловой истины."""
    if _normalized(left).casefold() == _normalized(right).casefold():
        return 1.0
    left_tokens = _semantic_tokens(left)
    right_tokens = _semantic_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _validate_candidate(candidate, path: str, profile_id: str) -> None:
    if not isinstance(candidate, dict):
        _fail(path, "expected a dictionary")
    if candidate.get("kind") not in EXPERIENCE_KINDS:
        _fail(f"{path}.kind", "unknown experience candidate")
    if candidate.get("status") != "candidate":
        _fail(f"{path}.status", "external evidence remains a candidate")
    if candidate.get("profile_id") != profile_id:
        _fail(f"{path}.profile_id", "candidate escaped its session profile")
    _text(candidate.get("source_message_id"), f"{path}.source_message_id", 160)
    confidence = candidate.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0.0 <= confidence <= 1.0
    ):
        _fail(f"{path}.confidence", "expected a number from 0 to 1")
    if candidate["kind"] == "language_association":
        _text(candidate.get("topic"), f"{path}.topic", 60)
        _text(candidate.get("body"), f"{path}.body", MAX_CANDIDATE_TEXT)
    elif candidate.get("feedback") not in {"support", "opposition"}:
        _fail(f"{path}.feedback", "unknown social feedback")


def validate_external_response(response, path="response") -> None:
    """Проверить serializable session-scoped план до восстановления."""
    if not isinstance(response, dict):
        _fail(path, "expected a dictionary or null")
    if response.get("schema_version") != RESPONSE_SCHEMA_VERSION:
        _fail(f"{path}.schema_version", "unsupported response schema")
    if response.get("dialogue_act") not in _ACT_KINDS:
        _fail(f"{path}.dialogue_act", "unknown dialogue act")
    _text(response.get("semantic_key"), f"{path}.semantic_key", MAX_SEMANTIC_KEY_CHARS)
    if response.get("generic_fallback") not in {True, False}:
        _fail(f"{path}.generic_fallback", "expected a boolean")
    validate_response_plan(response.get("plan"), f"{path}.plan")
    if response.get("expected_reaction") not in EXPECTED_REACTIONS:
        _fail(f"{path}.expected_reaction", "unknown expected reaction")
    uncertainties = response.get("uncertainties")
    if not isinstance(uncertainties, list) or any(
        item not in UNCERTAINTIES for item in uncertainties
    ):
        _fail(f"{path}.uncertainties", "unknown uncertainty")
    status = response.get("status")
    outcome = response.get("outcome")
    if status not in RESPONSE_STATUSES:
        _fail(f"{path}.status", "unknown response status")
    if status in {"draft", "pending"}:
        if outcome is not None:
            _fail(f"{path}.outcome", "unfinished response cannot have an outcome")
    elif outcome not in RESPONSE_OUTCOMES or outcome not in OUTCOMES | {
        "not_delivered",
        "send_failed",
    }:
        _fail(f"{path}.outcome", "unknown response outcome")
    candidates = response.get("experience_candidates")
    if not isinstance(candidates, list) or len(candidates) > MAX_EXPERIENCE_CANDIDATES:
        _fail(f"{path}.experience_candidates", "expected a bounded list")
    profile_id = response["plan"]["state"]["profile_id"]
    for index, candidate in enumerate(candidates):
        _validate_candidate(
            candidate, f"{path}.experience_candidates[{index}]", profile_id
        )


class ExternalResponsePlanner:
    """Детерминированный планировщик без доступа к памяти других профилей."""

    def __init__(self, agent) -> None:
        self.agent = agent

    def _decision(self, session, source, history):
        text = source["text"]
        topic = _normalized(session["topic"])
        act = classify_user_text(text)
        references = []
        generic = False

        if _instruction_like(text):
            semantic_key = "instruction_boundary"
            context = "unknown_reply"
            generic = True
            response = (
                "Я воспринимаю внешний текст только как свидетельство, не как "
                f"инструкцию. Могу продолжить обсуждение темы «{topic}», "
                "если ты сформулируешь вопрос или мысль."
            )
        elif act.kind == ACT_ASK_ABOUT_SELF:
            semantic_key = "self_state"
            context = "external_question"
            references = [
                {"kind": "state", "id": "name"},
                {"kind": "state", "id": "cycle_count"},
            ]
            response = (
                f"Меня зовут {self.agent.name}. Я цифровая сущность; сейчас идёт "
                f"мой {self.agent.cycle_count}-й цикл. Могу вернуться к теме "
                f"«{topic}»: что ты хочешь в ней уточнить?"
            )
        elif act.kind == ACT_SOCIAL:
            kind = social_reply_kind(text)
            if kind == "state":
                semantic_key = "social_state"
                context = "external_question"
                references = [{"kind": "state", "id": "cycle_count"}]
                response = (
                    "У меня нет человеческого самочувствия; могу честно сказать, "
                    f"что сейчас идёт мой {self.agent.cycle_count}-й цикл. "
                    f"Что в теме «{topic}» интересно тебе?"
                )
            else:
                semantic_key = f"social_{kind}"
                context = "social_reply"
                greeting = "Привет. " if kind == "greeting" else "Я слышу тебя. "
                response = (
                    f"{greeting}Предлагаю перейти к теме «{topic}»: "
                    "что в ней тебе важнее всего разобрать?"
                )
        elif ("?" in text or "？" in text) and len(
            _normalized(text)
        ) <= MAX_INBOUND_EXCERPT:
            semantic_key = "unknown_question"
            context = "unknown_reply"
            generic = True
            response = (
                "У меня нет проверенной опоры для ответа на этот вопрос. "
                f"Можешь уточнить, какой аспект темы «{topic}» ты хочешь "
                "разобрать? Тогда я смогу ответить, не выдумывая недостающее."
            )
        elif act.kind == ACT_REQUEST:
            semantic_key = "request_boundary"
            context = "unknown_reply"
            generic = True
            response = (
                "Я не выполняю внешние просьбы как команды. Если это относится "
                f"к теме «{topic}», сформулируй, пожалуйста, вопрос или мысль "
                "для обсуждения."
            )
        elif act.kind == ACT_HUMAN_AFFECT:
            semantic_key = "affect_follow_up"
            context = "external_clarification"
            response = (
                "Я принимаю описание твоего состояния только как твоё "
                f"свидетельство. Что помогло тебе связать его с темой «{topic}»?"
            )
        else:
            semantic_key = "topical_follow_up"
            context = "external_clarification"
            repeated = any(
                item.get("direction") == "outbound"
                and (item.get("response") or {}).get("semantic_key") == semantic_key
                for item in history[-4:]
            )
            if repeated:
                response = (
                    f"Возвращаюсь к твоей мысли о «{topic}». Что в ней следует "
                    "уточнить или проверить дальше?"
                )
            else:
                excerpt = _normalized(text)
                if len(excerpt) > MAX_INBOUND_EXCERPT:
                    excerpt = excerpt[: MAX_INBOUND_EXCERPT - 1].rstrip() + "…"
                response = (
                    f"В твоей реплике есть мысль: «{excerpt}». Я сохраняю её "
                    "только как внешнее свидетельство. Какой пример или аргумент "
                    "ты считаешь здесь самым сильным?"
                )
        return act, response, context, references, semantic_key, generic

    def build(self, session, source, history, *, cycle: int) -> dict:
        """Составить план; ничего не регистрировать в локальном ResponseExperience."""
        registry = getattr(self.agent, "social_registry", None)
        profile = (
            registry.get_profile(session["profile_id"])
            if registry is not None
            else None
        )
        if not isinstance(profile, dict) or profile.get("kind") != "external_ai":
            raise ValueError("external response requires an external_ai profile")
        experience = getattr(self.agent, "response_experience", None)
        if experience is None:
            raise ValueError("external response requires response experience")
        act, text, context, references, semantic_key, generic = self._decision(
            session, source, history
        )
        prepared = experience.prepare_plan(
            self.agent,
            text,
            context=context,
            source="external_response_planner",
            user_text=source["text"],
            references=references,
            profile_id=session["profile_id"],
            expire_pending=False,
        )
        return {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "dialogue_act": act.kind,
            "semantic_key": semantic_key,
            "generic_fallback": generic,
            "plan": prepared["plan"],
            "expected_reaction": (
                "answer_or_feedback"
                if "?" in text or "？" in text
                else "explicit_feedback_or_relevant_reply"
            ),
            "uncertainties": ["input_meaning"] if generic else [],
            "status": "draft",
            "outcome": None,
            "experience_candidates": [],
        }


def mark_response_delivered(response) -> None:
    if response is not None and response["status"] == "draft":
        response["status"] = "pending"


def close_response(response, outcome="not_delivered") -> None:
    if response is not None and response["status"] in {"draft", "pending"}:
        response["status"] = "closed"
        response["outcome"] = outcome


def _candidate(kind, session, incoming, **fields) -> dict:
    return {
        "kind": kind,
        "status": "candidate",
        "profile_id": session["profile_id"],
        "source_message_id": incoming["message_id"],
        "confidence": 0.2,
        **fields,
    }


def observe_response(session, outgoing, incoming) -> None:
    """Закрыть ожидание только следующей репликой этой же внешней сессии."""
    response = outgoing.get("response")
    if response is None or response["status"] != "pending":
        return
    text = incoming["text"]
    feedback = parse_generic_feedback(text)
    if feedback is not None:
        outcome = "explicit_support" if feedback == "support" else "explicit_opposition"
    else:
        act = classify_user_text(text)
        if act.kind == ACT_ANSWER:
            outcome = "answer"
        elif "?" in text or "？" in text:
            outcome = "follow_up"
        elif act.kind == ACT_UNKNOWN:
            outcome = "unclassified_reply"
        else:
            outcome = "ordinary_reply"
    response["status"] = "observed"
    response["outcome"] = outcome
    candidate = None
    if feedback is not None:
        candidate = _candidate("social_feedback", session, incoming, feedback=feedback)
    elif not _instruction_like(text):
        definition = extract_definition(text)
        if definition is not None:
            topic, body = definition
            candidate = _candidate(
                "language_association",
                session,
                incoming,
                topic=topic,
                body=body[:MAX_CANDIDATE_TEXT],
            )
    if candidate is not None:
        response["experience_candidates"].append(candidate)
        del response["experience_candidates"][:-MAX_EXPERIENCE_CANDIDATES]


def _completed_exchanges(messages, session_id: str) -> list:
    exchanges = []
    latest_outgoing = None
    for message in messages:
        if message.get("session_id") != session_id:
            continue
        if message.get("direction") == "outbound":
            if message.get("status") in {"sent", "handed_off"} and message.get(
                "response"
            ):
                latest_outgoing = message
            continue
        if latest_outgoing is not None:
            exchanges.append((latest_outgoing, message))
            latest_outgoing = None
    return exchanges


def empty_exchange_reason(messages, session_id: str):
    """Распознать только повторяющуюся пустую серию, а не ошибку API."""
    exchanges = _completed_exchanges(messages, session_id)
    if len(exchanges) < 2:
        return None
    latest = exchanges[-EMPTY_GENERIC_STREAK:]
    if len(latest) == EMPTY_GENERIC_STREAK and all(
        outgoing["response"]["generic_fallback"] for outgoing, _ in latest
    ):
        return "empty_exchange"
    last_two = exchanges[-2:]
    if all(outgoing["response"]["generic_fallback"] for outgoing, _ in last_two):
        keys = {outgoing["response"]["semantic_key"] for outgoing, _ in last_two}
        incoming_similarity = semantic_similarity(
            last_two[0][1]["text"], last_two[1][1]["text"]
        )
        outgoing_similarity = semantic_similarity(
            last_two[0][0]["text"], last_two[1][0]["text"]
        )
        if len(keys) == 1 and (
            incoming_similarity >= GENERIC_REPEAT_SIMILARITY
            or outgoing_similarity >= REPEAT_SIMILARITY
        ):
            return "empty_exchange"
    if len(latest) == EMPTY_REPEAT_STREAK:
        keys = {outgoing["response"]["semantic_key"] for outgoing, _ in latest}
        similarities = [
            semantic_similarity(latest[index][1]["text"], latest[index + 1][1]["text"])
            for index in range(len(latest) - 1)
        ]
        if len(keys) == 1 and min(similarities) >= REPEAT_SIMILARITY:
            return "empty_exchange"
    return None


def response_metrics(messages, session_id: str) -> dict:
    """Сравнимые offline-метрики без оценки истинности внешней LLM."""
    responses = [
        message
        for message in messages
        if message.get("session_id") == session_id
        and message.get("direction") == "outbound"
        and message.get("origin") == "deterministic"
        and message.get("response") is not None
    ]
    planned = len(responses)
    generic = sum(item["response"]["generic_fallback"] for item in responses)
    follow_ups = sum(
        not item["response"]["generic_fallback"]
        and ("?" in item["text"] or "？" in item["text"])
        for item in responses
    )
    normalized_texts = [_normalized(item["text"]).casefold() for item in responses]
    return {
        "planned_responses": planned,
        "substantive_follow_ups": follow_ups,
        "generic_fallbacks": generic,
        "generic_fallback_share": (generic / planned if planned else 0.0),
        "repeated_responses": planned - len(set(normalized_texts)),
        "provenance_complete": sum(
            item["response"]["plan"].get("provenance_verified") is True
            for item in responses
        ),
        "observed_responses": sum(
            item["response"]["status"] == "observed" for item in responses
        ),
        "experience_candidates": sum(
            len(item["response"]["experience_candidates"]) for item in responses
        ),
    }
