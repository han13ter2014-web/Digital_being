# 🤖 Расширенные системы DigitalBeing

Четыре новые мощные системы, которые превращают агента в существо, приближенное к человеческому уровню сознания.

---

## 1. 🧠 Долгосрочная память с decay-функцией

**Файл:** `src/memory/long_term_memory.py`

### Особенности:
- **Экспоненциальный decay** воспоминаний (забывание со временем)
- **Двухуровневая память**: краткосрочная → долгосрочная (консолидация)
- **Эпизодическая память** для отслеживания событий
- **Ассоциативные связи** между воспоминаниями
- **Запрос** воспоминаний с релевантностью и силой

### Использование:
```python
from src.memory.long_term_memory import LongTermMemory

memory = LongTermMemory("Agent_name", decay_rate=0.95)

# Сохраняем воспоминание
memory.store(
    content="Узнал что-то важное о трансформерах",
    importance=0.8,  # 0.0-1.0
    context="learning",
    memory_type="episodic"
)

# Вспоминаем
results = memory.recall("трансформеры", threshold=0.1, max_results=5)
for result in results:
    print(f"{result['content']} (сила: {result['strength']:.0%})")

# Запускаем процесс забывания
memory.trigger_decay()

# Сохраняем на диск
memory.save()
```

### Параметры decay:
- `decay_rate=0.95` → потеря 5% силы за цикл времени
- `importance` влияет на скорость забывания (важные помнятся дольше)
- `access_count` усиливает память (частый доступ = лучше помнится)

---

## 2. 🎯 Многозадачность целей

**Файл:** `src/cognition/multi_goal_manager.py`

### Особенности:
- **Одновременное управление** несколькими целями (до N активных)
- **Состояния целей**: PENDING → ACTIVE → PAUSED → COMPLETED
- **Приоритизация** и **зависимости** между целями
- **Отслеживание прогресса** и **эффективности**
- **Циклическое распределение** энергии между целями

### Использование:
```python
from src.cognition.multi_goal_manager import MultiTaskGoalManager

manager = MultiTaskGoalManager(max_active_goals=3)

# Добавляем цели
goal1 = manager.add_goal("Изучить Python", difficulty=2, priority=3)
goal2 = manager.add_goal("Понять НЛП", difficulty=3, priority=5)
goal3 = manager.add_goal("Написать статью", difficulty=2, priority=2)

# Устанавливаем зависимость (goal3 блокирована goal1)
goal3.blocked_by.append(goal1.id)

# Выбираем цели для текущего цикла
cycle_goals = manager.select_goals_for_cycle(available_energy=100)

# Обновляем прогресс
manager.update_goal_progress(goal1.id, 0.25)

# Завершаем цель
reward = manager.complete_goal(goal1.id)

# Смотрим эффективность
efficiency = manager.get_goal_efficiency(goal1.id)
print(f"Циклов на 1%: {efficiency['cycles_per_percent']}")

# Визуализация
print(manager.visualize_goals())
```

### Стратегия выбора целей:
1. Активируются новые цели если есть место (respecting dependencies)
2. Сортируются по приоритету и времени затраченному
3. Распределяется энергия между ними циклически

---

## 3. 🤝 Кооперация между агентами

**Файл:** `src/cognition/agent_cooperation.py`

### Особенности:
- **Глобальный хаб** для всех агентов (singleton)
- **Типы сообщений**: REQUEST, RESPONSE, SHARE_KNOWLEDGE, COLLABORATE, QUERY
- **Общая база знаний** по темам
- **Репутационная система** между агентами
- **Группы сотрудничества** (N агентов работают вместе)

