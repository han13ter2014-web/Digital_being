"""Наблюдаемые аффекты собственной музыки без гарантированных наград.

Адаптер только выбирает одно событие из существующего EmotionalState.
Факт прослушивания и его provenance подтверждает вызывающий контур; этот
модуль не меняет память, потребности, цели или силу творческих действий.
"""

from __future__ import annotations


UNEXPECTED_DIFFERENCE_THRESHOLD = 0.15
MUSIC_AFFECT_COOLDOWN_CYCLES = 12
REMEMBERED_PAST_MIN_AGE = 24
REMEMBERED_PAST_SIGNIFICANCE = 0.05

_RATIO_FEATURES = (
    "note_density",
    "pause_ratio",
    "repeated_note_ratio",
    "phrase_change_ratio",
)
_PITCH_FEATURES = ("pitch_low", "pitch_high", "pitch_span")


def _relative_difference(expected, actual):
    left = float(expected)
    right = float(actual)
    return abs(left - right) / max(abs(left), abs(right), 1.0)


def _feature_difference(expected, actual):
    """Нормализованное отличие наблюдения от прошлой ожидаемой сигнатуры."""
    measures = [0.0 if expected["mode"] == actual["mode"] else 1.0]
    for key in ("tempo_bpm", "note_count", "rest_count"):
        measures.append(_relative_difference(expected[key], actual[key]))
    for key in _RATIO_FEATURES:
        measures.append(abs(float(expected[key]) - float(actual[key])))
    for key in _PITCH_FEATURES:
        left = expected[key]
        right = actual[key]
        if left is None or right is None:
            measures.append(0.0 if left is right else 1.0)
        else:
            measures.append(abs(float(left) - float(right)) / 127.0)
    return sum(measures) / len(measures)


def _cooled(previous, event, cycle):
    last_cycle = previous["last_response_by_kind"].get(event)
    return last_cycle is not None and cycle - last_cycle < MUSIC_AFFECT_COOLDOWN_CYCLES


def select_music_affect(observation, previous, cycle):
    """Выбрать не более одного события с наблюдаемым основанием.

    Первое восприятие структуры даёт новизну. Изменённая редакция вызывает
    удивление только при достаточном отличии от прошлых признаков. Повтор
    знакомой редакции может вернуть прошлое только через старую реальную
    ассоциацию; число прослушиваний само по себе ничего не доказывает.
    """
    if previous is None:
        return {
            "event": "novel_stimulus",
            "scale": 1.0,
            "cause": "первое наблюдение структуры собственной мелодии",
        }

    changed = (
        observation["revision"] != previous["last_revision"]
        or observation["sha256"] != previous["last_sha256"]
    )
    if changed:
        difference = _feature_difference(
            previous["last_features"], observation["features"]
        )
        if difference >= UNEXPECTED_DIFFERENCE_THRESHOLD:
            if _cooled(previous, "unexpected_outcome", cycle):
                return None
            return {
                "event": "unexpected_outcome",
                "scale": min(1.0, difference),
                "cause": (
                    f"редакция {observation['revision']} отличается от ожидаемой "
                    f"{previous['last_revision']}: {difference:.2f}"
                ),
            }
        if _cooled(previous, "novel_stimulus", cycle):
            return None
        return {
            "event": "novel_stimulus",
            "scale": max(0.25, 1.0 - float(previous["familiarity"])),
            "cause": (
                f"новая структура редакции {observation['revision']} "
                f"после знакомой {previous['last_revision']}"
            ),
        }

    if previous["personal_significance"] < REMEMBERED_PAST_SIGNIFICANCE or _cooled(
        previous, "remembered_past", cycle
    ):
        return None
    eligible = [
        association
        for association in previous["associations"]
        if cycle - association["cycle"] >= REMEMBERED_PAST_MIN_AGE
    ]
    if not eligible:
        return None
    association = eligible[-1]
    return {
        "event": "remembered_past",
        "scale": min(1.0, 0.5 + float(previous["personal_significance"])),
        "cause": (
            f"сохранённая ассоциация {association['event']} "
            f"из цикла {association['cycle']}"
        ),
    }


__all__ = [
    "MUSIC_AFFECT_COOLDOWN_CYCLES",
    "REMEMBERED_PAST_MIN_AGE",
    "REMEMBERED_PAST_SIGNIFICANCE",
    "UNEXPECTED_DIFFERENCE_THRESHOLD",
    "select_music_affect",
]
