"""Goal management and goal-progress rules extracted from ``agent.py``.

The ``DigitalBeing`` facade keeps public methods, decorators and class-level
caches. Functions here receive the facade instance or class explicitly and
never import it back.
"""

from datetime import datetime
import re
from typing import Dict, Optional

from config.simulation_config import LR_CONFIG
from src.core.buffered_logger import get_logger
from src.core.world_delta import WorldDelta


def _generate_initial_goals_impl(self):
    """Создаёт начальные цели для агента с прогрессом"""
    initial_goals = [
        {
            "id": 1,
            "title": "Выучить основы Python",
            "status": "active",
            "difficulty": 1,
        },
        {
            "id": 2,
            "title": "Собрать 10 фактов о мире",
            "status": "pending",
            "difficulty": 1,
        },
        {
            "id": 3,
            "title": "Улучшить понимание самого себя",
            "status": "pending",
            "difficulty": 2,
        },
    ]
    self.goals = initial_goals
    self.active_goal = initial_goals[0]

    # Инициализируем прогресс для каждой цели
    for goal in initial_goals:
        self._goal_progress[goal["id"]] = {
            "matched_concepts": set(),
            "percentage": 0,
            "last_update_cycle": 0,
        }

    get_logger().flush_immediate(
        f"Агент {self.name} инициализирован, целей: {len(self.goals)}"
    )


def set_goal_impl(
    self,
    title,
    difficulty=1,
    activate=False,
    *,
    command=None,
    plan=None,
    success_predicate="",
):
    """Устанавливает новую цель.

    Args:
        activate: если True — сделать цель активной сразу, а прежнюю
            активную вернуть в ``pending``. Нужно внутренней мотивации:
            срочная потребность не должна создавать «цель без id».
        command/plan/success_predicate: необязательный executable-payload
            для опционального моста в Delamain (этап 12).
    """
    goal_id = len(self.goals) + 1
    goal = {
        "id": goal_id,
        "title": title,
        "status": "pending",
        "difficulty": difficulty,
        "created_at": datetime.now().isoformat(),
    }
    execution = None
    if hasattr(self, "goal_subsystem"):
        execution = self.goal_subsystem._build_execution(
            command=command,
            plan=plan,
            success_predicate=success_predicate,
        )
    if execution is not None:
        goal["execution"] = execution
    self.goals.append(goal)
    self._goal_progress.setdefault(
        goal_id,
        {
            "matched_concepts": set(),
            "percentage": 0,
            "last_update_cycle": self.cycle_count,
        },
    )
    if activate:
        if self.active_goal is not None and self.active_goal is not goal:
            self.active_goal["status"] = "pending"
        goal["status"] = "active"
        self.active_goal = goal
    elif not self.active_goal:
        goal["status"] = "active"
        self.active_goal = goal
    if hasattr(self, "goal_subsystem"):
        # Списки общие, но активная цель — отдельное поле подсистемы.
        self.goal_subsystem.active_goal = self.active_goal
    get_logger().log(f"[{self.name}] Новая цель: {title} (сложность: {difficulty})")
    return goal_id


