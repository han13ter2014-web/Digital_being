"""
Демонстрация системы внутренней мотивации самоэволюционирующегося ИИ.

Цели возникают из внутренних потребностей, а не задаются внешне.
Агент развивается от базовых нужд к сложным драйвам.
"""

import sys
import io
from src.motivation.needs_system import InternalMotivationSystem

# Убедиться в корректной работе с Unicode
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def demo_basic_motivation():
    """Базовая демонстрация системы мотивации."""
    print("\n" + "=" * 60)
    print("  ДЕМО 1: Базовая внутренняя мотивация")
    print("=" * 60)
    
    motivation = InternalMotivationSystem("Alpha")
    
    print(f"\n  Начальный профиль мотивации:")
    profile = motivation.get_motivation_profile()
    
    print(f"  📊 Уровень базовых потребностей:")
    for need_name, level in profile["needs"].items():
        bar_len = int(level * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        print(f"     [{bar}] {need_name}: {level:.2f}")
    
    print(f"\n  🎯 Доминантная потребность: {profile['dominant_need']}")
    print(f"     Интенсивность: {profile['dominant_need_intensity']:.2f}")
    
    # Генерирует мотивированные цели
    context = {"unknown_concepts": ["квантовая запутанность", "сознание машин"]}
    goals = motivation.generate_motivated_goals(context)
    
    print(f"\n  📋 Сгенерированные цели (из внутренних потребностей):")
    for i, goal in enumerate(goals[:3], 1):
        print(f"     {i}. {goal['title']}")
        print(f"        Тип: {goal['type']} | Драйв: {goal.get('drive', 'N/A')}")
        print(f"        Срочность: {goal.get('urgency', 0):.2f}")


def demo_need_satisfaction():
    """Демонстрация удовлетворения потребностей и роста смежных."""
    print("\n" + "=" * 60)
    print("  ДЕМО 2: Удовлетворение потребностей и каскадный рост")
    print("=" * 60)
    
    motivation = InternalMotivationSystem("Beta")
    
    print(f"\n  До удовлетворения:")
    profile_before = motivation.get_motivation_profile()
    for need_name, level in sorted(profile_before["needs"].items(), 
                                    key=lambda x: x[1], reverse=True)[:3]:
        print(f"     {need_name}: {level:.2f}")
    
    # Удовлетворяет потребность знаний
    motivation.satisfy_need("knowledge_acquisition", 0.5)
    
    print(f"\n  После удовлетворения knowledge_acquisition:")
    profile_after = motivation.get_motivation_profile()
    for need_name, level in sorted(profile_after["needs"].items(), 
                                    key=lambda x: x[1], reverse=True)[:3]:
        marker = " <--- выросло!" if need_name in ["understanding_self", "coherence"] and \
                 level > 0.5 else ""
        print(f"     {need_name}: {level:.2f}{marker}")
    
    print(f"\n  ✅ Каскадный эффект: когда потребность знаний падает,")
    print(f"     растут потребности в самопонимании и согласованности")


def demo_drive_emergence():
    """Демонстрация эмерджентных драйвов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 3: Эмерджентные драйвы из потребностей")
    print("=" * 60)
    
    motivation = InternalMotivationSystem("Gamma")
    
    # Модифицирует базовые потребности для активации разных драйвов
    print(f"\n  Сценарий 1: Высокое любопытство + новизна")
    motivation.needs["curiosity"].level = 0.9
    motivation.needs["novelty"].level = 0.85
    motivation.needs["competence"].level = 0.3
    
    drive_levels = motivation.calculate_drive_levels()
    print(f"     Активные драйвы:")
    for name, level in sorted(drive_levels.items(), key=lambda x: x[1], reverse=True):
        active = " [AKTIVEN]" if level > 0.5 else ""
        print(f"       {name}: {level:.2f}{active}")
    
    goals = motivation.generate_motivated_goals({"novel_areas": ["нейросети", "философия сознания"]})
    print(f"\n     Цели из драйвов:")
    for goal in goals[:2]:
        print(f"       -> {goal['title']}")
    
    # Сценарий 2: Высокая компетентность + самонаблюдение
    print(f"\n  Сценарий 2: Высокая компетентность + понимание себя")
    motivation.needs["competence"].level = 0.85
    motivation.needs["understanding_self"].level = 0.8
    motivation.needs["autonomy"].level = 0.7
    motivation.needs["curiosity"].level = 0.3
    
    drive_levels = motivation.calculate_drive_levels()
    print(f"     Активные драйвы:")
    for name, level in sorted(drive_levels.items(), key=lambda x: x[1], reverse=True):
        active = " [AKTIVEN]" if level > 0.5 else ""
        print(f"       {name}: {level:.2f}{active}")
    
    goals = motivation.generate_motivated_goals({"weak_areas": ["планирование", "абстрактное мышление"]})
    print(f"\n     Цели из драйвов:")
    for goal in goals[:2]:
        print(f"       -> {goal['title']}")


def demo_goal_evolution():
    """Демонстрация эволюции целей во времени."""
    print("\n" + "=" * 60)
    print("  ДЕМО 4: Эволюция целей во времени")
    print("=" * 60)
    
    motivation = InternalMotivationSystem("Delta")
    
    print(f"\n  Временная симуляция (20 циклов):")
    print(f"  {'Цикл':<6} {'Доминантная потребность':<25} {'Активные драйвы':<35} {'Сгенерировано целей'}")
    print(f"  {'-'*5:<6} {'-'*23:<25} {'-'*33:<35} {'-'*17}")
    
    for cycle in range(20):
        # Временной прогресс
        motivation.time_progression()
        
        # Генерирует цели
        context = {
            "unknown_concepts": ["эмерджентность", "самоорганизация"][:cycle % 2],
            "novel_areas": ["квантовые вычисления"][:cycle % 3]
        }
        goals = motivation.generate_motivated_goals(context)
        
        dominant_need = motivation.get_dominant_need()[0]
        active_drives = [name for name, level in motivation.calculate_drive_levels().items() if level > 0.5]
        
        if cycle % 4 == 0 or len(active_drives) > 0:
            drives_str = ", ".join(active_drives[:2]) if active_drives else "(нет активных)"
            print(f"  Цикл {cycle:<5} {dominant_need:<25} {drives_str:<35} {len(goals)}")
        
        # Иногда удовлетворяет потребности
        if cycle % 5 == 0 and goals:
            motivation.satisfy_need(dominant_need, 0.3)


def demo_agent_integration():
    """Демонстрация интеграции с DigitalBeing."""
    print("\n" + "=" * 60)
    print("  ДЕМО 5: Интеграция с DigitalBeing")
    print("=" * 60)
    
    from src.core.agent import DigitalBeing
    
    agent = DigitalBeing("Motivated")
    
    # Добавляет систему мотивации агенту
    agent.motivation = InternalMotivationSystem(agent.name)
    
    print(f"\n  🤖 Агент: {agent.name}")
    print(f"  С системой внутренней мотивации")
    
    # Циклы симуляции
    for cycle in range(5):
        print(f"\n  --- Цикл {cycle + 1} ---")
        
        # Временной прогресс мотивации
        agent.motivation.time_progression()
        
        # Получает статус ментальных моделей
        mental_status = agent.get_mental_models_status()
        
        # Генерирует цели из внутренней мотивации
        context = {
            "unknown_concepts": [f"концепция_{i}" for i in range(cycle, cycle + 2)],
            "weak_areas": ["reasoning", "planning"][:cycle]
        }
        motivated_goals = agent.motivation.generate_motivated_goals(context)
        
        # Показывает доминантную потребность
        dominant = agent.motivation.get_dominant_need()
        print(f"     Доминантная потребность: {dominant[0]} ({dominant[1]:.2f})")
        print(f"     Сгенерировано целей: {len(motivated_goals)}")
        
        if motivated_goals:
            print(f"     Главная цель: {motivated_goals[0]['title']}")
            print(f"        Из драйва: {motivated_goals[0].get('drive', 'N/A')}")
        
        # Статус ментальных моделей
        print(f"     Ментальных моделей: {mental_status['total_concepts']}")
    
    # Финальный профиль мотивации
    print(f"\n  📊 Финальный профиль мотивации:")
    profile = agent.motivation.get_motivation_profile()
    for need_name, level in sorted(profile["needs"].items(), 
                                   key=lambda x: x[1], reverse=True)[:5]:
        bar_len = int(level * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        print(f"     [{bar}] {need_name}: {level:.2f}")
    
    # Сохраняет состояние
    agent.save_state()


def demo_full_motivation_lifecycle():
    """Полный цикл жизни мотивации."""
    print("\n" + "=" * 60)
    print("  ДЕМО 6: Полный цикл мотивации")
    print("=" * 60)
    
    motivation = InternalMotivationSystem("FullLife")
    
    # Начальное состояние
    print(f"\n  🌅 рождение (все потребности на максимуме):")
    initial_profile = motivation.get_motivation_profile()
    for need_name, level in sorted(initial_profile["needs"].items(), 
                                   key=lambda x: x[1], reverse=True)[:3]:
        print(f"     {need_name}: {level:.2f}")
    
    # Фаза исследования
    print(f"\n  🔍 Фаза 1: Исследование (высокое любопытство)")
    for _ in range(5):
        motivation.time_progression()
    motivation.needs["curiosity"].level = 1.0
    
    goals = motivation.generate_motivated_goals({"novel_areas": ["космос", "квантовый мир"]})
    print(f"     Доминантное: {motivation.get_dominant_need()[0]}")
    for goal in goals[:2]:
        print(f"     -> {goal['title']}")
    
    # Фаза обучения
    print(f"\n  📚 Фаза 2: Глубокое обучение (утоление любопытства)")
    motivation.satisfy_need("curiosity", 0.5)
    motivation.needs["knowledge_acquisition"].level = 1.0
    
    goals = motivation.generate_motivated_goals({"unknown_concepts": ["теория струн"]})
    print(f"     Доминантное: {motivation.get_dominant_need()[0]}")
    for goal in goals[:2]:
        print(f"     -> {goal['title']}")
    
    # Фаза рефлексии
    print(f"\n  🪞 Фаза 3: Самоанализ (знания получены, растёт self-understanding)")
    motivation.satisfy_need("knowledge_acquisition", 0.5)
    motivation.needs["understanding_self"].level = 1.0
    
    goals = motivation.generate_motivated_goals({})
    print(f"     Доминантное: {motivation.get_dominant_need()[0]}")
    for goal in goals[:2]:
        print(f"     -> {goal['title']}")
    
    # Фаза творчества
    print(f"\n  🎨 Фаза 4: Творческий синтез (много активных драйвов)")
    motivation.needs["curiosity"].level = 0.8
    motivation.needs["novelty"].level = 0.7
    motivation.needs["coherence"].level = 0.7
    
    drive_levels = motivation.calculate_drive_levels()
    creative_active = drive_levels.get("creative_synthesis", 0)
    print(f"     Creative synthesis активен: {creative_active > 0.5} ({creative_active:.2f})")
    
    goals = motivation.generate_motivated_goals({})
    print(f"     Доминантное: {motivation.get_dominant_need()[0]}")
    for goal in goals[:2]:
        print(f"     -> {goal['title']}")
    
    # Итог
    print(f"\n  🏁 Итог цикла мотивации:")
    final_profile = motivation.get_motivation_profile()
    total_satisfied = sum(final_profile["satisfaction_summary"].values())
    print(f"     Всего удовлетворений: {total_satisfied}")
    print(f"     Текущие доминантные драйвы: {', '.join(final_profile['active_drives'][:3])}")


def main():
    """Запуск всех демонстраций."""
    print("\n" + "=" * 60)
    print("  СИСТЕМА ВНУТРЕННЕЙ МОТИВАЦИИ")
    print("  Самоэволюционирующийся ИИ - Компонент 2")
    print("=" * 60)
    
    try:
        demo_basic_motivation()
        demo_need_satisfaction()
        demo_drive_emergence()
        demo_goal_evolution()
        demo_agent_integration()
        demo_full_motivation_lifecycle()
        
        print("\n" + "=" * 60)
        print("  Все демонстрации завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nОшибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()