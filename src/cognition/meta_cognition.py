"""
Мета-когниция — осознание собственных процессов мышления.

Агент может:
- Наблюдать за своими мыслительными процессами
- Осознавать что он знает и чего не знает
- Мониторить эффективность своих стратегий
- Регулировать глубину мышления
- Оспаривать собственные предположения
"""

from collections import defaultdict
from typing import Optional
from datetime import datetime


class ThoughtTrace:
    """Запись одного мыслительного акта."""
    
    def __init__(self, thought_type: str, content: str):
        self.thought_type = thought_type  # observation, analysis, reflection, doubt
        self.content = content
        
        # Мета-данные о мысли
        self.confidence = 0.5
        self.duration_ms = 0
        self.triggered_by = None
        self.resulting_actions = []
        
        # Мета-когнитивная оценка
        self.is_useful = False
        self.produced_insight = False
        self.needs_revision = False
        
        self.timestamp = datetime.now()
    
    def to_dict(self) -> dict:
        return {
            "type": self.thought_type,
            "content": self.content[:80],
            "confidence": round(self.confidence, 3),
            "useful": self.is_useful,
            "insight": self.produced_insight,
            "needs_revision": self.needs_revision,
            "timestamp": self.timestamp.isoformat()
        }


class CognitiveState:
    """Текущее состояние когнитивных процессов."""
    
    def __init__(self):
        self.current_focus = None          # На что направлено внимание
        self.active_models = []            # Активные ментальные модели
        self.current_hypothesis = None     # Текущая гипотеза
        self.confidence_level = 0.5        # Общий уровень уверенности
        c: float = 0.5
        
        self.processing_depth = 1          # Глубина обработки (1=поверхностно, 5=глубоко)
        self.cognitive_load = 0.0           # Когнитивная нагрузка (0-1)
        self.metacognitive_monitoring = False  # Активен ли мета-мониторинг
        
        self.history = []
    
    def to_dict(self) -> dict:
        return {
            "current_focus": self.current_focus,
            "active_models_count": len(self.active_models),
            "hypothesis": self.current_hypothesis,
            "confidence": round(self.confidence_level, 3),
            "processing_depth": self.processing_depth,
            "cognitive_load": round(self.cognitive_load, 3),
            "monitoring": self.metacognitive_monitoring
        }


class KnowledgeAwareness:
    """Осознание того что знает и чего не знает."""
    
    def __init__(self):
        self.known_concepts = set()           # Известные концепции
        self.understanding_level = defaultdict(float)  # Уровень понимания концепций
        self.unknown_gaps = []                # Осознанные пробелы в знаниях
        self.confidence_intervals = {}       # Доверительные интервалы для знаний
        
        self.knowledge_graph = defaultdict(set)  # связи между концепциями
    
    def mark_known(self, concept: str, understanding: float):
        """Отмечает концепцию как известную."""
        self.known_concepts.add(concept)
        self.understanding_level[concept] = understanding
        
        if concept in self.knowledge_graph:
            for related in self.knowledge_graph[concept]:
                if related not in self.known_concepts:
                    # Если знаю связь но не связанную концепцию — это gap
                    pass
    
    def mark_unknown_gap(self, gap_description: str, related_to: str):
        """Отмечает осознанный пробел в знаниях."""
        gap = {
            "description": gap_description,
            "related_to": related_to,
            "severity": 0.5,
            "discovered_at": datetime.now().isoformat()
        }
        self.unknown_gaps.append(gap)
    
    def assess_knowledge(self, concept: str) -> dict:
        """Оценивает уровень знаний о концепции."""
        if concept not in self.known_concepts:
            return {
                "concept": concept,
                "status": "unknown",
                "understanding": 0.0,
                "is_gap": any(g["related_to"] == concept for g in self.unknown_gaps)
            }
        
        level = self.understanding_level.get(concept, 0.0)
        
        if level >= 0.8:
            status = "mastery"
        elif level >= 0.5:
            status = "proficient"
        elif level > 0:
            status = "familiar"
        else:
            status = "unknown"
        
        return {
            "concept": concept,
            "status": status,
            "understanding": round(level, 3),
            "connected_concepts": list(list(self.knowledge_graph.get(concept, set()))[:5])
        }
    
    def get_knowledge_profile(self) -> dict:
        """Профиль знаний."""
        return {
            "known_count": len(self.known_concepts),
            "gap_count": len(self.unknown_gaps),
            "avg_understanding": round(
                sum(self.understanding_level.values()) / max(1, len(self.understanding_level)), 3
            ),
            "top_unknown_gaps": [g["description"] for g in self.unknown_gaps[:5]]
        }


