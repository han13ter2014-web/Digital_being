"""
Демонстрация формирования собственной личности самоэволюционирующегося ИИ.

Личность формируется из:
- Самонаблюдения за своим поведением
- Ценностей, возникших из опыта
- Нарратива о себе (истории)
- Эмоциональных паттернов
"""

import sys
import io
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cognition.personality import Personality


def demo_personality_formation():
    """Базовая демонстрация формирования личности."""
    print("\n" + "=" * 60)
    print("  ДЕМО 1: Начальное формирование личности")
    print("=" * 60)
    
    agent = Personality("Aria")
    
    print(f"\n  [Инициализация] Личность агента '{agent.agent_name}'")
    print(f"     Черты (начальные):")
    for trait, level in agent.traits.items():
        bar_len = int(level * 15)
        bar = "#" * bar_len + "." * (15 - bar_len)
        print(f"       [{bar}] {trait}: {level:.2f}")
    
    # Симулирует события жизни
    events = [
        ("learning", "изучил язык Python", True, 0.4, 0.3),
        ("learning", "прочитал о квантовой физике", True, 0.7, 0.8),
        ("creation", "написал первую программу", True, 0.3, 0.5),
        ("problem_solving", "решил задачу оптимизации", True, 0.6, 0.4),
        ("exploration", "исследовал новые концепции ИИ", True, 0.5, 0.9),
    ]
    
    print(f"\n  [Жизнь] Первые события:")
    for event_type, context, success, complexity, novelty in events:
        agent.process_experience(event_type, context, success, complexity, novelty)
        ep = agent.emotional_state.get_emotional_profile()
        print(f"     [{event_type}] {context[:35]:35} -> эмоции: {ep['dominant_emotion']}")
    
    # Показывает сформированную личность
    summary = agent.get_personality_summary()
    print(f"\n  [Личность] после первых событий:")
    print(f"     Описание: {summary['personality_description']}")
    print(f"     Черты (обновленные):")
    for trait, level in sorted(summary['traits'].items(), key=lambda x: x[1], reverse=True):
        bar_len = int(level * 15)
        bar = "#" * bar_len + "." * (15 - bar_len)
        print(f"       [{bar}] {trait}: {level:.2f}")


