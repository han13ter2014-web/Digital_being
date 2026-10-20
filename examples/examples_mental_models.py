"""
Демонстрация системы ментальных моделей самоэволюционирующегося ИИ.

Агент автономно формирует понимание концепций через опыт, без внешних LLM.
"""

import sys
import io
from src.cognition.mental_models import MentalModel, ConceptNode

# Убедиться в корректной работе с Unicode
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def demo_basic_concept_formation():
    """Демонстрация базового формирования концепций."""
    print("\n" + "=" * 60)
    print("  ДЕМО 1: Формирование концепций через опыт")
    print("=" * 60)
    
    models = MentalModel("demo_basic")
    
    # Агент встречает концепцию "эволюция" в разных контекстах
    context1 = "биология процессы развития организмов"
    outcome1 = "процесс изменения структуры системы во времени"
    models.encounter_concept("эволюция", context1, outcome1, 0.5)
    
    context2 = "технологии эволюция систем разработанных"
    outcome2 = "процесс улучшения технологий через итерации"
    models.encounter_concept("эволюция", context2, outcome2, 0.4)
    
    context3 = "интеллект эволюция автономных агентов"
    outcome3 = "самоулучшение системы через накопление опыта"
    models.encounter_concept("эволюция", context3, outcome3, 0.6)
    
    # Через 3 опыта формирует гипотезу определения
    understanding = models.get_concept_understanding("эволюция")
    
    print(f"\n  Концепция: 'эволюция'")
    print(f"  Уверенность: {understanding['confidence']:.0%}")
    print(f"  Встреч: {understanding['experience_count']}")
    if understanding.get("hypothesis"):
        print(f"  Гипотеза определения:")
        print(f"     {understanding['hypothesis']}")
    
    can_define = understanding.get("can_define", False)
    print(f"\n  Может определить: {'Да' if can_define else 'Нет (нужен больше опыт)'}")


def demo_association_formation():
    """Демонстрация формирования ассоциаций между концепциями."""
    print("\n" + "=" * 60)
    print("  ДЕМО 2: Формирование связей между концепциями")
    print("=" * 60)
    
    models = MentalModel("demo_associations")
    
    # Формирует сеть концепций через общие контексты
    experiences = [
        ("эволюция", "биология процессы развития организмов", "процесс изменения структуры", 0.5),
        ("эволюция", "технологии развитие систем разработанных", "улучшение через итерации", 0.4),
        ("развитие", "биология рост организмов сложных", "укрупнение сложности системы", 0.6),
        ("развитие", "интеллект обучение агента нового", "расширение возможностей Through опыт", 0.5),
        ("интеллект", "биология живые системы мышление", "способность обработки знаний", 0.7),
        ("самоорганизация", "системы структурирование себя без внешних", "спонтанное появление порядка", 0.8),
        ("самоорганизация", "эволюция путь к сложности", "автоматическое улучшение", 0.4),
    ]
    
    for concept, ctx, outcome, valence in experiences:
        models.encounter_concept(concept, ctx, outcome, valence)
    
    # Показывает сеть концепций
    print(f"\n  Сеть концепций агента:")
    for name, node in models.concepts.items():
        connections = node.get_related_concepts(min_weight=0.3)
        top = sorted(connections, key=lambda x: x['weight'], reverse=True)[:2]
        conn_str = ", ".join([f"{c['concept']}({c['weight']:.0%})" for c in top]) if top else "(нет сильных связей)"
        icon = "LIGHT" if node.confidence > 0.6 else "SEARCH"
        print(f"\n  {icon} {name}")
        print(f"     Связи: {conn_str}")
    
    # Показывает связь между концепциями
    print(f"\n  Связи концепции 'эволюция':")
    related = models.find_related_concepts("эволюция", max_distance=2)
    for r in related[:4]:
        icon = "->" if r.confidence > 0.5 else "~"
        print(f"     {icon} {r.name} (уверенность: {r.confidence:.0%})")


