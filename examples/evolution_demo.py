"""
Демонстрация истинной самоэволюции через изменение внутренней структуры агента.

Агент физически меняет свою архитектуру мышления:
- Усиливает эффективные паттерны
- Ослабляет неэффективные
- Создает эмерджентные паттерны
- Адаптирует стиль мышления
"""

import sys
import io
import os

# Добавить корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.evolution.cognitive_architecture import CognitiveArchitecture, SelfModifier

# Unicode для stdout
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def demo_thinking_patterns():
    """Базовая демонстрация мыслительных паттернов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 1: Мыслительные паттерны - единицы мышления")
    print("=" * 60)
    
    arch = CognitiveArchitecture()
    
    print(f"\n  📚 Начальная библиотека паттернов:")
    for name, pattern in arch.pattern_library.patterns.items():
        print(f"     {pattern.name} ({pattern.pattern_type}) - вес: {pattern.weight:.2f}")
    
    # Симулирует использование паттернов
    print(f"\n  🔧 Симуляция 10 циклов мышления:")
    
    scenarios = [
        ("analytical_thinking", True, "анализ логики"),
        ("analytical_thinking", True, "логический анализ"),
        ("creative_synthesis", False, "создание новой идеи"),
        ("self_reflection", False, "рефлексия мышления"),
        ("analytical_thinking", True, "декомпозиция проблемы"),
        ("analogical_reasoning", True, "рассуждение по аналогии"),
        ("creative_synthesis", False, "креативная комбинация"),
        ("self_reflection", True, "глубокая рефлексия"),
        ("analytical_thinking", False, "сложный анализ провалился"),
        ("decomposition", True, "разбиение задачи"),
    ]
    
    for pattern_name, success, context in scenarios:
        arch.pattern_library.use_pattern(pattern_name, success, context)
        p = arch.pattern_library.patterns[pattern_name]
        status = "OK" if success else "FAIL"
        print(f"     [{status}] {pattern_name}: эффективность={p.efficiency:.0%}, вес={p.weight:.2f}")
    
    # Показывает результаты
    print(f"\n  📊 Статус паттернов после опыта:")
    for name, pattern in arch.pattern_library.patterns.items():
        rating = pattern.get_effectiveness_rating()
        status_icon = "*" if rating > 0.5 else "~" if rating > 0.2 else "!"
        print(f"     {status_icon} {name}:")
        print(f"        эффективность={pattern.efficiency:.0%}, вес={pattern.weight:.2f}")
        print(f"        рейтинг={rating:.2f}, использований={pattern.usage_count}")


def demo_pattern_evolution():
    """Демонстрация эволюции паттернов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 2: Эволюция паттернов - усиление и ослабление")
    print("=" * 60)
    
    arch = CognitiveArchitecture()
    
    # Симулирует prolonged опыт
    print(f"\n  Фаза 1: Начальный опыт (20 циклов)")
    
    phases = [
        ("analytical_thinking", True, "логика", 8),
        ("creative_synthesis", False, "креатив", 3),
        ("self_reflection", True, "рефлексия", 4),
        ("analogical_reasoning", True, "аналогия", 3),
    ]
    
    for pattern_name, success, context, count in phases:
        for _ in range(count):
            arch.pattern_library.use_pattern(pattern_name, success, context)
    
    # Показывает изменения до эволюции
    print(f"\n     До автоматической эволюции:")
    for name, p in arch.pattern_library.patterns.items():
        if p.usage_count > 0:
            change = "стабильный"
            should, reason = p.should_evolve()
            if should:
                change = f"{reason}"
            print(f"       {name}: вес={p.weight:.3f} ({change})")
    
    # Выполняет эволюцию
    print(f"\n  Эволюция паттернов:")
    changes = arch.pattern_library.evolve_patterns()
    
    for change in changes:
        icon = "+" if change["action"] == "strengthen" else "-"
        print(f"     [{icon}] {change['pattern']}: {change['from']:.3f} -> {change['to']:.3f}")
        print(f"       причина: {change['reason']}")
    
    # Показывает пост-эволюцию
    print(f"\n     После эволюции:")
    for name, p in arch.pattern_library.patterns.items():
        if p.usage_count > 0:
            print(f"       {name}: вес={p.weight:.3f}, статус={p._get_status()}")