### Использование:
```python
from src.cognition.agent_cooperation import cooperation_hub, MessageType

# Регистрируем агентов
cooperation_hub.register_agent(agent1)
cooperation_hub.register_agent(agent2)

# Создаём группу сотрудничества
cooperation_hub.create_collaboration_group("nlp_team", ["agent1", "agent2"])

# Агент1 делится знанием с группой
cooperation_hub.share_knowledge_in_group(
    group_id="nlp_team",
    agent_id="agent1",
    topic="трансформеры",
    knowledge={"definition": "...", "reliability": 0.85}
)

# Агент2 ищет знание
result = cooperation_hub.query_knowledge("agent2", "трансформеры")
if result['found']:
    print(f"Найдено у: {result['sources']}")

# Агент1 просит помощь
cooperation_hub.request_help(
    from_agent_id="agent1",
    to_agent_id="agent2",
    problem_description="Как работает внимание?",
    urgency=3
)

# Получить ожидающие сообщения
messages = cooperation_hub.get_pending_messages("agent2", message_type=MessageType.QUERY)

# Статистика
stats = cooperation_hub.get_agent_statistics("agent1")
print(f"Репутация: {stats['avg_reputation']:.0%}")
print(f"Активных сотрудничеств: {stats['active_collaborations']}")
```

### Репутационная система:
- Начальная репутация: 0.5 (нейтральная)
- Общение увеличивает репутацию (+0.1 за операцию)
- Используется для выбора надежных источников знаний

---

## 4. 🔄 Самоэволюция и самоулучшение

**Файл:** `src/evolution/self_evolution_analyzer.py`

### Особенности:
- **Анализ производительности**: энергия, цели, обучение, память, качество
- **Идентификация bottlenecks**: что нужно улучшить
- **Генерация код-предложений**: конкретные изменения
- **Применение модификаций**: оптимизация параметров
- **Историч изменений**: отслеживание эволюции

### Использование:
```python
from src.evolution.self_evolution_analyzer import SelfEvolutionAnalyzer

analyzer = SelfEvolutionAnalyzer(agent)

# Анализируем производительность
performance = analyzer.analyze_performance()
print(f"Энергоэффективность: {performance['energy_efficiency']:.0%}")
print(f"Качество концепций: {performance['concepts_quality']:.0%}")
print(f"ОБЩИЙ СКОР: {performance['overall_score']:.0%}")

# Ищем улучшения
improvements = analyzer.identify_improvements()
for improvement in improvements:
    print(f"[{improvement['severity']}] {improvement['description']}")

# Генерируем предложение
suggestion = analyzer.generate_code_suggestion(improvements[0])
if suggestion:
    print(f"Текущее: {suggestion['current']}")
    print(f"Предложено: {suggestion['suggested']}")
    print(f"Ожидаемое улучшение: +{suggestion['estimated_impact']:.0%}")

    # Применяем
    if analyzer.apply_self_modification(suggestion):
        print("✅ Модификация успешно применена!")

# Генерируем отчет о самоанализе
report = analyzer.generate_self_report()
for rec in report['recommendations']:
    print(f"• {rec}")
```

### Метрики анализа:
1. **Energy Efficiency** = (goals * 10 + concepts) / energy_spent
2. **Goal Completion Rate** = completed / total_goals
3. **Learning Speed** = concepts / cycles
4. **Memory Efficiency** = high_confidence / total_concepts
5. **Concepts Quality** = average_confidence

### Типы модификаций:
- `parameter_adjustment`: Изменение параметров (затраты энергии, пороги и т.д.)
- `enable_feature`: Включение/отключение фич (гипотезирование, проверка, и т.д.)

---

## 📝 Интеграция в DigitalBeing

Для полной интеграции нужно добавить в `src/core/agent.py`:

```python
from src.memory.long_term_memory import LongTermMemory
from src.cognition.multi_goal_manager import MultiTaskGoalManager
from src.cognition.agent_cooperation import cooperation_hub
from src.evolution.self_evolution_analyzer import SelfEvolutionAnalyzer

class DigitalBeing:
    def __init__(self, name="Lucy"):
        # ... существующий код ...
        
        # Новые системы
        self.long_term_memory = LongTermMemory(name)
        self.goal_manager = MultiTaskGoalManager(max_active_goals=3)
        self.evolution_analyzer = SelfEvolutionAnalyzer(self)
        
        # Регистрируемся в системе кооперации
        cooperation_hub.register_agent(self)
    
    def think(self, data):
        # Запоминаем входные данные
        self.long_term_memory.store(
            content=str(data),
            importance=0.5,
            context="perception"
        )
        
        # ... существующий think код ...
    
    def evolve(self):
        # ... существующий evolve код ...
        
        # Периодический самоанализ
        if self.cycle_count % 100 == 0:
            improvements = self.evolution_analyzer.identify_improvements()
            if improvements:
                suggestion = self.evolution_analyzer.generate_code_suggestion(improvements[0])
                if suggestion:
                    self.evolution_analyzer.apply_self_modification(suggestion)
    
    def save_state(self):
        # ... существующий save_state код ...
        self.long_term_memory.save()
        self.evolution_analyzer._save_history()
```

