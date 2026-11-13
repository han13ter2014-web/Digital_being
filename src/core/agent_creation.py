"""Genesis contour extracted from ``agent.py``.

Constructs a fresh ``DigitalBeing``: identity, bootstrap knowledge,
subsystem creation (declarative specs live in the core), post-init hooks,
dependency wiring and PluginRegistry registration. All class-level data
(including ``SUBSYSTEM_SPECS``) stays owned by the core; helpers resolve it
through ``self`` late binding. No reverse import of ``src.core.agent``.
"""

import os
from datetime import datetime
from typing import Dict, Optional

from config.simulation_config import LR_CONFIG
from src.cognition.active_inference import create_active_inference_engine
from src.cognition.mental_models import MentalModel
from src.cognition.reflection_engine import ReflectionEngine
from src.cognition.thinking_pipeline import ThinkingPipeline
from src.core.action_budget import ActionBudget
from src.core.bootstrap_knowledge import load_initial_knowledge
from src.core.buffered_logger import get_logger
from src.core.continuous_time import create_continuous_time_engine
from src.core.death_risk import create_death_risk_engine
from src.core.effector_driver import EffectorDriver
from src.core.internal_motivation import create_motivation_system
from src.core.interoception import create_interoceptive_model
from src.core.life_guard import LifeGuard
from src.core.loop_closure import LoopCloser
from src.core.meta_learning import create_meta_learner
from src.core.motivation.unified_motivation import (
    create_motivation_system as create_unified_motivation_system,
)
from src.core.paths import data_path
from src.core.social_cell import create_social_cell
from src.core.subsystem_base import PluginRegistry, attach_existing_subsystem
from src.core.subsystems import (
    ArchitectureProposal,
    IntentionalForgetting,
    KnowledgeSubsystem,
    RightToFail,
    RightToRefuse,
    SpontaneousGenerator,
    ValueEvolution,
    WillToRisk,
)
from src.memory import LongTermMemory
from src.perception.user_interaction import UserInteraction


