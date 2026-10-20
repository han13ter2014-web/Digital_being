"""
Система мыслительных паттернов — базовые единицы мышления агента.

Паттерны можно:
- Создавать новые
- Усиливать/ослаблять существующие
- Комбинировать для решения задач
- Отбрасывать неэффективные
"""

from collections import defaultdict
from datetime import datetime


class ThinkingPattern:
    """Один паттерн мышления — способ обработки информации."""
    
    def __init__(self, name: str, pattern_type: str, description: str = ""):
        self.name = name
        self.pattern_type = pattern_type  # analysis, synthesis, reflection, creative, analogical
        
        # Вес — насколько часто агент его использует и предпочитает
        self.weight = 0.5  # 0.0 - 1.0
        
        # История успешности
        self.usage_count = 0
        self.success_count = 0
        self.failure_count = 0
        
        # Эффективность (процент успеха)
        self.efficiency = 0.0
        
        # Контексты в которых паттерн работал хорошо/плохо
        self.effective_contexts = []
        self.failed_contexts = []
        
        # Параметры паттерна (настраиваемые)
        self.parameters = {}
        
        self.created_at = datetime.now()
        self.last_used = None
        
        self.history = []  # История изменений веса
    
    def use(self, success: bool, context: str = ""):
        """Регистрирует использование паттерна."""
        self.usage_count += 1
        self.last_used = datetime.now()
        
        if success:
            self.success_count += 1
            if context:
                self.effective_contexts.append(context)
        else:
            self.failure_count += 1
            if context:
                self.failed_contexts.append(context)
        
        # Пересчитывает эффективность
        total = self.success_count + self.failure_count
        self.efficiency = self.success_count / total if total > 0 else 0.0
        
        # Записывает состояние в историю
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "efficiency": round(self.efficiency, 3),
            "weight": round(self.weight, 3)
        })
    
    def strengthen(self, amount: float = 0.1):
        """Усиливает паттерн (делает его более доступным)."""
        self.weight = min(1.0, self.weight + amount)
    
    def weaken(self, amount: float = 0.1):
        """Ослабляет паттерн."""
        self.weight = max(0.05, self.weight - amount)
    
    def get_effectiveness_rating(self) -> float:
        """Получает общую оценку эффективности с учетом веса и истории."""
        if self.usage_count == 0:
            return 0.5  # Нейтральная оценка для неиспользованных
        
        # Комбинация эффективности и частоты использования
        experience_factor = min(1.0, self.usage_count / 10)
        weighted_effectiveness = self.efficiency * 0.7 + self.weight * 0.3
        
        return weighted_effectiveness * experience_factor
    
    def should_evolve(self) -> tuple[bool, str]:
        """Определяет нужно ли менять паттерн."""
        if self.usage_count < 2:
            return False, "недостаточно данных"
        
        # Если эффективность очень низкая — ослаблять или удалять
        if self.efficiency < 0.2 and self.usage_count >= 3:
            return True, f"низкая эффективность {self.efficiency:.1%}"
        
        # Если эффективность высокая — усиливать
        if self.efficiency > 0.8 and self.weight < 0.7:
            return True, f"высокая эффективность {self.efficiency:.1%} — можно усилить"
        
        return False, "стабилен"
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "pattern_type": self.pattern_type,
            "weight": round(self.weight, 3),
            "usage_count": self.usage_count,
            "success_rate": round(self.efficiency, 3),
            "effectiveness_rating": round(self.get_effectiveness_rating(), 3),
            "effective_contexts_count": len(self.effective_contexts),
            "failed_contexts_count": len(self.failed_contexts),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "status": self._get_status()
        }
    
    def _get_status(self) -> str:
        rating = self.get_effectiveness_rating()
        if rating > 0.7:
            return "highly_effective"
        elif rating > 0.4:
            return "moderate"
        elif rating > 0.2:
            return "needs_improvement"
        else:
            return "ineffective"


