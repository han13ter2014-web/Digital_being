# Digital Being: текущая интегрированная архитектура

Основная сущность — `src.core.agent.DigitalBeing`. Отдельный `ExtendedDigitalBeing` и функция `extend_agent()` больше не нужны: `extended_agent.py` сохранён только как deprecated-заглушка.

## Основные возможности

- единый контур мотивации, целей и арбитража;
- ментальные модели, знания и долгосрочная память;
- текстовое восприятие и социальная модель пользователя;
- эмоции, энергия, интероцепция и отдых;
- творческие занятия и явный экспорт черновика через Effector;
- наблюдаемые прогнозы, метакогниция, личность и мыслительные паттерны;
- чекпоинты, профили и безопасные предложения развития.

Архитектура не использует LLM: мышление и планирование детерминированы. Голос включён и использует доступные локальные движки с console-fallback; сетевые уведомления отправляются только при настроенных endpoint-ах.

## Базовый API

```python
from src.core.agent import DigitalBeing

agent = DigitalBeing("Example")
agent.set_goal("Изучить выбранную тему", difficulty=2)
print(agent.get_goals_status())
```

Для рабочего приложения профиль и жизненный цикл следует создавать через штатный запуск проекта, а не смешивать несколько независимых жизней в одном хранилище.

## Память

`LongTermMemory` хранит краткосрочные, консолидированные и эпизодические следы, учитывает важность, обращения и затухание. Основная жизнь владеет своим экземпляром; отдельная `KnowledgeAssociationEngine` удалена как дублирующий контур связей.

```python
agent.long_term_memory.store(
    content="Новый проверенный факт",
    importance=0.8,
    context="learning",
)
results = agent.long_term_memory.recall("факт")
```

## Цели

Используйте `DigitalBeing.set_goal()` и `GoalSubsystem`. Не импортируйте `MultiTaskGoalManager`: файл удалён вместе с другими параллельными менеджерами целей.

```python
goal_id = agent.set_goal("Подготовить заметку", difficulty=2)
agent.complete_goal(goal_id)
print(agent.get_all_goals_with_progress())
```

## Кооперация

Каждый агент получает собственный `agent.cooperation_hub`. Чтобы связать жизни, обоим явно назначают один хаб и регистрируют их по `life_id`:

```python
from src.core.agent import DigitalBeing
from src.cognition.agent_cooperation import AgentCooperationHub, MessageType

alpha = DigitalBeing("Alpha")
beta = DigitalBeing("Beta")
hub = AgentCooperationHub()
alpha.cooperation_hub = hub
beta.cooperation_hub = hub
hub.register_agent(alpha)
hub.register_agent(beta)

hub.send_message(
    alpha.life_id,
    beta.life_id,
    MessageType.REQUEST,
    "Опиши наблюдаемый результат",
)
messages = hub.get_pending_messages(beta.life_id)
```

Тик автономно обрабатывает входящие сообщения через безопасный `process_message()`. Знание из сообщения попадает в карантинную базу хаба, но не в память или цели получателя. Автономного сетевого общества этот адаптер не создаёт.

## Наблюдатели опыта

`IntegratedExperience` доступен как `agent.integrated_experience` и объединяет:

- `Personality` — нарратив и производные черты;
- `EmergenceEngine` — паттерны фактических действий;
- `ThinkingPatternLibrary` — статистику мыслительных паттернов;
- `HormonalSystem` — shadow-модель внутренней динамики.

Они получают реплики и исходы, но не добавляют кандидатов, не меняют оценки и не создают цели. Состояние входит в чекпоинт.

## Самоанализ без скрытой самомодификации

```python
performance = agent.evolution_analyzer.analyze_performance()
improvements = agent.evolution_analyzer.identify_improvements()
report = agent.evolution_analyzer.generate_self_report()
```

Эти вызовы анализируют состояние. Применение изменений через старый `apply_self_modification()` отсутствует; предложения проходят отдельный контур проверки и человеческого решения.

## Метрики и внешние адаптеры

- `agent.metrics` — временные ряды в памяти;
- `agent.i18n` — локализация;
- `agent.voice_router` — включён; доступные локальные движки имеют приоритет над console-fallback;
- `agent.webhooks` — worker запускается только при настроенных endpoint-ах.

Ответы пользователю передаются в голос и webhooks перед обычной доставкой в диалог. Без endpoint-ов сетевых отправок нет.

## Проверка и документы

```bash
.venv/Scripts/python.exe -m pytest -q
```

Актуальная карта модулей: `BIOLOGICAL_MAP.md`. Последовательность и границы интеграции: `INTERNAL_SIMULATOR_WORLD_DELTA_PLAN.md`.
