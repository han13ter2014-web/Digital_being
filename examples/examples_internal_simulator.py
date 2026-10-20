"""
Демонстрация внутренней симуляции для автономного обучения ИИ.

Агент может моделировать последствия действий БЕЗ их реального выполнения,
находить похожий опыт в памяти для аналогий и прогнозировать результаты.
"""

import sys
import io
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cognition.internal_simulator import InternalSimulator


def demo_basic_simulation():
    """Базовая демонстрация симуляции."""
    print("\n" + "=" * 60)
    print("  ДЕМО 1: Базовая внутренняя симуляция")
    print("=" * 60)
    
    sim = InternalSimulator("Alpha")
    
    # Сначала агент получает реальный опыт
    print(f"\n  Фаза 1: Сбор реального опыта (5 действий)")
    
    real_experiences = [
        ("analyze_data", "обработка числовых данных", "корректный результат", True),
        ("analyze_data", "обработка текстовых данных", "частично верно", True),
        ("analyze_data", "обработка изображений", "ошибка форматирования", False),
        ("visualize_data", "визуализация графиков", "понятная диаграмма", True),
        ("visualize_data", "визуализация таблиц", "неудачное отображение", False),
    ]
    
    for action, context, outcome, success in real_experiences:
        sim.learn_from_outcome(action, context, outcome, success)
        print(f"     [{action}] {'OK' if success else 'FAIL'} -> {outcome[:30]}")
    
    # Теперь симулирует новое действие
    print(f"\n  Фаза 2: Симуляция нового действия 'analyze_data'")
    
    readiness = sim.get_simulation_readiness()
    print(f"     Готов к симуляции: {'Да' if readiness['ready_for_simulation'] else 'Нет'}")
    print(f"     Реальных событий: {readiness['total_real_events']}")
    
    # Симулирует результат для нового контекста
    simulation = sim.simulate_outcome(
        "analyze_data",
        {},
        "анализ больших данных"
    )
    
    print(f"\n     Предсказание для 'analyze_data' на контекст 'анализ больших данных':")
    print(f"     Исход: {simulation.predicted_outcome[:60]}")
    print(f"     Уверенность: {simulation.confidence:.0%}")
    
    if simulation.benefits:
        print(f"     Потенциальные выгоды:")
        for b in simulation.benefits[:2]:
            print(f"       + {b}")
    
    if simulation.risks:
        print(f"     Потенциальные риски:")
        for r in simulation.risks[:2]:
            print(f"       - {r}")


def demo_mental_experiment():
    """Демонстрация мысленного эксперимента."""
    print("\n" + "=" * 60)
    print("  ДЕМО 2: Мысленный эксперимент с вариациями")
    print("=" * 60)
    
    sim = InternalSimulator("Beta")
    
    # Заполняет опыт
    experiences = [
        ("negotiate_price", "торг за дешевый товар", "хорошая сделка", True),
        ("negotiate_price", "торг за дорогой товар", "слишком дорого", False),
        ("negotiate_price", "торг за услугу", "скидка получена", True),
        ("direct_buy", "прямая покупка товара", "быстро но дорого", True),
        ("direct_buy", "прямая покупка услуги", "без наценки", True),
    ]
    
    for action, context, outcome, success in experiences:
        sim.learn_from_outcome(action, context, outcome, success)
    
    print(f"\n  Запуск мысленного эксперимента 'negotiate_price':")
    result = sim.run_mental_experiment("negotiate_price", "торг за подарок", iterations=5)
    
    print(f"     Симуляций: {result['iterations']}")
    print(f"     Предсказанный успех: {result['simulated_success_rate']:.0%}")
    print(f"     Общая уверенность: {result['confidence']:.0%}")
    print(f"     Рекомендация: {result['recommendation']}")


