"""Пример использования расширенного агента с полной интеграцией всех систем."""

import os
import sys
import io

# Fix encoding on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.agent import DigitalBeing
from src.core.extended_agent import extend_agent
from src.cognition.agent_cooperation import cooperation_hub


def simulate_extended_agent_lifecycle(num_cycles: int = 100):
    """Симулирует жизнь расширенного агента."""

    # Создаём агента
    agent = DigitalBeing("Extended_Alpha")

    # Расширяем его системами
    extended = extend_agent(agent)

    print(f"\n{'='*70}")
    print(f"  🚀 ЗАПУСК РАСШИРЕННОГО АГЕНТА: {agent.name}")
    print(f"{'='*70}\n")

    # Симуляция циклов жизни
    for cycle in range(1, num_cycles + 1):
        # === ВОСПРИЯТИЕ И ПАМЯТЬ ===
        stimuli_pool = [
            "Что такое трансформеры?",
            "Как работает механизм внимания?",
            "Объясни backpropagation",
            "Какие бывают оптимизаторы?",
            "Расскажи о регуляризации",
        ]

        import random
        stimulus = random.choice(stimuli_pool)
        perceived = extended.perceive_and_remember(stimulus, importance=0.6)

        # === МЫШЛЕНИЕ С ВОСПОМИНАНИЯМИ ===
        thought = extended.think_with_memory_recall(stimulus)

        # === РАБОТА НАД ЦЕЛЯМИ ===
        active_goals = extended.select_and_work_on_goals()

        # === ОБРАБОТКА СООБЩЕНИЙ ОТ ДРУГИХ АГЕНТОВ ===
        extended.process_cooperation_messages()

        # === ДЕЙСТВИЕ ===
        action = agent.act(thought)

        # === ЭВОЛЮЦИЯ ===
        agent.evolve()

        # === ПЕРИОДИЧЕСКАЯ КОНСОЛИДАЦИЯ ПАМЯТИ ===
        if cycle % 20 == 0:
            mem_stats = extended.trigger_memory_consolidation()
            if mem_stats['consolidations'] > 0 or mem_stats['forgotten'] > 0:
                print(f"  🧠 [{cycle}] Консолидировано: {mem_stats['consolidations']}, "
                      f"Забыто: {mem_stats['forgotten']}")

        # === ПЕРИОДИЧЕСКИЙ САМОАНАЛИЗ ===
        if cycle % 30 == 0:
            analysis = extended.perform_self_analysis()
            if analysis['improvements_applied'] > 0:
                print(f"  🔄 [{cycle}] Самоулучшение! Применено: {analysis['improvements_applied']} "
                      f"(скор: {analysis['overall_score']:.0%})")

        # === ВЫВОД СТАТУСА ===
        if cycle % 25 == 0:
            print(f"\n  📍 Цикл {cycle}/{num_cycles}")
            print(f"     Энергия: {agent.energy:.0f} | Интеллект: {agent.intelligence}")
            print(f"     Активных целей: {len(active_goals)} | Памяти: "
                  f"{extended.long_term_memory.get_memory_stats()['total_memories']}")

        # === СОХРАНЕНИЕ СОСТОЯНИЯ ===
        if cycle % 50 == 0:
            extended.save_all_systems()
            print(f"  💾 [{cycle}] Все системы сохранены")

    print(f"\n{'='*70}")
    print(f"  ✅ СИМУЛЯЦИЯ ЗАВЕРШЕНА ({num_cycles} циклов)")
    print(f"{'='*70}")

    # Финальный статус
    extended.print_status()

    return extended


def simulate_multi_agent_cooperation():
    """Симулирует кооперацию между несколькими агентами."""

    print(f"\n{'='*70}")
    print(f"  👥 СИМУЛЯЦИЯ КООПЕРАЦИИ МЕЖДУ АГЕНТАМИ")
    print(f"{'='*70}\n")

    # Создаём двух агентов
    agent_alpha = DigitalBeing("Coop_Alpha")
    agent_beta = DigitalBeing("Coop_Beta")

    # Расширяем их
    extended_alpha = extend_agent(agent_alpha)
    extended_beta = extend_agent(agent_beta)

    # === Фаза 1: Обмен знаниями ===
    print("📚 ФАЗА 1: Обмен знаниями\n")

    knowledge_alpha = {
        "topic": "трансформеры",
        "definition": "Архитектура на основе механизма внимания (Self-Attention)",
        "reliability": 0.85,
        "examples": ["BERT", "GPT", "T5"]
    }

    extended_alpha.cooperate_with_agent(
        other_agent_name="Coop_Beta",
        knowledge_topic="трансформеры",
        knowledge=knowledge_alpha
    )

    print(f"✅ Alpha поделилась знанием о трансформерах с Beta")

    # Beta получает знание
    extended_beta.process_cooperation_messages()
    print(f"✅ Beta получила знание и интегрировала в память\n")

    # === Фаза 2: Запрос помощи ===
    print("🆘 ФАЗА 2: Запрос помощи\n")

    extended_beta.cooperate_with_agent(
        other_agent_name="Coop_Alpha",
        knowledge_topic="backpropagation",
        knowledge={},
        ask_for_help=True
    )

    print(f"✅ Beta попросила помощь у Alpha")
    extended_alpha.process_cooperation_messages()
    print(f"✅ Alpha получила запрос\n")

    # === Фаза 3: Статистика ===
    print("📊 ФАЗА 3: Статистика кооперации\n")

    stats_alpha = cooperation_hub.get_agent_statistics("Coop_Alpha")
    stats_beta = cooperation_hub.get_agent_statistics("Coop_Beta")

    print(f"Alpha:")
    print(f"  Отправлено: {stats_alpha['messages_sent']}")
    print(f"  Получено: {stats_alpha['messages_received']}")
    print(f"  Репутация: {stats_alpha['avg_reputation']:.0%}")

    print(f"\nBeta:")
    print(f"  Отправлено: {stats_beta['messages_sent']}")
    print(f"  Получено: {stats_beta['messages_received']}")
    print(f"  Репутация: {stats_beta['avg_reputation']:.0%}")

    print(f"\n{'='*70}\n")


