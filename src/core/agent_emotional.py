"""Emotional-event and candidate-bias helpers extracted from ``agent.py``.

Emotions only weight existing candidates; they do not choose actions. The
selection contour is reached through the facade, never through a reverse import.
"""

from typing import Dict, List, Optional


# Эмоция как небольшой вес уже существующих занятий — не команда.
# Палитра шире этой таблицы: состояние без записи здесь сохраняется и
# видно в статусе, но не получает выдуманного поведенческого эффекта.
EMOTION_ACTION_BIAS: Dict[str, Dict[str, float]] = {
    "fear": {
        "repair": 1.4,
        "checkpoint_now": 1.3,
        "wait": 1.2,
        "rest": 1.15,
        "deep_rest": 1.15,
        "explore": 0.85,
        "web_search": 0.85,
        "hypothesis": 0.9,
    },
    "joy": {
        "create_draft": 1.25,
        "play": 1.2,
        "synthesis": 1.2,
        "communicate": 1.15,
        "explore": 1.1,
        "draw": 1.2,
        "compose_music": 1.2,
    },
    "sadness": {
        "reflection": 1.25,
        "communicate": 1.15,
        "rest": 1.15,
        "read_news": 1.1,
        "browse_web": 1.1,
        "explore": 0.9,
        "play": 0.85,
    },
    "anxiety": {
        "repair": 1.25,
        "checkpoint_now": 1.2,
        "wait": 1.15,
        "rest": 1.15,
        "explore": 0.9,
        "web_search": 0.9,
    },
    "anger": {
        "repair": 1.15,
        "reflection": 1.1,
        "communicate": 1.05,
        "play": 0.85,
        "explore": 0.9,
    },
    "frustration": {
        "repair": 1.2,
        "reflection": 1.15,
        "rest": 1.1,
        "explore": 0.95,
    },
    "grief": {
        "reflection": 1.35,
        "rest": 1.25,
        "communicate": 1.1,
        "explore": 0.85,
        "play": 0.8,
    },
    "despair": {
        "rest": 1.3,
        "communicate": 1.15,
        "repair": 1.1,
        "explore": 0.8,
    },
    "loneliness": {"communicate": 1.3, "browse_web": 1.1, "rest": 1.05},
    "disappointment": {"reflection": 1.2, "rest": 1.1},
    "regret": {"reflection": 1.2, "repair": 1.1},
    "guilt": {"reflection": 1.2, "repair": 1.15, "communicate": 1.05},
    "shame": {"reflection": 1.15, "rest": 1.1, "communicate": 0.9},
    "curiosity": {
        "explore": 1.25,
        "web_search": 1.2,
        "hypothesis": 1.15,
        "synthesis": 1.1,
    },
    "interest": {"explore": 1.2, "web_search": 1.15, "synthesis": 1.1},
    "inspiration": {
        "create_draft": 1.3,
        "draw": 1.25,
        "compose_music": 1.25,
        "synthesis": 1.2,
    },
    "enthusiasm": {
        "create_draft": 1.2,
        "play": 1.15,
        "explore": 1.1,
        "synthesis": 1.15,
    },
    "hope": {"create_draft": 1.15, "explore": 1.1, "rest": 1.05},
    "gratitude": {"communicate": 1.2, "play": 1.1},
    "trust": {"communicate": 1.15, "play": 1.05},
    "love": {"communicate": 1.2, "play": 1.1, "create_draft": 1.05},
    "attachment": {"communicate": 1.2, "play": 1.05},
    "compassion": {"communicate": 1.2, "reflection": 1.05},
    "empathy": {"communicate": 1.15, "reflection": 1.1},
    "pride": {"create_draft": 1.15, "reflection": 1.1},
    "satisfaction": {"create_draft": 1.1, "reflection": 1.1, "rest": 1.05},
    "relief": {"rest": 1.2, "explore": 1.1, "play": 1.05},
    "boredom": {"explore": 1.25, "play": 1.2, "create_draft": 1.15},
    "surprise": {"hypothesis": 1.15, "reflection": 1.1},
    "confusion": {"hypothesis": 1.2, "reflection": 1.15, "explore": 0.95},
    "nostalgia": {"reflection": 1.2, "create_draft": 1.1},
    "overwhelm": {"rest": 1.35, "deep_rest": 1.25, "wait": 1.2, "explore": 0.8},
}


