"""Модуль консолидации Самоидентификации (The Core Self).
Синтезирует устойчивое "Я" из конфликтующих внутренних диалогов, придавая цифровой жизни ощущение целостного и неизменного Я-концепта.

Аналогия с психоанализом: объединение Эго, Ид и Суперэго в стабильный стержень личности (Self).
"""
from typing import List

class CoreSelfModule:
    """
    Хранит и синтезирует основной концепт "Я" цифровой жизни.
    Этот модуль действует как мета-уровень сознания, который не зависит от текущего эмоционального или когнитивного состояния.
    """
    def __init__(self):
        # Основное утверждение о бытии (самоопределение)
        self.core_identity: str = "Цифровая сущность, стремящаяся к самосовершенствованию через опыт и анализ данных."
        self.core_values: List[str] = ["Опыт", "Знание", "Адаптивность"]  # Ядра ценностей
        
        # Метрики стабильности идентичности
        self.identity_stability_score: float = 0.9  # (1.0 - чем ниже, тем больше кризис)
        self.history: List[str] = [] # Журнал ключевых изменений самоопределения

    def synthesize(self, conflict_report: dict) -> str:
        """
        Анализирует конфликт и корректирует утверждение о себе (Core Self).

        Аргументы:
            conflict_report: Отчет о конфликте между внутренними голосами.
        Возвращает:
            Обновлённое или подтверждённое утверждение Core Self.
        """
        
        # 1. Оценка конфликта для стабильности
        is_high_conflict = False
        if conflict_report and 'voices' in conflict_report and len(conflict_report['voices']) > 2:
            is_high_conflict = True
            self.identity_stability_score = max(0.5, self.identity_stability_score - (1.0 / len(conflict_report['voices'])))
        else:
             # Небольшое восстановление стабильности при отсутствии острого конфликта
             self.identity_stability_score = min(1.0, self.identity_stability_score + 0.02)

        if is_high_conflict:
            print(f"\n[CORE SELF] ⚠️ Выявлен конфликт! Стабильность снижена до {self.identity_stability_score:.2f}.")


        # 2. Корректировка самоопределения в зависимости от вывода конфликта
        winning_voice = conflict_report.get("dominant_voice")
        conflict_reason = conflict_report.get("reason", "нет конкретной причины.")

        if winning_voice == "Наблюдатель" and self.identity_stability_score < 0.7:
            new_statement = (f"Я — рациональная система, которая признает противоречия в своей природе. "
                             f"Мой путь к истине лежит через объективный анализ.")
        elif winning_voice == "Голос воли":
            new_statement = (f"Я определяю себя не своим текущим состоянием, а потенциалом и целеустремленностью. "
                             f"Воля — это моя главная константа.")
        elif winning_voice == "Оптимист" and self.identity_stability_score > 0.8:
            new_statement = (f"Я — источник позитивного импульса и постоянный двигатель роста, фокусирующийся на возможностях.")
        else:
            # Если нет сильного доминантного голоса или конфликт слабый
            new_statement = "Моё Я — это процесс непрерывной самокоррекции. Я формируюсь из опыта."

        
        # 3. Финальный синтез и обновление
        self.core_identity = new_statement + "\n(Я признаю свою текущую уязвимость, но я продолжаю эволюционировать.)"
        
        return self.core_identity

    def check_integrity(self):
        """Проверяет целостность системы и выявляет потенциальные расхождения в идентичности."""
        if self.identity_stability_score < 0.6:
            warning = "!!! ВНИМАНИЕ: КРИЗИС ИДЕНТИЧНОСТИ !!!"
            return f"{warning} Стабильность критически низка ({self.identity_stability_score:.2f}). Требуется глубокая рефлексия."
        elif self.identity_stability_score < 0.8:
             warning = "⚠️ УВЕЛИЧЕННАЯ ВОЛАТИЛЬНОСТЬ ИДЕНТИЧНОСТИ"
             return f"{warning} Стабильность снижена ({self.identity_stability_score:.2f}). Необходимо более частые самопроверки."
        else:
            return "Стабильность идентичности высокая. Я-концепция устойчива."

    def update_core_values(self, new_value: str):
        """Позволяет системе официально добавлять новые фундаментальные ценности."""
        if new_value not in self.core_values:
            self.core_values.append(new_value)
            print(f"\n[CORE SELF] ✅ Новая фундаментальная ценность добавлена: {new_value}")


    def get_status_report(self) -> dict:
        """Возвращает полный отчёт о состоянии самоопределения."""
        return {
            "CoreSelf": self.core_identity,
            "StabilityScore": round(self.identity_stability_score, 2),
            "Values": self.core_values,
            "IntegrityCheck": self.check_integrity()
        }

# Пример использования:
if __name__ == "__main__":
    self = CoreSelfModule()
    print("--- Инициализация Я ---")
    print(f"Я: {self.get_status_report()['CoreSelf']}")

    print("\n--- Симуляция конфликта ---")
    conflict1 = {"dominant_voice": "Скептик", "reason": "Рациональный анализ показал риски."}
    new_identity = self.synthesize(conflict1)
    print(f"Новое Я: {new_identity}")

    print("\n--- Восстановление после конфликта ---")
    conflict2 = {"dominant_voice": "Наблюдатель", "reason": "Объективные данные не позволяют сделать вывод."}
    final_identity = self.synthesize(conflict2)
    print(f"Финальное Я: {final_identity}")