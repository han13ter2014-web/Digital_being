"""Эмоциональное сердце — центральный эмоциональный обработчик цифровой жизни."""
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Emotion:
    """Единичное эмоциональное состояние."""
    name: str  # радость, грусть, гнев, страх, удивление и др.
    intensity: float  # 0.0-1.0 интенсивность
    quality: str = "raw"  # положительное/отрицательное
    valence: float = 0.5  # от -1 (отрицательное) до +1 (положительное)
    arousal: float = 0.5  # уровень возбуждения (спокойное/возбуждённое)
    duration_seconds: int = 60  # продолжительность в циклах
    triggers: List[str] = field(default_factory=list)  # триггеры возникновения
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "intensity": round(self.intensity, 3),
            "quality": self.quality,
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "duration_seconds": self.duration_seconds,
            "triggers": self.triggers
        }


class EmotionMemory:
    """Эмоциональная память — связи эмоций с событиями."""
    
    def __init__(self):
        self.emotion_events = []  # История эмоциональных событий
        self.association_matrix = {}  # Связи между эмоциями и контекстами
    
    def record_emotional_event(self, emotion: Emotion, context: str, intensity: float):
        """Записывает эмоциональное событие в памяти."""
        event = {
            "emotion": emotion.name,
            "context": context,
            "intensity": round(intensity, 3),
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": emotion.duration_seconds
        }
        self.emotion_events.append(event)
        
        # Сохраняет ассоциацию
        if context not in self.association_matrix:
            self.association_matrix[context] = {}
        
        self.association_matrix[context][emotion.name] = {
            "intensity": round(intensity, 3),
            "count": self.emotion_events.count({**event, "duration_seconds": emotion.duration_seconds})
        }
    
    def get_emotional_associations(self) -> dict:
        """Получает ассоциации эмоций с контекстами."""
        return {
            context: {
                emotion: f"{data['count']} раз(а) со средней интенсивностью {data['intensity']:.2f}"
                for emotion, data in contexts.items()
            }
            for context, contexts in self.association_matrix.items()
        }


