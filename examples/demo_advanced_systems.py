"""Пример интеграции всех новых систем в DigitalBeing."""

import os
import sys
import io

# Fix encoding on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.agent import DigitalBeing
from src.memory.long_term_memory import LongTermMemory
from src.cognition.multi_goal_manager import MultiTaskGoalManager, GoalState
from src.cognition.agent_cooperation import cooperation_hub, MessageType
from src.evolution.self_evolution_analyzer import SelfEvolutionAnalyzer
import time
from datetime import datetime


def example_long_term_memory():
    """Демонстрирует долгосрочную память с decay."""
    print("\n" + "="*60)
    print("🧠 ДЕМО: ДОЛГОСРОЧНАЯ ПАМЯТЬ С DECAY")
    print("="*60)

    memory = LongTermMemory("TestAgent", decay_rate=0.95)

    # Сохраняем воспоминания
    memory.store(
        content="Встретил интересную концепцию о трансформерах в NLP",
        importance=0.8,
        context="learning",
        memory_type="episodic"
    )

    memory.store(
        content="Пользователь объяснил как работает механизм внимания",
        importance=0.9,
        context="user_interaction",
        memory_type="semantic"
    )

    memory.store(
        content="Обнаружил, что гипотеза о градиентном спуске была неправильная",
        importance=0.7,
        context="self_correction",
        memory_type="procedural"
    )

    # Попытаемся вспомнить
    print("\n📝 Сохранено 3 воспоминания")
    print("\n🔍 Поиск 'трансформеры':")
    results = memory.recall("трансформеры", max_results=5)
    for i, result in enumerate(results, 1):
        print(f"  {i}. {result['content'][:50]}... (Сила: {result['strength']:.0%})")

    # Статистика
    stats = memory.get_memory_stats()
    print(f"\n📊 Статистика памяти:")
    print(f"  Краткосрочная: {stats['short_term_count']}")
    print(f"  Долгосрочная: {stats['long_term_count']}")
    print(f"  Эпизодическая: {stats['episodic_count']}")

    # Запускаем decay
    memory.trigger_decay()
    print(f"\n⏰ После decay-процесса:")
    print(f"  Консолидировано: {stats['consolidation_count']}")
    print(f"  Забыто: {stats['decay_events']}")

    memory.save()


def example_multi_goal_management():
    """Демонстрирует многозадачность целей."""
    print("\n" + "="*60)
    print("🎯 ДЕМО: МНОГОЗАДАЧНОСТЬ ЦЕЛЕЙ")
    print("="*60)

    manager = MultiTaskGoalManager(max_active_goals=3)

    # Добавляем цели
    goal1 = manager.add_goal("Изучить Python", "Основы языка", difficulty=2, priority=3)
    goal2 = manager.add_goal("Понять НЛП", "Natural Language Processing", difficulty=3, priority=5)
    goal3 = manager.add_goal("Написать статью", "О машинном обучении", difficulty=2, priority=2)
    goal4 = manager.add_goal("Сотрудничать с агентом", "Совместный проект", difficulty=2, priority=3)

    # Устанавливаем зависимость
    goal4.blocked_by.append(goal1.id)

    print(f"\n✅ Добавлено 4 цели")
    print(manager.visualize_goals())

    # Выбираем цели для первого цикла
    cycle1_goals = manager.select_goals_for_cycle(available_energy=100)
    print(f"\n🔥 Выбраны для 1-го цикла: {len(cycle1_goals)} целей")
    for goal in cycle1_goals:
        print(f"  • {goal.title} (приоритет: {goal.priority})")

    # Обновляем прогресс
    for goal in cycle1_goals:
        goal.cycles_spent += 1
        manager.update_goal_progress(goal.id, 0.25)

    # Завершаем первую цель
    manager.complete_goal(goal1.id)
    print(f"\n✨ Завершена цель: {goal1.title}")

    # Проверяем что goal4 теперь доступна
    available = manager.get_available_goals_to_activate()
    print(f"\nОзвобождено целей для активации: {len(available)}")
    for goal in available:
        print(f"  • {goal.title}")

    # Статистика
    summary = manager.get_goals_summary()
    print(f"\n📊 Сводка целей:")
    print(f"  Всего: {summary['total_goals']}")
    print(f"  Активных: {summary['active_goals']}")
    print(f"  Завершено: {summary['completed_count']}")


