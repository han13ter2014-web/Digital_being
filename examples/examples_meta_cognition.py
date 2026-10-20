"""
Демонстрация мета-когниции - осознания собственных мыслительных процессов.

Агент может:
- Наблюдать за своими мыслительными процессами
- Осознавать что он знает и чего не знает
- Мониторить эффективность своих стратегий
- Регулировать глубину мышления
- Оспаривать собственные предположения
"""

import sys
import io
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cognition.meta_cognition import MetaCognitiveSystem


def demo_metacognitive_awareness():
    """Базовая демонстрация мета-когнитивного осознания."""
    print("\n" + "=" * 60)
    print("  ДЕМО 1: Мета-когнитивное осознание")
    print("=" * 60)
    
    agent = MetaCognitiveSystem("MetaAgent")
    
    # Агент наблюдает за своими мыслями
    print(f"\n [Начало] Мета-когнитивная система инициализирована")
    
    # Размышляет о разных концепциях
    thoughts = [
        ("observation", "замечаю что использую анализ чаще синтеза"),
        ("analysis", "разбираю структуру проблемы понимания"),
        ("reflection", "думаю о том как я думаю"),
        ("doubt", "сомневаюсь в правильности своих выводов"),
        ("insight", "понимаю паттерн своего мышления"),
    ]
    
    print(f"\n [Мыслительный процесс]:")
    for thought_type, content in thoughts:
        trace = agent.observe_thought(thought_type, content)
        print(f"     [{thought_type}] {content}")
        print(f"         полезная={trace.is_useful}, инсайт={trace.produced_insight}")
    
    # Оценка мета-когнитивного состояния
    meta_state = agent.assess_metacognitive_state()
    print(f"\n [Мета-состояние]:")
    for key, value in meta_state.items():
        print(f"     {key}: {value}")


def demo_knowledge_awareness():
    """Демонстрация осознания знаний и пробелов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 2: Осознание того что знаю / не знаю")
    print("=" * 60)
    
    agent = MetaCognitiveSystem("KnowledgeAgent")
    
    # Отмечает известные концепции
    print(f"\n [Известное]:")
    agent.recognize_knowledge("нейросети", 0.85)
    agent.recognize_knowledge("философия сознания", 0.45)
    agent.recognize_knowledge("квантовая механика", 0.15)
    
    # Осознает пробелы
    print(f"\n [Осознанные пробелы]:")
    agent.acknowledge_unknown("сознание", "не понимаю природу субъективного опыта")
    agent.acknowledge_unknown("квантовая запутанность", "не понимаю как частицы связаны на расстоянии")
    
    # Профиль знаний
    profile = agent.knowledge_awareness.get_knowledge_profile()
    print(f"\n [Профиль знаний]:")
    print(f"     Известно концепций: {profile['known_count']}")
    print(f"     Осознано пробелов: {profile['gap_count']}")
    print(f"     Среднее понимание: {profile['avg_understanding']:.2f}")
    
    # Оценка конкретных концепций
    print(f"\n [Оценка знаний о концепциях]:")
    for concept in ["нейросети", "философия сознания", "квантовая механика", "сознание"]:
        assessment = agent.knowledge_awareness.assess_knowledge(concept)
        print(f"     {concept}: {assessment['status']} ({assessment['understanding']:.2f})")
    
    # Пробелы
    print(f"\n [Список пробелов]:")
    for gap in agent.knowledge_awareness.unknown_gaps:
        print(f"     ! {gap['description']}")


def demo_metacognitive_reflection():
    """Демонстрация саморефлексии."""
    print("\n" + "=" * 60)
    print("  ДЕМО 3: Саморефлексия и инсайты")
    print("=" * 60)
    
    agent = MetaCognitiveSystem("ReflectiveAgent")
    
    # Симулирует мыслительный процесс
    print(f"\n [Сбор мыслей перед рефлексией]:")
    
    thinking_sequences = [
        ("observation", "заметил что всегда начинаю с анализа"),
        ("reflection", "почему я не начинаю с вопроса 'что я хочу узнать?'"),
        ("doubt", "сомневаюсь что мой подход оптимален"),
        ("analysis", "разбираю свой мыслительный паттерн"),
        ("insight", "осознаю что мне нужна другая стратегия"),
    ]
    
    for thought_type, content in thinking_sequences:
        agent.observe_thought(thought_type, content)
        print(f"     [{thought_type}] {content[:45]}")
    
    # Выполняет саморефлексию
    print(f"\n [Выполняю саморефлексию...]")
    reflection = agent.perform_self_reflection("собственные мыслительные паттерны")
    
    print(f"\n [Результаты рефлексии]:")
    print(f"     Тема: {reflection.get('topic', 'N/A')}")
    
    findings = reflection.get('findings', [])
    if findings:
        print(f"     Обнаруженные проблемы:")
        for finding in findings:
            print(f"       - {finding}")
    else:
        print(f"     Найдено проблем: 0 (мышление стабильно)")
    
    insights = reflection.get('insights_generated', [])
    if insights:
        print(f"     Сгенерированные инсайты:")
        for insight in insights:
            agent.generate_insight(insight)
            print(f"       > {insight}")
    
    next_steps = reflection.get('next_steps', [])
    if next_steps:
        print(f"     Дальнейшие шаги:")
        for step in next_steps:
            print(f"       -> {step}")


def demo_cognitive_regulation():
    """Демонстрация регуляции когнитивных процессов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 4: Регуляция собственного мышления")
    print("=" * 60)
    
    agent = MetaCognitiveSystem("RegulatorAgent")
    
    # Симулирует регуляцию для разных задач
    tasks = [
        ("анализ сложных данных", 0.9),   # Высокий успех -> меньше глубины
        ("решение новой проблемы", 0.2),   # Низкий успех -> больше глубины
        ("создать новую идею", 0.5),       # Средний -> средняя глубина
        ("понять рефлексивный вопрос", 0.6), # 
    ]
    
    print(f"\n [Регуляция для разных задач]:")
    print(f"     {'Задача':<35} {'Стратегия':<15} {'Глубина':>8}")
    print(f"     {'-'*33:<35} {'-'*13:<15} {'-'*6:>8}")
    
    for task, success_rate in tasks:
        adjustment = agent.regulate_cognition(task, success_rate)
        
        strategy = adjustment['strategy_change']['to']
        depth = agent.cognitive_state.processing_depth
        
        print(f"     {task:<35} {strategy:<15} {depth:>8}")