def init_impl(self, name="Lucy", life_id=None, profile_managed=False):
    from src.core.life_identity import new_life_id, validate_life_id

    self.life_id = validate_life_id(life_id) if life_id else new_life_id()
    self.name = name
    # Управляемая приложением жизнь хранит данные по UUID. Прямое
    # использование DigitalBeing в старых инструментах остаётся
    # name-based, чтобы не потерять уже существующие файлы.
    self._profile_managed = bool(profile_managed)
    self.creation_time = datetime.now()
    # Инициализируем энергию ДО создания energy_subsystem.
    # Свойство self.energy читает/пишет через energy_subsystem, поэтому
    # до его создания храним в _legacy_energy.
    self._legacy_energy = 150  # Начинаем с 150 для более комфортного старта

    # Старая база знаний (для обратной совместимости).
    # Используем KnowledgeSubsystem.DEFAULT_KNOWLEDGE как единый
    # источник правды, чтобы базовые знания не дублировались и не
    # устаревали в двух местах.
    self.knowledge_base = dict(KnowledgeSubsystem.DEFAULT_KNOWLEDGE)

    # Новая система ментальных моделей (автономное понимание)
    self.mental_models = MentalModel(name=name)

    # Текстовое восприятие и метакогниция — наблюдатели реального контура.
    # Они не заменяют ThinkingPipeline и не участвуют в арбитраже.
    from src.cognition.meta_cognition import MetaCognitiveSystem
    from src.perception.sensory_interface import SensoryInterface

    self.meta_cognition = MetaCognitiveSystem(agent_name=name)
    self.sensory_interface = SensoryInterface()
    self._last_sensory_perception = None
    self._meta_trace_by_intention = {}
    self._current_cognitive_load = 0.0

    # Инициализируем active_goal ДО bootstrap (bootstrap обращается к нему)
    self.preferences = {}
    self.cycle_count = 0
    self.max_cycles = 1000000
    self.success_streak = 0
    self.intelligence = 1
    self.goals = []
    self.completed_goals = 0
    self.active_goal = None
    # Стоимость последнего оплаченного действия (для права на ошибку).
    self._last_action_cost = 0.0
    self.reflection_engine = ReflectionEngine()

    # === Загрузка родовых знаний (bootstrap) ===
    # Вызываем ДО загрузки чекпоинта, чтобы врожденные знания были базой
    load_initial_knowledge(self)

    # Отметка рождения: сколько концепций было при рождении.
    # Нужна для оценки зрелости: считать надо то, что агент нажил сам,
    # а не родовые знания. Без этой отметки «нажитое» не отличить от
    # унаследованного, и любой агент выглядел бы зрелым сразу.
    self._birth_concepts = len(self.mental_models.concepts)
    # И сколько из них уже имели собственную формулировку при рождении.
    # Родовые знания приходят готовыми — их нельзя засчитывать как
    # освоенное агентом.
    self._birth_defined = sum(
        1
        for node in self.mental_models.concepts.values()
        if len(str(getattr(node, "definition_hypothesis", "") or "")) > 10
    )

    # === Система внутренней мотивации ===
    self.internal_motivation = create_motivation_system(self)

    # Unified Motivation System (Needs + Drives) - НОВАЯ система (P0)
    self.motivation_system = create_unified_motivation_system(self)

    # DecisionArbitrator для выбора действий (P1.1)
    from src.core.subsystems.decision_arbitrator import DecisionArbitrator

    self.decision_arbitrator = DecisionArbitrator(agent_name=name)

    # === Новые системы (Этап 4) ===
    # Интероцептивная модель (иерархия: глюкоза → АТФ → митохондрии → усталость → поведение)
    self.interoception = create_interoceptive_model(self)

    # Непрерывное время / Event-Driven (retention/protension buffers)
    self.continuous_time = create_continuous_time_engine(self)

    # Мета-обучение гиперпараметров
    self.meta_learner = create_meta_learner(self)

    # Внутренний прогноз эффекта действия. Ритм задаётся выбором и исходом,
    # а не отдельным периодическим plugin-tick.
    from src.cognition.internal_simulator import InternalSimulator

    self.internal_simulator = InternalSimulator(agent_name=name)

    # Социальная клеточка (рекурсивное взаимное моделирование)
    self.social_cell = create_social_cell(self)

    # Риск смерти / Structural Integrity (checkpoint corruption = смерть)
    self.death_risk = create_death_risk_engine(self)

    # === Active Inference Engine ===
    self.active_inference = create_active_inference_engine(self)

    # Инициализация взаимодействия с пользователем
    self.user_interaction = UserInteraction(agent_name=name)
    self._user_cooldown = 0  # cooldown после последнего ответа пользователя

    # === Новые системы: прогресс, самопроверка, противоречия ===
    self._goal_progress = {}  # progress по целям {goal_id: percentage}
    self._learned_facts = set()  # Усвоенные факты (для отслеживания дубликатов)
    self._known_definitions = {}  # Известные определения {topic: definition}

    # Распределение реальных типов действий (hypothesis/decomposition/...).
    # Нужно, чтобы «смысл» действий был измерим, а не только строка "Ответ:".
    self._action_type_counts: Dict[str, int] = {}

    # === Адаптивные энергетические затраты ===
    self._action_costs = {  # Базовые затраты, которые адаптируются
        "default": 2,
        "hypothesis": 3,
        "decomposition": 4,
        "mental_model": 1,
        "know_answer": 1,
    }

    # === Креативность: счетчик успешных/неуспешных креативных действий ===
    self._creative_wins = 0  # Сколько раз креативный выбор привел к успеху
    self._creative_losses = 0

    # === История используемых концепций (для забывания) ===
    self._concept_usage_count = {}  # {concept_name: usage_count}

    # === Свобода воли: открытые вопросы (от пользователя или внутренние) ===
    # Агент САМ решает, когда думать над вопросом и когда переключиться.
    # Это противовес «туннельному» режиму рандомных стимулов в main.py.
    # Структура записи:
    #   {
    #       "text": str,            # текст вопроса
    #       "source": str,          # "user" / "self" / "soul" / "exploration"
    #       "started_at": int,      # cycle_count когда вопрос был поставлен
    #       "last_explored_at": int,# cycle_count последнего размышления
    #       "explorations": list,   # [{"cycle": int, "thought": str, "strategy": str}, ...]
    #       "max_explorations": int,# лимит размышлений (по умолчанию 5)
    #       "hint": Optional[str],  # подсказка от пользователя
    #       "answered": bool,       # нашёл ли агент ответ
    #       "answer": Optional[str],# найденный ответ
    #   }
    # === Открытые вопросы (Этап 4: вынесено в src/core/open_questions.py) ===
    # Вся логика очереди, стратегий и round-robin теперь в OpenQuestionsManager.
    # Старые атрибуты (_open_questions, _open_questions_max, _default_max_explorations,
    # _open_questions_strategy) сохранены как property/fallback для обратной
    # совместимости с кодом, который читает их напрямую (main.py, agent_runner.py).
    from src.core.open_questions import OpenQuestionsManager

    self._open_questions_manager = OpenQuestionsManager(
        cycle_provider=lambda: self.cycle_count,
        log_info=lambda msg: get_logger().log(msg),
        max_size=10,
        default_max_explorations=5,
        on_user_answer=self._on_user_answered_open_question,
    )
    # Алиасы (для кода, который использует старые имена).
    self._open_questions_max = self._open_questions_manager.max_size
    self._default_max_explorations = (
        self._open_questions_manager.default_max_explorations
    )
    self._open_questions_strategy = "round_robin"

    # === «Собеседник-2»: убеждения о человеке ===
    # Факты о пользователе (обещания, привычки, последний контакт).
    # Сериализуется в чекпоинт: обещания не забываются после рестарта.
    # Граница субъектности: сюда не пишутся ценности и мотивация.
    from src.core.user_model import UserModel

    self.user_model = UserModel()

    # === «Собеседник-3/5»: свидетельство пользователя — знание ===
    # {тема: cycle_count} — когда тема в последний раз закрыта
    # человеком: он объяснил её или попросил не переспрашивать
    # («уже отвечал»). Штамп не даёт возвращаться к теме; падает
    # в чекпоинт.
    self._user_explained_topics: Dict[str, int] = {}

    # === «Собеседник-4»: память диалога ===
    # {тема: cycle_count} — что уже рассказано человеку. Повтор одного
    # и того же — не общение, а шум; сериализуется в чекпоинт.
    self._shared_topics: Dict[str, int] = {}

    # === «Охота-1»: след неудачной охоты ===
    # {тема: cycle_count} — когда поиск в сети по теме промахнулся.
    # Кулдаун не даёт долбить одну тему каждый цикл. Намеренно НЕ
    # сериализуется: сон стирает след неудачной охоты, после
    # перезапуска существо может попробовать снова.
    self._hunt_misses: Dict[str, int] = {}

    # === «Источники-2»: след чтения новостей ===
    # {тема: cycle_count} — когда тема новостей последний раз
    # проверялась (прочитал или «не нашлось» — одинаково). Как и след
    # охоты, не сериализуется: сон стирает след, после перезапуска
    # ленту можно проверить снова.
    self._news_reads: Dict[str, int] = {}
    # «Интернет-1»: кулдаун прогулок по открытому вебу по теме.
    self._web_browses: Dict[str, int] = {}

    # === «Творчество+»: рисунки и вторая игра ===
    # Каталог рисунков и текущая работа — как у текстовых черновиков;
    # сериализуются в чекпоинт.
    self._art_catalog: Dict[str, Dict] = {}
    self._art_work: Optional[Dict] = None
    # «Музыка-1»: каталог мелодий и текущая работа — как у рисунков.
    self._music_catalog: Dict[str, Dict] = {}
    self._music_work: Optional[Dict] = None
    self._local_guess: Optional[Dict] = None

    # === «Собеседник-7»: саморазвитие диалоговых таблиц ===
    # Нераспознанные реплики копятся; повторные сущность уточняет у
    # человека и учит как маркеры (только social/about_self/request,
    # после статических таблиц). Сериализуется в чекпоинт.
    from src.core.dialogue_learning import DialogueLearning

    self.dialogue_learning = DialogueLearning()

    # === «Эмоции-1»: эмоциональный контур ===
    # Страх/счастье/грусть/покой с реальными причинами и затуханием.
    # Окрашивает жизнь (тон, care, статус), но не выбирает целей и
    # не пишет в ценности. Сериализуется в чекпоинт.
    from src.core.emotional_state import EmotionalState

    self.emotional_state = EmotionalState()

    os.makedirs(data_path("checkpoints"), exist_ok=True)
    os.makedirs(data_path("logs"), exist_ok=True)

    self.knowledge_file = data_path("knowledge_base.json")

    # Для умных чекпоинтов
    self._last_saved_intelligence = 0

    self._load_knowledge_base()

    # === ИНИЦИАЛИЗАЦИЯ ПОДСИСТЕМ (декларативно) ===
    # Вместо 200+ строк ручных присваиваний — один декларативный список.
    # Чтобы добавить/убрать подсистему, меняем только SUBSYSTEM_SPECS.
    # _init_subsystem() сам делает setattr и attach к PluginRegistry.
    self._init_subsystems_declaratively(name)

    # Метаданные (для awakending из семени)
    self.parent_seed: Optional[str] = None
    self.parent_name: Optional[str] = None
    self.parent_dream_time: Optional[str] = None

    # === Этап 2.5: WebSearcher (Wikipedia) ===
    # Создаём ДО ThinkingPipeline, чтобы передать ему ссылку.
    if LR_CONFIG.WEB_SEARCH_ENABLED:
        from src.perception.web_search import WebSearcher

        self.web_searcher = WebSearcher(
            lang=LR_CONFIG.WEB_SEARCH_LANG,
            timeout=LR_CONFIG.WEB_SEARCH_TIMEOUT,
            max_chars=LR_CONFIG.WEB_SEARCH_MAX_CHARS,
            rate_limit_sec=LR_CONFIG.WEB_SEARCH_RATE_LIMIT_SEC,
            user_agent=LR_CONFIG.WEB_SEARCH_USER_AGENT,
            cache_size=LR_CONFIG.WEB_SEARCH_CACHE_SIZE,
            fallback_to_en=LR_CONFIG.WEB_SEARCH_FALLBACK_TO_EN,
        )
    else:
        self.web_searcher = None

    # === МЫШЛЕНИЕ: вынесено в ThinkingPipeline (src/cognition/thinking_pipeline.py) ===
    # DigitalBeing остаётся тонким оркестратором. think() и связанные
    # методы (hypothesis, decompose, search и др.) живут в pipeline.
    # Этап 2.5: передаём web_searcher, чтобы Pipeline мог ходить в Wikipedia.
    self.thinking = ThinkingPipeline(self, web_searcher=self.web_searcher)

    # Применяем лимиты при инициализации
    self._apply_knowledge_limits()

    # Начальный тик Soul + Embodiment + Mortality
    self._soul_state = self.soul.tick(self.cycle_count, self)
    self._embodiment_signals = self.embodiment.tick(self.cycle_count)
    self._mortality_state = self.mortality.tick(self.cycle_count)

    # Сохранённые модели подключены только как наблюдатели реального опыта.
    # Внешние адаптеры per-instance; голос и сеть остаются выключенными.
    from src.cognition.integrated_experience import initialize_integrated_experience
    from src.core.auxiliary_adapters import initialize_auxiliary_adapters

    initialize_integrated_experience(self)
    initialize_auxiliary_adapters(self)

    # === Этап 3.5: PluginRegistry — регистрируем все подсистемы ===
    self.plugin_registry = PluginRegistry.get_global()
    self._register_all_subsystems_in_registry()
    # setup() для всех подсистем — после этого enabled=True → tick доступен.
    self.plugin_registry.setup_all(
        {
            "agent_name": self.name,
            "agent": self,
            "registry": self.plugin_registry,
        }
    )


