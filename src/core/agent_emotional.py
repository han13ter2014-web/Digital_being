"""Emotional-event and candidate-bias helpers extracted from ``agent.py``.

Emotions only weight existing candidates; they do not choose actions. The
selection contour is reached through the facade, never through a reverse import.
"""

from typing import Dict, List, Optional


# «Эмоции-2»: эмоция как вес в выборе занятий — не команда.
# Доминирующая эмоция (выше порога заметности) слегка смещает тягу:
# страх — к безопасному и восстановительному, счастье — к творческому,
# грусть — к тихому. Множитель 1.0 = без влияния; сила смещения
# пропорциональна глубине переживания. Покой (calm) — базовая линия,
# он ничего не смещает. Эмоция не добавляет и не убирает кандидатов,
# не пишет в цели и ценности: выбор по-прежнему за арбитром.
EMOTION_ACTION_BIAS: Dict[str, Dict[str, float]] = {
    "fear": {
        # беречь структуру и силы
        "repair": 1.4,
        "checkpoint_now": 1.3,
        "wait": 1.2,
        "rest": 1.15,
        "deep_rest": 1.15,
        # не лезть в рискованное и тяжёлое
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
        # музыка — радостное занятие
        "compose_music": 1.2,
    },
    "sadness": {
        "reflection": 1.25,
        "communicate": 1.15,
        "rest": 1.15,
        # тихое чтение новостей — занятие для грустного настроения
        "read_news": 1.1,
        # и тихая прогулка по открытому вебу — тоже
        "browse_web": 1.1,
        "explore": 0.9,
        "play": 0.85,
    },
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
    warning_level = (integrity_info.get("thresholds") or {}).get(
        "warning", 0.5
    )
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


def _emotions_from_mortality_impl(self, mortality_state: Dict,
                                 cycle_count: int) -> None:
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
    """«Эмоции-2»: доминирующая эмоция смещает веса кандидатов.

        Эмоция — не команда: она не добавляет и не убирает занятия, не
        пишет в цели и ценности, а лишь чуть усиливает или ослабляет
        тягу (множитель пропорционален глубине переживания). Выбор
        остаётся за арбитром; смещение честно записывается в отчёт
        цикла. Фон (нет доминирующей эмоции) — без влияния.
        """
    state = getattr(self, "emotional_state", None)
    if state is None:
        return None
    dominant = state.dominant()
    if not dominant:
        return None
    table = EMOTION_ACTION_BIAS.get(dominant.get("emotion"))
    if not table:
        return None
    level = float(dominant.get("level", 0.0) or 0.0)
    shifted = []
    for candidate in candidates:
        action_type = self._normalize_action(candidate.get("action"))
        multiplier = table.get(action_type)
        if multiplier is None:
            continue
        factor = 1.0 + (multiplier - 1.0) * level
        if abs(factor - 1.0) < 0.01:
            continue
        candidate["strength"] = round(
            float(candidate.get("strength", 0.5)) * factor, 4
        )
        shifted.append({
            "action": candidate.get("action"),
            "factor": round(factor, 3),
        })
    if not shifted:
        return None
    return {
        "emotion": dominant.get("emotion"),
        "level": dominant.get("level"),
        "cause": dominant.get("cause"),
        "shifted": shifted,
    }