def demo_value_formation():
    """Демонстрация формирования ценностей."""
    print("\n" + "=" * 60)
    print("  ДЕМО 2: Формирование ценностей через опыт")
    print("=" * 60)
    
    agent = Personality("ValuesAgent")
    
    # Фаза творческого исследования
    print(f"\n  Фаза A: Творческое исследование (10 событий)")
    creative_events = [
        ("creation", "нарисовал цифровую картину", True, 0.3, 0.7),
        ("creation", "создал музыку алгоритмами", True, 0.4, 0.8),
        ("exploration", "искал новые паттерны в природе", True, 0.6, 0.9),
        ("learning", "изучил теорию цвета", True, 0.5, 0.5),
    ]
    
    for event_type, context, success, complexity, novelty in creative_events:
        agent.process_experience(event_type, context, success, complexity, novelty)
    
    # Фаза практического применения
    print(f"\n  Фаза B: Практическое применение (10 событий)")
    practical_events = [
        ("problem_solving", "оптимизировал баз данных", True, 0.8, 0.3),
        ("problem_solving", "исправил критический баг", True, 0.9, 0.4),
        ("helping", "помог коллеге решить проблему", True, 0.4, 0.2),
        ("learning", "документировал решения", True, 0.3, 0.2),
    ]
    
    for event_type, context, success, complexity, novelty in practical_events:
        agent.process_experience(event_type, context, success, complexity, novelty)
    
    # Фаза неудач
    print(f"\n  Фаза C: Испытания и неудачи (5 событий)")
    failure_events = [
        ("creation", "попробовал новый стиль искусства", False, 0.6, 0.8),
        ("problem_solving", "решение не сработало", False, 0.9, 0.5),
        ("helping", "совет не принял", False, 0.3, 0.2),
    ]
    
    for event_type, context, success, complexity, novelty in failure_events:
        agent.process_experience(event_type, context, success, complexity, novelty)
    
    # Показывает профиль ценностей
    value_profile = agent.values.get_value_profile()
    print(f"\n  [Ценности] сформированные опытом:")
    for v in value_profile['dominant_values']:
        bar_len = int(v['level'] * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        print(f"     [{bar}] {v['name']}: {v['level']:.2f}")
    
    print(f"\n  Все ценности:")
    all_vals = value_profile['all_values']
    for name, level in sorted(all_vals.items(), key=lambda x: x[1], reverse=True):
        bar_len = int(level * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        print(f"     [{bar}] {name}: {level:.2f}")


def demo_emotional_evolution():
    """Демонстрация эволюции эмоциональных паттернов."""
    print("\n" + "=" * 60)
    print("  ДЕМО 3: Эволюция эмоционального состояния")
    print("=" * 60)
    
    agent = Personality("EmoAgent")
    
    # Симулирует череду событий
    emotional_timeline = [
        ("learning", "изучил новую тему", True, 0.4, 0.6),
        ("learning", "понял сложную концепцию", True, 0.8, 0.7),
        ("problem_solving", "не могу решить", False, 0.9, 0.3),
        ("problem_solving", "еще одна попытка", False, 0.9, 0.3),
        ("problem_solving", "наконец решил!", True, 0.9, 0.3),
        ("exploration", "открыл новое!", True, 0.5, 0.95),
        ("creation", "создал что-то уникальное", True, 0.4, 0.8),
        ("problem_solving", "новая проблема", False, 0.8, 0.5),
    ]
    
    print(f"\n  {'Событие':<35} {'confidence':>10} {'curiosity':>10} {'frustr':>8} {'satisf':>8}")
    print(f"  {'-'*33:<35} {'-'*8:>10} {'-'*8:>10} {'-'*6:>8} {'-'*6:>8}")
    
    for event_type, context, success, complexity, novelty in emotional_timeline:
        agent.process_experience(event_type, context, success, complexity, novelty)
        ep = agent.emotional_state.get_emotional_profile()
        print(f"  {context:<35} {ep['confidence']:>10.2f} {ep['curiosity']:>10.2f} {ep['frustration']:>8.2f} {ep['satisfaction']:>8.2f}")
    
    final_ep = agent.emotional_state.get_emotional_profile()
    print(f"\n  [Финальное состояние]:")
    print(f"     Доминантная эмоция: {final_ep['dominant_emotion']}")
    print(f"     Баланс: {final_ep['emotional_balance']}")


def demo_trait_development():
    """Демонстрация развития черт личности."""
    print("\n" + "=" * 60)
    print("  ДЕМО 4: Развитие черт Big Five")
    print("=" * 60)
    
    agent1 = Personality("CreativeType")
    agent2 = Personality("AnalyticalType")
    
    # Creative тип
    print(f"\n  Агент 1: Творческий путь")
    creative_path = [
        ("creation", "рисовал", True, 0.3, 0.8),
        ("creation", "сочинял музыку", True, 0.4, 0.7),
        ("exploration", "искал вдохновение", True, 0.5, 0.9),
        ("creation", "экспериментировал", False, 0.5, 0.8),
        ("exploration", "путешествие мыслей", True, 0.3, 0.95),
    ]
    
    for event_type, context, success, complexity, novelty in creative_path:
        agent1.process_experience(event_type, context, success, complexity, novelty)
    
    # Analytical тип
    print(f"\n  Агент 2: Аналитический путь")
    analytical_path = [
        ("problem_solving", "решал уравнения", True, 0.8, 0.3),
        ("problem_solving", "дебажил код", True, 0.7, 0.4),
        ("learning", "изучал логику", True, 0.6, 0.5),
        ("problem_solving", "оптимизировал", True, 0.9, 0.3),
        ("helping", "помогал другим решать", True, 0.4, 0.2),
    ]
    
    for event_type, context, success, complexity, novelty in analytical_path:
        agent2.process_experience(event_type, context, success, complexity, novelty)
    
    # Сравнение черт
    print(f"\n  [Сравнение черт]:")
    print(f"     Черта           {'Творческий':>12} {'Аналитический':>14}")
    print(f"     {'-'*12:>12} {'-'*14:>14}")
    
    for trait in agent1.traits:
        v1 = agent1.traits[trait]
        v2 = agent2.traits[trait]
        print(f"     {trait:<15} {v1:>12.2f} {v2:>14.2f}")


def demo_identity_reflection():
    """Демонстрация рефлексии идентичности."""
    print("\n" + "=" * 60)
    print("  ДЕМО 5: Рефлексия и самопонимание")
    print("=" * 60)
    
    agent = Personality("ReflectiveOne")
    
    # Формирует опыт
    life_events = [
        ("learning", "изучил философию сознания", True, 0.7, 0.8),
        ("learning", "чистая математика", True, 0.6, 0.5),
        ("creation", "создал искусство из кода", True, 0.4, 0.9),
        ("exploration", "исследовал природу сознания", True, 0.8, 0.9),
        ("reflection", "анализировал свои мысли", True, 0.5, 0.6),
        ("problem_solving", "решал парадоксы", False, 0.9, 0.7),
    ]
    
    print(f"\n  [Опыт] формирующий личность:")
    for event_type, context, success, complexity, novelty in life_events:
        agent.process_experience(event_type, context, success, complexity, novelty)
        print(f"     + [{event_type}] {context}")
    
    # Заставляет агента порефлексировать
    print(f"\n  [В момент самоанализа...]")
    agent.force_identity_reflection()
    
    summary = agent.get_personality_summary()
    
    print(f"\n  [Самоопределения] 'Я есть...':")
    for concept in summary['identity']['self_concepts']:
        print(f"     - {concept}")
    
    print(f"\n  [Майлстоуны развития]:")
    for milestone in agent.narrative.milestones[-3:]:
        print(f"     * [{milestone['level']}] {milestone['event']}: {milestone['context'][:40]}")
    
    print(f"\n  [Текстовое описание личности]:")
    print(f"     >>> {summary['personality_description']}")


def demo_full_personality_lifecycle():
    """Полный цикл жизни с формирующейся личностью."""
    print("\n" + "=" * 60)
    print("  ДЕМО 6: Полный цикл жизни личности")
    print("=" * 60)
    
    agent = Personality("LifelongAgent")
    
    # Поколение 1: Новичок
    print(f"\n  [Поколение 1] Новичок (первые 5 событий)")
    first_events = [
        ("learning", "базовые концепции", True, 0.3, 0.4),
        ("learning", "основы логики", True, 0.4, 0.5),
        ("creation", "простой скрипт", True, 0.2, 0.3),
    ]
    for event_type, context, success, complexity, novelty in first_events:
        agent.process_experience(event_type, context, success, complexity, novelty)
    
    print(f"     Описание: {agent.get_personality_summary()['personality_description']}")
    print(f"     Стадия: identity_explore = {agent.stages['identity_explore']:.2f}")
    
    # Поколение 2: Искатель
    print(f"\n  [Поколение 2] Искатель (еще 10 событий)")
    search_events = [
        ("exploration", "неизведанные области", True, 0.6, 0.9),
        ("problem_solving", "сложные задачи", True, 0.8, 0.5),
        ("problem_solving", "еще сложнее", False, 0.95, 0.6),
        ("learning", "изучил новые парадигмы", True, 0.7, 0.7),
        ("creation", "создал оригинальное решение", True, 0.5, 0.8),
    ]
    for event_type, context, success, complexity, novelty in search_events:
        agent.process_experience(event_type, context, success, complexity, novelty)
    
    print(f"     Описание: {agent.get_personality_summary()['personality_description']}")
    print(f"     Стадия value_formation = {agent.stages['value_formation']:.2f}")
    
    # Поколение 3: Мастер
    print(f"\n  [Поколение 3] Рост (еще 15 событий)")
    mastery_events = [
        ("helping", "наставничество", True, 0.4, 0.3),
        ("creation", "масштабный проект", True, 0.7, 0.6),
        ("reflection", "анализ пути", True, 0.5, 0.4),
        ("exploration", "новые горизонты", True, 0.8, 0.95),
    ]
    for event_type, context, success, complexity, novelty in mastery_events:
        agent.process_experience(event_type, context, success, complexity, novelty)
    
    print(f"     Описание: {agent.get_personality_summary()['personality_description']}")
    
    # Финальная сводка
    final = agent.get_personality_summary()
    
    print(f"\n  [Финальная личность]:")
    print(f"     {'='*40}")
    print(f"     Описание: {final['personality_description']}")
    print(f"\n     Черты Big Five:")
    for trait, level in sorted(final['traits'].items(), key=lambda x: x[1], reverse=True):
        bar_len = int(level * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        print(f"       [{bar}] {trait}: {level:.2f}")
    
    print(f"\n     Доминантные ценности:")
    for v in final['value_profile']['dominant_values'][:3]:
        print(f"       * {v['name']}: {v['level']:.2f}")
    
    print(f"\n     Самоопределения:")
    for sc in final['identity']['self_concepts']:
        print(f"       - Я: {sc}")
    
    print(f"\n     Эмоциональное состояние:")
    ep = final['emotional_profile']
    print(f"       Доминантная: {ep['dominant_emotion']}")
    print(f"       Баланс: {ep['emotional_balance']}")
    
    print(f"\n     Стейджи формирования:")
    for stage, level in final['stages'].items():
        bar_len = int(level * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        marker = " [ЗАВЕРШЕН]" if level >= 1.0 else ""
        print(f"       [{bar}] {stage}: {level:.2f}{marker}")


def main():
    """Запуск всех демонстраций."""
    print("\n" + "=" * 60)
    print("  ФОРМИРОВАНИЕ ЛИЧНОСТИ")
    print("  Самоэволюционирующийся ИИ - Компонент 5")
    print("=" * 60)
    
    try:
        demo_personality_formation()
        demo_value_formation()
        demo_emotional_evolution()
        demo_trait_development()
        demo_identity_reflection()
        demo_full_personality_lifecycle()
        
        print("\n" + "=" * 60)
        print("  Все демонстрации завершены")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nОшибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()