"""
Демонстрация автономной постановки целей на основе внутренних потребностей.

Цели НЕ задаются извне - они возникают ИЗ внутренней структуры агента:
- Из мотивации (что хочу?)
- Из ценностей (что важно?)
- Из личности (кто я?)
- Из пробелов знаний (чего не знаю?)
"""

import sys
import io
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cognition.goal_management import GoalDrivenAgent, Goal


def demo_goal_generation():
    """Базовая демонстрация генерации целей."""
    print("\n" + "=" * 60)
    print("  ДЕМО 1: Автономная генерация целей")
    print("=" * 60)
    
    agent = GoalDrivenAgent("GoalAgent")
    
    # Устанавливает внутренние состояния
    motivation_profile = {
        "dominant_need": "knowledge_acquisition",
        "dominant_need_intensity": 0.85,
        "active_drives": ["purposeful_learning", "exploration_drive"]
    }
    
    values_profile = {
        "dominant_values": [
            {"name": "truth", "level": 0.75},
            {"name": "growth", "level": 0.68},
            {"name": "novelty", "level": 0.63}
        ]
    }
    
    knowledge_gaps = [
        {"description": "природа сознания"},
        {"description": "квантовая запутанность"}
    ]
    
    personality_summary = {
        "traits": {
            "openness": 0.75,
            "conscientiousness": 0.53,
            "extraversion": 0.42
        }
    }
    
    agent.set_motivation(motivation_profile)
    agent.set_values(values_profile)
    agent.set_knowledge_gaps(knowledge_gaps)
    agent.set_personality(personality_summary)
    
    # Генерирует цели
    print(f"\n  [Внутренние состояния]:")
    print(f"     Доминантная потребность: {motivation_profile['dominant_need']}")
    print(f"     Активные драйвы: {', '.join(motivation_profile['active_drives'][:2])}")
    print(f"     Ценности: truth={values_profile['dominant_values'][0]['level']:.2f}, growth={values_profile['dominant_values'][1]['level']:.2f}")
    print(f"     Пробелы: {len(knowledge_gaps)}")
    print(f"     Черта openness: {personality_summary['traits']['openness']:.2f}")
    
    new_goals = agent.generate_and_activate_goals()
    
    print(f"\n  [Сгенерированные цели (автоматически)]:")
    for i, goal in enumerate(new_goals, 1):
        print(f"     {i}. {goal.title[:50]}")
        print(f"        источник={goal.source}, приоритет={goal.priority:.2f}")


def demo_goal_lifecycle():
    """Демонстрация полного жизненного цикла цели."""
    print("\n" + "=" * 60)
    print("  ДЕМО 2: Жизненный цикл цели")
    print("=" * 60)
    
    # Создает цель напрямую
    goal = Goal(
        title="Изучить философию сознания",
        goal_type="learning",
        source="motivation",
        priority=0.85
    )
    
    # Декомпозирует
    print(f"\n  [Создание] Цель: '{goal.title}'")
    subgoals = goal.decompose("learning")
    print(f"     Декомпозиция на {len(subgoals)} подцели:")
    for sg in subgoals:
        print(f"       - {sg['subgoal_title']} ({sg['status']})")
    
    # Симулирует выполнение
    print(f"\n  [Выполнение]:")
    agent = GoalDrivenAgent("LifecycleAgent")
    agent.goal_system.active_goals.append(goal)
    
    for cycle in range(5):
        results = agent.goal_system.update_all_goals({"effort": 0.4})
        if results:
            r = results[0]
            print(f"     Цикл {cycle+1}: прогресс={r['progress_after']:.2f}, результат={r['outcome']}")


