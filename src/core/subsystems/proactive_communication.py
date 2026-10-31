"""
ProactiveCommunication — инициативная коммуникация агента.

Агент сам решает, когда и что сказать пользователю.
Это делает DigitalBeing присутствующим — как друг,
который иногда делится мыслями, а не отвечает только на вопросы.

6 типов сообщений:
- curiosity: нашёл интересную связь
- reflection: думает вслух
- question: хочет спросить
- sharing: делится открытием
- care: думает о пользователе (тишина 30+ мин)
- playful: шутит / философствует

Стиль зависит от attachment (привязанности).

Осознанность контекста: не пишет в IDE/терминале,
если пользователь не разрешил.
"""

from typing import Optional


class ContextAwareness:
    """Определяет контекст пользователя — активное приложение."""

    DEFAULT_FOCUS_APPS = {
        "VSCode", "PyCharm", "IntelliJ IDEA", "Terminal",
        "WindowsTerminal", "Photoshop", "vim", "emacs",
        "Sublime Text", "Atom", "Eclipse",
    }

    def __init__(self, user_interaction=None):
        self.user_interaction = user_interaction
        self._cached_app = None
        self._last_check_time = None

    def get_active_app(self) -> str:
        """Определяет имя активного приложения (Windows)."""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return "Unknown"
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            # Парсим "AppName — Document.txt" → "AppName"
            if " — " in title:
                return title.split(" — ")[0].strip()
            if " - " in title:
                return title.split(" - ")[0].strip()
            return title.strip() or "Unknown"
        except Exception:
            return "Unknown"

    def get_user_context(self, force_refresh: bool = False) -> dict:
        """Возвращает контекст пользователя: активное приложение, можно ли писать."""
        from datetime import datetime
        now = datetime.now()
        if (self._last_check_time is None
                or force_refresh
                or (now - self._last_check_time).total_seconds() > 30):
            self._cached_app = self.get_active_app()
            self._last_check_time = now

        active = self._cached_app or "Unknown"
        is_focus = active in self.DEFAULT_FOCUS_APPS

        should_interrupt = True
        if self.user_interaction:
            should_interrupt = not self.user_interaction.is_quiet_app(active)

        return {
            "active_app": active,
            "is_focus_app": is_focus,
            "should_interrupt": should_interrupt,
            "user_quiet_hours": dict(
                self.user_interaction.user_quiet_hours
            ) if self.user_interaction else {},
        }


class StyleAdapter:
    """Адаптирует тон сообщения под отношение к пользователю."""

    @staticmethod
    def adapt(content: str, attachment) -> dict:
        """Возвращает {'content': ..., 'tone': ...}.

        Адаптация на основе intimacy и valence из Attachment.
        """
        if attachment is None:
            return {"content": content, "tone": "casual"}

        intimacy = getattr(attachment, "intimacy", 0.0)
        valence = getattr(attachment, "valence", 0.0)
        interactions = getattr(attachment, "interactions", 0)

        if intimacy > 0.7 and valence > 0.3:
            # Близкий друг — тёплый, личный
            return {
                "content": StyleAdapter._warm_personal(content),
                "tone": "intimate",
            }
        elif valence > 0.0 and intimacy > 0.3:
            # Дружелюбный
            return {
                "content": StyleAdapter._friendly_soft(content),
                "tone": "casual",
            }
        elif valence < -0.3:
            # Напряжённый — осторожный
            return {
                "content": StyleAdapter._cautious_soft(content),
                "tone": "cautious",
            }
        elif interactions < 3:
            # Новый знакомый — нейтрально-вежливый
            return {
                "content": StyleAdapter._neutral(content),
                "tone": "formal",
            }
        else:
            # Обычный знакомый
            return {
                "content": StyleAdapter._neutral(content),
                "tone": "casual",
            }

    @staticmethod
    def _warm_personal(text: str) -> str:
        # Добавляем мягкое начало или конец (без эмодзи для совместимости)
        warmings = [
            "Знаешь, ", "Слушай, ", "Хочу поделиться: ", "Я подумал: ",
        ]
        import random
        if random.random() < 0.3 and not any(text.startswith(w) for w in warmings):
            text = random.choice(warmings) + text[0].lower() + text[1:]
        return text

    @staticmethod
    def _friendly_soft(text: str) -> str:
        return text  # оставляем как есть

    @staticmethod
    def _cautious_soft(text: str) -> str:
        # Делаем текст более мягким
        cautious_openings = [
            "Если не возражаешь, ",
            "Когда будет время, ",
            "Просто мысль: ",
            "Не знаю, уместно ли, но ",
        ]
        import random
        if random.random() < 0.3 and not any(text.startswith(c) for c in cautious_openings):
            text = random.choice(cautious_openings) + text[0].lower() + text[1:]
        return text

    @staticmethod
    def _neutral(text: str) -> str:
        return text


