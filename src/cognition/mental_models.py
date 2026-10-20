"""
Система ментальных моделей для автономного формирования понимания мира.

Агент формирует собственные ментальные модели понятий через:
- Встречу с концепциями в разных контекстах
- Анализ связей между концепциями
- Формирование гипотез о значении
- Обновление уверенности на основе опыта

Оптимизации (Шаг 2, 4):
- Мягкий лимит MAX_CONCEPTS (LR_CONFIG) с приоритетным забыванием.
- Кеш find_related_concepts с TTL по cycle_count.
"""

from collections import defaultdict, Counter
from typing import Dict, Tuple
from datetime import datetime


def _lr_config():
    """Ленивый импорт LR_CONFIG чтобы избежать циклов."""
    try:
        from config.simulation_config import LR_CONFIG
        return LR_CONFIG
    except Exception:
        return None


class ConceptNode:
    """Узел ментальной модели - представляет одну концепцию."""
    
    def __init__(self, name: str):
        self.name = name
        self.definition_hypothesis = ""  # Собственная гипотеза о значении
        self.experiences = []  # Опыт взаимодействия с концепцией
        self.connections = {}  # Связи с другими концепциями {название: вес}
        self.confidence = 0.1  # Уверенность в определении (0.0 - 1.0)
        self.usage_examples = []  # Примеры использования
        self.contexts_encountered = set()  # Контексты где встречалась
        self.created_at = datetime.now()
        self.last_updated = datetime.now()
    
    def add_experience(self, context: str, outcome: str, emotional_valence: float = 0.0):
        """Добавляет опыт взаимодействия с концепцией."""
        experience = {
            "context": context,
            "outcome": outcome,
            "valence": emotional_valence,  # -1.0 (негативный) до +1.0 (позитивный)
            "timestamp": datetime.now().isoformat()
        }
        self.experiences.append(experience)
        self.contexts_encountered.add(context)
        self.last_updated = datetime.now()
        
        # Обновляет уверенность на основе количества консистентного опыта
        consistent_outcomes = len([e for e in self.experiences if abs(e["valence"]) > 0.3])
        if len(self.experiences) > 0:
            self.confidence = min(1.0, consistent_outcomes / len(self.experiences) * 0.7 + 0.1)
    
    def connect_to(self, other_concept: str, weight: float = 0.5):
        """Создает связь с другой концепцией."""
        self.connections[other_concept] = max(self.connections.get(other_concept, 0.0), weight)
    
    def strengthen_connection(self, other_concept: str, delta: float = 0.1):
        """Усиливает существующую связь."""
        if other_concept in self.connections:
            self.connections[other_concept] = min(1.0, self.connections[other_concept] + delta)
    
    def get_related_concepts(self, min_weight: float = 0.3) -> list[dict]:
        """Возвращает связанные концепции с весом выше порога."""
        return [
            {"concept": c, "weight": w}
            for c, w in self.connections.items()
            if w >= min_weight
        ]
    
    def to_dict(self) -> dict:
        """Серилизует узел в словарь."""
        return {
            "name": self.name,
            "definition_hypothesis": self.definition_hypothesis,
            "confidence": round(self.confidence, 3),
            "experience_count": len(self.experiences),
            "connection_count": len(self.connections),
            "contexts": list(self.contexts_encountered)[:10],  # Топ-10 контекстов
            "usage_examples": self.usage_examples[:5],
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat()
        }


