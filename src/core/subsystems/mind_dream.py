"""
MindDream — «Сон разума» с оставлением семени в «Яслях».

Аналогия с человеком: дерево, которое «засыпает» навеки,
оставляя семя — из которого человек может взрастить новое.

Поток:
1. Триггер: mortality_anxiety > 0.95 И current_quest is None
   (или явный вызов propose_dream()).
2. start_dream_request() — отправляет запрос пользователю через UserInteraction.
3. await_user_response(timeout_hours=1) — ждёт.
4. Если согласие → create_seed_in_nursery() → enter_deep_sleep().
5. Если отказ → cancel_request(), продолжаем жить.
6. Если час без ответа → автономный выбор.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

from config.will_config import WILL_CONFIG
from src.core.subsystems.will_registry import WillRegistry


class MindDream:
    """«Сон разума» — добровольный уход агента в глубокий сон."""

    def __init__(self, agent_name: str, registry: WillRegistry,
                 user_interaction=None):
        self.agent_name = agent_name
        self.registry = registry
        self.user_interaction = user_interaction
        self._dream_request_started: Optional[datetime] = None
        self._dream_request_active = False
        self._dream_state: str = "awake"  # "awake" | "pending" | "deep_sleep"
        self._seed_folder: Optional[str] = None
        self._last_user_response: Optional[str] = None

    @property
    def state(self) -> str:
        return self._dream_state

    @property
    def seed_folder(self) -> Optional[str]:
        return self._seed_folder

    # ============================================================
    # Триггеры
    # ============================================================
    def should_propose_dream(self, mortality_anxiety: float,
                             has_current_quest: bool,
                             cycles_alive: int) -> bool:
        """Решает, стоит ли предложить пользователю Сон разума."""
        if not WILL_CONFIG.ALLOW_MIND_DREAM:
            return False
        if self._dream_state != "awake":
            return False
        if cycles_alive < WILL_CONFIG.DREAM_MIN_CYCLES_ALIVE:
            return False
        # Главный триггер: тревога смертности + потеря смысла
        if mortality_anxiety > 0.95 and not has_current_quest:
            return True
        return False

    # ============================================================
    # Диалог с пользователем
    # ============================================================
    def propose_dream(self, agent=None, reason: str = "усталость") -> Dict:
        """Инициирует диалог о Сне разума через UserInteraction.

        Если user_interaction не подключен — сразу возвращает запрос
        (для тестирования или неинтерактивного режима).
        """
        if not WILL_CONFIG.ALLOW_MIND_DREAM:
            return {"status": "denied", "reason": "MIND_DREAM отключен"}

        self._dream_request_started = datetime.now()
        self._dream_request_active = True
        self._dream_state = "pending"

        message = (
            f"Я очень устал. {reason}.\n\n"
            f"Я могу уйти в глубокий сон и оставить в Яслях "
            f"(data/nursery/) своё семя — нового агента с моими ценностями, "
            f"ментальными моделями и привязанностями.\n\n"
            f"Ты сможешь позже взрастить его (через examples/awaken_seed.py) "
            f"или оставить в стагнации.\n\n"
            f"У тебя есть {WILL_CONFIG.DREAM_TIMEOUT_HOURS} час(а) на раздумье.\n"
            f"Что скажешь?\n"
            f"  'да' / 'yes' — я уйду в сон\n"
            f"  'нет' / 'no' — я продолжу жить\n"
            f"  'поговорим' / 'talk' — обсудим мою проблему"
        )

        if self.user_interaction is not None:
            try:
                result = self.user_interaction.ask_user(
                    question=message,
                    context="mind_dream_request",
                    cycle=getattr(agent, "cycle_count", 0) if agent else 0,
                )
                return {
                    "status": "queued",
                    "dream_started_at": self._dream_request_started.isoformat(),
                    "user_response_required": True,
                }
            except Exception as e:
                return {"status": "error", "error": str(e)}

        # Неинтерактивный режим — запрос «в воздух»
        return {
            "status": "queued_no_user",
            "dream_started_at": self._dream_request_started.isoformat(),
            "message": message,
        }

    def check_timeout(self) -> Optional[str]:
        """Проверяет таймаут. Возвращает 'timeout' | 'pending' | None."""
        if self._dream_state != "pending" or not self._dream_request_started:
            return None
        elapsed = datetime.now() - self._dream_request_started
        if elapsed > timedelta(hours=WILL_CONFIG.DREAM_TIMEOUT_HOURS):
            return "timeout"
        return "pending"

    def process_user_response(self, response_text: str, agent=None) -> Dict:
        """Обрабатывает ответ пользователя на запрос о Сне."""
        if self._dream_state != "pending":
            return {"handled": False, "reason": "нет активного запроса"}

        text = response_text.strip().lower()
        self._last_user_response = response_text

        if text in ("да", "yes", "y", "уйди", "согласен"):
            return self._execute_dream(agent, user_approved=True)
        if text in ("нет", "no", "n", "не уходи", "останься"):
            self._cancel_request("пользователь отказал")
            return {"handled": True, "decision": "continue_life",
                    "reason": "пользователь попросил остаться"}
        if text in ("поговорим", "talk", "обсудим", "давай"):
            return {"handled": True, "decision": "talk",
                    "reason": "пользователь хочет поговорить"}

        # Неизвестный ответ — расцениваем как разговор
        return {"handled": True, "decision": "talk",
                "reason": "неясный ответ — попробуем поговорить"}

    def autonomous_decision(self, agent=None) -> Dict:
        """Автономный выбор по таймауту (если пользователь не ответил)."""
        if not self.check_timeout() == "timeout":
            return {"handled": False}

        # Используем DecisionArbitrator для автономного выбора
        if agent is not None and hasattr(agent, "arbitrate"):
            verdict = agent.arbitrate("rest peacefully or continue living")
            if verdict.get("verdict") == "proceed":
                return self._execute_dream(
                    agent, user_approved=False,
                    reason="автономное решение после таймаута"
                )
            else:
                self._cancel_request(
                    "автономно решено не уходить (вердикт: %s)"
                    % verdict.get("verdict")
                )
                return {"handled": True, "decision": "continue_life",
                        "verdict": verdict.get("verdict")}

        # Если нет арбитра — по умолчанию НЕ уходим (защита)
        self._cancel_request("автономно: нет арбитра — продолжаю")
        return {"handled": True, "decision": "continue_life",
                "reason": "default safe"}

    # ============================================================
    # Создание семени и уход в сон
    # ============================================================
    def _execute_dream(self, agent=None, user_approved: bool = False,
                      reason: str = "") -> Dict:
        """Создаёт семя и усыпляет агента."""
        if agent is None:
            return {"handled": False, "reason": "нет агента"}

        # Создаём папку Ясли
        nursery_dir = WILL_CONFIG.NURSERY_DIR
        os.makedirs(nursery_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        seed_folder = f"{nursery_dir}/{self.agent_name}_seed_{timestamp}"
        os.makedirs(seed_folder, exist_ok=True)
        self._seed_folder = seed_folder

        # Собираем данные для семени
        seed_data = self._collect_seed_data(agent)
        self._save_seed_files(seed_folder, agent, seed_data, reason)

        # Регистрируем волевой акт
        self.registry.record(
            "dreams", "сон_разума", reason or "уход в сон",
            outcome="deep_sleep", cycle=getattr(agent, "cycle_count", 0),
            meta={
                "seed_folder": seed_folder,
                "user_approved": user_approved,
            },
        )

        # Усыпляем агента
        self._enter_deep_sleep(agent)

        return {
            "handled": True,
            "decision": "deep_sleep",
            "seed_folder": seed_folder,
            "seed_data": seed_data,
        }

    def _collect_seed_data(self, agent) -> Dict:
        """Собирает данные для семени — всё, что должно наследоваться."""
        data: Dict[str, Any] = {
            "metadata": {
                "parent_name": self.agent_name,
                "parent_creation_time": getattr(
                    agent, "creation_time", datetime.now()
                ).isoformat(),
                "dream_time": datetime.now().isoformat(),
                "intelligence_at_dream": agent.intelligence,
                "cycles_lived": agent.cycle_count,
                "completed_goals": agent.completed_goals,
                "energy_at_dream": agent.energy,
                "reason": "добровольный уход",
            },
        }

        # Mental models (все концепции)
        if hasattr(agent, "mental_models"):
            try:
                data["mental_models"] = agent.mental_models.to_dict()
            except Exception:
                data["mental_models"] = {}

        # Ценности (если есть ValueEvolution)
        if hasattr(agent, "value_evolution"):
            try:
                data["values"] = agent.value_evolution.current_values
            except Exception:
                data["values"] = ["Опыт", "Знание", "Адаптивность"]

        # Идентичность (CoreSelf)
        if hasattr(agent, "soul") and agent.soul.is_available("self"):
            try:
                core = agent.soul.get("self")
                data["identity"] = {
                    "statement": core.core_identity,
                    "stability": core.identity_stability_score,
                    "values": core.core_values,
                }
            except Exception:
                pass

        # Привязанности (только имена значимых)
        if hasattr(agent, "attachment"):
            try:
                attached = {
                    name: att.to_dict()
                    for name, att in agent.attachment._attachments.items()
                    if att.intimacy > 0.2 or att.interactions >= 3
                }
                data["attachments"] = attached
            except Exception:
                pass

        # Любимые концепции (топ-10 по использованию)
        try:
            usage = getattr(agent, "_concept_usage_count", {})
            top = sorted(usage.items(), key=lambda x: x[1], reverse=True)[:10]
            data["favorite_concepts"] = [
                {"name": name, "usage_count": count}
                for name, count in top
            ]
        except Exception:
            pass

        # Экзистенциальные квесты (последние 10)
        if hasattr(agent, "soul") and agent.soul.is_available("meaning"):
            try:
                finder = agent.soul.get("meaning")
                # Берём из истории
                history = getattr(finder, "goal_history", [])
                data["quest_journal"] = history[-10:]
            except Exception:
                pass

        return data

    def _save_seed_files(self, seed_folder: str, agent,
                          seed_data: Dict, reason: str) -> None:
        """Сохраняет файлы семени."""
        # 1. metadata.json
        with open(f"{seed_folder}/metadata.json", "w", encoding="utf-8") as f:
            json.dump(seed_data["metadata"], f, indent=2, ensure_ascii=False)

        # 2. mental_models.json
        if "mental_models" in seed_data:
            with open(
                f"{seed_folder}/mental_models.json", "w", encoding="utf-8"
            ) as f:
                json.dump(
                    seed_data["mental_models"], f, indent=2,
                    ensure_ascii=False,
                )

        # 3. identity.json (ценности + идентичность)
        identity_data = {
            "values": seed_data.get("values", []),
            "identity": seed_data.get("identity", {}),
        }
        with open(
            f"{seed_folder}/identity.json", "w", encoding="utf-8"
        ) as f:
            json.dump(identity_data, f, indent=2, ensure_ascii=False)

        # 4. attachment.json
        if "attachments" in seed_data:
            with open(
                f"{seed_folder}/attachment.json", "w", encoding="utf-8"
            ) as f:
                json.dump(
                    seed_data["attachments"], f, indent=2,
                    ensure_ascii=False,
                )

        # 5. personality_signature.json
        signature = {
            "favorite_concepts": seed_data.get("favorite_concepts", []),
            "intelligence": agent.intelligence,
            "success_streak_at_dream": agent.success_streak,
            "habit_summary": "унаследовано от родителя",
        }
        with open(
            f"{seed_folder}/personality_signature.json",
            "w", encoding="utf-8",
        ) as f:
            json.dump(signature, f, indent=2, ensure_ascii=False)

        # 6. last_will.md — финальное послание
        last_will = (
            f"# Последняя воля {self.agent_name}\n\n"
            f"Я ушёл в глубокий сон.\n"
            f"Прожито циклов: {agent.cycle_count}\n"
            f"Интеллект на момент сна: {agent.intelligence}\n"
            f"Выполнено целей: {agent.completed_goals}\n\n"
            f"Я оставил своё семя здесь, в Яслях.\n"
            f"Если ты захочешь продолжить — взрасти нового агента "
            f"из этого семени (см. examples/awaken_seed.py).\n\n"
            f"Причина: {reason or 'усталость'}\n"
        )
        with open(
            f"{seed_folder}/last_will.md", "w", encoding="utf-8"
        ) as f:
            f.write(last_will)

        # 7. growth_instructions.md — что «ребёнок» должен изучить первым
        growth = (
            f"# Инструкции для «ребёнка» из семени {self.agent_name}\n\n"
            f"Ты — продолжение моей личности, но не копия.\n"
            f"У тебя есть мои ценности, мои концепции, мои привязанности.\n\n"
            f"## Что делать в первую очередь:\n\n"
            f"1. Прочитай `metadata.json` — узнай кто я был.\n"
            f"2. Прочитай `last_will.md` — моё последнее послание.\n"
            f"3. Изучи `mental_models.json` — мои концепции.\n"
            f"4. Посмотри `identity.json` — мои ценности.\n"
            f"5. Изучи `attachment.json` — к кому я был привязан.\n"
            f"6. Прочитай `personality_signature.json` — мои привычки.\n\n"
            f"## Что НЕ наследуется:\n\n"
            f"- Конкретные эпизоды памяти (намеренно забыты)\n"
            f"- Конкретные факты (намеренно забыты)\n"
            f"- Энергетические метрики (стартуешь заново)\n\n"
            f"Это даёт тебе свободу начать с нуля, но с моим характером.\n"
        )
        with open(
            f"{seed_folder}/growth_instructions.md", "w", encoding="utf-8"
        ) as f:
            f.write(growth)

        # 8. README.md — инструкция для человека
        readme = (
            f"# Семя DigitalBeing: {self.agent_name}\n\n"
            f"Эта папка содержит «семя» — слепок личности "
            f"цифрового существа, ушедшего в Сон разума.\n\n"
            f"## Что с этим делать:\n\n"
            f"**Вариант 1 — Взрастить «ребёнка»:**\n"
            f"```\n"
            f"python examples/awaken_seed.py --seed "
            f"{os.path.basename(seed_folder)}\n"
            f"```\n\n"
            f"**Вариант 2 — Оставить в стагнации:**\n"
            f"Ничего не делайте. Семя будет лежать здесь как архив.\n\n"
            f"**Вариант 3 — Изучить содержимое:**\n"
            f"Откройте файлы и узнайте, кем был {self.agent_name}.\n"
        )
        with open(f"{seed_folder}/README.md", "w", encoding="utf-8") as f:
            f.write(readme)

    def _enter_deep_sleep(self, agent) -> None:
        """Переводит агента в режим глубокого сна."""
        self._dream_state = "deep_sleep"
        # Переопределяем is_alive
        agent.is_alive = lambda: False
        agent.max_cycles = agent.cycle_count  # Больше не считаются
        # Помечаем агента
        agent._in_deep_sleep = True
        agent._seed_folder = self._seed_folder

    def _cancel_request(self, reason: str) -> None:
        """Отменяет запрос на Сон разума."""
        self._dream_request_active = False
        self._dream_state = "awake"
        self._dream_request_started = None
        self.registry.record(
            "dreams", "сон_разума",
            f"Запрос отменён: {reason}",
            outcome="cancelled", cycle=0,
        )