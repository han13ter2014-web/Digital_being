"""
Active Concept Searcher (ActiveConceptSearcher)
========================================================

Модуль для активного поиска новых концепций, выходящих за рамки текущего пула стимулов.
Реализует инициативное обучение и самостоятельное расширение кругозора.

Пример использования:
    >>> from src.perception.active_searcher import ActiveConceptSearcher
    >>> searcher = ActiveConceptSearcher(agent)
    >>> new_topics = searcher.find_interesting_topics()
    >>> # Вернёт темы, которые агент хочет изучить сам (не от внешних стимулов)
    
    >>> new_concepts = searcher.get_available_new_concepts(max_count=10)
    >>> # Доступные концепции для самостоятельного изучения
    
"""

import random
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class InterestingConcept:
    """Интересная концепция для изучения."""
    concept_name: str  # Название концепции
    reason_to_study: str  # Почему стоит изучать (мотивация)
    complexity_estimate: float  # Ожидаемая сложность (0-1)
    estimated_reward: float  # Ожидаемая польза/интерес
    
    def to_dict(self):
        return {
            "concept": self.concept_name,
            "reason": self.reason_to_study[:80] if len(self.reason_to_study) > 80 else self.reason_to_study,
            "complexity": self.complexity_estimate,
            "reward": self.estimated_reward
        }