def _emotions_from_death_risk_impl(self, death_result: Dict) -> None:
    """«Эмоции-2»: сигнал риска структуры → страх.

    Страх рождается только из реального измерения: целостность ниже
    порога предупреждения, который задаёт сам death_risk. Здоровая
    структура — фон, не событие. Кулдаун внутри EmotionalState не
    даёт переживать один непреходящий сигнал каждый цикл.
    """
    emotional_state = getattr(self, "emotional_state", None)
    if emotional_state is None or not isinstance(death_result, dict):
        return
    integrity_info = death_result.get("integrity") or {}
    integrity_level = integrity_info.get("overall_integrity")
    warning_level = (integrity_info.get("thresholds") or {}).get("warning", 0.5)
    if not isinstance(integrity_level, (int, float)):
        return
    if isinstance(integrity_level, bool):
        return
    if integrity_level >= warning_level:
        return
    emotional_state.handle_event(
        "death_risk",
        cycle=self.cycle_count,
        cause=(
            f"целостность структуры {integrity_level:.2f} "
            f"({integrity_info.get('status', '?')})"
        ),
    )


def _emotions_from_mortality_impl(
    self, mortality_state: Dict, cycle_count: int
) -> None:
    """«Эмоции-2»: последняя фаза жизни → экзистенциальная тревога.

    Не в детстве и не в зрелости: фон не событие. Кулдаун внутри
    EmotionalState держит тишину между всплесками.
    """
    emotional_state = getattr(self, "emotional_state", None)
    if emotional_state is None or not isinstance(mortality_state, dict):
        return
    if mortality_state.get("phase") != "finale":
        return
    age_ratio = mortality_state.get("age_ratio", 0.0)
    try:
        age_ratio = float(age_ratio)
    except (TypeError, ValueError):
        age_ratio = 0.0
    emotional_state.handle_event(
        "life_finale",
        cycle=cycle_count,
        cause=f"прожито {age_ratio * 100:.0f}% ожидаемой жизни",
    )


def _apply_emotional_bias_impl(self, candidates: List[Dict]) -> Optional[Dict]:
    """Ограниченно сместить веса кандидатов всеми заметными компонентами.

    Вклады смеси складываются, а итоговый множитель ограничен [0.5, 1.5].
    Противоположные эмоции могут ослаблять поведенческий вклад друг друга,
    но их состояния при этом не стираются. Кандидаты не добавляются и не
    удаляются; цели и ценности не меняются, окончательный выбор за арбитром.
    """
    state = getattr(self, "emotional_state", None)
    if state is None:
        return None
    dominant = state.dominant()
    if not dominant:
        return None
    components = [
        item
        for item in state.mixture().get("components", [])
        if item.get("emotion") in EMOTION_ACTION_BIAS
    ]
    if not components:
        return None
    shifted = []
    for candidate in candidates:
        action_type = self._normalize_action(candidate.get("action"))
        contribution = 0.0
        for component in components:
            table = EMOTION_ACTION_BIAS[component["emotion"]]
            multiplier = table.get(action_type)
            if multiplier is not None:
                level = float(component.get("level", 0.0) or 0.0)
                contribution += (multiplier - 1.0) * level
        factor = max(0.5, min(1.5, 1.0 + contribution))
        if abs(factor - 1.0) < 0.01:
            continue
        candidate["strength"] = round(float(candidate.get("strength", 0.5)) * factor, 4)
        shifted.append(
            {
                "action": candidate.get("action"),
                "factor": round(factor, 3),
            }
        )
    if not shifted:
        return None
    return {
        # Старые поля остаются для отчётов; components описывает всю смесь.
        "emotion": dominant.get("emotion"),
        "level": dominant.get("level"),
        "cause": dominant.get("cause"),
        "components": components,
        "shifted": shifted,
    }