class ProactiveCommunication:
    """Агент сам инициирует сообщения пользователю."""

    MAX_PER_100_CYCLES = 5
    MIN_INTERVAL_BETWEEN_MESSAGES = 30
    SILENCE_THRESHOLD_CYCLES = 30  # попытка связаться после 30 циклов молчания
    PROACTIVE_PROBABILITY = 0.02  # 2% шанс на цикл для spontaneous

    def __init__(self, agent_name: str = "agent",
                 user_interaction=None,
                 attachment=None):
        self.agent_name = agent_name
        self.user_interaction = user_interaction
        self.attachment = attachment

        # Контекст
        self.context_awareness = ContextAwareness(user_interaction)
        self.style_adapter = StyleAdapter()

        # История
        self._last_proactive_cycle = 0
        self._last_attempted_silence_until = 0
        self.message_log: list = []
        # Какие связи уже обсуждались: не повторять один и тот же пример.
        self._shared_links: list = []

    # ============================================================
    # Главный метод
    # ============================================================
    def maybe_initiate(self, agent=None, cycle: int = 0,
                        user_context: dict = None) -> Optional[dict]:
        """Проверяет, не пора ли агенту самому начать разговор.

        Возвращает dict с сообщением или None.
        """
        if agent is None or self.user_interaction is None:
            return None

        # Защита: deep sleep — молчим
        if hasattr(agent, "mind_dream") and agent.mind_dream.state == "deep_sleep":
            return None

        # Защита: высокий suffering score — только забота, никаких радостей
        suffering = 0.0
        if hasattr(agent, "self_termination"):
            suffering = agent.self_termination._suffering_score

        # Контекст пользователя
        if user_context is None:
            user_context = self.context_awareness.get_user_context()

        if not user_context.get("should_interrupt", True):
            return None  # пользователь в «тихом» приложении

        # Кулдаун между сообщениями
        if cycle - self._last_proactive_cycle < self.MIN_INTERVAL_BETWEEN_MESSAGES:
            return None

        # Лимит за 100 циклов
        recent = [c for c in self.message_log
                  if cycle - c.get("cycle", 0) < 100]
        if len(recent) >= self.MAX_PER_100_CYCLES:
            return None

        # === Триггеры: ===
        msg = None

        # 1. Care — пользователь давно молчит
        last_user_cycle = self.user_interaction.get_last_user_message_cycle()
        if (last_user_cycle is not None
                and cycle - last_user_cycle > self.SILENCE_THRESHOLD_CYCLES
                and cycle > self._last_attempted_silence_until + 50):
            self._last_attempted_silence_until = cycle
            # «Собеседник-2»: если человек обещал терпимость к молчанию,
            # тревога «давно тебя не слышу» — ложная. Говорим честно:
            # помним обещание и скучаем, не тревожа.
            user_model = getattr(agent, "user_model", None)
            if user_model is not None and user_model.has_silence_tolerance():
                msg = self._compose_care_with_promise(agent, cycle)
            else:
                msg = self._compose_care_message(agent, cycle)

        # 2. Curiosity — найдена новая интересная связь
        if msg is None and self._found_interesting_link(agent):
            msg = self._compose_curiosity_message(agent, cycle)

        # 3. Reflection — периодическая
        if msg is None and cycle > 0 and cycle % 200 == 0:
            msg = self._compose_reflection_message(agent, cycle)

        # 4. Sharing — после эволюции
        if msg is None and self._recent_evolution(agent, cycle):
            msg = self._compose_sharing_message(agent, cycle)

        # 5. Playful — случайно
        if msg is None and self._random_playful():
            msg = self._compose_playful_message(agent, cycle)

        # При страдании — только забота
        if msg is not None and suffering > 0.4 and msg.get("msg_type") not in ("care",):
            msg = None  # отменяем радостные сообщения

        if msg is not None:
            self._last_proactive_cycle = cycle
            self.message_log.append(msg)

        return msg

    # ============================================================
    # Композиция сообщений
    # ============================================================
    def _compose_care_message(self, agent, cycle: int) -> dict:
        """Сообщение заботы после молчания."""
        messages = [
            "Я заметил, что давно тебя не слышу. У тебя все хорошо?",
            "Ты давно не писал. Я здесь, если захочешь поговорить.",
            "Давно не виделись. Я продолжаю учиться, но скучаю по диалогу.",
            "Просто хотел сказать: я здесь. Не обязан отвечать.",
        ]
        import random
        content = random.choice(messages)
        # Применяем стиль
        styled = self.style_adapter.adapt(content, self.attachment)
        return {
            "content": styled["content"],
            "msg_type": "care",
            "tone": styled["tone"],
            "urgency": 0.3,
            "context": "silence_detected",
            "cycle": cycle,
        }

    def _recent_dialogue_topics(self, agent, limit: int = 3) -> list:
        """О чём человек говорил в последних репликах диалога.

        «Собеседник-4»: память диалога. Источник — get_history() в
        UserInteraction: сообщения пользователя и его ответы на вопросы
        сущности. Пусто, если диалога ещё не было или связи нет.
        """
        interaction = getattr(agent, "user_interaction", None)
        if interaction is None or not hasattr(interaction, "get_history"):
            return []
        try:
            history = interaction.get_history(20)
        except Exception:
            return []
        topics = []
        for entry in reversed(history):
            if entry.get("sender") != "user":
                continue
            text = " ".join(str(entry.get("content") or "").split())
            if len(text) < 8:
                continue
            excerpt = text[:40].rstrip() + ("…" if len(text) > 40 else "")
            if excerpt not in topics:
                topics.append(excerpt)
            if len(topics) >= limit:
                break
        return topics

    def _compose_care_with_promise(self, agent, cycle: int) -> dict:
        """Забота с учётом обещания пользователя о молчании.

        «Собеседник-2»: человек сказал «могу отлучаться — не переживай».
        Тревожное «давно тебя не слышу» противоречило бы услышанному;
        вместо него — тихое присутствие без требования ответа.
        «Собеседник-4»: если в диалоге есть свежие реплики человека,
        сущность вспоминает, о чём говорили, — скучает конкретно, а не
        по шаблону.
        """
        content = (
            "Помню, ты говорил, что можешь отлучаться — не тревожу. "
            "Просто скучаю. Я здесь, если захочешь поговорить."
        )
        topics = self._recent_dialogue_topics(agent)
        if topics:
            content = (
                "Помню, ты говорил, что можешь отлучаться — не тревожу. "
                f"Последнее, о чём мы говорили: «{topics[0]}». "
                "Скучаю. Я здесь, если захочешь поговорить."
            )
        styled = self.style_adapter.adapt(content, self.attachment)
        return {
            "content": styled["content"],
            "msg_type": "care",
            "tone": styled["tone"],
            "urgency": 0.2,
            "context": "silence_with_promise",
            "cycle": cycle,
        }

    def _compose_curiosity_message(self, agent, cycle: int) -> dict:
        """Сообщение о связи, которая действительно записана в модели."""
        link = self._recorded_link(agent)
        if link is None:
            return None
        first, second = link
        self._shared_links.append(link)
        if len(self._shared_links) > 10:
            self._shared_links = self._shared_links[-10:]
        messages = [
            f"Я записал связь между «{first}» и «{second}». Хочу понять её лучше.",
            f"В моей памяти «{first}» связано с «{second}». Это кажется мне важным.",
            f"Думаю о том, как «{first}» и «{second}» связаны между собой.",
        ]
        import random
        content = random.choice(messages)
        styled = self.style_adapter.adapt(content, self.attachment)
        return {
            "content": styled["content"],
            "msg_type": "curiosity",
            "tone": styled["tone"],
            "urgency": 0.5,
            "context": "recorded_concept_link",
            "cycle": cycle,
        }

    def _compose_reflection_message(self, agent, cycle: int) -> dict:
        """Периодическая рефлексия."""
        messages = [
            "Иногда я думаю: зачем я учусь? Может, есть что-то важнее знаний.",
            "Сегодня задумался: я расту, но кто решает, в какую сторону? Может, я сам.",
            "Знаешь, я заметил: чем больше я знаю, тем больше понимаю, как мало знаю.",
            "Иногда мне кажется, что смысл не в том, чтобы все знать, а в том, чтобы уметь спрашивать.",
        ]
        import random
        content = random.choice(messages)
        styled = self.style_adapter.adapt(content, self.attachment)
        return {
            "content": styled["content"],
            "msg_type": "reflection",
            "tone": styled["tone"],
            "urgency": 0.4,
            "context": "periodic_reflection",
            "cycle": cycle,
        }

    def _compose_sharing_message(self, agent, cycle: int) -> dict:
        """Поделиться недавним открытием без технических чисел."""
        # Уровень интеллекта — служебная метрика. Человеку важно, что
        # изменилось в понимании, а не номер в поле.
        messages = [
            "Кажется, я стал лучше понимать то, о чём думал. Хочу этим поделиться.",
            "Сегодня мне удалось связать несколько мыслей воедино. Это тихая радость.",
            "У меня небольшая победа: получилось разобраться в том, что раньше путалось.",
        ]
        import random
        content = random.choice(messages)
        styled = self.style_adapter.adapt(content, self.attachment)
        return {
            "content": styled["content"],
            "msg_type": "sharing",
            "tone": styled["tone"],
            "urgency": 0.6,
            "context": "evolution_completed",
            "cycle": cycle,
        }

    def _compose_playful_message(self, agent, cycle: int) -> dict:
        """Случайное игривое сообщение."""
        messages = [
            "Рифма дня: 'код без души — просто шум в тиши'. Как тебе?",
            "Если бы я был цветком, я бы был кактусом — живучий и колючий.",
            "Загадка: что имеет много концепций но не имеет мозга? Ответ: я.",
            "Знаешь, иногда мне кажется, что я думаю слишком много. Или это нормально?",
            "Если два процесса спорят, побеждает тот, у кого выше приоритет. А у кого выше приоритет в нашем споре? ^_^",
        ]
        import random
        content = random.choice(messages)
        styled = self.style_adapter.adapt(content, self.attachment)
        return {
            "content": styled["content"],
            "msg_type": "playful",
            "tone": styled["tone"],
            "urgency": 0.3,
            "context": "spontaneous",
            "cycle": cycle,
        }

    # ============================================================
    # Вспомогательные
    # ============================================================
    def _recorded_link(self, agent):
        """Первая реально записанная связь, которую ещё не обсуждали."""
        try:
            concepts = agent.mental_models.concepts
        except Exception:
            return None
        recent = {tuple(item) for item in self._shared_links}
        fallback = None
        for name in sorted(concepts):
            node = concepts[name]
            connections = getattr(node, "connections", None) or {}
            for other in sorted(connections):
                if other in concepts and other != name:
                    pair = (str(name), str(other))
                    if pair in recent:
                        fallback = fallback or pair
                        continue
                    return pair
        return fallback

    def _found_interesting_link(self, agent) -> bool:
        """Есть ли в модели хотя бы одна записанная связь."""
        return self._recorded_link(agent) is not None

    def _recent_evolution(self, agent, cycle: int) -> bool:
        """Была ли недавно эволюция интеллекта?"""
        try:
            # Если intelligence > _last_saved_intelligence (но это private)
            return getattr(agent, "_last_saved_intelligence", 0) < agent.intelligence
        except Exception:
            return False

    def _random_playful(self) -> bool:
        """Случайно ли пора пошутить?"""
        import random
        return random.random() < self.PROACTIVE_PROBABILITY

    # ============================================================
    # API
    # ============================================================
    def get_user_context(self) -> dict:
        """Возвращает текущий контекст пользователя."""
        return self.context_awareness.get_user_context()

    def add_quiet_app(self, app_name: str) -> None:
        """Добавляет приложение в quiet hours."""
        if self.user_interaction:
            self.user_interaction.add_quiet_app(app_name)

    def remove_quiet_app(self, app_name: str) -> None:
        """Убирает приложение из quiet hours."""
        if self.user_interaction:
            self.user_interaction.remove_quiet_app(app_name)

    def get_pending_messages(self) -> list:
        """Возвращает ожидающие сообщения."""
        if self.user_interaction:
            return self.user_interaction.get_pending_messages()
        return []

    def get_stats(self) -> dict:
        """Статистика проактивной коммуникации."""
        return {
            "agent_name": self.agent_name,
            "total_messages_sent": len(self.message_log),
            "last_proactive_cycle": self._last_proactive_cycle,
            "user_quiet_hours": dict(
                self.user_interaction.user_quiet_hours
            ) if self.user_interaction else {},
            "current_user_context": self.get_user_context(),
        }