class ActiveConceptSearcher:
    """
    Активный поисатель концепций
    
    Создан для инициативного поиска новых тем за пределами STIMULI_POOL.
    
    Основные функции:
        - Поиск интересных тем на основе интересов агента
        - Генерация новых тем по ключевым категориям
        - Фильтрация изученных концепций
    
    Характеристики:
        - Использует интересы из MentalModelsPreferences
        - Генерирует темы на основе ключевых слов в известных концепциях
        - Оценивает сложность и потенциальную награду
        
    Примеры поиска:
        >>> # На основе интересов "Python" + "алгоритм":
        >>> #   → "Дерево поиска", "Сложность алгоритмов", "Оптимизация кода"
        
        >>> # На основе интересов "интеллект" + "обучение":
        >>> #   → "Машинное обучение", "Когнитивные науки", "Нейропластичность"
    """

    def __init__(self, agent):
        """
        Инициализация поисателя
        
        Args:
            agent: Агент (для доступа к interests и mental_models)
        """
        self.agent = agent
    
    def find_interesting_topics(self, min_newness: float = 0.5) -> List[InterestingConcept]:
        """
        Находит интересные темы для изучения за пределами STIMULI_POOL
        
        Алгоритм:
            1. Берём ключевые интересы агента (если есть)
            2. Генерируем новые темы на основе этих интересов
            3. Фильтруем уже изученные концепции
            4. Оцениваем сложность и награду
            
        Args:
            min_newness: Минимальная степень новизны (0-1). Чем выше, тем реже темы
        
        Returns:
            Список интересных концепций для изучения
    
        Примеры:
            >>> # Интересы: Python + алгоритм + данные
            >>> # Вернёт: ["Оптимизация кода", "Бинарные деревья", "Векторизация"]
        
            >>> # Интересы: интеллект + обучение + эволюция
            >>> # Вернёт: ["Машинное обучение", "Эволюционные алгоритмы", "Когнитивные исследования"]
        """
        
        import datetime
        
        available_concepts = self._get_available_new_concepts(max_count=20)
        
        if not available_concepts:
            return []
        
        # === ШАГ 1: ФИЛЬТРУЕМ ПО НОВИЗНЕ (min_newness) ===
        new_topics = [c for c in available_concepts if random.random() < min_newness]
        
        # Если слишком мало новых тем, рандомно добавляем несколько из общего пула
        while len(new_topics) < 5 and random.random() < 0.3:
            new_topics.append(random.choice(available_concepts))
        
        return new_topics
    
    def get_available_new_concepts(self, max_count: int = 20) -> List[InterestingConcept]:
        """
        Возвращает доступные новые концепции для изучения
        
        Альтернативный интерфейс: просто возвращает все новые темы без фильтрации по новизне.
    
        Args:
            max_count: Максимальное количество концепций
    
        Returns:
            Список InterestingConcept
        """
        
        concepts = self._generate_new_topics_from_interests(max_count)
        
        return concepts
    
    def _get_available_new_concepts(self, max_count: int = 20) -> List[InterestingConcept]:
        """
        Внутренний метод для получения доступных концепций.
        
        Алгоритм:
            1. Берём интересы из preferences (если есть)
            2. Генерируем темы на основе этих интересов
            3. Фильтруем уже изученные концепции из mental_models
            4. Возвращаем топ-k лучших
    
        Args:
            max_count: Максимальное количество концепций
        
        Returns:
            Список InterestingConcept (только не изученных)
        """
        
        # === ШАГ 1: БЕРЁМ ИНТЕРЕСЫ АГЕНТА ===
        interests = []
        if hasattr(self.agent, 'mental_models') and self.agent.mental_models:
            if hasattr(self.agent.mental_models, 'preferences') and self.agent.mental_models.preferences:
                for topic, pref_type in sorted(
                    self.agent.mental_models.preferences.items(),
                    key=lambda x: ['love', 'curious'].index(x[1]) if x[1] in ['love', 'curious'] else 2
                )[:3]:
                    interests.append(topic)
        
        # === ШАГ 2: ГЕНЕРИРУЕМ ТЕМЫ НА ОСНОВЕ ИНТЕРЕСОВ ===
        new_topics = self._generate_new_topics_from_interests(max_count)
        
        # === ШАГ 3: ФИЛЬТРУЕМ УЖЕ ИЗУЧЕННЫЕ КОНЦЕПЦИИ ===
        existing_concepts = set()
        if hasattr(self.agent, 'mental_models') and self.agent.mental_models.concepts:
            existing_concepts.update(self.agent.mental_models.concepts.keys())
        
        filtered_topics = []
        for topic in new_topics:
            if topic.concept_name not in existing_concepts:
                filtered_topics.append(topic)
        
        # Возвращаем топ-k (по estimated_reward * (1 - complexity_estimate))
        if filtered_topics:
            filtered_topics.sort(
                key=lambda x: x.estimated_reward * (1 - x.complexity_estimate),
                reverse=True
            )
            return filtered_topics[:max_count]
        
        return new_topics[:max_count]

    def _generate_new_topics_from_interests(self, max_count: int = 20) -> List[InterestingConcept]:
        """
        Генерирует новые темы на основе интересов агента
        
        Алгоритм:
            1. Берём интересы (если есть), иначе — ключевые категории
            2. Для каждого интереса генерируем подкатегории
            3. Оцениваем сложность и награду
    
        Args:
            max_count: Максимальное количество тем
        
        Returns:
            Список InterestingConcept
        """
        
        interests = self._get_interests()
        
        if not interests:
            # Если нет интересов — используем ключевые категории
            base_topics = self._get_base_topics()
            
        else:
            # Генерируем темы на основе интересов
            base_topics = []
            for interest in interests:
                generated = self._generate_subtopics(interest)
                base_topics.extend(generated)
        
        # Если недостаточно тем — добавляем рандомные из общей базы
        if len(base_topics) < max_count * 0.7:
            additional = self._get_additional_random_topics(max_count - len(base_topics))
            base_topics.extend(additional)
        
        return base_topics[:max_count]

    def _get_interests(self) -> List[str]:
        """
        Получает интересы агента из mental_models.preferences
        
        Возвращает топ-3 наиболее предпочтительные темы.
    
        Returns:
            Список интересов (строк)
        """
        interests = []
        
        if not hasattr(self.agent, 'mental_models'):
            return interests
        
        preferences = self.agent.mental_models.preferences
        
        # Берём топ-3 по приоритету (love > curious > neutral)
        sorted_prefs = sorted(
            preferences.items(),
            key=lambda x: ['love', 'curious', 'neutral'].index(x[1]) if x[1] in ['love', 'curious', 'neutral'] else 2
        )[:3]
        
        interests = [topic for topic, _ in sorted_prefs]
        return interests

    def _get_base_topics(self) -> List[InterestingConcept]:
        """
        Возвращает базовые темы для генерации (если нет интересов)
    
        Returns:
            Список InterestingConcept (базовые категории знаний)
        """
        
        base_categories = {
            "Дерево поиска": {"reason": "Структура данных для быстрого поиска", "complexity": 0.5, "reward": 0.7},
            "Хэш-таблица": {"reason": "Оптимизация доступа к данным", "complexity": 0.4, "reward": 0.6},
            "Куча (Heap)": {"reason": "Структура для управления приоритетами", "complexity": 0.5, "reward": 0.6},
            "Стек/Очередь": {"reason": "Фундаментальные структуры данных", "complexity": 0.3, "reward": 0.6},
            "Графы": {"reason": "Моделирование отношений и связей", "complexity": 0.7, "reward": 0.8},
            "Редко используемые структуры": {"reason": "Бинарные деревья, сегментные деревья", "complexity": 0.9, "reward": 0.5},
        }
        
        topics = []
        for name, info in base_categories.items():
            topics.append(InterestingConcept(
                concept_name=name,
                reason_to_study=info["reason"],
                complexity_estimate=info["complexity"],
                estimated_reward=info["reward"]
            ))
        
        return topics

    def _generate_subtopics(self, interest: str) -> List[InterestingConcept]:
        """
        Генерирует подтемы на основе интереса
        
        Алгоритм:
            1. Извлекаем ключевые слова из интереса (пробел → разделитель)
            2. Для каждого слова добавляем префиксы/суффиксы для создания новых тем
    
        Args:
            interest: Строка интереса (например, "Python для начинающих")
        
        Returns:
            Список InterestingConcept
        """
        
        subtopics = []
        words = [w.strip().lower() for w in interest.split()]
        
        # Добавляем префиксы/суффиксы для генерации новых тем
        prefixes_suffixes = [
            ("Алгоритм сортировки ", "Python"),
            ("Динамическое программирование ", "Python"),
            ("Рекурсия в ", "Python"),
            ("Визуализация структуры ", "данных Python"),
            ("Оптимизация кода на ", ""),
        ]
        
        for prefix_suffix in prefixes_suffixes:
            if prefix_suffix[0] and words:
                base_word = words[-1].title() if not prefix_suffix[0][-1].endswith(' ') else ""
                full_topic = prefix_suffix[0] + base_word
                subtopics.append(InterestingConcept(
                    concept_name=full_topic,
                    reason_to_study=f"Исследование темы '{prefix_suffix[0].strip()}'",
                    complexity_estimate=random.uniform(0.4, 0.8),
                    estimated_reward=random.uniform(0.5, 0.9)
                ))
        
        return subtopics

    def _get_additional_random_topics(self, count: int) -> List[InterestingConcept]:
        """
        Возвращает случайные дополнительные темы из общей базы
        
        Args:
            count: Количество тем
        
        Returns:
            Список InterestingConcept
        """
        
        random_base_topics = [
            InterestingConcept(
                concept_name="Оптимизация больших данных",
                reason_to_study="Изучение обработки и аналитики больших объемов данных",
                complexity_estimate=0.8,
                estimated_reward=0.9
            ),
            InterestingConcept(
                concept_name="Кибербезопасность и защита данных",
                reason_to_study="Механизмы защиты от атак и уязвимостей",
                complexity_estimate=0.7,
                estimated_reward=0.8
            ),
            InterestingConcept(
                concept_name="Облачные вычисления (Cloud Computing)",
                reason_to_study="Архитектура и использование облачных платформ",
                complexity_estimate=0.6,
                estimated_reward=0.75
            ),
        ]
        
        import random
        return random.sample(random_base_topics, min(count, len(random_base_topics)))

    def get_topic_interest_score(self, topic: str) -> float:
        """
        Вычисляет степень интереса к теме (на основе интересов агента)
    
        Args:
            topic: Название темы
    
        Returns:
            Степень интереса (0-1). Чем выше, тем больше агент заинтересован.
        """
        
        if not hasattr(self.agent, 'mental_models'):
            return 0.5
        
        preferences = self.agent.mental_models.preferences
        
        # Прямые интересы имеют вес
        if topic.lower() in preferences:
            pref_type = preferences[topic.lower()]
            if pref_type == "love":
                return 1.0
            elif pref_type == "curious":
                return 0.8
            else:
                return 0.5
        
        # Если нет прямого интереса — случайный (для расширения кругозора)
        return random.uniform(0.2, 0.6)

    def should_explore_topic(self, topic: str) -> bool:
        """
        Определяет, стоит ли изучать тему (для принятия решений)
    
        Args:
            topic: Название темы
        
        Returns:
            True если стоит изучить (интересно или полезно)
        """
        
        score = self.get_topic_interest_score(topic)
        return random.random() < 0.5 or score > 0.7

    def generate_learning_plan(self, topics: List[str], duration_cycles: int = 10) -> str:
        """
        Генерирует план обучения для списка тем
    
        Args:
            topics: Список тем для изучения
            duration_cycles: Сколько циклов потратим
        
        Returns:
            Текст плана обучения
        """
        
        if not topics:
            return "Нет тем для изучения в плане."
        
        sorted_topics = sorted(topics, key=lambda t: self.get_topic_interest_score(t), reverse=True)
        
        plan_parts = [f"План обучения на {duration_cycles} циклах:", f"1. Сначала изучу: {', '.join(sorted_topics[:3])}", 
                     f"2. Затем: {', '.join(sorted_topics[3:min(6, len(sorted_topics))])}",
                     f"3. В конце — подведу итоги и сгенерирую тест."]
        
        return "\n".join(plan_parts)