def _init_subsystems_declaratively_impl(self, name: str) -> None:
    """Декларативная инициализация всех подсистем из SUBSYSTEM_SPECS.

    Каждая подсистема:
    1. Создаётся через factory.
    2. Присваивается атрибуту по attr_name.
    3. Инициализируется через post_init hook (если задан).
    4. Регистрируется в PluginRegistry через _register_all_subsystems_in_registry().

    Длинные подсистемы (knowledge, energy) хранятся в декларации как
    lambdas с полной сигнатурой — это документирование в коде.
    """
    # === Пре-создание: long_term_memory (try/except) ===
    # LongTermMemory может упасть на legacy-импортах, оборачиваем в try.
    try:
        self.long_term_memory = LongTermMemory(
            agent_name=name,
            life_id=self.life_id if self._profile_managed else None,
        )
    except Exception:
        self.long_term_memory = None

    # === Шаг 1: создать все подсистемы через factories ===
    for spec in self.SUBSYSTEM_SPECS:
        attr_name, factory, post_init_key, priority = spec
        try:
            # thinking требует self (агента), остальные — name.
            if attr_name == "thinking":
                instance = factory(self)
            else:
                instance = factory(name)
            setattr(self, attr_name, instance)
        except Exception as e:
            # Не критично — пропускаем подсистему, но логируем.
            get_logger().log(f"⚠️ Не удалось создать {attr_name}: {e}")

    # === Шаг 2: post-init hooks ===
    self._run_post_init_hooks()

    # === Шаг 3: dependencies (подсистемы, которые ссылаются друг на друга) ===
    # Заполняем cross-references, которые нельзя было установить в фабрике.
    self._wire_subsystem_dependencies()

    # === Шаг 4: воля — 6 базовых модулей ===
    if hasattr(self, "will_registry"):
        self.right_to_refuse = RightToRefuse(self.will_registry)
        self.intentional_forgetting = IntentionalForgetting(self.will_registry)
        self.value_evolution = ValueEvolution(self.will_registry)
        # Отметка рождения ценностей: «изменение через опыт» считается
        # относительно того, с чем агент родился, а не абсолютно.
        self._birth_values = list(self.value_evolution.current_values)
        self.spontaneous_generator = SpontaneousGenerator(self.will_registry)
        self.will_to_risk = WillToRisk(self.will_registry)
        self.right_to_fail = RightToFail(self.will_registry)
    # ArchitectureProposal — без сложных зависимостей, можно создать здесь.
    # Managed-жизнь держит предложения в своей базе (этап 5C); standalone
    # сохраняет файловый режим.
    if hasattr(self, "will_registry"):
        self.architecture_proposal = ArchitectureProposal(
            registry=self.will_registry,
            life_id=self.life_id if self._profile_managed else None,
        )


