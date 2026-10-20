"""
Демонстрация эмергентного поведения - незапланированных способностей.

Эмерджентные свойства НЕ были запрограммированы заранее - они ВОЗНИКЛИ из:
- Комбинаций простых правил
- Петель обратной связи
- Нелинейных взаимодействий компонентов
- Накопления малых изменений
"""

import sys
import io
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cognition.emergent_behavior import EmergentAgent


def demo_emergent_patterns():
    """Демонстрация выявления эмерджентных паттернов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 1: Выявление эмерджентных паттернов")
    print("=" * 60)
    
    agent = EmergentAgent("PatternAgent")
    
    # Наблюдает за агентом в разных ситуациях
    scenarios = [
        {"motivation": 0.8, "reflection": 0.7, "goals": 0.6},
        {"motivation": 0.8, "reflection": 0.7, "learning": 0.5},
        {"motivation": 0.9, "reflection": 0.8, "goals": 0.7},
        {"memory": 0.7, "simulation": 0.8},
        {"memory": 0.8, "simulation": 0.7},
        {"memory": 0.7, "simulation": 0.9},
    ]
    
    print(f"\n  [Наблюдения за поведением]:")
    for i, state in enumerate(scenarios):
        for comp, val in state.items():
            agent.set_component(comp, val)
        
        result = agent.simulate_with_emergence("эксперимент_действие", 0.6)
        
        active = agent.get_active_components()
        print(f"     Наблюдение {i+1}: активные={active[:4]}")
        
        if result["new_patterns_discovered"]:
            for p in result["new_patterns_discovered"]:
                print(f"       >>> НОВЫЙ ПАТТЕРН: {p}")
    
    report = agent.get_report()
    print(f"\n  [Итог]:")
    print(f"     Выявлено паттернов: {report['unique_patterns']}")
    print(f"     Эмерджентных событий: {report['emergent_events_count']}")


def demo_emergent_capabilities():
    """Демонстрация появления эмерджентных способностей."""
    print("\n" + "=" * 60)
    print("  ДЕМО 2: Появление новых способностей")
    print("=" * 60)
    
    agent = EmergentAgent("CapabilityAgent")
    
    synergy_scenarios = [
        {"motivation": 0.7, "reflection": 0.7},
        {"motivation": 0.8, "reflection": 0.8},
        {"motivation": 0.6, "reflection": 0.6},
        {"memory": 0.7, "simulation": 0.8},
        {"memory": 0.8, "simulation": 0.9},
        {"personality": 0.7, "goals": 0.8},
        {"personality": 0.8, "goals": 0.7},
        {"values": 0.7, "motivation": 0.8},
        {"emotions": 0.7, "goals": 0.8},
    ]
    
    print(f"\n  [Симуляция комбинаций компонентов]:")
    for i, state in enumerate(synergy_scenarios):
        for comp, val in state.items():
            agent.set_component(comp, val)
        
        result = agent.simulate_with_emergence("действие_с_синергией", 0.55)
        
        active = agent.get_active_components()
        bonus = result["emergence_bonus"]
        
        print(f"     Шаг {i+1}: активные={active[:4]}")
        print(f"        бонус=+{bonus:.2f}, успех={result['success']}")
    
    report = agent.get_report()
    patterns = report.get("discovered_patterns", [])
    
    if patterns:
        print(f"\n  [Эмерджентные паттерны]:")
        for p in patterns[:5]:
            print(f"     - {p['name']} (cat={p['category']}, strength={p['strength']:.2f})")


def demo_phase_transitions():
    """Демонстрация фазовых переходов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 3: Фазовые переходы - резкие изменения")
    print("=" * 60)
    
    agent = EmergentAgent("PhaseAgent")
    
    # Фаза 1: Низкая рефлексия (много наблюдений)
    print(f"\n  [Фаза 1] Низкая рефлексия (5 циклов)")
    for i in range(5):
        agent.set_component("reflection", 0.2)
        result = agent.simulate_with_emergence("поверхностное_мышление", 0.4)
        print(f"     Цикл {i+1}: reflection=0.2, успех={result['success']}")
    
    # Фаза 2: Резкий скачок рефлексии
    print(f"\n  [Фаза 2] Скачок рефлексии (после неудач)")
    for i in range(5):
        agent.set_component("reflection", 0.8)
        agent.set_component("learning", 0.7)
        result = agent.simulate_with_emergence("глубокий_анализ", 0.6)
        print(f"     Цикл {i+1}: reflection=0.8, успех={result['success']}, бонус={result['emergence_bonus']:.2f}")
    
    # Проверяет фазовые переходы
    report = agent.get_report()
    transitions = report.get("phase_transitions", [])
    
    if transitions:
        print(f"\n  [Фазовые переходы обнаружены]:")
        for t in transitions:
            print(f"     {t['component']}: {t['from_value']:.2f} -> {t['to_value']:.2f} ({t['direction']})")


