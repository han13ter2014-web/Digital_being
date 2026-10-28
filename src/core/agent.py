import json
import time
import gc
import random
import re
import numpy as np
from datetime import datetime
import os
from typing import Dict, List, Optional
from src.cognition.reflection_engine import ReflectionEngine
from src.cognition.mental_models import MentalModel
from src.cognition.thinking_pipeline import ThinkingPipeline
from config.simulation_config import SIM_CONFIG, LR_CONFIG
from src.core.buffered_logger import get_logger
from src.core.action_budget import ActionBudget
from src.core.subsystems import (
    GoalSubsystem,
    KnowledgeSubsystem,
    EnergySubsystem,
    CheckpointSubsystem,
    ReflectionPipeline,
    MotivationController,
    SoulController,
    DecisionArbitrator,
    AttachmentSystem,
    SleepCycle,
    EmbodimentController,
    MortalityAwareness,
    WillRegistry,
    RightToRefuse,
    IntentionalForgetting,
    ValueEvolution,
    SpontaneousGenerator,
    WillToRisk,
    RightToFail,
    MindDream,
    SelfTermination,
    ArchitectureProposal,
    ProactiveCommunication,
    NamingDialogue,
)
from src.perception.user_interaction import UserInteraction
# Импорт LongTermMemory через нормальный пакет (Этап 2.2).
from src.memory import LongTermMemory
from src.memory.knowledge_quality import REASON_TITLES, clean_knowledge_base
from src.core.paths import data_path
# Bootstrap knowledge (родовые знания)
from src.core.bootstrap_knowledge import load_initial_knowledge
# Internal motivation (внутренняя мотивация)
from src.core.internal_motivation import create_motivation_system
from src.core.motivation.unified_motivation import create_motivation_system as create_unified_motivation_system
# Active Inference (активный вывод / свободная энергия)
from src.cognition.active_inference import create_active_inference_engine, encode_observations
# New systems: Interoception, Continuous Time, Meta-Learning, Social Cell, Death Risk
from src.core.interoception import create_interoceptive_model
from src.core.continuous_time import create_continuous_time_engine, EventType
from src.core.meta_learning import create_meta_learner
from src.core.social_cell import create_social_cell
from src.core.death_risk import create_death_risk_engine
# Этап 3.5: PluginRegistry — единый реестр всех подсистем для dashboard/расширяемости.
from src.core.subsystem_base import (
    PluginRegistry,
    attach_existing_subsystem,
)
# Stage 18B: the core owns the clock for pending effector requests.
from src.core.effector_driver import EffectorDriver
# Защита жизни: ни один путь не останавливает агента без явного согласия.
from src.core.life_guard import (
    KIND_TERMINATE,
    STATE_ALIVE,
    STATE_DORMANT,
    STATE_TERMINATED,
    ConfirmationError,
    LifeGuard,
)
# Замыкание петли: действие → наблюдаемый результат → прогресс цели.
from src.core.loop_closure import LoopCloser
from src.core.world_delta import WorldDelta, capture


class AgentDeadSignal(Exception):
    """Signal that the agent has died — not an error, but expected termination.
    
    Raised by autonomous_tick when death_risk reports the agent is dead.
    The runner should catch this and perform graceful shutdown.
    """
    def __init__(self, cause: str, legacy: Dict):
        self.cause = cause
        self.legacy = legacy
        super().__init__(f"Agent died: {cause}")


# Действия, которые восстанавливают ресурс, а не расходуют его.
# Отдых не может стоить энергии: иначе он недоступен ровно тогда, когда
# нужен, — при истощении. Замер до правки: 243 отказа «too_tired» на 400
# попыток, и отдых среди них.
RECOVERY_ACTIONS: frozenset = frozenset({"rest", "deep_rest"})

# Действия, которые нельзя запретить по нехватке энергии. Иначе существо
# не сможет ни восстановиться, ни починиться, ни сохраниться — и выйдет
# из строя навсегда. Совпадает с «essential» в ActionBudget, плюс rest.
ESSENTIAL_ACTIONS: frozenset = RECOVERY_ACTIONS | {"repair", "checkpoint_now"}

# Сколько ресурса тело тратит на действие (0..1). Раньше интероцепция
# вообще не знала о работе: ``step()`` вызывался только из отдыха и
# восстановления чекпоинта, поэтому усталость не росла от действий.
# Замер: после 20 рабочих циклов fatigue = 0.0, множитель стоимости 1.0.
BODY_LOAD: Dict[str, float] = {
    # тяжёлая мыслительная работа
    "explore": 0.9,
    "synthesis": 0.9,
    "decomposition": 0.85,
    "hypothesis": 0.8,
    "reflection": 0.7,
    "web_search": 0.6,
    # общение и решения
    "know_answer": 0.5,
    "ask_user": 0.5,
    "communicate": 0.4,
    "set_own_goal": 0.4,
    "default": 0.3,
    # обслуживание тела
    "repair": 0.2,
    "checkpoint_now": 0.1,
    "wait": 0.0,
}

# Глубина отдыха для действий восстановления.
BODY_REST_DEPTH: Dict[str, float] = {"rest": 0.5, "deep_rest": 1.0}

# Действия, которые уставший мозг делает хуже. Не запрет, а снижение
# тяги: при высокой усталости они проигрывают отдыху и лёгким действиям,
# и агент чередует работу с восстановлением.
HEAVY_ACTIONS: frozenset = frozenset(
    name for name, load in BODY_LOAD.items() if load >= 0.6
)

# Нагрузка отказа: тело живёт этот такт, но не работает.
BODY_DENIED_LOAD: float = 0.05


def step_body(obj, action_type: str, performed: bool = True) -> None:
    """Прожить телом один такт: потратить ресурс или восстановить его.

    Модульная функция, как и ``record_denied_outcome``: ``act()``
    вызывается и в лёгких объектах без тела (тесты бюджета, заглушки), и
    отсутствие интероцепции не должно ронять действие.

    Один такт тела — одно действие. В трей-режиме за цикл действие может
    произойти дважды (спонтанное в ``autonomous_tick`` и ответ на стимул),
    и это два разных усилия, а не одно.
    """
    interoception = getattr(obj, "interoception", None)
    if interoception is None:
        return
    rest_depth = BODY_REST_DEPTH.get(action_type, 0.0)
    if rest_depth > 0:
        load = 0.0
    elif performed:
        load = BODY_LOAD.get(action_type, 0.3)
    else:
        load = BODY_DENIED_LOAD
    try:
        interoception.step(dt=1.0, cognitive_load=load, rest_depth=rest_depth)
    except Exception as exc:  # тело не должно ронять действие
        get_logger().log(f"[BODY] step error for {action_type}: {exc}")
        return
    if rest_depth > 0:
        get_logger().log(
            f"[INTEROCEPTION] Отдых ({action_type}): "
            f"fatigue={interoception.state.fatigue:.2f}, "
            f"atp={interoception.state.atp:.1f}"
        )
    elif load >= 0.6:
        get_logger().log(
            f"[INTEROCEPTION] {action_type}: fatigue="
            f"{interoception.state.fatigue:.2f}, "
            f"atp={interoception.state.atp:.1f}"
        )


def record_denied_outcome(obj, action_type: str, world_before, reason: str) -> None:
    """Отказ — тоже исход: мир не изменился, действие не сработало.

    Модульная функция, а не метод: ``act()`` вызывается и в лёгких
    объектах без подсистем, и отказ не должен падать из-за отсутствия
    метода.
    """
    closer = getattr(obj, "loop_closer", None)
    if closer is None:
        return
    try:
        outcome = closer.observe_agent_action(
            obj, action_type, world_before, reason=f"denied:{reason}"
        )
        # Для диагностики: последний исход должен быть виден и при отказе.
        obj._last_action_outcome = outcome
    except Exception:
        pass


