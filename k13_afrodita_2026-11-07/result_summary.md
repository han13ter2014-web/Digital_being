# K13 — Афродита: мосты памяти и доведение намерений

Дата завершения: 2026-11-07
Ветка: `kimi/k13-memory-intent-bridges`
HEAD до и после работы: `c58e30d210126070e697676301b254457510023b`

## Итог

Все шесть пунктов тикета реализованы. Изменения оставлены в рабочем дереве без commit, merge и push. Живая Афродита не запускалась; все тестовые записи создавались только в изолированных каталогах внутри `k13_afrodita_2026-11-07/`.

## Что изменено

1. **Мост записи → ответа.** Добавлен `src/core/dialogue_memory.py`: детерминированный разбор вопросов «Что такое…», «Что значит…», «Что ты знаешь про…» и «Расскажи про…». Ответ строится из свидетельства пользователя, `_known_definitions` или сохранённой гипотезы; поддерживаются осторожные корневые совпадения вроде `изучать ↔ изучение`.
2. **Персистентные факты.** Вопросы об имени получают факты из `naming_dialogue.get_name_history()`: имя, цикл и источник. Если календарная дата или причина не сохранены, ответ прямо сообщает об этом и не реконструирует их. Добавлены ответы из записей пользователя и перечислительный ответ «Что ты умеешь из просьб?».
3. **Тема `web_search`.** `autonomous_tick()` передаёт активное намерение в `act()`, а `_act_web_search(target=...)` использует `intent.params.target`. Селектор свободной темы вызывается только при отсутствии явной темы.
4. **Первое уточнение.** `DialogueLearning.immediate_candidate()` подключает существующий протокол 1–4 с первой непонятой реплики. Автообучения до ответа человека нет; learned/suppressed/noise и cooldown по-прежнему исключают предложение.
5. **Женский род.** Исправлены шаблоны самоописаний в `agent.py`, `agent_runner.py`, `naming_dialogue.py`, `proactive_communication.py` и `mind_dream.py`, включая обычные и ошибочные исходы действий.
6. **Автоснапшот диалога.** В `finally` каждого `_tick_once()` журналируется `logs/dialogue_cycles.jsonl`: UTC-время, агент, цикл, tick, ledger, checkpoint диалога и последние 100 входящих/исходящих сообщений. Файл дополняется между запусками; Core-checkpoint не расширяется. Ошибка журнала не останавливает жизненный цикл.

Запрещённые контуры не изменялись: `ThinkingPipeline`, арбитратор, мотивация, гейты, LOOP-контур, эмоциональный контур, `user_definition`, naming protect/cancel, care и curiosity-связывания.

## Критерии приёмки

| Критерий | Проверка | Результат |
|---|---|---|
| Ответ из записи вместо `unknown_reply` | 4 параметризованных вопроса + отдельный тест `_known_definitions` | Пройдено |
| Факт имени без выдуманных даты и причины | `test_name_fact_does_not_invent_date_or_reason` | Пройдено |
| Три поиска подряд по теме намерения | `test_three_web_searches_use_active_intention_target` | Пройдено |
| Свободная тема только без намерения | `test_web_search_without_intention_keeps_exploration_fallback` | Пройдено |
| Перечисление доступных просьб | `test_capabilities_request_gets_enumerated_answer` | Пройдено |
| Протокол 1–4 с первой реплики, обучение по ответу | `test_first_unknown_asks_category_and_answer_one_still_teaches` | Пройдено |
| Оба участника диалога в журнале и доступ после нового runner | `test_dialogue_snapshot_contains_both_sides_and_survives_new_runner` | Пройдено |
| Автоматический снимок после цикла | `test_tick_once_automatically_appends_dialogue_snapshot` | Пройдено |
| Женский род, включая ошибку отправки | 2 профильных проверки самоописаний | Пройдено |

## Тестовые гейты

- Профиль K13: **15 passed**.
- Связанные диалоговые контуры: **222 passed**.
- Полный набор после финальных правок: **2110 passed, 2 skipped, 2 warnings**.
- Предупреждения — только два существующих `DeprecationWarning` о `main_tray.py` в `tests/test_main_tray_shim.py`.
- `git diff --check`: ошибок нет.

Команда финального полного гейта:

```bash
DIGITAL_BEING_DATA_DIR='C:/digital_being/k13_afrodita_2026-11-07/pytest_data_full_release' .venv/Scripts/python.exe -m pytest -q
```

## Неизменность `data/`

Финальная сверка после полного гейта: **98/98 совпадений SHA-256**.

- baseline: 98 файлов;
- текущее состояние: 98 файлов;
- изменённые: `[]`;
- отсутствующие: `[]`;
- дополнительные: `[]`.

Доказательства: `data_hashes_before.json`, `data_hashes_after.json`, `data_verification.json`; проверочный скрипт — `verify_data_hashes.py`.

В git остаются ранее существовавшие модификации `data/access_settings.json`, `data/active_profile.json` и `data/knowledge_base.json`. K13 их не создавал и не изменял: их байтовое состояние совпадает с манифестом, снятым до начала тикета.

## Карта файлов

Новый код:
- `src/core/dialogue_memory.py`;
- `tests/test_k13_memory_intent_bridges.py`.

Изменённый код:
- `src/core/agent.py`;
- `src/core/agent_runner.py`;
- `src/core/dialogue_learning.py`;
- `src/core/subsystems/mind_dream.py`;
- `src/core/subsystems/naming_dialogue.py`;
- `src/core/subsystems/proactive_communication.py`.

Обновлены профильные ожидания в 12 существующих тестовых файлах; поведенческие проверки сохранены, включая отсутствие автообучения и защиту naming/care/curiosity.

**Commit, merge и push не выполнялись.**
