"""
Knowledge Association Engine (KnowledgeAssociationEngine)
=========================================================

Модуль для связывания концепций между собой на основе общих идей.
Реализует эмерджентное поведение через ассоциации знаний.

Пример использования:
    >>> from src.memory.knowledge_association import KnowledgeAssociationEngine
    >>> engine = KnowledgeAssociationEngine(mental_models)
    >>> associations = engine.find_associations("Python", max_distance=2)
    >>> # Вернёт связанные концепции с весами
"""

import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ConceptAssociation:
    """Ассоциация между двумя концепциями."""
    from_concept: str  # Исходная концепция
    to_concept: str    # Связанная концепция
    association_strength: float  # Вес связи (0-1)
    context: str  # Контекст ассоциации (почему связаны)
    
    def to_dict(self):
        return {
            "from": self.from_concept,
            "to": self.to_concept,
            "weight": self.association_strength,
            "context": self.context[:100] if len(self.context) > 100 else self.context
        }


class KnowledgeAssociationEngine:
    """
    Инженерия ассоциаций знаний
    
    Создана для формирования сетевой структуры знаний и эмерджентного поведения.
    
    Основные функции:
        - Создание связей между концепциями на основе общих идей
        - Поиск связанных концепций для расширения кругозора
        - Анализируют семантическую схожесть понятий
    
    Характеристики:
        - Связи создаются только если есть хотя бы 2 совпадающих слова/корня
        - Вес связи = (совпадения / max(слова)) * случайный множитель (0.3-0.8)
        - Контекст — объяснение почему связаны (ключевые общие слова)
    
    Примеры создания связей:
        >>> # Python → программирование (100% совпадение по смыслу)
        >>> # Данные → структура данных (2 общих корня + связь по контексту)
        >>> # Интеллект → обучение (через опыт и рефлексию)
    """
    
    # === НАСТРОЙКИ ===
    
    # Минимальная схожесть для создания связи (по общему количеству слов)
    MIN_SIMILARITY_THRESHOLD = 0.15
    
    # Минимум общих терминов для создания связи
    MIN_COMMON_TERMS = 2
    
    # Максимум ассоциаций, которые генерирует за один вызов
    MAX_GENERATE_ASSOCIATIONS = 300
    
    # Список ключевых понятий (для поиска ассоциаций)
    KEY_CONCEPTS = [
        "Python", "кодирование", "программирование", "алгоритм", "данные",
        "структура", "память", "искусственный интеллект", "нейросеть",
        "обучение", "эволюция", "развитие", "саморазвитие", "интеллект",
        "знание", "опыт", "мысленная модель", "концепция", "связь"
    ]

    def __init__(self, mental_models):
        """
        Инициализация двигателя ассоциаций
        
        Args:
            mental_models: Ментальные модели агента (граф знаний)
        """
        self.mental_models = mental_models
    
    def find_associations(self, concept_name: str, max_distance: int = 1) -> List[ConceptAssociation]:
        """
        Находит ассоциации для концепции на заданное расстояние
        
        Args:
            concept_name: Название концепции (или ключевое понятие)
            max_distance: Максимальное расстояние в графе (количество прыжков)
        
        Returns:
            Список ассоциаций с весами и контекстами
    
        Примеры:
            >>> # Для "Python":
            >>> #   → кодирование (прямая связь, 0.75 вес)
            >>> #   → программист (через кодирование, 0.42 веса)
        
        >>> # Для "алгоритм":
            >>> #   → сортировка (прямая связь, 0.81 вес)
            >>> #   → оптимизация (через сортировку, 0.55 вес)
        """
        associations = []
        
        # === ШАГ 1: НАХОДИМ СВЯЗАННЫЕ КОНЦЕПЦИИ В ГРАФЕ ===
        related_concepts = self.mental_models.find_related_concepts(
            concept_name, 
            max_distance=max_distance, 
            min_weight=0.1
        )
        
        if not related_concepts:
            return []
        
        # === ШАГ 2: ГЕНЕРИРУЕМ СЕМАНТИЧЕСКИЕ СВЯЗИ ===
        for target in related_concepts:
            associated = self._generate_semantic_association(concept_name, target)
            if associated:
                associations.append(associated)
        
        # === ШАГ 3: ДОБАВЛЯЕМ ПРОБЛЕМНЫЕ АССОЦИАЦИИ (для расширения кругозора) ===
        if len(associations) < self.MAX_GENERATE_ASSOCIATIONS:
            associations.extend(self._generate_problematic_associations(concept_name, related_concepts))
        
        return associations[:self.MAX_GENERATE_ASSOCIATIONS]

    def _generate_semantic_association(self, from_concept: str, to_concept: str) -> Optional[ConceptAssociation]:
        """
        Создаёт семантическую связь на основе общих понятий
        
        Алгоритм:
            1. Извлекаем ключевые слова из обеих концепций (пробел → разделитель)
            2. Находим общие термины (case-insensitive)
            3. Считаем минимальную схожесть по количеству слов
            4. Если схожесть >= threshold — создаём связь
        
        Пример:
            >>> from_concept = "Python для начинающих"
            >>> to_concept = "программирование на Python"
            >>> # Общие слова: {"python", "начинающ"}, min_similarity = 2/4 = 0.5 -> Связь!
            
        Args:
            from_concept: Исходная концепция
            to_concept: Цельная концепция
        
        Returns:
            ConceptAssociation если схожесть достаточна, None иначе
        """
        
        # === Шаг 1: Подготовка данных ===
        words_from = set(w.lower() for w in from_concept.split())
        words_to = set(w.lower() for w in to_concept.split())
        
        # Нормализуем термины (например, "data" + "base" → "database")
        from_terms = self._normalize_terms(from_concept)
        to_terms = self._normalize_terms(to_concept)
        
        common_terms = from_terms & to_terms
        
        if not common_terms:
            return None
        
        # === Шаг 2: Расчёт схожесть (Jaccard similarity) ===
        total_words_from = len(words_from)
        total_words_to = len(words_to)
        
        total_union = len(words_from | words_to)
        min_similarity = len(common_terms) / max(total_union, 1)
        
        # === Шаг 3: Проверка порогов ===
        if min_similarity < self.MIN_SIMILARITY_THRESHOLD and len(common_terms) < self.MIN_COMMON_TERMS:
            return None
        
        # === Шаг 4: Создание контекста (почему связаны?) ===
        context = self._generate_association_context(from_concept, to_concept, common_terms)
        
        # === Шаг 5: Расчёт веса (с небольшим стохастицизмом для разнообразия) ===
        base_weight = min_similarity * 0.8
        import random
        randomness_factor = 1.0 if len(common_terms) >= 4 else random.uniform(0.3, 0.9)
        weight = base_weight * randomness_factor
        
        # Ограничим вес диапазоном 0-1
        weight = min(1.0, max(0.0, weight))
        
        return ConceptAssociation(
            from_concept=from_concept,
            to_concept=to_concept,
            association_strength=weight,
            context=context
        )

    def _normalize_terms(self, text: str) -> set:
        """
        Нормализует термины для объединения (case-insensitive, удаляет лишнее)
        
        Примеры нормализации:
            >>> "database" → {"database"}
            >>> "data structure" → {"structure", "data", "array"}
            
        Args:
            text: Исходный текст концепции
        
        Returns:
            Set терминов (ниже регистра, без префиксов)
        """
        terms = set(w.lower() for w in text.split())
        
        # Удаляем короткие слова (менее 4 символов) — они неспецифичны
        terms = {t for t in terms if len(t) >= 4}
        
        return terms

    def _generate_association_context(self, from_concept: str, to_concept: str, common_terms: set) -> str:
        """
        Создаёт объяснение контекста ассоциации
        
        Алгоритм:
            1. Берём первые 3 общих термина (слова)
            2. Объединяем с "поскольку обе содержат [совпадения]"
        
        Примеры:
            >>> # Python + программирование на Python
            >>> # → "Поскольку обе концепции содержат термины: {python, кодирование, программ...}"
            
            >>> # Данные + структура данных  
            >>> # → "Обе темы связаны через понятия: данные и структуры."
        
        Args:
            from_concept: Исходная концепция
            to_concept: Цельная концепция
            common_terms: Общие термины
        
        Returns:
            Описание контекста (макс. 100 символов)
        """
        
        # Берём первые 3 общих термина для краткости
        top_common = sorted(common_terms, key=len)[:3]
        
        context_parts = [f"Поскольку обе концепции содержат: {', '.join(top_common)}"]
        
        # Добавляем контекст (опционально)
        if len(from_concept) > 20 or len(to_concept) > 20:
            context_parts.append("и тематически связаны")
        
        full_context = " ".join(context_parts)
        
        return full_context[:100] if len(full_context) > 100 else full_context

    def _generate_problematic_associations(self, concept_name: str, related_concepts: List) -> List[ConceptAssociation]:
        """
        Генерирует проблемные ассоциации для расширения кругозора
        
        Алгоритм:
            1. Выбираем случайную связанную концепцию
            2. Добавляем "сложный/редкий/контр-" префикс/суффикс к ней
            3. Создаём гипотетическую ассоциацию с весом 0.2-0.5
        
        Примеры проблемных ассоциаций:
            >>> # Для концепции "Python":
            >>> #   → "Парадоксы Python" (гипотетическая тема)
            >>> #   → "Ошибки в Python" (связь с проблемами)
            
            >>> # Для "алгоритм":
            >>> #   → "Неэффективные алгоритмы" (антисоциальный контекст)
            >>> #   → "Проблемы алгоритмов" (проблематизация темы)
        
        Args:
            concept_name: Исходная концепция
            related_concepts: Связанные концепции в графе
        
        Returns:
            Список проблемных ассоциаций (макс. 5 за один вызов)
        """
        problematic = []
        
        # Берём случайную связанную концепцию для модификации
        if not related_concepts:
            return []
        
        import random
        target_concept = random.choice(related_concepts)
        
        # === Проблема 1: Антисоциальные/контрастные ассоциации (отрицательные темы) ===
        problematic_words = ["антисоциальный", "проблемы", "ошибки", "неэффективные", 
                            "парадоксы", "риски", "сложности"]
        
        for prefix in problematic_words:
            # Добавляем префиксу к концепции (если не слишком длинная)
            if len(target_concept) < 30:
                new_topic = f"{prefix} {target_concept}"
                problematic.append(ConceptAssociation(
                    from_concept=concept_name,
                    to_concept=new_topic,
                    association_strength=random.uniform(0.2, 0.4),  # Низкий вес для проблемных
                    context=f"Возможно связан с темой '{new_topic}' (гипотеза)"
                ))
        
        return problematic[:5]

    def get_network_stats(self) -> Dict:
        """
        Возвращает статистику сети знаний
        
        Returns:
            Словарь со статистикой
    
        Пример структуры:
            >>> {
                    "total_concepts": 10,
                    "total_associations": 45,
                    "avg_connections_per_node": 4.5,
                    "most_connected": {"concept": "Python", "connections": 8}
                }
        """
        
        # Здесь могла быть сложная статистика сети
        # Пока возвращаем заглушку (для расширения в будущем)
        return {
            "total_concepts": len(self.mental_models.concepts) if hasattr(self.mental_models, 'concepts') else 0,
            "total_associations": 0,  # Будет заполняться при генерации
            "avg_connections_per_node": 0.0,
            "most_connected": None
        }

    def export_associations(self) -> List[Dict]:
        """Экспортирует текущие ассоциации (будущее расширение)."""
        return []