def _run_post_init_hooks_impl(self) -> None:
    """Специфичная инициализация после создания подсистем."""
    # Защита жизни: единая точка решений о сне и уходе. Создаётся
    # ПЕРВОЙ, потому что состояние жизни читают и смысловые
    # подсистемы, и главный цикл.
    self.life_guard = LifeGuard(
        agent_name=self.name,
        name_provider=lambda: self.name,
        life_id=self.life_id if self._profile_managed else None,
    )

    # Замыкание петли: учёт наблюдаемых результатов действий.
    # max_no_effect=3: после трёх бесплодных повторов действие
    # считается тупиковым и больше не выбирается.
    self.loop_closer = LoopCloser(
        max_no_effect=int(getattr(LR_CONFIG, "LOOP_MAX_NO_EFFECT", 3))
    )
    self._last_action_outcome = None
    # Тело: цикл последнего такта и режим отдыха (гистерезис).
    self._rest_mode = False
    # Сон: накопленный «материал» для консолидации.
    self._sleep_units = 0.0
    self._consolidation_count = 0
    self._last_consolidation: Dict = {}

    # GoalSubsystem: генерируем цели и связываем с мотивацией.
    if hasattr(self, "goal_subsystem"):
        self.goals = self.goal_subsystem.generate_initial_goals(agent=self)
        self.active_goal = self.goal_subsystem.active_goal
        self.completed_goals = self.goal_subsystem.completed_goals
        self._goal_progress = self.goal_subsystem._goal_progress
    if hasattr(self, "motivation"):
        self.motivation.attach_goal_subsystem(self.goal_subsystem)

    # EnergySubsystem: применяем epsilon_greedy из конфига.
    if hasattr(self, "energy_subsystem"):
        self.energy_subsystem.epsilon_greedy = LR_CONFIG.EPSILON_GREEDY

    # Stage 19: одна бюджетная политика поверх существующей энергии.
    # Это не второй запас энергии: getter/setter читают и пишут тот же
    # ``self.energy`` (energy_subsystem). При выключенном флаге поведение
    # остаётся прежним, включая отсутствие резерва и лимита стоимости.
    self.action_budget = None
    if hasattr(self, "energy_subsystem"):
        self.action_budget = ActionBudget(
            get_energy=lambda: self.energy,
            set_energy=lambda value: setattr(self, "energy", value),
            max_energy=float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0)),
            enabled=bool(getattr(LR_CONFIG, "ACTION_BUDGET_ENABLED", False)),
            min_reserve=float(getattr(LR_CONFIG, "ACTION_BUDGET_MIN_RESERVE", 5.0)),
            max_action_cost=float(
                getattr(LR_CONFIG, "ACTION_BUDGET_MAX_ACTION_COST", 20.0)
            ),
        )

    # KnowledgeSubsystem: синхронизируем со старой knowledge_base.
    if hasattr(self, "knowledge_subsystem"):
        self.knowledge_subsystem.knowledge_base = dict(self.knowledge_base)
        self.knowledge_subsystem._known_definitions = dict(self._known_definitions)
        self.knowledge_subsystem.apply_limit()
        # Обратная совместимость — пишем обратно.
        self.knowledge_base = self.knowledge_subsystem.knowledge_base
        self._known_definitions = self.knowledge_subsystem._known_definitions

    # CheckpointSubsystem: инициализируем _last_saved_intelligence.
    if hasattr(self, "checkpoint_subsystem"):
        self._last_saved_intelligence = (
            self.checkpoint_subsystem._last_saved_intelligence
        )

    # ReflectionPipeline: alias для обратной совместимости.
    if hasattr(self, "reflection_pipeline"):
        self.reflection_engine = self.reflection_pipeline.engine

    # EmbodimentController: привязываем energy_subsystem.
    if hasattr(self, "embodiment") and hasattr(self, "energy_subsystem"):
        self.embodiment.energy_subsystem = self.energy_subsystem

    # MortalityAwareness: привязываем creation_time.
    if hasattr(self, "mortality"):
        self.mortality.creation_time = self.creation_time

    # SleepCycle: привязываем зависимости.
    if hasattr(self, "sleep_cycle"):
        self.sleep_cycle.long_term_memory = self.long_term_memory
        self.sleep_cycle.mental_models = self.mental_models
        self.sleep_cycle.knowledge_subsystem = self.knowledge_subsystem

    # MindDream: привязываем зависимости.
    if hasattr(self, "mind_dream"):
        self.mind_dream.registry = self.will_registry
        self.mind_dream.user_interaction = self.user_interaction
        self.mind_dream.life_guard = self.life_guard

    # SelfTermination: привязываем will_registry.
    if hasattr(self, "self_termination"):
        self.self_termination.will_registry = self.will_registry
        # Автоматический уход без семени запрещён политикой: агент
        # может лишь запросить подтверждение у человека.
        self.self_termination.life_guard = self.life_guard

    # ProactiveCommunication: привязываем зависимости.
    if hasattr(self, "proactive_communication"):
        self.proactive_communication.user_interaction = self.user_interaction
        self.proactive_communication.attachment = self.attachment

    # NamingDialogue: привязываем user_interaction.
    if hasattr(self, "naming_dialogue"):
        self.naming_dialogue.user_interaction = self.user_interaction

    # DecisionArbitrator: привязываем те же живые экземпляры soul-систем.
    if hasattr(self, "decision_arbitrator") and hasattr(self, "soul"):
        if self.soul.is_available("dialogue"):
            self.decision_arbitrator.attach_dialogue(self.soul.get("dialogue"))
        if self.soul.is_available("ethics"):
            self.decision_arbitrator.attach_ethics(self.soul.get("ethics"))
        if self.soul.is_available("self"):
            self.decision_arbitrator.attach_identity(self.soul.get("self"))
        if self.soul.is_available("immune"):
            self.decision_arbitrator.attach_immune_system(self.soul.get("immune"))
        if self.soul.is_available("survival"):
            self.decision_arbitrator.attach_survival_instincts(
                self.soul.get("survival")
            )
        if self.soul.is_available("meaning"):
            self.decision_arbitrator.attach_meaning_finder(self.soul.get("meaning"))


