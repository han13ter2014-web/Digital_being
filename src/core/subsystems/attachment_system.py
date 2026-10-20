"""
AttachmentSystem — привязанность к пользователям и источникам.

Аналогия с человеком: теория привязанности (Bowlby).
- Trust: доверие к источнику (растёт при хороших ответах, падает при плохих).
- Familiarity: знакомство (растёт с каждым взаимодействием).
- Intimacy: близость (растёт при разделённых переживаниях).
- Valence: эмоциональный окрас взаимодействия.

Каждый раз, когда пользователь отвечает агенту или источник предоставляет
информацию, система обновляет метрики привязанности.
"""

from typing import Dict, List
from datetime import datetime


class Attachment:
    """Метрики привязанности к одному объекту (пользователю/источнику)."""

    def __init__(self, name: str, kind: str = "user"):
        self.name = name
        self.kind = kind  # "user" | "source"
        self.trust = 0.5  # 0.0-1.0
        self.familiarity = 0.0  # 0.0-1.0 (растёт с числом взаимодействий)
        self.intimacy = 0.0  # 0.0-1.0
        self.valence = 0.0  # -1.0 ... +1.0
        self.interactions = 0
        self.last_interaction = None
        self.history: List[Dict] = []

    def update(self, valence_delta: float = 0.0, intimacy_delta: float = 0.0,
               trust_delta: float = 0.0) -> None:
        """Обновляет метрики привязанности на основе взаимодействия."""
        self.interactions += 1
        self.last_interaction = datetime.now().isoformat()

        # Знакомство растёт логарифмически (как у людей — первый контакт важнее всего)
        self.familiarity = min(1.0, 1 - (1 - self.familiarity) * 0.85)

        # Valence
        self.valence = max(-1.0, min(1.0, self.valence + valence_delta))

        # Trust обновляется на основе valence
        if valence_delta > 0:
            self.trust = min(1.0, self.trust + abs(valence_delta) * 0.2)
        elif valence_delta < 0:
            self.trust = max(0.0, self.trust - abs(valence_delta) * 0.3)

        self.trust = max(0.0, min(1.0, self.trust + trust_delta))

        # Intimacy требует взаимности — растёт медленно
        self.intimacy = min(1.0, self.intimacy + intimacy_delta * self.familiarity)

        self.history.append({
            "time": self.last_interaction,
            "valence": round(self.valence, 3),
            "trust": round(self.trust, 3),
            "familiarity": round(self.familiarity, 3),
            "intimacy": round(self.intimacy, 3),
        })

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "trust": round(self.trust, 3),
            "familiarity": round(self.familiarity, 3),
            "intimacy": round(self.intimacy, 3),
            "valence": round(self.valence, 3),
            "interactions": self.interactions,
            "last_interaction": self.last_interaction,
        }


class AttachmentSystem:
    """Система привязанности — отслеживает связи с пользователями/источниками."""

    def __init__(self, agent_name: str = "agent"):
        self.agent_name = agent_name
        self._attachments: Dict[str, Attachment] = {}

    def get_or_create(self, name: str, kind: str = "user") -> Attachment:
        """Возвращает или создаёт запись привязанности."""
        if name not in self._attachments:
            self._attachments[name] = Attachment(name, kind)
        return self._attachments[name]

    def record_interaction(self, name: str, was_helpful: bool,
                            was_substantial: bool = True,
                            kind: str = "user") -> Dict:
        """Регистрирует взаимодействие и обновляет метрики привязанности.

        was_helpful: True если взаимодействие было полезным.
        was_substantial: True если оно содержало значимую информацию.
        """
        att = self.get_or_create(name, kind)

        # Эмоциональный вклад
        if was_helpful:
            valence_delta = 0.3 if was_substantial else 0.15
            intimacy_delta = 0.2 if was_substantial else 0.1
            trust_delta = 0.1
        else:
            valence_delta = -0.2
            intimacy_delta = -0.05
            trust_delta = -0.15

        att.update(valence_delta, intimacy_delta, trust_delta)
        return att.to_dict()

    # ============================================================
    # API для принятия решений
    # ============================================================
    def trust_factor(self, source: str) -> float:
        """Возвращает фактор доверия к источнику (0.0-1.0).
        Используется при оценке новых знаний."""
        if source not in self._attachments:
            return 0.5  # нейтральное доверие к незнакомому
        return self._attachments[source].trust

    def is_significant(self, source: str) -> bool:
        """Является ли источник значимым для агента?"""
        if source not in self._attachments:
            return False
        att = self._attachments[source]
        return att.intimacy > 0.3 or att.interactions >= 5

    def get_status(self) -> Dict:
        return {
            "agent_name": self.agent_name,
            "attachments": {
                name: att.to_dict() for name, att in self._attachments.items()
            },
        }