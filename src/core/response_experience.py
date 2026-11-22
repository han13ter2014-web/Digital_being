"""Явный план ответа, ожидание и наблюдаемый результат реплики.

Composer получает уже выбранный детерминированный ответ. Он может добавить
только разрешённый ``SpeechImitation`` оборот, но не создаёт факты, эмоции,
воспоминания или намерения. Все заявленные ссылки проверяются до доставки.
Отсутствие реакции истекает как ``no_observed_reaction``, а не как успех.
"""

from __future__ import annotations

from copy import deepcopy

from src.core.dialogue_acts import (
    ACT_ANSWER,
    ACT_FOLLOW_UP,
    ACT_UNKNOWN,
)
from src.core.chinese_dialogue import (
    parse_chinese_feedback,
    validate_chinese_realization_plan,
)
from src.core.emotional_state import EMOTIONS
from src.core.english_dialogue import (
    parse_english_feedback,
    validate_english_realization_plan,
)
from src.core.language_context import (
    LanguageContext,
    legacy_language_context,
    validate_language_context,
)
from src.core.speech_imitation import (
    SpeechImitation,
    is_safe_expression,
    normalize_expression,
)
from src.core.speech_imitation import validate_speech_imitation as validate_imitation
from src.core.semantic_response_plan import SemanticResponsePlan

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
MAX_RESPONSES = 64
MAX_REFERENCES = 8
RESPONSE_ID_MAX_LEN = 160
TEXT_MAX_LEN = 4000
INPUT_MAX_LEN = 500
CONTEXT_MAX_LEN = 80
SOURCE_MAX_LEN = 80
PROFILE_ID_MAX_LEN = 160
RESPONSE_TTL_CYCLES = 50
CONSOLIDATED_RESPONSE_HISTORY = 32

REFERENCE_KINDS = frozenset({"state", "concept", "episode", "affect", "dialogue_act"})
STATE_REFERENCES = frozenset(
    {"name", "cycle_count", "energy", "active_profile", "emotional_state"}
)
RESPONSE_STATUSES = frozenset({"pending", "observed", "expired"})
EXPECTED_REACTIONS = frozenset(
    {
        "explicit_feedback_or_relevant_reply",
        "answer_or_feedback",
        "continuation_or_support",
    }
)
UNCERTAINTIES = frozenset({"input_meaning", "borrowed_expression_fit"})
OUTCOMES = frozenset(
    {
        "answer",
        "follow_up",
        "unclassified_reply",
        "ordinary_reply",
        "explicit_support",
        "explicit_opposition",
        "no_observed_reaction",
    }
)
_GENERIC_FEEDBACK = {
    "так понятно": "support",
    "теперь понятно": "support",
    "так лучше": "support",
    "не то": "opposition",
    "ты меня не поняла": "opposition",
    "ты меня не понял": "opposition",
}


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _cycle(value, path="cycle"):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "expected a nonnegative integer")


def _text(value, path, limit, *, nonempty=True):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or nonempty
        and not value.strip()
    ):
        _fail(path, "expected a bounded string")


def parse_generic_feedback(text, *, language="ru"):
    if language == "en":
        return parse_english_feedback(text)
    if language == "zh":
        return parse_chinese_feedback(text)
    normalized = " ".join(str(text or "").replace("’", "'").lower().split()).strip(
        " .!…"
    )
    if not normalized or "?" in normalized or "？" in normalized:
        return None
    return _GENERIC_FEEDBACK.get(normalized)


def _validate_reference(reference, path) -> None:
    if not isinstance(reference, dict):
        _fail(path, "expected a dictionary")
    if reference.get("kind") not in REFERENCE_KINDS:
        _fail(f"{path}.kind", "unknown reference kind")
    _text(reference.get("id"), f"{path}.id", 160)
    if reference["kind"] == "state" and reference["id"] not in STATE_REFERENCES:
        _fail(f"{path}.id", "unknown state reference")
    if reference["kind"] == "affect" and reference["id"] not in EMOTIONS:
        _fail(f"{path}.id", "unknown affect reference")