def demonstrate_memory_recall():
    """Демонстрирует систему запоминания и припоминания."""

    print(f"\n{'='*70}")
    print(f"  🧠 ДЕМОНСТРАЦИЯ ДОЛГОСРОЧНОЙ ПАМЯТИ")
    print(f"{'='*70}\n")

    agent = DigitalBeing("Memory_Test")
    extended = extend_agent(agent)

    # Сохраняем разные знания
    facts = [
        ("Трансформеры используют внимание", 0.9, "learning"),
        ("BERT предварительно обучен на большом корпусе", 0.8, "learning"),
        ("Механизм внимания позволяет сосредоточиться на важных частях", 0.85, "understanding"),
        ("GPT - это генеративная модель", 0.8, "learning"),
        ("Токенизация - первый шаг обработки текста", 0.7, "technique"),
    ]

    print("💾 Сохранение фактов:")
    for fact, importance, context in facts:
        extended.long_term_memory.store(
            content=fact,
            importance=importance,
            context=context,
            memory_type="semantic"
        )
        print(f"  ✓ {fact[:50]}... (важность: {importance})")

    print(f"\n🔍 Поиск воспоминаний по запросу 'трансформеры':")
    results = extended.long_term_memory.recall("трансформеры", max_results=5)
    for i, result in enumerate(results, 1):
        print(f"  {i}. {result['content'][:60]}")
        print(f"     Сила: {result['strength']:.0%} | Релевантность: {result['relevance']:.0%}")

    print(f"\n{'='*70}\n")


def demonstrate_goal_management():
    """Демонстрирует многозадачное управление целями."""

    print(f"\n{'='*70}")
    print(f"  🎯 ДЕМОНСТРАЦИЯ МНОГОЗАДАЧНОСТИ ЦЕЛЕЙ")
    print(f"{'='*70}\n")

    agent = DigitalBeing("Goal_Manager")
    extended = extend_agent(agent)

    # Добавляем цели
    goals = [
        ("Изучить основы Python", 2, 4),
        ("Понять архитектуру трансформеров", 3, 5),
        ("Реализовать простой трансформер", 4, 5),
        ("Написать статью", 2, 2),
        ("Сотрудничать с Beta", 2, 3),
    ]

    print("🎯 Добавляемые цели:")
    for title, difficulty, priority in goals:
        goal = extended.goal_manager.add_goal(title, difficulty=difficulty, priority=priority)
        print(f"  ✓ {title} (сложность: {difficulty}, приоритет: {priority})")

    # Выбираем цели для работы
    print(f"\n⚙️ Выбор целей для параллельной работы:")
    selected = extended.goal_manager.select_goals_for_cycle(100)
    for goal in selected:
        print(f"  → {goal.title} (приоритет: {goal.priority})")

    # Обновляем прогресс
    print(f"\n📊 Симуляция работы над целями (10 циклов):")
    for cycle in range(1, 11):
        for goal in selected:
            goal.cycles_spent += 1
            extended.goal_manager.update_goal_progress(goal.id, 0.1)

        print(f"  Цикл {cycle}: {sum(g.progress for g in selected):.1f}/3.0 прогресса")

        # Завершаем цели
        for goal in selected:
            if goal.progress >= 1.0 and goal.state.value == "active":
                extended.goal_manager.complete_goal(goal.id)
                print(f"    ✅ ЗАВЕРШЕНА: {goal.title}")

    summary = extended.goal_manager.get_goals_summary()
    print(f"\n📈 Итого:")
    print(f"  Завершено целей: {summary['completed_count']}/{summary['total_goals']}")

    print(f"\n{'='*70}\n")


def main():
    """Главная функция."""
    print("\n" + "="*70)
    print("  🤖 ДЕМОНСТРАЦИЯ РАСШИРЕННОГО ЦИФРОВОГО СУЩЕСТВА")
    print("="*70)

    # Демонстрируем каждую систему
    print("\n[1/4] Запуск основной симуляции...\n")
    extended = simulate_extended_agent_lifecycle(num_cycles=50)

    print("\n[2/4] Демонстрация памяти...\n")
    demonstrate_memory_recall()

    print("\n[3/4] Демонстрация многозадачности...\n")
    demonstrate_goal_management()

    print("\n[4/4] Демонстрация кооперации...\n")
    simulate_multi_agent_cooperation()

    print("\n" + "="*70)
    print("  ✨ ВСЕ СИСТЕМЫ РАБОТАЮТ УСПЕШНО!")
    print("="*70)
    print("\n🎉 Агент готов к жизни с:")
    print("   • Долгосрочной памятью с забыванием")
    print("   • Параллельной работой над несколькими целями")
    print("   • Кооперацией с другими агентами")
    print("   • Самоанализом и самоулучшением")
    print("\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
