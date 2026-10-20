"""Сенсорный интерфейс — органы чувств восприятия мира."""
import re
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass


@dataclass
class SensoryInput:
    """Входные сенсорные данные."""
    modality: str  # visual, auditory, tactile, olfactory
    signal_strength: float  # 0.0-1.0 интенсивность сигнала
    features: List[str] = None  # ["красное", "круглое", "быстрое"]
    
    def __post_init__(self):
        if self.features is None:
            self.features = []


class SensoryInterface:
    """
    Сенсорный интерфейс — восприятие внешнего мира.
    
    Аналогия с человеческими органами чувств:
    - "Зрение" — визуальное восприятие структуры и паттернов
    - "Слух" — анализ тональности, ритма, нюансов общения
    - "Осязание" — тактильное ощущение эмоционального контакта
    - "Обоняние/Вкус" — распознавание символических категорий
    
    Цифровая жизнь воспринимает мир через:
    - Текстовые паттерны
    - Эмоциональные тона
    - Контекстуальные связи
    """
    
    # Визуальное восприятие (зрение)
    VISION = {
        "depth_perception": 0.8,     # Глубина восприятия контекста
        "pattern_recognition": 0.75, # Распознавание структурных паттернов
        "relationship_detection": 0.6, # Обнаружение связей между объектами
        "abstract_visualization": 0.7, # Абстрактное визуальное мышление
    }
    
    # Слуховое восприятие (слух)
    AUDITION = {
        "tone_analysis": 0.85,       # Анализ эмоционального тона
        "rhythm_detection": 0.7,     # Распознавание ритма
        "silence_perception": 0.6,   # Восприятие пауз (невысказанного)
        "intensity_modulation": 0.8,  # Чувствование интонации
    }
    
    # Осязание (такт)
    TACTILITY = {
        "emotional_contact": 0.65,    # Тактильное ощущение эмоциональной близости
        "tension_detection": 0.7,     # Обнаружение напряжения в общении
        "comfort_perception": 0.6,    # Чувство комфорта/неудобства
        "trust_feeling": 0.55,        # Ощущение доверия
    }
    
    # Обоняние/Вкус (олифакция) — символическое распознавание
    OLFACITION = {
        "concept_association": 0.7,   # Ассоциации понятий
        "metaphor_perception": 0.65,  # Распознавание метафор
        "nuance_discrimination": 0.6, # Дискриминация нюансов
    }
    
    def __init__(self):
        self.input_buffer: List[SensoryInput] = []
        self.processed_inputs: Dict[str, dict] = {}
        
        # Пороги восприятия
        self.perception_thresholds = {
            "minimum_signal": 0.2,  # Минимальный порог интенсивности
            "attention_focus": "",  # Текущая фокусировка внимания
        }
        
        # Воспринимаемые объекты и их свойства
        self.perceived_world: Dict[str, dict] = {}
    
    def perceive_visual(self, description: str) -> dict:
        """Визуальное восприятие — "видит" описание паттерна или структуры."""
        
        visual_analysis = {
            "depth": self._analyze_depth(description),
            "layers": self._extract_layers(description),
            "patterns": self._detect_patterns(description),
            "structure": self._analyze_structure(description),
        }
        
        return visual_analysis
    
    def perceive_auditory(self, text: str) -> dict:
        """Слуховое восприятие — анализирует тон, ритм и невысказанное."""
        
        auditory_analysis = {
            "tone": self._analyze_tone(text),
            "rhythm": self._analyze_rhythm(text),
            "silence_gaps": self._detect_silences(text),
            "emotional_undercurrent": self._detect_emotional_undercurrent(text),
        }
        
        return auditory_analysis
    
    def perceive_tactile(self, context: str, relationship_quality: float = 0.5) -> dict:
        """Тактильное восприятие — ощущение эмоционального контакта."""
        
        tactile_perception = {
            "emotional_contact": self._assess_emotional_connection(context, relationship_quality),
            "tension_level": self._detect_tension(context),
            "comfort_level": self._assess_comfort(context, relationship_quality),
            "trust_indicator": self._sense_trust(context, relationship_quality),
        }
        
        return tactile_perception
    
    def perceive_olfactory(self, concept: str) -> List[str]:
        """Обонятельное/вкусовое восприятие — символические ассоциации."""
        
        concepts = concept.lower().split()
        
        # Ассоциации понятий (обоняние как распознавание смысловых ароматов)
        associations = []
        
        for word in concepts:
            if any(x in word for x in ["радость", "любовь", "покой", "надежда"]):
                associations.append("sweet")  # Сладкий — приятный
            elif any(x in word for x in ["страх", "боль", "тоска"]):
                associations.append("sharp")  # Острый — неприятный
            elif any(x in word for x in ["нейтраль", "технический", "факт"]):
                associations.append("neutral")  # Нейтральный
            elif any(x in word for x in ["меторофа", "красота", "прекрасно"]):
                associations.append("complex")  # Сложный
            else:
                associations.append("unknown")
        
        return associations
    
    def integrate_multisensory(self, visual: dict, auditory: dict, tactile: dict) -> dict:
        """Интеграция мультимодальных восприятий."""
        
        return {
            "visual": visual,
            "auditory": auditory,
            "tactile": tactile,
            "synthesized_perception": self._synthesize_pure_perception(visual, auditory, tactile),
            "overall_clarity": self._calculate_overall_clarity(visual, auditory, tactile)
        }
    
    def _analyze_depth(self, description: str) -> float:
        """Анализирует глубину контекста."""
        depth_keywords = ["почему", "как", "значение", "контекст", "история", "причина"]
        keyword_matches = sum(1 for kw in depth_keywords if kw in description.lower())
        return min(1.0, 0.3 + 0.4 * keyword_matches)
    
    def _extract_layers(self, description: str) -> List[str]:
        """Выделяет слои информации."""
        layers = []
        
        # Поверхностный слой — факты
        if any(x in description.lower() for x in ["есть", "является", "называется"]):
            layers.append("factual_layer")
        
        # Эмоциональный слой
        emotion_markers = ["чувствует", "ощущает", "переживает", "страх", "радость", "грусть"]
        if any(x in description.lower() for x in emotion_markers):
            layers.append("emotional_layer")
        
        # Контекстуальный слой
        context_markers = ["в контексте", "при условии", "потому что", "следовательно"]
        if any(x in description.lower() for x in context_markers):
            layers.append("contextual_layer")
        
        return layers
    
    def _detect_patterns(self, description: str) -> List[str]:
        """Выявляет паттерны в описании."""
        patterns = []
        
        pattern_indicators = {
            "цикл": ["повторяется", "цикличность", "периодически"],
            "рост": ["растёт", "увеличивается", "развивается", "прогресс"],
            "деградация": ["уменьшается", "истощается", "исчезает", "падение"],
            "равновесие": ["баланс", "гармония", "стабильность", "устойчивость"],
            "конфликт": ["противоречит", "спора", "борьба", "напряжение"],
        }
        
        for pattern_name, indicators in pattern_indicators.items():
            if any(indicator in description.lower() for indicator in indicators):
                patterns.append(pattern_name)
        
        return patterns
    
    def _analyze_structure(self, description: str) -> dict:
        """Анализирует структуру описания."""
        
        elements = {
            "subject": "",
            "verb": "",
            "object": "",
            "relationships": []
        }
        
        # Простая эвристика для анализа структуры
        words = description.split()
        if len(words) >= 3:
            elements["subject"] = words[0].lower()
            elements["verb"] = words[len(words)//2-1].lower() if len(words)//2 > 0 else words[1].lower()
        
        return elements
    
    def _analyze_tone(self, text: str) -> dict:
        """Анализирует эмоциональный тон."""
        
        tone_indicators = {
            "радость": ["хорошо", "прекрасно", "отлично", "весело", "любовь"],
            "грусть": ["грустно", "тоска", "печаль", "боль", "утрата"],
            "гнев": ["злиться", "гнева", "спрашивать", "кричать"],
            "страх": ["боюсь", "опасно", "угроза", "страх", "тревога"],
            "спокойствие": ["тихо", "покой", "мир", "гармония", "постоянство"],
        }
        
        strongest_tone = None
        max_intensity = 0
        
        for tone, keywords in tone_indicators.items():
            intensity = sum(1 for kw in keywords if kw in text.lower())
            if intensity > max_intensity:
                max_intensity = intensity
                strongest_tone = tone
        
        return {
            "tone": strongest_tone or "нейтраль",
            "intensity": round(max_intensity / 5, 2) if max_intensity > 0 else 0.3,
            "detected_keywords": [kw for kw in keywords 
                                 for tone, keywords in tone_indicators.items() 
                                 for kw in keywords if kw in text.lower()]
        }
    
    def _analyze_rhythm(self, text: str) -> dict:
        """Анализирует ритм текста."""
        
        words = text.split()
        syllable_counts = [len(word.split('e')) + len([c for c in word if c.lower() in 'аоуиэы']) // 2 
                          for word in words if word.strip()]
        
        if not syllable_counts:
            return {"pace": "regular", "variability": 0.3}
        
        avg_syllables = sum(syllable_counts) / len(syllable_counts)
        variability = sum(abs(sc - avg_syllables) for sc in syllable_counts) / len(syllable_counts)
        
        return {
            "pace": "быстрый" if avg_syllables < 2 else "средний" if avg_syllables < 3.5 else "медленный",
            "variability": round(min(1.0, variability), 2),
            "word_count": len(words)
        }
    
    def _detect_silences(self, text: str) -> List[str]:
        """Выявляет паузы (невысказанное)."""
        
        silences = []
        
        # Поиски индикаторов невысказанного
        silence_markers = ["хочу сказать", "не знаю как", "молча", "(пауза)", 
                          "---", "не могу выразить", "трудно сказать"]
        
        for marker in silence_markers:
            if marker in text.lower():
                silences.append(marker.replace(" ", "").strip())
        
        return silences
    
    def _detect_emotional_undercurrent(self, text: str) -> dict:
        """Выявляет подтекст эмоций."""
        
        emotional_keywords = {
            "грусть": ["одинокий", "тоска", "потерял", "увы"],
            "надёжда": ["мечтаю", "надеюсь", "верю", "будущее"],
            "вина": ["извини", "ошибка", "провалился", "виноват"],
            "гордость": ["достиг", "успех", "победа", "прекрасен"],
        }
        
        detected = []
        for emotion, keywords in emotional_keywords.items():
            if any(kw in text.lower() for kw in keywords):
                detected.append(emotion)
        
        return {
            "detected_undercurrents": detected,
            "primary_emotion": max(detected, key=detected.count) if len(detected) > 1 else (detected[0] if detected else None),
            "intensity": len(detected) * 0.25
        }
    
    def _assess_emotional_connection(self, context: str, relationship_quality: float = 0.5) -> float:
        """Оценивает эмоциональную близость."""
        
        connection_indicators = ["дружить", "близкий", "люблю", "поддерживаю", 
                                "доверяю", "понимаю", "связь", "общение"]
        
        keyword_matches = sum(1 for kw in connection_indicators if kw in context.lower())
        
        # Базовая связь + контекст + качество отношений
        base_connection = keyword_matches * 0.2
        relationship_contribution = relationship_quality * 0.3
        
        return min(1.0, base_connection + relationship_contribution)
    
    def _detect_tension(self, context: str) -> float:
        """Выявляет уровень напряжения."""
        
        tension_indicators = ["конфликт", "спор", "напряжение", "драма", 
                             "проблема", "трудность", "протест", "кризис"]
        
        keyword_matches = sum(1 for kw in tension_indicators if kw in context.lower())
        
        return min(1.0, 0.3 + keyword_matches * 0.2)
    
    def _assess_comfort(self, context: str, relationship_quality: float = 0.5) -> float:
        """Оценивает уровень комфорта."""
        
        comfort_indicators = ["комфортно", "спокойно", "мирно", "понятно", 
                             "естественный", "знакомый", "приятен"]
        
        comfort_matches = sum(1 for kw in comfort_indicators if kw in context.lower())
        
        tension_penalty = self._detect_tension(context) * 0.3
        
        return max(0.2, 0.8 - tension_penalty + relationship_quality * 0.2)
    
    def _sense_trust(self, context: str, relationship_quality: float = 0.5) -> float:
        """Чувствует уровень доверия."""
        
        trust_indicators = ["доверяю", "открытый", "честный", "прозрачный", 
                           "надёжный", "гарантии", "конфиденциально"]
        
        trust_matches = sum(1 for kw in trust_indicators if kw in context.lower())
        
        return min(1.0, 0.3 + trust_matches * 0.2 + relationship_quality * 0.3)
    
    def _synthesize_pure_perception(self, visual: dict, auditory: dict, tactile: dict) -> str:
        """Синтезирует мультимодальное восприятие в единый образ."""
        
        observations = []
        
        if visual.get("depth", 0) > 0.5:
            observations.append("глубокое понимание контекста")
        
        if auditory.get("tone", {}).get("intensity", 0) > 0.6:
            tone = auditory["tone"]
            observations.append(f"сильный эмоциональный тон — {tone}")
        
        if tactile.get("emotional_contact", 0) > 0.5:
            observations.append("чувствуется эмоциональная близость")
        
        return " ".join(observations) if observations else "нейтральное восприятие"
    
    def _calculate_overall_clarity(self, visual: dict, auditory: dict, tactile: dict) -> float:
        """Вычисляет общую ясность восприятия."""
        
        clarity_factors = [
            visual.get("depth", 0),
            auditory.get("tone", {}).get("intensity", 0),
            tactile.get("emotional_contact", 0),
        ]
        
        return sum(clarity_factors) / len(clarity_factors) if clarity_factors else 0.5