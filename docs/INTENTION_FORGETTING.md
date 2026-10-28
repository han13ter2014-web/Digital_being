# Этап 5: забывание и новый интерес

Этап 4 закрыт коммитом e7dc469. Этап 5 добавляет explicit forgotten
resolution для waiting intention: внимание освобождается, причина и урок
остаются, старое ожидание не оживает автоматически.

`start_new_intention(agent, action, target, reason)` создаёт независимую
новую запись после forgotten. У неё новый UUID, `new_interest=True`,
`continuation_of=None`; она не является продолжением старого обязательства.
Если активное намерение ещё существует, создание нового отклоняется.
Старая terminal запись остаётся для автобиографической истории.
JSON/SQLite startup сохраняет обе записи и resolution.

Тесты: resolution/waiting/relevant/continuation — 8 passed для нового
interest-пути; причина forgotten сохраняется. Контроль test_forgotten_attention.py добавляет реальный проход через
continuation_candidate: forgotten исключается, затем start_new_intention
создаёт отдельную запись; memory и values не удаляются. Профильный набор
forgotten/new-interest: 10 passed.

Автоматическое порождение
нового интереса не реализовано: API вызывается явно, и это соответствует
принципу «забывание не навязывает следующее желание». Отдельно остаётся
лимит 200 waiting keys и отсутствие архива при вытеснении.