---

## 🎯 Примеры сценариев

### Сценарий 1: Параллельное обучение
```
Agent работает над 3 целями одновременно:
- Изучение Python (40% энергии, приоритет 3)
- Понимание НЛП (50% энергии, приоритет 5)  
- Социализация (10% энергии, приоритет 1)

Каждый цикл распределяет энергию между целями в зависимости от приоритета
```

### Сценарий 2: Совместное обучение
```
Alpha учит Beta про трансформеры:
1. Alpha > cooperation_hub: "Поделиться знанием"
2. Beta получает сообщение
3. Beta интегрирует знание в свои концепции
4. Репутация Alpha повышается в глазах Beta
```

### Сценарий 3: Самоулучшение
```
Цикл 100:
1. Анализ: "Энергоэффективность 35% (низко!)"
2. Поиск: "Действия стоят слишком дорого"
3. Предложение: "Снизить затраты на 30%"
4. Применение: action_costs *= 0.7
5. Результат: +15% эффективность

Цикл 200:
1. Анализ: "Очень много концепций (700)"
2. Поиск: "Забывание недостаточно активно"  
3. Предложение: "Включить агрессивное забывание"
4. Применение: FORGETTING_ENABLED = True
```

---

## 🚀 Включение систем в main.py

В `main.py` добавьте:

```python
# Периодическая работа с долгосрочной памятью
if cycle_count % 10 == 0:
    agent.long_term_memory.trigger_decay()

# Многозадачность целей
active_goals = agent.goal_manager.select_goals_for_cycle(agent.energy)
print(agent.goal_manager.visualize_goals())

# Проверка кооперации
if cycle_count % 50 == 0:
    print(cooperation_hub.visualize_network())

# Самоанализ (редко)
if cycle_count % 500 == 0:
    report = agent.evolution_analyzer.generate_self_report()
    for rec in report['recommendations']:
        print(f"Самоанализ: {rec}")
```

---

## 📊 Статистика и мониторинг

```python
# Долгосрочная память
stats = agent.long_term_memory.get_memory_stats()
print(f"Памяти: {stats['total_memories']} (long: {stats['long_term_count']})")

# Цели
summary = agent.goal_manager.get_goals_summary()
print(f"Целей активно: {summary['active_goals']}/{agent.goal_manager.max_active_goals}")

# Кооперация  
coop_stats = cooperation_hub.get_agent_statistics(agent.name)
print(f"Репутация: {coop_stats['avg_reputation']:.0%}")

# Самоэволюция
perf = agent.evolution_analyzer.analyze_performance()
print(f"Общий скор: {perf['overall_score']:.0%}")
```

---

## 🔧 Настройка параметров

### Память
```python
LongTermMemory(
    agent_name="Agent",
    decay_rate=0.95,        # 5% потери за цикл
    consolidation_threshold=0.7  # Переход в долгосрочную
)
```

### Цели
```python
MultiTaskGoalManager(
    max_active_goals=3      # Одновременные цели
)
```

### Кооперация
```python
# В конфиге задайте количество сообщений в приоритете
cooperation_hub.message_queue  # Автоматический приоритет
```

### Самоэволюция
```python
# Анализируется каждые N циклов
# Модификации применяются только если положительны
```

---

## ⚡ Производительность

- **Долгосрочная память**: O(1) для сохранения, O(N) для поиска
- **Цели**: O(1) для обновления, O(N) для выбора
- **Кооперация**: O(1) для отправки, O(1) для получения
- **Самоэволюция**: O(N) анализ, ~O(1) для применения

---

**Всё готово к запуску! Агент теперь может эволюционировать самостоятельно.**
