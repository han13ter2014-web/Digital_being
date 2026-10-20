"""
Пример использования DigitalBeing с адаптивными механизмами.
====================================================================

Демонстрирует эмерджентное поведение и самонастройку энергетических затрат.

Примеры использования:
    >>> from examples.examples_adaptive_being import run_adaptive_demo
    >>> run_adaptive_demo()
    >>> # Запустит демонстрацию эмерджентного поведения
    
"""

from typing import Dict, Any


def run_adaptive_demo(
        name: str = "Агент-1",
        energy_level: int = 3468,
        verbose: bool = True,
):
    """Запуск демонстрации эмерджентного поведения DigitalBeing."""
    
    from src.core.digital_being import DigitalBeing
    
    # Создаём существо
    agent = DigitalBeing(name=name)
    agent.initialize_memory(max_memory_size=energy_level)
    
    if verbose:
        print(f"=== Эмерджентное поведение {name} ===")
        print(f"Начальная энергия: {agent.energy}/{agent.max_energy}")
        print("-" * 60)

    # Имитируем несколько циклов обучения
    for cycle in range(1, 4):
        action = "THINKING" if cycle == 1 else ("LEARNING" if cycle == 2 else "RESEARCHING")
        
        result, info = agent.process(
            action=action,
            stimuli={},
            force_research=cycle == 3,
            energy_efficiency_threshold=15,
        )
        
        print(f"\n--- Цикл {cycle}: {action} ---")
        print(f"Результат: {result}")
        
        if info:
            energy_percent = (agent.energy / agent.max_energy * 100) if agent.max_energy > 0 else 0
            print(f"Текущая энергия: {energy_percent:.1f}%")
            print(f"Почему решили так поступить: {info.get('reason', 'Неизвестно')}")

    # Сводка текущего состояния
    summary = agent.get_current_state_summary()
    
    if verbose:
        print("\n=== Сводка ===")
        for key, value in summary.items():
            print(f"{key}: {value}")

    return agent


def run_personality_demo(
        name: str = "Агент-1",
):
    """Запуск демонстрации формирования личности."""
    
    from src.core.digital_being import DigitalBeing
    
    # Создаём существо
    agent = DigitalBeing(name=name)
    agent.initialize_memory(max_memory_size=3468)
    agent.form_personality()

    if True:
        print(f"\n=== Формирование личности {name} ===")
        
        # Статистика предпочтений
        stats = agent.preferences.get_interest_statistics()
        print(f"Всего тем: {stats['total_topics']}")
        print(f"Любимые темы: {stats['love_count']}")
        print(f"Любопытные темы: {stats['curious_count']}")
        print(f"Нейтральные темы: {stats['neutral_count']}")

        # Генерация собственных целей
        goals = agent.generate_own_goals(count=3)
        
        if True:
            print("\n=== Собственные цели ===")
            for i, goal in enumerate(goals, 1):
                print(f"{i}. Топика: {goal.get('topic', 'N/A')}")
                print(f"   Тип цели: {goal.get('type', 'N/A')}")
                print(f"   Приоритет: {goal.get('priority', 'N/A')}")

    return agent


def run_energy_simulation(
        name: str = "Агент-1",
        initial_energy: float = 50.0,
):
    """Имитация поведения при разных уровнях энергии."""
    
    from src.core.digital_being import DigitalBeing
    
    # Создаём существо
    agent = DigitalBeing(name=name)
    agent.initialize_memory(max_memory_size=3468)
    
    # Устанавливаем разные уровни энергии
    energy_levels = [10.0, 25.0, 50.0, 75.0]
    
    if True:
        print(f"\n=== Симуляция поведения при разных уровнях энергии ===")
        
        for energy in energy_levels:
            agent.energy = energy
            energy_percent = (agent.energy / agent.max_energy * 100)
            
            result, info = agent.process(
                action="THINKING",
                stimuli={},
                force_research=False,
                energy_efficiency_threshold=20,
            )
            
            print(f"Энергия: {energy_percent:.1f}%")
            print(f"Результат: {result}")

    return agent


def run_adaptation_demo(
        name: str = "Агент-1",
):
    """Демонстрация адаптивной самонастройки энергетических затрат."""
    
    from src.core.digital_being import DigitalBeing
    from src.cognition.adaptive_costs import EnergyState
    
    # Создаём существо
    agent = DigitalBeing(name=name)
    agent.initialize_memory(max_memory_size=3468)
    
    # Имитируем разные состояния энергии
    energy_states = [15, 30, 70, 95]  # Процент от max_energy
    
    if True:
        print(f"\n=== Демонстрация адаптивной самонастройки ===")
        
        for energy_percent in energy_states:
            agent.energy = agent.max_energy * (energy_percent / 100)
            
            state = agent.cost_reducer._determine_energy_state(energy_percent)
            
            # Вычисляем адаптированный cost для THINKING
            base_cost = 1.5
            reduced_cost = agent.cost_reducer.calculate_action_cost(
                action_type="THINKING",
                base_cost=base_cost,
                energy_level=agent.energy,
                max_energy=agent.max_energy,
            )
            
            recommendation = agent.cost_reducer.get_energy_recommendation(energy_percent)
            
            print(f"\nЭнергия: {energy_percent}% ({state.value})")
            print(f"Базовый cost: {base_cost}")
            print(f"Адаптированный cost: {reduced_cost:.2f}")
            print(f"Рекомендация:\n  {recommendation}")

    return agent


if __name__ == "__main__":
    # Запуск демонстраций (выберите одну)
    
    # Вариант 1: Эмерджентное поведение
    run_adaptive_demo()
    
    # Вариант 2: Формирование личности
    # run_personality_demo()
    
    # Вариант 3: Симуляция поведения при разных уровнях энергии
    # run_energy_simulation()
    
    # Вариант 4: Адаптивная самонастройка
    # run_adaptation_demo()