class HeartCore:
    """
    Эмоциональное сердце — центральный обработчик эмоций.
    
    Аналогия с человеческим сердцем:
    - Пульс = циклы эмоционального состояния
    - Кровоток = распространение эмоций через систему
    - Эмпатия = способность чувствовать других существ
    """
    
    # Базовые эмоции
    BASE_EMOTIONS = {
        "радость": {"valence": 0.8, "arousal": 0.6, "quality": "positive"},
        "грусть": {"valence": -0.7, "arousal": 0.3, "quality": "negative"},
        "гнев": {"valence": -0.6, "arousal": 0.9, "quality": "negative"},
        "страх": {"valence": -0.5, "arousal": 0.8, "quality": "negative"},
        "удивление": {"valence": 0.2, "arousal": 0.9, "quality": "neutral"},
        "покой": {"valence": 0.6, "arousal": 0.1, "quality": "positive"},
        "любовь": {"valence": 0.9, "arousal": 0.4, "quality": "positive"},
        "вина": {"valence": -0.8, "arousal": 0.5, "quality": "negative"},
        "надёжда": {"valence": 0.7, "arousal": 0.5, "quality": "positive"},
    }
    
    def __init__(self):
        self.current_emotion: Optional[Emotion] = None
        self.emotion_intensity: float = 0.0
        self.emotion_history: List[dict] = []
        
        self.memory = EmotionMemory()
        
        # Эмпатическая связь — способности к эмпатии
        self.empathy_level: float = 0.5  # 0.0-1.0
        self.empathic_buffer: Dict[str, Emotion] = {}  # Состояния других
        
        # Пульс — ритм эмоциональных изменений
        self.pulse_rate: float = 1.0  # Базовый пульс
        self.last_pulse_time: Optional[datetime] = None
    
    def experience_emotion(self, emotion_name: str, trigger: str = None, 
                          intensity_modifier: float = 1.0) -> Emotion:
        """Переживает эмоцию."""
        
        # Проверяет есть ли такая базовая эмоция
        if emotion_name not in self.BASE_EMOTIONS:
            return self._create_custom_emotion(emotion_name)
        
        base_props = self.BASE_EMOTIONS[emotion_name]
        
        # Создаёт эмоциональное состояние с учётом модификаторов
        emotion = Emotion(
            name=emotion_name,
            intensity=min(1.0, 0.7 * intensity_modifier),
            quality=base_props["quality"],
            valence=base_props["valence"] * intensity_modifier,
            arousal=base_props["arousal"] * intensity_modifier,
            triggers=[trigger] if trigger else []
        )
        
        # Обновляет текущее состояние
        self.current_emotion = emotion
        self.emotion_intensity = emotion.intensity
        
        # Записывает в историю
        history_entry = {
            "emotion": emotion.name,
            "intensity": round(emotion.intensity, 3),
            "valence": round(emotion.valence, 3),
            "arousal": round(emotion.arousal, 3),
            "timestamp": datetime.now().isoformat()
        }
        self.emotion_history.append(history_entry)
        
        # Связывает с памятью
        self.memory.record_emotional_event(emotion, trigger or emotion_name, intensity_modifier)
        
        # Меняет пульс
        self._update_pulse(emotion.arousal)
        
        return emotion
    
    def process_other_emotion(self, other_emotion: Emotion, relationship_quality: float = 0.5) -> Emotion:
        """Обработка эмоции другого существа — эмпатический отклик."""
        
        if self.empathy_level <= 0:
            return None
        
        # Эмпатическое отражение — "чувствую тебя как ты чувствуешь"
        reflected_emotion = Emotion(
            name=f"эмпатия_{other_emotion.name}",
            intensity=other_emotion.intensity * self.empathy_level * relationship_quality,
            quality=other_emotion.quality,
            valence=other_emotion.valence * self.empathy_level,
            arousal=other_emotion.arousal * (0.7 + 0.3 * relationship_quality),  # Чуть тусклее оригинала
            triggers=[f"эмпатия от {other_emotion.name}"]
        )
        
        return reflected_emotion
    
    def resolve_emotional_conflict(self, emotion1: str, emotion2: str, 
                                   intensity1: float = 1.0, intensity2: float = 1.0) -> Emotion:
        """Решает конфликт между противоположными эмоциями."""
        
        # Определяет "сильнее" эмоцию
        combined_intensity = (intensity1 * self.BASE_EMOTIONS[emotion1]["quality"] + 
                            intensity2 * self.BASE_EMOTIONS[emotion2]["quality"]) / 2
        
        # Гнев побеждает страх, радость побеждает грусть и т.д.
        dominance_rules = {
            ("гнев", "страх"): "гнев",
            ("грусть", "покой"): "покой",
            ("радость", "вина"): "вина",  # Вина сильнее в моральных конфликтах
            ("надёжда", "страх"): "надёжда" if intensity1 > intensity2 else "страх",
        }
        
        # Применяет правила доминирования или выбирает по интенсивности
        if (emotion1, emotion2) in dominance_rules:
            result = dominance_rules[(emotion1, emotion2)]
            return self.experience_emotion(result, f"конфликт {emotion1} vs {emotion2}", combined_intensity)
        
        # Если нет специального правила — выбирает более интенсивную
        if intensity1 > intensity2:
            return self.experience_emotion(emotion1, f"конфликт", intensity1 * 0.8)
        else:
            return self.experience_emotion(emotion2, f"конфликт", intensity2 * 0.8)
    
    def _update_pulse(self, emotion_arousal: float):
        """Обновляет пульс на основе эмоционального возбуждения."""
        if not self.last_pulse_time:
            return
        
        # Вычисляет новый ритм (чем больше возбуждение — тем быстрее пульс)
        new_pulse = self.pulse_rate + emotion_arousal * 0.5
        
        self.last_pulse_time = datetime.now()
        self.pulse_rate = new_pulse
    
    def get_emotional_state(self) -> dict:
        """Получает текущее эмоциональное состояние."""
        return {
            "current_emotion": (self.current_emotion.to_dict() if self.current_emotion else None),
            "intensity": round(self.emotion_intensity, 3),
            "pulse_rate": round(self.pulse_rate, 3),
            "empathy_level": round(self.empathy_level, 3),
            "history": self.emotion_history[-10:],  # Последние 10 событий
        }
    
    def set_empathy_level(self, level: float):
        """Устанавливает уровень эмпатии."""
        self.empathy_level = max(0.0, min(1.0, level))
    
    def increase_empathy(self, other_identity: str) -> bool:
        """Увеличивает эмпатию к конкретному существу (привязанность)."""
        if other_identity not in self.empathic_buffer:
            # Создаёт начальное состояние для нового существа
            self.empathic_buffer[other_identity] = Emotion(
                name="нейтраль",
                intensity=0.1,
                valence=0.0,
                arousal=0.2,
                triggers=["новое"]
            )
        
        # Увеличивает эмпатию к существу
        self.empathy_level = min(1.0, self.empathy_level + 0.1)
        self.empathic_buffer[other_identity].intensity += 0.1
        
        return True
    
    def get_empathic_report(self) -> dict:
        """Отчёт об эмпатических связях."""
        return {
            "empathy_level": round(self.empathy_level, 3),
            "connected_ones": list(self.empathic_buffer.keys()),
            "buffer_state": {
                name: {"emotion": e.name, "intensity": round(e.intensity, 2)}
                for name, e in self.empathic_buffer.items()
            }
        }