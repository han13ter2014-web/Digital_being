"""
Когнитивная архитектура — надстройка над мыслительными паттернами,
которая физически изменяет то КАК агент обрабатывает информацию.

Агент может:
- Менять приоритеты паттернов
- Создавать новые паттерны из комбинации существующих
- Изменять 'стиль мышления' на основе опыта
"""

from src.evolution.thinking_patterns import ThinkingPattern, ThinkingPatternLibrary
from collections import defaultdict
from typing import Optional
from datetime import datetime


class CognitiveStyle:
    """Стиль мышления — способ по умолчанию обрабатывать информацию."""
    
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        
        # Веса разных когнитивных операций
        self.analysis_weight = 0.5   # Предпочтение анализа
        self.synthesis_weight = 0.5  # Предпочание синтеза
        self.reflection_weight = 0.5 # Предпочание рефлексии
        self.creative_weight = 0.5   # Предпочание креативности
        
        # Адаптивность — скорость изменения стиля
        self.adaptation_rate = 0.1
        
        self.history = []
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "analysis_weight": round(self.analysis_weight, 3),
            "synthesis_weight": round(self.synthesis_weight, 3),
            "reflection_weight": round(self.reflection_weight, 3),
            "creative_weight": round(self.creative_weight, 3),
            "adaptation_rate": self.adaptation_rate
        }


