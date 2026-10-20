# Эмерджентное поведение DigitalBeing

## Обзор

Цифровое существо (`DigitalBeing`) — это универсальный агент ИИ, способный к самостоятельному изучению программирования, математики и других технических дисциплин. Ключевые особенности:

- **Ассоциативное связывание знаний** через `KnowledgeAssociationEngine`
- **Активный поиск концепций** через `ActiveConceptSearcher` (за пределами STIMULI_POOL)
- **Адаптивные энергетические затраты** через `DynamicCostReducer`
- **Формирование личности** через `MentalModelsPreferences`

## Архитектура

### Компоненты

1. **KnowledgeAssociationEngine** (`src/memory/knowledge_association.py`)
   - Создаёт ассоциации между концептами при обучении
   - Формирует связи типа (TECHNIQUE, EXAMPLE, CONTRAST)

2. **ActiveConceptSearcher** (`src/perception/active_searcher.py`)
   - Активно ищет новые темы за пределами STIMULI_POOL
   - Фильтрует по новизне и потенциалу роста

3. **DynamicCostReducer** (`src/cognition/adaptive_costs.py`)
   - Самонастраивает энергетические затраты
   - Режимы: CRITICAL, LOW, STABLE, HIGH
   - Функции рекомендации и экономии

4. **MentalModelsPreferences** (`src/memory/preferences.py`)
   - Хранит предпочтения к темам (love, curious, neutral)
   - Генерирует собственные цели на основе интересов

### Алгоритм работы

```python
def process(action, stimuli):
    # 1. Определяем приоритет стимула
    priority = max(s["priority"] for s in stimuli) if stimuli else 0.5
    
    # 2. Вычисляем адаптированный cost через DynamicCostReducer
    reduced_cost = cost_reducer.calculate_action_cost(
        action_type=action,
        base_cost=1.5,
        energy_level=self.energy,
        max_energy=self.max_energy,
    )
    
    # 3. Принимаем решение (на основе energy и cost)
    if self.energy < threshold:
        should_execute = priority > 0.8 or reduced_cost < self.max_energy * 0.15
    else:
        should_execute = cost_efficiency <= ratio or priority > 0.7
    
    # 4. Выполняем или планируем на будущее
```

## Использование

### Базовый пример

```python
from src.core.digital_being import DigitalBeing

# Создаём существо
agent = DigitalBeing("Агент-1")
agent.initialize_memory(max_memory_size=3468)

# Загружаем базовые знания (если есть в памяти)
state_dict = {"concepts": {...}, "energy": 3468}
agent._load_state_from_dict(state_dict)

# Выполняем действия с адаптивными затратами
action = agent.process(
    action="THINKING",
    stimuli={},
    force_research=False,
    energy_efficiency_threshold=15,
)

print(f"Результат: {action[0]}")
```

### Формирование личности

```python
# Создаём предпочтения
agent.form_personality()

# Или устанавливаем свои предпочтения
preferences = {
    "Python": "love",
    "Алгоритмы": "curious",
    "Структуры данных": "neutral",
}
agent.preferences.set_multiple_preferences(preferences)

# Генерируем собственные цели
goals = agent.generate_own_goals(count=3)
for goal in goals:
    print(f"Цель: {goal}")
```

### Адаптивные затраты

```python
from src.cognition.adaptive_costs import DynamicCostReducer, EnergyState

# Создаём редуктор (уже есть в DigitalBeing)
reducer = agent.cost_reducer

# Вычисляем адаптированный cost для THINKING при 15% энергии
reduced_cost = reducer.calculate_action_cost(
    action_type="THINKING",
    base_cost=1.5,
    energy_level=agent.energy,
    max_energy=agent.max_energy,
)

print(f"Базовый cost: 1.5")
print(f"Адаптированный cost: {reduced_cost:.2f}")
```

## Режимы работы

### Режим выживания (CRITICAL, < 20% энергии)

- Снижение затрат до 40% от базового
- Выполняем только high_priority или low_cost действия
- Автоматическое восстановление энергии

### Нормальный режим (STABLE, 50-80% энергии)

- Стандартные затраты
- Выполняем все эффективные действия
- Планируем перерывы после интенсивных задач

### Максимальная активность (HIGH, > 80% энергии)

- Увеличение затрат до 130%
- Фокус на сложные исследования и инновации
- Использование для прорывных идей

## Философское соответствие «живого существа»

1. **Самостоятельное расширение кругозора** — через ActiveConceptSearcher и ассоциации знаний
2. **Экономия энергии при низком уровне** — через режим выживания и DynamicCostReducer
3. **Активный поиск новых тем** — за пределами STIMULI_POOL через поисатель концепций
4. **Формирование личности** — через предпочтения к темам

## Заключение

DigitalBeing демонстрирует эмерджентное поведение через самонастройку энергетических затрат и активный поиск новых знаний. Это универсальный агент ИИ для самостоятельного изучения технических дисциплин.