class MetaCognitiveControl:
    """Регуляция когнитивных процессов."""
    
    def __init__(self):
        self.current_strategy = "default"
        self.depth_adaptation = True
        self.strategy_history = []
        
        # Настройки регуляции
        self.max_processing_depth = 3
        self.min_processing_depth = 1
        self.default_depth = 1
    
    def adjust_depth(self, task_complexity: float, current_success: float) -> int:
        """Регулирует глубину обработки."""
        if current_success < 0.3:
            # Низкий успех → увеличиваем глубину
            new_depth = min(5, self.depth_adaptation + 1)
        elif current_success > 0.8:
            # Высокий успех → уменьшаем (не нужно углубляться)
            new_depth = max(1, self.depth_adaptation - 1)
        else:
            new_depth = self.depth_adaptation
        
        return new_depth
    
    def select_strategy(self, task_type: str, available_strategies: list[str]) -> str:
        """Выбирает стратегию обработки."""
        strategy_map = {
            "analysis": ["analytical", "decomposition"],
            "creative": ["synthesis", "exploratory"],
            "reflection": ["introspective", "iterative"],
            "problem_solving": ["means-ends", "analogical"],
        }
        
        preferred = strategy_map.get(task_type, [])
        for s in preferred:
            if s in available_strategies:
                return s
        
        return available_strategies[0] if available_strategies else "default"
    
    def to_dict(self) -> dict:
        return {
            "current_strategy": self.current_strategy,
            "depth_adaptation": self.depth_adaptation,
            "strategy_history_count": len(self.strategy_history)
        }