def _validate_plan(plan, path="plan") -> None:
    if not isinstance(plan, dict):
        _fail(path, "expected a dictionary")
    _text(
        plan.get("observed_input"),
        f"{path}.observed_input",
        INPUT_MAX_LEN,
        nonempty=False,
    )
    _text(plan.get("intention"), f"{path}.intention", 80)
    _text(plan.get("context"), f"{path}.context", CONTEXT_MAX_LEN)
    _text(plan.get("source"), f"{path}.source", SOURCE_MAX_LEN)
    references = plan.get("references")
    if not isinstance(references, list) or len(references) > MAX_REFERENCES:
        _fail(f"{path}.references", "expected a bounded list")
    for index, reference in enumerate(references):
        _validate_reference(reference, f"{path}.references[{index}]")
    state = plan.get("state")
    if not isinstance(state, dict):
        _fail(f"{path}.state", "expected a dictionary")
    _cycle(state.get("cycle"), f"{path}.state.cycle")
    _text(
        state.get("profile_id"),
        f"{path}.state.profile_id",
        PROFILE_ID_MAX_LEN,
        nonempty=False,
    )
    language_context = plan.get("language_context")
    if language_context is not None:
        validate_language_context(language_context, f"{path}.language_context")
        if language_context["profile_id"] != state["profile_id"]:
            _fail(f"{path}.language_context", "profile does not match response state")
    if plan.get("components") != ["deterministic_reply"] and plan.get("components") != [
        "deterministic_reply",
        "borrowed_expression",
    ]:
        _fail(f"{path}.components", "unsupported response components")
    if plan.get("provenance_verified") is not True:
        _fail(f"{path}.provenance_verified", "references must be verified")
    realization = plan.get("realization")
    if not isinstance(realization, dict):
        _fail(f"{path}.realization", "expected a dictionary")
    if realization.get("kind") not in {"fixed_template", "borrowed_prefix"}:
        _fail(f"{path}.realization.kind", "unknown realization")
    _text(realization.get("base_text"), f"{path}.realization.base_text", TEXT_MAX_LEN)
    _text(realization.get("text"), f"{path}.realization.text", TEXT_MAX_LEN)
    borrowed = plan.get("borrowed")
    response_language = (language_context or {}).get("response_language", "ru")
    semantic_data = plan.get("semantic_response_plan")
    if semantic_data is not None:
        try:
            semantic = SemanticResponsePlan.from_dict(semantic_data)
        except ValueError as error:
            _fail(f"{path}.semantic_response_plan", str(error))
        if semantic.baseline_text != realization["base_text"]:
            _fail(
                f"{path}.semantic_response_plan.baseline_text",
                "must match realization.base_text",
            )
        if semantic.cycle != state["cycle"]:
            _fail(f"{path}.semantic_response_plan.cycle", "must match state.cycle")
        if semantic.language != response_language:
            _fail(
                f"{path}.semantic_response_plan.language",
                "must match the response language",
            )
    if borrowed is None:
        if realization["kind"] != "fixed_template" or len(plan["components"]) != 1:
            _fail(f"{path}.borrowed", "missing borrowed component")
    else:
        if not isinstance(borrowed, dict):
            _fail(f"{path}.borrowed", "expected a dictionary")
        borrowed_language = borrowed.get("language_id", "ru")
        if borrowed_language not in {"ru", "en"}:
            _fail(f"{path}.borrowed.language_id", "unsupported language")
        if borrowed_language != response_language:
            _fail(f"{path}.borrowed.language_id", "language does not match the plan")
        if not is_safe_expression(
            borrowed.get("expression"), borrowed.get("context"), borrowed_language
        ):
            _fail(f"{path}.borrowed.expression", "unsafe expression")
        if borrowed["expression"] != normalize_expression(borrowed["expression"]):
            _fail(f"{path}.borrowed.expression", "expected normalized expression")
        _text(
            borrowed.get("profile_id"),
            f"{path}.borrowed.profile_id",
            PROFILE_ID_MAX_LEN,
        )
        if borrowed["profile_id"] != state["profile_id"]:
            _fail(
                f"{path}.borrowed.profile_id", "profile does not match response state"
            )
        if borrowed.get("level") not in {"situational", "habit"}:
            _fail(f"{path}.borrowed.level", "expression is not available for use")
        if realization["kind"] != "borrowed_prefix" or len(plan["components"]) != 2:
            _fail(f"{path}.borrowed", "inconsistent borrowed component")
    validate_english_realization_plan(plan)
    validate_chinese_realization_plan(plan)