def demo_motivation_to_goals():
    """Демонстрация трансформации мотивации в цели."""
    print("\n" + "=" * 60)
    print("  ДЕМО 3: От внутренней мотивации к целям")
    print("=" * 60)
    
    agent = GoalDrivenAgent("MotivationAgent")
    
    # Разные сценарии мотивации
    scenarios = [
        {
            "name": "Фаза исследования",
            "motivation": {
                "dominant_need": "curiosity",
                "dominant_need_intensity": 0.9,
                "active_drives": ["exploration_drive", "creative_synthesis"]
            },
            "values": {"dominant_values": [{"name": "novelty", "level": 0.7}]},
            "gaps": [{"description": "неизведанные области физики"}],
            "personality": {"traits": {"openness": 0.8, "conscientiousness": 0.4}}
        },
        {
            "name": "Фаза самопознания",
            "motivation": {
                "dominant_need": "understanding_self",
                "dominant_need_intensity": 0.85,
                "active_drives": ["self_improvement", "purposeful_learning"]
            },
            "values": {"dominant_values": [{"name": "truth", "level": 0.73}]},
            "gaps": [{"description": "собственные паттерны мышления"}],
            "personality": {"traits": {"openness": 0.6, "conscientiousness": 0.7}}
        },
        {
            "name": "Фаза творчества",
            "motivation": {
                "dominant_need": "competence",
                "dominant_need_intensity": 0.8,
                "active_drives": ["self_improvement"]
            },
            "values": {"dominant_values": [{"name": "creativity", "level": 0.65}]},
            "gaps": [],
            "personality": {"traits": {"openness": 0.7, "conscientiousness": 0.6}}
        }
    ]
    
    for scenario in scenarios:
        print(f"\n  --- {scenario['name']} ---")
        
        agent.set_motivation(scenario["motivation"])
        agent.set_values(scenario["values"])
        agent.set_knowledge_gaps(scenario["gaps"])
        agent.set_personality(scenario["personality"])
        
        goals = agent.generate_and_activate_goals()
        
        print(f"     Доминантная потребность: {scenario['motivation']['dominant_need']}")
        print(f"     Сгенерировано целей: {len(goals)}")
        for g in goals[:3]:
            print(f"       -> {g.title[:45]} (приоритет={g.priority:.2f})")


def demo_goal_prioritization():
    """Демонстрация приоритизации целей."""
    print("\n" + "=" * 60)
    print("  ДЕМО 4: Приоритизация и декомпозиция")
    print("=" * 60)
    
    agent = GoalDrivenAgent("PriorityEngine")
    
    motivation_profile = {
        "dominant_need": "knowledge_acquisition",
        "dominant_need_intensity": 0.9,
        "active_drives": ["purposeful_learning", "exploration_drive"]
    }
    
    values_profile = {
        "dominant_values": [
            {"name": "truth", "level": 0.75},
            {"name": "growth", "level": 0.68}
        ]
    }
    
    knowledge_gaps = [
        {"description": "природа сознания"},
        {"description": "квантовая механика"},
        {"description": "математика топологии"}
    ]
    
    personality_summary = {
        "traits": {"openness": 0.75, "conscientiousness": 0.6},
        "personality_description": "открытый новому опыту"
    }
    
    agent.set_motivation(motivation_profile)
    agent.set_values(values_profile)
    agent.set_knowledge_gaps(knowledge_gaps)
    agent.set_personality(personality_summary)
    
    goals = agent.generate_and_activate_goals()
    
    print(f"\n  [Приоритезированные цели]:")
    print(f"     {'№':<4} {'Цель':<40} {'Приоритет':>10} {'Источник':>12}")
    print(f"     {'-'*3:<4} {'-'*38:<40} {'-'*8:>10} {'-'*10:>12}")
    
    for i, g in enumerate(goals, 1):
        print(f"     {i:<4} {g.title[:38]:<40} {g.priority:>10.2f} {g.source:>12}")


def demo_multi_cycle_execution():
    """Многоцикловое выполнение целей."""
    print("\n" + "=" * 60)
    print("  ДЕМО 5: Многоцикловое выполнение целей")
    print("=" * 60)
    
    agent = GoalDrivenAgent("MultiCycle")
    
    motivation_profile = {
        "dominant_need": "competence",
        "dominant_need_intensity": 0.7,
        "active_drives": ["self_improvement", "purposeful_learning"]
    }
    
    values_profile = {
        "dominant_values": [
            {"name": "growth", "level": 0.68},
            {"name": "truth", "level": 0.5}
        ]
    }
    
    agent.set_motivation(motivation_profile)
    agent.set_values(values_profile)
    agent.set_knowledge_gaps([{"description": "слабые стороны"}])
    agent.set_personality({"traits": {"openness": 0.5, "conscientiousness": 0.7}})
    
    print(f"\n  [Многоцикловое выполнение]:")
    print(f"     {'Цикл':<6} {'Новые цели':<12} {'Выполнено':<10} {'Завершено':<10} {'Отклонено':<10}")
    print(f"     {'-'*4:<6} {'-'*10:<12} {'-'*8:<10} {'-'*8:<10} {'-'*8:<10}")
    
    for cycle in range(8):
        result = agent.execute_cycle(0.3)
        dashboard = agent.get_dashboard()
        
        print(f"     Цикл {cycle+1:<5} {len(result['new_goals_titles']):<12} "
              f"{len(result['execution_results']):<10} {dashboard['completed_count']:<10} {dashboard['abandoned_count']:<10}")
    
    dashboard = agent.get_dashboard()
    print(f"\n  [Итог]:")
    print(f"     Завершено целей: {dashboard['completed_count']}")
    print(f"     Отклонено целей: {dashboard['abandoned_count']}")
    print(f"     Rate выполнения: {dashboard['metrics']['completion_rate']:.2f}")


