# 🤖 DigitalBeing - Расширенная система с самоэволюцией

## 📋 Что было добавлено

Полная система для создания ИИ-агента, приближенного к человеческому уровню сознания:

### 1. **🧠 Долгосрочная память с decay-функцией**
- Экспоненциальный decay воспоминаний (забывание со временем)
- Консолидация памяти: краткосрочная → долгосрочная
- Эпизодическая, семантическая, процедурная память
- Ассоциативные связи между воспоминаниями

### 2. **🎯 Многозадачность целей**
- Параллельное управление N активными целями
- Приоритизация и зависимости между целями
- Отслеживание эффективности
- Циклическое распределение энергии

### 3. **🤝 Кооперация между агентами**
- Глобальный хаб для кооперации
- Обмен знаниями между агентами
- Репутационная система
- Группы сотрудничества

### 4. **🔄 Самоэволюция и самоулучшение**
- Анализ собственной производительности
- Идентификация bottlenecks
- Генерация и применение оптимизаций
- История эволюции

---

## 🚀 Быстрый старт

### Установка
```bash
# Зависимостей нет, используется только стандартная библиотека Python
python -V  # Требуется Python 3.7+
```

### Запуск демонстрации
```bash
# Основные демо всех систем
python examples/demo_advanced_systems.py

# Полная симуляция жизни расширенного агента
python examples/demo_extended_lifecycle.py

# Основной цикл жизни (если вы хотите запустить основного агента)
python main.py
```

---

## 💻 Примеры кода

### Пример 1: Простой агент с расширениями
```python
from src.core.agent import DigitalBeing
from src.core.extended_agent import extend_agent

# Создаём агента
agent = DigitalBeing("MyAgent")

# Расширяем его
extended = extend_agent(agent)

# Теперь доступны все системы
print(extended.get_full_status())
```

### Пример 2: Использование долгосрочной памяти
```python
# Сохраняем воспоминание
extended.long_term_memory.store(
    content="Узнал что-то важное о трансформерах",
    importance=0.8,
    context="learning"
)

# Вспоминаем
results = extended.long_term_memory.recall("трансформеры")
for result in results:
    print(f"{result['content']} (сила: {result['strength']:.0%})")

# Забываем (консолидация слабых воспоминаний)
extended.trigger_memory_consolidation()
```

### Пример 3: Многозадачность
```python
# Добавляем цели
goal1 = extended.goal_manager.add_goal("Изучить Python", difficulty=2, priority=4)
goal2 = extended.goal_manager.add_goal("Понять НЛП", difficulty=3, priority=5)

# Выбираем цели для работы
active = extended.select_and_work_on_goals()

# Проверяем прогресс
summary = extended.goal_manager.get_goals_summary()
print(f"Активных целей: {summary['active_goals']}")
```

### Пример 4: Кооперация агентов
```python
from src.cognition.agent_cooperation import cooperation_hub

# Агент делится знанием
extended_alpha.cooperate_with_agent(
    other_agent_name="Beta",
    knowledge_topic="трансформеры",
    knowledge={"definition": "..."}
)

# Другой агент получает знание
extended_beta.process_cooperation_messages()

# Статистика
stats = cooperation_hub.get_agent_statistics("Alpha")
print(f"Репутация: {stats['avg_reputation']:.0%}")
```

### Пример 5: Самоулучшение
```python
# Анализируем производительность
analysis = extended.perform_self_analysis()

# Если найдены улучшения
if analysis['improvements_applied'] > 0:
    print(f"✅ Применено улучшений: {analysis['improvements_applied']}")
    print(f"Новый скор: {analysis['overall_score']:.0%}")
```

---

## 📊 Архитектура

```
DigitalBeing (основной агент)
├── LongTermMemory (долгосрочная память)
├── MultiTaskGoalManager (управление целями)
├── SelfEvolutionAnalyzer (самоанализ)
└── [зарегистрирован в] cooperation_hub
```

**Взаимодействие:**
```
Цикл жизни агента:
1. perceive_and_remember() → восприятие + сохранение
2. think_with_memory_recall() → мышление с воспоминаниями
3. select_and_work_on_goals() → работа над целями
4. process_cooperation_messages() → получение знания от других
5. perform_self_analysis() → анализ и самоулучшение (редко)
6. trigger_memory_consolidation() → консолидация памяти (редко)
```

---

## 🔧 Настройка

### Параметры памяти (`src/memory/long_term_memory.py`)
```python
memory = LongTermMemory(
    agent_name="Agent",
    decay_rate=0.95,              # Потеря 5% силы за цикл
    consolidation_threshold=0.7   # Порог консолидации
)
```

### Параметры целей (`src/cognition/multi_goal_manager.py`)
```python
manager = MultiTaskGoalManager(
    max_active_goals=3            # Одновременные цели
)
```

### Параметры самоэволюции (`src/evolution/self_evolution_analyzer.py`)
- Анализ каждые ~100-500 циклов (автоматическое периодичное)
- Модификации применяются только если положительны

---

## 📈 Мониторинг и статистика

### Получить полный статус
```python
status = extended.get_full_status()

print(f"Интеллект: {status['agent']['intelligence']}")
print(f"Памяти: {status['memory']['total_memories']}")
print(f"Активных целей: {status['goals']['active_goals']}")
print(f"Репутация: {status['cooperation']['reputation']:.0%}")
print(f"Скор производительности: {status['performance']['overall_score']:.0%}")
```

