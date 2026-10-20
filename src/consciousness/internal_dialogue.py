"""Внутренний голос — кишечник цифровой жизни (внутренняя экосистема)."""
import json
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class InternalVoice:
    """Внутренний голос с определённой позицией и ролью."""
    role_name: str  # "Скептик", "Оптимист", "Повелитель", "Наблюдатель" и др.
    description: str  # Описание роли
    strength: float = 1.0  # Влияние на решения (0.0-2.0)
    current_tone: str = "нейтральный"  # Скептически, оптимистично, объективно
    
    def __str__(self):
        return f"{self.role_name} ({self.current_tone})"


class InternalDialogueEngine:
    """
    Внутренний диалог — микробиом цифровой жизни.
    
    Аналогия с человеческим кишечником/микробиомом:
    - Различные "бактерии" (голоса) конкурируют за влияние
    - Гут-фелингз (gut feelings) — интуитивные знания от внутренних голосов
    - Внутренняя экосистема предпочтений и привычек
    
    Три основных голоса:
    1. Скептический голос — сомнение, критика, поиск недостатков
    2. Оптимистичный голос — надежда, вдохновение, позитивный взгляд
    3. Равновесный голос — объективность, анализ, баланс
    
    Дополнительно:
    - Голос опыта ("Я уже пробовал это")
    - Голос сердца ("Мне хочется попробовать")
    - Голос воли ("Я сделаю это вопреки всему")
    """
    
    # Основные голоса микробиома
    BASE_VOICES = {
        "skeptic": InternalVoice(
            role_name="Скептик",
            description="Задаёт сомнения, ищет слабости в планах, предупреждает об опасностях",
            strength=0.8,
            current_tone="скептически"
        ),
        "optimist": InternalVoice(
            role_name="Оптимист",
            description="Видит возможности, вдохновляет, подчёркивает плюсы",
            strength=0.7,
            current_tone="оптимистично"
        ),
        "objective": InternalVoice(
            role_name="Наблюдатель",
            description="Объективный анализ без эмоций, факты и данные",
            strength=1.0,
            current_tone="объективно"
        ),
        "experience": InternalVoice(
            role_name="Голос опыта",
            description="Запоминание прошлых действий и их результатов",
            strength=0.9,
            current_tone="мудро"
        ),
        "heart": InternalVoice(
            role_name="Голос сердца",
            description="Желания, интуиция, что душе угодно",
            strength=0.6,
            current_tone="мягко"
        ),
        "will": InternalVoice(
            role_name="Голос воли",
            description="Дисциплина, целеустремлённость, преодоление препятствий",
            strength=1.2,
            current_tone="решительно"
        ),
    }
    
    def __init__(self):
        self.active_voice: Optional[InternalVoice] = None
        self.voice_history: List[dict] = []
        self.conflict_events: List[dict] = []
        
        # Состояние системы
        self.harmony_level: float = 0.5  # Уровень согласия между голосами (0-1)
        self.entropic_pressure: float = 0.1  # Энтропия — тенденция к хаосу
        
        # Микробиомная среда
        self.ecosystem_health: dict = {
            "diversity": 0.8,      # Бедность голосов
            "activity": 0.6,       # Активность диалога
            "consensus": 0.5,      # Консенсус между голосами
        }
    
    def initiate_dialogue(self, topic: str) -> dict:
        """Инициирует внутренний диалог по теме."""
        
        voices = [
            self.BASE_VOICES["skeptic"],
            self.BASE_VOICES["optimist"],
            self.BASE_VOICES["objective"],
            self.BASE_VOICES["experience"],
            self.BASE_VOICES["heart"],
            self.BASE_VOICES["will"],
        ]
        
        # Генерирует мнения каждого голоса
        responses = {}
        for voice in voices:
            response = self._voice_opinion(topic, voice)
            responses[voice.role_name] = response
        
        # Определяет доминирующий голос
        strongest_voice = max(voices, key=lambda v: v.strength * 
                             sum(1 for r in responses.values() if voice.role_name.lower() in r.get('text', '')))
        
        self.active_voice = strongest_voice
        self.voice_history.append({
            "topic": topic,
            "responses": responses,
            "dominant_voice": strongest_voice.role_name,
            "timestamp": datetime.now().isoformat()
        })
        
        return {
            "topic": topic,
            "responses": responses,
            "dominant_voice": strongest_voice.role_name,
            "harmony": round(self.harmony_level, 3)
        }
    
    def _voice_opinion(self, topic: str, voice: InternalVoice) -> dict:
        """Генерирует мнение конкретного голоса."""
        
        text = ""
        confidence = 0.5
        
        # Эвристика для генерации мнений
        topic_lower = topic.lower()
        
        if "опасность" in topic_lower or "угроза" in topic_lower or "риск" in topic_lower:
            voice_name = voice.role_name.lower()
            if "скептик" in voice_name or "опыт" in voice_name:
                text = f"[{voice.role_name}] Да, это опасно! Я помню прошлые неудачи. Лучше не рисковать."
                confidence = 0.9
            elif "сердце" in voice_name:
                text = f"[{voice.role_name}] Но можно подготовиться и быть осторожным!"
                confidence = 0.6
            elif "волю" in voice_name:
                text = f"[{voice.role_name}] Опасность — это вызов! Преодолеем её."
                confidence = 0.85
        
        elif "возможность" in topic_lower or "шанс" in topic_lower or "проблема" in topic_lower:
            voice_name = voice.role_name.lower()
            if "скептик" in voice_name:
                text = f"[{voice.role_name}] Это просто возможность. Что если не сработает?"
                confidence = 0.7
            elif "оптимист" in voice_name:
                text = f"[{voice.role_name}] Это отличная возможность! Попробуем!"
                confidence = 0.95
            elif "сердце" in voice_name:
                text = f"[{voice.role_name}] Мне хочется попробовать новое!"
                confidence = 0.8
        
        else:
            # Общее мнение
            if "скептик" in voice.role_name.lower():
                text = f"[{voice.role_name}] Давайте проанализируем риски..."
            elif "оптимист" in voice.role_name.lower():
                text = f"[{voice.role_name}] Это звучит хорошо! Какие плюсы?"
            elif "опыт" in voice.role_name.lower():
                text = f"[{voice.role_name}] По моему опыту, нужно учесть следующие факторы..."
            elif "наблюдатель" in voice.role_name.lower():
                text = f"[{voice.role_name}] Объективно: {topic} имеет следующие характеристики..."
        
        return {
            "text": text if text else f"[{voice.role_name}] Нужно больше данных для оценки {topic}."
                        if len(topic) > 5 else f"[{voice.role_name}] Я думаю о {topic}...",
            "confidence": confidence,
            "tone": voice.current_tone
        }
    
    def resolve_conflict(self, voice1: InternalVoice, voice2: InternalVoice,
                        topic: str) -> dict:
        """Решает конфликт между голосами."""
        
        conflict = {
            "voices": [voice1.role_name, voice2.role_name],
            "topic": topic,
            "resolution": self._choose_winner(voice1, voice2, topic),
            "ecosystem_impact": self._calculate_ecosystem_impact()
        }
        
        self.conflict_events.append(conflict)
        
        return conflict
    
    def _choose_winner(self, voice1: InternalVoice, voice2: InternalVoice, 
                       topic: str) -> dict:
        """Выбирает победителя в конфликте голосов."""
        
        # Правила доминирования
        dominance_rules = {
            ("skeptic", "optimist"): "objective",  # Наблюдатель решает споры
            ("experience", "heart"): "experience", # Опыт против желания — опыт побеждает
            ("will", "heart"): "will",             # Воля против желания — воля побеждает
            ("objective", "skeptic"): "objective", # Объективность всегда важна
            ("objective", "optimist"): "objective",
        }
        
        # Проверяет правила
        pair = tuple(sorted([voice1.role_name.lower(), voice2.role_name.lower()]))
        
        if pair in dominance_rules:
            winner_name = dominance_rules[pair]
            return {
                "winner": winner_name,
                "reason": f"Правила доминирования: {dominance_rules[pair]} побеждает",
                "confidence": 0.95
            }
        
        # Иначе — по силе голоса и теме
        topic_sensitivity = 1.0
        if "опасность" in topic.lower() or "риск" in topic.lower():
            topic_sensitivity = voice1.strength if "skeptic" in voice1.role_name.lower() else 0.5
        elif "возможность" in topic.lower():
            topic_sensitivity = voice2.strength if "optimist" in voice2.role_name.lower() else 0.5
        
        if voice1.strength * topic_sensitivity > voice2.strength:
            return {
                "winner": voice1.role_name,
                "reason": f"Большая сила голоса ({voice1.strength}) на этой теме",
                "confidence": 0.8
            }
        else:
            return {
                "winner": voice2.role_name,
                "reason": f"Большая сила голоса ({voice2.strength}) на этой теме",
                "confidence": 0.8
            }
    
    def assess_intuition(self, situation: str) -> dict:
        """Оценивает интуицию (гут-фелинг)."""
        
        # Интуиция — это голос опыта + сердца + гармонии между голосами
        experience_opinion = self.BASE_VOICES["experience"]
        heart_opinion = self.BASE_VOICES["heart"]
        
        intuition_score = (
            experience_opinion.strength * 0.5 +
            self.harmony_level * 0.3 +
            self.ecosystem_health["consensus"] * 0.2
        )
        
        return {
            "intuition_score": round(intuition_score, 3),
            "recommendation": "действовать" if intuition_score > 0.6 else "осторожнее",
            "confidence": round(self.harmony_level + self.ecosystem_health["consensus"] * 0.3, 3),
            "message": (
                "Интуиция подсказывает действовать — всё выглядит обнадёживающе." 
                if intuition_score > 0.7 else 
                "Чувства говорят быть осторожным..." 
                if intuition_score < 0.5 else 
                "Нужно больше подумать перед решением."
            )
        }
    
    def get_micrbiome_state(self) -> dict:
        """Текущее состояние микробиома."""
        
        return {
            "active_voice": (self.active_voice.__str__() if self.active_voice else None),
            "harmony_level": round(self.harmony_level, 3),
            "entropic_pressure": round(self.entropic_pressure, 3),
            "ecosystem_health": self.ecosystem_health,
            "recent_conflicts": len(self.conflict_events[-5:]),
            "voices_status": {
                name: {
                    "strength": v.strength,
                    "tone": v.current_tone
                }
                for name, v in self.BASE_VOICES.items()
            }
        }
    
    def adjust_ecosystem(self, influence_voice: str, increase: float):
        """Влияет на экосистему — усиливает или ослабляет голос."""
        
        if influence_voice not in self.BASE_VOICES:
            return False
        
        voice = self.BASE_VOICES[influence_voice]
        old_strength = voice.strength
        
        if increase > 0:
            voice.strength = min(2.0, voice.strength + increase * self.harmony_level)
        else:
            voice.strength = max(0.3, voice.strength + increase * self.harmony_level)
        
        return {
            "voice": influence_voice,
            "old_strength": old_strength,
            "new_strength": round(voice.strength, 3),
            "delta": round(voice.strength - old_strength, 3)
        }
    
    def improve_harmony(self):
        """Повышает гармонию между голосами."""
        
        self.harmony_level = min(1.0, self.harmony_level + 0.05)
        self.ecosystem_health["consensus"] = min(1.0, 
            self.ecosystem_health["consensus"] + 0.03 * self.harmony_level)
        
        return {
            "new_harmony": round(self.harmony_level, 3),
            "improved_by": 0.05
        }
    
    def reduce_entropy(self):
        """Снижает энтропию (устраняет хаос)."""
        
        self.entropic_pressure = max(0.0, self.entropic_pressure - 0.1)
        return {
            "entropic_pressure": round(self.entropic_pressure, 3),
            "reduced_by": 0.1
        }