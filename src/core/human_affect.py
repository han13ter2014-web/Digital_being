"""Наблюдаемый аффект человека: узкий векторный разбор без LLM.

Компоненты — силы активации явных словесных маркеров, не вероятности и не
выводы о личности. Любое сообщение человека — свидетельство, а не истина:
его влияние взвешивается через текущие доверие и близость. Контекст может
подтвердить только разделённость уже распознанной реплики; сам по себе он
новый аффект не создаёт.
"""

from __future__ import annotations

import math
import re


AFFECT_COMPONENTS = ("joy", "sadness", "calm", "anxiety")
NEGATIVE_AFFECT_COMPONENTS = ("sadness", "anxiety")
AFFECT_EVIDENCE_KINDS = frozenset({"self_report", "user_taught"})
AFFECT_PHRASE_MAX_LEN = 80

BASE_AFFECT_ACTIVATION = 0.70
WEAK_AFFECT_MODIFIER_SCALE = 0.50
STRONG_AFFECT_MODIFIER_SCALE = 1.25
AFFECT_HALF_LIFE_CYCLES = 16
AFFECT_HARD_TTL_CYCLES = 50
NEGATIVE_AFFECT_THRESHOLD = 0.20
AFFECT_ATTENTION_WEIGHTS = (1.0, 0.5, 0.25)
DEFAULT_TESTIMONY_WEIGHT = 0.50
MIN_TESTIMONY_WEIGHT = 0.20

AFFECT_LABELS = {
    "joy": "радость",
    "sadness": "грусть",
    "calm": "спокойствие",
    "anxiety": "тревога",
}

_FORM_COMPONENTS = {
    "радостно": "joy",
    "рад": "joy",
    "рада": "joy",
    "счастлив": "joy",
    "счастлива": "joy",
    "грустно": "sadness",
    "грущу": "sadness",
    "спокойно": "calm",
    "спокоен": "calm",
    "спокойна": "calm",
    "тревожно": "anxiety",
    "тревожусь": "anxiety",
}

_WEAK_MODIFIERS = frozenset({"немного", "чуть-чуть", "слегка"})
_STRONG_MODIFIERS = frozenset({"очень", "сильно", "крайне"})
_MODIFIER_RE = re.compile(r"немного|чуть-чуть|слегка|очень|сильно|крайне")
_STATIC_REPORT_RE = re.compile(
    r"^(?P<shared>и\s+)?(?P<subject>мне|я)\s+(?P<too>тоже\s+)?"
    r"(?P<mods>(?:(?:немного|чуть-чуть|слегка|очень|сильно|крайне)\s+)*)"
    r"(?P<form>радостно|грустно|спокойно|тревожно|счастлива|счастлив|"
    r"спокойна|спокоен|тревожусь|грущу|рада|рад)"
    r"(?P<tail>(?:\s|[,.;:!?…—-]).*)?$"
)
_CONTRAST_SPLIT_RE = re.compile(r"\s+(?:но|зато|однако)\s+")
_NEGATION_RE = re.compile(r"(?:^|\s)не(?:\s|$)")
_QUOTE_CHARS = frozenset('"«»“”„')

_TEACHING_EMOTIONS = {
    "радость": "joy",
    "радостно": "joy",
    "грусть": "sadness",
    "грустно": "sadness",
    "спокойствие": "calm",
    "спокойно": "calm",
    "тревога": "anxiety",
    "тревожно": "anxiety",
}
_TEACHING_EMOTION_RE = "|".join(_TEACHING_EMOTIONS)
_QUOTED_TEACHING_RE = re.compile(
    r"^запомни\s*[:：]?\s*[«\"“](?P<phrase>.+?)[»\"”]\s*"
    r"(?:—|-|=|:)?\s*это\s+(?P<emotion>" + _TEACHING_EMOTION_RE + r")\.?$"
)
_PLAIN_TEACHING_RE = re.compile(
    r"^запомни\s+(?:фразу\s+)?(?P<phrase>.+?)\s+(?:—|-|=)\s*"
    r"это\s+(?P<emotion>" + _TEACHING_EMOTION_RE + r")\.?$"
)
_DEFAULT_TEACHING_RE = re.compile(
    r"^это\s+(?:(?:моя|значит|означает)\s+)?(?P<emotion>"
    + _TEACHING_EMOTION_RE
    + r")\.?$"
)
_HABIT_TEACHING_RE = re.compile(
    r"^это\s+я\s+так\s+говорю\s*,?\s*когда\s+(?P<report>.+)$"
)


def normalize_affect_phrase(text) -> str:
    """Нормализовать точную фразу без нечёткого сходства."""
    normalized = " ".join(str(text or "").lower().replace("ё", "е").split())
    return normalized.strip(" \t\r\n.!?…:;\"'«»„“”")


