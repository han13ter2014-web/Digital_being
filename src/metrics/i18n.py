"""
i18n — базовый менеджер локализаций Digital Being (Этап 3.7).

Архитектурное решение:
- Простой key-value словарь переводов, без внешних зависимостей.
- Загрузка из JSON-файлов в `data/i18n/{lang}.json`.
- Fallback на язык `default` (русский) при отсутствии ключа.
- Потокобезопасен (RLock).
- Поддержка интерполяции: `t("hello", name="Lucy")` → "Привет, Lucy!".

Использование:
    from src.metrics.i18n import set_language, t

    set_language("en")
    print(t("dashboard.title"))  # "Digital Being — Dashboard"
    print(t("greeting", name="Lucy"))  # "Hello, Lucy!"

Файлы локализаций: `data/i18n/ru.json`, `data/i18n/en.json`.
"""

import json
import logging
import os
import threading
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


# Базовый путь к локализациям
_DEFAULT_LOCALE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "i18n",
)


class I18n:
    """Менеджер локализаций."""

    DEFAULT_LANGUAGE = "ru"
    SUPPORTED_LANGUAGES = ("ru", "en")

    def __init__(self, locale_dir: Optional[str] = None,
                 default_language: str = DEFAULT_LANGUAGE) -> None:
        self._locale_dir = locale_dir or _DEFAULT_LOCALE_DIR
        self._default_language = default_language
        self._current_language = default_language
        self._translations: Dict[str, Dict[str, str]] = {}
        self._lock = threading.RLock()
        # Загружаем дефолтный язык сразу
        self._load_language(default_language)

    # ----------------------------------------------------------------
    # Управление языком
    # ----------------------------------------------------------------

    def set_language(self, language: str) -> bool:
        """Установить текущий язык. Возвращает True если успешно."""
        language = (language or "").lower()
        if not language:
            return False
        with self._lock:
            if language == self._current_language:
                return True
            if language not in self._translations:
                if not self._load_language(language):
                    return False
            self._current_language = language
            return True

    def get_language(self) -> str:
        with self._lock:
            return self._current_language

    def list_languages(self) -> list:
        """Список загруженных языков."""
        with self._lock:
            return sorted(self._translations.keys())

    # ----------------------------------------------------------------
    # Перевод
    # ----------------------------------------------------------------

    def t(self, key: str, /, **kwargs: Any) -> str:
        """Перевести ключ. Если ключ не найден — возвращает key.

        Поддерживает интерполяцию:
            t("hello", name="Lucy") → t.__call__ ищет {name} в строке.
        """
        with self._lock:
            # Сначала ищем в текущем языке
            value = self._translations.get(self._current_language, {}).get(key)
            # Затем в дефолтном
            if value is None:
                value = self._translations.get(self._default_language, {}).get(key)
        if value is None:
            return key  # ключ не найден — возвращаем как есть
        # Интерполяция
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError):
                return value
        return value

    # Без аргументов — можно звать как i18n.t("key")
    __call__ = t

    def has(self, key: str, language: Optional[str] = None) -> bool:
        """Проверить наличие ключа в указанном (или текущем) языке."""
        lang = language or self._current_language
        with self._lock:
            return key in self._translations.get(lang, {})

    # ----------------------------------------------------------------
    # Загрузка / сохранение
    # ----------------------------------------------------------------

    def _load_language(self, language: str) -> bool:
        """Загрузить переводы из JSON-файла. Возвращает успех."""
        path = os.path.join(self._locale_dir, f"{language}.json")
        if not os.path.isfile(path):
            logger.debug(f"[i18n] файл не найден: {path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(f"[i18n] {path} не dict, пропускаем")
                return False
            self._translations[language] = {
                str(k): str(v) for k, v in data.items()
            }
            logger.info(f"[i18n] загружен {language}: {len(data)} ключей")
            return True
        except Exception as e:
            logger.warning(f"[i18n] ошибка загрузки {path}: {e}")
            return False

    def load_all(self) -> int:
        """Загрузить все поддерживаемые языки из locale_dir.
        Возвращает количество успешно загруженных."""
        loaded = 0
        for lang in self.SUPPORTED_LANGUAGES:
            with self._lock:
                if self._load_language(lang):
                    loaded += 1
        return loaded

    def save_translations(self, language: str,
                           translations: Dict[str, str]) -> bool:
        """Сохранить переводы в JSON-файл."""
        try:
            os.makedirs(self._locale_dir, exist_ok=True)
            path = os.path.join(self._locale_dir, f"{language}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(translations, f, ensure_ascii=False, indent=2)
            # Обновляем кэш
            with self._lock:
                self._translations[language] = dict(translations)
            return True
        except Exception as e:
            logger.warning(f"[i18n] ошибка сохранения: {e}")
            return False

    # ----------------------------------------------------------------
    # Утилиты для тестов
    # ----------------------------------------------------------------

    def clear(self) -> None:
        """Очистить все переводы (только для тестов)."""
        with self._lock:
            self._translations.clear()


# ============================================================
# Глобальный экземпляр и удобные функции
# ============================================================

_global_i18n: Optional[I18n] = None
_global_lock = threading.Lock()


def get_i18n() -> I18n:
    """Получить глобальный экземпляр i18n (singleton)."""
    global _global_i18n
    if _global_i18n is None:
        with _global_lock:
            if _global_i18n is None:
                _global_i18n = I18n()
                _global_i18n.load_all()
    return _global_i18n


def set_language(language: str) -> bool:
    """Установить язык в глобальном i18n."""
    return get_i18n().set_language(language)


def t(key: str, /, **kwargs: Any) -> str:
    """Перевести ключ через глобальный i18n."""
    return get_i18n().t(key, **kwargs)


def reset_i18n() -> None:
    """Сбросить глобальный i18n (для тестов)."""
    global _global_i18n
    with _global_lock:
        _global_i18n = None


__all__ = [
    "I18n",
    "get_i18n",
    "set_language",
    "t",
    "reset_i18n",
]