class ThinkingPatternLibrary:
    """Библиотека мыслительных паттернов агента."""
    
    # Стандартные паттерны для инициализации
    DEFAULT_PATTERNS = {
        "pattern_analysis": {
            "name": "analytical_thinking",
            "type": "analysis",
            "description": "Постепенный логический анализ проблемы"
        },
        "pattern_synthesis": {
            "name": "creative_synthesis",
            "type": "synthesis", 
            "description": "Объединение разрозненных идей в новое целое"
        },
        "pattern_reflection": {
            "name": "self_reflection",
            "type": "reflection",
            "description": "Самоанализ собственных мыслей и решений"
        },
        "pattern_analogical": {
            "name": "analogical_reasoning",
            "type": "analogical",
            "description": "Рассуждение по аналогии с похожими ситуациями"
        },
        "pattern_contrarian": {
            "name": "contrarian_thinking",
            "type": "analysis",
            "description": "Попытка посмотреть на проблему с противоположной стороны"
        },
        "pattern_decomposition": {
            "name": "decomposition",
            "type": "analysis",
            "description": "Разбиение сложной проблемы на простые части"
        },
    }
    
    def __init__(self):
        self.patterns: dict[str, ThinkingPattern] = {}
        self._load_default_patterns()
        
        # История эволюции паттернов
        self.evolution_log = []
        self.created_patterns = []  # Паттерны созданные агентом
    
    def _load_default_patterns(self):
        """Загружает стандартные паттерны."""
        for key, config in self.DEFAULT_PATTERNS.items():
            pattern = ThinkingPattern(
                name=config["name"],
                pattern_type=config["type"],
                description=config["description"]
            )
            # Начальный вес зависит от типа
            if config["type"] == "analysis":
                pattern.weight = 0.6  # Аналитика — базовый паттерн
            elif config["type"] == "reflection":
                pattern.weight = 0.3  # Рефлексия — развивается
            else:
                pattern.weight = 0.4
            
            self.patterns[config["name"]] = pattern
    
    def get_available_patterns(self, min_weight: float = 0.1) -> list[ThinkingPattern]:
        """Возвращает доступные паттерны, отсортированные по весу."""
        return sorted(
            [p for p in self.patterns.values() if p.weight >= min_weight],
            key=lambda p: (p.get_effectiveness_rating(), p.weight),
            reverse=True
        )
    
    def get_patterns_by_type(self, pattern_type: str) -> list[ThinkingPattern]:
        """Возвращает паттерны определенного типа."""
        return [p for p in self.patterns.values() if p.pattern_type == pattern_type]
    
    def use_pattern(self, pattern_name: str, success: bool, context: str = "") -> bool:
        """Регистрирует использование паттерна и корректирует вес."""
        if pattern_name not in self.patterns:
            return False
        
        pattern = self.patterns[pattern_name]
        old_weight = pattern.weight
        
        pattern.use(success, context)
        
        # Корректировка веса на основе успеха
        if success:
            pattern.strengthen(0.05 * pattern.get_effectiveness_rating())
        else:
            pattern.weaken(0.08 * (1 - pattern.efficiency))  # Сильнее ослабляем если неудача
        
        # Записывает в журнал эволюции
        if abs(pattern.weight - old_weight) > 0.01:
            self.evolution_log.append({
                "action": "weight_change",
                "pattern": pattern_name,
                "from": round(old_weight, 3),
                "to": round(pattern.weight, 3),
                "reason": f"usage {'success' if success else 'failure'}",
                "timestamp": datetime.now().isoformat()
            })
        
        return True
    
    def evolve_patterns(self) -> list[dict]:
        """Выполняет эволюцию паттернов: усиливает эффективные, ослабляет неэффективные."""
        changes = []
        
        for name, pattern in self.patterns.items():
            should_change, reason = pattern.should_evolve()
            
            if should_change:
                old_weight = pattern.weight
                
                if "низкая эффективность" in reason:
                    pattern.weaken(0.15)
                    changes.append({
                        "action": "weaken",
                        "pattern": name,
                        "from": round(old_weight, 3),
                        "to": round(pattern.weight, 3),
                        "reason": reason
                    })
                
                elif "усилить" in reason:
                    pattern.strengthen(0.1)
                    changes.append({
                        "action": "strengthen",
                        "pattern": name,
                        "from": round(old_weight, 3),
                        "to": round(pattern.weight, 3),
                        "reason": reason
                    })
                
                self.evolution_log.append({
                    "action": "evolution_step",
                    "pattern": name,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat()
                })
        
        return changes
    
    def create_new_pattern(self, name: str, pattern_type: str, 
                           initial_weight: float = 0.3,
                           description: str = "") -> ThinkingPattern:
        """Агент создает новый паттерн мышления."""
        if name in self.patterns:
            raise ValueError(f"Паттерн '{name}' уже существует")
        
        pattern = ThinkingPattern(name, pattern_type, description)
        pattern.weight = initial_weight
        self.patterns[name] = pattern
        self.created_patterns.append(name)
        
        self.evolution_log.append({
            "action": "creation",
            "pattern": name,
            "type": pattern_type,
            "timestamp": datetime.now().isoformat()
        })
        
        return pattern
    
    def get_dominant_pattern(self) -> ThinkingPattern:
        """Возвращает доминирующий паттерн (наивысшая эффективность)."""
        if not self.patterns:
            return None
        return max(
            (p for p in self.patterns.values() if p.usage_count > 0),
            key=lambda p: p.get_effectiveness_rating(),
            default=None
        )
    
    def get_patterns_for_context(self, context: str, min_effectiveness: float = 0.3) -> list[ThinkingPattern]:
        """Выбирает подходящие паттерны для данного контекста."""
        relevant = []
        
        for pattern in self.patterns.values():
            score = pattern.weight * pattern.get_effectiveness_rating()
            
            # Паттерны аналитики полезны для анализа
            if "анализ" in context.lower() and pattern.pattern_type == "analysis":
                score *= 1.5
            
            # Паттерны синтеза полезны для креативных задач
            if any(w in context.lower() for w in ["создать", "новая", "комбинация"]):
                if pattern.pattern_type == "synthesis":
                    score *= 1.5
            
            # Аналогические рассуждения полезны когда есть похожий опыт
            if "похож" in context.lower() or "аналогия" in context.lower():
                if pattern.pattern_type == "analogical":
                    score *= 1.5
            
            if score >= min_effectiveness:
                relevant.append(pattern)
        
        return sorted(relevant, key=lambda p: p.weight * p.get_effectiveness_rating(), reverse=True)
    
    def get_status(self) -> dict:
        """Статус библиотеки паттернов."""
        patterns_by_type = defaultdict(list)
        for p in self.patterns.values():
            patterns_by_type[p.pattern_type].append(p)
        
        active_patterns = [p for p in self.patterns.values() if p.usage_count > 0]
        highly_effective = [p for p in active_patterns if p.get_effectiveness_rating() > 0.7]
        
        return {
            "total_patterns": len(self.patterns),
            "used_patterns": len(active_patterns),
            "highly_effective": len(highly_effective),
            "created_by_agent": len(self.created_patterns),
            "patterns_by_type": {
                t: [p.name for p in pls]
                for t, pls in patterns_by_type.items()
            },
            "dominant_pattern": self.get_dominant_pattern().name if self.get_dominant_pattern() else None,
            "evolution_log_count": len(self.evolution_log)
        }
    
    def to_dict(self) -> dict:
        """Серилизует всю библиотеку."""
        return {
            "patterns": {name: p.to_dict() for name, p in self.patterns.items()},
            "created_patterns": self.created_patterns,
            "evolution_log_count": len(self.evolution_log),
            "status": self.get_status()
        }