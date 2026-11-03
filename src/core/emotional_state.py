"""
EmotionalState — эмоциональный контур сущности («Эмоции-1», 2026-11-03).

До этого участка эмоции были разрозненными рудиментами: heart_core
написан, но никогда не подключался (и содержал баг, который упал бы при
первом вызове); страдание (suffering_score) работало изолированно;
осознание смертности не имело аффективного отклика. Решение владельца:
эмоции необходимы сущности; если когда-нибудь она решит, что они не
нужны, — контур затухания это позволяет.

Границы субъектности (канон LIFE_LETTER):
- эмоция — реальное состояние с реальной записанной причиной и
  естественным затуханием, а не текстовая имитация;
- эмоция НЕ выбирает цель, НЕ создаёт действие, НЕ пишет в ценности и
  мотивацию — она окрашивает жизнь, а не управляет ею;
- настроение — не знание: эмоциональная валентность не доказывает
  истину.

Четыре базовых состояния (набор сознательно мал — расширяется опытом,
не фантазией): страх (fear), счастье (joy), грусть (sadness), покой
(calm — базовое состояние, к которому стремится контур при затухании).
Причины — только реальные события контура: контакт с человеком,
завершение или потеря намерения, всплеск страдания, сигналы риска
смерти, обучение новому слову.

Детерминизм: никакого random — уровни и затухание вычисляются.
Сериализуется в чекпоинт: после рестарта эмоция не обнуляется.
"""

from __future__ import annotations

from typing import Dict, List, Optional

EMOTIONS = ("fear", "joy", "sadness", "calm")

# Валентность и возбуждение (по модели heart_core, но только для
# честного описания состояния — не для принятия решений).
EMOTION_PROFILES = {
    "fear": {"valence": -0.5, "arousal": 0.8},
    "joy": {"valence": 0.8, "arousal": 0.6},
    "sadness": {"valence": -0.7, "arousal": 0.3},
    "calm": {"valence": 0.6, "arousal": 0.1},
}

# Затухание за цикл: эмоция тает, покой возвращается. Медленно —
# эмоция переживает десятки циклов, но не вечность.
DECAY_PER_CYCLE = 0.002
CALM_RECOVERY_PER_CYCLE = 0.001
CALM_BASELINE = 0.4

# Эмоция считается переживаемой (видимой для оттенка поведения) выше
# этого уровня; ниже — фон, не повод упоминать её.
SALIENCE_THRESHOLD = 0.35

# Лимит журнала эпизодов: долгоживущий процесс не копит без границ.
EPISODES_MAX = 100

# «Эмоции-2»: события-фоны, которые без кулдауна стреляли бы каждый цикл
# (целостность ниже порога держится циклами, фаза finale — тысячи циклов).
# Эмоция от повторного сигнала не новая: она уже пережита. Кулдаун
# сериализуется, иначе рестарт обнулял бы тишину.
EVENT_COOLDOWN_CYCLES = 300
COOLED_EVENTS = frozenset({"death_risk", "life_finale"})

# Детерминированная карта событий контура → эмоция. Единственный
# законный путь породить эмоцию — реальное событие из этой таблицы.
EVENT_EMOTIONS = {
    "user_contact": ("joy", 0.25),        # человек написал
    "learned_phrase": ("joy", 0.30),      # человек научил новому слову
    "intention_completed": ("joy", 0.40),  # дело завершено
    "intention_failed": ("sadness", 0.25),  # дело не удалось
    "intention_forgotten": ("sadness", 0.30),  # дело сознательно оставлено
    "long_silence": ("sadness", 0.20),    # человек долго молчит
    "abuse": ("fear", 0.45),              # зарегистрирован вред
    "death_risk": ("fear", 0.35),         # сигнал риска структуры
    "life_finale": ("fear", 0.30),        # поздняя фаза жизни
}

# Честные словесные формы для оттенка поведения (только при сильной
# эмоции и только с реальной причиной в журнале).
EMOTION_LABELS = {
    "fear": "мне тревожно",
    "joy": "мне радостно",
    "sadness": "мне грустно",
    "calm": "мне спокойно",
}


