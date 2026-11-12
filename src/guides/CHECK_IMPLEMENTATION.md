# Проверка интеграции Digital Being

Этот документ описывает текущую архитектуру. Ранние отчёты о `MultiTaskGoalManager`, глобальном `cooperation_hub` и демонстрациях `demo_advanced_systems.py` / `demo_extended_lifecycle.py` относятся к удалённому параллельному контуру и больше не являются инструкциями по запуску.

## Канонические управляющие системы

- Цели: `GoalSubsystem`, публичные методы `DigitalBeing.set_goal()`, `complete_goal()` и `get_goals_status()`.
- Выбор действия: `DecisionArbitrator` и `SoulController`.
- Эмоции: `EmotionalState`.
- Тело и ресурсы: `EmbodimentController`, `EnergySubsystem`, `Interoception`.
- Ценности: `ValueEvolution`; дополнительные модели личности не создают второй источник управления.
- Безопасные переходы жизни: `LifeGuard`.

Старые `multi_goal_manager.py`, `goal_management.py`, `core/goal_manager.py`, `higher_cognition.py`, `lifecycle_manager.py`, `primitive_triggers.py` и другие параллельные реализации удалены.

## Подключённые наблюдатели

- `InternalSimulator` получает кандидатов и фактические `ActionOutcome` / `WorldDelta` в `shadow`-режиме.
- `MetaLearner` записывает fitness с `adapt=False`, не меняя конфигурацию.
- `ContinuousTimeEngine` связывает намерение, прогноз и фактический исход.
- `SocialCell` получает реплику пользователя один раз через общий социальный вход.
- `SensoryInterface` наблюдает текст, не подменяя stimulus.
- `MetaCognitiveSystem` наблюдает намерения и исходы, но не управляет арбитражем.
- `IntegratedExperience` передаёт фактический опыт в `Personality`, `EmergenceEngine`, `ThinkingPatternLibrary` и `HormonalSystem`.

## Локальные адаптеры

- `AgentCooperationHub` создаётся на каждую жизнь; общий хаб передаётся явно.
- Идентификатором кооперации является только непустой `life_id`.
- `tick()` автономно обрабатывает входящую очередь; знание карантинируется, а не записывается автоматически в память.
- `MetricsCollector` работает в памяти и не пишет временные ряды на диск сам.
- `I18n` доступен как отдельный per-instance адаптер.
- `VoiceRouter` включён: доступные локальные движки имеют приоритет над console-fallback; тесты не загружают аудиомодели.
- `WebhookManager` запускает worker только при настроенных endpoint-ах и останавливает его вместе с `AgentRunner`.

## Исполнение и развитие

- Effector остаётся опциональным; Core нормализует и `EffectorResult`, и mapping отчёта драйвера.
- `DigitalBeing.export_creative_draft()` экспортирует только уже существующий черновик по явному вызову.
- `SelfEvolutionAnalyzer` анализирует состояние и предлагает улучшения, но не применяет самомодификации.
- LLM/Ollama-планировщик удалён; Delamain использует детерминированный планировщик и явные планы.

## Сохранение

Чекпоинт включает секции `integrated_experience`, `cooperation`, `meta_cognition` и данные остальных подключённых систем. Восстановление выполняется в две фазы: сначала проверка и подготовка, затем применение. Старые снимки без новых секций восстанавливаются с пустым состоянием соответствующих модулей.

## Проверка

Из корня проекта используется проектное окружение:

```bash
.venv/Scripts/python.exe -m pytest -q
```

Дополнительная статическая проверка:

```bash
python -m compileall -q src
```

Интеграционные связи сосредоточены в `tests/test_life_systems_bridge.py`, `tests/test_integrated_experience.py`, `tests/test_core_effector_result.py` и связанных тестах чекпоинтов. Пользовательские `data/` для тестового запуска не нужны: тестовая инфраструктура изолирует изменяемые данные.
