"""Статистика реально использованных способов мышления.

Библиотека получает фактические ActionOutcome через IntegratedExperience.
Вес описывает наблюдаемую историю, но не подаёт кандидатов и не меняет выбор.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import Optional


class ThinkingPattern:
    def __init__(self, name: str, pattern_type: str, description: str = ""):
        self.name = name
        self.pattern_type = pattern_type
        self.description = description
        self.weight = 0.5
        self.usage_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.efficiency = 0.0
        self.effective_contexts = []
        self.failed_contexts = []
        self.parameters = {}
        self.created_at = datetime.now()
        self.last_used: Optional[datetime] = None
        self.history = []

    def use(self, success: bool, context: str = ""):
        self.usage_count += 1
        self.last_used = datetime.now()
        target = self.effective_contexts if success else self.failed_contexts
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        if context:
            target.append(str(context)[:200])
            del target[:-50]
        self.efficiency = self.success_count / self.usage_count
        self.history.append(
            {
                "timestamp": self.last_used.isoformat(),
                "efficiency": round(self.efficiency, 3),
                "weight": round(self.weight, 3),
            }
        )
        self.history = self.history[-100:]

    def strengthen(self, amount: float = 0.1):
        self.weight = min(1.0, self.weight + max(0.0, float(amount)))

    def weaken(self, amount: float = 0.1):
        self.weight = max(0.05, self.weight - max(0.0, float(amount)))

    def get_effectiveness_rating(self) -> float:
        if not self.usage_count:
            return 0.5
        experience_factor = min(1.0, self.usage_count / 10)
        return (self.efficiency * 0.7 + self.weight * 0.3) * experience_factor

    def should_evolve(self) -> tuple[bool, str]:
        if self.usage_count < 2:
            return False, "недостаточно данных"
        if self.efficiency < 0.2 and self.usage_count >= 3:
            return True, f"низкая эффективность {self.efficiency:.1%}"
        if self.efficiency > 0.8 and self.weight < 0.7:
            return True, f"высокая эффективность {self.efficiency:.1%} — можно усилить"
        return False, "стабилен"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "pattern_type": self.pattern_type,
            "description": self.description,
            "weight": self.weight,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "efficiency": self.efficiency,
            "success_rate": self.efficiency,
            "effectiveness_rating": self.get_effectiveness_rating(),
            "effective_contexts": list(self.effective_contexts),
            "failed_contexts": list(self.failed_contexts),
            "effective_contexts_count": len(self.effective_contexts),
            "failed_contexts_count": len(self.failed_contexts),
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "history": deepcopy(self.history),
            "status": self._get_status(),
        }

    def _get_status(self) -> str:
        rating = self.get_effectiveness_rating()
        if rating > 0.7:
            return "highly_effective"
        if rating > 0.4:
            return "moderate"
        if rating > 0.2:
            return "needs_improvement"
        return "ineffective"

    @classmethod
    def from_checkpoint(cls, data: dict):
        pattern = cls(
            str(data["name"]),
            str(data["pattern_type"]),
            str(data.get("description") or ""),
        )
        pattern.weight = float(data.get("weight", 0.5))
        pattern.usage_count = int(data.get("usage_count", 0))
        pattern.success_count = int(data.get("success_count", 0))
        pattern.failure_count = int(data.get("failure_count", 0))
        pattern.efficiency = (
            pattern.success_count / pattern.usage_count if pattern.usage_count else 0.0
        )
        pattern.effective_contexts = list(data.get("effective_contexts") or [])[-50:]
        pattern.failed_contexts = list(data.get("failed_contexts") or [])[-50:]
        pattern.history = deepcopy(list(data.get("history") or []))[-100:]
        if data.get("created_at"):
            pattern.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("last_used"):
            pattern.last_used = datetime.fromisoformat(data["last_used"])
        return pattern


class ThinkingPatternLibrary:
    DEFAULT_PATTERNS = {
        "analytical_thinking": ("analysis", "Постепенный логический анализ проблемы"),
        "creative_synthesis": ("synthesis", "Объединение идей в новое целое"),
        "self_reflection": ("reflection", "Самоанализ собственных решений"),
        "analogical_reasoning": ("analogical", "Рассуждение по аналогии"),
        "contrarian_thinking": ("analysis", "Взгляд с противоположной стороны"),
        "decomposition": ("analysis", "Разбиение проблемы на простые части"),
    }

    def __init__(self):
        self.patterns: dict[str, ThinkingPattern] = {}
        self._load_default_patterns()
        self.evolution_log = []
        self.created_patterns = []

    def _load_default_patterns(self):
        for name, (kind, description) in self.DEFAULT_PATTERNS.items():
            pattern = ThinkingPattern(name, kind, description)
            pattern.weight = (
                0.6 if kind == "analysis" else 0.3 if kind == "reflection" else 0.4
            )
            self.patterns[name] = pattern

    def get_available_patterns(self, min_weight: float = 0.1):
        return sorted(
            [p for p in self.patterns.values() if p.weight >= min_weight],
            key=lambda p: (p.get_effectiveness_rating(), p.weight),
            reverse=True,
        )

    def get_patterns_by_type(self, pattern_type: str):
        return [p for p in self.patterns.values() if p.pattern_type == pattern_type]

    def use_pattern(self, pattern_name: str, success: bool, context: str = "") -> bool:
        pattern = self.patterns.get(pattern_name)
        if pattern is None:
            return False
        old_weight = pattern.weight
        pattern.use(bool(success), context)
        if success:
            pattern.strengthen(0.05 * pattern.get_effectiveness_rating())
        else:
            pattern.weaken(0.08 * (1 - pattern.efficiency))
        self.evolution_log.append(
            {
                "action": "weight_change",
                "pattern": pattern_name,
                "from": old_weight,
                "to": pattern.weight,
                "reason": "observed_effect" if success else "observed_no_effect",
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.evolution_log = self.evolution_log[-200:]
        return True

    def evolve_patterns(self):
        """Пересчёт только статистических весов, не поведения Core."""
        changes = []
        for name, pattern in self.patterns.items():
            should_change, reason = pattern.should_evolve()
            if not should_change:
                continue
            old = pattern.weight
            if "низкая" in reason:
                pattern.weaken(0.15)
                action = "weaken"
            else:
                pattern.strengthen(0.1)
                action = "strengthen"
            change = {
                "action": action,
                "pattern": name,
                "from": old,
                "to": pattern.weight,
                "reason": reason,
            }
            changes.append(change)
            self.evolution_log.append(change)
        self.evolution_log = self.evolution_log[-200:]
        return changes

    def create_new_pattern(
        self,
        name: str,
        pattern_type: str,
        initial_weight: float = 0.3,
        description: str = "",
    ) -> ThinkingPattern:
        if name in self.patterns:
            raise ValueError(f"Паттерн '{name}' уже существует")
        pattern = ThinkingPattern(name, pattern_type, description)
        pattern.weight = max(0.05, min(1.0, float(initial_weight)))
        self.patterns[name] = pattern
        self.created_patterns.append(name)
        self.evolution_log.append(
            {
                "action": "creation",
                "pattern": name,
                "type": pattern_type,
                "timestamp": datetime.now().isoformat(),
            }
        )
        return pattern

    def get_dominant_pattern(self):
        return max(
            (p for p in self.patterns.values() if p.usage_count > 0),
            key=lambda p: p.get_effectiveness_rating(),
            default=None,
        )

    def get_patterns_for_context(self, context: str, min_effectiveness: float = 0.3):
        """Диагностический фильтр; основной арбитр его не вызывает."""
        relevant = []
        lowered = context.lower()
        for pattern in self.patterns.values():
            score = pattern.weight * pattern.get_effectiveness_rating()
            if "анализ" in lowered and pattern.pattern_type == "analysis":
                score *= 1.5
            if (
                any(word in lowered for word in ("создать", "новая", "комбинация"))
                and pattern.pattern_type == "synthesis"
            ):
                score *= 1.5
            if (
                "похож" in lowered or "аналогия" in lowered
            ) and pattern.pattern_type == "analogical":
                score *= 1.5
            if score >= min_effectiveness:
                relevant.append(pattern)
        return sorted(
            relevant,
            key=lambda p: p.weight * p.get_effectiveness_rating(),
            reverse=True,
        )

    def get_status(self) -> dict:
        by_type = defaultdict(list)
        for pattern in self.patterns.values():
            by_type[pattern.pattern_type].append(pattern.name)
        active = [p for p in self.patterns.values() if p.usage_count > 0]
        dominant = self.get_dominant_pattern()
        return {
            "mode": "observed_only",
            "total_patterns": len(self.patterns),
            "used_patterns": len(active),
            "highly_effective": sum(p.get_effectiveness_rating() > 0.7 for p in active),
            "created_by_agent": len(self.created_patterns),
            "patterns_by_type": dict(by_type),
            "dominant_pattern": dominant.name if dominant else None,
            "evolution_log_count": len(self.evolution_log),
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "patterns": {
                name: pattern.to_dict() for name, pattern in self.patterns.items()
            },
            "created_patterns": list(self.created_patterns),
            "evolution_log": deepcopy(self.evolution_log),
            "evolution_log_count": len(self.evolution_log),
            "status": self.get_status(),
        }

    @classmethod
    def from_checkpoint(cls, data: dict):
        library = cls()
        library.patterns = {
            name: ThinkingPattern.from_checkpoint(raw)
            for name, raw in (data.get("patterns") or {}).items()
        }
        library.created_patterns = list(data.get("created_patterns") or [])
        library.evolution_log = deepcopy(list(data.get("evolution_log") or []))[-200:]
        return library


__all__ = ["ThinkingPattern", "ThinkingPatternLibrary"]