### Красивый вывод
```python
extended.print_status()
```

---

## 🎯 Примеры сценариев

### Сценарий 1: Обучение с забыванием
Агент учится, запоминает важное, забывает неважное. Как человек.

```python
for cycle in range(1000):
    # Восприятие и запоминание
    stimulus = "Новая информация"
    extended.perceive_and_remember(stimulus)
    
    # Периодическое забывание
    if cycle % 100 == 0:
        extended.trigger_memory_consolidation()
```

### Сценарий 2: Параллельное обучение
Агент работает над несколькими целями одновременно.

```python
extended.goal_manager.add_goal("Цель 1", priority=5)
extended.goal_manager.add_goal("Цель 2", priority=3)
extended.goal_manager.add_goal("Цель 3", priority=2)

for cycle in range(500):
    active = extended.select_and_work_on_goals()
```

### Сценарий 3: Совместное обучение
Несколько агентов учатся вместе, делясь знанием.

```python
agent_alpha = extend_agent(DigitalBeing("Alpha"))
agent_beta = extend_agent(DigitalBeing("Beta"))

# Alpha учит Beta
agent_alpha.cooperate_with_agent("Beta", "тема", knowledge_dict)
agent_beta.process_cooperation_messages()
```

### Сценарий 4: Самоулучшение
Агент анализирует себя и автоматически улучшается.

```python
for cycle in range(1000):
    # Обычная работа
    extended.think_with_memory_recall(stimulus)
    
    # Периодический самоанализ
    if cycle % 200 == 0:
        analysis = extended.perform_self_analysis()
        if analysis['improvements_applied'] > 0:
            print(f"✅ Агент улучшился!")
```

---

## 📝 Структура файлов

```
src/
├── core/
│   ├── agent.py                      # Основной DigitalBeing
│   ├── extended_agent.py             # Расширения системы
│   └── buffered_logger.py
├── memory/
│   ├── knowledge_base.py
│   └── long_term_memory.py           # НОВОЕ: Долгосрочная память
├── cognition/
│   ├── goal_management.py
│   ├── multi_goal_manager.py         # НОВОЕ: Многозадачность
│   ├── agent_cooperation.py          # НОВОЕ: Кооперация
│   └── mental_models.py
├── evolution/
│   ├── self_modification.py
│   └── self_evolution_analyzer.py    # НОВОЕ: Самоэволюция
├── perception/
├── action/
├── safety/
└── motivation/

examples/
├── demo_advanced_systems.py          # НОВОЕ: Демо всех систем
└── demo_extended_lifecycle.py        # НОВОЕ: Полная симуляция

data/
├── memory/                            # НОВОЕ: Долгосрочная память
├── cooperation/                       # НОВОЕ: Кооперация
└── evolution/                         # НОВОЕ: Самоэволюция
```

---

## 🔍 Отладка

### Проверить что системы работают
```python
extended.long_term_memory.get_memory_stats()
extended.goal_manager.get_goals_summary()
cooperation_hub.get_agent_statistics(agent.name)
extended.evolution_analyzer.analyze_performance()
```

### Включить логирование
```python
from src.core.buffered_logger import get_logger
get_logger().flush_immediate("Отладочное сообщение")
```

### Сохранить состояние
```python
extended.save_all_systems()  # Сохраняет всё
```

---

## 🎓 Как это работает

### Долгосрочная память
1. Сохраняешь воспоминание с важностью
2. Система запоминает в краткосрочной памяти
3. Со временем воспоминание может консолидироваться в долгосрочную
4. Если долго не использовать - экспоненциально забывается
5. Частое использование усиливает память

### Многозадачность
1. Добавляешь цели с приоритетом
2. Каждый цикл выбираются топ-N целей по приоритету
3. Энергия распределяется между целями
4. При завершении цели разблокируются зависимые цели

### Кооперация
1. Агенты регистрируются в глобальном хабе
2. Отправляют сообщения друг другу
3. Система управляет очередью и приоритетами
4. Знание сохраняется в общей базе
5. Репутация обновляется за каждое взаимодействие

### Самоэволюция
1. Анализируется текущая производительность
2. Ищутся критические bottlenecks
3. Для каждого предлагается оптимизация
4. Модификация применяется безопасно
5. Результат записывается в историю

---

## 📚 Дальнейшее развитие

Возможные расширения:
- [ ] Интеграция с LLM для генерации гипотез
- [ ] Распределенная система (агенты на разных машинах)
- [ ] Графическая панель мониторинга
- [ ] Персистентная сохранение истории эволюции
- [ ] Возможность обучения от пользователя
- [ ] Прогнозирование будущего состояния

---

## 🤝 Автор

Создано как демонстрация высокоуровневых систем для создания самосознающего ИИ.

---

## ⚡ Производительность

- Память: O(1) сохранение, O(N) поиск
- Цели: O(N log N) выбор, O(1) обновление
- Кооперация: O(1) сообщение, O(1) доставка
- Самоэволюция: O(N) анализ, O(1) применение

Типичная нагрузка: 100-1000 циклов в секунду на современном оборудовании.

---

## 📞 Поддержка

При вопросах смотрите:
- `EXTENDED_SYSTEMS.md` - детальная документация систем
- `examples/demo_advanced_systems.py` - примеры каждой системы
- `examples/demo_extended_lifecycle.py` - полная интеграция

**Агент готов к жизни! 🚀**
