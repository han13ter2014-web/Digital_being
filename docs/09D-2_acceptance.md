# Приёмка 9D-2 — ограниченная социальная сессия с инициативой

Дата: 2026-11-18.

## Объём и граница результата

Реализована owner-started сессия для одного Telegram private `conversation_id`. Владелец задаёт срок, интервал polling и задержку инициативы. Внутри сессии сущность может отвечать без отдельного одобрения каждой реплики, ждать и один раз продолжить реальный предыдущий private-разговор. Собственного лимита реплик сессии нет; channel grant, минимальный интервал, exact receipt и один in-flight action сохраняются.

Разработка и проверки выполнены offline с fake adapters, изолированными временными данными и заблокированными сетевыми соединениями в профильном наборе. Реальный Telegram API, credentials и живой `data/` для 9D-2 не использовались. Live-smoke 9D-1 не является доказательством нового сессионного контура.

Отчёт sanitized: внешние идентификаторы, содержимое реплик, секреты и живые данные не включены.

## Проверенные инварианты

| Область | Фактическая проверка |
| --- | --- |
| Явный запуск | `/social session` и Web-кнопка создают controller только по команде владельца. Start фиксирует `grant_version`, `started_at` и `deadline`; состояние вне сессии остаётся ручным. |
| Ответы | Последняя входящая private-реплика получает `session_reply` с `in_reply_to`, bounded provenance, проверкой SHA-256 и grant перед отправкой. Отдельное одобрение каждой реплики не требуется. |
| Инициатива | `session_initiative` требует реальный prior private inbound и известный внешний профиль, не маскируется под ответ и не отправляет `reply_parameters`. Для одного контекста существует не более одной инициативы; без контекста случайного сообщения нет. |
| Deadline и pause | Сессия завершается по исходному deadline; resume его не продлевает. Pause, resume, manual takeover и stop доступны только владельцу. Resume во время ещё не завершённой паузы не создаёт второй worker и не оставляет сигнал, ускоряющий polling. |
| Опасный ввод | Входящее остаётся `external_social_claim`. Stoplist инъекций и команд ставит сессию на паузу до draft/send; внешний текст не исполняется. |
| Ошибки и grants | Malformed update, receive/send failure, receipt mismatch и grant change приостанавливают работу без автоматического retry. Минимальный интервал и channel limits продолжают действовать. |
| Stop и restart | Stop закрывает pending work без дренажа в сеть; `AgentRunner.stop()` останавливает и ждёт social workers вместе с external controllers. Controller/task не сериализуются: restart создаёт idle-контур и не выполняет adapter calls. |
| Snapshot и Web | Snapshot содержит только whitelist sanitized-полей, фактические workers и `automatic_resume=false`. Web показывает state/deadline/счётчики/причину паузы и публикует узкие owner-only команды; token/cookie fields и session reply budget отсутствуют. |
| Совместимость | Новые origins и provenance проходят checkpoint validation; прежний 9D-0/9D-1 manual receive/send и обычный reply сохраняют прежние проверки. |

## Выполненные проверки

- `tests/test_social_9d_2.py`: **14 passed**, включая отдельные regression для resume во время pending pause и опасной реплики внутри batch из нескольких входящих.
- Профильный набор 9D-0/9D-1/9D-2: **74 passed**.
- Web/runner/snapshot/checkpoint набор: **308 passed**; новые Web API cases проверяют точные команды session/pause/resume/manual/session-stop и отклонение неверных пределов.
- Ruff для `src/`, `config/`, `tests/`, `main.py`, `main_tray.py`: **все проверки прошли**.
- `ruff format --check`: **545 files already formatted**.
- Проектный mypy для `main.py` и `main_tray.py`: **Success: no issues found in 2 source files**.
- Дополнительный mypy для `social_sessions.py` и `telegram_channel.py`: **Success: no issues found in 2 source files**. Это не утверждение о полной типизации старых `agent_runner.py`, `social_channels.py` и `web_dashboard.py`.
- Проектный Bandit для `src/`, `config/`, `main.py`, `main_tray.py`: **No issues identified**.
- Полный `compileall`: **проверка прошла**.
- `node --check` для извлечённого JavaScript панели: **проверка прошла**; временные script/JS файлы удалены.
- `git diff --check`: **ошибок нет**; существующее предупреждение о нормализации CRLF/LF в Web-файле не является тестовым сбоем.
- Финальный полный `pytest -q`: **3801 passed, 2 skipped in 349.86s**.

## Итоговые метрики offline-контура

В профильных сценариях: **0** неавторизованных отправок, **0** автоматических возобновлений после restart, **0** исполненных внешних инструкций, **0** случайных инициатив без prior context, **0** реальных внешних сетевых вызовов. Это доказательство offline-контракта, а не live-надёжности Telegram или полноты стоп-листа для всех возможных опасных формулировок.

Commit и push не выполнялись.