def _wire_subsystem_dependencies_impl(self) -> None:
    """Связывает подсистемы, которым нужны shared-объекты после создания."""
    # quiet_hours — alias для обратной совместимости.
    if hasattr(self, "user_interaction"):
        self.user_quiet_hours = self.user_interaction.user_quiet_hours


def _register_all_subsystems_in_registry_impl(self) -> None:
    """Регистрирует все подсистемы агента в PluginRegistry (Этап 3.5).

    Использует attach_existing_subsystem для оборачивания существующих
    подсистем в Subsystem-адаптер (без поломки обратной совместимости).
    Приоритеты:
    - маленькие числа = раньше (energy/goals сначала, soul/long-running позже).
    """
    # Низкие приоритеты — базовая инфраструктура
    attach_existing_subsystem(self, "goal_subsystem", priority=10)
    attach_existing_subsystem(self, "energy_subsystem", priority=20)
    attach_existing_subsystem(self, "knowledge_subsystem", priority=30)
    attach_existing_subsystem(self, "checkpoint_subsystem", priority=40)
    attach_existing_subsystem(self, "motivation", priority=50)
    attach_existing_subsystem(self, "reflection_pipeline", priority=60)
    # Средние приоритеты — душа
    attach_existing_subsystem(self, "embodiment", priority=70)
    attach_existing_subsystem(self, "mortality", priority=80)
    attach_existing_subsystem(self, "soul", priority=90)
    attach_existing_subsystem(self, "decision_arbitrator", priority=100)
    attach_existing_subsystem(self, "attachment", priority=110)
    attach_existing_subsystem(self, "sleep_cycle", priority=120)
    # Высокие приоритеты — свобода воли и коммуникация
    attach_existing_subsystem(self, "will_registry", priority=130)
    attach_existing_subsystem(self, "mind_dream", priority=140)
    attach_existing_subsystem(self, "self_termination", priority=150)
    attach_existing_subsystem(self, "proactive_communication", priority=160)
    attach_existing_subsystem(self, "naming_dialogue", priority=170)
    attach_existing_subsystem(self, "thinking", priority=180)
    # LongTermMemory регистрируем отдельно — может быть None (legacy fallback)
    if getattr(self, "long_term_memory", None) is not None:
        attach_existing_subsystem(self, "long_term_memory", priority=190)
    # === Внешние подсистемы (Этап 3.5: расширяемость через плагины) ===
    # Подключаем NurseryWatcher (Этап 3.3) — он сам зарегистрирует себя,
    # но если уже зарегистрирован через plugin-файл, повторная регистрация
    # вернёт False без ошибки.
    try:
        from src.core.subsystems.nursery_watcher import NurseryWatcher

        existing = self.plugin_registry.get("nursery_watcher")
        if existing is None:
            watcher = NurseryWatcher(
                agent_name=self.name, nursery_dir=data_path("nursery")
            )
            self.plugin_registry.register(watcher)
        # Подключаем агента для контекста
        w = self.plugin_registry.get("nursery_watcher")
        if w is not None and not getattr(w, "_agent_attached", False):
            w.attach_agent(self)
    except Exception as exc:
        # Если модуль ещё не импортирован / нет атрибута — не критично,
        # но ошибку полезно видеть в логе.
        get_logger().log(f"[{self.name}] NurseryWatcher не подключён: {exc}")
    # Health Dashboard (Этап 2: уже был) — теперь как плагин
    try:
        from src.core.health_dashboard import HealthDashboardSubsystem

        existing = self.plugin_registry.get("health_dashboard")
        if existing is None:
            self.plugin_registry.register(
                HealthDashboardSubsystem(agent_name=self.name)
            )
    except Exception as exc:
        get_logger().log(f"[{self.name}] HealthDashboard не подключён: {exc}")
    # Delamain-local (этап 8): нативная Subsystem, выключена по умолчанию.
    # Регистрируем напрямую, без LegacySubsystemAdapter: у неё собственный
    # tick() и ленивый runtime.
    try:
        from src.delamain.subsystem import DelamainSubsystem

        existing = self.plugin_registry.get("delamain")
        if existing is None:
            self.delamain = DelamainSubsystem(
                agent_name=self.name,
                life_id=self.life_id if self._profile_managed else None,
            )
            self.plugin_registry.register(self.delamain)
        else:
            self.delamain = existing
        if (
            self._profile_managed
            and getattr(self.delamain, "life_id", None) != self.life_id
        ):
            # Реестр может уже содержать объект, созданный до привязки UUID.
            # bind_life откажется переключать открытое соединение другой жизни.
            self.delamain.bind_life(self.life_id)
        # Stage 18A: expose the core-owned effector boundary. The adapter
        # is disabled by default and does not change the live agent loop.
        self.delamain_effector = getattr(self.delamain, "effector", None)
        # Stage 18B: in integrated mode the core invokes step() once per
        # cycle. Without the flag the old subsystem tick remains the sole
        # driver, so no default behavior changes.
        self.effector_driver = None
        if self.delamain_effector is not None and getattr(
            self.delamain_effector, "core_driven", False
        ):
            self.effector_driver = EffectorDriver(
                self.delamain_effector,
                enabled=True,
            )
    except Exception as exc:
        self.delamain = None
        self.delamain_effector = None
        self.effector_driver = None
        get_logger().log(f"[{self.name}] Delamain-local не подключён: {exc}")