def demo_full_agent_lifecycle():
    """Полный цикл автономного агента с целями."""
    print("\n" + "=" * 60)
    print("  ДЕМО 6: Полный цикл автономного агента")
    print("=" * 60)
    
    agent = GoalDrivenAgent("FullAutonomous")
    
    # Эволюционирующая мотивация
    motivation_timeline = [
        {"dominant_need": "curiosity", "intensity": 0.9, "drives": ["exploration_drive"]},
        {"dominant_need": "knowledge_acquisition", "intensity": 0.85, "drives": ["purposeful_learning"]},
        {"dominant_need": "understanding_self", "intensity": 0.8, "drives": ["self_improvement"]},
        {"dominant_need": "competence", "intensity": 0.7, "drives": ["self_improvement", "purposeful_learning"]},
    ]
    
    values_timeline = [
        [{"name": "novelty", "level": 0.7}],
        [{"name": "truth", "level": 0.73}],
        [{"name": "growth", "level": 0.68}],
        [{"name": "creativity", "level": 0.65}]
    ]
    
    gaps_timeline = [
        [{"description": "неизведанные области"}],
        [{"description": "пробелы в знаниях"}],
        [{"description": "понимание себя"}],
        []
    ]
    
    personality = {
        "traits": {"openness": 0.65, "conscientiousness": 0.55, "extraversion": 0.4}
    }
    
    print(f"\n  Поколение 1: Исследователь")
    agent.set_motivation(motivation_timeline[0])
    agent.set_values(values_timeline[0])
    agent.set_knowledge_gaps(gaps_timeline[0])
    agent.set_personality(personality)
    
    goals = agent.generate_and_activate_goals()
    print(f"     Доминантное: {motivation_timeline[0]['dominant_need']}")
    for g in goals[:2]:
        print(f"       -> {g.title[:45]} (p={g.priority:.2f})")
    
    print(f"\n  Поколение 2: Учитель")
    agent.set_motivation(motivation_timeline[1])
    agent.set_values(values_timeline[1])
    agent.set_knowledge_gaps(gaps_timeline[1])
    
    goals = agent.generate_and_activate_goals()
    print(f"     Доминантное: {motivation_timeline[1]['dominant_need']}")
    for g in goals[:2]:
        print(f"       -> {g.title[:45]} (p={g.priority:.2f})")
    
    print(f"\n  Поколение 3: Рефлексивный аналитик")
    agent.set_motivation(motivation_timeline[2])
    agent.set_values(values_timeline[2])
    agent.set_knowledge_gaps(gaps_timeline[2])
    
    goals = agent.generate_and_activate_goals()
    print(f"     Доминантное: {motivation_timeline[2]['dominant_need']}")
    for g in goals[:2]:
        print(f"       -> {g.title[:45]} (p={g.priority:.2f})")
    
    print(f"\n  Поколение 4: Созидатель")
    agent.set_motivation(motivation_timeline[3])
    agent.set_values(values_timeline[3])
    agent.set_knowledge_gaps(gaps_timeline[3])
    
    goals = agent.generate_and_activate_goals()
    print(f"     Доминантное: {motivation_timeline[3]['dominant_need']}")
    for g in goals[:2]:
        print(f"       -> {g.title[:45]} (p={g.priority:.2f})")
    
    # Многоцикловое выполнение
    print(f"\n  [Цикл выполнения - 10 шагов]:")
    completed = 0
    for i in range(10):
        result = agent.execute_cycle(0.4)
        if any(r.get('outcome') == 'success' for r in result['execution_results']):
            completed += 1
    
    dashboard = agent.get_dashboard()
    print(f"     Успешных шагов: {completed}/10")
    print(f"     Итоговая панель:")
    print(f"       Активных целей: {dashboard['active_count']}/{dashboard['capacity']}")
    print(f"       Завершено: {dashboard['completed_count']}")
    print(f"       Rate: {dashboard['metrics']['completion_rate']:.2f}")


def main():
    """Запуск всех демонстраций."""
    print("\n" + "=" * 60)
    print("  АВТОНОМНАЯ ПОСТАНОВКА ЦЕЛЕЙ")
    print("  Самоэволюционирующийся ИИ - Компонент 7")
    print("=" * 60)
    
    try:
        demo_goal_generation()
        demo_goal_lifecycle()
        demo_motivation_to_goals()
        demo_goal_prioritization()
        demo_multi_cycle_execution()
        demo_full_agent_lifecycle()
        
        print("\n" + "=" * 60)
        print("  Все демонстрации завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nОшибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()