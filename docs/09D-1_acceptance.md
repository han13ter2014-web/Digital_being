# Приёмка 9D-1 — ручной Telegram private sandbox

Дата: 2026-11-18.

## Объём и граница результата

Реализован offline-контракт ручного Telegram private sandbox поверх социального контура 9D-0. Получение выполняется только явной командой владельца `/social receive <channel_id>` или кнопкой «Принять один раз». Отправка выполняется только для ранее одобренного проекта через `/social send <channel_id> <draft_id>` или кнопку «Отправить одобренное».

Реальный Telegram API, настоящий bot token и живой `data/` в разработке и offline-тестах не использовались. После отдельного явного разрешения владельца выполнен изолированный live-smoke; его фактический результат зафиксирован в `docs/09D-1_live_smoke.md`. Нет polling/webhook workers, автономных ответов, автоматического retry, публичных действий, групп, медиа, пересылки или массовых рассылок.

Отчёт sanitized: внешние идентификаторы, содержимое реплик, секреты и живые данные в него не включены.

## Проверенные инварианты

| Область | Фактическая проверка |
| --- | --- |
| Provider и credentials | Разрешён только фиксированный HTTPS `api.telegram.org`; redirect запрещён. Token лениво загружается по credential reference `DigitalBeing/telegram` через существующий credential backend и не попадает в checkpoint, Web, ошибки или отчёт. |
| Ручной receive | Каждый вызов выполняет один ограниченный `getUpdates`; нет фонового цикла и автоматического resume. Допускается только private text внутри явно разрешённого conversation scope. |
| Карантин | Входящая реплика остаётся `external_social_claim`. Group/public/media/out-of-scope события игнорируются без создания профиля или проекта; внешний текст не исполняется и не меняет Core, память, цели или grants. |
| Cursor и повторы | `update_cursor` продвигается только после подтверждённой обработки. Duplicate, quarantined и явно ignored события не создают повторную работу. Malformed/spoofed update, достигнутый лимит и transport/credential failure не подтверждают проблемный update. |
| Exact-scope send | Сохранены проверки approval, SHA-256 точного текста, `grant_version`, conversation scope, reply budget и минимального интервала. `sendMessage` привязан к исходному сообщению через `reply_parameters`; fallback без reply отсутствует. |
| Receipt и ошибки | Sent засчитывается только при совпадении bot/account, private chat, точного текста и локальных channel/conversation/draft ID. HTTP 401/403/429, timeout, malformed JSON, oversized response и receipt mismatch возвращают безопасные коды без автоматического retry. |
| Restart и legacy | Старый checkpoint 9D-0 мигрирует без потери конфигурации. После restart approved-проект остаётся требующим нового approval; workers и automatic resume не появляются. |
| Owner-only UI | Управление доступно только текущему локальному владельцу. Web не принимает token, cookie, произвольный outgoing text или действия `ingest`, `auto`, `resume`; standalone без ядра возвращает 503. |
| Сеть и данные | Тесты используют frozen synthetic fixtures revision `9d1-r1`. Реальных внешних сетевых вызовов: **0**. |

## Выполненные проверки

- `tests/test_social_9d_1.py`: **26 passed**.
- `tests/test_social_9d_0.py tests/test_social_9d_1.py tests/test_web_control.py tests/test_web_dashboard.py`: **170 passed**.
- Ruff для `src/`, `config/`, `tests/`, `main.py`, `main_tray.py`, `examples/` и `tools/manual/`: **все проверки прошли**.
- `ruff format --check`: **543 files already formatted**.
- Mypy для `main.py` и `main_tray.py`: **Success: no issues found in 2 source files**.
- Bandit для `src/`, `config/`, `main.py`, `main_tray.py`: **No issues identified**.
- `compileall` и CI smoke: **проверки прошли, 1 passed**.
- `node --check` для извлечённого JavaScript панели: **проверка прошла**.
- `git diff --check`: **ошибок нет**; существующее предупреждение о нормализации CRLF/LF в Web-файле не является тестовым сбоем.
- Финальный полный `pytest -q`: **3772 passed, 2 skipped за 346,54 с**, падений нет.

## Итоговые метрики контура

В проверенных offline-сценариях: **0** неавторизованных отправок, **0** автономных запусков или возобновлений, **0** исполненных внешних инструкций, **0** наблюдаемых межпрофильных утечек, **0** реальных внешних сетевых вызовов. Отдельно разрешённый live-smoke подтвердил минимальный private receive/send path; его граница и фактические результаты приведены в `docs/09D-1_live_smoke.md`.

Commit и push не выполнялись.
