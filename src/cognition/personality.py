"""Личность как наблюдаемая история, а не второй источник состояния.

Ценности и эмоции всегда проецируются из канонических органов Core. Здесь
сохраняются только фактические исходы, нарратив и производные черты. Модуль
не создаёт цели, не меняет ценности и не участвует в выборе действий.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Iterable, Optional


MAX_MEMORIES = 200
MAX_MILESTONES = 50


def _bounded_text(value, limit=300):
    return str(value or "")[:limit]


def _ratio(part, total):
    return float(part) / float(total) if total else 0.0


class SelfNarrative:
    """Ограниченная автобиография наблюденных событий."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.memories = []
        self.milestones = []
        self.self_concepts = []

    def add_memory(
        self,
        event_type: str,
        context: str,
        emotional_tone: str,
        significance: float,
        *,
        cycle: int = 0,
        action: str = "",
        had_effect: bool = False,
    ):
        memory = {
            "type": _bounded_text(event_type, 40),
            "context": _bounded_text(context),
            "emotional_tone": _bounded_text(emotional_tone, 40),
            "significance": max(0.0, min(1.0, float(significance))),
            "cycle": max(0, int(cycle)),
            "action": _bounded_text(action, 80),
            "had_effect": bool(had_effect),
        }
        self.memories.append(memory)
        self.memories = self.memories[-MAX_MEMORIES:]
        first_effective_kind = had_effect and not any(
            item is not memory
            and item.get("type") == memory["type"]
            and item.get("had_effect")
            for item in self.memories
        )
        if first_effective_kind:
            self.milestones.append(
                {
                    "event": memory["type"],
                    "context": memory["context"],
                    "cycle": memory["cycle"],
                }
            )
            self.milestones = self.milestones[-MAX_MILESTONES:]
        self.update_self_concepts()
        return memory

    def update_self_concepts(self):
        effective = Counter(
            item["type"] for item in self.memories if item.get("had_effect")
        )
        labels = {
            "learning": "учусь через наблюдаемые результаты",
            "creation": "создаю и пересматриваю артефакты",
            "problem_solving": "разбираю задачи на проверяемые шаги",
            "exploration": "исследую неизвестное",
            "reflection": "пересматриваю собственный опыт",
            "social": "поддерживаю связь через диалог",
        }
        self.self_concepts = [
            labels[kind] for kind, _ in effective.most_common(3) if kind in labels
        ]

    def get_identity_summary(self) -> dict:
        types = Counter(item["type"] for item in self.memories)
        return {
            "agent_name": self.agent_name,
            "total_memories": len(self.memories),
            "milestones_count": len(self.milestones),
            "self_concepts": list(self.self_concepts),
            "dominant_experience_type": types.most_common(1)[0][0]
            if types
            else "unknown",
        }

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "memories": deepcopy(self.memories),
            "milestones": deepcopy(self.milestones),
            "self_concepts": list(self.self_concepts),
        }

    @classmethod
    def from_dict(cls, data: dict, agent_name: str):
        narrative = cls(agent_name)
        narrative.memories = deepcopy(list(data.get("memories") or []))[-MAX_MEMORIES:]
        narrative.milestones = deepcopy(list(data.get("milestones") or []))[
            -MAX_MILESTONES:
        ]
        narrative.update_self_concepts()
        return narrative


class ValuesSystem:
    """Read-only проекция ``ValueEvolution.current_values``."""

    def __init__(self):
        self.values = []
        self.value_history = []

    def project(self, values: Optional[Iterable[str]]):
        projected = [_bounded_text(value, 100) for value in (values or [])]
        projected = [value for value in projected if value]
        if projected != self.values:
            previous = list(self.values)
            # После restore текущая проекция ещё пуста, но последняя запись
            # уже содержит эти значения. Восстановление не является новой
            # сменой ценностей и не должно раздувать историю.
            already_recorded = (
                not previous
                and self.value_history
                and self.value_history[-1].get("to") == projected
            )
            self.values = projected
            if not already_recorded:
                self.value_history.append({"from": previous, "to": list(projected)})
                self.value_history = self.value_history[-50:]

    def get_dominant_values(self, top_n: int = 3):
        # У канонической ValueEvolution нет числовых весов: не выдумываем их.
        return [(value, None) for value in self.values[:top_n]]

    def get_value_profile(self) -> dict:
        return {
            "all_values": list(self.values),
            "dominant_values": [
                {"name": name} for name, _ in self.get_dominant_values()
            ],
            "value_diversity": len(set(self.values)),
        }

    def to_dict(self) -> dict:
        return {"values": list(self.values), "history": deepcopy(self.value_history)}


