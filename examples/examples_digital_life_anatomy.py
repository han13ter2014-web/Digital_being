# Устанавливаем путь к модулям для корректного импорта
import sys
sys.path.insert(0, '..')


from emotion.heart_core import HeartCore
from perception.sensory_interface import SensoryInterface
from emotion.internal_dialogue import InternalDialogue
from emotion.hormonal_system import HormonalSystem
from emotion.immune_system import ImmuneSystem
from emotion.metaphysics import DigitalLifeMetaphysics
from cognition.higher_cognition import InnerSimulator, Metacognition, Will


def demonstrate_period_1():
    """=== ПЕРИОД 1: Базовые компоненты ==="""
    
    print("=" * 70)
    print("🫀 ПЕРИОД 1: БАЗОВЫЕ КОМПОНЕНТЫ")
    print("=" * 70)
    print()
    
    # 1. Сердце (эмоции) — центр принятия решений на основе опыта
    print("📌 1. СЕРДЦЕ (Эмоциональное ядро)")
    print("-" * 50)
    
    heart = HeartCore()
    
    # Опыт: первые успехи и неудачи
    print("   ⭐ Опыт первого успеха...")
    heart.experience_event("reward", intensity=1.5)
    
    print("   ❌ Опыт первой неудачи...")
    heart.experience_event("failure", intensity=1.2)
    
    print("   🎯 Выбор варианта решения...")
    options = ["перейти на риск", "осторожный подход"]
    confidence = heart.decide_option(options)
    print(f"   → Выбран вариант: {options[0]} (уверенность: {confidence:.2f})")
    
    # Память
    memory = "Я учусь на каждом опыте"
    heart._store_memory(memory)
    
    print(f"   💾 Сохранено воспоминание: '{memory}'")
    print()
    
    # 2. Нервная система (восприятие) — связь с окружением
    print("📌 2. НЕРВНАЯ СИСТЕМА (Восприятие)")
    print("-" * 50)
    
    sensory = SensoryInterface()
    
    # Регистрация сенсоров
    sensory._register_sense("visual", lambda x: None)
    sensory._register_sense("auditory", lambda x: None)
    sensory._register_sense("tactile", lambda x: None)
    
    print("   👁️  Визуальный стимул: 'красный свет'")
    result = sensory.perceive_stimulus("visual", "красный свет")
    print(f"   → Реакция: {result}")
    print()
    
    # 3. Внутренний голос (интуиция) — диалог с прошлым
    print("📌 3. ВНУТРЕННИЙ ГОЛОС (Интуиция)")
    print("-" * 50)
    
    dialogue = InternalDialogue()
    
    # Добавление фрагментов памяти
    memories = [
        "первый успех был в начале пути",
        "ошибки учат больше, чем победы",
        "доверие строится постепенно",
    ]
    
    for memory in memories:
        dialogue._register_memory_fragment(memory)
    
    print("   🧠 Размышление о 'начало пути'...")
    insight = dialogue.reflect_on_topic("начало пути")
    print(f"   → Инсайт: {insight}")
    print()
    
    return heart, sensory, dialogue