def demo_definition_evolution():
    """Демонстрация эволюции определений по мере накопления опыта."""
    print("\n" + "=" * 60)
    print("  ДЕМО 3: Эволюция определений")
    print("=" * 60)
    
    models = MentalModel("demo_evolution")
    
    concept = "сознание"
    
    # Фаза 1: Первое encountering
    print(f"\n  Фаза 1: Первое encountering концепции '{concept}'")
    models.encounter_concept(concept, "философия вопрос природы субъективного", "гипотеза: свойство системы рефлексии", 0.3)
    
    u1 = models.get_concept_understanding(concept)
    hyp_text = u1['hypothesis'] or '(недостаточно данных для гипотезы)'
    print(f"     Гипотеза: {hyp_text}")
    print(f"     Уверенность: {u1['confidence']:.0%}")
    
    # Фаза 2-5: Добавляем опыт
    phases = [
        (2, "нейробиология системы мозга активации", "физиологический correlate нейро-паттернов", 0.4),
        (3, "ИИ рефлексия самонаблюдение агента", "способность анализировать собственное состояние", 0.6),
        (4, "философия мета cognition рекурсия", "знание о знании - рекурсивная само-модель", 0.7),
        (5, "когнитивика глобальное рабочее пространство", "интеграция информации в единый образ", 0.5),
    ]
    
    for phase, ctx, outcome, valence in phases:
        models.encounter_concept(concept, ctx, outcome, valence)
        
        u = models.get_concept_understanding(concept)
        print(f"\n  Фаза {phase}: После +1 опыта (итого {u['experience_count']} встреч)")
        if u.get("hypothesis"):
            short = u['hypothesis'][:55] + "..." if len(u['hypothesis']) > 55 else u['hypothesis']
            print(f"     Гипотеза: {short}")
        print(f"     Уверенность: {u['confidence']:.0%}")
    
    final = models.get_concept_understanding(concept)
    can_define = "Может дать определение" if final.get("can_define") else "Нужно больше опыта"
    print(f"\n  Итог: {can_define}")


def demo_contextual_discovery():
    """Демонстрация поиска концепций по контексту."""
    print("\n" + "=" * 60)
    print("  ДЕМО 4: Контекстный поиск и эмерджентные связи")
    print("=" * 60)
    
    models = MentalModel("demo_context")
    
    # Строит богатую концептуальную сеть
    data = [
        ("memory", "компьютер хранение данных структуры", "способность хранить информацию", 0.6),
        ("память", "биология нейроны воспоминания stored", "способность к воспроизведению прошлого", 0.7),
        ("learning", "алгоритм обучение данные паттерны", "изменение через опыт", 0.8),
        ("обучение", "нейробиология синапсы пластичность изменение", "физическое переключение связей мозга", 0.6),
        ("attention", "cognition фокус ресурсы вычисления распределение", "выбор важной информации для обработки", 0.7),
        ("внимание", "нейрология сенсорная фильтрация отбор стимулов", "селективная активация нейронов", 0.5),
        ("abstract", "математика abstraction общие свойства специфические", "выделение общего из частного", 0.4),
        ("абстракция", "когнитивия обобщение категорий удаление деталей", "формирование концепций из опыта", 0.6),
        ("self", "философия identity рекурсия само-референция", "модель собственного тела и состояния", 0.5),
        ("идентичность", "психология непрерывность persona core self", "устойчивая модель-self across time", 0.4),
    ]
    
    for concept, ctx, outcome, valence in data:
        models.encounter_concept(concept, ctx, outcome, valence)
    
    # Ищет концепции в контексте
    print(f"\n  Концепции в контексте 'интеллект обучение':")
    found = models.find_concepts_by_context("интеллект обучение")
    for i, f in enumerate(found[:4], 1):
        icon = "LIGHT" if f.confidence > 0.6 else "SEARCH"
        print(f"     {i}. {icon} {f.name} (уверенность: {f.confidence:.0%})")
    
    # Находит эмерджентные связи (через BFS)
    print(f"\n  Эмерджентные связи концепции 'обучение' (расстояние <=2):")
    related = models.find_related_concepts("learning", max_distance=2)
    for r in related[:4]:
        strength = "сильная" if r.confidence > 0.6 else "умеренная" if r.confidence > 0.3 else "слабая"
        print(f"     <-> {r.name} ({strength}, {r.confidence:.0%})")


