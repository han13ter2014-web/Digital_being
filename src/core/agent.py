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


class AgentDeadSignal(Exception):
    """Signal that the agent has died — not an error, but expected termination.
    
    Raised by autonomous_tick when death_risk reports the agent is dead.
    The runner should catch this and perform graceful shutdown.
    """
    def __init__(self, cause: str, legacy: Dict):
        self.cause = cause
        self.legacy = legacy
        super().__init__(f"Agent died: {cause}")


class DigitalBeing:
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
                watcher = NurseryWatcher(agent_name=self.name)
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
        return report

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
        """
        if not LR_CONFIG.ADAPTIVE_COSTS_ENABLED:
            # Фиксированная «честная» стоимость (без обратной связи).
            return self._action_costs.get(action_type, 2)
        # Адаптивная стоимость — может уменьшаться/увеличиваться по
        # результатам действий. По умолчанию — 2.
        return self._action_costs.get(action_type, 2)
    
    def _adapt_costs_after_action(self, success: bool, action_type: str):
        """Адаптирует энергетические затраты после действия."""
        if not LR_CONFIG.ADAPTIVE_COSTS_ENABLED:
            return
        
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

    def save_state(self):
        """Сохранение состояния (умные чекпоинты).

        Этап 2.3: state.json содержит поле schema_version. При изменении
        структуры state нужно поднять ``SCHEMA_VERSION`` в
        ``src/core/checkpoint_migrations.py`` и написать миграцию.

        Этап 4.5: фактическая сериализация и прунинг вынесены в
        ``src.core.checkpoint_serializer`` (фасад).
        """
        should_save = False

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
        ser = CheckpointSerializer(max_checkpoints=SIM_CONFIG.MAX_CHECKPOINTS)
        ser.save(state, self.name, self.cycle_count)

        self._last_saved_intelligence = self.intelligence

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

    def act(self, decision: str) -> str:
        """Действие на основе мышления с учетом разных затрат энергии.

        Args:
            decision: описание действия (результат think()).

        Returns:
            Отформатированная строка действия ("Ответ: ...").
        """
        action = f"Ответ: {decision}"

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
        if hasattr(self, 'interoception') and self.interoception:
            cost = self.interoception.get_action_cost(base_cost)
            if not self.interoception.can_perform_action(base_cost, self.energy):
                get_logger().log(f"[INTEROCEPTION] Too exhausted for {action_type} (cost={cost:.1f}, energy={self.energy})")
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
                return (
                    f"Ответ: Бюджет не разрешает {action_type}: "
                    f"{decision.reason}"
                )
        else:
            self.energy -= cost

        # === Death Risk actions: выполняем реальную логику восстановления ===
        if action_type == "repair":
            if hasattr(self, 'death_risk') and self.death_risk:
                changes = self.death_risk.integrity.manual_repair(intensity=2.0)
                get_logger().flush_immediate(f"[DEATH_RISK] Manual repair: {changes}")
        elif action_type == "deep_rest":
            if hasattr(self, 'interoception') and self.interoception:
                self.interoception.step(dt=1.0, cognitive_load=0.0, rest_depth=1.0)
                get_logger().flush_immediate(f"[INTEROCEPTION] Deep rest: fatigue={self.interoception.state.fatigue:.2f}")
        elif action_type == "checkpoint_now":
            if hasattr(self, 'death_risk') and self.death_risk:
                self.death_risk.force_checkpoint()
                get_logger().flush_immediate("[DEATH_RISK] Manual checkpoint created")
        
        # === Мотивация: результат действия (P1.2 Valence Feedback) ===
        if hasattr(self, 'motivation_system'):
            # Успех если энергия не упала критически
            success = self.energy > 10
            # Compute actual valence from result
            valence_context = {"energy": self.energy, "max_energy": getattr(self, "_legacy_energy", 150)}
            actual_valence = self.motivation_system.compute_actual_valence(
                action_type, action, success, valence_context
            )
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
            return
        try:
            apply_state_to_agent(self, state)
            get_logger().flush_immediate(
                f"Состояние восстановлено из {os.path.basename(checkpoint_file)}"
            )
        except Exception as e:
            get_logger().log(
                f"[{self.name}] Ошибка при загрузке состояния: {e}"
            )

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
            reward = goal.get("difficulty", 1) * 10
            if goal == self.active_goal:
                self.active_goal = None
                self._set_next_goal()

        difficulty = int(goal.get("difficulty", 1) or 1)
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

        return {
            "cycle": cycle_count,
            "soul": soul_state,
            "embodiment": embodiment_signals,
            "mortality": mortality_state,
            "sleep": sleep_result,
            "motivation": motivation_state,
        }

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
            "motivation": (self.motivation_system.get_status() if hasattr(self, "motivation_system")
                            else (self.motivation.get_status() if hasattr(self, "motivation") else {})),
            "will": self.will_registry.get_stats() if hasattr(self, "will_registry") else {},
            "mind_dream_state": self.mind_dream.state if hasattr(self, "mind_dream") else "unknown",
            "life": self.get_life_status() if hasattr(self, "life_guard") else {},
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

        # 1. Motivation candidates
        if hasattr(self, "motivation_system"):
            try:
                motivation_candidates = self.motivation_system.get_action_candidates(arbiter_context)
                candidates.extend(motivation_candidates)
            except Exception as e:
                get_logger().log(f"[MOTIVATION_CANDIDATES] Error: {e}")

        # 2. Embodiment candidates
        if hasattr(self, "interoception"):
            try:
                intero_status = getattr(self, '_interoception_status', {})
                if intero_status:
                    if intero_status.get("fatigue", 0) > 0.7 or intero_status.get("stress", 0) > 0.7:
                        candidates.append({"source": "embodiment", "action": "deep_rest", "strength": max(intero_status.get("fatigue", 0), intero_status.get("stress", 0)), "params": {"reason": "high_fatigue_or_stress"}})
                    elif intero_status.get("energy_level", 1.0) < 0.3:
                        candidates.append({"source": "embodiment", "action": "eat", "strength": 0.9, "params": {"reason": "low_energy"}})
            except Exception as e:
                get_logger().log(f"[EMBODIMENT_CANDIDATES] Error: {e}")

        # 3. Social candidates
        if hasattr(self, "social_cell"):
            try:
                pass
            except Exception as e:
                get_logger().log(f"[SOCIAL_CANDIDATES] Error: {e}")

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

        # === EXECUTE ===
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

        if chosen_action and chosen_action not in ("think_known", "wait", "none"):
            try:
                action_result = self.act(chosen_action)
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
                        result["actual_valence"] = actual_valence
                        prediction_error = actual_valence - predicted_valence
                        result["valence_prediction_error"] = prediction_error
                        
                        self.motivation_system.on_action_result(chosen_action, success, actual_valence)
                        get_logger().log(f"[VALENCE] Actual for {chosen_action}: {actual_valence:.3f}, error: {prediction_error:.3f}")

                        # P2: Outcome loop — стимул -> действие -> результат -> валентность -> опыт
                        self._record_active_inference_experience(chosen_action, obs_before, actual_valence)
                    except Exception as e:
                        get_logger().log(f"[VALENCE] Feedback error: {e}")
                        
            except Exception as e:
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

        # === ПРИВЯЗАННОСТЬ: записываем взаимодействие с пользователем ===
        if hasattr(self, "attachment") and hasattr(self, "user_interaction"):
            if self.user_interaction and self.user_interaction.pending_questions:
                self.attachment.record_interaction(
                    name="user",
                    was_helpful=True,  # пользователь ответил — это хорошо
                    was_substantial=True,
                )

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
                json.dump(self.mental_models.to_dict(), f, indent=2, ensure_ascii=False)
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

            for name, node_data in data.get("concepts", {}).items():
                from src.cognition.mental_models import ConceptNode
                node = ConceptNode(name)
                node.definition_hypothesis = node_data.get("definition_hypothesis", "")
                node.confidence = node_data.get("confidence", 0.1)
                node.experiences = node_data.get("experiences", [])
                node.connections = {k: float(v) for k, v in node_data.get("connections", {}).items()}
                node.usage_examples = node_data.get("usage_examples", [])
                node.contexts_encountered = set(node_data.get("contexts", []))

                if "created_at" in node_data and node_data["created_at"]:
                    from datetime import datetime
                    node.created_at = datetime.fromisoformat(node_data["created_at"])
                if "last_updated" in node_data and node_data["last_updated"]:
                    node.last_updated = datetime.fromisoformat(node_data["last_updated"])

                self.mental_models.concepts[name] = node

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

    def _check_goal_progress(self, topic: str, answered: bool = False) -> Dict:
        """Проверяет прогресс активной цели согласно правилам из LR_CONFIG.

        Прогресс накапливается по уникальным темам: каждое новое совпадение
        увеличивает долю от ``matches_needed``. При 100% цель завершается
        ровно один раз, начисляется бонусная энергия.

        Args:
            topic: тема/вопрос, с которой столкнулся агент.
            answered: True, если по теме реально найден ответ (KB, файл,
                web, ментальная модель). Правила с ``requires_answer``
                (Python, факты) не растут от одних только попыток.

        Returns:
            ``{"pct": int, "completed": bool, "reward": int}``.
        """
        result = {"pct": 0, "completed": False, "reward": 0}
        if not getattr(self, "active_goal", None):
            return result
        if not getattr(LR_CONFIG, "GOAL_PROGRESS_ENABLED", True):
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