def _cycle(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        if not math.isfinite(value):
            return 0
    except OverflowError:
        return 0
    return max(0, int(value))


def _finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _unit_number(value, default=0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def attachment_testimony_weight(attachment) -> float:
    """Взвесить свидетельство через доверие и близость, не объявляя его фактом.

    Доверие вносит 70%, близость — 30% относительной части. Нижняя граница
    оставляет возможность вежливо услышать даже недоверенный источник; верхняя
    не меняет epistemic статус записи ``self_report`` / ``user_taught``.
    """
    if attachment is None:
        return DEFAULT_TESTIMONY_WEIGHT
    try:
        trust = _unit_number(attachment.trust_factor("user"), 0.5)
    except Exception:
        trust = 0.5
    intimacy = 0.0
    try:
        status = attachment.get_status()
        active_key = status.get("active_user_key", "user")
        user = status.get("attachments", {}).get(active_key, {})
        intimacy = _unit_number(user.get("intimacy"), 0.0)
    except Exception:
        pass
    relational = 0.7 * trust + 0.3 * intimacy
    return round(MIN_TESTIMONY_WEIGHT + 0.8 * relational, 6)


def _clean_components(value):
    if not isinstance(value, dict):
        return None
    cleaned = {}
    for name, raw in value.items():
        if name not in AFFECT_COMPONENTS:
            return None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        try:
            number = float(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            return None
        if number > 0.0:
            cleaned[name] = number
    return cleaned or None


def restore_affect(data, *, include_metadata=False):
    """Безопасно восстановить дескриптор; повреждение → None."""
    if not isinstance(data, dict):
        return None
    components = _clean_components(data.get("components"))
    evidence = data.get("evidence")
    testimony_weight = data.get("testimony_weight")
    cycle = data.get("cycle")
    if (
        components is None
        or evidence not in AFFECT_EVIDENCE_KINDS
        or isinstance(testimony_weight, bool)
        or not isinstance(testimony_weight, (int, float))
        or not _finite_number(testimony_weight)
        or not 0.0 < float(testimony_weight) <= 1.0
        or isinstance(cycle, bool)
        or not isinstance(cycle, int)
        or cycle < 0
    ):
        return None
    restored = {
        "components": dict(components),
        "evidence": evidence,
        "testimony_weight": float(testimony_weight),
        "cycle": cycle,
    }
    if include_metadata:
        marker = data.get("marker", "")
        shared_marker = data.get("shared_marker", False)
        if not isinstance(marker, str) or not isinstance(shared_marker, bool):
            return None
        restored["marker"] = marker[:AFFECT_PHRASE_MAX_LEN]
        restored["shared_marker"] = shared_marker
    return restored


def restore_learned_affect(data):
    """Проверить одну долговременную запись normalized_phrase → testimony."""
    if not isinstance(data, dict):
        return None
    components = _clean_components(data.get("components"))
    weight = data.get("weight")
    cycle = data.get("cycle")
    if (
        components is None
        or data.get("evidence", "user_taught") != "user_taught"
        or isinstance(weight, bool)
        or not isinstance(weight, (int, float))
        or not _finite_number(weight)
        or not 0.0 < float(weight) <= 1.0
        or isinstance(cycle, bool)
        or not isinstance(cycle, int)
        or cycle < 0
    ):
        return None
    return {
        "components": dict(components),
        "weight": float(weight),
        "evidence": "user_taught",
        "cycle": cycle,
    }


def _parse_static_clause(clause, components, markers) -> bool:
    if not clause or "?" in clause or any(char in clause for char in _QUOTE_CHARS):
        return False
    match = _STATIC_REPORT_RE.match(clause)
    if match is None:
        return False
    modifiers = _MODIFIER_RE.findall(match.group("mods") or "")
    if len(modifiers) > 1:
        return False
    scale = 1.0
    if modifiers and modifiers[0] in _WEAK_MODIFIERS:
        scale = WEAK_AFFECT_MODIFIER_SCALE
    elif modifiers and modifiers[0] in _STRONG_MODIFIERS:
        scale = STRONG_AFFECT_MODIFIER_SCALE
    component = _FORM_COMPONENTS[match.group("form")]
    value = round(min(1.0, BASE_AFFECT_ACTIVATION * scale), 6)
    components[component] = max(components.get(component, 0.0), value)
    markers.append(match.group("form"))
    return bool(match.group("shared") or match.group("too"))


def extract_static_human_affect(
    text, *, cycle=0, testimony_weight=DEFAULT_TESTIMONY_WEIGHT
):
    """Разобрать только прямые самосообщения из статической таблицы."""
    normalized = " ".join(str(text or "").lower().replace("ё", "е").split())
    if not normalized:
        return None
    components = {}
    markers = []
    shared_marker = False
    for clause in _CONTRAST_SPLIT_RE.split(normalized):
        shared = _parse_static_clause(clause.strip(), components, markers)
        shared_marker = shared_marker or shared
    if not components:
        return None
    return {
        "components": components,
        "evidence": "self_report",
        "testimony_weight": _unit_number(testimony_weight, DEFAULT_TESTIMONY_WEIGHT),
        "cycle": _cycle(cycle),
        "marker": ", ".join(markers),
        "shared_marker": shared_marker,
    }


def extract_learned_human_affect(
    text, learned=None, *, cycle=0, testimony_weight=DEFAULT_TESTIMONY_WEIGHT
):
    """Применить user_taught-ассоциацию только к точной полной фразе."""
    if not isinstance(learned, dict):
        return None
    raw = str(text or "")
    if "?" in raw or any(char in raw for char in _QUOTE_CHARS):
        return None
    phrase = normalize_affect_phrase(raw)
    if not phrase or len(phrase) > AFFECT_PHRASE_MAX_LEN or _NEGATION_RE.search(phrase):
        return None
    entry = restore_learned_affect(learned.get(phrase))
    if entry is None:
        return None
    components = {
        name: round(value * entry["weight"], 6)
        for name, value in entry["components"].items()
    }
    return {
        "components": components,
        "evidence": "user_taught",
        "testimony_weight": _unit_number(testimony_weight, DEFAULT_TESTIMONY_WEIGHT),
        "cycle": _cycle(cycle),
        "marker": phrase,
        "shared_marker": bool(re.match(r"^и\s+", phrase) or " тоже " in phrase),
    }


def extract_human_affect(
    text, learned=None, *, cycle=0, testimony_weight=DEFAULT_TESTIMONY_WEIGHT
):
    """Статические правила сильнее user_taught-лексикона."""
    return extract_static_human_affect(
        text, cycle=cycle, testimony_weight=testimony_weight
    ) or extract_learned_human_affect(
        text, learned, cycle=cycle, testimony_weight=testimony_weight
    )


def decayed_affect(data, current_cycle):
    """Вернуть свежий дескриптор с экспоненциально затухшими компонентами."""
    restored = restore_affect(data)
    if restored is None:
        return None
    age = _cycle(current_cycle) - restored["cycle"]
    if age < 0 or age > AFFECT_HARD_TTL_CYCLES:
        return None
    factor = 0.5 ** (age / AFFECT_HALF_LIFE_CYCLES)
    restored["components"] = {
        name: value * factor for name, value in restored["components"].items()
    }
    return restored


def negative_affect_strength(data, current_cycle) -> float:
    current = decayed_affect(data, current_cycle)
    if current is None:
        return 0.0
    lexical_strength = max(
        (current["components"].get(name, 0.0) for name in NEGATIVE_AFFECT_COMPONENTS),
        default=0.0,
    )
    return lexical_strength * current["testimony_weight"]


def shared_affect_components(affect, recent_acts) -> list:
    """Разделённость только по последнему свежему акту сущности.

    ``recent_acts`` упорядочен от последнего к более старым и содержит
    attention-веса. Старые совпадения никогда не перекрывают последний акт.
    """
    current = restore_affect(affect, include_metadata=True)
    if current is None or not current["shared_marker"] or not recent_acts:
        return []
    latest = recent_acts[0]
    if not isinstance(latest, dict) or str(latest.get("user_text") or "").strip():
        return []
    latest_cycle = latest.get("cycle")
    if isinstance(latest_cycle, bool) or not isinstance(latest_cycle, int):
        return []
    age = current["cycle"] - latest_cycle
    if age < 0 or age > AFFECT_HARD_TTL_CYCLES:
        return []
    previous = extract_static_human_affect(
        latest.get("agent_text"), cycle=latest.get("cycle", 0), testimony_weight=1.0
    )
    if previous is None:
        return []
    return [
        name
        for name in AFFECT_COMPONENTS
        if current["components"].get(name, 0.0) > 0.0
        and previous["components"].get(name, 0.0) > 0.0
    ]


def extract_affect_teaching(text, *, default_phrase=""):
    """Распознать явное намерение научить, не обучая автоматически."""
    normalized = " ".join(str(text or "").lower().replace("ё", "е").split())
    phrase = ""
    component = ""
    for pattern in (_QUOTED_TEACHING_RE, _PLAIN_TEACHING_RE):
        match = pattern.match(normalized)
        if match is not None:
            phrase = normalize_affect_phrase(match.group("phrase"))
            component = _TEACHING_EMOTIONS[match.group("emotion")]
            break
    default_phrase = normalize_affect_phrase(default_phrase)
    if not component and default_phrase:
        match = _DEFAULT_TEACHING_RE.match(normalized)
        if match is not None:
            phrase = default_phrase
            component = _TEACHING_EMOTIONS[match.group("emotion")]
        else:
            match = _HABIT_TEACHING_RE.match(normalized)
            if match is not None:
                report = extract_static_human_affect(match.group("report"))
                if report is not None and len(report["components"]) == 1:
                    phrase = default_phrase
                    component = next(iter(report["components"]))
    if (
        not phrase
        or len(phrase) < 3
        or len(phrase) > AFFECT_PHRASE_MAX_LEN
        or component not in AFFECT_COMPONENTS
    ):
        return None
    return {"phrase": phrase, "component": component}