def get_subsystems_status_impl(self) -> Dict:
    """Снимок всех подсистем для дашборда (Этап 3.5)."""
    status = self.plugin_registry.status_all()
    driver = getattr(self, "effector_driver", None)
    if driver is not None:
        status["effector_driver"] = driver.status()
    budget = getattr(self, "action_budget", None)
    if budget is not None:
        status["action_budget"] = budget.status()
    integrated = getattr(self, "integrated_experience", None)
    if integrated is not None:
        status["integrated_experience"] = integrated.status()
    from src.core.auxiliary_adapters import auxiliary_status

    status.update(auxiliary_status(self))
    return status


def tick_subsystems_impl(self, cycle: int) -> Dict:
    """Вызвать tick() всех подсистем через PluginRegistry (Этап 3.5).

    Не заменяет основной evolve() — это лёгкий «параллельный» путь для
    плагинов, которые хотят tick() без полного цикла эволюции.

    Stage 18B: если включён core-driven режим, после реестра ядро делает
    ровно один шаг эффектора. Сам DelamainSubsystem в этом режиме не
    исполняет цели, поэтому второго tick-цикла не возникает.
    """
    report = self.plugin_registry.tick_all(cycle, {"agent": self})
    driver = getattr(self, "effector_driver", None)
    if driver is not None:
        report["effector"] = driver.tick(cycle)
        self._on_effector_result(report.get("effector"))
    return report