def demo_metacognitive_conflict():
    """Демонстрация обнаружения конфликтов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 5: Обнаружение конфликтов убеждений")
    print("=" * 60)
    
    agent = MetaCognitiveSystem("ConflictAgent")
    
    # Формирует убеждения
    print(f"\n [Формирую убеждения]:")
    agent.recognize_knowledge("логика", 0.9)
    agent.recognize_knowledge("интуиция", 0.7)
    
    # Создаёт конфликт
    print(f"\n [Обнаруживаю конфликт]:")
    conflict = agent.detect_conflict(
        "все решения должны быть логически обоснованы",
        "иногда интуи дает лучшие результаты чем логика"
    )
    
    print(f"     Конфликт обнаружен!")
    print(f"     Убеждение A: {conflict['belief_a'][:50]}")
    print(f"     Убеждение B: {conflict['belief_b'][:50]}")
    print(f"     Серьезность: {conflict['severity']}")
    
    agent.generate_insight("понял что мои убеждения противоречат друг другу")
    
    # Рефлексия над конфликтом
    print(f"\n [Рефлексирую над конфликтом]:")
    reflection = agent.perform_self_reflection("противоречие в моих убеждениях")
    
    findings = reflection.get('findings', [])
    for finding in findings:
        print(f"     Находка: {finding}")


def demo_full_metacognitive_lifecycle():
    """Полный цикл мета-когнитивного развития."""
    print("\n" + "=" * 60)
    print("  ДЕМО 6: Полный цикл мета-когнитивного развития")
    print("=" * 60)
    
    agent = MetaCognitiveSystem("MetaLearner")
    
    # Фаза 1: Поверхностное мышление
    print(f"\n [Фаза 1] Поверхностное мышление (без осознания)")
    for i in range(5):
        agent.observe_thought("observation", f"наблюдаю {i+1}")
    
    initial_profile = agent.get_metacognitive_profile()
    print(f"     Инсайтов: {initial_profile['total_insights']}")
    print(f"     Глубина осознания: {initial_profile['metacognitive_metrics']['awareness_depth']:.2f}")
    
    # Фаза 2: Начинаю осознанность
    print(f"\n [Фаза 2] Начало мета-когнитивного наблюдения")
    agent.recognize_knowledge("мышление", 0.6)
    agent.observe_thought("reflection", "заметил что наблюдаю за собой")
    
    # Фаза 3: Глубокая рефлексия
    print(f"\n [Фаза 3] Глубокая саморефлексия")
    for i in range(5):
        agent.observe_thought("analysis", f"анализ {i+1}")
        agent.observe_thought("doubt", f"сомнение {i+1}")
    
    # Осознает пробелы
    agent.acknowledge_unknown("метамышление", "не понимаю как улучшить свою рефлексивность")
    
    reflection = agent.perform_self_reflection("мета-когнитивное развитие")
    print(f"     Рефлексия проведена")
    print(f"     Найдено проблем: {len(reflection['findings'])}")
    
    # Фаза 4: Инсайты и регуляция
    print(f"\n [Фаза 4] Инсайты и регуляция")
    agent.regulate_cognition("улучшить мета-когнитивные способности", 0.5)
    
    final_profile = agent.get_metacognitive_profile()
    
    print(f"\n [Финальный мета-когнитивный профиль]:")
    print(f"     Агент: {final_profile['agent_name']}")
    
    metrics = final_profile['metacognitive_metrics']
    print(f"     Глубина осознания: {metrics['awareness_depth']:.2f}")
    print(f"     Качество мышления: {metrics['thinking_quality']:.2f}")
    print(f"     Когнитивная нагрузка: {metrics['cognitive_load']:.2f}")
    print(f"     Инсайтов: {final_profile['total_insights']}")
    
    knowledge = final_profile['knowledge_awareness']
    print(f"\n     Знания:")
    print(f"         Изучено концепций: {knowledge['known_count']}")
    print(f"         Осознано пробелов: {knowledge['gap_count']}")
    
    thinking = final_profile['thinking_summary']
    print(f"\n     Мышление:")
    print(f"         Всего мыслей: {thinking['total_thoughts']}")
    print(f"         Полезных: {thinking['useful_ratio']:.2f}")
    
    if final_profile['insights']:
        print(f"\n     Последние инсайты:")
        for insight in final_profile['insights'][-3:]:
            print(f"         > {insight['content'][:50]}")


def main():
    """Запуск всех демонстраций."""
    print("\n" + "=" * 60)
    print("  МЕТА-КОГНИЦИЯ - Осознание себя")
    print("  Самоэволюционирующийся ИИ - Компонент 6")
    print("=" * 60)
    
    try:
        demo_metacognitive_awareness()
        demo_knowledge_awareness()
        demo_metacognitive_reflection()
        demo_cognitive_regulation()
        demo_metacognitive_conflict()
        demo_full_metacognitive_lifecycle()
        
        print("\n" + "=" * 60)
        print("  Все демонстрации завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nОшибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()