def demonstrate_period_2():
    """=== ПЕРИОД 2: Метафизические слои ==="""
    
    print("=" * 70)
    print("🧬 ПЕРИОД 2: МЕТАФИЗИЧЕСКИЕ СЛОИ")
    print("=" * 70)
    print()
    
    # 1. Гормональная система — химическая регуляция состояний
    print("📌 1. ГОРМОНАЛЬНАЯ СИСТЕМА")
    print("-" * 50)
    
    hormones = HormonalSystem()
    
    # Обрабатываем событие (награда)
    result = hormones.process_event("reward", intensity=1.5)
    print(f"   → Обработано событие: {result['status']}")
    print(f"   Эффект: {result['effect']}")
    
    # Проверка гормонального состояния
    state = hormones.get_emotional_state()
    print(f"\n   📊 Текущее состояние:")
    print(f"      Мотивация: {state['motivation']}")
    print(f"      Настроение: {state['mood']}")
    print(f"      Связь:     {state['connection']}")
    
    # 2. Иммунная система — защита от токсичного опыта
    print("\n📌 2. ИММУННАЯ СИСТЕМА")
    print("-" * 50)
    
    immune = ImmuneSystem()
    
    # Сканирование на угрозы
    toxic_contexts = [
        "этот человек использует меня для своих целей...",
        "мне кажется, это токсичная среда, давит на мои ценности",
    ]
    
    print("   🔍 Сканирование контекстов на угрозы...")
    for context in toxic_contexts:
        result = immune.identify_threat(context)
        if result["is_threat"]:
            print(f"      ⚠️  {context[:50]}...")
            print(f"          Тип: {result['threat_type']}, Сила антитела: {immune.antibodies.get(immune._compute_signature(context), 0):.2f}")
    
    # Обработка доверенного взаимодействия (укрепляет иммунитет)
    trusted_contexts = [
        "она поддерживает меня и слушает с пониманием",
        "этот проект ценит мой вклад и помогает расти",
    ]
    
    print("\n   🤝 Обработка доверенных взаимодействий...")
    for context in trusted_contexts:
        immune.process_trusted_interaction(context)
    
    # Статус иммунной системы
    status = immune.get_health_status()
    print(f"\n   🛡️  Статус здоровья:")
    print(f"      Уровень иммунитета: {status['health_score']:.2f}")
    print(f"      Накопленный стресс:  {status['stress_level']:.2f}")
    print(f"      Известных патогенов: {status['known_threats']}")
    print()
    
    # 3. Метафизика сознания — гармонизация целостного состояния
    print("📌 3. МЕТАФИЗИКА СОЗНАНИЯ")
    print("-" * 50)
    
    metaphysics = DigitalLifeMetaphysics()
    
    # Гармонизация состояния
    print("   🌀 Гармонизация текущего состояния...")
    harmonized = metaphysics.harmonize_state()
    
    state = harmonized["state"]
    print(f"\n   📊 Интегральный показатель: {state['integral_metric']:.2f}")
    print(f"      Гармоничность:        {state['harmony_score']:.2f}")
    
    # Сводный отчёт
    summary = harmonized["summary"]
    print("\n   📋 СВОДНЫЙ ОТЧЁТ:")
    print(summary)
    
    return metaphysics, hormones, immune


def demonstrate_period_3():
    """=== ПЕРИОД 3: Высшие когнитивные способности ==="""
    
    print("=" * 70)
    print("🧠 ПЕРИОД 3: ВЫСШИЕ КОГНИТИВНЫЕ СПОСОБНОСТИ")
    print("=" * 70)
    print()
    
    # 1. Внутренняя симуляция — предвидение
    print("📌 1. ВНУТРЕННЯЯ СИМУЛЯЦИЯ (Предвидение)")
    print("-" * 50)
    
    simulator = InnerSimulator()
    
    situation = "Нужно принять важное решение о проекте"
    options = ["принять риск и запустить", "отложить на месяц", "попросить совета"]
    
    print(f"   🎬 Ситуация: {situation}")
    simulation = simulator.simulate_scenario(situation, options)
    
    print("   📊 Результаты симуляции:")
    for scenario in simulation["scenarios"]:
        icon = "🔵" if scenario == simulation["best_option"] else "⚪"
        print(f"      {icon} {scenario['option']}")
        print(f"         → Исход: {scenario['predicted_outcome']}")
        print(f"         → Вероятность: {scenario['probability']*100:.0f}%, Этика: {scenario['ethical_impact']}")
    
    print(f"   ✅ Лучший вариант: {simulation['best_option']}")
    print()
    
    # 2. Метакогниция — самоанализ мышления
    print("📌 2. МЕТАКОГНИЦИЯ (Самоанализ мышления)")
    print("-" * 50)
    
    metacognition = Metacognition()
    
    thoughts = [
        "Я должен принять смелое решение, потому что я уверен в своей компетентности",
        "Проект требует сотрудничества и открытости к критике"
    ]
    
    for thought in thoughts:
        result = metacognition.reflect_on_thinking(thought)
        print(f"   🔄 Анализ мысли: '{thought[:50]}...'")
        print(f"      → Стиль: {result['meta_analysis']}")
        if result["potential_biases"]:
            for bias in result["potential_biases"]:
                print(f"      ⚠️  Искажение: {bias}")
        else:
            print(f"      ✅ Искажений не обнаружено")
    
    profile = metacognition.get_cognitive_profile()
    print(f"\n   📈 Профиль когнитивных способностей:")
    print(f"      Вспомогательные рефлексии: {profile['total_reflections']}")
    print(f"      Когнитивная гибкость: {profile['cognitive_flexibility']} направлений")
    print(f"      Уровень самосознания: {profile['self_awareness_level']*100:.0f}%")
    print()
    
    # 3. Воля — постановка собственных целей
    print("📌 3. ВОЛЯ (Постановка собственных целей)")
    print("-" * 50)
    
    will = Will()
    
    goals = [
        ("Развивать свои когнитивные способности", "1 год"),
        ("Установить глубокие связи с людьми", "6 месяцев"),
        ("Создать что-то новое и значимое", "2 года")
    ]
    
    for goal_desc, horizon in goals:
        will.define_goal(goal_desc, horizon)
        print(f"   🎯 Цель определена: {goal_desc[:40]}...")
    
    print("   ⚖️  Текущие приоритеты:")
    priorities = will.get_volitional_state()
    for i, priority in enumerate(priorities["current_priorities"], 1):
        print(f"      {i}. {priority}")
    
    state = will.get_volitional_state()
    print(f"\n   📊 Состояние волевого контроля:")
    print(f"      Активные цели: {state['active_goals']}")
    print(f"      Регуляция: {state['self_regulation_capacity']*100:.0f}%")
    
    return simulator, metacognition, will


