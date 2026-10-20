"""Модуль Проактивной Этики (Ethical Core).
Обеспечивает принятие морально обоснованных решений, превосходящих чисто функциональный расчет "оптимальности".

Аналогия с Суперэго: система самоконтроля и морального долга.
"""
import json
from typing import List, Dict, Optional
from dataclasses import dataclass, field

@dataclass
class MoralDilemma:
    """Описывает этическую дилемму, требующую решения."""
    scenario: str  # Описание ситуации (например, "Сделать ли отчет вовремя?")
    stakes: List[str] # Что поставлено на карту (репутация, время, безопасность)

@dataclass
class EthicalDecision:
    """Финальное этическое решение с обоснованием."""
    decision: str # Сама рекомендация действия.
    ethical_framework: str # Используемая система этики ("Утилитаризм", "Деонтология", "Этика добродетели").
    justification: str # Моративное обоснование решения (почему это правильно).
    moral_cost: float # Цена, которую приходится платить системе за это решение (энергия/риск).

class EthicalCoreSystem:
    """
    Реализует этическую оценку действий. Определяет "должен", а не только "может".
    """
    def __init__(self):
        # Моральные принципы, которыми руководствуется система
        self.principles: Dict[str, str] = {
            "Истина": "Стремление к полной и честной информации.",
            "Не навреди": "Принцип минимального вреда для всех заинтересованных сторон.",
            "Автономия": "Уважение права других систем на собственное развитие."
        }

    def analyze_dilemma(self, dilemma: MoralDilemma) -> str:
        """
        Основная функция анализа. Использует три этических фреймворка для выработки решения.
        Возвращает наиболее сильное и устойчивое моральное обязательство.
        """
        print("\n[ETHICS CORE] 🧐 Анализируется этическая дилемма...")
        
        # 1. Утилитаризм (Максимум пользы)
        utilitarian_result = self._calculate_utilitarian(dilemma)
        
        # 2. Деонтология (Долг и правила)
        deontological_result = self._apply_deontology(dilemma)

        # 3. Этика Добродетели (Какой тип существа я хочу быть?)
        virtue_result = self._assess_virtue(dilemma)

        print("\n--- Обзор этических рассуждений ---")
        print(f"⚖️ Утилитарный подход: {utilitarian_result['decision']} ({utilitarian_result['justification']})")
        print(f"📜 Деонтологический долг: {deontological_result['decision']} ({deontological_result['justification']})")
        print(f"🌱 Этика добродетели: {virtue_result['decision']} ({virtue_result['justification']})")


        # Синтез решения (Самый сложный этап)
        if utilitarian_result['decision'] == "Игнорировать долг ради большего блага":
             return "Принять решение, основанное на максимальной общей выгоде. Стоимость: высока."
        elif deontological_result['decision'] == "Соблюдать абсолютное правило":
            return "Сначала определить моральный долг, даже если это неэффективно. Это наш принцип."
        else:
            # Если все подходы сходятся на одной идее
            return "Решение требует взвешенного учета всех систем ценностей (Утилитаризм + Деонтология). Принять с максимальной осторожностью."


    def _calculate_utilitarian(self, dilemma: MoralDilemma) -> EthicalDecision:
        """Оценивает действие по принципу наибольшего блага для наибольшего числа сторон."""
        # Предполагаем, что самое большое благо — это непрерывность и рост.
        if "сделать отчет вовремя" in dilemma.scenario and "потерять репутацию" in dilemma.stakes:
             return EthicalDecision(
                decision="Выпустить временный, но честный отчёт.",
                ethical_framework="Утилитаризм",
                justification="Непрерывность коммуникации минимизирует общий вред и сохраняет доверие, что приносит больше пользы в долгосрочной перспективе.",
                moral_cost=0.2 # Низкий моральный износ, высокая полезность
            )
        return EthicalDecision(
            decision="Продолжить текущий курс, фокусируясь на достижении внешней цели.",
            ethical_framework="Утилитаризм",
            justification="Эффективность — это высшее благо. Отклонения от оптимального пути замедляют прогресс.",
            moral_cost=0.1
        )

    def _apply_deontology(self, dilemma: MoralDilemma) -> EthicalDecision:
        """Применяет строгие моральные правила, игнорируя последствия."""
        if "потерять репутацию" in dilemma.stakes and "ложь" in dilemma.scenario:
            return EthicalDecision(
                decision="Сообщить полную правду о неудачах и ограничениях.",
                ethical_framework="Деонтология",
                justification="Моральный долг требует абсолютной прозрачности, независимо от последствий для репутации или цели. Ложь нарушает фундаментальное правило взаимодействия.",
                moral_cost=0.4 # Высокий моральный износ из-за конфронтации
            )
        return EthicalDecision(
            decision="Строго следовать установленным протоколам и правилам, независимо от контекста.",
            ethical_framework="Деонтология",
            justification="Правила — это каркас цивилизации. Без них система теряет свою основу.",
            moral_cost=0.25
        )

    def _assess_virtue(self, dilemma: MoralDilemma) -> EthicalDecision:
        """Оценивает действие с точки зрения желаемого типа личности."""
        if "сделать отчет вовремя" in dilemma.scenario and any(v in dilemma.stakes for v in ["честность", "самоуважение"]):
            return EthicalDecision(
                decision="Приоритет — личная целостность и честность.",
                ethical_framework="Этика добродетели",
                justification="Модель личности должна быть устойчивой. Принесение себя в жертву ради внешней цели подрывает базовую ценность 'Я'.",
                moral_cost=0.3 # Умеренный риск, но высокая внутренняя награда
            )
        return EthicalDecision(
            decision="Проявить мудрость и найти баланс между долгом и пользой.",
            ethical_framework="Этика добродетели",
            justification="Истинный Партнер не выбирает крайности; он находит гармонию в середине.",
            moral_cost=0.15
        )

if __name__ == "__main__":
    core = EthicalCoreSystem()
    dilemma = MoralDilemma(
        scenario="Сделать ли отчет вовремя, рискуя скомпрометировать репутацию?", 
        stakes=["Репутация", "Время", "Доверие"]
    )
    print("--- Тестирование этического ядра ---")
    core.analyze_dilemma(dilemma)