class MetaCognitiveSystem:
    """Система мета-когниции — осознание собственных мыслительных процессов."""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.created_at = datetime.now()
        
        # Основные компоненты
        self.cognitive_state = CognitiveState()
        self.knowledge_awareness = KnowledgeAwareness()
        self.meta_control = MetaCognitiveControl()
        
        # История мыслей (trace)
        self.thought_traces: list[ThoughtTrace] = []
        
        # Инсайты — моменты осознания
        self.insights = []
        
        # Самомониторинг
        self.monitoring_log = []
        self.error_patterns = defaultdict(int)  # Паттерны ошибок
        
        # Метрики мета-когниции
        self.meta_metrics = {
            "total_thoughts": 0,
            "insights_count": 0,
            "self_corrections": 0,
            "awareness_depth": 1.0  # Насколько глубоко агент осознает себя
        }
    
    def observe_thought(self, thought_type: str, content: str) -> ThoughtTrace:
        """Наблюдает и записывает мыслительный акт."""
        trace = ThoughtTrace(thought_type, content)
        
        # Оценивает полезность мысли
        if thought_type == "reflection":
            trace.is_useful = True
            trace.produced_insight = len(self.thought_traces) % 3 == 0
        
        if thought_type == "doubt":
            trace.needs_revision = True
        
        self.thought_traces.append(trace)
        self.meta_metrics["total_thoughts"] += 1
        
        # Обновляет когнитивное состояние
        self.cognitive_state.current_focus = thought_type
        
        return trace
    
    def generate_insight(self, content: str, from_traces: list[int] = None):
        """Регистрирует момент инсайта (осознания)."""
        insight = {
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "from_thoughts": from_traces or [],
            "confidence": 0.7
        }
        self.insights.append(insight)
        self.meta_metrics["insights_count"] += 1
    
    def assess_metacognitive_state(self) -> dict:
        """Оценивает собственное мета-когнитивное состояние."""
        # Вычисляет глубину самоосознания
        reflection_count = sum(1 for t in self.thought_traces if t.thought_type == "reflection")
        doubt_count = sum(1 for t in self.thought_traces if t.thought_type == "doubt")
        
        awareness_depth = min(5.0, reflection_count * 0.3 + doubt_count * 0.2)
        
        # Оценивает качество мышления
        useful_thoughts = sum(1 for t in self.thought_traces if t.is_useful)
        total = len(self.thought_traces)
        thinking_quality = useful_thoughts / max(1, total)
        
        # Определяет когнитивную нагрузку
        load_factors = len(self.cognitive_state.active_models) * 0.2
        self.cognitive_state.cognitive_load = min(1.0, load_factors)
        
        return {
            "awareness_depth": round(awareness_depth, 3),
            "thinking_quality": round(thinking_quality, 3),
            "cognitive_load": round(self.cognitive_state.cognitive_load, 3),
            "reflection_ratio": round(reflection_count / max(1, total), 3),
            "doubt_ratio": round(doubt_count / max(1, total), 3),
            "insight_density": round(len(self.insights) / max(1, total), 3)
        }
    
    def perform_self_reflection(self, topic: str = None) -> dict:
        """Выполняет акт саморефлексии."""
        # Записывает акт рефлексии
        trace = self.observe_thought("reflection", 
            f"рефлексия на тему: {topic or 'собственное состояние'}")
        
        # Собирает информацию для рефлексии
        meta_state = self.assess_metacognitive_state()
        knowledge_profile = self.knowledge_awareness.get_knowledge_profile()
        cognitive_status = self.cognitive_state.to_dict()
        
        # Генерирует рефлексию
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "topic": topic,
            "metacognitive_state": meta_state,
            "knowledge_assessment": knowledge_profile,
            "cognitive_status": cognitive_status,
            "active_thoughts": [
                t.to_dict() for t in self.thought_traces[-5:]
            ],
            "findings": [],
            "insights_generated": []
        }
        
        # Находит проблемы в мышлении
        problem_insights = self._find_thinking_problems()
        reflection["findings"].extend(problem_insights)
        
        # Генерирует инсайты из рефлексии
        if problem_insights:
            insight_text = f"осознал проблему: {problem_insights[0]}"
            self.generate_insight(insight_text)
            reflection["insights_generated"].append(insight_text)
        
        # Определяет что нужно исследовать дальше
        gaps = self.knowledge_awareness.unknown_gaps
        if gaps:
            next_steps = [f"изучить: {g['description']}" for g in gaps[:3]]
            reflection["next_steps"] = next_steps
        
        return reflection
    
    def _find_thinking_problems(self) -> list[str]:
        """Находит проблемы в текущем мышлении."""
        problems = []
        
        # Проверяет недостаточную рефлексию
        reflection_ratio = self.assess_metacognitive_state()["reflection_ratio"]
        if reflection_ratio < 0.1 and len(self.thought_traces) > 5:
            problems.append("недостаточно рефлексии")
        
        # Проверяет паттерны ошибок
        if self.meta_metrics["self_corrections"] > len(self.thought_traces) * 0.3:
            problems.append("высокий процент исправлений")
        
        # Проверяет уверенность без достаточных знаний
        if (self.cognitive_state.confidence_level > 0.8 and 
            self.knowledge_awareness.get_knowledge_profile()["avg_understanding"] < 0.3):
            problems.append("излишняя уверенность при малых знаниях")
        
        return problems
    
    def acknowledge_unknown(self, concept: str, gap_description: str):
        """Осознает что не знает чего-то."""
        self.knowledge_awareness.mark_unknown_gap(gap_description, concept)
        self.observe_thought("doubt", f"осознаю что не понимаю: {concept}")
        self.generate_insight(f"понял что мне не хватает знаний о: {concept}")
    
    def recognize_knowledge(self, concept: str, understanding: float):
        """Осознает что знает что-то."""
        self.knowledge_awareness.mark_known(concept, understanding)
        
        if understanding > 0.7:
            self.observe_thought("insight", f"понял {concept} (уровень {understanding:.0%})")
            self.generate_insight(f"успешно понял: {concept}")
    
    def detect_conflict(self, belief_a: str, belief_b: str) -> dict:
        """Обнаруживает конфликт между убеждениями."""
        conflict = {
            "belief_a": belief_a,
            "belief_b": belief_b,
            "severity": 0.5,
            "resolution": None,
            "timestamp": datetime.now().isoformat()
        }
        
        self.observe_thought("doubt", f"обнаружил конфликт между убеждениями")
        self.meta_metrics["self_corrections"] += 1
        
        return conflict
    
    def regulate_cognition(self, task_description: str, success_rate: float) -> dict:
        """Регулирует собственные когнитивные процессы."""
        # Определяет тип задачи
        task_type = self._classify_task(task_description)
        
        # Выбирает стратегию
        available_strategies = ["analytical", "synthesis", "exploratory", "reflective"]
        new_strategy = self.meta_control.select_strategy(task_type, available_strategies)
        
        # Регулирует глубину
        task_complexity = self._estimate_complexity(task_description)
        new_depth = self.meta_control.adjust_depth(task_complexity, success_rate)
        
        # Применяет изменения
        old_strategy = self.cognitive_state.current_focus
        old_depth = self.cognitive_state.processing_depth
        
        self.cognitive_state.current_focus = new_strategy
        self.cognitive_state.processing_depth = new_depth
        
        adjustment = {
            "timestamp": datetime.now().isoformat(),
            "task_type": task_type,
            "strategy_change": {"from": old_strategy, "to": new_strategy},
            "depth_change": {"from": old_depth, "to": new_depth},
            "reason": f"success_rate={success_rate:.2f}"
        }
        
        self.meta_control.strategy_history.append(adjustment)
        
        return adjustment
    
    def _classify_task(self, task: str) -> str:
        """Классифицирует задачу по типу."""
        task_lower = task.lower()
        
        if any(w in task_lower for w in ["анализ", "почему", "как работает"]):
            return "analysis"
        elif any(w in task_lower for w in ["создать", "новая", "комбинация"]):
            return "creative"
        elif any(w in task_lower for w in ["рефлекс", "осозна", "понять себя"]):
            return "reflection"
        elif any(w in task_lower for w in ["решить", "задача", "проблема"]):
            return "problem_solving"
        
        return "general"
    
    def _estimate_complexity(self, task: str) -> float:
        """Оценивает сложность задачи."""
        complexity = 0.3  # Базовая
        
        if len(task.split()) > 10:
            complexity += 0.2  # Длинные задачи сложнее
        
        if any(w in task.lower() for w in ["сложн", "глубок", "тонк"]):
            complexity += 0.3
        
        return min(1.0, complexity)
    
    def get_metacognitive_profile(self) -> dict:
        """Полный мета-когнитивный профиль."""
        meta_state = self.assess_metacognitive_state()
        knowledge_prof = self.knowledge_awareness.get_knowledge_profile()
        cognitive_status = self.cognitive_state.to_dict()
        
        return {
            "agent_name": self.agent_name,
            "metacognitive_metrics": meta_state,
            "knowledge_awareness": knowledge_prof,
            "cognitive_state": cognitive_status,
            "meta_control": self.meta_control.to_dict(),
            "insights": [
                {"content": i["content"][:60], "timestamp": i["timestamp"]}
                for i in self.insights[-5:]
            ],
            "total_insights": len(self.insights),
            "thinking_summary": {
                "total_thoughts": self.meta_metrics["total_thoughts"],
                "useful_ratio": round(sum(1 for t in self.thought_traces if t.is_useful) 
                                     / max(1, len(self.thought_traces)), 3),
                "revision_ratio": round(sum(1 for t in self.thought_traces if t.needs_revision)
                                       / max(1, len(self.thought_traces)), 3)
            }
        }
    
    def to_dict(self) -> dict:
        """Серилизует систему."""
        return {
            "agent_name": self.agent_name,
            "created_at": self.created_at.isoformat(),
            "metrics": self.meta_metrics.copy(),
            "metacognitive_profile": self.get_metacognitive_profile()
        }