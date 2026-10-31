"""
UserModel — убеждения Core о человеке (участок «Собеседник», ступень 2).

До этого этапа слова пользователя о себе испарялись: живой прогон
2026-11-01 показал, что «могу отлучаться надолго — не переживай, если
молчу» исчезало, а детектор тишины продолжал тревожиться («давно тебя
не слышу» через 6 циклов после реплики человека).

Здесь хранятся ТОЛЬКО факты о пользователе: обещания («не переживай»),
привычки и черты («я обычно работаю по ночам»), цикл последнего
контакта. Граница субъектности: ничего из этого не пишется в ценности,
мотивацию или innate_values — человек не может влиять на желания Core
через слова, только на убеждения о себе.

Извлечение детерминированное (таблицы маркеров, без LLM). Структура
сериализуется в чекпоинт: после рестарта сущность не забывает, что ей
обещали. Реестры маркеров вынесены на уровень модуля для будущих
ступеней (включая возможное саморазвитие таблиц самой сущностью).
"""
from __future__ import annotations

from typing import Dict, Optional

# Обещания пользователя: вид → маркеры. Вид определяет, как убеждение
# меняет поведение Core (см. proactive_communication).
PROMISE_MARKERS: Dict[str, tuple] = {
    "silence_tolerance": (
        "не переживай",
        "не волнуйся",
        "буду молчать",
        "могу молчать",
        "могу отлучаться",
        "могу пропадать",
        "могу долго не писать",
        "отлучусь",
        "не жди",
        "не скучай",
    ),
}

# Привычки и черты: пользователь рассказал о себе.
TRAIT_MARKERS: tuple = (
    "я обычно",
    "я всегда",
    "я часто",
    "я никогда",
    "я работаю",
    "я учусь",
    "я люблю",
    "я не люблю",
    "мне нравится",
    "мне не нравится",
)

_PROMISES_MAX = 20
_TRAITS_MAX = 20


class UserModel:
    """Убеждения Core о человеке: обещания, черты, последний контакт.

    Только факты о пользователе; субъектность Core не затрагивается.
    Сериализуется в чекпоинт (checkpoint_serializer).
    """

    def __init__(self) -> None:
        # kind → {"text": str, "cycle": int} — последнее обещание вида
        self.promises: Dict[str, dict] = {}
        # маркер → текст рассказа о себе (последний по маркеру)
        self.traits: Dict[str, str] = {}
        self.last_contact_cycle: Optional[int] = None

    # === Наблюдение ===

    def observe(self, text, cycle: int = 0) -> Dict[str, list]:
        """Извлечь факты о пользователе из реплики.

        Возвращает, что именно записано (для тестов и журналов):
        ``{"promises": [...], "traits": [...]}``. Пустые списки —
        реплика не содержала узнаваемых фактов, это нормально.
        """
        normalized = " ".join(str(text or "").lower().split())
        recorded: Dict[str, list] = {"promises": [], "traits": []}
        if not normalized:
            return recorded

        for kind, markers in PROMISE_MARKERS.items():
            for marker in markers:
                if marker in normalized:
                    self.promises[kind] = {
                        "text": normalized[:150],
                        "cycle": int(cycle),
                    }
                    recorded["promises"].append(kind)
                    break

        for marker in TRAIT_MARKERS:
            if marker in normalized:
                self.traits[marker] = normalized[:150]
                recorded["traits"].append(marker)
                if len(self.traits) > _TRAITS_MAX:
                    self._trim_traits()

        if recorded["promises"] or recorded["traits"]:
            self.last_contact_cycle = int(cycle)
        return recorded

    def note_contact(self, cycle: int) -> None:
        """Зафиксировать контакт без содержательных фактов."""
        self.last_contact_cycle = int(cycle)

    # === Запросы ===

    def has_silence_tolerance(self) -> bool:
        """Пользователь обещал терпимость к молчанию сущности?"""
        return "silence_tolerance" in self.promises

    def silence_promise(self) -> Optional[dict]:
        """Последнее обещание терпимости к молчанию (или None)."""
        return self.promises.get("silence_tolerance")

    def get_status(self) -> dict:
        return {
            "promises": sorted(self.promises),
            "traits_count": len(self.traits),
            "last_contact_cycle": self.last_contact_cycle,
        }

    # === Сериализация ===

    def to_dict(self) -> dict:
        return {
            "promises": {
                kind: dict(entry) for kind, entry in self.promises.items()
            },
            "traits": dict(self.traits),
            "last_contact_cycle": self.last_contact_cycle,
        }

    def load_from(self, data) -> None:
        """Восстановиться из чекпоинта. Повреждённые поля → дефолты."""
        if not isinstance(data, dict):
            return
        promises = data.get("promises")
        if isinstance(promises, dict):
            restored = {}
            for kind, entry in promises.items():
                if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                    restored[str(kind)] = {
                        "text": str(entry["text"]),
                        "cycle": int(entry.get("cycle") or 0),
                    }
            self.promises = restored
        traits = data.get("traits")
        if isinstance(traits, dict):
            self.traits = {
                str(key): str(value)
                for key, value in traits.items()
                if isinstance(value, str)
            }
        contact = data.get("last_contact_cycle")
        self.last_contact_cycle = (
            int(contact) if isinstance(contact, (int, float)) else None
        )

    # === Внутреннее ===

    def _trim_traits(self) -> None:
        """Держим шапку рассказов о пользователе ограниченной.

        dict в Python сохраняет порядок вставки: стираем самые старые
        записи, пока размер не вернётся в лимит.
        """
        for key in list(self.traits):
            if len(self.traits) <= _TRAITS_MAX:
                break
            del self.traits[key]
        if len(self.promises) > _PROMISES_MAX:
            self.promises.clear()
