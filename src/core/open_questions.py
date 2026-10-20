"""
Open Questions — открытые вопросы (Свобода воли цифровой жизни).

Этот модуль вынесен из src/core/agent.py (Этап 4 рефакторинга, июль 2026).
DigitalBeing всё ещё предоставляет высокоуровневые методы
(ask_user, hint_to_open_question, drop_open_question, и др.),
но вся логика работы с очередью инкапсулирована здесь.

Архитектура:
- OpenQuestionsManager — основной класс.
- _QuestionRecord — dataclass-подобный dict (dict-friendly для JSON
  сериализации в чекпоинт; см. note в `to_dict`/`from_dict`).
- Стратегии размышления: round_robin по списку EXPLORATION_STRATEGIES.

Использование:
    >>> from src.core.open_questions import OpenQuestionsManager
    >>> mgr = OpenQuestionsManager(cycle_provider=lambda: 42)
    >>> mgr.ask("что такое любовь?", source="user")
    {'status': 'queued', 'id': ..., 'queue_size': 1}
    >>> mgr.has_unanswered()
    True
    >>> mgr.consume()  # вернёт стимул для thinking
    'вопрос: что такое любовь? [стратегия=mental_model_lookup, попытка 1/5]'
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional


# Шесть стратегий размышления. Приоритет по порядку: сначала
# ищем в ментальных моделях, потом в knowledge_base, и т.д.
EXPLORATION_STRATEGIES: List[str] = [
    "mental_model_lookup",   # ищем в ментальных моделях
    "knowledge_base_search", # в knowledge_base
    "hypothesis_generation", # генерируем гипотезу
    "decomposition",         # разбиваем на части
    "analogy_search",        # ищем аналогии в известном
    "cross_reference",       # ищем перекрёстные ссылки
]

# Эвристика «найден ответ» — определяется в ThinkingPipeline, но
# мы фильтруем здесь, чтобы не считать «Не знаю» за ответ.
_ANSWER_PREFILTER = ("Не знаю", "Новый концепт")
_ANSWER_REQUIRED_MARKER = "[Ментальная модель]"


class OpenQuestionsManager:
    """Менеджер очереди открытых вопросов.

    Атрибуты (хранятся как dict для совместимости с чекпоинтами):
        queue: List[dict] — очередь вопросов.
        max_size: int — лимит очереди.
        default_max_explorations: int — лимит размышлений на один вопрос.
        strategy_order: List[str] — порядок стратегий.

    Зависимости (внедряются через конструктор для тестируемости):
        cycle_provider: Callable[[], int] — функция, возвращающая
            текущий cycle_count агента. По умолчанию ленивая лямбда.
        log_info: Callable[[str], None] — логгер. По умолчанию no-op.
    """

    def __init__(
        self,
        cycle_provider: Optional[Callable[[], int]] = None,
        log_info: Optional[Callable[[str], None]] = None,
        max_size: int = 10,
        default_max_explorations: int = 5,
    ) -> None:
        self.queue: List[dict] = []
        self.max_size = max_size
        self.default_max_explorations = default_max_explorations
        self.strategy_order: List[str] = list(EXPLORATION_STRATEGIES)
        # Lazy-доступ к cycle_count (не нужен на момент __init__).
        self._cycle = cycle_provider or (lambda: 0)
        self._log = log_info or (lambda msg: None)

    # === API (тонкий фасад, ранее был в DigitalBeing) ===

    def ask(self, text: str, source: str = "user",
            max_explorations: Optional[int] = None) -> Dict:
        """Поставить открытый вопрос в очередь.

        Args:
            text: текст вопроса.
            source: "user" / "self" / "soul" / "exploration".
            max_explorations: лимит размышлений (None = default).

        Returns:
            ``{"status": "queued"|"duplicate"|"rejected", ...}``.
        """
        if not text or not text.strip():
            return {"status": "rejected", "reason": "пустой вопрос"}

        # Дедупликация: тот же текст (case-insensitive) — не дублируем.
        for q in self.queue:
            if q["text"].strip().lower() == text.strip().lower() and not q["answered"]:
                return {
                    "status": "duplicate",
                    "id": id(q),
                    "queue_size": len(self.queue),
                }

        # Лимит очереди — вытесняем самый старый неотвеченный.
        if len(self.queue) >= self.max_size:
            for q in self.queue:
                if not q["answered"]:
                    self.queue.remove(q)
                    break

        question = self._make_record(text, source, max_explorations)
        self.queue.append(question)
        self._log(
            f"[OpenQ] Поставлен в очередь: '{text[:60]}...' "
            f"(source={source}, cycle={self._cycle()})"
        )
        return {
            "status": "queued",
            "id": id(question),
            "queue_size": len(self.queue),
        }

    def hint(self, text: str, hint: str) -> Dict:
        """Добавить подсказку к существующему вопросу + дать ещё 2 попытки."""
        for q in self.queue:
            if q["text"].strip().lower() == text.strip().lower():
                q["hint"] = hint
                q["max_explorations"] += 2
                self._log(f"[OpenQ] Подсказка к '{text[:40]}': '{hint[:40]}'")
                return {"status": "hint_added"}
        return {"status": "not_found", "reason": "вопрос не в очереди"}

    def drop(self, text: str) -> Dict:
        """Удалить вопрос из очереди (пользователь отменил интерес)."""
        for q in list(self.queue):
            if q["text"].strip().lower() == text.strip().lower():
                self.queue.remove(q)
                return {"status": "dropped"}
        return {"status": "not_found"}

    def list_public(self) -> List[Dict]:
        """Копия очереди (только публичные поля, без explorations)."""
        return [
            {
                "text": q["text"],
                "source": q["source"],
                "explored": len(q["explorations"]),
                "max": q["max_explorations"],
                "answered": q["answered"],
                "hint": q.get("hint"),
            }
            for q in self.queue
        ]

    def has_unanswered(self) -> bool:
        """Есть ли в очереди неотвеченные вопросы?"""
        return any(not q["answered"] for q in self.queue)

    def consume(self) -> Optional[str]:
        """Взять следующий стимул для размышления.

        Стратегия: round_robin по списку стратегий — берём первую
        неиспользованную стратегию из ``EXPLORATION_STRATEGIES``.

        Returns:
            Строка для ``agent.perceive(stimulus)`` или ``None``.
        """
        for q in self.queue:
            if q["answered"]:
                continue
            if len(q["explorations"]) >= q["max_explorations"]:
                # Лимит исчерпан — помечаем как «неразрешённый».
                q["answered"] = True
                q["answer"] = (
                    f"Не удалось найти ответ за {q['max_explorations']} "
                    f"размышлений. Вопрос остаётся открытым."
                )
                self._log(
                    f"[OpenQ] Не разрешён за {q['max_explorations']} попыток: "
                    f"'{q['text'][:50]}...'"
                )
                continue

            # Выбираем стратегию (round_robin).
            explored = {e["strategy"] for e in q["explorations"]}
            chosen = next(
                (s for s in self.strategy_order if s not in explored),
                "hypothesis_generation",  # fallback если все испробованы
            )
            return (
                f"вопрос: {q['text']} "
                f"[стратегия={chosen}, "
                f"попытка {len(q['explorations']) + 1}/{q['max_explorations']}]"
            )
        return None

    def record_exploration(
        self, stimulus: str, thought: str, strategy: Optional[str] = None
    ) -> None:
        """Записать результат размышления над открытым вопросом.

        Эвристика «ответ найден»: thought не начинается с «Не знаю»,
        содержит маркер ``[Ментальная модель]`` и не пустой.
        """
        text_marker = "вопрос: "
        if not stimulus.startswith(text_marker):
            return
        # "вопрос: <text> [стратегия=..., попытка N/M]"
        rest = stimulus[len(text_marker):]
        if " [стратегия=" in rest:
            q_text = rest.split(" [стратегия=")[0].strip()
        else:
            q_text = rest.strip()

        for q in self.queue:
            if q["text"].strip().lower() == q_text.strip().lower() and not q["answered"]:
                q["last_explored_at"] = self._cycle()
                used_strategy = strategy
                if "[" in stimulus and "стратегия=" in stimulus:
                    try:
                        used_strategy = (
                            stimulus.split("стратегия=")[1].split(",")[0].strip()
                        )
                    except Exception:
                        pass

                q["explorations"].append({
                    "cycle": self._cycle(),
                    "thought": thought[:200],
                    "strategy": used_strategy or "unknown",
                })

                # Эвристика «найден ответ».
                if (
                    thought
                    and not thought.startswith(_ANSWER_PREFILTER)
                    and _ANSWER_REQUIRED_MARKER in thought
                ):
                    q["answered"] = True
                    q["answer"] = thought[:300]
                    self._log(
                        f"[OpenQ] Ответ найден на '{q_text[:40]}...': "
                        f"{thought[:80]}..."
                    )
                break

    # === Сериализация (чеклист) ===

    def to_dict(self) -> List[dict]:
        """Сохранить очередь для чекпоинта."""
        return list(self.queue)

    def load_from(self, saved: Optional[List[dict]]) -> int:
        """Восстановить очередь из чекпоинта. Возвращает кол-во загруженных."""
        self.queue = []
        if not saved:
            return 0
        for q_data in saved:
            self.queue.append({
                "text": q_data.get("text", ""),
                "source": q_data.get("source", "user"),
                "started_at": q_data.get("started_at", 0),
                "last_explored_at": q_data.get("last_explored_at", 0),
                "explorations": q_data.get("explorations", []),
                "max_explorations": q_data.get("max_explorations", self.default_max_explorations),
                "hint": q_data.get("hint"),
                "answered": q_data.get("answered", False),
                "answer": q_data.get("answer"),
            })
        return len(self.queue)

    # === Внутреннее ===

    def _make_record(
        self, text: str, source: str, max_explorations: Optional[int]
    ) -> dict:
        """Создать новую запись открытого вопроса."""
        cycle = self._cycle()
        return {
            "text": text.strip(),
            "source": source,
            "started_at": cycle,
            "last_explored_at": cycle,
            "explorations": [],
            "max_explorations": (
                max_explorations if max_explorations is not None
                else self.default_max_explorations
            ),
            "hint": None,
            "answered": False,
            "answer": None,
        }