def example_agent_cooperation():
    """Демонстрирует кооперацию агентов."""
    print("\n" + "="*60)
    print("🤝 ДЕМО: КООПЕРАЦИЯ МЕЖДУ АГЕНТАМИ")
    print("="*60)

    # Создаём 3 агента (упрощенных)
    class SimpleAgent:
        def __init__(self, name):
            self.name = name
            self.knowledge = {}

    agent1 = SimpleAgent("Alpha")
    agent2 = SimpleAgent("Beta")
    agent3 = SimpleAgent("Gamma")

    # Регистрируем в системе
    cooperation_hub.register_agent(agent1)
    cooperation_hub.register_agent(agent2)
    cooperation_hub.register_agent(agent3)

    print(f"\n✅ Зарегистрировано {len(cooperation_hub.agents)} агентов")

    # Создаём группу сотрудничества
    cooperation_hub.create_collaboration_group("nlp_team", ["Alpha", "Beta"])
    print(f"✨ Создана группа 'nlp_team' для Alpha и Beta")

    # Alpha делится знанием с Beta
    knowledge_to_share = {
        "concept": "трансформеры",
        "definition": "Архитектура нейросети на основе внимания",
        "reliability": 0.85
    }

    cooperation_hub.share_knowledge_in_group(
        group_id="nlp_team",
        agent_id="Alpha",
        topic="NLP",
        knowledge=knowledge_to_share
    )
    print(f"\n📚 Alpha поделилась знанием о NLP с Beta")

    # Beta ищет знание
    query_result = cooperation_hub.query_knowledge("Beta", "NLP")
    if query_result['found']:
        print(f"✅ Beta нашла знание по теме 'NLP'")
        print(f"  Источники: {', '.join(query_result['sources'])}")

    # Alpha просит помощь у Gamma
    cooperation_hub.request_help(
        from_agent_id="Alpha",
        to_agent_id="Gamma",
        problem_description="Не могу понять как работает backpropagation",
        urgency=3
    )
    print(f"\n🆘 Alpha попросила помощь у Gamma (приоритет: 3)")

    # Статистика
    stats = cooperation_hub.get_agent_statistics("Alpha")
    print(f"\n📊 Статистика Alpha:")
    print(f"  Отправлено сообщений: {stats['messages_sent']}")
    print(f"  Получено сообщений: {stats['messages_received']}")
    print(f"  Репутация: {stats['avg_reputation']:.0%}")

    print(cooperation_hub.visualize_network())

    cooperation_hub.save_state()


def example_self_evolution():
    """Демонстрирует самоэволюцию."""
    print("\n" + "="*60)
    print("🔄 ДЕМО: САМОЭВОЛЮЦИЯ И САМОУЛУЧШЕНИЕ")
    print("="*60)

    # Создаём тестовый агент
    agent = DigitalBeing("SelfEvolving")

    # Создаём анализатор
    analyzer = SelfEvolutionAnalyzer(agent)

    # Анализируем производительность
    performance = analyzer.analyze_performance()
    print(f"\n📈 Текущая производительность:")
    print(f"  Интеллект: {performance['intelligence']}")
    print(f"  Энергоэффективность: {performance['energy_efficiency']:.0%}")
    print(f"  Завершение целей: {performance['goal_completion_rate']:.0%}")
    print(f"  Скорость обучения: {performance['learning_speed']:.0%}")
    print(f"  Качество концепций: {performance['concepts_quality']:.0%}")
    print(f"  ОБЩИЙ СКОР: {performance['overall_score']:.0%}")

    # Ищем улучшения
    improvements = analyzer.identify_improvements()
    print(f"\n🔍 Найдено возможностей для улучшения: {len(improvements)}")
    for i, improvement in enumerate(improvements, 1):
        print(f"\n  {i}. {improvement['category']} ({improvement['severity']})")
        print(f"     {improvement['description']}")

    # Генерируем предложения и применяем
    if improvements:
        suggestion = analyzer.generate_code_suggestion(improvements[0])
        if suggestion:
            print(f"\n💡 Предложенное изменение:")
            print(f"  Модуль: {suggestion['module']}")
            print(f"  Текущее: {suggestion['current']}")
            print(f"  Предложение: {suggestion['suggested']}")
            print(f"  Ожидаемое улучшение: +{suggestion['estimated_impact']:.0%}")

            # Применяем
            if analyzer.apply_self_modification(suggestion):
                print(f"  ✅ Изменение успешно применено!")

    # Генерируем отчет
    report = analyzer.generate_self_report()
    print(f"\n📋 ОТЧЕТ О САМОАНАЛИЗЕ:")
    print(f"  Рекомендации:")
    for rec in report['recommendations']:
        print(f"    • {rec}")

    analyzer._save_history()


def main():
    """Запускает все демо."""
    print("\n" + "="*70)
    print("  🤖 ДЕМОНСТРАЦИЯ: РАСШИРЕННЫЕ СИСТЕМЫ ЦИФРОВОГО СУЩЕСТВА")
    print("="*70)

    try:
        example_long_term_memory()
        example_multi_goal_management()
        example_agent_cooperation()
        example_self_evolution()

        print("\n" + "="*70)
        print("  ✅ ВСЕ ДЕМО УСПЕШНО ЗАВЕРШЕНЫ!")
        print("="*70)
        print("\nТеперь вы можете:")
        print("  1. Использовать долгосрочную память в DigitalBeing")
        print("  2. Управлять несколькими целями одновременно")
        print("  3. Запустить кооперацию между несколькими агентами")
        print("  4. Позволить агентам анализировать и улучшать себя")
        print("\n")

    except Exception as e:
        print(f"\n❌ Ошибка при выполнении демо: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