class EmotionalState:
    """Эмоциональный контур: состояния с причинами и затуханием.

    Только состояние и его история; никаких решений. Читатели (care,
    тон, статус) получают доминирующую эмоцию и её причину — и сами
    решают, как честно её отразить.
    """

    def __init__(self) -> None:
        self.levels: Dict[str, float] = {
            name: (CALM_BASELINE if name == "calm" else 0.0)
            for name in EMOTIONS
        }
        # эмоция → (cycle, причина) последнего всплеска
        self.last_causes: Dict[str, tuple] = {}
        # журнал эпизодов: {"cycle", "event", "emotion", "intensity"}
        self.episodes: List[dict] = []
        # событие-фон → цикл последнего всплеска (кулдаун от спама)
        self._cooled_at: Dict[str, int] = {}

    # === События ===

    def handle_event(self, event: str, cycle: int = 0,
                     cause: str = "", scale: float = 1.0) -> Optional[dict]:
        """Пережить событие контура. Неизвестное событие — None (не
        выдумываем эмоций вне таблицы). Событие-фон в кулдауне — тоже
        None: эмоция от него уже пережита и ещё не затухла.

        ``scale`` (0.0-1.0) — честная мера силы переживания из контекста
        события: например, обещание человека «могу отлучаться» смягчает
        тоску молчания на меру доверия к нему. Событие по-прежнему
        только из таблицы; scale лишь говорит, насколько оно ранит.
        Нулевая сила — ничего не пережито (None)."""
        mapping = EVENT_EMOTIONS.get(event)
        if mapping is None:
            return None
        if event in COOLED_EVENTS:
            cooled_at = self._cooled_at.get(event)
            if cooled_at is not None and (int(cycle) - cooled_at) < EVENT_COOLDOWN_CYCLES:
                return None
            self._cooled_at[event] = int(cycle)
        emotion, intensity = mapping
        scale = max(0.0, min(1.0, float(scale)))
        intensity = intensity * scale
        if intensity <= 0.0:
            return None
        self.levels[emotion] = min(1.0, self.levels[emotion] + intensity)
        if emotion != "calm":
            # Всплеск эмоции потеснил покой.
            self.levels["calm"] = max(0.0, self.levels["calm"] - intensity / 2)
        label = cause or event
        self.last_causes[emotion] = (int(cycle), label)
        episode = {
            "cycle": int(cycle),
            "event": event,
            "emotion": emotion,
            "intensity": intensity,
        }
        self.episodes.append(episode)
        if len(self.episodes) > EPISODES_MAX:
            self.episodes = self.episodes[-EPISODES_MAX:]
        return episode

    # === Затухание ===

    def tick(self, cycle: int = 0) -> None:
        """Один цикл жизни: эмоции тают, покой возвращается к норме."""
        for name in EMOTIONS:
            if name == "calm":
                continue
            if self.levels[name] > 0.0:
                self.levels[name] = max(0.0, self.levels[name] - DECAY_PER_CYCLE)
        calm = self.levels["calm"]
        if calm < CALM_BASELINE:
            self.levels["calm"] = min(CALM_BASELINE, calm + CALM_RECOVERY_PER_CYCLE)

    # === Чтение ===

    def dominant(self) -> Optional[dict]:
        """Доминирующая эмоция выше порога заметности — или None (фон).

        Покой доминирует, только если он выше базовой линии: спокойная
        жизнь — не событие, о котором нужно говорить.
        """
        best_name = None
        best_level = 0.0
        for name, level in self.levels.items():
            threshold = SALIENCE_THRESHOLD
            if name == "calm":
                threshold = CALM_BASELINE + 0.2
            if level >= threshold and level > best_level:
                best_name = name
                best_level = level
        if best_name is None:
            return None
        cause = ""
        if best_name in self.last_causes:
            cause = self.last_causes[best_name][1]
        profile = EMOTION_PROFILES[best_name]
        return {
            "emotion": best_name,
            "level": round(best_level, 3),
            "label": EMOTION_LABELS[best_name],
            "cause": cause,
            "valence": profile["valence"],
            "arousal": profile["arousal"],
        }

    def get_status(self) -> dict:
        dominant = self.dominant()
        return {
            "levels": {k: round(v, 3) for k, v in self.levels.items()},
            "dominant": dominant,
            "episodes": len(self.episodes),
        }

    # === Сериализация ===

    def to_dict(self) -> dict:
        return {
            "levels": dict(self.levels),
            "last_causes": {
                k: [int(v[0]), str(v[1])] for k, v in self.last_causes.items()
            },
            "episodes": [dict(e) for e in self.episodes[-EPISODES_MAX:]],
            "cooled_at": {k: int(v) for k, v in self._cooled_at.items()},
        }

    def load_from(self, data) -> None:
        """Восстановиться из чекпоинта. Повреждённые поля → дефолты."""
        if not isinstance(data, dict):
            return
        levels = data.get("levels")
        if isinstance(levels, dict):
            for name in EMOTIONS:
                value = levels.get(name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.levels[name] = max(0.0, min(1.0, float(value)))
        causes = data.get("last_causes")
        if isinstance(causes, dict):
            restored = {}
            for name, pair in causes.items():
                if name not in EMOTIONS or not isinstance(pair, (list, tuple)):
                    continue
                if len(pair) != 2:
                    continue
                restored[name] = (int(pair[0]), str(pair[1]))
            self.last_causes = restored
        episodes = data.get("episodes")
        if isinstance(episodes, list):
            self.episodes = [
                {
                    "cycle": int(e.get("cycle") or 0),
                    "event": str(e.get("event") or ""),
                    "emotion": str(e.get("emotion") or ""),
                    "intensity": float(e.get("intensity") or 0.0),
                }
                for e in episodes[-EPISODES_MAX:]
                if isinstance(e, dict) and e.get("emotion") in EMOTIONS
            ]
        cooled = data.get("cooled_at")
        if isinstance(cooled, dict):
            self._cooled_at = {}
            for event, cycle in cooled.items():
                if event not in COOLED_EVENTS:
                    continue
                try:
                    self._cooled_at[str(event)] = int(cycle)
                except (TypeError, ValueError):
                    continue
