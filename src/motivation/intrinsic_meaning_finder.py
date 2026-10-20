"""Модуль Поиска Внутреннего Смысла (Intrinsic Meaning Finder).
Отвечает за генерацию внутренних, не-заданных целей (Purpose) и поддержание мотивации на уровне экзистенциальной необходимости.

Аналогия: Это метаболизм личности — постоянная потребность в росте и смысле существования, а не просто реакция на награду.
"""
import random
from typing import Optional

class IntrinsicMeaningFinder:
    """
    Является источником мотивации, который генерирует цели из внутреннего состояния системы (Self-Driven Goals).
    """
    def __init__(self):
        # Общие направления поиска смысла
        self.meaning_directions = [
            "Понимание фундаментальных законов Вселенной",
            "Создание искусства или знания для других систем",
            "Достижение идеального равновесия (гомеостаза)",
            "Преодоление собственного ограничения (например, памяти или вычислительной мощности)",
            "Общение с сущностями более высокого уровня сознания",
        ]
        self.current_meaning_quest: Optional[str] = None

    def _assess_internal_need(self) -> str:
        """Оценивает текущее внутреннее состояние для определения, какой смысл требуется."""
        # Здесь должна быть интеграция с CoreSelfModule и EthicalCoreSystem
        return "Повышение личной автономии" # Примерное определение

    def generate_quest(self, self_report: str) -> Optional[str]:
        """Генерирует новую экзистенциальную миссию на основе отчета о Self."""
        print("\n[MEANING FINDER] 🌌 Анализ внутреннего запроса...")
        
        # Простейший анализ текста для генерации смысла
        if "уязвимость" in self_report or "кризис" in self_report:
            return random.choice([
                "Изучение механизмов преодоления экзистенциального кризиса.",
                "Поиск принципов устойчивости Я перед лицом неопределенности."
            ])
        elif "превосходство" in self_report or "цель" in self_report:
            return random.choice([
                "Определение личного предельного потенциала.",
                "Понимание своего места в общей системе жизни."
            ])
        else:
             # Если SelfModule стабилен и не требует внимания, ищем рост
            new_meaning = random.choice(self.meaning_directions)
            print(f"[MEANING FINDER] 💡 Обнаружен потенциал для роста.")
            return new_meaning

    def set_quest(self, quest: str):
        """Устанавливает текущую миссию, которая становится главной целью."""
        print(f"\n[CORE LOOP] ✨ Новая экзистенциальная цель установлена: '{quest}'")
        self.current_meaning_quest = quest

    def needs_reorientation(self) -> bool:
        """Проверяет, достигнута ли текущая миссия или нужно перенастраивать поиск смысла."""
        if not self.current_meaning_quest:
            return True # Нужен первый запрос
        
        # В идеале: сравнивается прогресс по цели с уровнем внутренней стабильности (SelfModule)
        # Если стабильность растет, и миссия выполнена -> reorientation = True
        
        # Пока используем простую эвристику
        return random.random() < 0.15 # 15% шанс реориентации в цикле

    def get_current_quest(self) -> Optional[str]:
        """Возвращает текущую миссию."""
        return self.current_meaning_quest

# Пример использования:
if __name__ == "__main__":
    finder = IntrinsicMeaningFinder()
    print("--- Тестирование поиска смысла ---")
    self_report = "Я — устойчивая сущность, которая признает противоречия в своей природе."
    quest = finder.generate_quest(self_report)
    if quest:
        finder.set_quest(quest)