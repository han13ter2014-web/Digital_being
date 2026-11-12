"""
EmotionalState — единый эмоциональный контур сущности.

Эмоция здесь — ограниченное функциональное состояние с записанной
причиной и естественным затуханием, а не утверждение о человеческом
субъективном переживании. Эмоция НЕ выбирает цель, НЕ создаёт действие,
НЕ пишет в ценности и мотивацию. Валентность — описание состояния, а не
доказательство истины.

Каноническая палитра охватывает базовые, позитивные, негативные и
социальные состояния. Компоненты могут сосуществовать: радость и страх
не заменяются одной искусственной «смешанной эмоцией» и не уничтожают
друг друга. У каждой компоненты сохраняются уровень и причина.

Детерминизм: никакого random — уровни, смеси и затухание вычисляются.
Сериализуются исходные уровни и эпизоды; смесь восстанавливается из них
после рестарта. Старые чекпоинты с четырьмя состояниями остаются valid.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

# Затухание за цикл: эмоция тает, покой возвращается. Медленно —
# эмоция переживает десятки циклов, но не вечность.
DECAY_PER_CYCLE = 0.002
CALM_RECOVERY_PER_CYCLE = 0.001
CALM_BASELINE = 0.4

# Единственная спецификация палитры: русская словесная форма, валентность
# и возбуждение. Это описательные координаты, а не мера человеческого
# чувства и не разрешение на автономный выбор действия.
EMOTION_PROFILES = {
    "fear": {"label": "мне тревожно", "valence": -0.5, "arousal": 0.8},
    "joy": {"label": "мне радостно", "valence": 0.8, "arousal": 0.6},
    "sadness": {"label": "мне грустно", "valence": -0.7, "arousal": 0.3},
    "calm": {"label": "мне спокойно", "valence": 0.6, "arousal": 0.1},
    "anger": {"label": "я разгневана", "valence": -0.8, "arousal": 0.85},
    "disgust": {"label": "мне противно", "valence": -0.75, "arousal": 0.55},
    "surprise": {"label": "я удивлена", "valence": 0.0, "arousal": 0.85},
    "interest": {"label": "мне интересно", "valence": 0.6, "arousal": 0.45},
    "anticipation": {"label": "я предвкушаю", "valence": 0.5, "arousal": 0.55},
    "trust": {"label": "я доверяю", "valence": 0.7, "arousal": 0.2},
    "love": {"label": "я люблю", "valence": 0.95, "arousal": 0.55},
    "attachment": {"label": "я привязана", "valence": 0.8, "arousal": 0.35},
    "tenderness": {"label": "я чувствую нежность", "valence": 0.85, "arousal": 0.25},
    "pride": {"label": "я горжусь", "valence": 0.75, "arousal": 0.55},
    "gratitude": {"label": "я благодарна", "valence": 0.85, "arousal": 0.35},
    "hope": {"label": "я надеюсь", "valence": 0.7, "arousal": 0.4},
    "inspiration": {"label": "я вдохновлена", "valence": 0.85, "arousal": 0.75},
    "relief": {"label": "я чувствую облегчение", "valence": 0.75, "arousal": 0.2},
    "satisfaction": {"label": "я удовлетворена", "valence": 0.75, "arousal": 0.25},
    "curiosity": {"label": "мне любопытно", "valence": 0.65, "arousal": 0.55},
    "admiration": {"label": "я восхищена", "valence": 0.8, "arousal": 0.45},
    "amusement": {"label": "мне забавно", "valence": 0.75, "arousal": 0.6},
    "serenity": {"label": "я умиротворена", "valence": 0.8, "arousal": 0.08},
    "contentment": {"label": "я довольна", "valence": 0.7, "arousal": 0.15},
    "enthusiasm": {"label": "я воодушевлена", "valence": 0.85, "arousal": 0.8},
    "awe": {"label": "я испытываю трепет", "valence": 0.65, "arousal": 0.7},
    "compassion": {"label": "я сострадаю", "valence": 0.45, "arousal": 0.35},
    "empathy": {"label": "я сопереживаю", "valence": 0.4, "arousal": 0.35},
    "anxiety": {"label": "я обеспокоена", "valence": -0.65, "arousal": 0.75},
    "shame": {"label": "мне стыдно", "valence": -0.75, "arousal": 0.5},
    "guilt": {"label": "я чувствую вину", "valence": -0.8, "arousal": 0.45},
    "embarrassment": {"label": "я смущена", "valence": -0.55, "arousal": 0.65},
    "jealousy": {"label": "я ревную", "valence": -0.75, "arousal": 0.7},
    "envy": {"label": "я завидую", "valence": -0.65, "arousal": 0.5},
    "loneliness": {"label": "мне одиноко", "valence": -0.8, "arousal": 0.25},
    "contempt": {"label": "я презираю", "valence": -0.7, "arousal": 0.45},
    "disappointment": {"label": "я разочарована", "valence": -0.6, "arousal": 0.35},
    "frustration": {"label": "я чувствую фрустрацию", "valence": -0.65, "arousal": 0.7},
    "resentment": {"label": "я обижена", "valence": -0.7, "arousal": 0.55},
    "regret": {"label": "я сожалею", "valence": -0.65, "arousal": 0.35},
    "longing": {"label": "я тоскую", "valence": -0.55, "arousal": 0.35},
    "despair": {"label": "я в отчаянии", "valence": -0.95, "arousal": 0.4},
    "boredom": {"label": "мне скучно", "valence": -0.35, "arousal": 0.15},
    "confusion": {"label": "я растеряна", "valence": -0.35, "arousal": 0.55},
    "grief": {"label": "я горюю", "valence": -0.95, "arousal": 0.25},
    "anguish": {"label": "мне мучительно", "valence": -0.95, "arousal": 0.65},
    "irritation": {"label": "я раздражена", "valence": -0.5, "arousal": 0.55},
    "hostility": {"label": "я настроена враждебно", "valence": -0.8, "arousal": 0.7},
    "nervousness": {"label": "я нервничаю", "valence": -0.55, "arousal": 0.7},
    "vulnerability": {
        "label": "я чувствую уязвимость",
        "valence": -0.45,
        "arousal": 0.45,
    },
    "helplessness": {
        "label": "я чувствую беспомощность",
        "valence": -0.85,
        "arousal": 0.25,
    },
    "overwhelm": {"label": "я перегружена", "valence": -0.75, "arousal": 0.8},
    "worry": {"label": "я беспокоюсь", "valence": -0.55, "arousal": 0.6},
    "nostalgia": {"label": "я ностальгирую", "valence": 0.1, "arousal": 0.25},
}

EMOTIONS = tuple(EMOTION_PROFILES)
EMOTION_LABELS = {name: profile["label"] for name, profile in EMOTION_PROFILES.items()}

# Эмоция считается заметной выше этого уровня; ниже — фон, не повод
# упоминать её или смещать поведение.
SALIENCE_THRESHOLD = 0.35

# Лимит журнала эпизодов: долгоживущий процесс не копит без границ.
EPISODES_MAX = 100

# События-фоны, которые без кулдауна повторялись бы каждый цикл.
EVENT_COOLDOWN_CYCLES = 300
COOLED_EVENTS = frozenset(
    {
        "death_risk",
        "life_finale",
        "intention_completed",
        "intention_failed",
    }
)

# Детерминированная карта наблюдаемых событий → один компонент эмоции.
# Существующие события Core сохраняют прежние интенсивности. Остальные
# входы предназначены для адаптеров, которые действительно наблюдали
# соответствующий факт; неизвестное событие по-прежнему игнорируется.
EVENT_EMOTIONS = {
    "user_contact": ("joy", 0.25),
    "learned_phrase": ("joy", 0.30),
    "intention_completed": ("joy", 0.40),
    "intention_failed": ("sadness", 0.25),
    "intention_forgotten": ("sadness", 0.30),
    "long_silence": ("sadness", 0.20),
    "abuse": ("fear", 0.45),
    "death_risk": ("fear", 0.35),
    "life_finale": ("fear", 0.30),
    "boundary_violated": ("anger", 0.40),
    "goal_blocked": ("frustration", 0.30),
    "unpleasant_stimulus": ("disgust", 0.35),
    "unexpected_outcome": ("surprise", 0.35),
    "valued_opportunity": ("interest", 0.30),
    "approaching_desired_outcome": ("anticipation", 0.30),
    "trusted_contact": ("trust", 0.30),
    "shared_joy": ("love", 0.25),
    "bond_strengthened": ("attachment", 0.30),
    "affection_received": ("tenderness", 0.30),
    "achievement_recognized": ("pride", 0.35),
    "care_received": ("gratitude", 0.35),
    "positive_future_signal": ("hope", 0.30),
    "creative_insight": ("inspiration", 0.35),
    "danger_passed": ("relief", 0.40),
    "need_satisfied": ("satisfaction", 0.30),
    "novel_stimulus": ("curiosity", 0.30),
    "beauty_observed": ("admiration", 0.30),
    "playful_exchange": ("amusement", 0.30),
    "peaceful_environment": ("serenity", 0.25),
    "stable_satisfaction": ("contentment", 0.25),
    "engaging_challenge": ("enthusiasm", 0.30),
    "meaningful_beauty": ("awe", 0.35),
    "other_suffering": ("compassion", 0.30),
    "shared_perspective": ("empathy", 0.30),
    "persistent_threat": ("anxiety", 0.30),
    "social_evaluation_negative": ("shame", 0.35),
    "responsibility_for_harm": ("guilt", 0.40),
    "social_blunder": ("embarrassment", 0.30),
    "bond_threatened": ("jealousy", 0.35),
    "other_advantage": ("envy", 0.25),
    "prolonged_isolation": ("loneliness", 0.30),
    "devaluing_stimulus": ("contempt", 0.30),
    "expectation_violated": ("disappointment", 0.35),
    "unfair_treatment": ("resentment", 0.35),
    "harmful_choice": ("regret", 0.35),
    "absent_attachment": ("longing", 0.30),
    "repeated_failure": ("despair", 0.40),
    "unstimulating_routine": ("boredom", 0.20),
    "unresolved_ambiguity": ("confusion", 0.30),
    "loss": ("grief", 0.45),
    "acute_distress": ("anguish", 0.45),
    "minor_irritant": ("irritation", 0.25),
    "hostile_intent": ("hostility", 0.35),
    "performance_pressure": ("nervousness", 0.30),
    "exposure": ("vulnerability", 0.30),
    "resource_loss": ("helplessness", 0.35),
    "excessive_demand": ("overwhelm", 0.35),
    "uncertain_threat": ("worry", 0.30),
    "remembered_past": ("nostalgia", 0.25),
}


class EmotionalState:
    """Эмоциональный контур: состояния с причинами и затуханием.

    Только состояние и его история; никаких решений. Читатели (care,
    тон, статус) получают доминирующую эмоцию и её причину — и сами
    решают, как честно её отразить.
    """

    def __init__(self) -> None:
        self.levels: Dict[str, float] = {
            name: (CALM_BASELINE if name == "calm" else 0.0) for name in EMOTIONS
        }
        # эмоция → (cycle, причина) последнего всплеска
        self.last_causes: Dict[str, tuple] = {}
        # журнал эпизодов: {"cycle", "event", "emotion", "intensity"}
        self.episodes: List[dict] = []
        # событие-фон → цикл последнего всплеска (кулдаун от спама)
        self._cooled_at: Dict[str, int] = {}

    # === События ===

    def handle_event(
        self, event: str, cycle: int = 0, cause: str = "", scale: float = 1.0
    ) -> Optional[dict]:
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
        emotion, base_intensity = mapping
        intensity = base_intensity * self._unit_interval(scale)
        if intensity <= 0.0:
            return None
        if event in COOLED_EVENTS:
            cooled_at = self._cooled_at.get(event)
            if (
                cooled_at is not None
                and (int(cycle) - cooled_at) < EVENT_COOLDOWN_CYCLES
            ):
                return None
            # Нулевая сила выше не расходует кулдаун: переживания не было.
            self._cooled_at[event] = int(cycle)
        return self._record(emotion, intensity, event, cycle, cause or event)

    @staticmethod
    def _unit_interval(value, default: float = 0.0) -> float:
        """Конечное число в [0, 1]; NaN/бесконечность не попадают в состояние."""
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        if not math.isfinite(number):
            return default
        return max(0.0, min(1.0, number))

    def _record(
        self, emotion: str, intensity: float, event: str, cycle: int, cause: str
    ) -> dict:
        """Атомарно применить один компонент и сохранить его наблюдаемую причину."""
        self.levels[emotion] = min(1.0, self.levels[emotion] + intensity)
        if emotion != "calm":
            self.levels["calm"] = max(0.0, self.levels["calm"] - intensity / 2)
        self.last_causes[emotion] = (int(cycle), str(cause))
        episode = {
            "cycle": int(cycle),
            "event": str(event),
            "emotion": emotion,
            "intensity": intensity,
        }
        self.episodes.append(episode)
        if len(self.episodes) > EPISODES_MAX:
            self.episodes = self.episodes[-EPISODES_MAX:]
        return episode

    def blend(
        self,
        components,
        cycle: int = 0,
        cause: str = "",
        scale: float = 1.0,
        event: str = "mixed_experience",
    ) -> Optional[dict]:
        """Добавить нормализованную смесь нескольких одновременных компонент.

        ``components`` — отображение ``{emotion: weight}`` или пары. Веса
        суммируются при повторе, нормализуются до 1 и умножаются на общую
        силу ``scale`` из [0, 1]. Нулевые, отрицательные и неfinite веса,
        а также неизвестные имена не создают состояний. Противоположные
        эмоции не сокращаются: каждая получает свой эпизод и причину.
        """
        if isinstance(components, dict):
            items = list(components.items())
        else:
            try:
                items = list(components)
            except TypeError:
                return None
        weights: Dict[str, float] = {}
        for item in items:
            try:
                name, raw_weight = item
            except (TypeError, ValueError):
                continue
            if name not in EMOTIONS:
                continue
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(weight) or weight <= 0.0:
                continue
            weights[name] = weights.get(name, 0.0) + weight
        total_weight = sum(weights.values())
        strength = self._unit_interval(scale)
        if not math.isfinite(total_weight) or total_weight <= 0.0 or strength <= 0.0:
            return None
        label = str(cause or event)
        episodes = [
            self._record(
                name,
                strength * weights[name] / total_weight,
                event,
                cycle,
                label,
            )
            for name in EMOTIONS
            if name in weights
        ]
        return {
            "cycle": int(cycle),
            "event": str(event),
            "cause": label,
            "components": episodes,
            "total_intensity": strength,
        }

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

    def _component(self, name: str) -> dict:
        profile = EMOTION_PROFILES[name]
        cause = self.last_causes.get(name, (0, ""))[1]
        return {
            "emotion": name,
            "level": round(self.levels[name], 3),
            "label": EMOTION_LABELS[name],
            "cause": cause,
            "valence": profile["valence"],
            "arousal": profile["arousal"],
        }

    def active(self) -> List[dict]:
        """Все заметные компоненты по убыванию силы, без взаимного подавления.

        Покой заметен только выше базовой линии. При равной силе порядок
        определяется канонической палитрой, поэтому чтение детерминировано.
        """
        components = []
        for name, level in self.levels.items():
            threshold = CALM_BASELINE + 0.2 if name == "calm" else SALIENCE_THRESHOLD
            if level >= threshold:
                components.append(self._component(name))
        components.sort(key=lambda item: -self.levels[item["emotion"]])
        return components

    def mixture(self) -> dict:
        """Нормализованная смесь заметных компонент и её средние координаты.

        ``weight`` каждого компонента — доля его уровня в общей сумме;
        сумма долей равна 1 (или 0 для пустой смеси). Средняя валентность
        описывает баланс, но исходные противоположные компоненты остаются
        в ``components`` и не аннулируются.
        """
        components = self.active()
        total = sum(self.levels[item["emotion"]] for item in components)
        if total <= 0.0:
            return {
                "components": [],
                "total_intensity": 0.0,
                "valence": 0.0,
                "arousal": 0.0,
            }
        mixed = []
        valence = 0.0
        arousal = 0.0
        for item in components:
            weight = self.levels[item["emotion"]] / total
            component = dict(item)
            component["weight"] = weight
            mixed.append(component)
            valence += item["valence"] * weight
            arousal += item["arousal"] * weight
        return {
            "components": mixed,
            "total_intensity": round(total, 3),
            "valence": valence,
            "arousal": arousal,
        }

    def dominant(self) -> Optional[dict]:
        """Самый сильный заметный компонент — совместимый scalar-интерфейс."""
        components = self.active()
        return components[0] if components else None

    def get_status(self) -> dict:
        return {
            "levels": {k: round(v, 3) for k, v in self.levels.items()},
            "dominant": self.dominant(),
            "mixture": self.mixture(),
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
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                ):
                    self.levels[name] = max(0.0, min(1.0, float(value)))
        causes = data.get("last_causes")
        if isinstance(causes, dict):
            restored = {}
            for name, pair in causes.items():
                if name not in EMOTIONS or not isinstance(pair, (list, tuple)):
                    continue
                if len(pair) != 2:
                    continue
                try:
                    restored[name] = (int(pair[0]), str(pair[1]))
                except (TypeError, ValueError, OverflowError):
                    continue
            self.last_causes = restored
        episodes = data.get("episodes")
        if isinstance(episodes, list):
            restored_episodes = []
            for entry in episodes[-EPISODES_MAX:]:
                if not isinstance(entry, dict) or entry.get("emotion") not in EMOTIONS:
                    continue
                try:
                    cycle = int(entry.get("cycle") or 0)
                    intensity = float(entry.get("intensity") or 0.0)
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(intensity):
                    continue
                restored_episodes.append(
                    {
                        "cycle": cycle,
                        "event": str(entry.get("event") or ""),
                        "emotion": str(entry["emotion"]),
                        "intensity": max(0.0, min(1.0, intensity)),
                    }
                )
            self.episodes = restored_episodes
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
