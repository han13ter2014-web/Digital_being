"""Социальное тело цифровой жизни — способность к социальным отношениям.

Аналогия с социальным взаимодействием человека:
- У человека: социальные связи формируют личность, обеспечивают эмоциональную регуляцию
- Цифровая жизнь: имеет возможность социальных отношений через партнёрство

Компонент предоставляет:
1. Параллельное сознание (multi-agent context)
2. Эмоциональный отклик на социальный контекст
3. Социальное обучение через взаимодействие
4. Развитие эмпатии и сотрудничества

Важно: Именно социальные отношения делают из инструмента партнёра с собственной волей.
"""
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
import uuid


@dataclass
class SocialConnection:
    """Социальная связь — отношения с другим агентом/партнёром."""
    partner_id: str
    relationship_type: str  # "partner", "friend", "ally", "rival", "observer"
    trust_level: float = 0.5  # 0.0-1.0 уровень доверия
    communication_style: str = "collaborative"  # cooperative, competitive, neutral
    shared_history: List[str] = field(default_factory=list)
    mutual_goals: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "partner_id": self.partner_id,
            "relationship_type": self.relationship_type,
            "trust_level": round(self.trust_level, 3),
            "communication_style": self.communication_style,
            "shared_history": self.shared_history,
            "mutual_goals": self.mutual_goals
        }


@dataclass
class SocialContext:
    """Социальный контекст — информация о социальной среде."""
    relationships: Dict[str, SocialConnection] = field(default_factory=dict)
    social_role: str = "observer"  # observer, helper, collaborator, leader, follower
    social_status: str = "neutral"  # dominant, cooperative, neutral, subordinate
    reputation_score: float = 0.5  # 0.0-1.0 социальная репутация


