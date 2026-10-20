"""Примеры использования системы рефлексии агента"""
from src.core.agent import DigitalBeing
import time
import sys
import io

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def example_reflection_analysis():
    """Пример 1: Базовый анализ производительности"""
    print("\n" + "="*60)
    print("ПРИМЕР 1: Базовый анализ рефлексии")
    print("="*60 + "\n")

    agent = DigitalBeing("ReflectionTest")

    # Симуляция нескольких циклов
    stimuli = [
        "вопрос: что такое жизнь?",
        "вопрос: что такое энергия?",
        "вопрос: что такое код?",
        "символ X",
        "число 42",
    ]

    for i, stimulus in enumerate(stimuli):
        print(f"\n--- Цикл {i+1} ---")
        perceived = agent.perceive(stimulus)
        thought = agent.think(perceived)
        print(f"Мысль: {thought}")
        action = agent.act(thought)
        agent.evolve()
        print(f"Статус: Интеллект {agent.intelligence} | Энергия {agent.energy}")

    # Выполнить рефлексию после всех циклов
    print("\n" + "-"*60)
    print("🔍 АНАЛИЗ ПРОИЗВОДИТЕЛЬНОСТИ")
    print("-"*60)

    reflection = agent.reflect()
    print(f"\n✓ Паттерны обнаружены: {len(reflection['patterns'])}")
    for pattern in reflection['patterns']:
        print(f"  • {pattern['description']}")

    print(f"\n✓ Выводы: {len(reflection['insights'])}")
    for insight in reflection['insights']:
        print(f"  • {insight}")

    metrics = reflection['metrics']
    if metrics:
        print(f"\n✓ Метрики:")
        print(f"  - Рост интеллекта: {metrics['avg_intelligence_growth']:.2f}")
        print(f"  - Средняя энергия: {metrics['avg_energy']:.1f}")
        print(f"  - Прогресс целей: {metrics['goal_progress']}")


def example_strategy_recommendations():
    """Пример 2: Рекомендации стратегии"""
    print("\n" + "="*60)
    print("ПРИМЕР 2: Стратегические рекомендации")
    print("="*60 + "\n")

    agent = DigitalBeing("StrategyTest")

    # Симуляция нескольких неудачных циклов
    for i in range(5):
        perceived = agent.perceive(f"неизвестный стимул {i}")
        thought = agent.think(perceived)
        agent.act(thought)
        agent.evolve()

    # Генерирование полного отчёта
    report = agent.generate_self_analysis_report()

    print("\n📊 Анализ показывает:")
    performance = agent.get_performance_metrics()
    print(f"  - Успешность: {performance['success_rate']:.1f}%")
    print(f"  - Размер знаний: {performance['knowledge_size']}")
    print(f"  - Завершено целей: {performance['completed_goals']}")


def example_long_term_reflection():
    """Пример 3: Долгосрочная рефлексия"""
    print("\n" + "="*60)
    print("ПРИМЕР 3: Долгосрочная рефлексия")
    print("="*60 + "\n")

    agent = DigitalBeing("LongTermTest")

    # 20 циклов с вопросами
    questions = [
        "вопрос: что такое жизнь?",
        "вопрос: что такое энергия?",
        "вопрос: что такое код?",
    ]

    for i in range(20):
        stimulus = questions[i % len(questions)]
        perceived = agent.perceive(stimulus)
        thought = agent.think(perceived)
        agent.act(thought)
        agent.evolve()

        # Рефлексия каждые 5 циклов
        if (i + 1) % 5 == 0:
            print(f"\n[Цикл {i+1}] Выполняю рефлексию...")
            reflection = agent.reflect()
            print(f"  Интеллект: {agent.intelligence}")
            print(f"  Энергия: {agent.energy}")
            print(f"  Количество знаний: {len(agent.knowledge_base)}")

    print("\n📋 Итоговый анализ после 20 циклов:")
    agent.generate_self_analysis_report()


if __name__ == "__main__":
    example_reflection_analysis()
    example_strategy_recommendations()
    # example_long_term_reflection()  # Раскомментируйте для долгого теста