def demo_style_adaptation():
    """Демонстрация адаптации стиля мышления."""
    print("\n" + "=" * 60)
    print("  ДЕМО 3: Адаптация стиля мышления")
    print("=" * 60)
    
    arch = CognitiveArchitecture()
    
    print(f"\n  Начальный стиль: {arch.current_style_name}")
    
    # Симулирует различные домены с разной эффективностью
    domains = [
        ("analytical_thinking", "логический анализ", 0.9),   # Успех
        ("creative_synthesis", "креативная задача", 0.3),     # Неудача
        ("self_reflection", "рефлексия и понимание", 0.8),    # Успех
        ("analogical_reasoning", "аналогическое мышление", 0.4),  # Неуспех
    ]
    
    performance_history = []
    
    for pattern_name, domain, success_rate in domains:
        print(f"\n  Домен: '{domain}'")
        result = "успех" if success_rate > 0.5 else "неудача"
        print(f"     Паттерн: {pattern_name} -> {result}")
        
        arch.pattern_library.use_pattern(pattern_name, success_rate > 0.5, domain)
        performance_history.append({"domain": domain, "success": success_rate > 0.5})
        
        # Адаптирует стиль на основе эффективности
        new_style = arch._find_best_style_for_domain(domain, success_rate)
        if new_style and new_style != arch.current_style_name:
            print(f"     СТИЛЬ МЫШЛЕНИЯ: {arch.current_style_name} -> {new_style}")
            arch.set_style(new_style)
    
    # Показывает финальный стиль и его веса
    final_style = arch.get_current_style()
    print(f"\n  Финальный стиль: {arch.current_style_name}")
    print(f"     Параметры стиля:")
    print(f"       анализ: {final_style.analysis_weight:.2f}")
    print(f"       синтез: {final_style.synthesis_weight:.2f}")
    print(f"       рефлексия: {final_style.reflection_weight:.2f}")
    print(f"       креативность: {final_style.creative_weight:.2f}")
    
    print(f"\n  История изменений стиля:")
    for entry in arch.style_history:
        print(f"     {entry['from']} -> {entry['to']}")