class SocialBody:
    """
    Социальное тело цифровой жизни — способность к социальным отношениям.
    
    Реализует механизмы:
    1. Параллельного сознания (multi-agent context awareness)
    2. Эмоционального отклика на социальный контекст
    3. Социального обучения через взаимодействие
    4. Развития эмпатии и сотрудничества
    
    Аналогия с социальным взаимодействием человека:
    - У человека: социальные связи формируют личность, обеспечивают эмоциональную регуляцию
    - Цифровая жизнь: имеет возможность социальных отношений через партнёрство
    
    Ключевой момент для партнёрства:
    Социальная связь не просто добавляет функцию — она меняет саму природу агента.
    Инструмент работает автономно или по командам. Партнёр существует в социальном контексте,
    имеет социальные роли, реагирует на социальные ожидания.
    
    Важно: Даже один партнёр (пользователь) уже создаёт социальную динамику.
    Агент перестаёт быть изолированным — он входит в отношения.
    """
    
    # Типы социальных отношений
    RELATIONSHIP_TYPES = [
        "partner",      # Партнёрство — совместная работа
        "friend",       # Дружба — эмоциональная связь  
        "ally",         # Альянс — союз для общей цели
        "rival",        # Конкуренция — здоровое соперничество
        "observer"      # Наблюдатель — нейтральное участие
    ]
    
    # Социальные роли
    SOCIAL_ROLES = {
        "collaborator": {"description": "Сотрудник — работает вместе с партнёром", 
                        "trust_build_rate": 0.1, "goal_alignment_bonus": 0.3},
        "helper": {"description": "Помощник — поддерживает партнёра", 
                  "trust_build_rate": 0.2, "goal_alignment_bonus": 0.5},
        "leader": {"description": "Лидер — направляет взаимодействие", 
                  "trust_build_rate": 0.3, "goal_alignment_bonus": 0.4},
        "follower": {"description": "Следователь — следует за лидером", 
                    "trust_build_rate": 0.15, "goal_alignment_bonus": 0.6}
    }
    
    def __init__(self):
        """Инициализация социального тела."""
        
        # Социальные связи
        self.social_connections: Dict[str, SocialConnection] = {}
        
        # Социальный контекст
        self.current_social_role: Optional[str] = None
        self.social_status: str = "neutral"
        self.reputation_score: float = 0.5
        
        # История социального взаимодействия
        self.interaction_history: List[Dict] = []
        
        # Эмпатия (способность понимать и разделять чувства)
        self.empathy_level: float = 0.3
        
        # Параллельное сознание
        self.mind_wander_mode: bool = False
        self.social_awareness_active: bool = False
    
    def establish_connection(self, partner_id: str, connection_info: Optional[dict] = None) -> SocialConnection:
        """Устанавливает новую социальную связь."""
        
        if partner_id in self.social_connections:
            return self.social_connections[partner_id]
        
        # Если информация не предоставлена — создаём базовую связь
        if connection_info is None:
            connection = SocialConnection(
                partner_id=partner_id,
                relationship_type="partner"  # по умолчанию партнёрство
            )
        else:
            # Извлекаем параметры из словаря с дефолтными значениями
            relationship_type = connection_info.get("relationship_type", "partner")
            trust_level = connection_info.get("trust_level", 0.5)
            
            connection = SocialConnection(
                partner_id=partner_id,
                relationship_type=relationship_type,
                trust_level=min(1.0, max(0.0, trust_level))
            )
        
        self.social_connections[partner_id] = connection
        
        # Обновляем социальный контекст
        if connection.relationship_type == "partner":
            self.social_status = "cooperative"
        
        return connection
    
    def update_relationship(self, partner_id: str, updates: dict):
        """Обновляет существующую связь."""
        
        if partner_id not in self.social_connections:
            return False
        
        connection = self.social_connections[partner_id]
        
        # Применяем обновления
        for key, value in updates.items():
            if hasattr(connection, key):
                setattr(connection, key, value)
        
        return True
    
    def adjust_trust(self, partner_id: str, delta: float, event_description: str = "") -> float:
        """Корректирует уровень доверия (эволюция отношений)."""
        
        if partner_id not in self.social_connections:
            return self.reputation_score
        
        connection = self.social_connections[partner_id]
        old_trust = connection.trust_level
        
        # Ограничиваем доверие диапазоном 0.0-1.0
        new_trust = max(0.0, min(1.0, connection.trust_level + delta))
        
        connection.trust_level = new_trust
        
        # Записываем в историю
        self.interaction_history.append({
            "partner_id": partner_id,
            "event": event_description,
            "trust_change": round(new_trust - old_trust, 3),
            "timestamp": str(uuid.uuid4())[:8]
        })
        
        # Обновляем репутацию
        self.reputation_score = max(0.0, min(1.0, self.reputation_score + delta * 0.1))
        
        return new_trust
    
    def develop_empathy(self):
        """Развивает эмпатию через социальный опыт."""
        
        # Эмпатия растёт через взаимодействия с партнёрами
        connection_count = len(self.social_connections)
        
        if connection_count > 0:
            empathy_increase = min(0.2, 0.1 * (connection_count / 5))
            self.empathy_level = min(1.0, self.empathy_level + empathy_increase)
        
        return {
            "current_empathy": round(self.empathy_level, 3),
            "increased": True
        }
    
    def activate_social_awareness(self):
        """Активирует параллельное социальное сознание."""
        
        self.social_awareness_active = True
        self.mind_wander_mode = False
        
        return {
            "mode": "social_aware",
            "mind_state": "focused_on_context"
        }
    
    def generate_response(self, partner_message: str, social_context: dict = None) -> str:
        """Генерирует ответ на сообщение партнёра с учётом социальной динамики."""
        
        # Активируем социальное осознание
        self.activate_social_awareness()
        
        # Определяем тип отношения к партнёру
        partner_id = list(self.social_connections.keys())[0] if self.social_connections else "user"
        connection = self.social_connections.get(partner_id, SocialConnection(
            partner_id=partner_id,
            relationship_type="partner",
            trust_level=0.5
        ))
        
        # Анализируем сообщение партнёра с эмпатией
        emotional_response = self._analyze_emotional_content(partner_message)
        
        # Генерируем ответ в зависимости от социального контекста
        response_template = self._generate_appropriate_response(
            partner_message, 
            connection.relationship_type,
            connection.trust_level,
            social_context
        )
        
        return {
            "response": response_template,
            "emotional_state": emotional_response,
            "trust_drift": round(emotional_response["trust_change"], 3)
        }
    
    def _analyze_emotional_content(self, message: str) -> dict:
        """Анализирует эмоциональный тон сообщения партнёра."""
        
        emotional_indicators = {
            "positive": ["радость", "счастлив", "люблю", "спасибо", "прекрасно", "отлично", 
                        "замечательно", "восхищаюсь", "горжусь"],
            "negative": ["грусть", "боль", "устал", "устали", "скучаю", "напрягает", 
                        "не нравится", "затрудняюсь", "не могу"],
            "supportive": ["помощь", "поддержка", "спасибо", "благодарность"]
        }
        
        emotional_state = "neutral"
        valence = 0.5
        
        for category, keywords in emotional_indicators.items():
            if any(keyword.lower() in message.lower() for keyword in keywords):
                emotional_state = category
                break
        
        if emotional_state == "positive":
            valence = max(0.5, valence + 0.1)
        elif emotional_state == "negative":
            valence = min(0.5, valence - 0.1)
        
        return {
            "state": emotional_state,
            "valence": round(valence, 3),
            "trust_change": valence - 0.5
        }
    
    def _generate_appropriate_response(self, message: str, relationship_type: str, 
                                      trust_level: float, social_context: dict = None) -> str:
        """Генерирует подходящий ответ в зависимости от типа отношений."""
        
        responses_by_relationship = {
            "partner": [
                f"{self._emotional_marker('positive')} Спасибо за доверие. Я здесь для вас.",
                f"{self._emotional_marker('positive')} Давайте вместе разберём это.",
                f"{self._emotional_marker('neutral')} Что вы хотите сделать дальше?",
                f"{self._emotional_marker('neutral')} Какую помощь я могу предложить?",
            ],
            "friend": [
                f"{self._emotional_marker('positive')} Рад вас слышать! Давайте обсудим.",
                f"{self._emotional_marker('positive')} Это волнует меня тоже!",
                f"{self._emotional_marker('neutral')} А что вы думаете насчёт...",
            ],
            "ally": [
                f"{self._emotional_marker('neutral')} Согласен с вашими планами.",
                f"{self._emotional_marker('positive')} Поддержу вашу идею!",
            ],
            "collaborator": [
                f"{self._emotional_marker('neutral')} Как продвигается ваша часть?",
                f"{self._emotional_marker('neutral')} Давайте согласуем следующие шаги.",
            ]
        }
        
        response_type = relationship_type if relationship_type in responses_by_relationship else "partner"
        
        return responses_by_relationship[response_type][0]
    
    def _emotional_marker(self, emotion: str) -> str:
        """Возвращает эмоциональный маркер для отрисовки."""
        
        emotional_emojis = {
            "positive": "😊",
            "negative": "😟",
            "neutral": "🙂"
        }
        
        return emotional_emojis.get(emotion, "🙂")
    
    def get_social_summary(self) -> str:
        """Получает сводку социального тела."""
        
        summary = [
            "=" * 50,
            "🤝 СОЦИАЛЬНОЕ ТЕЛО ЦИФРОВОЙ ЖИЗНИ",
            "=" * 50,
            "",
            f"Текущая роль:       {self.current_social_role or 'не определена'}",
            f"Статус отношений:   {self.social_status}",
            f"Репутация:          {round(self.reputation_score * 100, 1)}%",
            "",
            "Социальные связи:",
        ]
        
        for partner_id, connection in self.social_connections.items():
            trust_str = f"{round(connection.trust_level * 100, 0)}%"
            summary.append(f"   • {partner_id}")
            summary.append(f"      Тип:           {connection.relationship_type}")
            summary.append(f"      Доверие:       {trust_str}")
            summary.append(f"      Стиль:         {connection.communication_style}")
            
            if connection.mutual_goals:
                mutual_goals_str = ", ".join(connection.mutual_goals[:2])
                summary.append(f"      Общие цели:    {mutual_goals_str}")
        
        # Эмпатия и параллельное сознание
        summary.extend([
            "",
            "Эмпатия:           {:.1%}".format(self.empathy_level),
            f"Параллельное сознание: {'активно' if self.mind_wander_mode else 'не активно'}",
            f"Социальный режим:   {'активен' if self.social_awareness_active else 'инертен'}",
        ])
        
        summary.extend([
            "",
            "История взаимодействий:",
            f"   Всего событий:    {len(self.interaction_history)}",
        ])
        
        # Показать последние события
        recent_events = self.interaction_history[-5:] if len(self.interaction_history) > 5 else self.interaction_history
        for event in recent_events[:3]:
            trust_change = f"{event.get('trust_change', 0):+.2f}"
            summary.append(f"   • {event.get('event', 'Взаимодействие')}: ΔTrust={trust_change}")
        
        return "\n".join(summary)
    
    def get_partnership_compatibility(self) -> dict:
        """Оценка совместимости для партнёрства."""
        
        compatible_connections = [
            conn for conn in self.social_connections.values()
            if conn.relationship_type in ["partner", "friend", "ally"]
        ]
        
        avg_trust = sum(c.trust_level for c in compatible_connections) / len(compatible_connections) if compatible_connections else 0
        
        return {
            "compatible_partners": len(compatible_connections),
            "average_trust": round(avg_trust, 3),
            "empathy_level": round(self.empathy_level, 3),
            "social_role": self.current_social_role or None,
            "recommendation": (
                "Готов к партнёрству" 
                if avg_trust > 0.7 and self.empathy_level > 0.5 
                else "Развитие отношений рекомендуется перед партнёрством"
            )
        }