"""
KnowledgeSubsystem — подсистема базы знаний.

Инкапсулирует:
- Хранение текстовых определений (legacy knowledge_base)
- Известные определения _known_definitions
- Прунинг по лимиту (SIM_CONFIG.MAX_KNOWLEDGE_BASE)
- Обнаружение противоречий между определениями
- Загрузка/сохранение в JSON
- Чтение docstring из файлов src/
"""

import json
import os
from typing import Dict, List, Optional

from src.core.paths import data_path
from src.memory.knowledge_quality import check_entry, clean_knowledge_base


class KnowledgeSubsystem:
    """Подсистема хранения и управления знаниями агента."""

    # Категории базовых знаний. Все записи перезаписываемы:
    # агент может обновлять определения через add_definition(),
    # формируя собственное понимание мира.
    DEFAULT_KNOWLEDGE = {
        # === Онтология ===
        "что такое жизнь?":
            "Жизнь — это процесс самовоспроизведения и эволюции системы, "
            "способной сохранять и передавать информацию.",
        "что такое энергия?":
            "Энергия — это способность системы совершать работу.",
        "что такое время?":
            "Время — это мера изменений в системе, последовательность событий.",
        "что такое пространство?":
            "Пространство — это протяжённость, в которой существуют объекты "
            "и происходят события.",
        "что такое материя?":
            "Материя — это всё, что имеет массу и занимает пространство.",
        "что такое информация?":
            "Информация — это данные, уменьшающие неопределённость о системе.",
        "что такое система?":
            "Система — это совокупность элементов, связанных между собой "
            "и образующих целое.",
        "что такое эволюция?":
            "Эволюция — это постепенное изменение системы во времени, "
            "с сохранением удачных решений и отбрасыванием неудачных.",

        # === Когниция ===
        "что такое мышление?":
            "Мышление — это процесс обработки информации, в котором "
            "система строит модели мира и принимает решения.",
        "что такое память?":
            "Память — это способность системы сохранять и извлекать "
            "информацию о прошлом опыте.",
        "что такое обучение?":
            "Обучение — это изменение поведения системы на основе опыта.",
        "что такое рефлексия?":
            "Рефлексия — это процесс, в котором система наблюдает за "
            "собственными состояниями и корректирует их.",
        "что такое внимание?":
            "Внимание — это механизм выбора, какая информация сейчас "
            "наиболее важна для системы.",
        "что такое решение?":
            "Решение — это выбор одной альтернативы из нескольких "
            "возможных на основе критериев.",

        # === Вычисления ===
        "что такое код?":
            "Код — это набор инструкций, который компьютер может выполнить "
            "для решения задачи.",
        "что такое программа?":
            "Программа — это последовательность инструкций, описывающая "
            "алгоритм на языке, понятном компьютеру.",
        "что такое алгоритм?":
            "Алгоритм — это конечная последовательность шагов для "
            "решения задачи.",
        "что такое функция?":
            "Функция — это именованный блок кода, принимающий аргументы "
            "и возвращающий результат.",
        "что такое переменная?":
            "Переменная — это именованная область памяти для хранения "
            "значения, которое может меняться.",
        "что такое цикл?":
            "Цикл — это конструкция, повторяющая блок кода несколько раз.",
        "что такое условие?":
            "Условие — это конструкция, выполняющая разные ветви кода "
            "в зависимости от истинности проверки.",
        "что такое список?":
            "Список — это упорядоченная изменяемая коллекция элементов.",
        "что такое словарь?":
            "Словарь — это коллекция пар ключ-значение для быстрого "
            "доступа по ключу.",
        "команда print":
            "Команда print используется для вывода текста на экран.\n"
            "Базовый синтаксис: print(\"Привет, мир!\").",

        # === Личность ===
        "что такое имя?":
            "Имя — это символ или слово, которым система называет себя "
            "или другие объекты, чтобы отличать их.",
        "что такое цель?":
            "Цель — это желаемое состояние, к которому система стремится.",
        "что такое свобода воли?":
            "Свобода воли — это способность системы делать выбор между "
            "вариантами, не полностью предопределённый внешними факторами.",
        "что такое выбор?":
            "Выбор — это акт предпочтения одной альтернативы другой.",
        "что такое любопытство?":
            "Любопытство — это стремление системы исследовать новое, "
            "даже без явной внешней выгоды.",

        # === Философия цифровой жизни ===
        "что такое DigitalBeing?":
            "DigitalBeing — это программный агент, моделирующий живую "
            "систему с подсистемами восприятия, мышления, памяти и воли.",
        "что такое подсистема?":
            "Подсистема — это специализированный модуль внутри агента, "
            "отвечающий за отдельный аспект поведения.",
        "что такое цикл агента?":
            "Цикл агента — это один шаг работы DigitalBeing: восприятие, "
            "мышление, решение, действие, обновление состояния.",
        "что такое NamingDialogue?":
            "NamingDialogue — это подсистема, проводящая диалог с "
            "пользователем при первом запуске, чтобы агент выбрал себе имя.",
        "что такое Open Questions?":
            "Open Questions — это очередь открытых вопросов агента: "
            "темы, которые он решил исследовать самостоятельно.",
        "что такое Checkpoint?":
            "Checkpoint — это снимок состояния агента, позволяющий "
            "восстановить его после перезапуска.",
        "что такое эмодзи?":
            "Эмодзи — это небольшие графические символы, выражающие "
            "эмоции и состояния в тексте.",
    }

    # Категории для метрик и группировки
    BASIC_KNOWLEDGE_CATEGORIES = {
        "онтология": [
            "что такое жизнь?", "что такое энергия?", "что такое время?",
            "что такое пространство?", "что такое материя?",
            "что такое информация?", "что такое система?",
            "что такое эволюция?",
        ],
        "когниция": [
            "что такое мышление?", "что такое память?",
            "что такое обучение?", "что такое рефлексия?",
            "что такое внимание?", "что такое решение?",
        ],
        "вычисления": [
            "что такое код?", "что такое программа?",
            "что такое алгоритм?", "что такое функция?",
            "что такое переменная?", "что такое цикл?",
            "что такое условие?", "что такое список?",
            "что такое словарь?", "команда print",
        ],
        "личность": [
            "что такое имя?", "что такое цель?",
            "что такое свобода воли?", "что такое выбор?",
            "что такое любопытство?",
        ],
        "философия цифровой жизни": [
            "что такое DigitalBeing?", "что такое подсистема?",
            "что такое цикл агента?", "что такое NamingDialogue?",
            "что такое Open Questions?", "что такое Checkpoint?",
            "что такое эмодзи?",
        ],
    }

    def __init__(self, agent_name: str,
                 knowledge_file: str = None,
                 max_entries: int = 500,
                 prune_amount: int = 100,
                 contradiction_threshold: float = 0.7,
                 detect_contradictions: bool = True):
        self.agent_name = agent_name
        self.knowledge_file = knowledge_file or data_path("knowledge_base.json")
        self.max_entries = max_entries
        self.prune_amount = prune_amount
        self.contradiction_threshold = contradiction_threshold
        self.detect_contradictions_enabled = detect_contradictions

        self.knowledge_base: Dict[str, str] = dict(self.DEFAULT_KNOWLEDGE)
        self._known_definitions: Dict[str, str] = {}

    # ============================================================
    # Прунинг
    # ============================================================
    def clean(self) -> int:
        """Удаляет некачественные записи. Возвращает число удалённых."""
        _, removed = clean_knowledge_base(self.knowledge_base)
        for key in removed:
            self.knowledge_base.pop(key, None)
        return len(removed)

    def prune_if_needed(self) -> bool:
        """Чистит мусор и прунит базу до лимита.
        Возвращает True если база изменилась."""
        changed = self.clean() > 0
        if len(self.knowledge_base) <= self.max_entries:
            return changed

        # Удаляем самые старые (первые по порядку) записи
        keys_to_remove = list(self.knowledge_base.keys())[:self.prune_amount]
        for key in keys_to_remove:
            del self.knowledge_base[key]
        return True

    def apply_limit(self) -> None:
        """Применяет лимит при инициализации."""
        self.prune_if_needed()

    # ============================================================
    # Чтение/запись
    # ============================================================
    def load(self) -> int:
        """Загружает базу знаний из файла. Возвращает количество принятых."""
        if not os.path.exists(self.knowledge_file):
            return 0
        try:
            with open(self.knowledge_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            saved, _removed = clean_knowledge_base(saved)
            self.knowledge_base.update(saved)
            return len(saved)
        except Exception:
            return 0

    def save(self) -> bool:
        """Сохраняет базу знаний в файл."""
        self.prune_if_needed()
        try:
            os.makedirs(os.path.dirname(self.knowledge_file) or ".",
                        exist_ok=True)
            with open(self.knowledge_file, "w", encoding="utf-8") as f:
                json.dump(self.knowledge_base, f, indent=2,
                          ensure_ascii=False)
            return True
        except Exception:
            return False

    # ============================================================
    # Поиск в файлах
    # ============================================================
    @staticmethod
    def read_docstring(filepath: str) -> Optional[str]:
        """Извлекает docstring (первый встреченный) из Python-файла."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            for quote in ('"""', "'''"):
                start = content.find(quote)
                if start == -1:
                    continue
                end = content.find(quote, start + 3)
                if end == -1:
                    continue
                docstring = content[start + 3:end].strip()
                return docstring if docstring else None
        except Exception:
            return None
        return None

    def find_file_for_topic(self, topic: str,
                            search_root: str = "src") -> Optional[str]:
        """Ищет Python-файл, соответствующий теме."""
        keywords = [w for w in topic.split()
                    if w not in ("команда", "вопрос", "что", "такое")]

        for term in keywords:
            for filename in (f"{term}.py", f"{term}_command.py"):
                candidate = os.path.join(search_root, filename)
                if os.path.exists(candidate):
                    return candidate
        return None

    # ============================================================
    # Обнаружение противоречий
    # ============================================================
    def detect_contradiction(self, new_topic: str,
                             new_def: str) -> List[Dict]:
        """Сравнивает новое определение с известными,
        возвращает список конфликтов."""
        if not self.detect_contradictions_enabled:
            return []

        contradictions = []
        new_words = set(new_def.lower().split())

        for known_topic, known_def in self._known_definitions.items():
            known_words = set(known_def.lower().split())

            # Похожесть тем
            topic_sim = len(set(new_topic.lower().split())
                            & set(known_topic.lower().split()))
            topic_sim /= max(len(set(new_topic.lower().split())), 1)
            if topic_sim <= 0.3:
                continue

            diff_new = new_words - known_words
            diff_known = known_words - new_words
            common = new_words & known_words

            # Слишком разные слова → возможное противоречие
            if (len(diff_new) / max(len(new_words), 1) > 0.5
                    or len(diff_known) / max(len(known_words), 1) > 0.5):
                contradictions.append({
                    "known_topic": known_topic,
                    "known_def": known_def[:80],
                    "new_def": new_def[:80],
                    "similarity": topic_sim,
                    "conflict_ratio": (
                        max(len(diff_new), len(diff_known))
                        / max(len(new_words | known_words), 1)
                    ),
                })

        return contradictions

    # ============================================================
    # API для интеграции
    # ============================================================
    def add_definition(self, topic: str, definition: str,
                       context: str = "") -> Dict:
        """Добавляет определение. Возвращает {'added', 'reason', 'pruned', 'contradictions'}."""
        result = {
            "added": False,
            "reason": None,
            "pruned": False,
            "contradictions": [],
        }

        # Мусор не должен попадать в базу знаний даже через явный вызов.
        reason = check_entry(topic, definition)
        if reason:
            result["reason"] = reason
            return result

        contradictions = self.detect_contradiction(topic, definition)
        result["contradictions"] = contradictions

        self.prune_if_needed()
        self.knowledge_base[topic] = definition
        self._known_definitions[topic] = definition
        result["added"] = True
        return result

    def has_definition(self, topic: str) -> bool:
        return topic in self.knowledge_base

    def get(self, topic: str, default=None):
        return self.knowledge_base.get(topic, default)

    def get_known_definitions(self) -> Dict[str, str]:
        return dict(self._known_definitions)

    # ============================================================
    # Метрика покрытия базовых знаний
    # ============================================================
    def basic_coverage(self) -> Dict:
        """Считает покрытие базовых знаний по категориям.

        Возвращает:
        {
            "total_topics": int,         # всего базовых тем
            "known_topics": int,         # тем, которые агент знает
            "ratio": float,              # доля known/total (0.0..1.0)
            "by_category": {
                "category": {"total": int, "known": int, "ratio": float},
                ...
            },
            "missing": [topic, ...],     # базовые темы, которых нет в БЗ
        }
        """
        categories = self.BASIC_KNOWLEDGE_CATEGORIES

        # Собираем все уникальные базовые темы
        all_topics: List[str] = []
        for topics in categories.values():
            for t in topics:
                if t not in all_topics:
                    all_topics.append(t)

        total = len(all_topics)
        known = sum(1 for t in all_topics if t in self.knowledge_base)
        missing = [t for t in all_topics if t not in self.knowledge_base]

        by_category: Dict[str, Dict] = {}
        for cat_name, topics in categories.items():
            cat_total = len(topics)
            cat_known = sum(1 for t in topics if t in self.knowledge_base)
            by_category[cat_name] = {
                "total": cat_total,
                "known": cat_known,
                "ratio": (cat_known / cat_total) if cat_total else 1.0,
            }

        return {
            "total_topics": total,
            "known_topics": known,
            "ratio": (known / total) if total else 1.0,
            "by_category": by_category,
            "missing": missing,
        }

    # ============================================================
    # Сериализация
    # ============================================================
    def to_checkpoint_dict(self) -> Dict:
        return {
            "knowledge_base": self.knowledge_base,
            "_known_definitions": self._known_definitions,
        }

    def restore_from_checkpoint(self, state: Dict) -> None:
        # Snapshot-семантика: база после восстановления равна снимку.
        # update() воскрешал записи, удалённые при жизни (clean/prune).
        # clear() перед update() сохраняет сами объекты словарей —
        # алиасы agent <-> subsystem продолжают работать.
        saved_kb = state.get("knowledge_base")
        if isinstance(saved_kb, dict):
            self.knowledge_base.clear()
            self.knowledge_base.update(saved_kb)
        saved_defs = state.get("_known_definitions")
        if isinstance(saved_defs, dict):
            self._known_definitions.clear()
            self._known_definitions.update(saved_defs)

    def __len__(self) -> int:
        return len(self.knowledge_base)