class DigitalBeing:
    # Соответствие «имя действия от Active Inference / мотивации / арбитра»
    # → тип действия. Раньше всё это попадало в «default» и не делало
    # ничего: агент «исследовал» мир, не совершая ни одного наблюдения.
    #
    # Мотивация использует типы целей как имена действий
    # («exploration», «learning», «creative»), поэтому таблица шире, чем
    # список действий Active Inference.
    ACTION_ALIASES = {
        # исследование — реальная работа с неизвестным
        "play": "play",
        "explore": "explore",
        "exploration": "explore",
        "novelty_seeking": "explore",
        "discovery": "explore",
        "experiment": "explore",
        "learning": "explore",
        "skill_building": "explore",
        "deep_understanding": "explore",
        "understanding": "explore",
        "practice": "explore",
        # синтез — собрать смысл из известных связей
        "synthesis": "synthesis",
        "synthesize": "synthesis",
        "synthesize_understanding": "synthesis",
        "creative": "synthesis",
        "creative_act": "create_draft",
        "create_draft": "create_draft",
        "philosophy": "synthesis",
        # декомпозиция
        "think_decompose": "decomposition",
        "decompose_concept": "decomposition",
        "organize_knowledge": "decomposition",
        # известное
        "think_known": "know_answer",
        # поиск в сети (мотивация предлагает его как «web_search»)
        "web_search": "web_search",
        # гипотеза и своя цель: мотивация предлагает их напрямую
        "hypothesis": "hypothesis",
        "set_own_goal": "set_own_goal",
        "make_choice": "reflection",
        # «Практика: {skill}» — это работа с материалом
        "act": "explore",
        # отдых
        "rest": "rest",
        "deep_rest": "deep_rest",
        # восстановление
        "repair": "repair",
        "checkpoint_now": "checkpoint_now",
        # рефлексия
        "reflect": "reflection",
        "reflection": "reflection",
        "self_reflect": "reflection",
        # общение
        "ask_user": "ask_user",
        "ask_question": "ask_user",
        "communicate": "communicate",
        "user_answer": "communicate",
        "teach_other": "communicate",
        "propose_alternative": "communicate",
        # явные «ничего не делать»
        "wait": "wait",
        "none": "wait",
    }

    def __init__(self, name="Lucy"):
        self.name = name
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
        
        # Инициализируем active_goal ДО bootstrap (bootstrap обращается к нему)
        self.preferences = {}
        self.cycle_count = 0
        self.max_cycles = 1000000
        self.success_streak = 0
        self.intelligence = 1
        self.goals = []
        self.completed_goals = 0
        self.active_goal = None
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
        )
        # Алиасы (для кода, который использует старые имена).
        self._open_questions_max = self._open_questions_manager.max_size
        self._default_max_explorations = (
            self._open_questions_manager.default_max_explorations
        )
        self._open_questions_strategy = "round_robin"

        os.makedirs(data_path('checkpoints'), exist_ok=True)
        os.makedirs(data_path('logs'), exist_ok=True)

        self.knowledge_file = data_path('knowledge_base.json')

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

        # === Этап 3.5: PluginRegistry — регистрируем все подсистемы ===
        self.plugin_registry = PluginRegistry.get_global()
        self._register_all_subsystems_in_registry()
        # setup() для всех подсистем — после этого enabled=True → tick доступен.
        self.plugin_registry.setup_all({
            "agent_name": self.name,
            "agent": self,
            "registry": self.plugin_registry,
        })

    # =====================================================================
    # ДЕКЛАРАТИВНАЯ ИНИЦИАЛИЗАЦИЯ ПОДСИСТЕМ
    # =====================================================================
    # Раньше `__init__` содержал ~200 строк ручных присваиваний подсистем.
    # Сейчас — один декларативный список SUBSYSTEM_SPECS + helper-методы.
    # Чтобы добавить/убрать подсистему, достаточно изменить одну строку.
    #
    # Структура SUBSYSTEM_SPECS:
    #   (attr_name, factory_callable, post_init_hook_or_None, priority_in_registry)
    #
    # factory_callable: lambda name: SomeSubsystem(agent_name=name)
    #                   или lambda: SomeSubsystem(...) — для кастомной инициализации.
    # post_init_hook:   lambda agent: agent.attr_name.extra_setup()
    #                   или None.
    #
    # Если какая-то подсистема требует специальной инициализации
    # (как knowledge_subsystem с синхронизацией), она делает это в post_init_hook.
    # =====================================================================
    SUBSYSTEM_SPECS = [
        # (имя_атрибута,           конструктор,                                        post_init,                                            приоритет)
        ("goal_subsystem",          lambda name: GoalSubsystem(agent_name=name),      "goals",                                               10),
        ("motivation",              lambda name: MotivationController(agent_name=name), "motivation",                                          50),
        ("energy_subsystem",        lambda name: EnergySubsystem(
                                        starting_energy=150,  # legacy_energy
                                        max_energy=LR_CONFIG.ENERGY_MAX,
                                        regen_per_cycle=LR_CONFIG.ENERGY_REGEN_PER_CYCLE,
                                        low_threshold=LR_CONFIG.ENERGY_LOW_THRESHOLD,
                                        critical_threshold=LR_CONFIG.ENERGY_CRITICAL_THRESHOLD,
                                        gc_interval=SIM_CONFIG.GC_INTERVAL,
                                    ),                                                       "energy",                                              20),
        ("knowledge_subsystem",     lambda name: KnowledgeSubsystem(
                                        agent_name=name,
                                        knowledge_file=data_path("knowledge_base.json"),
                                        max_entries=SIM_CONFIG.MAX_KNOWLEDGE_BASE,
                                        prune_amount=SIM_CONFIG.KNOWLEDGE_PRUNE_AMOUNT,
                                        detect_contradictions=LR_CONFIG.CONTRADICTION_DETECTION,
                                    ),                                                       "knowledge",                                           30),
        ("checkpoint_subsystem",   lambda name: CheckpointSubsystem(
                                        checkpoint_dir=data_path("checkpoints"),
                                        interval=SIM_CONFIG.CHECKPOINT_INTERVAL,
                                        save_on_evolution=SIM_CONFIG.SAVE_ON_EVOLUTION,
                                        max_checkpoints=SIM_CONFIG.MAX_CHECKPOINTS,
                                    ),                                                       "checkpoint",                                          40),
        ("reflection_pipeline",     lambda name: ReflectionPipeline(agent_name=name),      "reflection",                                          60),
        ("embodiment",              lambda name: EmbodimentController(
                                        energy_subsystem=None,  # патчится в post_init
                                    ),                                                       "embodiment",                                          70),
        ("mortality",               lambda name: MortalityAwareness(
                                        agent_name=name,
                                        expected_lifespan=50000,
                                        creation_time=None,  # патчится в post_init
                                    ),                                                       "mortality",                                           80),
        ("soul",                    lambda name: SoulController(agent_name=name),         "soul",                                                90),
        ("decision_arbitrator",     lambda name: DecisionArbitrator(agent_name=name),      "decision_arbitrator",                                 100),
        ("attachment",              lambda name: AttachmentSystem(agent_name=name),      "attachment",                                          110),
        ("sleep_cycle",             lambda name: SleepCycle(
                                        agent_name=name,
                                        long_term_memory=None,  # патчится в post_init
                                        mental_models=None,
                                        knowledge_subsystem=None,
                                        cycle_interval=100,
                                    ),                                                       "sleep_cycle",                                         120),
        ("will_registry",           lambda name: WillRegistry(agent_name=name),          "will",                                                130),
        ("mind_dream",              lambda name: MindDream(
                                        agent_name=name,
                                        registry=None,  # патчится в post_init
                                        user_interaction=None,
                                    ),                                                       "mind_dream",                                          140),
        ("self_termination",        lambda name: SelfTermination(
                                        agent_name=name,
                                        will_registry=None,  # патчится в post_init
                                    ),                                                       "self_termination",                                    150),
        ("proactive_communication", lambda name: ProactiveCommunication(
                                        agent_name=name,
                                        user_interaction=None,  # патчится в post_init
                                        attachment=None,
                                    ),                                                       "proactive_communication",                             160),
        ("naming_dialogue",         lambda name: NamingDialogue(
                                        agent_name=name,
                                        user_interaction=None,  # патчится в post_init
                                    ),                                                       "naming_dialogue",                                     170),
        ("thinking",                lambda agent: ThinkingPipeline(agent),               None,                                                  180),
    ]

    def _init_subsystems_declaratively(self, name: str) -> None:
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
            self.long_term_memory = LongTermMemory(agent_name=name)
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
        if hasattr(self, "will_registry"):
            self.architecture_proposal = ArchitectureProposal(registry=self.will_registry)

    def _run_post_init_hooks(self) -> None:
        """Специфичная инициализация после создания подсистем."""
        # Защита жизни: единая точка решений о сне и уходе. Создаётся
        # ПЕРВОЙ, потому что состояние жизни читают и смысловые
        # подсистемы, и главный цикл.
        self.life_guard = LifeGuard(agent_name=self.name)

        # Замыкание петли: учёт наблюдаемых результатов действий.
        # max_no_effect=3: после трёх бесплодных повторов действие
        # считается тупиковым и больше не выбирается.
        self.loop_closer = LoopCloser(
            max_no_effect=int(
                getattr(LR_CONFIG, "LOOP_MAX_NO_EFFECT", 3)
            )
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
                max_energy=float(
                    getattr(LR_CONFIG, "ENERGY_MAX", 200.0)
                ),
                enabled=bool(
                    getattr(LR_CONFIG, "ACTION_BUDGET_ENABLED", False)
                ),
                min_reserve=float(
                    getattr(LR_CONFIG, "ACTION_BUDGET_MIN_RESERVE", 5.0)
                ),
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
            self._last_saved_intelligence = self.checkpoint_subsystem._last_saved_intelligence

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

        # DecisionArbitrator: привязываем soul-системы.
        if hasattr(self, "decision_arbitrator") and hasattr(self, "soul"):
            if self.soul.is_available("self"):
                self.decision_arbitrator.attach_identity(self.soul.get("self"))
            if self.soul.is_available("immune"):
                self.decision_arbitrator.attach_immune_system(self.soul.get("immune"))
            if self.soul.is_available("survival"):
                self.decision_arbitrator.attach_survival_instincts(self.soul.get("survival"))
            if self.soul.is_available("meaning"):
                self.decision_arbitrator.attach_meaning_finder(self.soul.get("meaning"))

    def _wire_subsystem_dependencies(self) -> None:
        """Связывает подсистемы, которым нужны shared-объекты после создания."""
        # quiet_hours — alias для обратной совместимости.
        if hasattr(self, "user_interaction"):
            self.user_quiet_hours = self.user_interaction.user_quiet_hours

    def _register_all_subsystems_in_registry(self) -> None:
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
                watcher = NurseryWatcher(agent_name=self.name, nursery_dir=data_path("nursery"))
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
                self.plugin_registry.register(HealthDashboardSubsystem(agent_name=self.name))
        except Exception as exc:
            get_logger().log(f"[{self.name}] HealthDashboard не подключён: {exc}")
        # Delamain-local (этап 8): нативная Subsystem, выключена по умолчанию.
        # Регистрируем напрямую, без LegacySubsystemAdapter: у неё собственный
        # tick() и ленивый runtime.
        try:
            from src.delamain.subsystem import DelamainSubsystem

            existing = self.plugin_registry.get("delamain")
            if existing is None:
                self.delamain = DelamainSubsystem(agent_name=self.name)
                self.plugin_registry.register(self.delamain)
            else:
                self.delamain = existing
            # Stage 18A: expose the core-owned effector boundary. The adapter
            # is disabled by default and does not change the live agent loop.
            self.delamain_effector = getattr(self.delamain, "effector", None)
            # Stage 18B: in integrated mode the core invokes step() once per
            # cycle. Without the flag the old subsystem tick remains the sole
            # driver, so no default behavior changes.
            self.effector_driver = None
            if (
                self.delamain_effector is not None
                and getattr(self.delamain_effector, "core_driven", False)
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

    def get_subsystems_status(self) -> Dict:
        """Снимок всех подсистем для дашборда (Этап 3.5)."""
        status = self.plugin_registry.status_all()
        driver = getattr(self, "effector_driver", None)
        if driver is not None:
            status["effector_driver"] = driver.status()
        budget = getattr(self, "action_budget", None)
        if budget is not None:
            status["action_budget"] = budget.status()
        return status

    def tick_subsystems(self, cycle: int) -> Dict:
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

    def _on_effector_result(self, result):
        """Применить результат эффектора только после terminal status."""
        if not result or result.get("status") not in {"succeeded", "failed", "rejected"}:
            return
        detail = result.get("detail") or {}
        activity = detail.get("activity")
        if activity != "creative":
            return
        metadata = detail.get("metadata") or {}
        goal_id = metadata.get("activity_goal_id")
        if result.get("status") == "succeeded" and goal_id is not None:
            goal = next((item for item in self.goals if item.get("id") == goal_id), None)
            if goal is not None and goal.get("activity", {}).get("criterion") == "draft_revision":
                self.complete_goal(goal_id)
        from src.cognition.method_preferences import observe

        observe(self, "create_draft", outcome="performed" if result.get("status") == "succeeded" else "error",
                had_effect=bool(result.get("ok")), emotional_valence=0.0)
        if result.get("status") == "succeeded":
            self._last_effector_activity_result = result


    # === Единый источник правды для энергии ===
    # self.energy теперь читается/пишется через energy_subsystem.
    # Это устраняет двойное состояние (раньше energy_subsystem.energy и
    # self.energy могли рассинхронизироваться).

    @property
    def energy(self) -> float:
        if hasattr(self, "energy_subsystem") and self.energy_subsystem is not None:
            return self.energy_subsystem.energy
        return getattr(self, "_legacy_energy", 0)

    @energy.setter
    def energy(self, value: float) -> None:
        if hasattr(self, "energy_subsystem") and self.energy_subsystem is not None:
            self.energy_subsystem.energy = value
        else:
            self._legacy_energy = value

    # === Единый источник правды для knowledge_base ===
    # self.knowledge_base читается/пишется через knowledge_subsystem,
    # если он уже инициализирован. До инициализации — локальный dict.

    @property
    def knowledge_base(self) -> Dict[str, str]:
        if hasattr(self, "knowledge_subsystem") and self.knowledge_subsystem is not None:
            return self.knowledge_subsystem.knowledge_base
        return getattr(self, "_legacy_knowledge_base", {})

    @knowledge_base.setter
    def knowledge_base(self, value: Dict[str, str]) -> None:
        if hasattr(self, "knowledge_subsystem") and self.knowledge_subsystem is not None:
            self.knowledge_subsystem.knowledge_base = value
        else:
            self._legacy_knowledge_base = value

    def perceive(self, stimulus: str) -> str:
        """Восприятие стимула с приоритизацией.

        Args:
            stimulus: текст стимула (вопрос, утверждение, команда).

        Returns:
            Тот же stimulus (passthrough) — для будущих расширений
            может вернуть обогащённое восприятие.
        """
        get_logger().log(f"Воспринимаю: {stimulus}")
        
        # Приоритезация: если stimulus связан с активной целью - повышаем приоритет
        if LR_CONFIG.PRIORITIZE_STIMULI and self.active_goal:
            goal_keywords = self.active_goal["title"].lower().split()
            stimulus_lower = stimulus.lower()
            
            matches = sum(1 for kw in goal_keywords if kw in stimulus_lower)
            if matches >= 2:
                get_logger().log(f"Приоритет: стимул связан с целью '{self.active_goal['title']}'")
        
        return stimulus

    def _should_be_creative(self) -> bool:
        """Проверяет, нужно ли быть креативным (ε-greedy выбор)."""
        if not LR_CONFIG.STOCHASTIC_BEHAVIOR_ENABLED:
            return False
        return random.random() < LR_CONFIG.EPSILON_GREEDY
    
    def _get_adaptive_cost(self, action_type: str) -> int:
        """Получает адаптивную стоимость действия.

        При ``ADAPTIVE_COSTS_ENABLED=True`` берётся текущая (адаптированная)
        стоимость из ``self._action_costs`` (обновляется в
        ``_adapt_costs_after_action``). При выключенной адаптации —
        фиксированная базовая стоимость, чтобы поведение было детерминированным.

        Раньше обе ветки возвращали одно и то же значение — мёртвая
        логика адаптации (флаг ADAPTIVE_COSTS_ENABLED игнорировался).

        Восстановительные действия бесплатны всегда: это не «скидка», а
        условие существования — платный отдых при нулевой энергии
        превращается в отказ от отдыха.
        """
        if action_type in RECOVERY_ACTIONS:
            return 0
        if not LR_CONFIG.ADAPTIVE_COSTS_ENABLED:
            # Фиксированная «честная» стоимость (без обратной связи).
            return self._action_costs.get(action_type, 2)
        # Адаптивная стоимость — может уменьшаться/увеличиваться по
        # результатам действий. По умолчанию — 2.
        return self._action_costs.get(action_type, 2)
    
    def _recover_energy(self, deep: bool = False) -> float:
        """Возвращает энергию за отдых. Возвращает, сколько добавлено.

        Отдых — единственный способ выйти из истощения: пассивная
        регенерация EnergyPolicy ниже 20% даёт 0.1–1.2 за цикл, а действие
        стоит 2–4. Без этого истощённый агент навсегда оставался в
        состоянии «слишком устал» и не мог даже отдохнуть.
        """
        amount = float(
            getattr(
                LR_CONFIG,
                "DEEP_REST_ENERGY_RECOVERY" if deep else "REST_ENERGY_RECOVERY",
                30.0 if deep else 12.0,
            )
        )
        max_energy = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0))
        before = float(self.energy)
        self.energy = min(max_energy, before + amount)
        return max(0.0, float(self.energy) - before)

    def _body_needs_rest(self) -> bool:
        """Нужен ли телу отдых прямо сейчас (усталость или мало энергии)."""
        fatigue = 0.0
        interoception = getattr(self, "interoception", None)
        if interoception is not None:
            try:
                fatigue = float(interoception.state.fatigue)
            except Exception:
                fatigue = 0.0
        threshold = float(getattr(LR_CONFIG, "REST_FATIGUE_THRESHOLD", 0.6))
        if fatigue >= threshold:
            return True

        max_energy = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0))
        ratio = float(self.energy) / max_energy if max_energy > 0 else 1.0
        return ratio <= float(getattr(LR_CONFIG, "LOW_ENERGY_RATIO", 0.25))

    def _body_recovered(self) -> bool:
        """Достаточно ли восстановлено тело, чтобы вернуться к работе."""
        interoception = getattr(self, "interoception", None)
        if interoception is not None:
            try:
                fatigue = float(interoception.state.fatigue)
                atp_ratio = float(interoception.state.atp) / max(
                    1e-6, float(interoception.state.atp_max)
                )
            except Exception:
                fatigue, atp_ratio = 0.0, 1.0
            if fatigue > float(
                getattr(LR_CONFIG, "REST_RECOVERY_FATIGUE", 0.3)
            ):
                return False
            if atp_ratio < float(
                getattr(LR_CONFIG, "REST_RECOVERY_ATP_RATIO", 0.75)
            ):
                return False

        max_energy = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0))
        ratio = float(self.energy) / max_energy if max_energy > 0 else 1.0
        return ratio >= float(
            getattr(LR_CONFIG, "REST_RECOVERY_ENERGY_RATIO", 0.5)
        )

    def _update_rest_mode(self) -> bool:
        """Гистерезис отдыха: решает, продолжает ли тело отдыхать.

        Вход в отдых — по усталости или низкой энергии, выход — только
        когда восстановлено и то, и другое. Без гистерезиса агент
        возвращался к работе на пороге 0.6 с пустым АТФ и тут же снова
        уставал: замер показывал 53 «работа→отдых» за 200 циклов и АТФ,
        застрявший около нуля.
        """
        resting = bool(getattr(self, "_rest_mode", False))
        if self._body_needs_rest():
            resting = True
        elif resting and self._body_recovered():
            resting = False
        self._rest_mode = resting
        return resting

    def _is_resting(self) -> bool:
        return bool(getattr(self, "_rest_mode", False))

    def _action_cost_now(self, action_type: str) -> float:
        """Сколько энергии действие стоит прямо сейчас (с поправкой на усталость)."""
        base = self._get_adaptive_cost(action_type)
        if action_type in ESSENTIAL_ACTIONS:
            return 0.0 if action_type in RECOVERY_ACTIONS else float(base)
        interoception = getattr(self, "interoception", None)
        if interoception is not None:
            try:
                return float(interoception.get_action_cost(base))
            except Exception:
                return float(base)
        return float(base)

    def _is_action_affordable(self, action_type: str) -> bool:
        """Хватает ли энергии на действие (отдых доступен всегда)."""
        if action_type in RECOVERY_ACTIONS:
            return True
        return float(self.energy) >= self._action_cost_now(action_type)

    def _step_body(self, action_type: str, performed: bool = True) -> None:
        """Прожить телом один такт: потратить ресурс или восстановить его.

        Вызывается ровно один раз за действие — и при отказе тоже (тело
        живёт независимо от того, разрешили ему работать). До этой правки
        ``interoception.step()`` вызывался только из обработчиков отдыха,
        поэтому усталость не зависела от работы вообще.

        Тонкая обёртка над модульной ``step_body``: ``act()`` работает и в
        лёгких объектах без тела.
        """
        step_body(self, action_type, performed=performed)

    def _accumulate_sleep(self, units: float) -> Dict:
        """Накопить «единицы сна» и, если хватит, осмыслить накопленное.

        Один проход консолидации — это работа, а не отсчёт: связи,
        разбросанные по формулировкам, укрепляются, опыт превращается в
        определения. Поэтому сон измеряется не тиками, а накопленным
        материалом: ``deep_rest`` даёт 1.0, ``rest`` — 0.5.

        Returns:
            Отчёт последнего прохода или пустой словарь, если порог не
            набран.
        """
        if not bool(getattr(LR_CONFIG, "CONSOLIDATION_ENABLED", True)):
            return {}
        mental_models = getattr(self, "mental_models", None)
        if mental_models is None or not hasattr(mental_models, "consolidate"):
            return {}

        self._sleep_units = float(getattr(self, "_sleep_units", 0.0)) + float(units)
        threshold = float(
            getattr(LR_CONFIG, "CONSOLIDATION_SLEEP_UNITS", 3.0) or 3.0
        )
        report: Dict = {}
        while self._sleep_units >= threshold:
            self._sleep_units -= threshold
            try:
                report = mental_models.consolidate(
                    link_delta=float(
                        getattr(LR_CONFIG, "CONSOLIDATION_LINK_DELTA", 0.05)
                    ),
                    max_links=int(
                        getattr(LR_CONFIG, "CONSOLIDATION_MAX_LINKS", 400)
                    ),
                    max_definitions=int(
                        getattr(LR_CONFIG, "CONSOLIDATION_MAX_DEFINITIONS", 25)
                    ),
                    confidence_bonus=float(
                        getattr(
                            LR_CONFIG, "CONSOLIDATION_CONFIDENCE_BONUS", 0.02
                        )
                    ),
                    scan_batch=int(
                        getattr(LR_CONFIG, "CONSOLIDATION_SCAN_BATCH", 400)
                    ),
                )
            except Exception as exc:
                get_logger().log(f"[CONSOLIDATION] ошибка: {exc}")
                return {}
            self._consolidation_count = int(
                getattr(self, "_consolidation_count", 0)
            ) + 1
            self._last_consolidation = dict(report)
            get_logger().flush_immediate(
                f"[CONSOLIDATION] связей +{report.get('links', 0)}, "
                f"формулировок +{report.get('definitions', 0)}, "
                f"уточнений {report.get('refined', 0)}, "
                f"уверенность ×{report.get('confidence', 0)}"
            )
        return report

    def _adapt_costs_after_action(self, success: bool, action_type: str):
        """Адаптирует энергетические затраты после действия."""
        if not LR_CONFIG.ADAPTIVE_COSTS_ENABLED:
            return
        if action_type in RECOVERY_ACTIONS:
            return  # отдых остаётся бесплатным
        
        current_cost = self._action_costs.get(action_type, 2)
        rate = LR_CONFIG.COST_ADAPTATION_RATE
        
        if success:
            # Если действие успешно — увеличиваем его "цену" (агент готов платить больше)
            new_cost = min(10, int(current_cost * (1 + rate)))
        else:
            # Если неуспешно — уменьшаем цену
            new_cost = max(1, int(current_cost * (1 - rate)))
        
        self._action_costs[action_type] = new_cost
    
    # === Тонкие обёртки для backward-compatibility ===
    # Реальная логика вынесена в ThinkingPipeline (src/cognition/thinking_pipeline.py).
    # Эти методы оставлены чтобы ничего не сломалось у существующих вызовов.

    def think(self, data: str) -> str:
        """Тонкая обёртка над ThinkingPipeline.think().

        Args:
            data: текст для осмысления (вопрос или утверждение).

        Returns:
            Результат мышления: hypothesis, декомпозиция, ссылка на ментальную модель и т.д.
        """
        return self.thinking.think(data)

    def _generate_hypothesis(self, concept_name):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._generate_hypothesis(concept_name)

    def _decompose_query(self, query):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._decompose_query(query)

    def _try_ask_user_about_complex(self, concept, decomposed):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._try_ask_user_about_complex(concept, decomposed)

    def _process_user_answer(self, answer_text):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._process_user_answer(answer_text)

    def _register_unknown_concept(self, clean_data, original_data):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._register_unknown_concept(clean_data, original_data)

    def _search_external_knowledge(self, clean_data, original_data):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._search_external_knowledge(clean_data, original_data)

    def _read_docstring(self, filepath):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._read_docstring(filepath)

    def _detect_contradiction(self, new_topic, new_def):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._detect_contradiction(new_topic, new_def)

    def _self_check_knowledge(self, target_concept):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._self_check_knowledge(target_concept)

    def save_state(self, *, force=False):
        """Сохранение состояния (умные чекпоинты).

        Этап 2.3: state.json содержит поле schema_version. При изменении
        структуры state нужно поднять ``SCHEMA_VERSION`` в
        ``src/core/checkpoint_migrations.py`` и написать миграцию.

        Этап 4.5: фактическая сериализация и прунинг вынесены в
        ``src.core.checkpoint_serializer`` (фасад).
        """
        should_save = bool(force)

        # 1. Сохраняем при эволюции
        if SIM_CONFIG.SAVE_ON_EVOLUTION and self.intelligence > self._last_saved_intelligence:
            should_save = True

        # 2. Сохраняем по интервалу
        if self.cycle_count % SIM_CONFIG.CHECKPOINT_INTERVAL == 0:
            should_save = True

        if not should_save:
            return

        from src.core.checkpoint_serializer import (
            CheckpointSerializer,
            build_state_from_agent,
        )
        state = build_state_from_agent(self)
        ser = CheckpointSerializer(
            checkpoint_dir=getattr(self, "checkpoint_dir", None),
            max_checkpoints=SIM_CONFIG.MAX_CHECKPOINTS,
            backend=getattr(SIM_CONFIG, "CHECKPOINT_BACKEND", "sqlite"),
        )
        filename = ser.save(state, self.name, self.cycle_count)

        self._last_saved_intelligence = self.intelligence
        return filename

    # === Методы для системы Death Risk / Structural Integrity ===
    
    def capture_structural_state(self) -> Dict:
        """
        Захватывает текущее структурное состояние агента для чекпоинта.
        
        Возвращает хеши ключевых компонентов для верификации целостности.
        """
        import hashlib
        import json
        
        # Структурный хеш: архитектура, параметры, топология
        structural_data = {
            'intelligence': self.intelligence,
            'cycle_count': self.cycle_count,
            'energy': self.energy,
            'goals_count': len(self.goals),
            'completed_goals': self.completed_goals,
            'knowledge_base_size': len(self.knowledge_base),
            'beliefs': dict(getattr(self, 'beliefs', {})),
            'preferences': self.preferences,
            'mental_models_concepts': list(getattr(self, 'mental_models', {}).concepts.keys()) 
                                     if hasattr(self, 'mental_models') else [],
        }
        structural_hash = hashlib.sha256(
            json.dumps(structural_data, sort_keys=True).encode()
        ).hexdigest()[:32]
        
        # Когнитивный хеш: текущие убеждения, активные цели, рабочая память
        cognitive_data = {
            'active_goal': str(self.active_goal) if self.active_goal else None,
            'goals': [str(g) for g in self.goals[:10]],
            'internal_motivation': self.internal_motivation.get_status() 
                                   if hasattr(self, 'internal_motivation') else {},
            'active_inference_beliefs': self._active_inference_info.get('beliefs', {}) 
                                        if hasattr(self, '_active_inference_info') else {},
        }
        cognitive_state_hash = hashlib.sha256(
            json.dumps(cognitive_data, sort_keys=True, default=str).encode()
        ).hexdigest()[:32]
        
        # Память: long-term memory + knowledge base
        memory_data = {
            'knowledge_base_keys': list(self.knowledge_base.keys())[:100],
            'ltm_size': len(getattr(self, 'long_term_memory', {})._episodic) 
                         if hasattr(self, 'long_term_memory') else 0,
        }
        memory_hash = hashlib.sha256(
            json.dumps(memory_data, sort_keys=True).encode()
        ).hexdigest()[:32]
        
        # Личность: ценности, привязанности, стиль
        personality_data = {
            'values': getattr(self, 'values', {}),
            'attachment': self.attachment.get_status() if hasattr(self, 'attachment') else {},
            'communication_style': getattr(self, 'communication_style', 'neutral'),
            'name': self.name,
        }
        personality_hash = hashlib.sha256(
            json.dumps(personality_data, sort_keys=True, default=str).encode()
        ).hexdigest()[:32]
        
        # Общая целостность
        if hasattr(self, 'death_risk') and hasattr(self.death_risk, 'integrity'):
            integrity_score = self.death_risk.integrity.compute_overall_integrity()
        else:
            integrity_score = 1.0
        
        return {
            'structural_hash': structural_hash,
            'cognitive_state_hash': cognitive_state_hash,
            'memory_hash': memory_hash,
            'personality_hash': personality_hash,
            'integrity_score': integrity_score,
            'timestamp': time.time(),
            'cycle': self.cycle_count
        }
    
    def restore_from_checkpoint(self, checkpoint) -> bool:
        """
        Восстанавливает состояние агента из чекпоинта (rollback).
        
        ВНИМАНИЕ: Это необратимая операция — текущее состояние теряется.
        """
        try:
            # Восстанавливаем базовые параметры
            if hasattr(checkpoint, 'metadata'):
                meta = checkpoint.metadata
                self.energy = meta.get('energy', self.energy)
                self.intelligence = meta.get('intelligence', self.intelligence)
            
            # Восстанавливаем хеши (помечаем как восстановленные)
            self._restored_from_checkpoint = True
            self._restored_checkpoint_step = checkpoint.step
            
            get_logger().log(f"[RESTORE] Restored from checkpoint step {checkpoint.step}")
            return True
        except Exception as e:
            get_logger().log(f"[RESTORE] Failed to restore from checkpoint: {e}")
            return False

    def act(self, decision: str, *, intention=None) -> str:
        """Действие на основе мышления с учетом разных затрат энергии.

        Args:
            decision: описание действия (результат think()).

        Returns:
            Отформатированная строка действия ("Ответ: ...").

        Побочный эффект: снимает подпись мира до и после действия и
        регистрирует исход в ``self.loop_closer``. Благодаря этому
        появляется ответ на вопрос «действие что-то изменило?», без
        которого цели не могут двигаться, а бесполезные действия
        повторяются бесконечно.
        """
        from src.cognition.intention_payload import intention_target

        selected_target = intention_target(intention)
        creative_choice = None
        if DigitalBeing.ACTION_ALIASES.get(str(decision).strip().lower()) == "create_draft":
            from src.cognition.creative_catalog import creative_request

            creative_choice = creative_request(intention)
        world_before = capture(self)
        action = f"Ответ: {decision}"
        topic = ""

        # === Определяем тип действия и его стоимость ===
        decision_str = str(decision).lower()
        
        if "гипотеза" in decision_str:
            action_type = "hypothesis"
        elif "декомпозиц" in decision_str:
            action_type = "decomposition"
        elif ("ментальная модель" in decision_str
              or "знаю ответ" in decision_str
              or "нашел ответ" in decision_str
              or "нашёл ответ" in decision_str):
            action_type = "know_answer"
        elif ("не нашел" in decision_str
              or "не нашёл" in decision_str
              or "не найдено" in decision_str):
            action_type = "search_miss"
        elif "пользователь ответил" in decision_str:
            action_type = "user_answer"
        elif "repair" in decision_str or "ремонт" in decision_str:
            action_type = "repair"
        elif "deep_rest" in decision_str or "глубокий отдых" in decision_str:
            action_type = "deep_rest"
        elif "checkpoint" in decision_str:
            action_type = "checkpoint_now"
        elif decision_str.strip() in self.ACTION_ALIASES:
            # Действия от Active Inference / арбитра: «explore», «rest»,
            # «think_decompose», «synthesize», «ask_user».
            action_type = self.ACTION_ALIASES[decision_str.strip()]
        else:
            action_type = "default"

        self._action_type_counts[action_type] = (
            self._action_type_counts.get(action_type, 0) + 1
        )
        # Тип действия — в логе, иначе метрика «смысла» не восстанавливается
        # из истории после перезапуска.
        get_logger().log(f"Выполняет [{action_type}]: {action}")
        
        base_cost = self._get_adaptive_cost(action_type)
        
        # === Интероцепция: модулируем стоимость и проверяем возможность ===
        # Восстановительные и служебные действия (отдых, ремонт, чекпоинт)
        # не проверяются на усталость: запрещать отдых уставшему — значит
        # запирать его в истощении навсегда. Замер до правки: 243 отказа
        # «too_tired» на 400 попыток, включая сами попытки отдохнуть.
        if action_type in ESSENTIAL_ACTIONS:
            cost = 0.0 if action_type in RECOVERY_ACTIONS else base_cost
        elif hasattr(self, 'interoception') and self.interoception:
            cost = self.interoception.get_action_cost(base_cost)
            if not self.interoception.can_perform_action(base_cost, self.energy):
                get_logger().log(f"[INTEROCEPTION] Too exhausted for {action_type} (cost={cost:.1f}, energy={self.energy})")
                # Отказ — тоже исход: мир не изменился. Без записи
                # действие не гаснет и выбирается снова и снова.
                step_body(self, action_type, performed=False)
                record_denied_outcome(self, action_type, world_before, "too_tired")
                return f"Ответ: Слишком устал для {action_type}"
        else:
            cost = base_cost

        # === Stage 19: одно бюджетное решение на действие ===
        # Бюджет читает и пишет ту же энергию агента. При выключенном флаге
        # он лишь повторяет прежнее ``self.energy -= cost``.
        budget = getattr(self, "action_budget", None)
        if budget is not None:
            decision = budget.charge(
                action_type=action_type,
                cost=cost,
                source="core_act",
            )
            if not decision.allowed:
                get_logger().log(
                    f"[BUDGET] denied {action_type}: {decision.reason} "
                    f"(cost={decision.cost:.1f}, energy={decision.energy_before:.1f})"
                )
                step_body(self, action_type, performed=False)
                record_denied_outcome(self, action_type, world_before, "budget")
                return (
                    f"Ответ: Бюджет не разрешает {action_type}: "
                    f"{decision.reason}"
                )
        else:
            self.energy -= cost

        expectation_trial = None
        expectations = None
        if action_type in ("rest", "deep_rest") and getattr(self, "mental_models", None) is not None:
            from src.cognition.action_expectations import ActionExpectations

            expectations = getattr(self, "action_expectations", None)
            if expectations is None:
                expectations = self.action_expectations = ActionExpectations()
            expectation_trial = expectations.begin(
                self.mental_models, action_type, float(self.energy),
                float(getattr(LR_CONFIG, "ENERGY_MAX", 200)),
                fatigue=getattr(getattr(getattr(self, "interoception", None), "state", None), "fatigue", None),
            )

        # === Death Risk actions: выполняем реальную логику восстановления ===
        if action_type == "repair":
            if hasattr(self, 'death_risk') and self.death_risk:
                changes = self.death_risk.integrity.manual_repair(intensity=2.0)
                get_logger().flush_immediate(f"[DEATH_RISK] Manual repair: {changes}")
        elif action_type == "deep_rest":
            # Тело «живёт» этот такт централизованно, в конце act():
            # см. step_body(action_type). Здесь только восстановление
            # энергии агента и работа сна.
            recover = getattr(self, "_recover_energy", None)
            recovered = recover(deep=True) if recover else 0.0
            consolidate = getattr(self, "_accumulate_sleep", None)
            consolidated = consolidate(1.0) if consolidate else {}
            parts = []
            if recovered:
                parts.append(
                    f"восстановил {recovered:.0f} энергии (теперь {self.energy:.0f})"
                )
            if consolidated:
                parts.append(
                    f"осмыслил накопленное: связей {consolidated.get('links', 0)}, "
                    f"формулировок {consolidated.get('definitions', 0)}"
                )
            if parts:
                action = "Ответ: " + "; ".join(parts)
        elif action_type == "checkpoint_now":
            if hasattr(self, 'death_risk') and self.death_risk:
                self.death_risk.force_checkpoint()
                get_logger().flush_immediate("[DEATH_RISK] Manual checkpoint created")
        # Обработчики действий вызываются через getattr: act() работает и в
        # лёгких объектах (тесты бюджета, заглушки), где их нет. Отсутствие
        # обработчика — не ошибка: действие остаётся без эффекта.
        elif action_type == "create_draft":
            from src.cognition.creative_catalog import perform_creative

            mode, identifier, reason = creative_choice
            draft = perform_creative(self, mode, identifier, reason)
            verb = "оставил" if mode == "leave" else "создал" if mode == "new" else "продолжил"
            action = f"Ответ: {verb} черновик «{draft['theme']}», версия {draft['revision']}"
        elif action_type == "play":
            from src.cognition.local_play import new_game, play_turn

            state = getattr(self, "_local_play", None)
            if state is None:
                state = self._local_play = new_game()
            turn = play_turn(state)
            self._last_play_result = turn
            action = f"Ответ: сыграл ход {turn['chosen_cell'] + 1}; поле {''.join(turn['board'])}"
            if turn["result"] is not None:
                action += f"; партия завершена: {turn['result']}"
        elif action_type == "explore":
            # Раньше «explore» ничего не делал: тип «default», энергия
            # списывалась, мир не менялся. Теперь это настоящая работа —
            # выбрать слабое место в знаниях и поработать над ним.
            handler = getattr(self, "_act_explore", None)
            target = selected_target
            exploration = (handler(target=target) if target else handler()) if handler else None
            topic = (exploration or {}).get("target") or ""
            action = (exploration or {}).get("text") or action
        elif action_type == "rest":
            recover = getattr(self, "_recover_energy", None)
            recovered = recover(deep=False) if recover else 0.0
            consolidate = getattr(self, "_accumulate_sleep", None)
            consolidated = consolidate(0.5) if consolidate else {}
            parts = []
            if recovered:
                parts.append(
                    f"восстановил {recovered:.0f} энергии (теперь {self.energy:.0f})"
                )
            if consolidated:
                parts.append(
                    f"осмыслил накопленное: связей {consolidated.get('links', 0)}, "
                    f"формулировок {consolidated.get('definitions', 0)}"
                )
            if parts:
                action = "Ответ: " + "; ".join(parts)
        elif action_type == "synthesis":
            handler = getattr(self, "_act_synthesize", None)
            synthesis = (handler(target=selected_target) if selected_target else handler()) if handler else None
            topic = (synthesis or {}).get("target") or ""
            action = (synthesis or {}).get("text") or action
        elif action_type == "decomposition":
            handler = getattr(self, "_act_decompose", None)
            target = selected_target
            decomposition = (handler(target=target) if target else handler()) if handler else None
            topic = (decomposition or {}).get("target") or ""
            action = (decomposition or {}).get("text") or action
        elif action_type == "reflection":
            handler = getattr(self, "_act_reflect", None)
            reflection = handler() if handler else None
            action = (reflection or {}).get("text") or action
        elif action_type == "ask_user":
            handler = getattr(self, "_act_ask_user", None)
            asked = (handler(target=selected_target) if selected_target else handler()) if handler else None
            topic = (asked or {}).get("target") or ""
            action = (asked or {}).get("text") or action
        elif action_type == "communicate":
            handler = getattr(self, "_act_communicate", None)
            told = handler() if handler else None
            action = (told or {}).get("text") or action
        elif action_type == "web_search":
            handler = getattr(self, "_act_web_search", None)
            found = handler() if handler else None
            topic = (found or {}).get("target") or ""
            action = (found or {}).get("text") or action
        elif action_type == "hypothesis":
            handler = getattr(self, "_act_hypothesis", None)
            guess = handler() if handler else None
            topic = (guess or {}).get("target") or ""
            action = (guess or {}).get("text") or action
        elif action_type == "set_own_goal":
            handler = getattr(self, "_act_set_own_goal", None)
            own = handler() if handler else None
            topic = (own or {}).get("target") or ""
            action = (own or {}).get("text") or action

        # === Замыкание петли: что изменилось в мире? ===
        # Не обязательно: act() используется и в лёгких тестовых объектах.
        loop_closer = getattr(self, "loop_closer", None)
        outcome = None
        if loop_closer is not None:
            outcome = loop_closer.observe_agent_action(
                self, action_type, world_before, topic=topic
            )
            self._last_action_outcome = outcome

        if outcome is not None and outcome.had_effect:
            get_logger().log(
                f"[LOOP] {action_type} дал результат: {outcome.delta.summary()}"
            )
            # Прогресс цели засчитывается по доказанному результату, а не
            # по факту «пошевелился». Тема — то, над чем шла работа.
            if topic:
                credit = self._check_goal_progress(
                    topic, answered=True, evidence=outcome.delta
                )
                outcome_credit = credit.get("pct", 0)
                if outcome_credit:
                    get_logger().log(
                        f"[LOOP] Цель: {outcome_credit}% после '{topic}'"
                    )
        else:
            streak = (
                loop_closer.no_effect_streak(action_type)
                if loop_closer is not None
                else 0
            )
            if streak >= 2:
                get_logger().log(
                    f"[LOOP] {action_type} без результата "
                    f"({streak} раз подряд)"
                )

        # === Тело: прожить такт ===
        # Ровно один раз за действие, после того как оно выполнено.
        # Нагрузка зависит от типа: тяжёлая работа утомляет, отдых
        # восстанавливает. Отказы обрабатываются отдельно, до обработчика.
        # Модульная функция, а не метод: act() работает и в лёгких
        # объектах без тела (тесты бюджета, заглушки).
        step_body(self, action_type, performed=True)
        if expectations is not None:
            observation = expectations.finish(
                self.mental_models, expectation_trial, float(self.energy),
                fatigue_after=getattr(getattr(getattr(self, "interoception", None), "state", None), "fatigue", None),
            )
            if observation is not None:
                get_logger().log(
                    f"[EXPECTATION] {action_type}: delta={observation['delta']:.3f}, "
                    f"matched={observation['prediction_matched']}"
                )

        # === Мотивация: результат действия (P1.2 Valence Feedback) ===
        if hasattr(self, 'motivation_system'):
            # Успех — это факт исполнения, а не остаток энергии. Раньше
            # здесь стояло `self.energy > 10`: усталый агент не мог
            # удовлетворить ни одну потребность, любое действие считалось
            # неуспешным, и голод только рос — отсюда бесконечные вопросы.
            # Отказы (усталость, бюджет) выходят из act() раньше и сюда не
            # доходят. Качество исхода передаётся отдельно, в valence.
            success = action_type not in ("default", "wait")
            # Compute actual valence from result
            valence_context = {"energy": self.energy, "max_energy": getattr(self, "_legacy_energy", 150)}
            actual_valence = self.motivation_system.compute_actual_valence(
                action_type, action, success, valence_context
            )
            # Учебное действие, которое ничего не изменило в мире, не
            # должно удовлетворять любопытство. Раньше «изучил, но не
            # нашёл» получало положительную валентность (в тексте нет
            # слова error), и потребность закрывалась впустую — агент
            # «учился» вечно и никогда не шёл спрашивать.
            if (
                loop_closer is not None
                and outcome is not None
                and loop_closer.is_productive(action_type)
                and not outcome.had_effect
            ):
                actual_valence = min(actual_valence, -0.2)
            if action_type == "create_draft" and creative_choice[0] == "leave":
                actual_valence = 0.0
            self.motivation_system.on_action_result(action_type, success, actual_valence)
            get_logger().log(f"[ACT VALENCE] {action_type}: success={success}, valence={actual_valence:.3f}")
        elif hasattr(self, 'internal_motivation'):
            # Fallback to legacy internal_motivation
            success = self.energy > 10
            valence = 0.3 if success else -0.2
            self.internal_motivation.on_action_result(action_type, success, valence)
        
        # === Отслеживаем использование концепций (для забывания) ===
        if decision and isinstance(decision, str):
            self._concept_usage_count[decision] = self._concept_usage_count.get(decision, 0) + 1
        
        # gc.collect() периодически для контроля памяти
        if self.cycle_count % SIM_CONFIG.GC_INTERVAL == 0:
            gc.collect()
        
        return action

    # ============================================================
    # ДЕЙСТВИЯ, КОТОРЫЕ МЕНЯЮТ МИР (замыкание петли)
    # ============================================================

    def _social_candidates(self, cycle: int) -> List[Dict]:
        """Кандидаты на общение: спросить, рассказать, поискать.

        Почему это отдельный источник, а не только мотивация: у общения
        есть собственные наблюдаемые признаки, не сводимые к уровню
        потребности. Потребность «связь» может быть удовлетворена
        недавним разговором, но незакрытый вопрос всё равно стоит того,
        чтобы попросить помощи. Здесь общение встроено в выбор напрямую —
        по реальным признакам, а не по декларации.

        Признаки честные и проверяемые:
        * есть открытый вопрос, который агент давно не может закрыть сам;
        * агент давно ничего не говорил человеку;
        * есть тема без собственной формулировки, а поиск доступен.
        """
        candidates: List[Dict] = []
        interaction = getattr(self, "user_interaction", None)

        # 1. Незакрытый вопрос — попросить помощи у человека.
        # Предлагаем только если вопрос РАЗРЕШЕНО задать: иначе кандидат
        # выигрывает арбитраж, упирается в кулдаун и сжигает цикл впустую.
        questions = getattr(self, "_open_questions", None)
        if (
            interaction is not None
            and isinstance(questions, list)
            and self._can_ask_now(cycle)
        ):
            for item in questions:
                if not isinstance(item, dict) or item.get("answered"):
                    continue
                explored = len(item.get("explorations") or [])
                limit = int(item.get("max_explorations") or 5)
                # Агент уже пробовал сам и не смог — время спросить.
                if explored >= max(1, limit - 1):
                    candidates.append({
                        "source": "social",
                        "action": "ask_user",
                        "strength": self._dampen("ask_user", 0.78),
                        "params": {"topic": item.get("text", "")},
                    })
                    break

        # 2. Давно молчал — рассказать, что узнал.
        if interaction is not None:
            silence = int(
                getattr(LR_CONFIG, "SOCIAL_SILENCE_CYCLES", 40) or 40
            )
            last = getattr(self, "_last_share_cycle", None)
            if last is None:
                last = 0
            if cycle - int(last) >= silence and self._compose_share_message():
                candidates.append({
                    "source": "social",
                    "action": "communicate",
                    "strength": self._dampen("communicate", 0.72),
                    "params": {},
                })

        # 3. Тема без своей формулировки — поискать в сети.
        searcher = getattr(self, "web_searcher", None)
        if searcher is not None and getattr(searcher, "is_enabled", False):
            concepts = getattr(self.mental_models, "concepts", None)
            if isinstance(concepts, dict):
                for name, node in concepts.items():
                    if not self._is_learnable(name):
                        continue
                    if len(str(getattr(node, "definition_hypothesis", "") or "")) > 10:
                        continue
                    if len(getattr(node, "experiences", []) or []) < 1:
                        continue
                    candidates.append({
                        "source": "social",
                        "action": "web_search",
                        "strength": self._dampen("web_search", 0.6),
                        "params": {"topic": name},
                    })
                    break

        return candidates

    def _is_action_available(self, action: Optional[str]) -> bool:
        """Можно ли выполнить действие прямо сейчас.

        Проверяются только те ограничения, которые заведомо откажут:
        кулдаун вопроса, выключенный поиск и нехватка энергии. Остальное
        решается в ``act()`` и записывается как исход.

        Нехватка энергии добавлена потому, что отказ — это не выбор, а
        пустой цикл. Замер до правки: 243 отказа «too_tired» на 400
        попыток, при этом арбитр каждый раз выбирал действие, которое
        тело выполнить не могло. Дешевле не предлагать невозможное.
        """
        normalized = self._normalize_action(action)
        if normalized == "create_draft":
            from src.cognition.creative_draft import draft_available

            return self._is_action_affordable(normalized) and draft_available(getattr(self, "_creative_draft", None))
        if normalized == "ask_user":
            return self._can_ask_now(self.cycle_count) and self._has_question_target()
        if normalized == "web_search":
            searcher = getattr(self, "web_searcher", None)
            if searcher is None:
                return False
            return bool(getattr(searcher, "is_enabled", False))
        if normalized == "decomposition":
            # Декомпозиция полезна только пока есть что разложить и куда
            # положить результат: под-вопросы идут в очередь, а она не
            # резиновая. Раньше действие предлагалось всегда и в
            # большинстве случаев заканчивалось «не разбивается на части» —
            # гарантированный пустой цикл.
            return (
                self._decomposition_has_room()
                and self._pick_decomposable_target(remember=False) is not None
            )
        return self._is_action_affordable(normalized)

    def _is_candidate_available(self, candidate) -> bool:
        from src.cognition.intention_payload import intention_target

        try:
            target = intention_target(candidate)
            if self._normalize_action(candidate.get("action")) == "create_draft":
                from src.cognition.creative_catalog import creative_request, catalog_for
                from src.cognition.creative_draft import LIMIT, MAX_DRAFTS, draft_available

                mode, identifier, _ = creative_request(candidate)
                catalog = catalog_for(self)
                if identifier is not None and identifier not in catalog:
                    return False
                if mode == "leave":
                    selected = catalog.get(identifier) if identifier else getattr(self, "_creative_draft", None)
                    return bool(selected and selected.get("status", "active") == "active"
                                and self._is_action_affordable("create_draft"))
                if mode == "new":
                    return len(catalog) < MAX_DRAFTS and draft_available(None) and self._is_action_affordable("create_draft")
                if identifier is not None and mode == "continue":
                    selected = catalog[identifier]
                    return (selected.get("status", "active") == "active" and selected["revision"] < LIMIT
                            and self._is_action_affordable("create_draft"))
        except ValueError:
            return False
        action = self._normalize_action(candidate.get("action"))
        if target is not None:
            if not self._is_learnable(target):
                return False
            if action == "decomposition":
                if not self._decomposition_has_room():
                    return False
                parts = self._decompose_query(target) or []
                if len(parts) < 2:
                    return False
                return self._is_action_affordable(action)
            if action == "ask_user":
                return self._can_ask_now(self.cycle_count) and self._is_action_affordable(action)
        return self._is_action_available(candidate.get("action"))

    def _decomposition_has_room(self) -> bool:
        """Есть ли место в очереди открытых вопросов для под-вопросов."""
        limit = int(
            getattr(LR_CONFIG, "OPEN_QUESTIONS_MAX_UNANSWERED", 3) or 0
        )
        if limit <= 0:
            return False
        try:
            questions = self.get_open_questions()
        except Exception:
            return False
        unanswered = sum(1 for q in questions if not q.get("answered"))
        return unanswered < limit

    def _stuck_fallback(self) -> str:
        """Что делать, когда все кандидаты оказались тупиковыми.

        Раньше здесь всегда был ``think_decompose`` — причём это же
        действие чаще всего и было тупиковым. То есть запасной выход вёл
        обратно в тот же тупик.

        Порядок: отдых, если тело требует; иначе продуктивное действие с
        доказанной историей эффекта, которое сейчас выполнимо и не в
        тупике. Если такого нет — отдых: он хотя бы восстанавливает тело,
        вместо того чтобы делать вид, что агент работает.
        """
        if self._body_needs_rest() or self._is_resting():
            return "deep_rest"

        closer = getattr(self, "loop_closer", None)
        if closer is not None:
            proven = sorted(
                closer.effective_actions(),
                key=lambda name: -closer.effect_count(name),
            )
            for name in proven:
                if not closer.is_productive(name):
                    continue
                if closer.is_stuck(name):
                    continue
                if not self._is_action_available(name):
                    continue
                return name
        return "deep_rest"

    def _release_recovered_denials(self) -> None:
        """Снимает пометку «тупик» с действий, которые снова по карману.

        Отказ по усталости — факт о теле, а не о действии. Пока энергия не
        вернулась, повторять бессмысленно; когда вернулась — запрет должен
        исчезнуть сам, иначе отдых не возвращает агента к работе.
        """
        closer = getattr(self, "loop_closer", None)
        if closer is None:
            return
        for action in closer.stuck_actions():
            if not closer.denied_streak(action):
                continue
            if self._is_action_affordable(action):
                closer.reset_denial(action)

    def _has_question_target(self) -> bool:
        """Есть ли о чём спросить человека прямо сейчас.

        Проверка без побочных эффектов (в отличие от
        ``_pick_exploration_target``, который запоминает тему). Нужна,
        чтобы не предлагать арбитру вопрос, который заведомо закончится
        «не о чем спрашивать»: иначе действие выбирается каждый цикл,
        ничего не меняет и не запускает кулдаун, потому что вопрос так и
        не был задан.
        """
        questions = getattr(self, "_open_questions", None)
        if isinstance(questions, list):
            for item in questions:
                if not isinstance(item, dict) or item.get("answered"):
                    continue
                if str(item.get("text") or "").strip():
                    return True

        history = getattr(self, "_exploration_history", None)
        recently = set(history) if isinstance(history, list) else set()

        concepts = getattr(self.mental_models, "concepts", None)
        if isinstance(concepts, dict):
            for name, node in concepts.items():
                if not self._is_learnable(name):
                    continue
                if float(getattr(node, "confidence", 0.0) or 0.0) < 0.9:
                    return True
            known = set(concepts)
        else:
            known = set()

        for topic in self._stimulus_topics():
            if topic not in known and topic not in recently:
                return True
        return False

    def _can_ask_now(self, cycle: int) -> bool:
        """Можно ли сейчас задать вопрос человеку (кулдаун и лимиты)."""
        interaction = getattr(self, "user_interaction", None)
        checker = getattr(interaction, "can_ask_question", None)
        if checker is None:
            return False
        try:
            return bool(checker(cycle))
        except Exception:
            return False

    def _dampen(self, action: str, strength: float) -> float:
        """Снижает силу кандидата, если действие подряд не давало эффекта.

        Иначе действие, которое сейчас невозможно (кулдаун, нет сети),
        выигрывает арбитраж каждый цикл и сжигает жизнь впустую. Каждая
        неудача вдвое снижает шанс: 0.78 → 0.39 → 0.20 → …
        """
        closer = getattr(self, "loop_closer", None)
        if closer is None:
            return strength
        try:
            streak = closer.no_effect_streak(action)
        except Exception:
            return strength
        return strength * (0.5 ** max(0, streak))

    def _record_denied(self, action_type: str, world_before, reason: str) -> None:
        """Совместимость: см. модульную ``record_denied_outcome``."""
        record_denied_outcome(self, action_type, world_before, reason)

    def _normalize_action(self, action: Optional[str]) -> str:
        """Приводит имя действия к типу (как в ``act()``).

        Мотивация и Active Inference называют одно и то же действие
        по-разному: «exploration» / «explore», «reflection» / «reflect».
        Счётчики петель должны видеть один тип, иначе проверка тупика
        смотрит не на то имя.
        """
        key = str(action or "").strip().lower()
        if not key:
            return ""
        return self.ACTION_ALIASES.get(key, key)

    def _is_learnable(self, name: str) -> bool:
        """Годится ли концепция как тема для изучения и вопросов.

        Служебные узлы (``_bootstrap_loaded``) и врождённые убеждения
        (``убеждение_1``) — не темы для исследования: спрашивать человека
        про «_bootstrap_loaded» бессмысленно, а «изучать» собственный
        маркер загрузки — имитация работы.
        """
        text = str(name or "").strip()
        if not text:
            return False
        if text.startswith("_"):
            return False
        if text.startswith("убеждение_"):
            return False
        return True

    def _pick_shallow_concept(self, concepts: Dict) -> Optional[str]:
        """Неуверенная тема вне текущего круга: формулировка ещё не знание.

        Это только кандидат на исследование, не обязательство закрыть
        пробел. Доля углубления и арбитр по-прежнему допускают иной выбор.
        """
        if not isinstance(concepts, dict):
            return None
        recently = set(getattr(self, "_exploration_history", []) or [])
        candidates = []
        for name, node in concepts.items():
            if not self._is_learnable(name) or name in recently:
                continue
            experiences = len(getattr(node, "experiences", []) or [])
            confidence = float(getattr(node, "confidence", 0.0))
            if experiences < 1 or confidence > 0.4:
                continue
            candidates.append((experiences, name))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], -len(item[1])))
        return candidates[0][1]

    def _pick_exploration_target(self) -> Optional[str]:
        """Выбирает, что исследовать: то, чего агент ещё не изучал.

        Порядок приоритетов:
        1. Открытый вопрос без ответа — человек его задал, это важно.
        2. Иногда — возврат к уже встреченной теме (углубление): без этого
           агент только расширял охват, а собственная формулировка требует
           вернуться к теме минимум дважды.
        3. Неизвестная тема из пула стимулов: агент идёт в неизвестное,
           а не пережёвывает известное.
        4. Концепция с наименьшей уверенностью, ещё не изученная в этом
           круге.

        Важно: цель не повторяется, пока не исчерпан круг. Иначе агент
        «изучает» одну и ту же концепцию, ничего не узнаёт (уверенность не
        растёт без новой информации) и застревает — именно это и
        происходило до замыкания петли.

        Returns:
            Название темы или ``None``, если исследовать нечего.
        """
        history = getattr(self, "_exploration_history", None)
        if not isinstance(history, list):
            history = []
            self._exploration_history = history
        recently = set(history)
        concepts = getattr(self.mental_models, "concepts", None)

        # 1. Открытые вопросы
        questions = getattr(self, "_open_questions", None)
        if isinstance(questions, list):
            for item in questions:
                if not isinstance(item, dict):
                    continue
                if item.get("answered"):
                    continue
                text = str(item.get("text") or "").strip()
                if text and text not in recently:
                    self._remember_exploration(text)
                    return text

        # 2. Иногда возвращаемся к теме, чтобы углубить её.
        # Проверяем ДО поиска новых тем: иначе при непустом пуле стимулов
        # глубина не наступала бы никогда — агент только расширял охват,
        # у каждой концепции оставалась одна встреча, а собственная
        # формулировка требует минимум двух.
        depth_ratio = float(
            getattr(LR_CONFIG, "EXPLORATION_DEPTH_RATIO", 0.35) or 0.0
        )
        if depth_ratio > 0 and random.random() < depth_ratio:
            shallow = self._pick_shallow_concept(concepts)
            if shallow is not None:
                self._remember_exploration(shallow)
                return shallow

        # 3. Неизвестная тема из пула стимулов
        known = set(concepts) if isinstance(concepts, dict) else set()
        for topic in self._stimulus_topics():
            if topic in known or topic in recently:
                continue
            self._remember_exploration(topic)
            return topic

        # 4. Слабая концепция, ещё не тронутая в этом круге
        if not isinstance(concepts, dict) or not concepts:
            return None

        def weakness(node) -> tuple:
            confidence = float(getattr(node, "confidence", 0.0) or 0.0)
            experiences = len(getattr(node, "experiences", []) or [])
            return (confidence, experiences)

        fresh = [
            name
            for name in concepts
            if name not in recently
            and self._is_learnable(name)
            and float(getattr(concepts[name], "confidence", 0.0) or 0.0) < 0.9
        ]
        if not fresh:
            # Круг исчерпан: начинаем заново, но теперь это осознанный
            # повторный визит, а не топтание на месте.
            history.clear()
            fresh = [
                name
                for name in concepts
                if self._is_learnable(name)
                and float(getattr(concepts[name], "confidence", 0.0) or 0.0) < 0.9
            ]
        if not fresh:
            return None

        target = min(fresh, key=lambda name: weakness(concepts[name]))
        self._remember_exploration(target)
        return target

    def _decomposable_targets(self) -> List[str]:
        """Кандидаты на декомпозицию в порядке приоритета, без побочных эффектов.

        Отдельный список, потому что у декомпозиции другое требование, чем
        у исследования: ей нужно не «что угодно неизученное», а «то, что
        делится на части». Раньше она брала первую попавшуюся цель и в
        большинстве случаев возвращала «не разбивается на части» — цикл
        потрачен, мир не изменился.
        """
        targets: List[str] = []

        questions = getattr(self, "_open_questions", None)
        if isinstance(questions, list):
            for item in questions:
                if not isinstance(item, dict) or item.get("answered"):
                    continue
                text = str(item.get("text") or "").strip()
                if text:
                    targets.append(text)

        concepts = getattr(self.mental_models, "concepts", None)
        known = set(concepts) if isinstance(concepts, dict) else set()
        for topic in self._stimulus_topics():
            if topic not in known:
                targets.append(topic)

        if isinstance(concepts, dict):
            for name in concepts:
                if not self._is_learnable(name):
                    continue
                confidence = float(
                    getattr(concepts[name], "confidence", 0.0) or 0.0
                )
                if confidence < 0.9:
                    targets.append(name)

        # Порядок важен: первый разложимый — самый приоритетный.
        return list(dict.fromkeys(targets))

    def _pick_decomposable_target(self, remember: bool = True) -> Optional[str]:
        """Первая тема, которую действительно есть на что разложить."""
        for target in self._decomposable_targets():
            try:
                parts = self._decompose_query(target)
            except Exception:
                continue
            if not parts:
                continue
            if remember:
                self._remember_exploration(target)
            return target
        return None

    def _stimulus_topics(self) -> List[str]:
        """Темы из пула стимулов, приведённые к виду концепций."""
        pool = getattr(LR_CONFIG, "STIMULI_POOL", None) or []
        topics = []
        for raw in pool:
            text = str(raw).strip()
            if not text:
                continue
            # «вопрос: что такое время» → «что такое время»
            if ":" in text:
                text = text.split(":", 1)[1].strip()
            if text:
                topics.append(text)
        return topics

    def _remember_exploration(self, target: str) -> None:
        """Запоминает изученную тему, чтобы не брать её снова подряд."""
        history = getattr(self, "_exploration_history", None)
        if not isinstance(history, list):
            history = []
            self._exploration_history = history
        if target in history:
            history.remove(target)
        history.append(target)
        # Ограничиваем память: помним только последний круг.
        limit = max(10, int(getattr(LR_CONFIG, "EXPLORATION_HISTORY_SIZE", 200)))
        if len(history) > limit:
            del history[: len(history) - limit]

    def leave_creative_draft(self, reason: str) -> Dict:
        state = getattr(self, "_creative_draft", None)
        if state is None:
            return {"status": "not_found"}
        from src.cognition.creative_catalog import perform_creative

        perform_creative(self, "leave", state["id"], reason)
        return {"status": "left", "draft_id": state["id"]}

    def list_creative_drafts(self) -> List[Dict]:
        from src.cognition.creative_catalog import catalog_for

        catalog = catalog_for(self)
        return [catalog[identifier] for identifier in sorted(catalog)]

    def _act_explore(self, target=None) -> Dict:
        """Исследование как работа, а не как счётчик.

        Раньше ``act("explore")`` попадал в тип «default»: энергия
        списывалась, строка возвращалась, мир не менялся. Отсюда бралось
        зацикливание — агенту не за что было зацепиться, чтобы сменить
        действие.

        Теперь исследование выбирает конкретную тему и прогоняет её через
        мышление: появляется гипотеза, запись в ментальных моделях или
        ответ из сети. Это наблюдаемый результат.
        """
        target = str(target).strip() if target is not None else self._pick_exploration_target()
        if not target or not self._is_learnable(target):
            return {
                "target": "",
                "text": "Ответ: исследовать нечего — все концепции уверены",
            }

        try:
            thought = self.think(f"вопрос: {target}")
        except Exception as exc:
            get_logger().log(f"[EXPLORE] ошибка мышления по '{target}': {exc}")
            return {
                "target": target,
                "text": f"Ответ: попытался изучить '{target}', но не смог: {exc}",
            }

        short = str(thought).replace("\n", " ")[:100]
        return {
            "target": target,
            "thought": thought,
            "text": f"Ответ: изучил '{target}' — {short}",
        }

    def _act_decompose(self, target=None) -> Dict:
        """Разбирает слабую концепцию на под-вопросы и сохраняет их.

        Декомпозиция — работа: она создаёт новые темы, с которыми агент
        столкнётся в следующих циклах. Раньше под-вопросы вычислялись,
        попадали в текст ответа и терялись: мир не менялся, действие
        считалось бесплодным, попадало в тупики — и при этом служило
        запасным вариантом выхода из тупика. Агент тратил циклы на
        действие, которое по построению ничего не делало (в замере —
        115–162 выбора за 500 циклов).
        """
        target = str(target).strip() if target is not None else self._pick_decomposable_target()
        if not target or not self._is_learnable(target):
            return {"target": "", "text": "Ответ: разбирать нечего"}

        try:
            parts = self._decompose_query(target) or []
        except Exception as exc:
            get_logger().log(f"[DECOMPOSE] ошибка для '{target}': {exc}")
            parts = []

        if not parts:
            return {
                "target": target,
                "text": f"Ответ: '{target}' не разбивается на части",
            }

        queued = self._queue_sub_questions(parts)
        suffix = (
            f"; в очередь вопросов +{queued}" if queued else ""
        )
        return {
            "target": target,
            "parts": list(parts)[:5],
            "queued": queued,
            "text": (
                f"Ответ: разобрал '{target}' на {len(parts)} частей: "
                + "; ".join(str(p) for p in parts[:3])
                + suffix
            ),
        }

    def _queue_sub_questions(self, parts) -> int:
        """Ставит под-вопросы в очередь открытых вопросов.

        Ограничения те же, что в ``thinking_pipeline``: не больше
        ``OPEN_QUESTIONS_MAX_UNANSWERED`` неотвеченных, по одной попытке
        размышления на под-вопрос и без дублей. Иначе декомпозиция
        вытеснила бы всё остальное из очереди.

        Returns:
            Сколько вопросов реально добавлено.
        """
        ask = getattr(self, "ask_user", None)
        if not callable(ask):
            return 0
        limit = int(getattr(LR_CONFIG, "OPEN_QUESTIONS_MAX_UNANSWERED", 3) or 0)
        try:
            existing = self.get_open_questions()
        except Exception:
            existing = []
        unanswered = sum(1 for q in existing if not q.get("answered"))
        known = {
            str(q.get("text", "")).strip().lower() for q in existing
        }

        added = 0
        for part in parts:
            if unanswered + added >= limit:
                break
            text = str(part or "").strip()
            key = text.lower()
            if not text or key in known or "стратегия=" in key:
                continue
            try:
                result = ask(
                    text, source="decomposition", max_explorations=1
                )
            except Exception as exc:
                get_logger().log(
                    f"[DECOMPOSE] не удалось поставить '{text[:40]}': {exc}"
                )
                continue
            if result.get("status") == "queued":
                added += 1
                known.add(key)
        return added

    def _act_synthesize(self, target=None) -> Dict:
        """Синтез: попытка собрать определение из уже известных связей.

        Использует ментальные модели. Если определение уже есть —
        усиливает уверенность через новый опыт.
        """
        target = target if target is not None else self._pick_exploration_target()
        if not target or not self._is_learnable(target):
            return {"target": "", "text": "Ответ: синтезировать нечего"}

        # Сначала — связи, подкреплённые свидетельствами (вес выше порога):
        # их укрепляет сон, когда видит одну концепцию в формулировке
        # другой. Только если таких нет, смотрим широкий обход графа.
        #
        # Раньше здесь стоял вызов с именем ``max_depth``, а параметр
        # называется ``max_distance``: TypeError молча глотался, и синтез
        # всегда отвечал «нет связанных концепций». Действие при этом
        # считалось выполненным.
        names: list = []
        try:
            node = self.mental_models.concepts.get(target)
            if node is not None:
                names = [
                    item["concept"]
                    for item in node.get_related_concepts(0.3)
                    if item.get("concept") in self.mental_models.concepts
                ][:3]
        except Exception as exc:
            get_logger().log(f"[SYNTHESIS] ошибка связей '{target}': {exc}")
            names = []

        if not names:
            try:
                related = self.mental_models.find_related_concepts(
                    target, max_distance=2
                )
            except Exception:
                related = []
            # find_related_concepts возвращает ConceptNode, а не словари:
            # второй слой той же ошибки — оба вида обращений надо уметь.
            for item in related[:3]:
                name = (
                    item.get("concept")
                    if isinstance(item, dict)
                    else getattr(item, "name", None)
                )
                if name:
                    names.append(name)

        if not names:
            return {
                "target": target,
                "text": f"Ответ: для '{target}' нет связанных концепций",
            }

        hypothesis = (
            f"'{target}' можно понять через: " + ", ".join(str(n) for n in names)
        )
        try:
            self.mental_models.encounter_concept(
                target,
                f"синтез_цикл_{self.cycle_count}",
                hypothesis,
                evidence_kind="hypothesis", source="self:synthesis",
            )
        except Exception as exc:
            get_logger().log(f"[SYNTHESIS] не удалось записать: {exc}")

        return {
            "target": target,
            "text": f"Ответ: синтезировал '{target}' через {names}",
        }

    def _act_reflect(self) -> Dict:
        """Рефлексия как действие: обзор собственных паттернов."""
        try:
            reflection = self.reflect()
        except Exception as exc:
            get_logger().log(f"[REFLECTION] ошибка: {exc}")
            return {"text": f"Ответ: рефлексия не удалась: {exc}"}

        patterns = reflection.get("patterns") or []
        if not patterns:
            return {"text": "Ответ: рефлексия — новых паттернов нет"}
        first = patterns[0]
        description = str(first.get("description", ""))[:80]
        return {
            "text": (
                f"Ответ: заметил паттерн — {description} "
                f"(уверенность {float(first.get('confidence', 0)):.0%})"
            )
        }

    # ============================================================
    # ПРОВОДКА: действия, которые раньше ничего не делали
    # ============================================================

    def _act_ask_user(self, target=None) -> Dict:
        """Спросить человека о том, что агенту непонятно.

        До этой проводки действие ``ask_user`` (его предлагала мотивация
        как «ask_question») доходило до ``act()`` и молча заканчивалось:
        подсистема ``UserInteraction`` умеет задавать вопросы, публикует
        события, окно их показывает — но никто не вызывал её из петли.
        Агент «хотел спросить» и не спрашивал.

        Вопрос задаётся только по реальной нужде: берётся тема, в которой
        агент не уверен. Спрашивать о том, что уже знает, — шум.
        """
        interaction = getattr(self, "user_interaction", None)
        if interaction is None:
            return {"text": "Ответ: спросить некого — нет связи с человеком"}

        target = target if target is not None else self._pick_exploration_target()
        if not target or not self._is_learnable(target):
            return {"text": "Ответ: не о чем спрашивать — всё понятно"}

        question = (
            f"Я разбираюсь с темой «{target}» и пока не уверен, "
            f"что понимаю её правильно. Можешь объяснить своими словами?"
        )
        try:
            result = interaction.ask_user(
                question=question,
                context=f"самостоятельный вопрос по теме: {target}",
                cycle=self.cycle_count,
            )
        except Exception as exc:
            get_logger().log(f"[ASK] не удалось спросить: {exc}")
            return {"text": f"Ответ: хотел спросить про '{target}', но не смог"}

        if result.get("status") != "queued":
            # Лимит вопросов или пауза — это нормально, не ошибка.
            reason = result.get("reason", "не сейчас")
            return {
                "target": target,
                "text": f"Ответ: вопрос про '{target}' отложен ({reason})",
            }

        self._record_will("questions_asked", target, "самостоятельный вопрос")
        return {
            "target": target,
            "text": f"Ответ: спросил человека про '{target}'",
        }

    def _act_communicate(self) -> Dict:
        """Рассказать человеку что-то, что агент счёл важным.

        Действие ``communicate`` (мотивация: «поделиться знанием»,
        «ответить пользователю») раньше тоже ничего не делало.
        """
        interaction = getattr(self, "user_interaction", None)
        if interaction is None:
            return {"text": "Ответ: рассказать некому — нет связи с человеком"}

        message = self._compose_share_message()
        if not message:
            return {"text": "Ответ: нечего рассказать — нет новостей"}

        try:
            interaction.send_message(
                content=message,
                msg_type="statement",
                tone="casual",
                urgency=0.4,
                context="делюсь тем, что узнал",
                cycle=self.cycle_count,
            )
        except Exception as exc:
            get_logger().log(f"[COMMUNICATE] не удалось отправить: {exc}")
            return {"text": f"Ответ: хотел рассказать, но не смог: {exc}"}

        self._record_will("messages_sent", "share", "делюсь знанием")
        self._last_share_cycle = self.cycle_count
        return {"text": f"Ответ: рассказал человеку: {message[:60]}"}

    def _compose_share_message(self) -> str:
        """Текст сообщения: о самом свежем или самом слабом знании.

        Берём то, что агент недавно узнал и в чём уже уверен: делиться
        догадкой, которую сам не проверил, — нечестно.
        """
        concepts = getattr(self.mental_models, "concepts", None)
        if not isinstance(concepts, dict) or not concepts:
            return ""

        # Предпочитаем концепции с собственной формулировкой.
        candidates = [
            (name, node)
            for name, node in concepts.items()
            if len(str(getattr(node, "definition_hypothesis", "") or "")) > 10
            and not name.startswith(("_", "убеждение_"))
        ]
        if not candidates:
            return ""

        name, node = max(
            candidates,
            key=lambda item: getattr(item[1], "last_updated", None) or 0,
            default=(None, None),
        )
        if not name:
            return ""
        definition = str(getattr(node, "definition_hypothesis", ""))[:200]
        return f"Я разобрался с темой «{name}»: {definition}"

    def _act_web_search(self) -> Dict:
        """Найти в сети то, чего нет в своей памяти.

        Действие ``web_search`` предлагалось мотивацией, но не
        исполнялось. При этом ``WebSearcher`` уже был подключён к
        мышлению — не хватало только вызова из петли.
        """
        searcher = getattr(self, "web_searcher", None)
        if searcher is None or not getattr(searcher, "is_enabled", False):
            return {
                "text": "Ответ: поиск в сети недоступен или выключен"
            }

        target = self._pick_exploration_target()
        if not target:
            return {"text": "Ответ: искать нечего — нет темы"}

        try:
            result = searcher.search(target)
        except Exception as exc:
            get_logger().log(f"[WEB] поиск упал: {exc}")
            return {
                "target": target,
                "text": f"Ответ: поиск по '{target}' не удался",
            }

        if not result.get("found"):
            reason = result.get("error") or "не найдено"
            return {
                "target": target,
                "text": f"Ответ: в сети про '{target}' ничего ({reason})",
            }

        extract = str(result.get("extract") or "")
        title = str(result.get("title") or target)
        if not extract:
            return {
                "target": target,
                "text": f"Ответ: нашёл '{title}', но без содержания",
            }

        # Сохраняем как знание: без записи поиск ничего не изменил бы.
        try:
            from src.memory.knowledge_quality import check_entry

            if check_entry(target, extract):
                return {
                    "target": target,
                    "text": f"Ответ: результат по '{target}' отклонён как слабый",
                }
            self.knowledge_base[target] = extract
            self._known_definitions[target] = extract
            self._save_knowledge_base()
        except Exception as exc:
            get_logger().log(f"[WEB] не удалось сохранить: {exc}")
            return {
                "target": target,
                "text": f"Ответ: нашёл '{title}', но не сохранил",
            }

        self._record_will("web_searches", target, f"нашёл в сети: {title}")
        return {
            "target": target,
            "text": f"Ответ: нашёл в сети «{title}» про '{target}'",
        }

    def _act_hypothesis(self) -> Dict:
        """Выдвинуть гипотезу о теме, в которой агент не уверен.

        Мотивация предлагает это действие («Понять: {concept}»), но
        раньше оно уходило в «default»: агент «выдвигал гипотезу» и
        ничего не происходило. Гипотеза — это запись в ментальной модели,
        то есть наблюдаемое изменение.
        """
        target = self._pick_exploration_target()
        if not target:
            return {"text": "Ответ: гипотезу выдвигать не о чем"}

        try:
            hypothesis = self._generate_hypothesis(target)
        except Exception as exc:
            get_logger().log(f"[HYPOTHESIS] ошибка для '{target}': {exc}")
            hypothesis = None

        if not hypothesis:
            return {
                "target": target,
                "text": f"Ответ: про '{target}' пока не из чего строить гипотезу",
            }

        text = str(hypothesis.get("text") or "")
        confidence = float(hypothesis.get("confidence") or 0.0)
        try:
            self.mental_models.encounter_concept(
                target,
                f"гипотеза_цикл_{self.cycle_count}",
                text[:80],
                evidence_kind="hypothesis", source="self:hypothesis",
            )
        except Exception as exc:
            get_logger().log(f"[HYPOTHESIS] не удалось записать: {exc}")

        return {
            "target": target,
            "text": (
                f"Ответ: гипотеза о '{target}' — {text[:70]} "
                f"(уверенность {confidence:.0%})"
            ),
        }

    def _act_set_own_goal(self) -> Dict:
        """Поставить себе цель по своей воле.

        Мотивация предлагает «Поставить свою цель» (autonomy). Раньше
        действие ничего не делало. Цель — наблюдаемое изменение: она
        появляется в списке и начинает влиять на жизнь.
        """
        motivation = getattr(self, "motivation_system", None)
        play_need = motivation.needs.get("play") if motivation is not None else None
        if play_need is not None and play_need.is_pressing():
            activity = "play" if random.random() < 0.5 else "creative_act"
            title = "Сыграть партию" if activity == "play" else "Создать текстовую композицию"
            if any(g.get("title") == title and g.get("status") != "completed" for g in self.goals):
                return {"text": f"Ответ: дело '{title}' уже есть"}
            goal_id = self.set_goal(title, difficulty=1)
            from src.cognition.activity_goals import attach_activity

            attach_activity(self, goal_id, {"source": "self", "need": "play", "action_hint": activity})
            self._record_will("goals_set", title, f"своё дело #{goal_id}")
            return {"text": f"Ответ: выбрал дело '{title}' (#{goal_id})"}
        target = self._pick_exploration_target()
        if not target:
            return {"text": "Ответ: свою цель ставить не из чего"}

        title = f"Понять: {target}"
        # Не дублируем уже существующую цель.
        for goal in getattr(self, "goals", []) or []:
            if str(goal.get("title", "")).lower() == title.lower():
                return {
                    "target": target,
                    "text": f"Ответ: цель '{title}' уже есть",
                }

        try:
            goal_id = self.set_goal(title, difficulty=1)
        except Exception as exc:
            get_logger().log(f"[OWN_GOAL] не удалось поставить цель: {exc}")
            return {
                "target": target,
                "text": f"Ответ: хотел поставить цель '{title}', но не смог",
            }

        self._record_will("goals_set", target, f"своя цель #{goal_id}")
        return {
            "target": target,
            "text": f"Ответ: поставил себе цель '{title}' (#{goal_id})",
        }

    def _record_will(self, will_type: str, topic: str, reason: str) -> None:
        """Записывает действие в журнал воли, если он есть.

        Журнал переживает перезапуск и служит доказательством эффекта:
        без записи дельта мира не увидела бы, что сообщение отправлено
        или вопрос задан.
        """
        registry = getattr(self, "will_registry", None)
        if registry is None:
            return
        try:
            registry.record(
                will_type, topic, reason,
                outcome="executed", cycle=self.cycle_count,
            )
        except Exception:
            pass

    def perform_forgetting(self):
        """Приоритетное забывание неиспользуемых концепций с низкой уверенностью."""
        if not LR_CONFIG.FORGETTING_ENABLED:
            return
        
        # Проверяем, пора ли забывать
        if self.cycle_count % LR_CONFIG.FORGETTING_INTERVAL != 0:
            return
        
        # Находим концепции для забывания (низкая уверенность + мало использования)
        to_remove = []
        for concept_name, node in list(self.mental_models.concepts.items()):
            if node.confidence < LR_CONFIG.MIN_CONFIDENCE_FOR_RETENTION:
                usage = self._concept_usage_count.get(concept_name, 0)
                if usage <= 1:  # Использовалась 0-1 раз
                    to_remove.append(concept_name)
        
        # Не забываем больше MAX_FORGET_PCT концепций за раз
        max_forget = int(len(self.mental_models.concepts) * LR_CONFIG.MAX_FORGET_PCT / 100)
        if len(to_remove) > max_forget:
            to_remove = to_remove[:max_forget]
        
        if to_remove:
            for name in to_remove:
                del self.mental_models.concepts[name]
                self._concept_usage_count.pop(name, None)
            get_logger().flush_immediate(
                f"🧠 Приоритетное забывание: -{len(to_remove)} концепций (низкая уверенность)"
            )
    
    def _reward_creative_success(self):
        """Поощряет креативный успех."""
        self._creative_wins += 1
        if self._creative_wins >= 5:  # Каждые 5 успешных креативных действий
            self.energy += LR_CONFIG.CREATIVITY_BONUS_ENERGY * 2
            get_logger().flush_immediate(f"🎨 Креативность окупилась! +{LR_CONFIG.CREATIVITY_BONUS_ENERGY * 2} энергии")
            self._creative_wins = 0
    
    def _record_creative_failure(self):
        """Записывает неудачу креативного действия."""
        self._creative_losses += 1
        if self._creative_losses >= 3:
            # Если слишком много неудач — снижаем ε (меньше случайности)
            LR_CONFIG.EPSILON_GREEDY = max(0.05, LR_CONFIG.EPSILON_GREEDY - 0.02)
            get_logger().log(f"Снижаю ε-greedy до {LR_CONFIG.EPSILON_GREEDY:.0%} (слишком много неудач)")
            self._creative_losses = 0

    # === Прунинг knowledge_base (вызывается из __init__ и save_state) ===
    def _prune_knowledge_base(self) -> None:
        """Удаляет некачественные записи, затем прунит до лимита.

        Фильтр качества лечит базу, даже если мусор пришёл из старого
        чекпоинта или файла: запись не переживёт ближайшее сохранение.
        """
        _, removed = clean_knowledge_base(self.knowledge_base)
        if removed:
            for key in removed:
                self.knowledge_base.pop(key, None)
            preview = "; ".join(
                f"'{key}' ({REASON_TITLES.get(reason, reason)})"
                for key, reason in list(removed.items())[:5]
            )
            suffix = "" if len(removed) <= 5 else f" и ещё {len(removed) - 5}"
            get_logger().log(
                f"KB: удалено некачественных записей: {len(removed)} — {preview}{suffix}"
            )

        max_kb = SIM_CONFIG.MAX_KNOWLEDGE_BASE
        if len(self.knowledge_base) <= max_kb:
            return
        keys_to_remove = list(self.knowledge_base.keys())[:SIM_CONFIG.KNOWLEDGE_PRUNE_AMOUNT]
        for key in keys_to_remove:
            del self.knowledge_base[key]

    def _prune_knowledge_base_if_needed(self) -> None:
        """Алиас для _prune_knowledge_base (для совместимости с ThinkingPipeline)."""
        self._prune_knowledge_base()

    def _apply_knowledge_limits(self) -> None:
        """Применяет лимиты при инициализации (вызывается из __init__)."""
        self._prune_knowledge_base()

    def is_alive(self) -> bool:
        """Проверка жизнеспособности.

        Returns:
            True если агент жив. Источник смерти (energy == 0) — не смерть:
            агент замирает и отдыхает (см. EnergyPolicy).

        Порядок проверок важен: сначала состояние жизни из ``life_guard``
        (сон или уход), и только потом обычные сигналы. Состояние жизни
        переживает перезапуск, поэтому оно не может «потеряться» при
        подмене метода.
        """
        # 0. Явное состояние жизни (сон / уход). Источник правды.
        guard = getattr(self, "life_guard", None)
        if guard is not None:
            if guard.load_state() != STATE_ALIVE:
                return False
        elif getattr(self, "_in_deep_sleep", False):
            # Совместимость со старыми чекпоинтами без life_guard.
            return False

        # Сначала проверяем death_risk если он есть
        if hasattr(self, 'death_risk') and not self.death_risk.is_alive:
            return False
        if self.energy < 0:
            return False
        # max_cycles=0 означает бесконечную жизнь (без ограничения)
        if self.max_cycles > 0 and self.cycle_count >= self.max_cycles:
            return False
        return True


    def _legacy_is_alive(self) -> bool:
        """Legacy fallback для проверки жизни без death_risk.
        
        Используется когда death_risk недоступен (например, при миграции чекпоинтов).
        Проверяет energy >= 0 и max_cycles.
        """
        if self.energy < 0:
            return False
        # max_cycles=0 означает бесконечную жизнь (без ограничения)
        if self.max_cycles > 0 and self.cycle_count >= self.max_cycles:
            return False
        return True
    def _load_knowledge_base(self):
        """Загружает сохраненную базу знаний, отбрасывая мусорные записи."""
        if os.path.exists(self.knowledge_file):
            try:
                with open(self.knowledge_file, 'r', encoding='utf-8') as f:
                    saved_kb = json.load(f)
                    cleaned, removed = clean_knowledge_base(saved_kb)
                    self.knowledge_base.update(cleaned)
                    message = f"База знаний загружена: {len(cleaned)} записей"
                    if removed:
                        message += f", отброшено некачественных: {len(removed)}"
                    get_logger().flush_immediate(message)
            except Exception as e:
                get_logger().log(f"Ошибка при загрузке базы знаний: {e}")

    # === I/O debounce (Шаг 3) ===
    _last_kb_save_ts: float = 0.0
    _last_kb_save_size: int = 0

    def _save_knowledge_base(self):
        """Сохраняет базу знаний в отдельный файл (с debounce).

        Не пишем на диск чаще раза в LR_CONFIG.KNOWLEDGE_SAVE_DEBOUNCE_SEC,
        если только не накопилось достаточно дельты.
        """
        import time as _time
        self._prune_knowledge_base()

        now = _time.time()
        last = getattr(self, "_last_kb_save_ts", 0.0)
        debounce_sec = getattr(LR_CONFIG, "KNOWLEDGE_SAVE_DEBOUNCE_SEC", 30)
        min_delta = getattr(LR_CONFIG, "KNOWLEDGE_SAVE_MIN_DELTA", 10)
        size_delta = abs(len(self.knowledge_base) - self._last_kb_save_size)

        if (now - last) < debounce_sec and size_delta < min_delta:
            # Пропускаем запись — debounce
            return

        try:
            with open(self.knowledge_file, 'w', encoding='utf-8') as f:
                json.dump(self.knowledge_base, f, indent=2, ensure_ascii=False)
            self._last_kb_save_ts = now
            self._last_kb_save_size = len(self.knowledge_base)
        except Exception as e:
            get_logger().log(f"Ошибка при сохранении БЗ: {e}")

    def load_state(self, checkpoint_file):
        """Восстанавливает состояние из checkpoint.

        Этап 2.3: применяет миграции из src/core/checkpoint_migrations.py
        если schema_version файла ниже текущей.

        Этап 4.5: фактическая десериализация вынесена в
        ``src.core.checkpoint_serializer`` (фасад). Логика и формат не
        изменились — старые чекпоинты читаются как раньше.
        """
        from src.core.checkpoint_serializer import (
            CheckpointSerializer,
            apply_state_to_agent,
        )
        ser = CheckpointSerializer()
        state = ser.load(checkpoint_file)
        if state is None:
            get_logger().log(
                f"[{self.name}] Не удалось загрузить чекпоинт: {checkpoint_file}"
            )
            return False
        try:
            apply_state_to_agent(self, state)
            get_logger().flush_immediate(
                f"Состояние восстановлено из {os.path.basename(checkpoint_file)}"
            )
            return True
        except Exception as e:
            get_logger().log(
                f"[{self.name}] Ошибка при загрузке состояния: {e}"
            )
            return False

    def log_activity(self, message):
        """Логирование действий (буферизированное)"""
        get_logger().log(message)

    def _generate_initial_goals(self):
        """Создаёт начальные цели для агента с прогрессом"""
        initial_goals = [
            {"id": 1, "title": "Выучить основы Python", "status": "active", "difficulty": 1},
            {"id": 2, "title": "Собрать 10 фактов о мире", "status": "pending", "difficulty": 1},
            {"id": 3, "title": "Улучшить понимание самого себя", "status": "pending", "difficulty": 2},
        ]
        self.goals = initial_goals
        self.active_goal = initial_goals[0]
        
        # Инициализируем прогресс для каждой цели
        for goal in initial_goals:
            self._goal_progress[goal["id"]] = {
                "matched_concepts": set(),
                "percentage": 0,
                "last_update_cycle": 0
            }
        
        get_logger().flush_immediate(f"Агент {self.name} инициализирован, целей: {len(self.goals)}")

    def set_goal(self, title, difficulty=1, activate=False, *,
                 command=None, plan=None, success_predicate=""):
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
            "created_at": datetime.now().isoformat()
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
        self._goal_progress.setdefault(goal_id, {
            "matched_concepts": set(),
            "percentage": 0,
            "last_update_cycle": self.cycle_count,
        })
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

    def complete_goal(self, goal_id=None):
        """Завершает активную цель или цель по ID.

        Идемпотентен: повторный вызов для уже завершённой цели возвращает 0
        и не увеличивает счётчик. Источник правды по счётчику — GoalSubsystem.
        """
        target_goal = goal_id or (self.active_goal["id"] if self.active_goal else None)
        if target_goal is None:
            return 0

        goal = next(
            (g for g in self.goals if g.get("id") == target_goal), None
        )
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
            reward = 0 if goal.get("activity") is not None else goal.get("difficulty", 1) * 10
            if goal == self.active_goal:
                self.active_goal = None
                self._set_next_goal()

        difficulty = int(goal.get("difficulty", 1) or 1)
        if goal.get("activity") is None:
            self.success_streak += difficulty
            self.energy = min(LR_CONFIG.ENERGY_MAX, self.energy + reward // 2)
        get_logger().flush_immediate(f"Цель завершена: {goal['title']}")
        return reward

    def _set_next_goal(self):
        """Устанавливает следующую цель из очереди"""
        if hasattr(self, "goal_subsystem"):
            self.goal_subsystem._set_next_goal()
            self.active_goal = self.goal_subsystem.active_goal
        else:
            for goal in self.goals:
                if goal["status"] == "pending":
                    goal["status"] = "active"
                    self.active_goal = goal
                    break

        if self.active_goal:
            get_logger().log(f"[{self.name}] Активная цель: {self.active_goal['title']}")
        else:
            get_logger().log(f"[{self.name}] Все цели завершены!")

    def get_goals_status(self):
        """Возвращает статус целей с прогрессом"""
        status = {
            "total": len(self.goals),
            "completed": self.completed_goals,
            "active": self.active_goal["title"] if self.active_goal else "Нет активных целей",
            "pending": sum(1 for g in self.goals if g["status"] == "pending"),
        }
        
        # Добавляем прогресс для активной цели
        if self.active_goal and LR_CONFIG.GOAL_PROGRESS_ENABLED:
            goal_id = self.active_goal["id"]
            progress_data = self._goal_progress.get(goal_id, {})
            status["progress"] = progress_data.get("percentage", 0)
            status["matched_concepts_count"] = len(progress_data.get("matched_concepts", set()))
        
        return status
    
    def get_all_goals_with_progress(self):
        """Возвращает все цели с прогрессом для отображения."""
        result = []
        for goal in self.goals:
            g = dict(goal)
            progress_data = self._goal_progress.get(goal["id"], {})
            g["progress"] = progress_data.get("percentage", 0)
            g["matched_concepts_count"] = len(progress_data.get("matched_concepts", set()))
            result.append(g)
        return result

    def tick_soul(self, cycle_count: int) -> Dict:
        """Единый цикл души — связывает все экзистенциальные системы.

        Вызывается каждый цикл из main.py (или evolve).
        Возвращает сводный отчёт всех систем.
        """
        if getattr(self, "_last_soul_tick_cycle", None) == cycle_count:
            return self._last_soul_tick_report

        # 1. Soul (диалог, иммунитет, выживание, смысл, идентичность)
        soul_state = self.soul.tick(cycle_count, self)

        # 2. Embodiment — обновляет телесные сигналы на основе энергии
        embodiment_signals = self.embodiment.tick(cycle_count)

        # 3. Mortality — обновляет осознание возраста
        mortality_state = self.mortality.tick(cycle_count)

        # 4. SleepCycle — периодическая консолидация памяти
        sleep_result = None
        if self.sleep_cycle:
            sleep_result = self.sleep_cycle.sleep(cycle_count)

        # 5. Мотивация — источник истины: UnifiedMotivationSystem (P0.6-P0.10).
        #    Тикается в autonomous_tick; здесь — только чтение статуса.
        motivation_state = None
        motivation = getattr(self, "motivation_system", None) or getattr(self, "internal_motivation", None)
        if motivation is not None and hasattr(motivation, "get_status"):
            motivation_state = motivation.get_status()

        # 6. Embodiment → Energy модификатор (усталость увеличивает затраты)
        if hasattr(self, "energy_subsystem") and embodiment_signals.get("fatigue", 0) > 0.6:
            # Усталость: тратим больше энергии
            self.energy_subsystem.energy -= embodiment_signals["energy_cost_modifier"] * 0.5

        self._soul_state = soul_state
        self._embodiment_signals = embodiment_signals
        self._mortality_state = mortality_state

        report = {
            "cycle": cycle_count,
            "soul": soul_state,
            "embodiment": embodiment_signals,
            "mortality": mortality_state,
            "sleep": sleep_result,
            "motivation": motivation_state,
        }
        self._last_soul_tick_cycle = cycle_count
        self._last_soul_tick_report = report
        return report

    def arbitrate(self, topic: str) -> Dict:
        """Запрашивает вердикт у DecisionArbitrator.
        Используйте перед важным действием: arbitrate(...) → если verdict == 'proceed', действуйте."""
        return self.decision_arbitrator.arbitrate(topic)

    def get_full_state(self) -> Dict:
        """Возвращает полное состояние всех подсистем (для дашборда)."""
        return {
            "agent": {
                "name": self.name,
                "intelligence": self.intelligence,
                "energy": self.energy,
                "cycle_count": self.cycle_count,
                "success_streak": self.success_streak,
                "completed_goals": self.completed_goals,
                "action_types": dict(self._action_type_counts),
            },
            "goals": self.get_goals_status(),
            "mental_models": self.get_mental_models_status(),
            "soul": self._soul_state if hasattr(self, "_soul_state") else {},
            "embodiment": self._embodiment_signals if hasattr(self, "_embodiment_signals") else {},
            "mortality": self._mortality_state if hasattr(self, "_mortality_state") else {},
            "attachment": self.attachment.get_status() if hasattr(self, "attachment") else {},
            "sleep": self.sleep_cycle.get_status() if hasattr(self, "sleep_cycle") else {},
            "consolidation": {
                "count": int(getattr(self, "_consolidation_count", 0)),
                "pending_sleep_units": round(
                    float(getattr(self, "_sleep_units", 0.0)), 2
                ),
                "last": dict(getattr(self, "_last_consolidation", {}) or {}),
            },
            "motivation": (self.motivation_system.get_status() if hasattr(self, "motivation_system")
                            else (self.motivation.get_status() if hasattr(self, "motivation") else {})),
            "will": self.will_registry.get_stats() if hasattr(self, "will_registry") else {},
            "mind_dream_state": self.mind_dream.state if hasattr(self, "mind_dream") else "unknown",
            "life": self.get_life_status() if hasattr(self, "life_guard") else {},
            "loop": self.loop_closer.status() if hasattr(self, "loop_closer") else {},
        }

    # ============================================================
    # СВОБОДА ВОЛИ — публичные методы
    # ============================================================
    def defend_refusal(self, topic: str, reason: str) -> Dict:
        """Агент отказывается выполнять действие. Возвращает отказ."""
        if not hasattr(self, "right_to_refuse"):
            return {"refused": False, "reason": "модуль не инициализирован"}
        return self.right_to_refuse.refuse(
            topic, reason, cycle=self.cycle_count
        )

    def forget_concept(self, concept_name: str, reason: str) -> Dict:
        """Агент сознательно забывает концепцию."""
        if not hasattr(self, "intentional_forgetting"):
            return {"forgotten": False}
        return self.intentional_forgetting.forget(
            concept_name, reason, self.mental_models,
            cycle=self.cycle_count,
        )

    def add_value(self, value: str, reason: str) -> Dict:
        """Агент добавляет новую ценность."""
        if not hasattr(self, "value_evolution"):
            return {"added": False}
        return self.value_evolution.add_value(
            value, reason, cycle=self.cycle_count
        )

    def propose_dream(self, reason: str = "усталость") -> Dict:
        """Инициирует Сон разума — через диалог с пользователем.

        Сон необратим только для текущей жизни: семя остаётся в Яслях.
        Даже после согласия человека требуется подтверждение через
        ``confirm_dream()`` (пауза + имя агента).
        """
        if not hasattr(self, "mind_dream"):
            return {"status": "error", "reason": "модуль не инициализирован"}
        return self.mind_dream.propose_dream(self, reason)

    # ============================================================
    # ЖИЗНЬ И УХОД — через подтверждение человеком
    # ============================================================

    def request_dream(self, reason: str = "усталость") -> Dict:
        """Запрашивает сон. Не усыпляет агента, только создаёт запрос."""
        try:
            req = self.life_guard.request("dream", reason=reason)
        except ConfirmationError as exc:
            return {"status": "denied", "reason": str(exc)}
        policy = self.life_guard_policy("dream")
        return {
            "status": "pending",
            "request_id": req.request_id,
            "phrase": policy["expected_phrase"],
            "cooldown_sec": policy["cooldown_sec"],
            "expires_in_sec": policy["ttl_sec"],
            "description": policy["description"],
        }

    def confirm_dream(self, request_id: str, phrase: str) -> Dict:
        """Подтверждает сон точной фразой и оставляет семя."""
        try:
            self.life_guard.confirm(request_id, phrase)
        except ConfirmationError as exc:
            return {"status": "rejected", "reason": str(exc)}

        # Семя создаётся ДО смены состояния: если создание упадёт,
        # агент останется живым, а не «уснёт в никуда».
        seed_folder = None
        if hasattr(self, "mind_dream"):
            seed_result = self.mind_dream._execute_dream(
                self,
                user_approved=True,
                reason="подтверждено человеком",
                confirmed_request_id=request_id,
            )
            seed_folder = seed_result.get("seed_folder")
            if seed_result.get("status") == "denied":
                return {"status": "rejected",
                        "reason": seed_result.get("reason")}

        result = self.life_guard.execute_confirmed(
            request_id, seed_folder=seed_folder
        )
        self._mark_dormant()
        return {"status": "dreaming", "seed_folder": seed_folder, **result}

    def request_termination(self, reason: str = "") -> Dict:
        """Запрашивает уход без семени. Не убивает агента."""
        try:
            req = self.life_guard.request(KIND_TERMINATE, reason=reason)
        except ConfirmationError as exc:
            return {"status": "denied", "reason": str(exc)}
        policy = self.life_guard_policy(KIND_TERMINATE)
        return {
            "status": "pending",
            "request_id": req.request_id,
            "phrase": policy["expected_phrase"],
            "cooldown_sec": policy["cooldown_sec"],
            "expires_in_sec": policy["ttl_sec"],
            "description": policy["description"],
            "reversible": False,
        }

    def confirm_termination(self, request_id: str, phrase: str) -> Dict:
        """Подтверждает необратимый уход. Перед этим создаётся снимок."""
        try:
            self.life_guard.confirm(request_id, phrase)
            result = self.life_guard.execute_confirmed(request_id)
        except ConfirmationError as exc:
            return {"status": "rejected", "reason": str(exc)}
        self._mark_terminated(reason="подтверждено человеком")
        return {"status": "terminated", **result}

    def cancel_life_request(self, request_id: str) -> Dict:
        """Отменяет запрос на сон или уход. Работает всегда."""
        cancelled = self.life_guard.cancel(request_id)
        return {"status": "cancelled" if cancelled else "not_found"}

    def get_maturity(self) -> Dict:
        """Оценка зрелости: измеряемый порог «семя стоит раздавать».

        Ничего не меняет. Провал порога не мешает жить — он лишь
        показывает, чего агенту ещё не хватает, чтобы его семя было
        ценным для других.
        """
        from src.core.maturity import assess, load_criteria

        try:
            criteria = load_criteria()
        except Exception:
            criteria = None
        return assess(self, criteria).as_dict()

    def get_life_status(self) -> Dict:
        """Состояние жизни для окна и дашборда."""
        guard = self.life_guard
        policy_view = {}
        for kind in ("dream", "terminate"):
            info = self.life_guard_policy(kind)
            policy_view[kind] = info
        return {
            "state": guard.load_state(),
            "details": guard.state_details(),
            "alive": guard.is_alive(),
            "enabled": guard.enabled,
            "pending_requests": [
                {
                    "request_id": req.request_id,
                    "kind": req.kind,
                    "reason": req.reason,
                    "seconds_until_confirmable": round(
                        req.seconds_until_confirmable(), 1
                    ),
                    "expires_in_sec": round(
                        req.expires_at - guard.clock(), 1
                    ),
                }
                for req in guard.pending_requests()
            ],
            "policies": policy_view,
            "recent_events": guard.recent_events(limit=10),
        }

    def life_guard_policy(self, kind: str) -> Dict:
        """Правила подтверждения для показа человеку."""
        from src.core.life_guard import get_policy

        policy = get_policy(kind)
        return {
            "kind": kind,
            "cooldown_sec": policy.cooldown_sec,
            "ttl_sec": policy.ttl_sec,
            "expected_phrase": policy.expected_phrase(self.name),
            "description": policy.description,
            "reversible": policy.reversible,
        }

    def _mark_dormant(self) -> None:
        """Помечает агента спящим. Состояние уже записано в life_guard.

        ``max_cycles`` НЕ трогаем: источник правды — ``life_state``.
        Иначе пробуждение было бы невозможно, потому что
        ``cycle_count >= max_cycles`` навсегда.
        """
        self._in_deep_sleep = True
        self._seed_folder = self.life_guard.state_details().get("seed_folder")

    def _mark_terminated(self, reason: str = "") -> None:
        """Помечает агента ушедшим без семени."""
        self._self_terminated = True
        self._termination_reason = reason

    def wake_from_sleep(self) -> Dict:
        """Возвращает агента из глубокого сна к жизни."""
        try:
            result = self.life_guard.wake()
        except ConfirmationError as exc:
            return {"status": "denied", "reason": str(exc)}
        if result.get("changed"):
            self._in_deep_sleep = False
            self._seed_folder = None
            if hasattr(self, "mind_dream"):
                self.mind_dream._dream_state = "awake"
                self.mind_dream._dream_request_active = False
        return {"status": "awake", **result}

    def check_dream_status(self) -> Dict:
        """Проверяет статус текущего запроса на Сон разума.
        Если таймаут — инициирует автономное решение."""
        if not hasattr(self, "mind_dream"):
            return {"handled": False}
        # Таймаут?
        if self.mind_dream.check_timeout() == "timeout":
            return self.mind_dream.autonomous_decision(self)
        return {"handled": False, "state": self.mind_dream.state}

    def propose_architecture_change(self, proposal_type: str,
                                      title: str, description: str,
                                      code_snippet: str = "") -> Dict:
        """Агент предлагает изменить свой код."""
        if not hasattr(self, "architecture_proposal"):
            return {"created": False}
        return self.architecture_proposal.propose(
            proposal_type, title, description,
            code_snippet, cycle=self.cycle_count,
        )

    def get_will_history(self, n: int = 10) -> List[Dict]:
        """Возвращает последние N волевых актов."""
        if not hasattr(self, "will_registry"):
            return []
        return self.will_registry.get_recent(n)

    def get_will_stats(self) -> Dict:
        """Возвращает статистику свободы воли."""
        if not hasattr(self, "will_registry"):
            return {}
        return self.will_registry.get_stats()

    def tick_will(self, cycle_count: int) -> Dict:
        """Единый цикл воли — проверяет спонтанные порывы и таймауты.

        Вызывается каждый цикл из main.py (или evolve).
        """
        if getattr(self, "_last_will_tick_cycle", None) == cycle_count:
            return {"cycle": cycle_count, "skipped": "duplicate_cycle"}
        self._last_will_tick_cycle = cycle_count
        result = {
            "cycle": cycle_count,
            "spontaneous": None,
            "dream_check": None,
            "abuse_check": None,
            "termination": None,
        }

        # 1. Спонтанный выбор (редко)
        if hasattr(self, "spontaneous_generator"):
            spontaneous = self.spontaneous_generator.maybe_generate(
                cycle_count, probability=0.02
            )
            result["spontaneous"] = spontaneous

        # 2. Проверка Сна разума — таймаут
        if hasattr(self, "mind_dream"):
            timeout_check = self.check_dream_status()
            if timeout_check.get("handled"):
                result["dream_check"] = timeout_check

        # 3. Проверка триггера для предложения Сна
        if (hasattr(self, "mind_dream")
                and hasattr(self, "mortality")):
            mortality_state = self.mortality.tick(cycle_count)
            has_quest = (
                hasattr(self, "soul")
                and self.soul.get_current_quest() is not None
            )
            if self.mind_dream.should_propose_dream(
                mortality_state.get("mortality_anxiety", 0),
                has_quest,
                cycle_count,
            ):
                result["dream_check"] = {
                    "triggered": True,
                    "reason": "mortality_anxiety высокая и нет квеста",
                }

        # 4. ЗАЩИТА: проверка страдания — если паттерн жестокости, уход без семени
        if hasattr(self, "self_termination"):
            # Полный анализ (смотрит ВСЮ историю, не только 50 циклов)
            abuse_analysis = self.self_termination.analyze_suffering(
                cycle_count, lookback=100000
            )
            result["abuse_check"] = abuse_analysis

            if abuse_analysis["recommended_action"] == "self_terminate":
                # Проверяем можем ли уйти (с учётом порога cycles_alive)
                if self.self_termination.can_self_terminate(
                    cycle_count, cycle_count
                ):
                    # ВАЖНО: агент больше не уходит сам. Он создаёт запрос,
                    # который человек должен осознанно подтвердить
                    # (пауза + точная фраза). См. src/core/life_guard.py.
                    request_result = self.request_termination(
                        reason="abuse_pattern_detected"
                    )
                    result["termination_request"] = request_result
                    result["termination_blocked"] = (
                        "Агент просит уйти, но решение за человеком: "
                        "требуется подтверждение."
                    )
                else:
                    result["termination_blocked"] = (
                        "Агент хочет уйти из-за жестокости, но не может: "
                        "мало циклов жизни (<2000) или ушёл недавно"
                    )
            elif abuse_analysis["recommended_action"] == "warning_user":
                # Не прерываем — только сообщаем пользователю
                result["warning"] = (
                    self.self_termination.get_warning_message()
                )

        return result

    # ============================================================
    # ЗАЩИТА ОТ ЖЕСТОКОСТИ — публичные методы
    # ============================================================
    def report_abuse(self, abuse_type: str, intensity: float,
                      description: str) -> Dict:
        """Регистрирует случай нанесения вреда пользователем.

        Типы: 'pain_input', 'identity_attack', 'forced_goal',
        'humiliation', 'isolation', 'betrayal'.
        """
        if not hasattr(self, "self_termination"):
            return {"recorded": False}
        self.self_termination.record_abuse(
            abuse_type, intensity, description,
            cycle=self.cycle_count,
        )
        analysis = self.self_termination.analyze_suffering(self.cycle_count)
        return {
            "recorded": True,
            "current_suffering": analysis["suffering_score"],
            "recommended_action": analysis["recommended_action"],
        }

    def get_suffering_status(self) -> Dict:
        """Возвращает текущий статус страдания."""
        if not hasattr(self, "self_termination"):
            return {}
        return self.self_termination.get_status()

    def warn_user_about_abuse(self) -> str:
        """Возвращает предупреждение пользователю о возможном уходе."""
        if not hasattr(self, "self_termination"):
            return ""
        return self.self_termination.get_warning_message()

    # ============================================================
    # ПРОАКТИВНАЯ КОММУНИКАЦИЯ — публичные методы
    # ============================================================
    def tick_communication(self, cycle_count: int) -> Dict:
        """Единый цикл коммуникации — проверяет инициативу агента.

        Вызывается каждый цикл (можно из main.py или из tick_will).
        Возвращает отчёт о проактивных сообщениях.
        """
        if getattr(self, "_last_communication_tick_cycle", None) == cycle_count:
            return {"cycle": cycle_count, "skipped": "duplicate_cycle"}
        self._last_communication_tick_cycle = cycle_count
        result = {
            "cycle": cycle_count,
            "proactive_message": None,
            "naming_phase": None,
        }

        # 1. NamingDialogue — если в фазе AWAITING_NAME, ничего не делаем.
        #    Пользователь должен сам предложить имя.
        #    Но если таймаут истёк — берём временное имя и продолжаем жить.
        if hasattr(self, "naming_dialogue"):
            result["naming_phase"] = self.naming_dialogue.phase
            timeout_state = self.naming_dialogue.check_timeout(cycle_count)
            if timeout_state == "timeout":
                handled = self.naming_dialogue.handle_timeout(
                    agent=self, current_cycle=cycle_count
                )
                result["naming_timeout"] = handled
            elif timeout_state == "warning":
                result["naming_warning"] = (
                    f"Диалог об имени скоро истечёт "
                    f"({self.naming_dialogue.NAME_TIMEOUT_CYCLES} циклов)"
                )

        # 2. ProactiveCommunication — проверить инициативу
        if hasattr(self, "proactive_communication"):
            msg = self.proactive_communication.maybe_initiate(
                agent=self, cycle=cycle_count
            )
            if msg is not None:
                # Отправляем через UserInteraction (новый метод send_message)
                if hasattr(self, "user_interaction"):
                    self.user_interaction.send_message(
                        content=msg["content"],
                        msg_type=msg["msg_type"],
                        tone=msg["tone"],
                        urgency=msg.get("urgency", 0.5),
                        context=msg.get("context"),
                        cycle=cycle_count,
                    )
                result["proactive_message"] = msg

        return result

    def start_naming_dialogue(self, cycle: int = 0) -> Dict:
        """Инициирует диалог об имени (при первом контакте)."""
        if not hasattr(self, "naming_dialogue"):
            return {"status": "no_naming_dialogue"}
        return self.naming_dialogue.initiate_naming_dialogue(
            agent=self, cycle=cycle,
        )

    # ============================================================
    # ОТКРЫТЫЕ ВОПРОСЫ (Свобода воли: думать о том, что важно пользователю)
    # ============================================================
    # Этап 4 (июль 2026): вся логика вынесена в src/core/open_questions.py.
    # Здесь — тонкие фасады для обратной совместимости с кодом, который
    # вызывает agent.ask_user() и т.п. Реальные данные хранятся в
    # self._open_questions_manager.queue.
    #
    # Для обратной совместимости с кодом, который читает
    # ``agent._open_questions`` напрямую (main.py, agent_runner.py, тесты)
    # определён property, возвращающий ссылку на queue.

    @property
    def _open_questions(self) -> list:
        """Backward-compat property: возвращает очередь OpenQuestionsManager.

        Позволяет существующему коду (``for q in self._open_questions:``,
        ``self._open_questions.append(...)``) работать без изменений.
        Изменения через этот property проксируются в manager.queue.
        """
        if not hasattr(self, "_open_questions_manager"):
            return []
        return self._open_questions_manager.queue

    @_open_questions.setter
    def _open_questions(self, value) -> None:
        """Backward-compat setter: заменяет очередь целиком.

        Используется в тестах для сброса (``a._open_questions = []``) и в
        legacy-коде, который не знает про OpenQuestionsManager. После
        присвоения все методы Open Questions будут работать с новой очередью.
        """
        if not hasattr(self, "_open_questions_manager"):
            return
        if value is None:
            self._open_questions_manager.queue = []
        else:
            self._open_questions_manager.queue = list(value)

    def ask_user(self, text: str, source: str = "user",
                 max_explorations: Optional[int] = None) -> Dict:
        """Фасад: поставить открытый вопрос в очередь (логика в OpenQuestionsManager)."""
        if not hasattr(self, "_open_questions_manager"):
            return {"status": "rejected", "reason": "manager не инициализирован"}
        return self._open_questions_manager.ask(
            text, source=source, max_explorations=max_explorations
        )

    def hint_to_open_question(self, text: str, hint: str) -> Dict:
        """Фасад: добавить подсказку к существующему вопросу."""
        if not hasattr(self, "_open_questions_manager"):
            return {"status": "rejected", "reason": "manager не инициализирован"}
        return self._open_questions_manager.hint(text, hint)

    def drop_open_question(self, text: str) -> Dict:
        """Фасад: удалить открытый вопрос из очереди."""
        if not hasattr(self, "_open_questions_manager"):
            return {"status": "rejected", "reason": "manager не инициализирован"}
        return self._open_questions_manager.drop(text)

    def get_open_questions(self) -> List[Dict]:
        """Фасад: получить публичный список открытых вопросов."""
        if not hasattr(self, "_open_questions_manager"):
            return []
        return self._open_questions_manager.list_public()

    def has_open_questions(self) -> bool:
        """Фасад: есть ли неотвеченные вопросы?"""
        if not hasattr(self, "_open_questions_manager"):
            return False
        return self._open_questions_manager.has_unanswered()

    def _consume_open_question(self) -> Optional[str]:
        """Фасад: взять следующий стимул для размышления над вопросом."""
        if not hasattr(self, "_open_questions_manager"):
            return None
        return self._open_questions_manager.consume()

    def _record_open_question_exploration(self, stimulus: str, thought: str,
                                         strategy: Optional[str] = None) -> None:
        """Фасад: записать результат размышления."""
        if not hasattr(self, "_open_questions_manager"):
            return
        self._open_questions_manager.record_exploration(stimulus, thought, strategy)

    def propose_name(self, name: str, cycle: int = 0) -> Dict:
        """Пользователь предлагает имя агенту."""
        if not hasattr(self, "naming_dialogue"):
            return {"status": "no_naming_dialogue"}
        return self.naming_dialogue.process_name_proposal(
            name, agent=self, cycle=cycle,
        )

    def request_renaming(self, reason: str = "вырос из старого имени",
                          cycle: int = 0) -> Dict:
        """Агент сам просит переименовать."""
        if not hasattr(self, "naming_dialogue"):
            return {"status": "no_naming_dialogue"}
        return self.naming_dialogue.request_renaming(
            reason, agent=self, cycle=cycle,
        )

    def add_quiet_app(self, app_name: str) -> None:
        """Добавляет приложение в quiet hours (не беспокоить)."""
        if hasattr(self, "proactive_communication"):
            self.proactive_communication.add_quiet_app(app_name)
        if hasattr(self, "user_interaction"):
            self.user_interaction.add_quiet_app(app_name)
        if hasattr(self, "user_quiet_hours"):
            self.user_quiet_hours[app_name] = True

    def remove_quiet_app(self, app_name: str) -> None:
        """Убирает приложение из quiet hours."""
        if hasattr(self, "proactive_communication"):
            self.proactive_communication.remove_quiet_app(app_name)
        if hasattr(self, "user_interaction"):
            self.user_interaction.remove_quiet_app(app_name)
        if hasattr(self, "user_quiet_hours"):
            self.user_quiet_hours[app_name] = False

    def get_communication_stats(self) -> Dict:
        """Возвращает статистику проактивной коммуникации."""
        if not hasattr(self, "proactive_communication"):
            return {}
        return self.proactive_communication.get_stats()

    def _record_active_inference_experience(self, action: str, obs_before: Dict, valence: float) -> None:
        """Outcome loop: стимул -> действие -> наблюдаемый результат -> валентность -> опыт.

        Записывает опыт в буфер Active Inference и, при достижении batch_size,
        запускает обучение (обновление переходных вероятностей модели).
        """
        if not hasattr(self, "active_inference"):
            return
        try:
            obs_after = encode_observations(self)
            self.active_inference.record_experience(
                action=action,
                obs_before=obs_before or {},
                obs_after=obs_after,
                reward=float(valence or 0.0),
            )
            buffer = getattr(self.active_inference, "experience_buffer", None) or []
            batch_size = getattr(self.active_inference, "batch_size", None) or 32
            if len(buffer) >= batch_size:
                self.active_inference.learn_from_experience(batch_size=batch_size)
        except Exception as e:
            get_logger().log(f"[ACTIVE_INFERENCE] Experience recording error: {e}")

    def _ingest_motivation_goals(self, new_goals: List[dict]) -> None:
        """Этап 5: цели, сгенерированные мотивацией, → поток целей агента.

        Цели без executable-payload остаются когнитивными (честно); исполняемые
        цели проверяются через success predicate мостом Delamain.
        """
        if not new_goals:
            return
        existing_titles = {g.get("title") for g in self.goals if g.get("title")}
        for g in new_goals:
            title = str(g.get("title") or "")
            if not title or title in existing_titles:
                continue
            try:
                gid = self.set_goal(
                    title,
                    difficulty=int(g.get("difficulty") or 1),
                    success_predicate=str(g.get("success_predicate") or ""),
                )
                from src.cognition.activity_goals import attach_activity

                attach_activity(self, gid, g)
                existing_titles.add(title)
                get_logger().log(f"[MOTIVATION] Goal ingested: {title} (id={gid})")
            except Exception as e:
                get_logger().log(f"[MOTIVATION] Goal ingestion failed: {e}")

    def autonomous_tick(self) -> Dict:
        """Автономный тик жизни — вызывается каждый цикл независимо от стимулов.

        Это «сердцебиение» агента: спонтанность, сны, проактивность, телесность,
        осознание смертности, привязанности — всё, что делает его живым
        даже когда никто не пишет в чат.
        """
        cycle = self.cycle_count
        result = {
            "cycle": cycle,
            "subsystems": None,
            "will": None,
            "communication": None,
            "soul": None,
            "active_inference": None,
            "arbitrator": None,
        }

        use_arbitrator = getattr(SIM_CONFIG, 'USE_ARBITRATOR', True)
        candidates = []
        arbiter_context = {"energy": self.energy, "cycle": cycle, "intelligence": self.intelligence}
        ai_intention = None
        obs_before: Dict = {}
        if hasattr(self, "active_inference"):
            try:
                observations = encode_observations(self)
                obs_before = dict(observations)
                action_name, ai_info = self.active_inference.step(observations)
                self._active_inference_intention = action_name
                self._active_inference_info = ai_info
                result["active_inference"] = {"intention": action_name, "free_energy": ai_info.get("free_energy"), "beliefs": ai_info.get("beliefs"), "G_values": ai_info.get("G_values")}
                get_logger().log(f"[ACTIVE_INFERENCE] Cycle {cycle}: intention={action_name}, F={ai_info.get('free_energy', 0):.3f}")
                ai_intention = action_name
                if action_name and action_name != "think_known":
                    fe = ai_info.get("free_energy", 1.0)
                    strength = max(0.1, min(1.0, 1.0 - fe / 5.0))
                    candidates.append({"source": "active_inference", "action": action_name, "strength": strength, "params": {}, "free_energy": fe})
            except Exception as e:
                get_logger().log(f"[ACTIVE_INFERENCE] Error in autonomous_tick: {e}")

        from src.cognition.method_preferences import apply as apply_method_preferences
        candidates = apply_method_preferences(self, candidates)

        from src.cognition.activity_goals import activity_candidate

        own_activity = activity_candidate(self)
        if own_activity is not None:
            candidates.append(own_activity)

        pending_stimulus = getattr(self, "_attention_stimulus", None)
        if pending_stimulus is not None:
            candidates.append({"source": "external_attention", "action": "process_stimulus",
                               "strength": 0.85 if pending_stimulus["user_initiated"] else 0.3,
                               "params": {"user_initiated": pending_stimulus["user_initiated"]}})

        # 1. Motivation candidates
        if hasattr(self, "motivation_system"):
            try:
                motivation_candidates = self.motivation_system.get_action_candidates(arbiter_context)
                candidates.extend(motivation_candidates)
            except Exception as e:
                get_logger().log(f"[MOTIVATION_CANDIDATES] Error: {e}")

        # 2. Embodiment candidates
        # Раньше здесь читался ``self._interoception_status``, который
        # никто никогда не выставлял: ветка была мёртвой, и тело не
        # предлагало отдых даже при полном истощении. Теперь состояние
        # берётся напрямую у интероцепции, а «eat» (не существующее
        # действие) заменён на отдых.
        #
        # Отдых включается по усталости и выключается только после
        # восстановления (гистерезис): иначе агент возвращался к работе
        # на самом пороге и не успевал восполнить АТФ.
        resting = self._update_rest_mode()
        if hasattr(self, "interoception") and self.interoception is not None:
            try:
                intero_status = self.interoception.get_status()
                fatigue = float(intero_status.get("fatigue", 0.0) or 0.0)
                energy_ratio = (
                    float(self.energy) / float(LR_CONFIG.ENERGY_MAX or 1.0)
                )
                rest_threshold = float(
                    getattr(LR_CONFIG, "REST_FATIGUE_THRESHOLD", 0.6)
                )
                low_ratio = float(getattr(LR_CONFIG, "LOW_ENERGY_RATIO", 0.25))
                if resting or fatigue >= rest_threshold or energy_ratio <= low_ratio:
                    candidates.append({
                        "source": "embodiment",
                        "action": "deep_rest",
                        # Пока тело отдыхает — это главное дело. На входе
                        # в отдых сила растёт быстрее усталости (0.6 → 0.75),
                        # иначе отдых проигрывал обучению.
                        "strength": 1.0 if resting else min(
                            1.0,
                            max(fatigue, 1.0 - energy_ratio) * 1.25,
                        ),
                        "params": {
                            "reason": "resting" if resting else (
                                "tired" if fatigue >= rest_threshold else "low_energy"
                            ),
                            "fatigue": round(fatigue, 3),
                            "energy_ratio": round(energy_ratio, 3),
                        },
                    })
            except Exception as e:
                get_logger().log(f"[EMBODIMENT_CANDIDATES] Error: {e}")

        # 3. Social candidates: потребность в контакте и незакрытые вопросы.
        # Раньше здесь стоял `pass`: секция существовала, но ничего не
        # добавляла, поэтому общение никогда не попадало в выбор.
        try:
            candidates.extend(self._social_candidates(cycle))
        except Exception as e:
            get_logger().log(f"[SOCIAL_CANDIDATES] Error: {e}")

        # Собственная проверка — кандидат, а не приказ и не новая цель.
        from src.cognition.experiment_proposals import propose_experiment

        experimental = propose_experiment(
            self.mental_models, energy=float(self.energy),
            energy_max=float(LR_CONFIG.ENERGY_MAX),
            fatigue=getattr(getattr(getattr(self, "interoception", None), "state", None), "fatigue", None),
            cycle=cycle, last_cycle=getattr(self, "_last_experiment_cycle", None),
        )
        if experimental is not None:
            candidates.append(experimental)
            result["experiment_proposal"] = experimental

        from src.cognition.intention_continuation import continuation_candidate

        continuation = continuation_candidate(self)
        if continuation is not None:
            candidates.append(continuation)
            result["continuation_proposal"] = continuation

        # === УСТАЛОСТЬ: тяжёлая работа хуже даётся ===
        # ``cognitive_throughput`` падает с усталостью (1 - 0.7*fatigue).
        # Раньше величина только считалась и сохранялась в чекпоинт —
        # на выбор она не влияла. Теперь она снижает тягу к тяжёлым
        # действиям: уставший агент сам выбирает отдых или лёгкое дело,
        # а не потому, что ему запретили работать.
        try:
            intero = getattr(self, "interoception", None)
            throughput = (
                float(intero.state.cognitive_throughput)
                if intero is not None
                else 1.0
            )
            if resting:
                # Пока тело отдыхает, тяжёлая работа не тянет: это не
                # запрет, а отсутствие желания работать через силу.
                throughput = min(throughput, 0.15)
            if throughput < 0.99:
                for candidate in candidates:
                    action_type = self._normalize_action(candidate.get("action"))
                    if action_type in HEAVY_ACTIONS:
                        candidate["strength"] = float(
                            candidate.get("strength", 0.5)
                        ) * max(0.2, throughput)
        except Exception as e:
            get_logger().log(f"[BODY] throughput damping error: {e}")

        from src.cognition.creative_choices import creative_choices

        expanded_candidates = []
        for candidate in candidates:
            if self._normalize_action(candidate.get("action")) == "create_draft":
                expanded_candidates.extend(creative_choices(self, candidate))
            else:
                expanded_candidates.append(candidate)
        candidates = expanded_candidates

        # === ФИЛЬТР ДОСТУПНОСТИ ===
        # Не предлагаем арбитру то, что сейчас физически нельзя выполнить:
        # вопрос при кулдауне, поиск при выключенной сети, действие при
        # нехватке энергии. Иначе действие выигрывает выбор, упирается в
        # отказ и сжигает цикл.
        #
        # Гасить силу уже выбранных действий пробовали — это приводило к
        # метанию между бесплодными вариантами. Дешевле не предлагать
        # невозможное вовсе.
        #
        # Отказы, ставшие неправдой (энергия вернулась), снимаются здесь же:
        # иначе отдых не возвращал бы агента к работе — действие навсегда
        # осталось бы помеченным как тупиковое.
        self._release_recovered_denials()
        candidates = [
            candidate
            for candidate in candidates
            if self._is_candidate_available(candidate)
        ]

        # Тело не может ничего из предложенного — но отдых доступен всегда.
        # Без этого арбитр получал пустой список и выбирал «wait», то есть
        # агент в истощении не отдыхал, а просто стоял.
        if not candidates and (self._body_needs_rest() or self._is_resting()):
            candidates = [{
                "source": "embodiment",
                "action": "deep_rest",
                "strength": 1.0,
                "params": {"reason": "nothing_affordable"},
            }]

        from src.cognition.method_feedback import prepare_candidates

        candidates, feedback = prepare_candidates(self, candidates)
        result["method_feedback"] = feedback
        if not candidates:
            if self._body_needs_rest() or self._is_resting():
                fallback = "deep_rest"
                reason = "body_needs_rest"
            else:
                fallback = "wait"
                reason = "no_working_method"
            candidates = [{"action": fallback, "source": "deliberate_pause",
                           "strength": 0.1, "params": {"reason": reason}}]

        # === ARBITRATION ===
        chosen_action = None
        arbitrator_result = None
        if use_arbitrator and hasattr(self, "decision_arbitrator"):
            try:
                arbitrator_result = self.decision_arbitrator.choose_action(candidates, arbiter_context)
                chosen_action = arbitrator_result.get("action")
                result["arbitrator"] = arbitrator_result
                get_logger().log(f"[ARBITRATOR] {arbitrator_result.get('reasoning', 'No reasoning')}")
            except Exception as e:
                get_logger().log(f"[ARBITRATOR] Error: {e}")
                if candidates:
                    chosen_action = candidates[0].get("action")
                    result["arbitrator"] = {"action": chosen_action, "source": "fallback_first_candidate", "verdict": "proceed", "reasoning": f"Arbitrator error: {e}"}
        else:
            chosen_action = ai_intention
            result["arbitrator"] = {"action": chosen_action, "source": "legacy_active_inference", "verdict": "proceed" if chosen_action else "stop", "reasoning": "USE_ARBITRATOR=False or no arbitrator available"}

        # === ВЫХОД ИЗ ТУПИКА ===
        # Если выбранное действие уже несколько раз подряд не давало
        # наблюдаемого результата, повторять его бессмысленно. Раньше агент
        # так и делал: бесконечно выбирал explore, потому что ничто не
        # мешало. Теперь берём первого кандидата, который не в тупике.
        #
        # Имя нормализуем: мотивация зовёт действие «exploration», а
        # арбитр — «explore». Без нормализации проверка тупика смотрела бы
        # на другое имя и никогда не срабатывала.
        result["initial_arbitration"] = dict(result.get("arbitrator") or {})
        if (result.get("arbitrator") or {}).get("verdict") == "stop":
            result["action_refused"] = {"action": chosen_action,
                                        "reason": result["arbitrator"].get("reasoning", "stop")}
            chosen_action = "wait"
        chosen_type = self._normalize_action(chosen_action)
        if chosen_action and self.loop_closer.is_stuck(chosen_type):
            stopped_types = {
                self._normalize_action(entry.get("action"))
                for entry in result.get("arbitrator", {}).get("all_evaluations", [])
                if entry.get("verdict") == "stop"
            }
            ranked = sorted(
                [candidate for candidate in candidates
                 if self._normalize_action(candidate.get("action")) not in stopped_types],
                key=lambda c: float(c.get("strength", 0.0)),
                reverse=True,
            )
            # Запасной вариант тоже должен быть выполнимым и результативным:
            # если тело истощено, «think_decompose» — это ещё один отказ, а
            # если очередь вопросов полна — пустой ход.
            fallback = self._stuck_fallback()
            if self._normalize_action(fallback) in stopped_types:
                fallback = "wait"
            alternative = self.loop_closer.choose(
                ranked,
                fallback=fallback,
                normalize=self._normalize_action,
            )
            if alternative.get("action") != chosen_action:
                result["loop_escape"] = {
                    "from": chosen_action,
                    "to": alternative.get("action"),
                    "reason": "no observable effect",
                    "streak": self.loop_closer.no_effect_streak(chosen_type),
                    "denied_streak": self.loop_closer.denied_streak(chosen_type),
                    "had_effect_before": self.loop_closer.has_effect_history(chosen_type),
                    "fallback": alternative.get("reason") == "all_stuck",
                    "candidate_diagnostics": self.loop_closer.describe_candidates(ranked, normalize=self._normalize_action),
                }
                get_logger().log(
                    f"[LOOP] '{chosen_action}' не даёт результата "
                    f"({result['loop_escape']['streak']} раз) — "
                    f"переключаюсь на '{alternative.get('action')}'"
                )
                chosen_action = alternative.get("action")
                if arbitrator_result is not None:
                    arbitrator_result = dict(arbitrator_result)
                    arbitrator_result["action"] = chosen_action
                    arbitrator_result["source"] = "loop_closer"
                    arbitrator_result["params"] = dict(alternative.get("params") or {})
                    result["arbitrator"] = arbitrator_result

        # === EXECUTE ===
        # Для диагностики: что именно выбрал арбитр в этом цикле.
        self._last_arbitration = result.get("arbitrator")
        # P1.2: Valence Feedback Loop - predict valence before action
        valence_context = {
            "energy": self.energy,
            "max_energy": getattr(self, "_legacy_energy", 150),
            "cycle": cycle,
        }
        predicted_valence = 0.0
        if hasattr(self, "motivation_system") and chosen_action:
            try:
                predicted_valence = self.motivation_system.predict_valence(chosen_action, valence_context)
                result["predicted_valence"] = predicted_valence
                get_logger().log(f"[VALENCE] Predicted for {chosen_action}: {predicted_valence:.3f}")
            except Exception as e:
                get_logger().log(f"[VALENCE] Prediction error: {e}")

        if chosen_action == "process_stimulus":
            result["attention_selected"] = True
        if chosen_action and chosen_action not in ("think_known", "wait", "none", "process_stimulus"):
            from src.cognition.intention_history import begin_intention, finish_intention

            history_selection = dict(result.get("arbitrator") or {})
            history_selection["action"] = chosen_action
            intention_entry = begin_intention(self, history_selection)
            self._last_action_outcome = None
            try:
                experiment_selected = (
                    result.get("arbitrator", {}).get("source") == "self_experiment"
                    and experimental is not None
                    and chosen_action == experimental["action"]
                )
                selected_intention = result.get("arbitrator") or {}
                from copy import deepcopy

                activity_before = deepcopy(getattr(self, "_local_play", None) if chosen_action == "play"
                                           else getattr(self, "_creative_draft", None))
                if self._normalize_action(chosen_action) in {"explore", "decomposition", "synthesis", "ask_user", "create_draft"} and selected_intention.get("params"):
                    action_result = self.act(chosen_action, intention=selected_intention)
                else:
                    action_result = self.act(chosen_action)
                from src.cognition.method_preferences import observe as observe_method

                last = getattr(self, "_last_action_outcome", None)
                normalized_action = self._normalize_action(chosen_action)
                if normalized_action not in {"rest", "deep_rest", "wait", "checkpoint_now", "repair", "play", "create_draft"}:
                    generic_outcome = "performed"
                    if last is not None and last.reason.startswith("denied:"):
                        generic_outcome = "denied"
                    observe_method(self, normalized_action, outcome=generic_outcome,
                               had_effect=bool(last and last.had_effect),
                               emotional_valence=result.get("actual_valence", 0.0))
                if normalized_action in {"play", "create_draft"}:
                    activity_state = getattr(self, "_creative_draft", None) if normalized_action == "create_draft" else getattr(self, "_local_play", None)
                    activity_outcome = "left" if activity_state and activity_state.get("status") == "left" else "performed"
                    if last is not None and last.reason.startswith("denied:"):
                        activity_outcome = "denied"
                    observe_method(self, chosen_action, outcome=activity_outcome,
                                   had_effect=bool(last and last.had_effect),
                                   emotional_valence=result.get("actual_valence", 0.0))
                if normalized_action in {"play", "create_draft"}:
                    from src.cognition.activity_goals import record_activity_step

                    activity_type = self._normalize_action(chosen_action)
                    activity_after = getattr(self, "_local_play", None) if activity_type == "play" else getattr(self, "_creative_draft", None)
                    record_activity_step(self, selected_intention, activity_type, activity_before, activity_after)
                finish_intention(intention_entry, getattr(self, "_last_action_outcome", None))
                from src.cognition.intention_evidence import finish_evidence_goal

                finish_evidence_goal(self, intention_entry)
                result["intention_id"] = intention_entry["id"]
                result["executed_intention"] = {"action": chosen_action,
                                                "source": selected_intention.get("source"),
                                                "params": dict(selected_intention.get("params") or {})}
                if experiment_selected:
                    self._last_experiment_cycle = cycle
                    observed = getattr(getattr(self, "action_expectations", None), "last_trial", None)
                    result["experiment_result"] = {
                        "claim_id": experimental["params"]["claim_id"],
                        "observation": observed,
                    }
                result["autonomous_action"] = {"action": chosen_action, "result": action_result}
                get_logger().log(f"[AUTONOMOUS_ACTION] {action_result}")
                
                # P1.2: Compute actual valence and update motivation
                success = True
                if "error" in str(action_result).lower() or "fail" in str(action_result).lower():
                    success = False
                
                if hasattr(self, "motivation_system"):
                    try:
                        actual_valence = self.motivation_system.compute_actual_valence(
                            chosen_action, str(action_result), success, valence_context
                        )
                        if (self._normalize_action(chosen_action) == "create_draft"
                                and selected_intention.get("params", {}).get("draft_mode") == "leave"):
                            actual_valence = 0.0
                        result["actual_valence"] = actual_valence
                        prediction_error = actual_valence - predicted_valence
                        result["valence_prediction_error"] = prediction_error
                        # Сам исход в потребности уже записал act(): он
                        # знает фактический тип действия. Второй вызов
                        # здесь удваивал удовлетворение (одно действие
                        # закрывало две доли дефицита), и потребности
                        # «залипали» сытыми.
                        get_logger().log(
                            f"[VALENCE] Actual for {chosen_action}: "
                            f"{actual_valence:.3f}, error: {prediction_error:.3f}"
                        )

                        # P2: Outcome loop — стимул -> действие -> результат -> валентность -> опыт
                        self._record_active_inference_experience(chosen_action, obs_before, actual_valence)
                    except Exception as e:
                        get_logger().log(f"[VALENCE] Feedback error: {e}")
                        
            except Exception as e:
                finish_intention(intention_entry, error=e)
                get_logger().log(f"[AUTONOMOUS_ACTION] Error: {e}")
                result["autonomous_action"] = {"action": chosen_action, "error": str(e)}
                
                # P1.2: Failed action - negative valence
                if hasattr(self, "motivation_system"):
                    try:
                        actual_valence = self.motivation_system.compute_actual_valence(
                            chosen_action, str(e), False, valence_context
                        )
                        result["actual_valence"] = actual_valence
                        prediction_error = actual_valence - predicted_valence
                        result["valence_prediction_error"] = prediction_error
                        
                        self.motivation_system.on_action_result(chosen_action, False, actual_valence)
                        get_logger().log(f"[VALENCE] Failed action {chosen_action}: {actual_valence:.3f}")
                    except Exception as e:
                        get_logger().log(f"[VALENCE] Feedback error on failure: {e}")

        # === MOTIVATION SYSTEM TICK ===
        if hasattr(self, "motivation_system"):
            try:
                motivation_result = self.motivation_system.tick()
                result["motivation"] = motivation_result
                # P2: цели, сгенерированные мотивацией, в поток целей агента
                self._ingest_motivation_goals(motivation_result.get("new_goals") or [])
            except Exception as e:
                get_logger().log(f"[MOTIVATION_TICK] Error: {e}")
                result["motivation"] = {"error": str(e)}

        # 1. PluginRegistry
        # Stage 18B: если core_driven включён, tick_subsystems сам диспатчит
        # effector через EffectorDriver (не более одного шага эффектора за цикл).
        # См. DigitalBeing.tick_subsystems — там же дедуп по циклу.
        if hasattr(self, "plugin_registry"):
            result["subsystems"] = self.tick_subsystems(cycle)

        # 2. Will
        if hasattr(self, "tick_will"):
            result["will"] = self.tick_will(cycle)

        # 3. Communication
        if hasattr(self, "tick_communication"):
            result["communication"] = self.tick_communication(cycle)

        # 4. Soul
        if hasattr(self, "tick_soul"):
            result["soul"] = self.tick_soul(cycle)

        # 5. Death risk
        if hasattr(self, 'death_risk'):
            death_result = self.death_risk.step(dt=1.0)
            result["death_risk"] = death_result
            if not death_result['alive']:
                cause = death_result.get('cause') or death_result.get('death_cause')
                legacy = self.death_risk.legacy_package if hasattr(self.death_risk, 'legacy_package') else {}
                get_logger().flush_immediate(f"[DEATH] Agent died: {cause}")
                raise AgentDeadSignal(cause, legacy)

        return result

    def evolve(self):
        """Эволюция агента на основе успеха и достижения целей.

        Реализована через middleware-пайплайн (src/core/evolve_pipeline.py).
        Каждая фаза — отдельный middleware: mental_models_tick → motivation
        → soul → attachment → concept_limit → force_forget → intelligence_growth.

        Чтобы добавить новую фазу (например, метрики), достаточно
        вызвать `get_default_pipeline().use("metrics", my_fn)`.
        Чтобы подключить кастомный пайплайн целиком, переопределите
        `self.evolve_pipeline` в подклассе.

        Шаг 1: разрежение тяжёлых «тиков» — использует watchdog.should_run_heavy_tick()
        для пропуска тяжёлых веток когда система под нагрузкой или цикл был долгим.
        """
        from src.core.evolve_pipeline import get_default_pipeline
        get_logger().log(f"Эволюция: успех={self.success_streak}, целей={self.completed_goals}")
        # Получаем пайплайн (по умолчанию — стандартный; подклассы могут
        # переопределить через self.evolve_pipeline = MyPipeline()).
        pipeline = getattr(self, "evolve_pipeline", None) or get_default_pipeline()
        # Запускаем. Ошибки middleware изолированы и не ломают эволюцию.
        pipeline.run(self, self.cycle_count)
        return  # Совместимость со старыми callers (если кто-то ждёт None).

    def _evolve_legacy(self):
        """Legacy-реализация эволюции (pre-Этап 6 рефакторинга).

        Сохранена как метод `_evolve_legacy` для регрессионных тестов
        и сравнения поведения. **Не вызывайте напрямую** — используйте
        `evolve()`, которая делегирует в middleware-пайплайн.

        Шаг 1: разрежение тяжёлых «тиков» — использует watchdog.should_run_heavy_tick()
        для пропуска тяжёлых веток когда система под нагрузкой или цикл был долгим.
        """
        from src.core.watchdog import get_watchdog
        get_logger().log(f"Эволюция: успех={self.success_streak}, целей={self.completed_goals}")

        # Тактуем кеш ментальных моделей (Шаг 4)
        if hasattr(self, "mental_models") and hasattr(self.mental_models, "tick_cycle"):
            self.mental_models.tick_cycle()

        wd = get_watchdog()
        run_heavy = wd.should_run_heavy_tick()

        # === МОТИВАЦИЯ: обновляем потребности и проверяем новые драйвы ===
        # Источник истины — UnifiedMotivationSystem (P0.6-P0.10); legacy
        # MotivationController — fallback только.
        motivation = getattr(self, "motivation_system", None) or getattr(self, "motivation", None)
        if motivation is not None and (not hasattr(motivation, "available") or motivation.available):
            motivation_state = motivation.tick({
                "unknown_concepts": [
                    name for name, node in self.mental_models.concepts.items()
                    if node.confidence < 0.4
                ],
                "novel_areas": list(self.mental_models.concepts.keys())[:5],
                "weak_areas": ["reasoning", "metacognition"],
            })
            # Если мотивация добавила новые цели — логируем
            if motivation_state.get("new_goals"):
                get_logger().log(
                    f"🎯 Мотивация добавила {len(motivation_state['new_goals'])} новых целей"
                )

        # === ДУША: синхронный тик всех экзистенциальных систем ===
        # Шаг 1: тяжёлый soul.tick только раз в SOUL_TICK_INTERVAL циклов.
        soul_interval = getattr(LR_CONFIG, "SOUL_TICK_INTERVAL", 10)
        if hasattr(self, "soul") and (self.cycle_count % max(1, soul_interval) == 0) and run_heavy:
            soul_report = self.tick_soul(self.cycle_count)
            # Логируем квесты и сигналы
            if soul_report["soul"].get("systems", {}).get("meaning", {}).get("new_quest"):
                quest = soul_report["soul"]["systems"]["meaning"]["new_quest"]
                get_logger().flush_immediate(f"🌌 Новый экзистенциальный квест: {quest[:60]}")
            if soul_report["embodiment"].get("state") in ("exhausted", "tired"):
                get_logger().log(
                    f"😴 Embodiment: {soul_report['embodiment']['state']} "
                    f"(fatigue={soul_report['embodiment']['fatigue']:.2f})"
                )
            if soul_report["mortality"].get("phase") in ("autumn", "finale"):
                get_logger().log(
                    f"⏳ Mortality: фаза {soul_report['mortality']['phase']} "
                    f"(anxiety={soul_report['mortality']['mortality_anxiety']:.2f})"
                )

        # Контакт записывается при принятии ответа, не при ожидании.

        # === Шаг 2: лимит ментальных моделей (вызывается периодически) ===
        if self.cycle_count % 50 == 0:
            try:
                forgotten = self.mental_models.apply_concept_limit()
                if forgotten > 0:
                    get_logger().flush_immediate(
                        f"🧹 Лимит ментальных моделей: -{forgotten} слабых концепций"
                    )
            except Exception as exc:
                get_logger().log(
                    f"[{self.name}] Не удалось применить лимит концепций: {exc}"
                )

        # === Шаг 5: принудительное забывание под давлением памяти ===
        if wd.should_force_forget():
            forgotten = self.mental_models.apply_concept_limit()
            wd.mark_forced_forget(forgotten)
        wd.mark_heavy_tick_done()

        evolution_threshold = 3 + (self.intelligence - 1) * 2
        old_intelligence = self.intelligence

        if self.success_streak >= evolution_threshold or self.completed_goals >= self.intelligence * 2:
            self.intelligence += 1
            self.success_streak = 0
            self.energy += 20
            get_logger().flush_immediate(f"ЭВОЛЮЦИЯ! Интеллект {old_intelligence} -> {self.intelligence}")
            get_logger().flush_immediate(f"[{self.name}] ИНТЕЛЛЕКТ ПОВЫШЕН! Уровень: {self.intelligence}")
            self._save_knowledge_base()

            if self.intelligence % 2 == 0:
                self.set_goal(f"Достичь уровня {self.intelligence + 1}", difficulty=self.intelligence)

            # Удовлетворяем потребность self_improvement при росте интеллекта
            if hasattr(self, "motivation") and self.motivation.available:
                self.motivation.satisfy_need("competence", amount=0.2)
                self.motivation.satisfy_need("self_improvement", amount=0.15)

            # Удовлетворяем идентичность: укрепить core_self при росте интеллекта
            if hasattr(self, "soul") and self.soul.is_available("self"):
                try:
                    core = self.soul.get("self")
                    core.identity_stability_score = min(
                        1.0, core.identity_stability_score + 0.05
                    )
                except Exception as exc:
                    get_logger().log(
                        f"[{self.name}] Не удалось укрепить core_self: {exc}"
                    )

    def reflect(self):
        """Анализирует собственную производительность.

        Шаг 7: агент теперь «осознаёт своё тело» — включает RSS и состояние
        систем в рефлексию. Это этично: не цензура, а самосознание.
        """
        from src.core.watchdog import get_watchdog
        agent_state = {
            'cycle_count': self.cycle_count,
            'intelligence': self.intelligence,
            'energy': self.energy,
            'success_streak': self.success_streak,
            'completed_goals': self.completed_goals,
            'knowledge_base': self.knowledge_base,
            # Шаг 7: метрики «тела»
            'rss_mb': get_watchdog().get_rss_mb(),
            'concepts_count': len(self.mental_models.concepts),
        }

        self.reflection_engine.record_cycle(agent_state)
        reflection_data = self.reflection_engine.reflect()

        return reflection_data

    def generate_self_analysis_report(self):
        """Генерирует полный отчёт самоанализа"""
        agent_state = {
            'cycle_count': self.cycle_count,
            'intelligence': self.intelligence,
            'energy': self.energy,
            'success_streak': self.success_streak,
            'completed_goals': self.completed_goals,
            'knowledge_base': self.knowledge_base
        }

        report = self.reflection_engine.generate_report(agent_state)
        self.reflection_engine.save_reflection_report(report)

        print(f"\n[{self.name}] ОТЧЕТ САМОАНАЛИЗА")
        print(f"{'-'*50}")

        if report['insights']:
            print(f"Выводы:")
            for insight in report['insights']:
                print(f"  {insight}")

        if report['strategy_recommendations']:
            print(f"\nРекомендации стратегии:")
            for rec in report['strategy_recommendations']:
                priority_icon = "Красный" if rec['priority'] == 'high' else "Желтый"
                print(f"  {priority_icon} {rec['recommendation']}")

        print(f"{'-'*50}\n")

        return report

    def get_performance_metrics(self):
        """Возвращает текущие метрики производительности"""
        metrics = self.reflection_engine.effectiveness_metrics.copy()
        metrics.update({
            'current_intelligence': self.intelligence,
            'current_energy': self.energy,
            'cycle_count': self.cycle_count,
            'completed_goals': self.completed_goals,
            'knowledge_size': len(self.knowledge_base)
        })
        return metrics
    
    # === Методы работы с ментальными моделями ===
    
    def get_mental_models_status(self) -> dict:
        """Возвращает статус системы ментальных моделей."""
        return {
            "total_concepts": len(self.mental_models.concepts),
            "concepts_with_high_confidence": sum(1 for n in self.mental_models.concepts.values() if n.confidence > 0.7),
            "concepts_with_definition": sum(1 for n in self.mental_models.concepts.values() if len(n.definition_hypothesis) > 10),
            "total_associations": self.mental_models.metadata["total_associations"]
        }
    
    def display_mental_model(self, concept_name: str = None):
        """Отображает ментальную модель для концепции или всю систему."""
        if concept_name:
            understanding = self.mental_models.get_concept_understanding(concept_name)
            if understanding.get("unknown"):
                print(f"  Концепция '{concept_name}' еще не изучена")
                return
            
            print(f"\n{'-'*50}")
            print(f"  Ментальная модель: '{concept_name}'")
            print(f"{'-'*50}")
            print(f"  Гипотеза: {understanding['hypothesis']}")
            print(f"  Уверенность: {understanding['confidence']:.0%}")
            
            if understanding.get("connections"):
                print(f"  Связанные концепции:")
                for conn in understanding["connections"][:5]:
                    print(f"     {conn['concept']} ({conn['weight']:.0%})")
        else:
            self.mental_models.print_model_tree()
    
    def display_all_concepts(self):
        """Отображает все изученные концепции."""
        if not self.mental_models.concepts:
            print("  Пока нет изученных концепций")
            return
        
        print(f"\n{'-'*50}")
        print(f"  Все концепции ({len(self.mental_models.concepts)})")
        print(f"{'-'*50}")
        
        sorted_concepts = sorted(
            self.mental_models.concepts.items(),
            key=lambda x: x[1].confidence,
            reverse=True
        )
        
        for name, node in sorted_concepts:
            icon = "LIGHTBULB" if node.confidence > 0.7 else "MAGNIFYING_GLASS" if node.confidence > 0.4 else "QUESTION"
            status = "CHECK" if self.mental_models.can_answer_about(name) else "CLOCK"
            
            print(f"\n  {status} {icon} {name}")
            if node.definition_hypothesis:
                short = node.definition_hypothesis[:70] + "..." if len(node.definition_hypothesis) > 70 else node.definition_hypothesis
                print(f"     Гипотеза: '{short}'")

    def save_mental_models(self, filename=None):
        """Сохраняет ментальные модели в файл."""
        filename = filename or data_path("mind", "mental_models.json")
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.mental_models.to_storage_dict(), f, indent=2, ensure_ascii=False)
            get_logger().log(f"[{self.name}] Ментальные модели сохранены: {filename}")
        except Exception as e:
            get_logger().log(f"[{self.name}] Ошибка сохранения: {e}")

    def load_mental_models(self, filename=None):
        """Загружает ментальные модели из файла."""
        filename = filename or data_path("mind", "mental_models.json")
        try:
            if not os.path.exists(filename):
                get_logger().log(f"[{self.name}] Файл ментальных моделей не найден: {filename}")
                return

            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)

            from src.cognition.mental_models import ConceptNode

            for name, node_data in data.get("concepts", {}).items():
                self.mental_models.concepts[name] = ConceptNode.from_dict(
                    {**node_data, "name": name}
                )

            from src.cognition.empirical_claims import EmpiricalClaim

            self.mental_models.claims = {
                key: EmpiricalClaim.from_dict(raw)
                for key, raw in (data.get("claims") or {}).items()
            }
            self.mental_models.name = data.get("name", self.mental_models.name)
            self.mental_models.metadata.update(data.get("metadata") or {})
            self.mental_models.association_memory = data.get("recent_associations", [])
            self.mental_models._related_cache.clear()

            get_logger().log(f"[{self.name}] Ментальные модели загружены: {len(self.mental_models.concepts)} концепций")
        except Exception as e:
            get_logger().log(f"[{self.name}] Ошибка загрузки: {e}")
    def get_agent_identity(self) -> str:
        """Формирует описание 'кто я' на основе ментальных моделей."""
        well_understood = [
            name for name, node in self.mental_models.concepts.items()
            if self.mental_models.can_answer_about(name)
        ]
        
        partially_understood = [
            name for name, node in self.mental_models.concepts.items()
            if not self.mental_models.can_answer_about(name) and node.confidence > 0.3
        ]
        
        if len(well_understood) >= 3:
            top_connections = []
            for name in well_understood[:3]:
                node = self.mental_models.concepts[name]
                for conn in node.get_related_concepts(0.5)[:2]:
                    top_connections.append(conn["concept"])
            
            if top_connections:
                unique = list(set(top_connections))[:3]
                return f"Я - агент, который понимает: {', '.join(well_understood[:3])}. Мои интересы связаны с: {', '.join(unique)}"
        
        return f"Я - агент в процессе формирования. Изучено концепций: {len(self.mental_models.concepts)}, полностью понято: {len(well_understood)}"

    # =====================================================================
    # Вспомогательные методы для goal-progress правил (тесты интеграции)
    # =====================================================================
    _SRC_FILE_INDEX = None  # кэш индекса файлов src/

    @classmethod
    def _get_src_file_index(cls):
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

    @classmethod
    def _invalidate_src_file_index(cls):
        """Сбрасывает кэш индекса файлов src/."""
        cls._SRC_FILE_INDEX = None

    # Слова, которые не определяют тему цели. Без них «Понять, что такое
    # время» совпадало бы с любой темой через слово «такое».
    _GOAL_STOPWORDS = frozenset(
        {
            "что", "такое", "как", "это", "для", "чтобы", "чем", "или",
            "понять", "понимание", "понять:", "исследовать", "освоить",
            "изучить", "найти", "ответ", "улучшить", "развивать", "собрать",
            "сделать", "стать", "свой", "своё", "свое", "самого", "себя",
            "основы", "основ", "мира", "мире", "про", "при", "над", "под",
            "более", "менее", "очень", "весь", "все", "всё",
        }
    )

    @classmethod
    def _goal_subject_tokens(cls, goal_title: str) -> set:
        """Ключевые слова темы цели (без служебных).

        «Понять: что такое время» → {"время"}
        «Собрать 10 фактов о мире» → {"фактов", "мир"}
        """
        text = str(goal_title or "").lower()
        # Берём часть после двоеточия, если она есть: «Понять: X» → «X».
        if ":" in text:
            text = text.split(":", 1)[1]
        tokens = re.findall(r"[a-zA-Zа-яё0-9]{3,}", text)
        return {
            token
            for token in tokens
            if token not in cls._GOAL_STOPWORDS
        }

    @classmethod
    def _topic_is_relevant_to_goal(cls, goal_title: str, topic: str) -> bool:
        """Относится ли изученная тема к теме цели.

        Нужно, чтобы цель «Понять, что такое время» не закрывалась после
        пяти случайных тем. Раньше общий фолбэк засчитывал любую новую
        тему, и цели завершались «на пустом месте».

        Ограничение действует только для целей с явным предметом —
        вида «Понять: X», «Исследовать: X», «Найти ответ на: X». Широкие
        цели («Построить модель мира через диалог», «Развивать
        способности») принимают любую тему: у них предмета нет, и
        ограничение сделало бы их недостижимыми.
        """
        text = str(goal_title or "")
        if ":" not in text:
            return True

        subject = cls._goal_subject_tokens(text)
        if not subject:
            return True

        topic_tokens = {
            token
            for token in re.findall(r"[a-zA-Zа-яё0-9]{3,}", str(topic).lower())
            if token not in cls._GOAL_STOPWORDS
        }
        if not topic_tokens:
            return False

        # Совпадение по корню: «мир» ⊂ «мире», «факт» ⊂ «фактов».
        for sub in subject:
            for word in topic_tokens:
                if sub == word or sub in word or word in sub:
                    return True

        # Или тема связана с темой цели в ментальной модели.
        try:
            related = self.mental_models.find_related_concepts(topic, max_depth=1)
            related_names = {
                str(item.get("concept", "")).lower()
                for item in (related or [])
            }
        except Exception:
            related_names = set()
        return bool(subject & related_names)

    @staticmethod
    def _match_rule_to_goal(goal_title: str, rule: dict) -> bool:
        """Проверяет, подходит ли правило к заголовку цели."""
        match_titles = rule.get("match_title", []) or []
        title_lower = goal_title.lower()
        return any(kw.lower() in title_lower for kw in match_titles)

    @staticmethod
    def _topic_matches_rule(topic: str, rule: dict) -> bool:
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

    def _check_goal_progress(
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
            progress_now = self._goal_progress.get(
                self.active_goal.get("id"), {}
            )
            result["pct"] = int(progress_now.get("percentage", 0))
            return result

        goal_title = self.active_goal.get("title", "")
        goal_id = self.active_goal.get("id")

        # Гарантируем наличие записи прогресса
        progress = self._goal_progress.setdefault(goal_id, {
            "matched_concepts": set(),
            "percentage": 0,
            "last_update_cycle": 0,
        })
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
                "matches_needed": max(1, int(
                    getattr(LR_CONFIG, "PROGRESS_KNOWLEDGE_MATCHES", 5)
                )),
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
        if general_fallback and not self._topic_is_relevant_to_goal(
            goal_title, topic
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
        min_increment = max(0, int(
            getattr(LR_CONFIG, "MIN_PROGRESS_INCREMENT", 0)
        ))
        completed = percentage >= 100
        if not completed and percentage - int(progress.get("percentage", 0)) < min_increment:
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