class MentalModel:
    """Система ментальных моделей для формирования понимания концепций."""

    def __init__(self, name: str = "default"):
        self.name = name
        self.concepts: dict[str, ConceptNode] = {}  # {название: ConceptNode}
        self.association_memory = []  # История ассоциаций между концепциями
        self.metadata = {
            "created_at": datetime.now().isoformat(),
            "total_concepts_encountered": 0,
            "total_associations": 0,
            "forgotten_count": 0,
        }
        # === Кеш (Шаг 4) ===
        # Структура: {(concept, max_distance): (cycle_count, result)}
        self._related_cache: Dict[Tuple[str, int], Tuple[int, list]] = {}
        self._cycle_counter: int = 0

    def tick_cycle(self) -> None:
        """Увеличить счётчик циклов (для инвалидации кеша)."""
        self._cycle_counter += 1

    def _invalidate_cache_if_needed(self) -> None:
        """Инвалидирует кеш по TTL."""
        cfg = _lr_config()
        ttl = getattr(cfg, "RELATED_CONCEPTS_CACHE_TTL", 50) if cfg else 50
        if self._cycle_counter % max(1, ttl) == 0:
            self._related_cache.clear()

    def apply_concept_limit(self) -> int:
        """Мягкое ограничение количества концепций (Шаг 2).

        Возвращает количество забытых концепций.
        При превышении MAX_CONCEPTS забывает FORGET_PCT_PER_PASS процентов
        самых слабых (по confidence).
        """
        cfg = _lr_config()
        max_concepts = getattr(cfg, "MAX_CONCEPTS", 20000) if cfg else 20000
        forget_pct = getattr(cfg, "FORGET_PCT_PER_PASS", 5) if cfg else 5

        if len(self.concepts) <= max_concepts:
            return 0

        # Считаем сколько забыть (но не больше, чем превышение)
        over = len(self.concepts) - max_concepts
        target_forget = max(over, int(max_concepts * forget_pct / 100))
        target_forget = min(target_forget, over)

        if target_forget <= 0:
            return 0

        # Сортируем по confidence (по возрастанию — самые слабые первые)
        sorted_nodes = sorted(
            self.concepts.items(),
            key=lambda x: (x[1].confidence, x[1].last_updated),
        )
        forgotten = 0
        for name, _node in sorted_nodes:
            if forgotten >= target_forget:
                break
            del self.concepts[name]
            forgotten += 1

        self.metadata["forgotten_count"] = self.metadata.get("forgotten_count", 0) + forgotten
        # Инвалидируем кеш (связи могли измениться)
        self._related_cache.clear()
        return forgotten

    def encounter_concept(self, concept_name: str, context: str, outcome: str,
                          valence: float = 0.0) -> ConceptNode:
        """Агент встречает концепцию в определенном контексте."""

        if concept_name not in self.concepts:
            # Новая концепция - создаем узел
            node = ConceptNode(concept_name)
            node.add_experience(context, outcome, valence)
            self.concepts[concept_name] = node
            self.metadata["total_concepts_encountered"] += 1

            # Ищет связи с существующими концепциями
            self._find_initial_associations(node)

            return node
        else:
            # Уже известная концепция - обновляем опыт
            node = self.concepts[concept_name]
            node.add_experience(context, outcome, valence)

            # Обновляет связи с другими концепциями в этом контексте
            self._update_associations(node)

            # Формирует/обновляет гипотезу определения
            self._synthesize_definition(concept_name)

            return node
    
    def _find_initial_associations(self, new_node: ConceptNode):
        """Находит потенциальные связи для новой концепции."""
        if len(self.concepts) < 2:
            return
        
        for existing_name, existing_node in self.concepts.items():
            if existing_name == new_node.name:
                continue
            
            # Проверяет пересечение контекстов
            common_contexts = new_node.contexts_encountered & existing_node.contexts_encountered
            if common_contexts:
                weight = min(0.7, len(common_contexts) * 0.25)
                new_node.connect_to(existing_name, weight)
                existing_node.connect_to(new_node.name, weight)
                self._record_association(new_node.name, existing_name, weight)
            else:
                # Слабая базовая связь (возможно связана по теме)
                new_node.connect_to(existing_name, 0.1)
                existing_node.connect_to(new_node.name, 0.1)
    
    def _update_associations(self, updated_node: ConceptNode):
        """Обновляет ассоциации на основе нового опыта."""
        for other_name, other_node in self.concepts.items():
            if other_name == updated_node.name:
                continue
            
            # Если встретились вместе в каком-то контексте
            if any(exp["context"] in other_node.contexts_encountered 
                   for exp in updated_node.experiences):
                updated_node.strengthen_connection(other_name, 0.1)
                other_node.strengthen_connection(updated_node.name, 0.1)
                self._record_association(updated_node.name, other_name, 
                                       updated_node.connections.get(other_name, 0.3))
    
    def _synthesize_definition(self, concept_name: str):
        """Синтезирует гипотезу определения на основе опыта."""
        node = self.concepts[concept_name]
        
        if len(node.experiences) < 2:
            return  # Нужно минимум 2 опыта для синтеза
        
        # Собирает общие паттерны в контекстах
        context_patterns = defaultdict(list)
        for exp in node.experiences:
            # Извлекает ключевые слова из контекста
            keywords = [w for w in exp["context"].split() if len(w) > 3]
            for kw in keywords:
                context_patterns[kw].append(exp)
        
        # Находит наиболее часто встречающиеся паттерны
        most_common = max(context_patterns.items(), key=lambda x: len(x[1])) if context_patterns else (None, [])
        
        if most_common[0] and len(most_common[1]) >= 2:
            # Формирует гипотезу определения
            common_outcomes = [e["outcome"] for e in most_common[1]]
            outcome_counter = Counter(common_outcomes)
            most_frequent = outcome_counter.most_common(3)
            
            if len(most_frequent) > 0:
                hypothesis_parts = [p[0] for p in most_frequent if p[1] >= 1]
                if hypothesis_parts:
                    node.definition_hypothesis = f"По опыту ({len(node.experiences)} встреч): '{concept_name}' связано с {' -> '.join(hypothesis_parts[:3])}"
        
        # Обновляет уверенность
        consistent_valences = [e["valence"] for e in node.experiences if abs(e["valence"]) > 0.3]
        if len(consistent_valences) >= 2:
            variance = sum((v - sum(consistent_valences)/len(consistent_valences))**2 
                          for v in consistent_valences) / len(consistent_valences)
            node.confidence = min(1.0, 0.3 + (1 - variance) * 0.5 + len(node.experiences) * 0.05)
    
    def _record_association(self, concept1: str, concept2: str, weight: float):
        """Записывает ассоциацию в память."""
        self.association_memory.append({
            "concept1": concept1,
            "concept2": concept2,
            "weight": weight,
            "timestamp": datetime.now().isoformat()
        })
        self.metadata["total_associations"] += 1
    
    def find_concepts_by_context(self, context: str, min_confidence: float = 0.1) -> list[ConceptNode]:
        """Находит концепции связанные с данным контекстом."""
        relevant = []
        for name, node in self.concepts.items():
            # Проверяет пересечение контекстов
            common = len(node.contexts_encountered & set(context.split()))
            if common > 0 or any(ctx in context for ctx in node.contexts_encountered):
                if node.confidence >= min_confidence:
                    relevant.append(node)
        return sorted(relevant, key=lambda n: n.confidence, reverse=True)
    
    def find_related_concepts(self, concept_name: str, max_distance: int = 2) -> list[ConceptNode]:
        """Находит связанные концепции через граф (BFS) с кешированием (Шаг 4)."""
        if concept_name not in self.concepts:
            return []

        self._invalidate_cache_if_needed()
        cache_key = (concept_name, max_distance)
        cached = self._related_cache.get(cache_key)
        if cached is not None:
            cached_cycle, cached_result = cached
            if (self._cycle_counter - cached_cycle) < (
                getattr(_lr_config(), "RELATED_CONCEPTS_CACHE_TTL", 50) or 50
            ):
                return cached_result

        visited = set()
        queue = [(self.concepts[concept_name], 0)]
        result = []

        while queue:
            node, distance = queue.pop(0)

            if node.name in visited or distance > max_distance:
                continue

            visited.add(node.name)
            if node != self.concepts[concept_name]:
                result.append(node)

            for related_name in node.connections:
                if related_name not in visited and related_name in self.concepts:
                    queue.append((self.concepts[related_name], distance + 1))

        result = sorted(result, key=lambda n: n.confidence, reverse=True)
        # Сохраняем в кеш (но не больше MAX_SIMILARITY_CACHE записей)
        cfg = _lr_config()
        max_cache = getattr(cfg, "MAX_SIMILARITY_CACHE", 1000) if cfg else 1000
        if len(self._related_cache) >= max_cache:
            # Простой FIFO: удаляем первый ключ
            try:
                first_key = next(iter(self._related_cache))
                del self._related_cache[first_key]
            except StopIteration:
                pass
        self._related_cache[cache_key] = (self._cycle_counter, result)
        return result
    
    def get_concept_understanding(self, concept_name: str) -> dict:
        """Возвращает полное понимание концепции агентом."""
        if concept_name not in self.concepts:
            return {"unknown": True, "concept": concept_name}
        
        node = self.concepts[concept_name]
        return {
            "concept": concept_name,
            "hypothesis": node.definition_hypothesis,
            "confidence": node.confidence,
            "experience_count": len(node.experiences),
            "connections": node.get_related_concepts(),
            "experiences": node.experiences[-5:],  # Последние 5 опытов
            "can_define": node.confidence > 0.5 and len(node.definition_hypothesis) > 10
        }
    
    def can_answer_about(self, concept_name: str) -> bool:
        """Проверяет может ли агент дать осмысленный ответ о концепции."""
        if concept_name not in self.concepts:
            return False
        
        node = self.concepts[concept_name]
        return (node.confidence > 0.4 and 
                len(node.experiences) >= 2 and 
                len(node.definition_hypothesis) > 10)
    
    def to_dict(self) -> dict:
        """Серилизует всю систему ментальных моделей."""
        return {
            "name": self.name,
            "metadata": self.metadata,
            "concepts": {name: node.to_dict() for name, node in self.concepts.items()},
            "recent_associations": self.association_memory[-10:]
        }
    
    def print_model_tree(self, concept_name: str = None, indent: int = 0):
        """Визуально отображает ментальную модель."""
        if concept_name:
            if concept_name not in self.concepts:
                print(f"  Концепция '{concept_name}' не найдена в модели")
                return
            
            node = self.concepts[concept_name]
            self._print_node(node, indent)
        else:
            for name, node in self.concepts.items():
                if indent == 0:
                    print(f"\n{'─' * 40}")
                    print(f"  🧠 Ментальная модель: {self.name}")
                    print(f"  Концепций: {len(self.concepts)}")
                    print(f"{'─' * 40}")
                self._print_node(node, indent)
    
    def _print_node(self, node: ConceptNode, indent: int):
        """Визуально отображает один узел с связями."""
        prefix = "  " * indent
        icon = "💡" if node.confidence > 0.7 else "🔍" if node.confidence > 0.4 else "❓"
        
        print(f"{prefix}{icon} {node.name}")
        if node.definition_hypothesis:
            print(f"{prefix}   📝 '{node.definition_hypothesis[:60]}...'")
        print(f"{prefix}   Уверенность: {node.confidence:.1%} | Опыт: {len(node.experiences)} встреч")
        
        if node.connections:
            top_connections = sorted(node.connections.items(), key=lambda x: x[1], reverse=True)[:3]
            for conn_name, weight in top_connections:
                print(f"{prefix}   ↔ {conn_name} ({weight:.1%})")

# ============================================================
# Public API
# ============================================================
__all__ = [
    # Классы
    "ConceptNode",
    "MentalModel",
]
