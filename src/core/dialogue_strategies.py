"""Отдельная память диалоговых стратегий без влияния на действия и ценности.

P2: хранение, явный feedback, атрибуция, взвешивание, восстановление,
подтверждаемые preferences и детерминированный выбор только в whitelist.
"""

from __future__ import annotations

import math


STRATEGY_WHITELIST = {"unknown": ("learning_question", "unknown_listen")}
FEEDBACK_KINDS = frozenset({"support", "opposition"})
FEEDBACK_TARGET_TTL_CYCLES = 50
# Учебные вопросы допускаются не чаще одного раза в 1200 циклов.
# Сигнал должен переживать минимум три таких интервала, иначе реальные
# отзывы никогда не накапливаются до порога смены стратегии.
STRATEGY_OUTCOME_HALF_LIFE_CYCLES = 5000
STRATEGY_MIN_RESPONSES = 3
STRATEGY_SIGNAL_MIN = 1.0
RECENT_RESPONSE_IDS_MAX = 20
RESPONSE_ID_MAX_LEN = 160


def _finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _valid_cycle(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_response_id(value) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= RESPONSE_ID_MAX_LEN


def _valid_pair(context_key, strategy_id) -> bool:
    return strategy_id in STRATEGY_WHITELIST.get(context_key, ())


_FEEDBACK_FORMS = {
    "так понятно": "support",
    "теперь понятно": "support",
    "так лучше": "support",
    "не то": "opposition",
    "ты меня не поняла": "opposition",
    "ты меня не понял": "opposition",
}
_QUESTION_OPPOSITION_FORMS = frozenset(
    {"не задавай таких вопросов", "не надо таких вопросов"}
)


PREFERENCE_CONTEXT_PREFIX = "dialogue_strategy_preference:"
_PREFERENCE_REQUESTS = {
    "в таких случаях не задавай вопросов": "unknown_listen",
    "в таких случаях спрашивай": "learning_question",
}
_PREFERENCE_CONFIRM_ANSWERS = frozenset(
    {"да", "подтверждаю", "верно", "согласен", "согласна"}
)
_PREFERENCE_REJECT_ANSWERS = frozenset(
    {"нет", "отмена", "не надо", "не учи", "не запоминай"}
)


def _normalize_exact(text):
    if not isinstance(text, str):
        return ""
    normalized = " ".join(text.lower().split())
    if not normalized or "?" in normalized or "？" in normalized:
        return ""
    return normalized.strip(" .!…")


def parse_feedback(text, strategy_id):
    """Распознать только полную явную оценку, без угадывания контекста."""
    normalized = _normalize_exact(text)
    if not normalized or not _valid_pair("unknown", strategy_id):
        return None
    if strategy_id == "learning_question" and normalized in _QUESTION_OPPOSITION_FORMS:
        return "opposition"
    return _FEEDBACK_FORMS.get(normalized)


def parse_preference_request(text):
    """Вернуть стратегию только для точной scoped просьбы человека."""
    return _PREFERENCE_REQUESTS.get(_normalize_exact(text))


def is_forget_preference_request(text):
    return _normalize_exact(text) == "забудь правило для таких ответов"


def build_preference_proposal(strategy, action="set"):
    """Собрать отдельный вопрос; сама функция память не изменяет."""
    if not _valid_pair("unknown", strategy) or action not in {"set", "forget"}:
        raise ValueError("unknown dialogue preference proposal")
    if action == "set":
        rule = (
            "не задавать учебных вопросов"
            if strategy == "unknown_listen"
            else "задавать учебный вопрос"
        )
        question = (
            f"Запомнить для непонятных реплик: {rule}? "
            "Это правило можно исправить или забыть. Ответь «да» или «нет»."
        )
    else:
        question = (
            "Забыть правило для непонятных реплик? Старые отзывы останутся "
            "без изменений. Ответь «да» или «нет»."
        )
    return {
        "question": question,
        "context": f"{PREFERENCE_CONTEXT_PREFIX}{action}:{strategy}",
    }


def is_preference_context(context):
    return str(context or "").startswith(PREFERENCE_CONTEXT_PREFIX)


def preference_from_context(context):
    text = str(context or "")
    if not text.startswith(PREFERENCE_CONTEXT_PREFIX):
        return None, None
    payload = text[len(PREFERENCE_CONTEXT_PREFIX) :]
    action, separator, strategy = payload.partition(":")
    if (
        not separator
        or action not in {"set", "forget"}
        or not _valid_pair("unknown", strategy)
    ):
        return None, None
    return action, strategy


def parse_preference_decision(text):
    """True — подтвердить, False — отклонить, None — не менять память."""
    normalized = _normalize_exact(text)
    if normalized in _PREFERENCE_CONFIRM_ANSWERS:
        return True
    if normalized in _PREFERENCE_REJECT_ANSWERS:
        return False
    return None


def _empty_outcome() -> dict:
    return {
        "support": 0.0,
        "opposition": 0.0,
        "response_count": 0,
        "last_cycle": 0,
        "recent_response_ids": [],
    }


def _restore_target(data):
    if not isinstance(data, dict):
        return None
    response_id = data.get("response_id")
    context_key = data.get("context_key")
    strategy_id = data.get("strategy_id")
    cycle = data.get("cycle")
    if (
        not _valid_response_id(response_id)
        or not _valid_pair(context_key, strategy_id)
        or not _valid_cycle(cycle)
    ):
        return None
    return {
        "response_id": response_id,
        "strategy_id": strategy_id,
        "context_key": context_key,
        "cycle": cycle,
    }


def _restore_outcome(data):
    if not isinstance(data, dict):
        return None
    support = data.get("support")
    opposition = data.get("opposition")
    response_count = data.get("response_count")
    last_cycle = data.get("last_cycle")
    recent = data.get("recent_response_ids")
    if (
        not _finite_number(support)
        or not 0.0 <= support
        or not _finite_number(opposition)
        or not 0.0 <= opposition
        or not _valid_cycle(response_count)
        or not _valid_cycle(last_cycle)
        or not isinstance(recent, list)
        or len(recent) > RECENT_RESPONSE_IDS_MAX
    ):
        return None
    clean_ids = []
    for response_id in recent:
        if not _valid_response_id(response_id) or response_id in clean_ids:
            return None
        clean_ids.append(response_id)
    if response_count < len(clean_ids):
        return None
    return {
        "support": float(support),
        "opposition": float(opposition),
        "response_count": response_count,
        "last_cycle": last_cycle,
        "recent_response_ids": clean_ids,
    }


def _restore_preference(data):
    if not isinstance(data, dict):
        return None
    strategy = data.get("strategy")
    cycle = data.get("cycle")
    if data.get("evidence") != "user_taught" or not _valid_cycle(cycle):
        return None
    return {"strategy": strategy, "evidence": "user_taught", "cycle": cycle}


class DialogueStrategyMemory:
    """Свидетельства о приёме ответов, не об их истинности."""

    def __init__(self) -> None:
        self.outcomes = {}
        self.preferences = {}
        self.feedback_target = None

    def register_response(self, response_id, strategy_id, context_key, cycle) -> dict:
        """Зарегистрировать только фактически показанную стратегию."""
        if not _valid_response_id(response_id):
            raise ValueError("response_id")
        if not _valid_pair(context_key, strategy_id):
            raise ValueError("unknown dialogue strategy")
        if not _valid_cycle(cycle):
            raise ValueError("cycle")
        self.feedback_target = {
            "response_id": response_id,
            "strategy_id": strategy_id,
            "context_key": context_key,
            "cycle": cycle,
        }
        return dict(self.feedback_target)

    def current_target(self, cycle):
        """Вернуть копию свежей цели; истёкшая цель очищается."""
        if not _valid_cycle(cycle):
            return None
        target = _restore_target(self.feedback_target)
        if target is None:
            self.feedback_target = None
            return None
        age = cycle - target["cycle"]
        if age < 0 or age > FEEDBACK_TARGET_TTL_CYCLES:
            self.feedback_target = None
            return None
        return dict(target)

    def clear_feedback_target(self) -> None:
        self.feedback_target = None

    def _decayed_entry(self, entry, cycle):
        clean = _restore_outcome(entry) or _empty_outcome()
        age = max(0, cycle - clean["last_cycle"])
        factor = 0.5 ** (age / STRATEGY_OUTCOME_HALF_LIFE_CYCLES)
        clean["support"] *= factor
        clean["opposition"] *= factor
        clean["last_cycle"] = cycle
        return clean

    def signal_at(self, context_key, strategy_id, cycle) -> dict:
        """Активный сигнал без изменения сохранённого состояния."""
        if not _valid_pair(context_key, strategy_id) or not _valid_cycle(cycle):
            return {
                "support": 0.0,
                "opposition": 0.0,
                "response_count": 0,
                "difference": 0.0,
            }
        stored = self.outcomes.get(context_key, {}).get(strategy_id)
        clean = _restore_outcome(stored)
        if clean is None:
            return {
                "support": 0.0,
                "opposition": 0.0,
                "response_count": 0,
                "difference": 0.0,
            }
        decayed = self._decayed_entry(clean, cycle)
        return {
            "support": decayed["support"],
            "opposition": decayed["opposition"],
            "response_count": decayed["response_count"],
            "difference": decayed["opposition"] - decayed["support"],
        }

    def apply_feedback(
        self, response_id, feedback, cycle, *, testimony_weight=1.0
    ) -> dict:
        """Применить один явный отзыв к непосредственно предыдущему ответу."""
        target = self.current_target(cycle)
        if target is None:
            return {"status": "ignored", "reason": "no_target"}
        self.clear_feedback_target()
        if response_id != target["response_id"]:
            return {"status": "ignored", "reason": "target_mismatch"}
        if feedback not in FEEDBACK_KINDS:
            return {"status": "ignored", "reason": "unknown_feedback"}
        if not _finite_number(testimony_weight) or not 0.0 < testimony_weight <= 1.0:
            raise ValueError("testimony_weight")

        context_key = target["context_key"]
        strategy_id = target["strategy_id"]
        by_context = self.outcomes.setdefault(context_key, {})
        entry = self._decayed_entry(
            by_context.get(strategy_id, _empty_outcome()), cycle
        )
        if response_id in entry["recent_response_ids"]:
            return {"status": "duplicate", "response_id": response_id}

        entry[feedback] += float(testimony_weight)
        entry["response_count"] += 1
        entry["last_cycle"] = cycle
        entry["recent_response_ids"] = (entry["recent_response_ids"] + [response_id])[
            -RECENT_RESPONSE_IDS_MAX:
        ]
        by_context[strategy_id] = entry
        return {
            "status": "recorded",
            "response_id": response_id,
            "context_key": context_key,
            "strategy_id": strategy_id,
            "feedback": feedback,
            "weight": float(testimony_weight),
        }

    def set_preference(self, context_key, strategy, cycle) -> dict:
        """Сохранить scoped правило после внешнего явного подтверждения."""
        if not _valid_pair(context_key, strategy):
            raise ValueError("unknown dialogue strategy")
        if not _valid_cycle(cycle):
            raise ValueError("cycle")
        self.preferences[context_key] = {
            "strategy": strategy,
            "evidence": "user_taught",
            "cycle": cycle,
        }
        return dict(self.preferences[context_key])

    def preference_for(self, context_key):
        preference = _restore_preference(self.preferences.get(context_key))
        if preference is None or not _valid_pair(context_key, preference["strategy"]):
            return None
        return dict(preference)

    def clear_preference(self, context_key) -> bool:
        return self.preferences.pop(context_key, None) is not None

    def select_strategy(self, context_key, cycle) -> dict:
        """Детерминированный выбор без exploration и без мутации памяти."""
        if context_key not in STRATEGY_WHITELIST:
            raise ValueError("unknown strategy context")
        if not _valid_cycle(cycle):
            raise ValueError("cycle")
        preference = self.preference_for(context_key)
        if preference is not None:
            return {
                "strategy_id": preference["strategy"],
                "reason": "confirmed_preference",
            }
        signal = self.signal_at(context_key, "learning_question", cycle)
        if (
            signal["response_count"] >= STRATEGY_MIN_RESPONSES
            and signal["difference"] >= STRATEGY_SIGNAL_MIN
        ):
            return {
                "strategy_id": "unknown_listen",
                "reason": "weighted_feedback",
            }
        reason = (
            "decayed_return"
            if signal["response_count"] >= STRATEGY_MIN_RESPONSES
            and signal["opposition"] > 0.0
            else "baseline"
        )
        return {"strategy_id": "learning_question", "reason": reason}

    def get_status(self) -> dict:
        return {
            "contexts": len(self.outcomes),
            "preferences": len(self.preferences),
            "has_feedback_target": self.feedback_target is not None,
        }

    def to_dict(self) -> dict:
        return {
            "outcomes": {
                context: {
                    strategy: dict(
                        entry,
                        recent_response_ids=list(entry["recent_response_ids"]),
                    )
                    for strategy, entry in strategies.items()
                }
                for context, strategies in self.outcomes.items()
            },
            "preferences": {
                context: dict(entry) for context, entry in self.preferences.items()
            },
            "feedback_target": (
                dict(self.feedback_target) if self.feedback_target is not None else None
            ),
        }

    def load_from(self, data) -> None:
        """Безопасно восстановить только whitelist-записи; дефекты пропускаются."""
        self.outcomes = {}
        self.preferences = {}
        self.feedback_target = None
        if not isinstance(data, dict):
            return

        outcomes = data.get("outcomes")
        if isinstance(outcomes, dict):
            for context_key, strategies in outcomes.items():
                if context_key not in STRATEGY_WHITELIST or not isinstance(
                    strategies, dict
                ):
                    continue
                clean_strategies = {}
                for strategy_id, raw in strategies.items():
                    if not _valid_pair(context_key, strategy_id):
                        continue
                    clean = _restore_outcome(raw)
                    if clean is not None:
                        clean_strategies[strategy_id] = clean
                if clean_strategies:
                    self.outcomes[context_key] = clean_strategies

        preferences = data.get("preferences")
        if isinstance(preferences, dict):
            for context_key, raw in preferences.items():
                clean = _restore_preference(raw)
                if clean is None or not _valid_pair(context_key, clean["strategy"]):
                    continue
                self.preferences[context_key] = clean

        self.feedback_target = _restore_target(data.get("feedback_target"))
