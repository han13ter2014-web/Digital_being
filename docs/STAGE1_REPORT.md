# Этап 1 — отчёт

Цель этапа: остановить потери (лог, декомпозиция, энергия, повторы),
не рефакторя `agent.py` и не добавляя новых подсистем.

## 1. Что исправлено

| # | Дефект | Исправление |
|---|--------|-------------|
| 1 | `agent_log.txt` вырос до 420 МБ без ротации | `BufferedLogger`: ротация 10 МБ × 3 бэкапа; `main_tray.py`: `RotatingFileHandler` 5 МБ × 3 |
| 2 | «что такое такое» — 252 938 повторов в логе | `_decompose_query`: стоп-слова, «что такое X» больше не дробится, фильтр глагольных форм, дедупликация |
| 3 | Энергия уходила в −2.34 | `EnergySubsystem.energy` — свойство с клампом `[0, max_energy]`; `is_exhausted()`; истощение ≠ смерть |
| 4 | Один стимул повторялся 13 596 раз | `select_novel_stimulus` + `STIMULUS_COOLDOWN_TICKS = 20`: стимул не повторяется раньше, чем через 20 тиков; если все «скучны» — тик отдыха |
| 5 | Побочный эффект, найденный прогоном | `normalize_concept_name`: «что такое счастье» → узел «счастье», а не узел-фраза |

Пункт 5 появился не из плана: после фикса декомпозиции простые вопросы
стали доходить до регистрации концепта и создавать узлы вида
«что такое счастье». Нормализация имён убирает этот класс загрязнения.

## 2. Замер до/после

Методика: один и тот же harness `tools/stage1_smoke.py`, 500 циклов,
offline (Wikipedia отключён), изолированная временная папка.
«До» — git-worktree на коммите `3f86433` (этап 0), «после» — рабочее дерево этапа 1.

```
python tools/stage1_smoke.py --cycles 500 --json after500.json
```

| Метрика | До | После |
|---|---:|---:|
| `что такое такое` в логе | **93** | **0** |
| Максимум повторов одного действия | **33** | **23** |
| Уникальных действий | 49 | 49 |
| Строк лога | 3053 | 3055 |
| Новых концептов | 8 | 27 |
| Служебных слов среди новых концептов | 0 | 0 |
| Минимум энергии | 0.05 | 0.03 |
| Ошибок | 0 | 0 |

Выводы:

* Декомпозиция: 18.6 % циклов больше не порождают бессмысленный под-вопрос.
* Кулдаун: худший случай повтора снизился с 33 до 23 за 500 циклов.
  Это **разрежение**, а не сокращение объёма: лог всё равно пишет каждый цикл.
  Объём ограничивает ротация (пункт 1), а не дедупликация — так и задумано.
* Новых концептов стало больше (8 → 27), потому что простые вопросы
  «что такое X» теперь не съедаются декомпозицией, а доходят до регистрации.
  Имена проверены: `счастье`, `сознание`, `свобода`, `мышление`, … —
  без «что такое …» и без служебных слов.
* Минимум энергии ≥ 0 в обоих прогонах: в этом сценарии срабатывает
  interoception (агент блокирует действие при истощении). Клэмп —
  жёсткий инвариант для всех остальных путей записи энергии, включая
  чекпоинты и прямые `agent.energy -= ...`.

## 3. Ротация логов

* `src/core/buffered_logger.py`: `max_bytes=10 МБ`, `backup_count=3`,
  проверка в `flush()` и `flush_immediate()`; `max_bytes=0` отключает ротацию.
* `main_tray.py`: `RotatingFileHandler(maxBytes=5 МБ, backupCount=3)`.
* Потолок: ~40 МБ на `agent_log.txt` и ~20 МБ на `tray_agent.log`
  вместо неограниченного роста.

## 4. Энергия

* `energy` — свойство `EnergySubsystem`, всегда `[0, max_energy]`.
  Это покрывает `agent.energy`, `energy_subsystem.energy`, `restore_from_checkpoint`
  и прямые `-=` в `thinking_pipeline`/`primitive_triggers`.
* `is_alive()` → `energy >= 0`; новый `is_exhausted()` → `energy <= 0`.
* `DigitalBeing.is_alive()`: смерть только при `energy < 0`, то есть
  при 0 агент жив, но устал. `max_cycles` по-прежнему работает.

## 5. Тесты

* Новый файл `tests/test_stage1_fixes.py` — 21 тест:
  декомпозиция, регистрация концептов, ротация, клампы энергии, кулдаун.
* Существующие: 147 тестов в затронутых модулях — зелёные.

```
python -m pytest tests/test_stage1_fixes.py -q
python -m pytest tests/test_stimulus_selector.py tests/test_integration.py ^
  tests/test_checkpoint_serializer.py tests/test_tray_foundation.py ^
  tests/test_open_questions_manager.py tests/test_tray_open_questions.py ^
  tests/test_basic_knowledge.py tests/test_evolve_pipeline.py -q
```

## 6. Изменённые файлы

* `src/core/buffered_logger.py` — ротация
* `main_tray.py` — `RotatingFileHandler`
* `src/cognition/thinking_pipeline.py` — декомпозиция, стоп-слова,
  `normalize_concept_name`
* `src/core/subsystems/energy_economics.py` — кламп энергии, `is_exhausted`
* `src/core/agent.py` — семантика `is_alive`
* `src/core/stimulus_selector.py` — `select_novel_stimulus`, `is_open_question_stimulus`
* `src/core/agent_runner.py` — кулдаун, тики отдыха, `idle_ticks`
* `config/simulation_config.py` — `STIMULUS_COOLDOWN_TICKS`
* `tests/test_stage1_fixes.py` — новый
* `tools/stage1_smoke.py` — новый harness для сравнения до/после

## 7. Что осталось на этап 2

* Мусор в KB: `Меня`, `Ты`, `?`, `Альфа`, `Малютка` (Wikipedia-фоллбэк).
* Фильтр внешнего поиска: не сохранять ответы на служебные запросы.
* Качество извлечения концептов: остались `число 42`, `символ x`, `этика ии`.
* `tests/test_tray_smoke.py` не является pytest-тестом (этап 3).
