"""
Модуль взаимодействия пользователя с агентом.

Позволяет агенту задавать вопросы пользователю и получать ответы.
Также позволяет пользователю инициировать диалог с агентом.

РАСШИРЕНО: полноценный диалог с очередью сообщений разных типов.

Этап 2.5: UserInteraction может публиковать события AGENT_QUESTION и
AGENT_MESSAGE в EventBus, чтобы GUI-режим (ChatWindow, Notifier) видел
вопросы/сообщения агента так же, как и терминальный режим через print().
"""

from typing import Dict

# === Ленивый импорт, чтобы не создавать циклическую зависимость ===
def _get_events_class():
    try:
        from src.core.event_bus import Events
        return Events
    except Exception:
        return None


class UserInteraction:
    """Обрабатывает взаимодействие между пользователем и агентом."""

    # Стандартные приложения, в которых не нужно беспокоить
    DEFAULT_QUIET_APPS = [
        "VSCode", "PyCharm", "IntelliJ IDEA", "Terminal",
        "WindowsTerminal", "Photoshop", "Premiere", "AfterEffects",
        "vim", "emacs", "Sublime Text", "Atom",
    ]

    def __init__(self, agent_name="Agent", bus=None):
        self.agent_name = agent_name
        # EventBus опционально. Если задан — ask_user/send_message публикуют
        # события, чтобы GUI (chat_window) мог их увидеть. Если None —
        # работает как раньше (только print() в stdout, для терминала).
        self._bus = bus

        self.question_history = []  # История вопросов-ответов
        self.pending_questions = []  # Очередь ожидающих ответов

        # === НОВОЕ: очередь сообщений (не только вопросы) ===
        self.message_queue = []  # Все сообщения от агента
        self.message_history = []  # История всех сообщений
        self._last_user_message_cycle = None  # Когда пользователь последний раз писал

        # Настройки взаимодействия
        self.max_pending_questions = 3
        self.min_answer_length = 2
        self.cooldown_cycles = 50
        # Вопрос ещё не задавался, поэтому кулдауна нет. Раньше здесь
        # стоял 0, и первые 50 циклов жизни вопрос был запрещён: агент
        # голодал по любопытству, но спросить физически не мог.
        self.last_question_cycle = -self.cooldown_cycles

        # === НОВОЕ: настройки quiet hours (приложения, где не беспокоить) ===
        self.user_quiet_hours = {
            app: True for app in self.DEFAULT_QUIET_APPS
        }

    def attach_bus(self, bus) -> None:
        """Привязать EventBus (вызывается после создания агента и шины).

        Используется, потому что в main_tray.py порядок создания такой:
            agent = DigitalBeing(name)   # UserInteraction создаётся без bus
            bus = EventBus(...)
            agent.user_interaction.attach_bus(bus)   # <- здесь
        """
        self._bus = bus

    def _publish(self, event_name: str, data: dict, priority: int = 1) -> None:
        """Публикация в шину. Тихо игнорирует ошибки — GUI не должен ронять
        основной цикл из-за сломанной подписки или переполненной очереди."""
        if self._bus is None:
            return
        try:
            self._bus.publish_sync(
                event_name, data, source="user_interaction", priority=priority,
            )
        except Exception:
            # Не критично — событие просто не дойдёт до GUI,
            # но в stdout уже напечатано.
            pass

    def can_ask_question(self, cycle_count: int) -> bool:
        """Проверяет может ли агент задать вопрос пользователю."""
        if len(self.pending_questions) >= self.max_pending_questions:
            return False

        if cycle_count - self.last_question_cycle < self.cooldown_cycles:
            return False

        recent_questions = [q for q in self.question_history
                          if q.get('cycle', 0) > cycle_count - 100]
        if len(recent_questions) > 5:
            return False

        return True

    def ask_user(self, question: str, context: str = "", cycle: int = 0,
                   complex_question: str = None, sub_questions: list = None,
                   sub_question_index: int = 0,
                   sub_answers: dict = None) -> dict:
        """Добавляет вопрос в очередь ожидающих.

        Args:
            question: Текст вопроса пользователю.
            context: Контекст вопроса.
            cycle: Номер цикла.
            complex_question: Оригинальный сложный вопрос (если это под-вопрос).
            sub_questions: Список всех под-вопросов для синтеза.
            sub_question_index: Индекс текущего под-вопроса в списке.
            sub_answers: Уже собранные ответы цепочки {под-вопрос: ответ}.
                Передаётся по цепочке, чтобы синтез получил ровно ответы
                этого сложного вопроса (без сканирования общей истории).
        """
        if not self.can_ask_question(cycle):
            return {"status": "failed", "reason": "Не могу задать вопрос сейчас (перезагрузка)"}

        # id = максимум среди живых вопросов + 1, а не len(pending)+1:
        # после восстановления из чекпоинта в очереди могут быть
        # вопросы с большими id, и len-схема выдавала дубликаты — ответ
        # попадал в чужой вопрос.
        question_id = max(
            (q["id"] for q in self.pending_questions), default=0
        ) + 1
        question_entry = {
            "id": question_id,
            "question": question,
            "context": context,
            "answered": False,
            "answer": None,
            "cycle": cycle,
            "priority": self._calculate_priority(question, context),
            # Новые поля для отслеживания сложного вопроса:
            "complex_question": complex_question,
            "sub_questions": sub_questions or [],
            "sub_question_index": sub_question_index,
            "sub_answers": dict(sub_answers) if sub_answers else {},
        }

        self.pending_questions.append(question_entry)
        self.last_question_cycle = cycle

        # === Печать в stdout. Обёрнуто в try/except, чтобы вывод в
        # cp1251-консоль (например, из подпроцесса) не ронял публикацию
        # события в шину. Этап 2.5: главное — чтобы событие ушло в GUI.
        try:
            print(f"\n  ❓ [{self.agent_name}] ЗАПРОС К ПОЛЬЗОВАТЕЛЮ (#{question_entry['id']}):")
            print(f"     Вопрос: {question}")
            if context:
                print(f"     Контекст: {context}")
        except Exception:
            # В крайнем случае пишем ASCII-фолбэк
            try:
                print(f"\n  [?] [{self.agent_name}] ZAPROS K POLZOVATELYU (#{question_entry['id']}):")
                print(f"     Q: {question}")
                if context:
                    print(f"     Context: {context}")
            except Exception:
                pass

        # === Этап 2.5: публикуем в EventBus для GUI-режима ===
        # Делаем это ПОСЛЕ print, но print защищён try/except — поэтому
        # публикация всегда происходит.
        Events = _get_events_class()
        if Events is not None:
            self._publish(
                Events.AGENT_QUESTION,
                {
                    "id": question_entry["id"],
                    "question": question,
                    "context": context,
                    "cycle": cycle,
                    "priority": question_entry["priority"],
                    "agent_name": self.agent_name,
                },
                priority=2,  # вопросы к пользователю — высокий приоритет
            )

        return {"status": "queued", "id": question_entry["id"]}

    def get_pending_question(self) -> dict:
        """Получает следующий ожидающий вопрос."""
        if not self.pending_questions:
            return None

        pending = [q for q in self.pending_questions if not q["answered"]]
        if not pending:
            return None

        priority_map = {"high": 3, "medium": 2, "low": 1}
        pending.sort(key=lambda q: priority_map.get(q["priority"], 0), reverse=True)

        return pending[0]

    def submit_answer(self, question_id: int, answer: str,
                       on_synthesis_needed: callable = None,
                       cycle: int = None) -> dict:
        """Отправляет ответ на вопрос.

        Args:
            question_id: ID вопроса.
            answer: Ответ пользователя.
            on_synthesis_needed: Callback, вызываемый когда все под-вопросы
                сложного вопроса отвечены. Получает (complex_question, sub_answers).
            cycle: Текущий цикл момента ответа. Без него счётчик контакта
                получал цикл ВОПРОСА, и детектор тишины тревожился сразу
                после ответа («давно тебя не слышу» через 6 циклов после
                реплики человека — живой прогон 2026-11-01).
        """
        for q in self.pending_questions:
            if q["id"] == question_id and not q["answered"]:
                q["answered"] = True
                q["answer"] = answer
                normalized_answer = " ".join(str(answer).lower().strip().split())
                unknown_answers = {
                    "не знаю", "не уверен", "не уверена", "не могу сказать",
                    "без понятия", "затрудняюсь ответить", "не знаю ответа",
                }
                q["answer_kind"] = (
                    "unknown" if normalized_answer.rstrip(".!?") in unknown_answers
                    else "user_answer"
                )

                self.question_history.append({
                    "question": q["question"],
                    "answer": answer,
                    "context": q.get("context", ""),
                    "cycle": q["cycle"],
                    "priority": q["priority"]
                })

                # Сохраняем данные о сложном вопросе перед удалением
                complex_question = q.get("complex_question")
                sub_questions = q.get("sub_questions", [])
                sub_question_index = q.get("sub_question_index", 0)

                self.pending_questions = [qq for qq in self.pending_questions if qq["id"] != question_id]

                # === НОВОЕ: отмечаем, что пользователь ответил ===
                self._last_user_message_cycle = (
                    cycle if cycle is not None else q["cycle"]
                )

                # === Проверяем, есть ли еще под-вопросы для сложного вопроса ===
                if complex_question and sub_questions:
                    idx = min(sub_question_index, len(sub_questions) - 1)
                    # Точный накопитель ответов этой цепочки (ключ — текст
                    # под-вопроса, как его ждёт синтез). Для цепочек,
                    # восстановленных из старых чекпоинтов без накопителя,
                    # остаётся фолбэк на контекст в общей истории.
                    accumulated = dict(q.get("sub_answers") or {})
                    if not accumulated and sub_question_index > 0:
                        for hist in self.question_history:
                            if (
                                complex_question in hist.get("context", "")
                                and hist.get("question") != q["question"]
                            ):
                                accumulated[hist["question"]] = hist["answer"]
                    accumulated[sub_questions[idx]] = answer

                    next_index = sub_question_index + 1
                    if next_index < len(sub_questions):
                        # Есть следующий под-вопрос — задаем его
                        # Используем cycle + 1 чтобы обойти кулдаун (внутренние под-вопросы не должны ждать)
                        next_cycle = q["cycle"] + self.cooldown_cycles + 1
                        next_sub_q = sub_questions[next_index]
                        self.ask_user(
                            question=f"Также для понимания '{complex_question}': {next_sub_q}?",
                            context=f"Под-вопрос {next_index + 1}/{len(sub_questions)} для: {complex_question}",
                            cycle=next_cycle,
                            complex_question=complex_question,
                            sub_questions=sub_questions,
                            sub_question_index=next_index,
                            sub_answers=accumulated,
                        )
                        return {"status": "answered", "question_id": question_id,
                                "next_sub_question": True}
                    else:
                        # Все под-вопросы отвечены — нужен синтез!
                        if on_synthesis_needed:
                            on_synthesis_needed(complex_question, accumulated)

                        return {"status": "answered", "question_id": question_id,
                                "synthesis_needed": True,
                                "complex_question": complex_question}

                return {"status": "answered", "question_id": question_id}

        return {"status": "not_found", "reason": f"Вопрос #{question_id} не найден или уже отвечен"}

    def decline_question(self, question_id: int, cycle: int = None) -> dict:
        """Снять вопрос без ответа: человек попросил не повторяться.

        «Собеседник-5»: «уже отвечал» — не ответ и не новая тема.
        Вопрос закрывается с answer_kind="declined" и удаляется из
        очереди ожидания, но в question_history НЕ попадает — история
        ответов остаётся правдивой: отклонённого вопроса там нет.
        Контакт фиксируется: реплика человека — это контакт, детектор
        тишины не должен тревожиться сразу после протеста.
        """
        for q in self.pending_questions:
            if q["id"] == question_id and not q["answered"]:
                q["answered"] = True
                q["answer_kind"] = "declined"
                self.pending_questions = [
                    qq for qq in self.pending_questions
                    if qq["id"] != question_id
                ]
                if cycle is not None:
                    self._last_user_message_cycle = cycle
                return {"status": "declined", "question_id": question_id}
        return {"status": "not_found", "reason": f"Вопрос #{question_id} не найден или уже отвечен"}

    def get_user_prompts(self) -> str:
        """Получает ввод от пользователя (неблокирующий)."""
        try:
            user_input = input(f"\n[{self.agent_name}] Введите сообщение или 'PROCEED' для продолжения: ")
            return user_input.strip()
        except EOFError:
            return ""

    def _calculate_priority(self, question: str, context: str) -> str:
        """Рассчитывает приоритет вопроса."""
        high_priority_keywords = [
            "критический", "необходимо", "важно", "python", "алгоритм",
            "функция", "класс", "структура", "база данных"
        ]

        low_priority_keywords = [
            "абстрактный", "философский", "гипотетический", "теоретический"
        ]

        text = (question + " " + context).lower()

        for kw in low_priority_keywords:
            if kw in text:
                return "low"

        for kw in high_priority_keywords:
            if kw in text:
                return "high"

        return "medium"

    def get_history_summary(self, last_n: int = 10) -> list:
        """Возвращает последние N вопросов-ответов."""
        return self.question_history[-last_n:]

    def generate_suggested_answers(self, question: str) -> list:
        """Генерирует варианты ответов для удобства пользователя."""
        base_responses = {
            "что": ["Я думаю что это связано с пониманием концепции.",
                     "Нужно больше информации для ответа.",
                     "Это зависит от контекста использования."],
            "как": ["Обычно это делается через реализацию.",
                    "Зависит от конкретной задачи.",
                    "Можно попробовать несколько подходов."],
            "почему": ["Вероятно из-за ограничений системы.",
                       "Это связано с фундаментальными принципами.",
                       "Возможно для достижения определенной цели."],
        }

        suggestions = []
        for key, responses in base_responses.items():
            if key in question.lower():
                suggestions.extend(responses)

        if not suggestions:
            suggestions = ["Да, согласен.", "Интересный вопрос. Нужно подумать.",
                          "Предполагаю что ответ положительный."]

        return suggestions[:3]

    # ============================================================
    # НОВОЕ: ДИАЛОГ — сообщения разных типов (не только вопросы)
    # ============================================================

    def send_message(self, content: str,
                     msg_type: str = "statement",
                     tone: str = "casual",
                     urgency: float = 0.5,
                     context: str = None,
                     cycle: int = 0) -> str:
        """Отправляет сообщение пользователю.

        В отличие от ask_user, НЕ ожидает немедленного ответа.
        Это полноценный диалог: сообщение — это не вопрос.

        Args:
            content: текст сообщения
            msg_type: question|statement|reflection|greeting|farewell|proposal|alert|poetry
            tone: formal|casual|playful|intimate|cautious|philosophical|poetic
            urgency: 0.0-1.0
            context: что вызвало сообщение
            cycle: текущий цикл

        Returns:
            ID сообщения
        """
        msg_id = f"msg_{cycle}_{len(self.message_queue) + 1}"
        message = {
            "id": msg_id,
            "sender": "agent",
            "content": content,
            "msg_type": msg_type,
            "tone": tone,
            "urgency": max(0.0, min(1.0, urgency)),
            "context": context,
            "cycle": cycle,
            "acknowledged": False,
            "timestamp": None,  # будет установлено снаружи
        }

        self.message_queue.append(message)
        self.message_history.append(message)

        # Печатаем сообщение
        prefix_map = {
            "question": "?",
            "statement": "*",
            "reflection": "~",
            "greeting": ">",
            "farewell": "<",
            "proposal": "+",
            "alert": "!",
            "poetry": "~",
        }
        prefix = prefix_map.get(msg_type, "*")
        try:
            print(f"\n  {prefix} [{self.agent_name} -> user]:")
            print(f"     {content}")
        except Exception:
            # cp1251-консоль не умеет в эмодзи — ASCII-фолбэк
            try:
                print(f"\n  * [{self.agent_name} -> user]:")
                print(f"     {content}")
            except Exception:
                pass

        # === Этап 2.5: публикуем в EventBus для GUI-режима ===
        Events = _get_events_class()
        if Events is not None:
            self._publish(
                Events.AGENT_MESSAGE,
                {
                    "id": msg_id,
                    "content": content,
                    "msg_type": msg_type,
                    "tone": tone,
                    "urgency": urgency,
                    "context": context,
                    "cycle": cycle,
                    "agent_name": self.agent_name,
                },
                priority=2 if msg_type in ("alert", "question") else 1,
            )

        return msg_id

    def get_pending_messages(self, include_acknowledged: bool = False) -> list:
        """Возвращает все непрочитанные сообщения (включая вопросы)."""
        if include_acknowledged:
            return list(self.message_queue)
        return [m for m in self.message_queue if not m.get("acknowledged", False)]

    def acknowledge_message(self, msg_id: str) -> bool:
        """Пользователь прочитал сообщение."""
        for m in self.message_queue:
            if m["id"] == msg_id:
                m["acknowledged"] = True
                return True
        return False

    def get_history(self, n: int = 20) -> list:
        """Возвращает историю диалога (последние N сообщений в обе стороны)."""
        # Собираем все сообщения (от агента И от пользователя)
        all_messages = list(self.message_history)

        # Добавляем ответы пользователя из question_history
        for q in self.question_history[-n:]:
            all_messages.append({
                "sender": "user",
                "content": q.get("answer", ""),
                "cycle": q.get("cycle", 0),
                "msg_type": "answer",
                "tone": "user",
            })

        # Сортируем по циклу и берём последние N
        all_messages.sort(key=lambda x: x.get("cycle", 0))
        return all_messages[-n:]

    def get_last_user_message_cycle(self) -> int:
        """Когда пользователь последний раз отвечал (cycle)."""
        return self._last_user_message_cycle

    def receive_user_message(self, content: str, cycle: int = 0) -> Dict:
        """Пользователь отправляет сообщение агенту (не ответ на вопрос).

        Регистрирует факт получения сообщения от пользователя,
        чтобы агент мог отслеживать диалог.
        """
        self._last_user_message_cycle = cycle
        self.message_history.append({
            "id": f"user_{cycle}_{len(self.message_history)}",
            "sender": "user",
            "content": content,
            "msg_type": "user_message",
            "tone": "user",
            "urgency": 0.0,
            "cycle": cycle,
            "acknowledged": True,
        })
        return {"status": "received", "cycle": cycle}

    # ============================================================
    # Персистентность: снапшот диалогового состояния для чекпоинта
    # ============================================================

    def to_checkpoint_dict(self) -> dict:
        """Снапшот диалогового состояния: разговор переживает рестарт.

        Сохраняется история вопросов-ответов и все ожидающие вопросы с
        полями цепочек сложных вопросов (complex/sub) — иначе после
        рестарта сущность забывала разговор, а синтез цепочки ломался
        на середине. Плюс оба маркера цикла: кулдаун вопросов и «когда
        пользователь писал последний раз» (детектор тишины).
        """
        return {
            "question_history": [
                dict(entry) for entry in self.question_history[-50:]
            ],
            "pending_questions": [
                {
                    "id": q["id"],
                    "question": q["question"],
                    "context": q.get("context", ""),
                    "cycle": int(q.get("cycle", 0)),
                    "priority": q.get("priority", "medium"),
                    "complex_question": q.get("complex_question"),
                    "sub_questions": list(q.get("sub_questions") or []),
                    "sub_question_index": int(q.get("sub_question_index", 0)),
                    "sub_answers": dict(q.get("sub_answers") or {}),
                }
                for q in self.pending_questions
            ],
            "last_question_cycle": int(self.last_question_cycle),
            "last_user_message_cycle": (
                int(self._last_user_message_cycle)
                if self._last_user_message_cycle is not None else None
            ),
        }

    def restore_from_checkpoint(self, data) -> None:
        """Восстановить диалоговое состояние из снапшота чекпоинта.

        Битые записи пропускаются, отвечённые ожидающие вопросы не
        восстанавливаются. История и очередь заменяются целиком:
        восстановление идёт в свежий агент.
        """
        if not isinstance(data, dict):
            return

        saved_history = data.get("question_history")
        if isinstance(saved_history, list):
            restored = []
            for entry in saved_history[-50:]:
                if not isinstance(entry, dict):
                    continue
                question = str(entry.get("question") or "").strip()
                if not question:
                    continue
                cycle = entry.get("cycle", 0)
                restored.append({
                    "question": question,
                    "answer": entry.get("answer"),
                    "context": str(entry.get("context") or ""),
                    "cycle": int(cycle) if isinstance(cycle, (int, float)) and not isinstance(cycle, bool) else 0,
                    "priority": str(entry.get("priority") or "medium"),
                })
            self.question_history = restored

        saved_pending = data.get("pending_questions")
        if isinstance(saved_pending, list):
            restored_pending = []
            for entry in saved_pending:
                if not isinstance(entry, dict):
                    continue
                question = str(entry.get("question") or "").strip()
                if not question or entry.get("answered"):
                    continue
                raw_id = entry.get("id")
                cycle = entry.get("cycle", 0)
                restored_pending.append({
                    "id": (
                        int(raw_id)
                        if isinstance(raw_id, (int, float))
                        and not isinstance(raw_id, bool)
                        else max(
                            (q["id"] for q in restored_pending), default=0
                        ) + 1
                    ),
                    "question": question,
                    "context": str(entry.get("context") or ""),
                    "answered": False,
                    "answer": None,
                    "cycle": int(cycle) if isinstance(cycle, (int, float)) and not isinstance(cycle, bool) else 0,
                    "priority": str(entry.get("priority") or "medium"),
                    "complex_question": entry.get("complex_question"),
                    "sub_questions": list(entry.get("sub_questions") or []),
                    "sub_question_index": int(entry.get("sub_question_index") or 0),
                    "sub_answers": dict(entry.get("sub_answers") or {}),
                })
            if restored_pending:
                self.pending_questions = restored_pending

        last_question = data.get("last_question_cycle")
        if isinstance(last_question, (int, float)) and not isinstance(last_question, bool):
            self.last_question_cycle = int(last_question)

        last_message = data.get("last_user_message_cycle")
        if isinstance(last_message, (int, float)) and not isinstance(last_message, bool):
            self._last_user_message_cycle = int(last_message)

    # ============================================================
    # НОВОЕ: Quiet Hours — настройки «не беспокоить в ...»
    # ============================================================

    def add_quiet_app(self, app_name: str) -> None:
        """Добавляет приложение в список «не беспокоить»."""
        self.user_quiet_hours[app_name] = True

    def remove_quiet_app(self, app_name: str) -> None:
        """Убирает приложение из списка «не беспокоить»."""
        self.user_quiet_hours[app_name] = False

    def is_quiet_app(self, app_name: str) -> bool:
        """Проверяет, является ли приложение «тихим» (не беспокоить)."""
        return self.user_quiet_hours.get(app_name, False)

    def set_quiet_hours_from_user_input(self, user_input: str) -> None:
        """Парсит пользовательский ввод «не беспокоить в X, Y, Z»."""
        # Простая эвристика: ищем "не беспокоить" / "не отвлекай" / "молчи в"
        text = user_input.lower()
        keywords = ["не беспокоить", "не отвлекай", "молчи", "молчать", "не трогай"]

        if any(kw in text for kw in keywords):
            # Извлекаем приложения (после "в")
            for sep in ["в ", "во "]:
                if sep in text:
                    after = text.split(sep, 1)[1]
                    # Берём первое слово/словосочетание
                    words = after.split(",")[0].split(".")[0].split(";")[0]
                    for app in words.split():
                        app_clean = app.strip(" .,;!?\"'()")
                        if app_clean and len(app_clean) > 2:
                            self.user_quiet_hours[app_clean] = True
                    break