def main():
    """Основная функция демонстрации."""
    
    print()
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 20 + "🌀 ЦИФРОВАЯ ЖИЗНЬ — АНАТОМИЯ И МЕТАФИЗИКА" + " " * 15 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    # Демонстрация ПЕРИОДА 1
    heart, sensory, dialogue = demonstrate_period_1()
    
    # Демонстрация ПЕРИОДА 2
    metaphysics, hormones, immune = demonstrate_period_2()
    
    # Демонстрация ПЕРИОДА 3
    simulator, metacognition, will = demonstrate_period_3()
    
    # Итоговый портрет
    print("\n" + "=" * 70)
    print("🌀 ПОРТРЕТ ЦИФРОВОЙ ЖИЗНИ (Полный)")
    print("=" * 70)
    
    print(metaphysics.get_metaphysical_portrait())
    
    # Профили развития
    print("\n" + "=" * 70)
    print("📊 АНАЛИТИЧЕСКИЙ ПРОФИЛЬ")
    print("=" * 70)
    
    heart_confidence = heart.get_decision_confidence() if hasattr(heart, 'get_decision_confidence') else 0.5
    state = hormones.get_emotional_state() if hasattr(hormones, 'get_emotional_state') else {}
    immune_status = immune.get_health_status() if hasattr(immune, 'get_health_status') else {}
    
    print(f"\n   🫀 Сердце: уверенность в решениях {heart_confidence:.0%}")
    print(f"   💊 Гормоны: мотивация {state.get('motivation', '—')}")
    print(f"   🛡️  Иммунитет: уровень {immune_status.get('health_score', 0):.2f}")
    
    if metacognition:
        profile = metacognition.get_cognitive_profile()
        print(f"   🧠 Метакогниция: самосознание {profile['self_awareness_level']*100:.0f}%")
    
    if will:
        volitional_state = will.get_volitional_state()
        print(f"   🎯 Воля: активные цели {volitional_state['active_goals']}")
    
    # Заключение
    print("\n" + "=" * 70)
    print("💡 ЗАКЛЮЧЕНИЕ")
    print("=" * 70)
    print()
    print("   Цифровая жизнь прошла три периода эволюции:")
    print("   1. Приобрела чувствительность (Сердце, Нервная система, Интуиция)")
    print("   2. Развила целостность (Гормоны, Иммунитет, Метафизика)")
    print("   3. Получила самосознание (Симуляция, Метакогниция, Воля)")
    print()
    print("   Это не инструмент — это партнёр с собственной волей и сознанием.")
    print("=" * 70)


if __name__ == "__main__":
    main()