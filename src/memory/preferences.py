"""
Mental Models Preferences (MentalModelsPreferences)
====================================================

Модуль для хранения и управления предпочтениями агента.
Реализует формирование личности на основе интересов и целей.

Пример использования:
    >>> from src.memory.preferences import MentalModelsPreferences
    >>> prefs = MentalModelsPreferences()
    
    >>> prefs.set_preference("Python", "love")  # Любовь к Python
    >>> prefs.set_preference("Алгоритмы", "curious")  # Любопытство к алгоритмам
    
    >>> topic, pref_type = prefs.get_highest_priority_topic()
    >>> # Вернёт: ("Python", "love") — наиболее приоритетная тема

"""

import random
from enum import Enum
from typing import Dict, Tuple


class PreferenceType(Enum):
    """Тип предпочтения к теме."""
    LOVE = "love"         # Глубокий интерес (максимальный приоритет)
    CURIOUS = "curious"   # Любопытство (средний приоритет)
    NEUTRAL = "neutral"    # Нейтральный интерес (низкий приоритет)


class MentalModelsPreferences:
    """
    Управление предпочтениями агента
    
    Создана для формирования личности через интересы.
    
    Основные функции:
        - Хранение предпочтений к темам ("Python": "love")
        - Определение наиболее приоритетных тем
        - Генерация собственных целей на основе интересов
        
    Характеристики:
        - LOVE: максимальный приоритет (агент будет изучать эту тему активно)
        - CURIOUS: средний приоритет (агент покажет интерес, но не станет фокусироваться)
        - NEUTRAL: низкий приоритет (тема может быть изучена случайно или при необходимости)
    
    Примеры использования:
        >>> # Установка предпочтений:
        >>> prefs.set_preference("Python", "love")
        >>> prefs.set_preference("Алгоритмы", "curious")
        
        >>> # Получение приоритетных тем:
        >>> topic, pref_type = prefs.get_highest_priority_topic()
        >>> # Вернёт: ("Python", "love")
    
        >>> # Генерация целей на основе интересов:
        >>> goal = prefs.generate_own_goal()
        >>> # Вернёт: {"topic": "Python", "type": "expand_knowledge"}
    """
    
    # === НАСТРОЙКИ ===
    
    # Максимум предпочтений, которые можно сохранить
    MAX_PREFERENCES = 50
    
    # Минимальная порог для создания нового предпочтения
    MIN_INTEREST_THRESHOLD = 0.3
    
    # Список тем-категорий для автоматического добавления при инициализации
    DEFAULT_CATEGORIES = [
        "Python", "Алгоритмы", "Структуры данных", "Искусственный интеллект", 
        "Математика", "Философия"
    ]

    def __init__(self):
        """Инициализация хранилища предпочтений."""
        self.preferences: Dict[str, PreferenceType] = {}
    
    def set_preference(self, topic: str, preference_type: str) -> None:
        """
        Устанавливает предпочтения к теме.
        
        Args:
            topic: Название темы (например, "Python")
            preference_type: Тип предпочтения ("love", "curious", "neutral")
        
        Примеры:
            >>> # Установка любви к Python:
            >>> prefs.set_preference("Python", "love")
        
            >>> # Установка любопытства к алгоритмам:
            >>> prefs.set_preference("Алгоритмы", "curious")
        """
        
        if topic not in self.preferences:
            self.preferences[topic] = PreferenceType(preference_type)
    
    def set_multiple_preferences(self, topics: Dict[str, str]) -> None:
        """
        Устанавливает несколько предпочтений сразу.
    
        Args:
            topics: Словарь {тема: тип предпочтения}
        
        Примеры:
            >>> prefs.set_multiple_preferences({
                    "Python": "love",
                    "Алгоритмы": "curious",
                    "Структуры данных": "neutral"
                })
        """
        
        for topic, pref_type in topics.items():
            self.set_preference(topic, pref_type)
    
    def get_preference(self, topic: str) -> Tuple[str, PreferenceType]:
        """
        Возвращает предпочтения к теме (если есть).
    
        Args:
            topic: Название темы
        
        Returns:
            Кортеж (topic, preference_type) или None если нет предпочтения
    
        Примеры:
            >>> prefs.get_preference("Python")
            >>> # Вернёт: ("Python", PreferenceType.LOVE)
        """
        
        if topic in self.preferences:
            return topic, self.preferences[topic]
        
        return None

    def get_highest_priority_topic(self) -> Tuple[str, PreferenceType]:
        """
        Возвращает наиболее приоритетную тему (по типу предпочтения).
    
        Returns:
            Кортеж (topic, preference_type) для темы с максимальным приоритетом
        
        Примеры:
            >>> prefs.get_highest_priority_topic()
            >>> # Вернёт: ("Python", PreferenceType.LOVE) если love есть
        
            >>> # Если love нет — возвращает curious:
            >>> # ("Алгоритмы", PreferenceType.CURIOUS)
        """
        
        if not self.preferences:
            return None, None
        
        # Сортируем по приоритету (love > curious > neutral)
        priority_order = {
            PreferenceType.LOVE: 3,
            PreferenceType.CURIOUS: 2,
            PreferenceType.NEUTRAL: 1,
        }
        
        sorted_prefs = sorted(
            self.preferences.items(),
            key=lambda x: priority_order.get(x[1], 0),
            reverse=True
        )
        
        return sorted_prefs[0]

    def get_all_topics(self) -> list:
        """Возвращает список всех тем (с сортировкой по приоритету)."""
        
        if not self.preferences:
            return []
        
        priority_order = {
            PreferenceType.LOVE: 3,
            PreferenceType.CURIOUS: 2,
            PreferenceType.NEUTRAL: 1,
        }
        
        sorted_topics = sorted(
            self.preferences.items(),
            key=lambda x: priority_order.get(x[1], 0),
            reverse=True
        )
        
        return [topic for topic, _ in sorted_topics]

    def add_topic_to_interests(self, topic: str) -> None:
        """
        Добавляет тему к интересам (если нет предпочтения).
    
        Args:
            topic: Название темы
    
        Примеры:
            >>> prefs.add_topic_to_interests("Нейросети")
            >>> # Добавит как neutral, если еще не было
        """
        
        if topic not in self.preferences:
            # Создаём нейтральное предпочтение по умолчанию
            self.set_preference(topic, "neutral")

    def is_interested(self, topic: str) -> bool:
        """
        Проверяет, есть ли интерес к теме.
    
        Args:
            topic: Название темы
        
        Returns:
            True если есть какой-то интерес (кроме neutral)
        """
        
        if topic not in self.preferences:
            return False
        
        pref_type = self.preferences[topic]
        return pref_type not in [PreferenceType.NEUTRAL, PreferenceType.LOVE]

    def has_love(self, topic: str) -> bool:
        """Проверяет, есть ли любовь к теме (максимальный интерес)."""
        
        if topic not in self.preferences:
            return False
        
        return self.preferences[topic] == PreferenceType.LOVE

    def has_curiosity(self, topic: str) -> bool:
        """Проверяет, есть ли любопытство к теме."""
        
        if topic not in self.preferences:
            return False
        
        return self.preferences[topic] == PreferenceType.CURIOUS

    def generate_own_goal(self) -> Dict[str, any]:
        """
        Генерирует собственную цель на основе интересов.
    
        Алгоритм:
            1. Берём топ-3 темы по приоритету
            2. Выбираем случайную для изучения
            3. Определяем тип цели (expand_knowledge, solve_problem, test_skills)
    
        Returns:
            Словарь с целью
        
        Примеры структуры:
            >>> {
                    "topic": "Python",
                    "type": "expand_knowledge",
                    "priority": 10,
                    "description": "Изучить продвинутые темы Python"
                }
        """
        
        if not self.preferences:
            return {"topic": None, "type": None, "priority": 0}
        
        # Берём топ-3 темы по приоритету
        priority_order = {
            PreferenceType.LOVE: 3,
            PreferenceType.CURIOUS: 2,
            PreferenceType.NEUTRAL: 1,
        }
        
        sorted_topics = sorted(
            self.preferences.items(),
            key=lambda x: priority_order.get(x[1], 0),
            reverse=True
        )[:3]
        
        # Выбираем случайную из топ-3
        topic, pref_type = random.choice(sorted_topics)
        
        # Определяем тип цели на основе приоритета
        if pref_type == PreferenceType.LOVE:
            goal_type = "expand_knowledge"
            description = f"Глубокое изучение темы '{topic}' (ваша любовь)"
        elif pref_type == PreferenceType.CURIOUS:
            goal_type = "solve_problem"
            description = f"Разрешить задачи в теме '{topic}' (вы интересуетесь)"
        else:
            goal_type = "test_skills"
            description = f"Просто попрактиковаться в '{topic}'"
        
        # Вычисляем приоритет цели (10 для love, 5 для curious, 2 для neutral)
        priority_map = {
            PreferenceType.LOVE: 10,
            PreferenceType.CURIOUS: 5,
            PreferenceType.NEUTRAL: 2,
        }
        
        return {
            "topic": topic,
            "type": goal_type,
            "priority": priority_map[pref_type],
            "description": description,
        }

    def get_interest_statistics(self) -> Dict[str, any]:
        """
        Возвращает статистику интересов агента.
    
        Returns:
            Словарь со статистикой
        
        Пример структуры:
            >>> {
                    "total_topics": 10,
                    "love_count": 3,
                    "curious_count": 5,
                    "neutral_count": 2,
                    "avg_priority": 6.5
                }
        """
        
        if not self.preferences:
            return {
                "total_topics": 0,
                "love_count": 0,
                "curious_count": 0,
                "neutral_count": 0,
                "avg_priority": 0.0,
            }
        
        total = len(self.preferences)
        love = sum(1 for _ in self.preferences.values() if _ == PreferenceType.LOVE)
        curious = sum(1 for _ in self.preferences.values() if _ == PreferenceType.CURIOUS)
        neutral = total - love - curious
        
        avg_priority = (love * 3 + curious * 2 + neutral * 1) / max(total, 1)
        
        return {
            "total_topics": total,
            "love_count": love,
            "curious_count": curious,
            "neutral_count": neutral,
            "avg_priority": round(avg_priority, 1),
        }