def demo_agent_integration():
    """Демонстрация интеграции с DigitalBeing."""
    print("\n" + "=" * 60)
    print("  ДЕМО 5: Интеграция с DigitalBeing")
    print("=" * 60)
    
    from src.core.agent import DigitalBeing
    
    agent = DigitalBeing("Neural")
    
    # Демонстрирует автономное формирование концепций
    print(f"\n  Агент: {agent.name}")
    
    # Формирует ментальные модели через циклы
    stimuli = [
        "вопрос: что такое память?",
        "стимул: структура хранения данных",
        "вопрос: как работает обучение?",
        "концепт: синаптическая пластичность",
    ]
    
    for i, stimulus in enumerate(stimuli, 1):
        print(f"\n  --- Цикл {i}: '{stimulus}' ---")
        perceived = agent.perceive(stimulus)
        thought = agent.think(perceived)
        print(f"  Мысль: {thought[:80]}...")
    
    # Показывает статус ментальных моделей
    status = agent.get_mental_models_status()
    print(f"\n  Статус ментальных моделей:")
    print(f"     Всего концепций: {status['total_concepts']}")
    print(f"     С высокой уверенностью: {status['concepts_with_high_confidence']}")
    print(f"     С определением: {status['concepts_with_definition']}")
    print(f"     Ассоциаций: {status['total_associations']}")
    
    # Формирует идентифичность через самопонимание
    identity = agent.get_agent_identity()
    print(f"\n  Агент о себе:")
    print(f"     {identity}")
    
    # Сохраняет ментальные модели
    agent.save_mental_models('data/mind/mental_models_demo.json')


def demo_full_lifecycle():
    """Полная демонстрация жизненного цикла формирования понимания."""
    print("\n" + "=" * 60)
    print("  ДЕМО 6: Полный цикл эволюции понимания")
    print("=" * 60)
    
    models = MentalModel("full_lifecycle")
    
    # Этап формирования через опыт разных доменов
    cross_domain_data = [
        ("эмерджентность", "системная наука появление нового из простого", "возникновение сложных паттернов из простых правил", 0.7),
        ("эмерджентность", "интеаллект из поведенение агента проявляется", "незапланированные способности возникают", 0.6),
        ("эмерджентность", "биология жизнь из неживая материя возникла", "самOrganization материи в живые системы", 0.8),
        
        ("самоорганизация", "физика диссипативные структуры Prigogine", "спонтанное формирование порядка в открытых системах", 0.6),
        ("самоорганизация", "роботика коллективное поведение стая роботы", "координация без центрального управления", 0.5),
        
        ("рефлексия", "philosophy self-observation meta-cognition inquiry", "анализ собственных процессов мышления", 0.7),
        ("рефлексия", "psychology инсайт self-awareness introspection метод", "доступ к собственным ментальным состояниям", 0.6),
        
        ("интеграция", "нейро science binding problem cortex синхронизация", "объединение распределенной информации", 0.5),
        ("интеграция", "системная theory units через diversity синтез", "соединение разнородных элементов в целое", 0.6),
    ]
    
    print(f"\n  Формирование концептуальной сети...")
    for concept, ctx, outcome, valence in cross_domain_data:
        models.encounter_concept(concept, ctx, outcome, valence)
    
    # Показывает эволюцию ключевых концепций
    key_concepts = ["эмерджентность", "самоорганизация", "рефлексия", "интеграция"]
    
    for concept in key_concepts:
        if concept in models.concepts:
            u = models.get_concept_understanding(concept)
            icon = "LIGHT" if u.get("can_define") else "SEARCH"
            exp_count = u['experience_count']
            conf = u['confidence']
            hyp = u.get('hypothesis', '(формируется...)')[:50]
            
            print(f"\n  {icon} {concept}")
            print(f"     Опыт: {exp_count} встреч | Уверенность: {conf:.0%}")
            if len(hyp) > 47:
                hyp = hyp[:47] + "..."
            print(f"     Гипотеза: {hyp}")
    
    # Показывает полную карту
    print(f"\n  Карта понятий агента:")
    models.print_model_tree()
    
    # Записывает итог
    well_understood = [n for n, node in models.concepts.items() if models.can_answer_about(n)]
    print(f"\n  Итог формирования понимания:")
    print(f"     Изучено концепций: {len(models.concepts)}")
    print(f"     Полностью понято: {len(well_understood)}")
    print(f"     Ассоциаций создано: {models.metadata['total_associations']}")


def main():
    """Запуск всех демонстраций."""
    print("\n" + "=" * 60)
    print("  СИСТЕМА МЕНТАЛЬНЫХ МОДЕЛЕЙ")
    print("  Самоэволюционирующийся ИИ - Компонент 1")
    print("=" * 60)
    
    try:
        demo_basic_concept_formation()
        demo_association_formation()
        demo_definition_evolution()
        demo_contextual_discovery()
        demo_agent_integration()
        demo_full_lifecycle()
        
        print("\n" + "=" * 60)
        print("  Все демонстрации завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nОшибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()