def demo_strategy_comparison():
    """Демонстрация сравнения стратегий."""
    print("\n" + "=" * 60)
    print("  ДЕМО 3: Сравнение стратегий симуляцией")
    print("=" * 60)
    
    sim = InternalSimulator("Gamma")
    
    # Заполняет опыт для сравнения
    experiences = [
        ("search_online", "поиск информации в интернете", "нашел ответ быстро", True),
        ("search_online", "поиск данных в библиотеке", "долго но точно", True),
        ("ask_expert", "спросить у эксперта", "получил точный ответ", True),
        ("ask_expert", "спросить у новичка", "не помог", False),
        ("trial_error", "методом проб и ошибок", "нашел но с ошибками", True),
        ("trial_error", "методом проб и ошибок", "много ошибся", False),
    ]
    
    for action, context, outcome, success in experiences:
        sim.learn_from_outcome(action, context, outcome, success)
    
    print(f"\n  Задача: найти ответ на сложный вопрос")
    strategies = ["search_online", "ask_expert", "trial_error"]
    
    print(f"\n  Сравнение стратегий:")
    ranked = sim.compare_strategies(strategies, "поиск ответа")
    
    for i, r in enumerate(ranked, 1):
        bar_len = int(r["simulated_success_rate"] * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        print(f"     {i}. {r['action']:<15} успех={bar} {r['simulated_success_rate']:.0%}")
        if r.get("best_prediction"):
            pred = r["best_prediction"]
            print(f"       Лучшее предсказание: {pred.get('predicted_outcome', 'N/A')[:40]}")


def demo_learning_from_outcome():
    """Демонстрация обучения на исходе."""
    print("\n" + "=" * 60)
    print("  ДЕМО 4: Обучение из реального опыта и улучшение симуляции")
    print("=" * 60)
    
    sim = InternalSimulator("Delta")
    
    # Фаза 1: Сначала только симуляция (без опыта)
    print(f"\n  Фаза 1: Симуляция БЕЗ опыта")
    
    pred_before = sim.simulate_outcome("analyze_data", {}, "анализ текста")
    print(f"     Предсказание до опыта: {pred_before.predicted_outcome[:50]}")
    print(f"     Уверенность: {pred_before.confidence:.0%}")
    
    # Фаза 2: Добавляет опыт
    print(f"\n  Фаза 2: Сбор опыта (7 действий)")
    
    experiences = [
        ("analyze_data", "анализ текста Python", "корректно обработал", True),
        ("analyze_data", "анализ данных numpy", "корректно посчитал", True),
        ("analyze_data", "анализ изображений PIL", "ошибка формата", False),
        ("analyze_data", "анализ аудио ffmpeg", "частично верно", True),
        ("process_input", "ввод текстовый", "обрабатывается", True),
        ("process_input", "ввод числовой", "преобразовано", True),
        ("process_input", "ввод бинарный", "не распознано", False),
    ]
    
    for action, context, outcome, success in experiences:
        sim.learn_from_outcome(action, context, outcome, success)
    
    # Фаза 3: Симуляция с опытом
    print(f"\n  Фаза 3: Симуляция ПОСЛЕ получения опыта")
    
    pred_after = sim.simulate_outcome("analyze_data", {}, "анализ большого текста")
    print(f"     Предсказание после опыта: {pred_after.predicted_outcome[:60]}")
    print(f"     Уверенность: {pred_after.confidence:.0%}")
    
    if pred_after.benefits:
        print(f"     Выгоды:")
        for b in pred_after.benefits[:2]:
            print(f"       + {b}")
    
    # Сравнивает готовность
    readiness = sim.get_simulation_readiness()
    print(f"\n  Готовность симуляции:")
    print(f"     Реальных событий: {readiness['total_real_events']}")
    print(f"     Уникальных действий: {readiness['unique_actions']}")
    print(f"     Каузальных правил: {readiness['causal_rules_count']}")


def demo_prediction_accuracy():
    """Демонстрация отслеживания точности предсказаний."""
    print("\n" + "=" * 60)
    print("  ДЕМО 5: Точность предсказаний и коррекция")
    print("=" * 60)
    
    sim = InternalSimulator("Epsilon")
    
    # Добавляет опыт
    experiences = [
        ("code_write", "писать код Python", "код работал", True),
        ("code_write", "писать код C++", "были ошибки", False),
        ("code_review", "ревью кода Python", "нашел баги", True),
        ("code_review", "ревью кода Java", "пропустил баги", False),
        ("debug_code", "отладка Python", "исправил", True),
    ]
    
    for action, context, outcome, success in experiences:
        sim.learn_from_outcome(action, context, outcome, success)
    
    # Проверяет предсказания и сверяет с реальностью
    print(f"\n  Проверка точности предсказаний:")
    
    test_actions = [
        ("code_write", "писать код JavaScript"),
        ("code_review", "ревью кода Python"),
        ("debug_code", "отладка C++"),
    ]
    
    for action, context in test_actions:
        sim_pred = sim.simulate_outcome(action, {}, context)
        
        # Симулирует реальный исход (для демонстрации)
        actual_success = action == "code_write" and "JavaScript" in context
        
        if sim_pred.predicted_outcome != "неопределенно (мало опыта...)":
            print(f"\n     Действие: {action} ({context[:20]}...)")
            print(f"       Предсказание: {sim_pred.predicted_outcome[:45]}...")
            print(f"       Уверенность: {sim_pred.confidence:.0%}")


def demo_full_learning_cycle():
    """Полный цикл автономного обучения через симуляцию."""
    print("\n" + "=" * 60)
    print("  ДЕМО 6: Полный цикл обучения")
    print("=" * 60)
    
    sim = InternalSimulator("FullLife")
    
    print(f"\n  [Начало] Нет опыта:")
    readiness = sim.get_simulation_readiness()
    print(f"     Готовность: {'OK' if readiness['ready_for_simulation'] else 'НЕ ГОТОВ'}")
    
    # Фаза сбора опыта
    print(f"\n  [Фаза 1] Сбор опыта (20 действий)")
    
    all_actions = [
        ("solve_math", "решить уравнение", "правильно", True, 5),
        ("solve_math", "решить систему", "ошибка вычисления", False, 3),
        ("write_code", "написать функцию", "работает", True, 4),
        ("write_code", "написать класс", "баги в методах", False, 2),
        ("test_unit", "тест модуля A", "все прошло", True, 3),
        ("test_unit", "тест модуля B", "2 падения", False, 1),
    ]
    
    for action, context, outcome, success, count in all_actions:
        for _ in range(count):
            sim.learn_from_outcome(action, context, f"{outcome}_{count}", success)
    
    print(f"     Собрано {sim.memory.real_events} событий")
    
    # Фаза симуляции нового
    print(f"\n  [Фаза 2] Симуляция НОВЫХ решений")
    
    new_challenges = [
        ("solve_math", "решить интеграл"),
        ("write_code", "написать API"),
        ("test_unit", "тест интеграции"),
    ]
    
    for action, context in new_challenges:
        result = sim.run_mental_experiment(action, context, iterations=3)
        print(f"\n     Задача: '{context}'")
        print(f"     Действие: {action}")
        print(f"     Предсказанный успех: {result['simulated_success_rate']:.0%}")
        print(f"     Рекомендация: {result['recommendation']}")
    
    # Фаза выбора лучшей стратегии
    print(f"\n  [Фаза 3] Выбор стратегии для 'написать программу'")
    
    strategies = ["write_code", "solve_math", "test_unit"]
    ranked = sim.compare_strategies(strategies, "написание программы")
    
    best = ranked[0] if ranked else None
    if best:
        print(f"     Лучшая стратегия: {best['action']}")
        print(f"     Предсказанный успех: {best['simulated_success_rate']:.0%}")
    
    # Финальный статус
    print(f"\n  [Итог] цикла обучения:")
    status = sim.get_status()
    print(f"     Реальных событий: {status['simulation_readiness']['total_real_events']}")
    print(f"     Каузальных правил: {status['simulation_readiness']['causal_rules_count']}")


def main():
    """Запуск всех демонстраций."""
    print("\n" + "=" * 60)
    print("  ВНУТРЕННЯЯ СИМУЛЯЦИЯ - Автономное обучение")
    print("  Самоэволюционирующийся ИИ - Компонент 4")
    print("=" * 60)
    
    try:
        demo_basic_simulation()
        demo_mental_experiment()
        demo_strategy_comparison()
        demo_learning_from_outcome()
        demo_prediction_accuracy()
        demo_full_learning_cycle()
        
        print("\n" + "=" * 60)
        print("  Все демонстрации завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nОшибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()