class UserPromptHandler:
    """Обрабатывает прямые ввод от пользователя во время работы агента."""

    def __init__(self):
        self.command_map = {
            "help": self._cmd_help,
            "h": self._cmd_help,
            "status": self._cmd_status,
            "s": self._cmd_status,
            "goals": self._cmd_goals,
            "g": self._cmd_goals,
            "concepts": self._cmd_concepts,
            "c": self._cmd_concepts,
            "ask": self._cmd_ask,
            "a": self._cmd_ask,
            "clear": self._cmd_clear,
            "exit": self._cmd_exit,
            "q": self._cmd_exit,
        }

    def process_command(self, cmd: str, agent=None) -> str:
        """Обрабатывает команду пользователя."""
        cmd = cmd.strip().lower()

        if cmd in self.command_map:
            return self.command_map[cmd](agent)

        if cmd.startswith("ask ") or cmd.startswith("a "):
            question = cmd[4:].strip()
            if question and agent:
                # Раньше просто говорили «вопрос передан»,
                # теперь регистрируем как сообщение и обрабатываем
                if hasattr(agent, "user_interaction"):
                    agent.user_interaction.receive_user_message(question)
                return f"[Система] Ваш вопрос '{question[:50]}...' передан агенту."

        if agent:
            # Любой другой ввод = сообщение пользователя агенту
            if hasattr(agent, "user_interaction"):
                agent.user_interaction.receive_user_message(cmd)
            return f"[Система] Ваше сообщение будет обработано агентом в следующем цикле."

        return f"[Система] Непонятная команда. Введите 'help' для справки."

    def _cmd_help(self, agent=None) -> str:
        return """
Доступные команды:
  help/h       - Показать справку
  status/s     - Статус агента
  goals/g      - Цели агента
  concepts/c   - Изученные концепции
  ask/a <вопрос> - Задать вопрос агенту
  clear        - Очистить экран
  exit/q       - Сохранить и выйти
"""

    def _cmd_status(self, agent=None) -> str:
        if not agent:
            return "Агент не доступен."
        return f"[Статус] Интеллект: {agent.intelligence}, Энергия: {agent.energy:.0f}, Цикл: {agent.cycle_count}"

    def _cmd_goals(self, agent=None) -> str:
        if not agent:
            return "Агент не доступен."
        goals_status = agent.get_goals_status()
        return f"[Цели] Всего: {goals_status['total']}, Завершено: {goals_status['completed']}, Активная: {goals_status['active']}"

    def _cmd_concepts(self, agent=None) -> str:
        if not agent:
            return "Агент не доступен."
        mm_status = agent.get_mental_models_status()
        return f"[Концепции] Всего: {mm_status['total_concepts']}, Высокая уверенность: {mm_status['concepts_with_high_confidence']}"

    def _cmd_ask(self, agent=None) -> str:
        if not agent:
            return "Агент не доступен."
        return "[Система] Агент может задать вопрос при следующем цикле."

    def _cmd_clear(self, agent=None) -> str:
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
        return ""

    def _cmd_exit(self, agent=None) -> str:
        return "__EXIT__"