def demo_synergy_effects():
    """Демонстрация синергетических эффектов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 4: Синергетические эффекты комбинаций")
    print("=" * 60)
    
    agent = EmergentAgent("SynergyAgent")
    
    test_cases = [
        {"name": "Один компонент", "state": {"motivation": 0.8}, "base": 0.5},
        {"name": "Два компонента", "state": {"motivation": 0.7, "reflection": 0.7}, "base": 0.5},
        {"name": "Три компонента + синергия", "state": {"motivation": 0.8, "reflection": 0.8, "memory": 0.7, "simulation": 0.8}, "base": 0.5},
        {"name": "Полная интеграция", "state": {"motivation": 0.8, "reflection": 0.8, "memory": 0.8, "simulation": 0.8, "personality": 0.7, "values": 0.7}, "base": 0.5},
    ]
    
    print(f"\n  {'Тест':<30} {'База':>6} {'Бонус':>8} {'Итог':>6} {'Успех':>6}")
    print(f"  {'-'*28:<30} {'-'*4:>6} {'-'*6:>8} {'-'*4:>6} {'-'*4:>6}")
    
    for case in test_cases:
        for comp, val in case["state"].items():
            agent.set_component(comp, val)
        
        result = agent.simulate_with_emergence(case["name"], case["base"])
        
        name_short = case["name"][:28]
        print(f"     {name_short:<30} {case['base']:>6.1f} {result['emergence_bonus']:>8.2f} {result['effective_success']:>6.2f} {'OK' if result['success'] else 'FAIL':>6}")


def demo_full_emergent_lifecycle():
    """Полный цикл эмерджентного поведения."""
    print("\n" + "=" * 60)
    print("  ДЕМО 5: Полный цикл эмерджентного поведения")
    print("=" * 60)
    
    agent = EmergentAgent("FullEmergent")
    
    # Поколение 1: Базовое поведение
    print(f"\n  [Поколение 1] Простые действия (5 циклов)")
    simple_actions = [
        {"motivation": 0.6},
        {"memory": 0.6},
        {"goals": 0.6},
        {"learning": 0.7},
        {"emotions": 0.5},
    ]
    
    for i, state in enumerate(simple_actions):
        for comp, val in state.items():
            agent.set_component(comp, val)
        result = agent.simulate_with_emergence("простое_действие", 0.4)
        print(f"     Цикл {i+1}: comps={[k for k in state.keys()]}, успех={result['success']}")
    
    # Поколение 2: Комбинации возникают
    print(f"\n  [Поколение 2] Формирование комбинаций (10 циклов)")
    combo_actions = [
        {"motivation": 0.7, "goals": 0.6},
        {"motivation": 0.7, "reflection": 0.6},
        {"memory": 0.6, "simulation": 0.7},
        {"personality": 0.6, "learning": 0.7},
        {"values": 0.6, "motivation": 0.7},
    ]
    
    for i, state in enumerate(combo_actions):
        for comp, val in state.items():
            agent.set_component(comp, val)
        result = agent.simulate_with_emergence("комбинированное_действие", 0.5)
        print(f"     Цикл {i+1}: combos={[k for k in state.keys()]}, бонус={result['emergence_bonus']:.2f}")
    
    # Поколение 3: Полная интеграция
    print(f"\n  [Поколение 3] Интеграция всех компонентов (5 циклов)")
    integrated = {
        "motivation": 0.8, "reflection": 0.7, "memory": 0.7,
        "simulation": 0.7, "personality": 0.6, "values": 0.6, "learning": 0.7
    }
    
    for i in range(5):
        for comp, val in integrated.items():
            agent.set_component(comp, val)
        result = agent.simulate_with_emergence("интегрированное_действие", 0.5)
        print(f"     Цикл {i+1}: все_компоненты, бонус={result['emergence_bonus']:.2f}, успех={result['success']}")
    
    # Финальный отчет
    report = agent.get_report()
    
    print(f"\n  [Финальная эмерджентная статистика]:")
    print(f"     Выявлено паттернов: {report['unique_patterns']}")
    print(f"     Эмерджентных событий: {report['emergent_events_count']}")
    
    patterns = report.get("discovered_patterns", [])
    if patterns:
        print(f"\n  [Выявленные эмерджентные паттерны]:")
        for p in patterns[:5]:
            combo = p.get('most_common_combination', [])
            print(f"     * {p['name']} (strength={p['strength']:.2f}, combo={combo})")


def main():
    """Запуск всех демонстраций."""
    print("\n" + "=" * 60)
    print("  ЭМЕРДЖЕНТНОЕ ПОВЕДЕНИЕ - Незапланированные способности")
    print("  Самоэволюционирующийся ИИ - Компонент 8")
    print("=" * 60)
    
    try:
        demo_emergent_patterns()
        demo_emergent_capabilities()
        demo_phase_transitions()
        demo_synergy_effects()
        demo_full_emergent_lifecycle()
        
        print("\n" + "=" * 60)
        print("  Все демонстрации завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nОшибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()