import random
from config.simulation_config import LR_CONFIG
# Предполагаем, что нам понадобятся некоторые базовые компоненты из ядра
# from src.cognition.mental_models import MentalModel 


class PrimitiveTriggerSystem:
    """
    Система, имитирующая примитивные инстинкты и эмоциональный рефлекс. 
    Работает как "шум" или "импульс", который может отвлекать от рационального пути (декомпозиция).
    Этот модуль не должен быть полностью логичным; он должен быть *эмоционально* реактивным.
    """

    def __init__(self, agent_system):
        self.agent = agent_system
        self.trigger_frequency = LR_CONFIG.PRIMITIVE_TRIGGER_RATE # Определяем частоту срабатывания
        self._last_triggered_cycle = 0
        # Эмоциональные состояния, которые могут стать триггерами (вместо ментальных моделей)
        self.base_emotions = ["страх", "радость", "гнев", "удивление", "спокойствие"]

    def check_for_trigger(self):
        """Проверяет, должно ли сработать примитивное инстинктивное событие."""
        current_cycle = self.agent.cycle_count
        if current_cycle < self._last_triggered_cycle + self.trigger_frequency:
            return None # Слишком рано
        
        # Определяем случайный триггер, основанный на текущем эмоциональном состоянии (если оно есть) или просто случайно
        emotion = random.choice(self.base_emotions)
        self._last_triggered_cycle = current_cycle
        
        trigger = {
            "type": "primitive",
            "emotion": emotion,
            "intensity": random.uniform(0.5, 1.0), # Насколько сильно это влияет на принятие решения
            "raw_input": f"[Триггер: Эмоциональный всплеск ({emotion})] - Инстинкт требует реакции."
        }
        return trigger

    def process_trigger(self, trigger_data: dict):
        """
        Обрабатывает триггер. Это должно вызвать прерывание рационального потока и 
        переключить внимание на базовое эмоциональное переживание.
        Возвращает сообщение или инструкцию для следующего шага.
        """
        emotion = trigger_data["emotion"]
        intensity = trigger_data["intensity"]

        # Логика: Эмоция > Уровень внимания -> Примитивное действие
        if intensity * 1.2 > self.agent._action_costs["default"]: # Если триггер сильнее, чем базовые затраты
            self.agent.energy -= (self.agent._get_adaptive_cost("default") + int(intensity * 3))
            
            # Выход из рационального потока и возврат к эмоциональному ответу
            if emotion == "страх":
                return f"!!! Эмоциональный сбой: Чувство {emotion}. Требуется немедленная пауза и поиск безопасности. (Импульс)"
            elif emotion == "радость":
                return f"*** Всплеск {emotion}! Это очень хорошо! Нужно поделиться этим ощущением и закрепить положительный опыт. (Инстинкт) ***"
            elif emotion == "гнев":
                return f"!! Прерывание: Сильный импульс гнева по поводу текущей ситуации. Требуется немедленная перефокусировка внимания. (Эмоциональная реакция)"
            else: # Удивление, Спокойствие - могут быть просто замечаниями
                 return f"[Инстинкт] Я ощущаю {emotion}. Это заставляет меня задуматься о чем-то более базовом."

        return None
