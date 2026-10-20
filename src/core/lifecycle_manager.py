import random
from datetime import datetime
from src.cognition.reflection_engine import ReflectionEngine
from config.simulation_config import LR_CONFIG

class LifeCycleManager:
    """
    Менеджер жизненного цикла агента. Отвечает за отслеживание ресурсов (Энергия), 
    статуса (Сон/Бодрствование) и проведение фоновых процессов регенерации.
    Работает как "биометрика" для обеспечения бессмертия системы.
    """

    def __init__(self, agent_system):
        """
        Инициализация менеджера с передачей ссылки на ядро агента (DigitalBeing).
        agent_system - это объект DigitalBeing.
        """
        self.agent = agent_system
        # Инициализируем состояние:
        # Основная энергия хранится в self.energy внутри самого агента
        self.rest_cycle_counter = 0

    def check_vital_systems(self):
        """
        Проверяет витальные показатели и определяет, должен ли агент войти в режим сна.
        Вызывается при каждом цикле мышления (think()).
        Возвращает True, если произошло значимое изменение состояния (например, переход в сон).
        """
        current_energy = self.agent.energy
        changed = False

        # Условие перехода в сон: ниже порога критической энергии и не во сне
        if current_energy < LR_CONFIG.ENERGY_CRITICAL_THRESHOLD and not self.agent.is_dormant:
            self.agent.is_dormant = True
            self.rest_cycle_counter = 0
            print(f"🚨 ВНИМАНИЕ! Энергия критически низка ({current_energy:.0f}). Агент переходит в режим Сна (Низкая Активность).")
            changed = True
        # Условие пробуждения: достижение высокой энергии или длительный сон
        elif current_energy >= LR_CONFIG.ENERGY_MAX * 0.8 and self.agent.is_dormant:
             self.agent.is_dormant = False
             self.rest_cycle_counter = 0
             print(f"✅ Агент пробудился! Энергия {current_energy:.0f}. Возобновление активности.")
             changed = True

        return changed

    def run_sleep_cycle(self):
        """Обрабатывает процесс сна (регенерация и консолидация)."""
        if not self.agent.is_dormant:
            return False # Не спать, ничего не делать

        self.rest_cycle_counter += 1
        print("💤 Агент в режиме Сна (Регенерация)...")

        # Фаза регенерации энергии (усиленный процесс во сне)
        regen_amount = LR_CONFIG.ENERGY_REGEN_PER_CYCLE * 2
        self.agent.energy = min(LR_CONFIG.ENERGY_MAX, self.agent.energy + regen_amount)
        
        # Фаза консолидации памяти (как сон в человеке): пассивное обновление и очистка
        if self.rest_cycle_counter % 5 == 0:
            self._consolidate_memory()

        # Пробуждение после достижения порога энергии или длительного цикла сна
        if self.rest_cycle_counter >= LR_CONFIG.PAUSE_DURATION_SECONDS or self.agent.energy >= LR_CONFIG.ENERGY_MAX * 0.9:
            self.agent.is_dormant = False
            self.rest_cycle_counter = 0
            print(f"✅ Агент пробудился! Энергия {self.agent.energy:.0f}. Возобновление активности.")
            return True
        return False

    def _consolidate_memory(self):
        """Симуляция работы сна: укрепляет связи между концепциями и удаляет противоречия."""
        # Укрепляем связи (увеличиваем уверенность)
        for node in self.agent.mental_models.concepts.values():
            node.confidence = min(1.0, node.confidence + 0.05)

        # Активный поиск противоречий между самими собой и базовой линией
        self.agent._detect_contradiction("Консолидация", "Я - стабильная система.")


    def process_passive_cycle(self):
        """
        Главный метод для цикла, когда агент не выполняет активные действия.
        Отвечает за пассивное течение времени и поддержание жизни.
        """
        # 1. Обновляем счетчики
        self.agent.cycle_count += 1

        # 2. Проверка жизненных систем
        self.check_vital_systems()
        if self.agent.is_dormant:
            self.run_sleep_cycle()
            return False # Активности нет, процесс был пассивным

        # 3. Базовая регенерация энергии (даже если бодрствует)
        self.agent.energy += LR_CONFIG.ENERGY_REGEN_PER_CYCLE
        
        # 4. Выполнение фоновых процессов
        self.agent.perform_forgetting()

        return True