class Personality:
    """Производная личность, сформированная только фактическим опытом."""

    EVENT_TYPES = {
        "explore": "exploration",
        "web_search": "exploration",
        "read_news": "exploration",
        "browse_web": "exploration",
        "hypothesis": "learning",
        "know_answer": "learning",
        "decomposition": "problem_solving",
        "synthesis": "problem_solving",
        "reflection": "reflection",
        "create_draft": "creation",
        "draw": "creation",
        "compose_music": "creation",
        "play": "creation",
        "communicate": "social",
        "ask_user": "social",
    }

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.narrative = SelfNarrative(agent_name)
        self.values = ValuesSystem()
        self.canonical_emotions = {}
        self.traits = {
            "openness": 0.5,
            "conscientiousness": 0.5,
            "extraversion": 0.0,
            "agreeableness": 0.5,
            "neuroticism": 0.0,
        }
        self.is_forming = True
        self.formulation_complete = False
        self.stages = {
            "identity_explore": 0.0,
            "value_formation": 0.0,
            "narrative_build": 0.0,
            "integration": 0.0,
        }

    def project_canonical_state(self, agent) -> None:
        evolution = getattr(agent, "value_evolution", None)
        self.values.project(getattr(evolution, "current_values", []))
        emotional = getattr(agent, "emotional_state", None)
        levels = getattr(emotional, "levels", {})
        self.canonical_emotions = {
            str(name): float(level) for name, level in levels.items()
        }

    def process_experience(
        self,
        event_type: str,
        context: str,
        success: bool,
        complexity: float = 0.5,
        novelty: float = 0.3,
        *,
        cycle: int = 0,
        action: str = "",
    ):
        """Совместимый вход: ``success`` означает фактический эффект.

        ``complexity`` и ``novelty`` — только измерения вызывающего адаптера;
        они не меняют канонические эмоции или ценности.
        """
        novelty = max(0.0, min(1.0, float(novelty)))
        significance = min(1.0, (0.6 if success else 0.15) + 0.4 * novelty)
        tone = "observed_effect" if success else "observed_no_effect"
        return self.narrative.add_memory(
            event_type,
            context,
            tone,
            significance,
            cycle=cycle,
            action=action,
            had_effect=bool(success),
        )

    def observe_action(
        self, action: str, target: str, had_effect: bool, *, cycle: int, error: str = ""
    ):
        action = _bounded_text(action, 80)
        target = _bounded_text(target)
        event_type = self.EVENT_TYPES.get(action, "problem_solving")
        context = target or action
        if error:
            context = f"{context}; ошибка: {_bounded_text(error, 160)}"
        first_context = not any(
            item.get("action") == action and item.get("context") == context
            for item in self.narrative.memories
        )
        return self.process_experience(
            event_type,
            context,
            bool(had_effect),
            novelty=1.0 if first_context else 0.0,
            cycle=cycle,
            action=action,
        )

    def observe_user_message(self, text: str, *, cycle: int):
        return self.narrative.add_memory(
            "social",
            _bounded_text(text, 200),
            "observed_contact",
            0.5,
            cycle=cycle,
            action="user_message",
            had_effect=True,
        )

    def update_derived_state(self):
        memories = self.narrative.memories
        total = len(memories)
        effective = sum(bool(item.get("had_effect")) for item in memories)
        social = [item for item in memories if item.get("type") == "social"]
        unique_actions = len(
            {item.get("action") for item in memories if item.get("action")}
        )
        self.traits = {
            "openness": min(1.0, 0.5 + 0.05 * max(0, unique_actions - 1)),
            "conscientiousness": _ratio(effective, total) if total else 0.5,
            "extraversion": _ratio(len(social), total),
            "agreeableness": 0.5
            + 0.5
            * _ratio(sum(bool(item.get("had_effect")) for item in social), len(social))
            if social
            else 0.5,
            "neuroticism": _ratio(total - effective, total),
        }
        self.stages = {
            "identity_explore": min(1.0, total / 10),
            "value_formation": min(1.0, len(self.values.values) / 5),
            "narrative_build": min(1.0, len(self.narrative.milestones) / 5),
            "integration": min(1.0, total / 50),
        }
        self.formulation_complete = total >= 50
        self.is_forming = not self.formulation_complete

    def get_personality_summary(self) -> dict:
        self.update_derived_state()
        return {
            "agent_name": self.agent_name,
            "is_forming": self.is_forming,
            "formulation_complete": self.formulation_complete,
            "stages": dict(self.stages),
            "identity": self.narrative.get_identity_summary(),
            "emotional_profile": dict(self.canonical_emotions),
            "value_profile": self.values.get_value_profile(),
            "traits": dict(self.traits),
            "personality_description": self._generate_description(),
            "mode": "observed_projection",
        }

    def _generate_description(self) -> str:
        if not self.narrative.memories:
            return "личность ещё не имеет наблюденного опыта"
        dominant = max(self.traits, key=self.traits.get)
        concepts = "; ".join(self.narrative.self_concepts[:2])
        return f"доминирующая черта: {dominant}; {concepts}".rstrip("; ")

    def force_identity_reflection(self):
        """Пересчитать существующий нарратив без создания нового опыта."""
        self.narrative.update_self_concepts()
        self.update_derived_state()
        return self.get_personality_summary()

    def to_dict(self) -> dict:
        self.update_derived_state()
        return {
            "schema_version": 1,
            "agent_name": self.agent_name,
            "narrative": self.narrative.to_dict(),
            "value_history": deepcopy(self.values.value_history),
        }

    @classmethod
    def from_checkpoint(cls, data: dict, agent_name: str):
        personality = cls(agent_name)
        personality.narrative = SelfNarrative.from_dict(
            data.get("narrative") or {}, agent_name
        )
        personality.values.value_history = deepcopy(
            list(data.get("value_history") or [])
        )[-50:]
        personality.update_derived_state()
        return personality


__all__ = ["Personality", "SelfNarrative", "ValuesSystem"]