def validate_response_plan(plan, path="plan") -> None:
    """Публичная проверка плана для session-scoped внешних ответов."""
    _validate_plan(plan, path)


def validate_response_experience(data) -> None:
    if (
        not isinstance(data, dict)
        or data.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS
    ):
        _fail("response_experience", "unsupported snapshot")
    responses = data.get("responses")
    if not isinstance(responses, list) or len(responses) > MAX_RESPONSES:
        _fail("response_experience.responses", "expected a bounded list")
    response_ids = set()
    for index, response in enumerate(responses):
        path = f"response_experience.responses[{index}]"
        if not isinstance(response, dict):
            _fail(path, "expected a dictionary")
        response_id = response.get("response_id")
        _text(response_id, f"{path}.response_id", RESPONSE_ID_MAX_LEN)
        if response_id in response_ids:
            _fail(path, "duplicate response ID")
        response_ids.add(response_id)
        _cycle(response.get("cycle"), f"{path}.cycle")
        _validate_plan(response.get("plan"), f"{path}.plan")
        if response["plan"]["state"]["cycle"] != response["cycle"]:
            _fail(f"{path}.cycle", "response and plan cycles must match")
        semantic_data = response["plan"].get("semantic_response_plan")
        if semantic_data is not None and semantic_data["response_id"] != response_id:
            _fail(
                f"{path}.plan.semantic_response_plan.response_id",
                "must match the delivered response ID",
            )
        if response.get("expected_reaction") not in EXPECTED_REACTIONS:
            _fail(f"{path}.expected_reaction", "unknown expectation")
        uncertainties = response.get("uncertainties")
        if not isinstance(uncertainties, list) or any(
            item not in UNCERTAINTIES for item in uncertainties
        ):
            _fail(f"{path}.uncertainties", "unknown uncertainty")
        status = response.get("status")
        outcome = response.get("outcome")
        if status not in RESPONSE_STATUSES:
            _fail(f"{path}.status", "unknown response status")
        if status == "pending" and outcome is not None:
            _fail(f"{path}.outcome", "pending response cannot have an outcome")
        if status != "pending" and outcome not in OUTCOMES:
            _fail(f"{path}.outcome", "unknown observed outcome")
        if status == "expired" and outcome != "no_observed_reaction":
            _fail(f"{path}.outcome", "expiration is not a successful outcome")
    latest = data.get("latest_response_id")
    if latest is not None and latest not in response_ids:
        _fail("response_experience.latest_response_id", "unknown response ID")
    validate_imitation(data.get("imitation"))
    by_id = {item["response_id"]: item for item in responses}
    for response_id, link in data["imitation"]["response_links"].items():
        response = by_id.get(response_id)
        if response is None:
            continue
        borrowed = response["plan"]["borrowed"]
        if borrowed is None:
            _fail("response_experience.imitation.response_links", "unexpected link")
        expression = link if isinstance(link, str) else link["expression"]
        language_id = "ru" if isinstance(link, str) else link["language_id"]
        if expression != borrowed["expression"] or language_id != borrowed.get(
            "language_id", "ru"
        ):
            _fail("response_experience.imitation.response_links", "plan mismatch")


