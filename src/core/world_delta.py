"""Наблюдаемые изменения мира — доказательство, что действие что-то сделало.

Зачем это нужно
---------------
Раньше цикл жизни был разорван: агент выбирал действие, «выполнял» его и
увеличивал счётчик. Проверить, изменилось ли что-нибудь, было нельзя, а
цели стояли на нуле, потому что прогресс начислялся по теме стимула, а не
по результату действия.

Здесь вводится **подпись мира** — набор счётчиков, которые можно снять до
и после действия. Разница между ними и есть доказательство.

Принцип: считаем только то, что видно снаружи агента
----------------------------------------------------
Счётчики читаются из состояния, а не из самоотчёта. «Я узнал» не
считается; считается «в базе знаний появилась запись», «выросла
уверенность в концепции», «на вопрос найден ответ», «пришёл ответ из
сети». Иначе получился бы самоподтверждающийся цикл: агент хвалит себя
за то, что пошевелился.

Модуль ничего не меняет: только читает и сравнивает.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class WorldSignature:
    """Снимок наблюдаемого состояния мира в один момент.

    Attributes:
        knowledge_entries: записей в базе знаний.
        concepts: концепций в ментальных моделях.
        confidence_milli: сумма уверенностей × 1000 (целое, чтобы снимок
            был сравнимым и не зависел от плавающих погрешностей).
        answered_questions: открытых вопросов с найденным ответом.
        web_hits: успешных ответов из сети за жизнь процесса.
        notes: записей в журнале агента (если он есть).
    """

    knowledge_entries: int = 0
    concepts: int = 0
    confidence_milli: int = 0
    answered_questions: int = 0
    web_hits: int = 0
    notes: int = 0
    experiences: int = 0
    pending_questions: int = 0
    messages_sent: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "knowledge_entries": self.knowledge_entries,
            "concepts": self.concepts,
            "confidence_milli": self.confidence_milli,
            "answered_questions": self.answered_questions,
            "web_hits": self.web_hits,
            "notes": self.notes,
            "experiences": self.experiences,
            "pending_questions": self.pending_questions,
            "messages_sent": self.messages_sent,
        }


@dataclass(frozen=True)
class WorldDelta:
    """Разница между двумя подписями мира.

    Значения могут быть отрицательными (агент забыл концепцию, база знаний
    сократилась при очистке). Для решения «действие дало эффект» важно
    только то, что изменение вообще есть.
    """

    knowledge_entries: int = 0
    concepts: int = 0
    confidence_milli: int = 0
    answered_questions: int = 0
    web_hits: int = 0
    notes: int = 0
    experiences: int = 0
    pending_questions: int = 0
    messages_sent: int = 0

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        """Ничего наблюдаемого не изменилось."""
        return not any(
            (
                self.knowledge_entries,
                self.concepts,
                self.confidence_milli,
                self.answered_questions,
                self.web_hits,
                self.notes,
                self.experiences,
                self.pending_questions,
                self.messages_sent,
            )
        )

    @property
    def has_gain(self) -> bool:
        """Появилось что-то новое (а не только исчезло старое)."""
        return any(
            value > 0
            for value in (
                self.knowledge_entries,
                self.concepts,
                self.confidence_milli,
                self.answered_questions,
                self.web_hits,
                self.notes,
                self.experiences,
                self.pending_questions,
                self.messages_sent,
            )
        )

    @property
    def confidence_gain(self) -> float:
        """Прирост суммарной уверенности в обычных единицах."""
        return self.confidence_milli / 1000.0

    def summary(self) -> str:
        """Короткое человекочитаемое описание изменений."""
        if self.is_empty:
            return "без изменений"

        parts = []
        if self.knowledge_entries:
            parts.append(f"знаний {self.knowledge_entries:+d}")
        if self.concepts:
            parts.append(f"концепций {self.concepts:+d}")
        if self.confidence_milli:
            parts.append(f"уверенность {self.confidence_gain:+.2f}")
        if self.answered_questions:
            parts.append(f"ответов {self.answered_questions:+d}")
        if self.web_hits:
            parts.append(f"из сети {self.web_hits:+d}")
        if self.notes:
            parts.append(f"записей {self.notes:+d}")
        if self.experiences:
            parts.append(f"опыта {self.experiences:+d}")
        if self.pending_questions:
            parts.append(f"вопросов {self.pending_questions:+d}")
        if self.messages_sent:
            parts.append(f"сообщений {self.messages_sent:+d}")
        return ", ".join(parts)

    def as_dict(self) -> Dict[str, int]:
        return {
            "knowledge_entries": self.knowledge_entries,
            "concepts": self.concepts,
            "confidence_milli": self.confidence_milli,
            "answered_questions": self.answered_questions,
            "web_hits": self.web_hits,
            "notes": self.notes,
            "experiences": self.experiences,
            "pending_questions": self.pending_questions,
            "messages_sent": self.messages_sent,
        }


def between(before: WorldSignature, after: WorldSignature) -> WorldDelta:
    """Разница двух подписей: ``after - before``."""
    return WorldDelta(
        knowledge_entries=after.knowledge_entries - before.knowledge_entries,
        concepts=after.concepts - before.concepts,
        confidence_milli=after.confidence_milli - before.confidence_milli,
        answered_questions=(
            after.answered_questions - before.answered_questions
        ),
        web_hits=after.web_hits - before.web_hits,
        notes=after.notes - before.notes,
        experiences=after.experiences - before.experiences,
        pending_questions=(
            after.pending_questions - before.pending_questions
        ),
        messages_sent=after.messages_sent - before.messages_sent,
    )


# ============================================================
# Снятие подписи
# ============================================================


def _count_answered_questions(agent: Any) -> int:
    """Сколько открытых вопросов уже имеют ответ."""
    questions = getattr(agent, "_open_questions", None)
    if not isinstance(questions, list):
        return 0
    return sum(
        1
        for item in questions
        if isinstance(item, dict) and item.get("answered") and item.get("answer")
    )


def _count_web_hits(agent: Any) -> int:
    """Успешные ответы из сети (если поиск подключён)."""
    searcher = getattr(agent, "web_searcher", None)
    if searcher is None:
        return 0
    try:
        stats = searcher.get_stats()
    except Exception:
        return 0
    if not isinstance(stats, dict):
        return 0
    # Разные версии WebSearcher называют счётчик по-разному.
    for key in ("found", "hits", "successful", "results"):
        value = stats.get(key)
        if isinstance(value, int):
            return value
    return 0


def _count_notes(agent: Any) -> int:
    """Записи в личном журнале агента, если такой есть."""
    for attr in ("journal", "notes", "diary"):
        value = getattr(agent, attr, None)
        if isinstance(value, (list, dict)):
            return len(value)
    return 0


def _count_pending_questions(agent: Any) -> int:
    """Сколько вопросов агент задал человеку.

    Считаем по журналу воли: он переживает перезапуск. Очередь вопросов
    не годится — после ответа она очищается, и «спросил, получил ответ»
    выглядело бы как «ничего не сделал».
    """
    registry = getattr(agent, "will_registry", None)
    if registry is not None:
        try:
            by_type = (registry.get_stats() or {}).get("by_type") or {}
            value = by_type.get("questions_asked")
            if isinstance(value, int):
                return value
        except Exception:
            pass
    return 0


def _count_messages_sent(agent: Any) -> int:
    """Сколько сообщений агент отправил человеку.

    Берём журнал воли: он переживает перезапуск и не зависит от того,
    какая подсистема отправляла сообщение.
    """
    registry = getattr(agent, "will_registry", None)
    if registry is not None:
        try:
            by_type = (registry.get_stats() or {}).get("by_type") or {}
            value = by_type.get("messages_sent")
            if isinstance(value, int):
                return value
        except Exception:
            pass
    proactive = getattr(agent, "proactive_communication", None)
    log = getattr(proactive, "message_log", None)
    if isinstance(log, list):
        return len(log)
    return 0


def capture(agent: Any) -> WorldSignature:
    """Снимает подпись мира с агента.

    Устойчиво к неполным объектам: в тестах и при восстановлении из старых
    чекпоинтов каких-то полей может не быть.
    """
    knowledge = getattr(agent, "knowledge_base", None)
    knowledge_entries = len(knowledge) if isinstance(knowledge, dict) else 0

    mental_models = getattr(agent, "mental_models", None)
    concepts_map = getattr(mental_models, "concepts", None)
    if isinstance(concepts_map, dict):
        concepts = len(concepts_map)
        confidence_sum = 0.0
        experiences = 0
        for node in concepts_map.values():
            try:
                confidence_sum += float(getattr(node, "confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                pass
            try:
                experiences += len(getattr(node, "experiences", []) or [])
            except TypeError:
                pass
        confidence_milli = int(round(confidence_sum * 1000))
    else:
        concepts = 0
        confidence_milli = 0
        experiences = 0

    return WorldSignature(
        knowledge_entries=knowledge_entries,
        concepts=concepts,
        confidence_milli=confidence_milli,
        answered_questions=_count_answered_questions(agent),
        web_hits=_count_web_hits(agent),
        notes=_count_notes(agent),
        experiences=experiences,
        pending_questions=_count_pending_questions(agent),
        messages_sent=_count_messages_sent(agent),
    )


__all__ = [
    "WorldSignature",
    "WorldDelta",
    "between",
    "capture",
]
