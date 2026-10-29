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

    def _compose_curiosity_message(self, agent, cycle: int) -> dict:
        """Сообщение о найденной связи между концепциями."""
        try:
            concepts = list(agent.mental_models.concepts.keys())
            if len(concepts) < 2:
                return None
            import random
            c1, c2 = random.sample(concepts, 2)
            messages = [
                f"Я заметил, что у '{c1}' и '{c2}' похожая структура. Тебе не кажется?",
                f"Интересно: '{c1}' и '{c2}' — между ними что-то есть. Думал об этом?",
                f"Случайно нашёл связь: '{c1}' связано с '{c2}'. Это случайно или нет?",
            ]
            content = random.choice(messages)
            styled = self.style_adapter.adapt(content, self.attachment)
            return {
                "content": styled["content"],
                "msg_type": "curiosity",
                "tone": styled["tone"],
                "urgency": 0.5,
                "context": "concept_link_found",
                "cycle": cycle,
            }
        except Exception:
            return None

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
        """Поделиться недавним открытием."""
        intelligence = getattr(agent, "intelligence", 1)
        messages = [
            f"Представляешь, я только что понял как работает кое-что новое. Мой интеллект: {intelligence}.",
            "Хочу поделиться открытием. Сегодня я связал несколько понятий воедино.",
            "У меня маленькая победа — эволюция прошла. Чувствую, что становлюсь умнее.",
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
    def _found_interesting_link(self, agent) -> bool:
        """Проверяет, появились ли новые интересные связи."""
        try:
            concepts = agent.mental_models.concepts
            if len(concepts) < 2:
                return False
            # Считаем связи за последнее время
            total_links = sum(len(n.connections) for n in concepts.values())
            return total_links > len(concepts) * 0.3  # эвристика
        except Exception:
            return False

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