class ResponseExperience:
    """Персональная память планов, ожиданий и заимствований."""

    def __init__(self) -> None:
        self.responses = {}
        self.latest_response_id = None
        self.imitation = SpeechImitation()
        # Только runtime-наблюдатель: в Core snapshot и checkpoint не входит.
        self._transition_observer = None

    @property
    def transition_observer(self):
        return self._transition_observer

    def set_transition_observer(self, observer) -> None:
        if observer is not None and not callable(observer):
            raise TypeError("transition observer: expected callable or None")
        self._transition_observer = observer

    def _notify_transition(self, transition_kind, record, cycle) -> None:
        observer = self._transition_observer
        if observer is None:
            return
        try:
            observer(transition_kind, deepcopy(record), cycle=cycle)
        except Exception:
            # Дополнительная наблюдаемость не может отменить реальный переход.
            pass

    def note_core_restore(self, cycle) -> None:
        """Обозначить расхождение Core snapshot и независимого журнала."""
        self._notify_transition("core_restored", None, cycle)

    @staticmethod
    def _verify_reference(agent, reference) -> dict:
        if not isinstance(reference, dict):
            raise ValueError("reference: expected a dictionary")
        kind = reference.get("kind")
        target_id = reference.get("id")
        _validate_reference(reference, "reference")
        if kind == "state":
            if target_id == "active_profile":
                registry = getattr(agent, "social_registry", None)
                exists = bool(getattr(registry, "current_profile_id", ""))
            else:
                exists = getattr(agent, target_id, None) is not None
        elif kind == "concept":
            models = getattr(agent, "mental_models", None)
            exists = target_id in getattr(models, "concepts", {})
        elif kind == "episode":
            memory = getattr(agent, "long_term_memory", None)
            checker = getattr(memory, "has_episode", None)
            exists = callable(checker) and checker(target_id)
        elif kind == "dialogue_act":
            interaction = getattr(agent, "user_interaction", None)
            ring = getattr(interaction, "dialogue_act_ring", None)
            exists = ring is not None and any(
                item.get("kind") == target_id
                for item in ring.fresh_acts(
                    getattr(agent, "cycle_count", 0), limit=ring.size
                )
            )
        else:
            emotional = getattr(agent, "emotional_state", None)
            exists = float(getattr(emotional, "levels", {}).get(target_id, 0.0)) > 0.0
        if not exists:
            raise ValueError(f"reference: real {kind}:{target_id} is required")
        return {"kind": kind, "id": target_id}

    @staticmethod
    def _expectation(context):
        if context in {"unknown_reply", "unknown_listen"}:
            return "continuation_or_support", ["input_meaning"]
        if context in {"dialogue_learning", "dialogue_feedback"}:
            return "answer_or_feedback", []
        return "explicit_feedback_or_relevant_reply", []

    def expire(self, cycle) -> int:
        """Истечение ожидания фиксирует отсутствие наблюдения, не успех."""
        _cycle(cycle)
        expired = 0
        for response in self.responses.values():
            if response["status"] != "pending":
                continue
            age = cycle - response["cycle"]
            if age < 0 or age <= RESPONSE_TTL_CYCLES:
                continue
            response["status"] = "expired"
            response["outcome"] = "no_observed_reaction"
            expired += 1
            self._notify_transition("expired", response, cycle)
        return expired

    def consolidate(self, cycle) -> dict:
        """Ограничить историю, не превращая повторный сон в новый опыт."""
        expired = self.expire(cycle)
        terminal_ids = [
            response_id
            for response_id, response in self.responses.items()
            if response["status"] != "pending"
        ]
        excess = max(0, len(terminal_ids) - CONSOLIDATED_RESPONSE_HISTORY)
        pruned_ids = set(terminal_ids[:excess])
        for response_id in pruned_ids:
            record = self.responses.pop(response_id)
            self._notify_transition("record_pruned", record, cycle)
        if self.latest_response_id in pruned_ids:
            # Не переносим будущий отзыв на более старое ожидание.
            self.latest_response_id = None

        pending_ids = {
            response_id
            for response_id, response in self.responses.items()
            if response["status"] == "pending"
        }
        stale_links = [
            response_id
            for response_id in self.imitation.response_links
            if response_id not in pending_ids
        ]
        for response_id in stale_links:
            del self.imitation.response_links[response_id]
        return {
            "expired_responses": expired,
            "pruned_responses": len(pruned_ids),
            "stale_response_links": len(stale_links),
        }

    def prepare_plan(
        self,
        agent,
        text,
        *,
        context,
        source,
        user_text="",
        references=(),
        borrow_context="",
        profile_id="",
        language_context=None,
        english_realization=None,
        chinese_realization=None,
        expire_pending=True,
        semantic_response_plan=None,
    ) -> dict:
        """Проверить ссылки и составить план до фактической доставки.

        Внешний session-scoped план задаёт профиль явно и не истекает ожидания
        локального собеседника. По умолчанию прежнее поведение не меняется.
        Языковая realization допускается только как проверяемое правило.
        """
        cycle = int(agent.cycle_count)
        _cycle(cycle)
        _text(text, "text", TEXT_MAX_LEN)
        _text(context, "context", CONTEXT_MAX_LEN)
        _text(source, "source", SOURCE_MAX_LEN)
        if (
            not isinstance(references, (list, tuple))
            or len(references) > MAX_REFERENCES
        ):
            raise ValueError("references: expected a bounded sequence")
        clean_references = [self._verify_reference(agent, item) for item in references]
        registry = getattr(agent, "social_registry", None)
        current_profile_id = str(getattr(registry, "current_profile_id", "") or "")
        external_profile = bool(profile_id and profile_id != current_profile_id)
        profile_id = str(profile_id or current_profile_id)
        if language_context is None and not external_profile:
            attribution = getattr(agent, "social_attribution", None)
            if attribution is not None:
                language_context = attribution.current_language_context().to_dict()
            elif profile_id:
                language_context = legacy_language_context(profile_id).to_dict()
        elif language_context is not None:
            if isinstance(language_context, LanguageContext):
                language_context = language_context.to_dict()
            else:
                language_context = LanguageContext.from_dict(language_context).to_dict()
        if english_realization is not None and chinese_realization is not None:
            raise ValueError("language realization: expected only one language rule")
        if english_realization is not None:
            if not isinstance(english_realization, dict):
                raise ValueError("english realization: expected a dictionary")
            if english_realization.get("text") != text:
                raise ValueError("english realization: input text does not match rule")
        if chinese_realization is not None:
            if not isinstance(chinese_realization, dict):
                raise ValueError("chinese realization: expected a dictionary")
            if chinese_realization.get("text") != text:
                raise ValueError("chinese realization: input text does not match rule")
        response_language = (language_context or {}).get("response_language", "ru")
        borrowed = None
        composed = str(text)
        if borrow_context and profile_id:
            candidate = self.imitation.candidate(
                context=borrow_context,
                profile_id=profile_id,
                cycle=cycle,
                language_id=response_language,
            )
            if candidate is not None:
                expression = candidate["expression"]
                borrowed = {
                    "expression": expression,
                    "context": borrow_context,
                    "profile_id": profile_id,
                    "language_id": response_language,
                    "level": candidate["level"],
                }
                composed = expression[:1].upper() + expression[1:] + ". " + composed
        _text(composed, "composed text", TEXT_MAX_LEN)
        plan = {
            "observed_input": str(user_text or "")[:INPUT_MAX_LEN],
            "intention": self._intention(context),
            "context": context,
            "source": source,
            "references": clean_references,
            "state": {"cycle": cycle, "profile_id": profile_id},
            "components": ["deterministic_reply"],
            "realization": {
                "kind": "fixed_template",
                "base_text": str(text),
                "text": composed,
            },
            "provenance_verified": True,
            "borrowed": None,
        }
        if semantic_response_plan is not None:
            if not isinstance(semantic_response_plan, SemanticResponsePlan):
                raise ValueError(
                    "semantic_response_plan: expected SemanticResponsePlan or None"
                )
            plan["semantic_response_plan"] = deepcopy(semantic_response_plan.to_dict())
        language_realization = english_realization or chinese_realization
        if language_realization is not None:
            plan["realization"].update(
                deepcopy(
                    {
                        key: language_realization.get(key)
                        for key in (
                            "language_id",
                            "rule_id",
                            "fallback_policy",
                            "act",
                            "evidence",
                        )
                    }
                )
            )
        if language_context is not None:
            plan["language_context"] = deepcopy(language_context)
        if borrowed is not None:
            plan["components"].append("borrowed_expression")
            plan["realization"]["kind"] = "borrowed_prefix"
            plan["borrowed"] = borrowed
        _validate_plan(plan)
        if expire_pending:
            self.expire(cycle)
        return {"text": composed, "plan": plan}

    @staticmethod
    def _intention(context):
        if context in {"unknown_reply", "unknown_listen"}:
            return "acknowledge_uncertainty"
        if context == "social_reply":
            return "social_acknowledgement"
        if context == "dialogue_feedback":
            return "acknowledge_feedback"
        if "question" in context or "clarification" in context:
            return "clarify"
        return "answer_from_existing_state"

    @staticmethod
    def _response_language(record) -> str:
        plan = record.get("plan") or {}
        context = plan.get("language_context") or {}
        return context.get("response_language", "ru")

    def latest_pending(self, *, language_id="ru") -> dict | None:
        """Найти свежее ожидание активного языка, не закрывая другое."""
        for record in reversed(list(self.responses.values())):
            if (
                record["status"] == "pending"
                and self._response_language(record) == language_id
            ):
                return record
        return None

    def register_delivery(self, response_id, plan, cycle) -> dict:
        """Сохранить ожидание только для фактически отправленного ответа."""
        _text(response_id, "response_id", RESPONSE_ID_MAX_LEN)
        _cycle(cycle)
        _validate_plan(plan)
        semantic_data = plan.get("semantic_response_plan")
        if semantic_data is not None and semantic_data["response_id"] != response_id:
            raise ValueError(
                "semantic_response_plan.response_id: must match delivered response ID"
            )
        if response_id in self.responses:
            raise ValueError("response_id: duplicate")
        if len(self.responses) >= MAX_RESPONSES:
            oldest = next(iter(self.responses))
            pruned = self.responses.pop(oldest)
            self._notify_transition("record_pruned", pruned, cycle)
            if self.latest_response_id == oldest:
                self.latest_response_id = None
        expected, uncertainties = self._expectation(plan["context"])
        if plan["borrowed"] is not None:
            uncertainties.append("borrowed_expression_fit")
        record = {
            "response_id": response_id,
            "cycle": cycle,
            "plan": deepcopy(plan),
            "expected_reaction": expected,
            "uncertainties": uncertainties,
            "status": "pending",
            "outcome": None,
        }
        self.responses[response_id] = record
        self.latest_response_id = response_id
        borrowed = plan["borrowed"]
        if borrowed is not None:
            self.imitation.mark_used(
                borrowed["expression"],
                context=borrowed["context"],
                profile_id=borrowed["profile_id"],
                response_id=response_id,
                cycle=cycle,
                language_id=borrowed.get("language_id", "ru"),
            )
        return deepcopy(record)

    def observe_reply(self, act_kind, cycle, *, language_id=None) -> dict | None:
        """Зафиксировать обычную реплику без интерпретации её как успеха."""
        self.expire(cycle)
        if language_id is None:
            response_id = self.latest_response_id
            record = self.responses.get(response_id)
        else:
            record = self.latest_pending(language_id=language_id)
        if record is None or record["status"] != "pending":
            return None
        outcome = {
            ACT_ANSWER: "answer",
            ACT_FOLLOW_UP: "follow_up",
            ACT_UNKNOWN: "unclassified_reply",
        }.get(act_kind, "ordinary_reply")
        record["status"] = "observed"
        record["outcome"] = outcome
        self._notify_transition("outcome", record, cycle)
        return deepcopy(record)

    def observe_feedback(
        self, response_id, feedback, cycle, *, language_id=None
    ) -> dict | None:
        """Применить явный отзыв к ответу и конкретному обороту."""
        self.expire(cycle)
        record = self.responses.get(response_id)
        if (
            record is None
            or record["status"] != "pending"
            or feedback not in {"support", "opposition"}
            or language_id is not None
            and self._response_language(record) != language_id
        ):
            return None
        record["status"] = "observed"
        record["outcome"] = (
            "explicit_support" if feedback == "support" else "explicit_opposition"
        )
        borrowed = record["plan"]["borrowed"]
        if borrowed is not None:
            self.imitation.apply_feedback(
                response_id,
                feedback,
                profile_id=borrowed["profile_id"],
                cycle=cycle,
                language_id=borrowed.get("language_id", "ru"),
            )
        self._notify_transition("outcome", record, cycle)
        return deepcopy(record)

    def get_status(self) -> dict:
        return {
            "responses": len(self.responses),
            "pending": sum(
                item["status"] == "pending" for item in self.responses.values()
            ),
            "imitation_expressions": len(self.imitation.expressions),
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "responses": [deepcopy(item) for item in self.responses.values()],
            "latest_response_id": self.latest_response_id,
            "imitation": self.imitation.to_dict(),
        }

    def load_from(self, data) -> None:
        validate_response_experience(data)
        self.responses = {
            item["response_id"]: deepcopy(item) for item in data["responses"]
        }
        self.latest_response_id = data["latest_response_id"]
        self.imitation = SpeechImitation()
        self.imitation.load_from(data["imitation"])