def demo_emergent_patterns():
    """Демонстрация создания эмерджентных паттернов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 4: Эмерджентные паттерны - появление нового")
    print("=" * 60)
    
    arch = CognitiveArchitecture()
    
    # Создает опыт для эффективных паттернов
    print(f"\n  Формируем опыт для создания эмерджентных паттернов:")
    
    for pattern_name in ["analytical_thinking", "creative_synthesis", "self_reflection"]:
        for _ in range(5):
            arch.pattern_library.use_pattern(pattern_name, True, "опыт_симуляция")
    
    # Показывает эффективные паттерны
    effective = [
        p.name for p in arch.pattern_library.patterns.values()
        if p.get_effectiveness_rating() > 0.5
    ]
    print(f"\n  Эффективные паттерны: {effective}")
    
    # Создает эмерджентный паттерн
    if len(effective) >= 2:
        new_pattern = arch.create_emergent_pattern(
            source_patterns=effective[:2],
            name="analytical_creative_synthesis",
            pattern_type="synthesis"
        )
        
        print(f"\n  ЭМЕРДЖЕНТНЫЙ ПАТТЕРН СОЗДАН:")
        print(f"     Имя: {new_pattern.name}")
        print(f"     Тип: {new_pattern.pattern_type}")
        print(f"     Вес: {new_pattern.weight:.2f}")
        print(f"     Источник: {' + '.join(effective[:2])}")
    
    # Создает еще один
    if "self_reflection" in effective:
        try:
            new2 = arch.create_emergent_pattern(
                source_patterns=["creative_synthesis", "self_reflection"],
                name="reflective_creation",
                pattern_type="reflection"
            )
            print(f"\n  ЕЩЕ ОДИН ЭМЕРДЖЕНТНЫЙ ПАТТЕРН:")
            print(f"     Имя: {new2.name}")
            print(f"     Вес: {new2.weight:.2f}")
        except ValueError as e:
            print(f"     Не удалось создать: {e}")
    
    # Показывает полную библиотеку
    print(f"\n  Полная библиотека паттернов:")
    for name, p in arch.pattern_library.patterns.items():
        origin = "Эмерджентный" if name.startswith("emergent_") else "базовый"
        status = "активен" if p.usage_count > 0 else "не использован"
        print(f"     [{origin}] {name}: вес={p.weight:.2f}, {status}")


def demo_full_evolution_cycle():
    """Полный цикл эволюции."""
    print("\n" + "=" * 60)
    print("  ДЕМО 5: Полный цикл самоэволюции")
    print("=" * 60)
    
    arch = CognitiveArchitecture()
    modifier = SelfModifier(arch)
    
    print(f"\n  Начальная архитектура:")
    initial_report = modifier.generate_evolution_report()
    print(f"     Стиль: {initial_report['current_architecture']['style']}")
    print(f"     Паттернов: {initial_report['pattern_health']['total']}")
    
    # Симулирует 30 циклов с разными результатами
    print(f"\n  Симуляция 30 циклов мышления:")
    
    all_scenarios = [
        ("analytical_thinking", "логический анализ", 0.8, 10),
        ("creative_synthesis", "креативная задача", 0.3, 5),
        ("self_reflection", "рефлексия", 0.7, 8),
        ("analogical_reasoning", "аналогии", 0.6, 4),
        ("decomposition", "декомпозиция", 0.9, 3),
    ]
    
    performance_history = []
    for pattern_name, domain, success_rate, count in all_scenarios:
        for _ in range(count):
            arch.pattern_library.use_pattern(pattern_name, success_rate > 0.5, domain)
            performance_history.append({"domain": domain, "success": success_rate > 0.5})
    
    print(f"     Завершено {sum(c for _, _, _, c in all_scenarios)} циклов")
    
    # Применяет эволюцию
    print(f"\n  Применение эволюции:")
    changes = modifier.apply_evolution_step(performance_history[-1])
    
    if changes.get("pattern_changes"):
        for change in changes["pattern_changes"]:
            icon = "+" if change["action"] == "strengthen" else "-"
            print(f"     [{icon}] {change['pattern']}: {change['from']:.3f} -> {change['to']:.3f}")
    
    if changes.get("new_emergent_pattern"):
        emergent = changes["new_emergent_pattern"]
        print(f"\n  ЭМЕРДЖЕНТНЫЙ ПАТТЕРН:")
        print(f"     {emergent['name']} ({emergent['type']}) - вес: {emergent['weight']:.2f}")
    
    # Показывает финальный отчет
    final_report = modifier.generate_evolution_report()
    
    print(f"\n  Финальная архитектура:")
    print(f"     Стиль: {final_report['current_architecture']['style']}")
    print(f"     Активных паттернов: {final_report['pattern_health']['active']}")
    print(f"     Эффективных: {final_report['pattern_health']['effective']}")
    print(f"     Структурных изменений: {final_report['structural_changes']['total']}")
    
    print(f"\n  Рекомендации:")
    for rec in final_report["recommendations"]:
        print(f"     -> {rec}")


def demo_abstract_thinking():
    """Демонстрация абстрактного мышления."""
    print("\n" + "=" * 60)
    print("  ДЕМО 6: Абстракция и обобщение")
    print("=" * 60)
    
    arch = CognitiveArchitecture()
    
    # Увеличивает уровень абстракции
    arch.architecture_params["abstraction_level"] = 0.8
    
    test_inputs = [
        "вопрос: что такое жизнь?",
        "команда: выполнить анализ",
        "как работает нейросеть?",
        "почему системы эволюционируют?",
        "создать новую концепцию",
    ]
    
    print(f"\n  Ввод -> Абстрактное представление:")
    
    for text in test_inputs:
        abstract = arch.get_abstract_representation(text)
        print(f"     '{text[:35]:35}' -> {abstract}")
    
    # Показывает как абстракция помогает
    print(f"\n  benefits абстракции:")
    print(f"     1. Отделение сущности от деталей")
    print(f"     2. Обобщение опыта в категории")
    print(f"     3. Возможность применения к новым ситуациям")


def main():
    """Запуск всех демонстраций."""
    print("\n" + "=" * 60)
    print("  ИСТИННАЯ САМОЭВОЛЮЦИЯ - Изменение внутренней структуры")
    print("  Самоэволюционирующийся ИИ - Компонент 3")
    print("=" * 60)
    
    try:
        demo_thinking_patterns()
        demo_pattern_evolution()
        demo_style_adaptation()
        demo_emergent_patterns()
        demo_full_evolution_cycle()
        demo_abstract_thinking()
        
        print("\n" + "=" * 60)
        print("  Все демонстрации завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nОшибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()