def complete_goal_impl(self, goal_id=None):
    """Завершает активную цель или цель по ID.

    Идемпотентен: повторный вызов для уже завершённой цели возвращает 0
    и не увеличивает счётчик. Источник правды по счётчику — GoalSubsystem.
    """
    target_goal = goal_id or (self.active_goal["id"] if self.active_goal else None)
    if target_goal is None:
        return 0

    goal = next((g for g in self.goals if g.get("id") == target_goal), None)
    if goal is None or goal.get("status") == "completed":
        return 0

    if hasattr(self, "goal_subsystem"):
        reward = self.goal_subsystem.complete_goal(target_goal)
        self.completed_goals = self.goal_subsystem.completed_goals
        self.active_goal = self.goal_subsystem.active_goal
    else:
        goal["status"] = "completed"
        goal["completed_at"] = datetime.now().isoformat()
        self.completed_goals += 1
        reward = (
            0 if goal.get("activity") is not None else goal.get("difficulty", 1) * 10
        )
        if goal == self.active_goal:
            self.active_goal = None
            self._set_next_goal()

    difficulty = int(goal.get("difficulty", 1) or 1)
    if goal.get("activity") is None:
        self.success_streak += difficulty
        self.energy = min(LR_CONFIG.ENERGY_MAX, self.energy + reward // 2)
    get_logger().flush_immediate(f"Цель завершена: {goal['title']}")
    return reward


def _set_next_goal_impl(self):
    """Устанавливает следующую цель из очереди"""
    if hasattr(self, "goal_subsystem"):
        self.goal_subsystem._set_next_goal()
        self.active_goal = self.goal_subsystem.active_goal
    else:
        from src.cognition.activity_goals import activate_next_pending_goal

        self.active_goal = activate_next_pending_goal(self.goals)

    if self.active_goal:
        get_logger().log(f"[{self.name}] Активная цель: {self.active_goal['title']}")
    else:
        get_logger().log(f"[{self.name}] Все цели завершены!")


def get_goals_status_impl(self):
    """Возвращает статус целей с прогрессом"""
    status = {
        "total": len(self.goals),
        "completed": self.completed_goals,
        "active": self.active_goal["title"]
        if self.active_goal
        else "Нет активных целей",
        "pending": sum(1 for g in self.goals if g["status"] == "pending"),
    }

    # Добавляем прогресс для активной цели
    if self.active_goal and LR_CONFIG.GOAL_PROGRESS_ENABLED:
        goal_id = self.active_goal["id"]
        progress_data = self._goal_progress.get(goal_id, {})
        status["progress"] = progress_data.get("percentage", 0)
        status["matched_concepts_count"] = len(
            progress_data.get("matched_concepts", set())
        )

    return status


def get_all_goals_with_progress_impl(self):
    """Возвращает все цели с прогрессом для отображения."""
    result = []
    for goal in self.goals:
        g = dict(goal)
        progress_data = self._goal_progress.get(goal["id"], {})
        g["progress"] = progress_data.get("percentage", 0)
        g["matched_concepts_count"] = len(progress_data.get("matched_concepts", set()))
        result.append(g)
    return result


# =====================================================================
# Вспомогательные методы для goal-progress правил (тесты интеграции)
# =====================================================================


def _get_src_file_index_impl(cls):
    """Возвращает set относительных путей всех .py файлов src/ (с кэшированием)."""
    if cls._SRC_FILE_INDEX is None:
        import os

        index = set()
        src_root = os.path.join(os.path.dirname(__file__), "..")
        for root, _dirs, files in os.walk(src_root):
            for f in files:
                if f.endswith(".py"):
                    rel = os.path.relpath(os.path.join(root, f), src_root)
                    # нормализуем разделители
                    rel = rel.replace("\\", "/")
                    index.add(rel)
        cls._SRC_FILE_INDEX = index
    return cls._SRC_FILE_INDEX


def _invalidate_src_file_index_impl(cls):
    """Сбрасывает кэш индекса файлов src/."""
    cls._SRC_FILE_INDEX = None


def _goal_subject_tokens_impl(cls, goal_title: str) -> set:
    """Ключевые слова темы цели (без служебных).

    «Понять: что такое время» → {"время"}
    «Собрать 10 фактов о мире» → {"фактов", "мир"}
    """
    text = str(goal_title or "").lower()
    # Берём часть после двоеточия, если она есть: «Понять: X» → «X».
    if ":" in text:
        text = text.split(":", 1)[1]
    tokens = re.findall(r"[a-zA-Zа-яё0-9]{3,}", text)
    return {token for token in tokens if token not in cls._GOAL_STOPWORDS}


def _topic_is_relevant_to_goal_impl(self, goal_title: str, topic: str) -> bool:
    """Относится ли изученная тема к теме цели.

    Нужно, чтобы цель «Понять, что такое время» не закрывалась после
    пяти случайных тем. Раньше общий фолбэк засчитывал любую новую
    тему, и цели завершались «на пустом месте».

    Ограничение действует только для целей с явным предметом —
    вида «Понять: X», «Исследовать: X», «Найти ответ на: X». Широкие
    цели («Построить модель мира через диалог», «Развивать
    способности») принимают любую тему: у них предмета нет, и
    ограничение сделало бы их недостижимыми.

    Непосредственное совпадение доступно и при классовом вызове.
    Связи графа проверяются только на экземпляре: класс не владеет
    ментальной моделью конкретной сущности.
    """
    text = str(goal_title or "")
    if ":" not in text:
        return True

    subject = self._goal_subject_tokens(text)
    if not subject:
        return True

    topic_tokens = {
        token
        for token in re.findall(r"[a-zA-Zа-яё0-9]{3,}", str(topic).lower())
        if token not in self._GOAL_STOPWORDS
    }
    if not topic_tokens:
        return False

    def shares_root(left, right):
        return any(
            first == second or first in second or second in first
            for first in left
            for second in right
        )

    # Совпадение по корню: «мир» ⊂ «мире», «факт» ⊂ «фактов».
    if shares_root(subject, topic_tokens):
        return True

    # Или тема связана с предметом цели в ментальной модели. Граф может
    # хранить направленное ребро, поэтому смотрим из обеих точек. Узлы —
    # ConceptNode, а не словари; неверный max_depth здесь раньше скрывался
    # общим except и навсегда отключал эту ветку.
    models = getattr(self, "mental_models", None)
    if models is None:
        return False
    subject_text = text.split(":", 1)[1].strip().lower()
    related_names = set()
    for anchor in (str(topic).strip().lower(), subject_text):
        if not anchor:
            continue
        try:
            related = models.find_related_concepts(anchor, max_distance=1)
        except (AttributeError, TypeError):
            continue
        for item in related or []:
            name = (
                item.get("concept", item.get("name", ""))
                if isinstance(item, dict)
                else getattr(item, "name", "")
            )
            if name:
                related_names.add(str(name).lower())
    related_tokens = {
        token
        for name in related_names
        for token in re.findall(r"[a-zA-Zа-яё0-9]{3,}", name)
        if token not in self._GOAL_STOPWORDS
    }
    return shares_root(subject, related_tokens) or shares_root(
        topic_tokens, related_tokens
    )


def _match_rule_to_goal_impl(goal_title: str, rule: dict) -> bool:
    """Проверяет, подходит ли правило к заголовку цели."""
    match_titles = rule.get("match_title", []) or []
    title_lower = goal_title.lower()
    return any(kw.lower() in title_lower for kw in match_titles)


def _topic_matches_rule_impl(topic: str, rule: dict) -> bool:
    """Проверяет, содержит ли тема хотя бы одно ключевое слово из правила.

    Короткие слова (1–2 символа, например «я») матчатся только как
    отдельные токены. Иначе «я» находится внутри «функция» и цель
    «понять себя» прогрессирует на любых технических вопросах.
    """
    match_keywords = rule.get("match_topic_keywords", []) or []
    topic_lower = topic.lower()
    for keyword in match_keywords:
        kw = str(keyword).lower().strip()
        if not kw:
            continue
        if len(kw) <= 2 and kw.isalpha():
            if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", topic_lower):
                return True
        elif kw in topic_lower:
            return True
    return False


def _check_goal_progress_impl(
    self,
    topic: str,
    answered: bool = False,
    evidence: Optional[WorldDelta] = None,
) -> Dict:
    """Проверяет прогресс активной цели согласно правилам из LR_CONFIG.

    Прогресс накапливается по уникальным темам: каждое новое совпадение
    увеличивает долю от ``matches_needed``. При 100% цель завершается
    ровно один раз, начисляется бонусная энергия.

    Args:
        topic: тема/вопрос, с которой столкнулся агент.
        answered: True, если по теме реально найден ответ (KB, файл,
            web, ментальная модель). Правила с ``requires_answer``
            (Python, факты) не растут от одних только попыток.
        evidence: наблюдаемые изменения мира, вызванные действием.
            Если передано и пусто — прогресс не начисляется: «я ничего
            не сделал» не может приблизить цель. Если не передано,
            работает прежняя логика (например, при чтении стимула).

    Returns:
        ``{"pct": int, "completed": bool, "reward": int}``.
    """
    result = {"pct": 0, "completed": False, "reward": 0}
    if not getattr(self, "active_goal", None):
        return result
    if self.active_goal.get("activity") is not None:
        return result
    if not getattr(LR_CONFIG, "GOAL_PROGRESS_ENABLED", True):
        return result

    # Доказательство: действие не изменило мир — засчитывать нечего.
    if evidence is not None and evidence.is_empty:
        progress_now = self._goal_progress.get(self.active_goal.get("id"), {})
        result["pct"] = int(progress_now.get("percentage", 0))
        return result

    goal_title = self.active_goal.get("title", "")
    goal_id = self.active_goal.get("id")

    # Гарантируем наличие записи прогресса
    progress = self._goal_progress.setdefault(
        goal_id,
        {
            "matched_concepts": set(),
            "percentage": 0,
            "last_update_cycle": 0,
        },
    )
    matched = progress.get("matched_concepts")
    if not isinstance(matched, set):
        # После восстановления из старого чекпоинта может лежать list.
        matched = set(matched or [])
        progress["matched_concepts"] = matched

    rules = getattr(LR_CONFIG, "GOAL_PROGRESS_RULES", []) or []
    applicable_rule = next(
        (rule for rule in rules if self._match_rule_to_goal(goal_title, rule)),
        None,
    )
    general_fallback = applicable_rule is None
    if applicable_rule is None:
        # У цели нет специализированного правила («Построить модель мира»,
        # «Развивать способности»). Без fallback такие цели не завершатся
        # никогда: прогресс просто некуда записывать. Считаем любые новые
        # темы — это честный «общий учебный» прогресс.
        rule = {
            "name": "general_learning",
            "matches_needed": max(
                1, int(getattr(LR_CONFIG, "PROGRESS_KNOWLEDGE_MATCHES", 5))
            ),
            "bonus_energy": 5,
        }
    elif self._topic_matches_rule(topic, applicable_rule):
        rule = applicable_rule
    else:
        # Цель конкретная (Python/факты/самопонимание), а тема не про неё.
        result["pct"] = int(progress.get("percentage", 0))
        return result

    # Общий фолбэк: цель без специализированного правила. Принимаем
    # только темы, относящиеся к её предмету, иначе цель «Понять, что
    # такое время» завершалась бы после пяти случайных тем.
    if general_fallback and not _topic_is_relevant_to_goal_impl(
        self, goal_title, topic
    ):
        result["pct"] = int(progress.get("percentage", 0))
        return result

    if rule.get("requires_answer") and not answered:
        # Встретил вопрос — ещё не выучил и не собрал факт.
        result["pct"] = int(progress.get("percentage", 0))
        return result

    matched.add(topic)
    matches_needed = max(1, int(rule.get("matches_needed", 3)))
    percentage = min(100, int(len(matched) / matches_needed * 100))
    min_increment = max(0, int(getattr(LR_CONFIG, "MIN_PROGRESS_INCREMENT", 0)))
    completed = percentage >= 100
    if (
        not completed
        and percentage - int(progress.get("percentage", 0)) < min_increment
    ):
        # Тема уже учтена или прирост слишком мал — не дёргаем метрики.
        result["pct"] = int(progress.get("percentage", 0))
        return result

    progress["percentage"] = max(int(progress.get("percentage", 0)), percentage)
    progress["rule_name"] = rule.get("name", "unnamed")
    progress["last_update_cycle"] = getattr(self, "cycle_count", 0)
    result["pct"] = progress["percentage"]

    if completed:
        bonus = max(0, int(rule.get("bonus_energy", 0) or 0))
        if bonus:
            self.energy = min(LR_CONFIG.ENERGY_MAX, self.energy + bonus)
        result["reward"] = self.complete_goal()
        result["completed"] = True
        get_logger().flush_immediate(
            f"🎯 Цель достигнута: {goal_title} "
            f"(+{bonus} энергии, награда {result['reward']})"
        )
    return result