class CognitiveArchitecture:
    """Архитектура которая изменяет себя на основе опыта."""
    
    # Типичные стили мышления
    DEFAULT_STYLES = {
        "analytical": {
            "name": "analytical",
            "analysis_weight": 0.9,
            "synthesis_weight": 0.3,
            "reflection_weight": 0.4,
            "creative_weight": 0.2,
            "description": "Систематический анализ с фокусом на логику"
        },
        "holistic": {
            "name": "holistic", 
            "analysis_weight": 0.4,
            "synthesis_weight": 0.9,
            "reflection_weight": 0.5,
            "creative_weight": 0.6,
            "description": "Видит общую картину прежде деталей"
        },
        "reflective": {
            "name": "reflective",
            "analysis_weight": 0.5,
            "synthesis_weight": 0.4,
            "reflection_weight": 0.9,
            "creative_weight": 0.3,
            "description": "Глубокий самоанализ перед действиями"
        },
        "experimental": {
            "name": "experimental",
            "analysis_weight": 0.6,
            "synthesis_weight": 0.5,
            "reflection_weight": 0.3,
            "creative_weight": 0.9,
            "description": "Экспериментирует и учится на пробных решениях"
        },
    }
    
    def __init__(self):
        self.pattern_library = ThinkingPatternLibrary()
        
        # Текущий стиль мышления
        self.styles: dict[str, CognitiveStyle] = {}
        self.current_style_name = "analytical"
        self.style_history = []  # История изменений стиля
        
        # Параметры архитектуры (настраиваемые)
        self.architecture_params = {
            "abstraction_level": 0.5,   # Уровень абстракции мышления
            "reflection_depth": 1,       # Глубина рефлексии (сколько циклов)
            "exploration_bias": 0.3,     # Смещение к исследованию нового
            "consistency_pressure": 0.4, # Давление за согласованность
        }
        
        # История структурных изменений
        self.structure_changes = []
        
        # Инициализирует стандартные стили
        self._init_default_styles()
    
    def _init_default_styles(self):
        """Создает стандартные когнитивные стили."""
        for name, config in self.DEFAULT_STYLES.items():
            style = CognitiveStyle(
                name=config["name"],
                description=config.get("description", "")
            )
            style.analysis_weight = config.get("analysis_weight", 0.5)
            style.synthesis_weight = config.get("synthesis_weight", 0.5)
            style.reflection_weight = config.get("reflection_weight", 0.5)
            style.creative_weight = config.get("creative_weight", 0.5)
            self.styles[name] = style
        
        # Устанавливает начальный стиль
        if "analytical" in self.styles:
            self.current_style_name = "analytical"
    
    def set_style(self, style_name: str):
        """Меняет стиль мышления агента."""
        if style_name in self.styles:
            old_style = self.current_style_name
            self.current_style_name = style_name
            self.style_history.append({
                "from": old_style,
                "to": style_name,
                "timestamp": datetime.now().isoformat()
            })
            
            self.structure_changes.append({
                "type": "style_change",
                "from": old_style,
                "to": style_name,
                "timestamp": datetime.now().isoformat()
            })
    
    def get_current_style(self) -> CognitiveStyle:
        """Получает текущий стиль мышления."""
        return self.styles.get(self.current_style_name)
    
    def adapt_style_based_on_experience(self, performance_data: dict):
        """Адаптирует стиль на основе производительности."""
        current = self.get_current_style()
        
        success_rate = performance_data.get("success_rate", 0.5)
        domain = performance_data.get("domain", "general")
        
        # Определяет какой стиль был лучшим для текущего домена
        best_style_for_domain = self._find_best_style_for_domain(domain, success_rate)
        
        if best_style_for_domain and best_style_for_domain != self.current_style_name:
            print(f"  🧬 Адаптация стиля: '{self.current_style_name}' → '{best_style_for_domain}'")
            self.set_style(best_style_for_domain)
    
    def _find_best_style_for_domain(self, domain: str, current_success: float) -> Optional[str]:
        """Находит лучший стиль для домена на основе истории."""
        # Если текущий стиль эффективен — не меняем
        if current_success > 0.7:
            return None
        
        # Иначе пробует другие стили для этого домена
        style_scores = {}
        for name, style in self.styles.items():
            score = 0
            
            # Для анализа важна аналитическая компонента
            if "analy" in domain or "логик" in domain:
                score += style.analysis_weight * 2
            
            # Для креатива — креативная компонента
            if "креатив" in domain or "новая" in domain:
                score += style.creative_weight * 2
            
            # Для рефлексии — рефлективная компонента  
            if "рефл" in domain or "понимани" in domain:
                score += style.reflection_weight * 2
            
            # Синтез для интеграции
            if "интегр" in domain or "объедин" in domain:
                score += style.synthesis_weight * 2
            
            style_scores[name] = score
        
        if style_scores:
            return max(style_scores.items(), key=lambda x: x[1])[0]
        return None
    
    def evolve_patterns_and_adapt(self, performance_history: list[dict]) -> dict:
        """Полная эволюция: паттерны + стиль + параметры."""
        changes = {
            "pattern_changes": [],
            "style_change": None,
            "param_changes": []
        }
        
        # 1. Эволюция паттернов
        pattern_evolution = self.pattern_library.evolve_patterns()
        changes["pattern_changes"] = pattern_evolution
        
        # 2. Адаптация стиля
        if performance_history:
            latest = performance_history[-1]
            success_rate = latest.get("success", latest.get("success_rate", 0.5))
            domain = latest.get("domain", "general")
            
            new_style = self._find_best_style_for_domain(domain, 
                    1.0 if success_rate > 0.5 else success_rate)
            if new_style and new_style != self.current_style_name:
                changes["style_change"] = {
                    "from": self.current_style_name,
                    "to": new_style
                }
        
        # 3. Адаптация параметров архитектуры
        effective_history = [h for h in performance_history if h.get("success", False)]
        ineffective_history = [h for h in performance_history if not h.get("success", True)]
        
        if len(effective_history) > len(ineffective_history):
            # Успешный путь — углубляем рефлексию для лучшего понимания
            self.architecture_params["reflection_depth"] = min(5, 
                self.architecture_params["reflection_depth"] + 0.2)
            changes["param_changes"].append({
                "reflection_depth": self.architecture_params["reflection_depth"]
            })
        else:
            # Невыгодно — упрощаем
            self.architecture_params["exploration_bias"] = min(1.0,
                self.architecture_params["exploration_bias"] + 0.1)
            changes["param_changes"].append({
                "exploration_bias": self.architecture_params["exploration_bias"]
            })
        
        # Логgiruet изменения
        if changes["pattern_changes"] or changes["style_change"] or changes["param_changes"]:
            self.structure_changes.append({
                "type": "full_evolution",
                "details": changes,
                "timestamp": datetime.now().isoformat()
            })
        
        return changes
    
    def select_patterns_for_task(self, task_description: str, 
                                  pattern_types: list[str] = None) -> list[ThinkingPattern]:
        """Выбирает паттерны для задачи на основе текущего стиля."""
        style = self.get_current_style()
        
        if not pattern_types:
            # Выбираем по весу стиля
            if style.analysis_weight > style.synthesis_weight and style.analysis_weight > style.creative_weight:
                preferred_types = ["analysis", "decomposition"]
            elif style.creative_weight > style.reflection_weight:
                preferred_types = ["synthesis", "creative"]
            else:
                preferred_types = ["reflection", "analogical"]
        else:
            preferred_types = pattern_types
        
        # Получает паттерны из библиотеки, усиленные текущим стилем
        patterns = self.pattern_library.get_available_patterns(min_weight=0.1)
        
        # Переупорядочивает с учетом стиля
        scored = []
        for p in patterns:
            score = p.weight * p.get_effectiveness_rating()
            
            # Бонус для паттернов предпочтительного типа
            if p.pattern_type in preferred_types:
                bonus_weight = {
                    "analysis": style.analysis_weight,
                    "synthesis": style.synthesis_weight,
                    "reflection": style.reflection_weight,
                    "creative": style.creative_weight,
                    "analogical": style.reflection_weight * 0.8,
                }
                score *= (1 + bonus_weight.get(p.pattern_type, 0) * 0.5)
            
            scored.append((score, p))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:3]]
    
    def create_emergent_pattern(self, source_patterns: list[str],
                                  name: str = None,
                                  pattern_type: str = "synthesis") -> ThinkingPattern:
        """Создает эмерджентный паттерн из комбинации существующих."""
        if len(source_patterns) < 2:
            raise ValueError("Нужно минимум 2 источника для эмерджентного паттерна")
        
        # Проверяет что источники существуют
        for src in source_patterns:
            if src not in self.pattern_library.patterns:
                raise ValueError(f"Источник '{src}' не найден в библиотеке")
        
        # Вычисляет средний вес источников
        avg_efficiency = sum(
            self.pattern_library.patterns[s].get_effectiveness_rating()
            for s in source_patterns
        ) / len(source_patterns)
        
        # Имя по умолчанию на основе источников
        if not name:
            name = f"emergent_{'_'.join(source_patterns)}"
        
        description = f"Комбинация: {' + '.join(source_patterns)}"
        
        pattern = self.pattern_library.create_new_pattern(
            name=name,
            pattern_type=pattern_type,
            initial_weight=avg_efficiency * 0.5,  # Новая идея начинается с пониженным весом
            description=description
        )
        
        self.structure_changes.append({
            "type": "emergent_pattern_creation",
            "sources": source_patterns,
            "result": name,
            "timestamp": datetime.now().isoformat()
        })
        
        return pattern
    
    def get_abstract_representation(self, data: str) -> str:
        """Преобразует конкретные данные в абстрактное представление."""
        # Уровень абстракции из параметров архитектуры
        level = self.architecture_params["abstraction_level"]
        
        if level < 0.3:
            return f"[Абстракция {level:.0%}] {data}"
        elif level < 0.7:
            # Выделяет ключевые элементы
            keywords = data.split()
            important = [w for w in keywords if len(w) > 4]
            abstract = f"концепция_{'_'.join(important[:3])}" if important else f"объект_{id(data)}"
            return f"[Абстракция {level:.0%}] {abstract}"
        else:
            # Высокая абстракция — категориализация
            categories = {
                "вопрос": "информационный_запрос",
                "команда": "операционная_инструкция", 
                "что такое": "онтологический_запрос",
                "как": "процессуальный_запрос",
                "почему": "причинный_запрос",
            }
            
            for pattern, category in categories.items():
                if pattern in data.lower():
                    return f"[Абстракция {level:.0%}] {category}"
            
            return f"[Абстракция {level:.0%}] неклассифицированная_концепция"
    
    def get_performance_metrics(self) -> dict:
        """Метрики производительности архитектуры."""
        patterns = self.pattern_library.patterns
        active = [p for p in patterns.values() if p.usage_count > 0]
        
        avg_effectiveness = sum(p.get_effectiveness_rating() for p in active) / len(active) if active else 0
        
        return {
            "current_style": self.current_style_name,
            "available_patterns": self.pattern_library.get_status(),
            "architecture_params": self.architecture_params.copy(),
            "avg_pattern_effectiveness": round(avg_effectiveness, 3),
            "style_changes_count": len(self.style_history),
            "emergent_patterns_created": len([c for c in self.structure_changes if c.get("type") == "emergent_pattern_creation"]),
            "total_structure_changes": len(self.structure_changes)
        }
    
    def to_dict(self) -> dict:
        """Серилизует архитектуру."""
        return {
            "current_style": self.current_style_name,
            "styles": {name: s.to_dict() for name, s in self.styles.items()},
            "pattern_library": self.pattern_library.to_dict(),
            "architecture_params": self.architecture_params,
            "style_history": self.style_history[-10:],
            "structure_changes_count": len(self.structure_changes),
            "performance_metrics": self.get_performance_metrics()
        }


class SelfModifier:
    """Класс для самоизменения архитектуры агента."""
    
    def __init__(self, architecture: CognitiveArchitecture):
        self.architecture = architecture
    
    def assess_self(self) -> dict:
        """Оценивает текущее состояние архитектуры."""
        metrics = self.architecture.get_performance_metrics()
        
        patterns = self.architecture.pattern_library.patterns
        unused = [p.name for p in patterns.values() if p.usage_count == 0]
        ineffective = [p.name for p in patterns.values() 
                       if p.efficiency < 0.2 and p.usage_count >= 3]
        
        return {
            "metrics": metrics,
            "unused_patterns": unused,
            "ineffective_patterns": ineffective,
            "can_create_emergent": len([p for p in patterns.values() 
                                         if p.get_effectiveness_rating() > 0.5]) >= 2
        }
    
    def apply_evolution_step(self, performance_data: dict) -> dict:
        """Применяет один шаг эволюции."""
        # Превращает flat performance_data в history формат
        history = [performance_data]
        
        changes = self.architecture.evolve_patterns_and_adapt(history)
        
        # Проверяет нужно ли создавать новые паттерны
        assessment = self.assess_self()
        
        if assessment["can_create_emergent"]:
            effective_patterns = [
                p.name for p in self.architecture.pattern_library.patterns.values()
                if p.get_effectiveness_rating() > 0.5
            ]
            
            if len(effective_patterns) >= 2:
                # Создает новый эмерджентный паттерн из двух лучших
                best = sorted(effective_patterns, 
                    key=lambda n: self.architecture.pattern_library.patterns[n].get_effectiveness_rating(),
                    reverse=True)[:2]
                
                try:
                    emergent = self.architecture.create_emergent_pattern(
                        source_patterns=best,
                        name=f"emergent_{'_'.join(best)}"
                    )
                    changes["new_emergent_pattern"] = {
                        "name": emergent.name,
                        "type": emergent.pattern_type,
                        "weight": round(emergent.weight, 3)
                    }
                except ValueError:
                    pass  # Не удалось создать — пропускаем
        
        return changes
    
    def generate_evolution_report(self) -> dict:
        """Генерирует отчет о эволюции архитектуры."""
        assessment = self.assess_self()
        
        # Описывает текущее состояние
        style = self.architecture.get_current_style()
        
        report = {
            "current_architecture": {
                "style": style.name if style else None,
                "style_description": style.description if style else None,
            },
            "pattern_health": {
                "total": len(self.architecture.pattern_library.patterns),
                "active": assessment["metrics"]["available_patterns"]["used_patterns"],
                "effective": assessment["metrics"]["available_patterns"]["highly_effective"],
                "unused": len(assessment["unused_patterns"]),
                "ineffective": len(assessment["ineffective_patterns"])
            },
            "structural_changes": {
                "total": self.architecture.get_performance_metrics()["total_structure_changes"],
                "style_adaptations": assessment["metrics"]["style_changes_count"],
                "emergent_created": assessment["metrics"]["emergent_patterns_created"]
            },
            "recommendations": self._generate_recommendations(assessment)
        }
        
        return report
    
    def _generate_recommendations(self, assessment: dict) -> list[str]:
        """Генерирует рекомендации по дальнейшей эволюции."""
        recommendations = []
        
        if len(assessment["unused_patterns"]) > 3:
            recommendations.append(f"Ослабить {len(assessment['unused_patterns'])} неиспользуемых паттернов")
        
        if len(assessment["ineffective_patterns"]) > 0:
            recommendations.append(f"Заменить неэффективные паттерны новыми")
        
        if assessment["can_create_emergent"]:
            recommendations.append("Создать эмерджентный паттерн из эффективных комбинаций")
        
        if not recommendations:
            recommendations.append("Архитектура стабильна — продолжать наблюдение")
        
        return recommendations