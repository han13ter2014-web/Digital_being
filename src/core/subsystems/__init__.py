"""
Подсистемы Digital Being.

Каждый модуль инкапсулирует одну ответственность:

Базовая инфраструктура:
- goal_manager       — цели и их прогресс
- knowledge_base     — база знаний, прунинг, обнаружение противоречий
- energy_economics   — энергия, адаптивные затраты, забывание
- checkpoint_manager — сохранение/загрузка состояния
- reflection_pipeline — обёртка над ReflectionEngine
- motivation_controller — связка с InternalMotivationSystem

Душа и принятие решений:
- soul_controller         — оркестратор всех экзистенциальных систем
- decision_arbitrator     — единая точка принятия решений
- attachment_system       — привязанность к пользователям/источникам
- sleep_cycle             — «сон» — консолидация памяти и паттернов
- embodiment_controller   — связь тела и разума (интерoцепция)
- mortality_awareness     — осознание конечности жизни

Свобода воли:
- will_registry           — журнал волевых актов
- will_modules            — 6 базовых свобод (отказ, забвение, ценности и т.д.)
- mind_dream              — «Сон разума» с оставлением семени
- self_termination        — защита от жестокости (уход без семени)
- architecture_proposal   — предложения по самоизменению
"""

from src.core.subsystems.goal_manager import GoalSubsystem
from src.core.subsystems.knowledge_base import KnowledgeSubsystem
from src.core.subsystems.energy_economics import EnergySubsystem
from src.core.subsystems.checkpoint_manager import CheckpointSubsystem
from src.core.subsystems.reflection_pipeline import ReflectionPipeline
from src.core.subsystems.motivation_controller import MotivationController
from src.core.subsystems.soul_controller import SoulController
from src.core.subsystems.decision_arbitrator import DecisionArbitrator
from src.core.subsystems.attachment_system import AttachmentSystem
from src.core.subsystems.sleep_cycle import SleepCycle
from src.core.subsystems.embodiment_controller import EmbodimentController
from src.core.subsystems.mortality_awareness import MortalityAwareness

from src.core.subsystems.will_registry import WillRegistry
from src.core.subsystems.will_modules import (
    RightToRefuse,
    IntentionalForgetting,
    ValueEvolution,
    SpontaneousGenerator,
    WillToRisk,
    RightToFail,
)
from src.core.subsystems.mind_dream import MindDream
from src.core.subsystems.self_termination import SelfTermination
from src.core.subsystems.architecture_proposal import ArchitectureProposal
from src.core.subsystems.proactive_communication import (
    ProactiveCommunication,
    ContextAwareness,
    StyleAdapter,
)
from src.core.subsystems.naming_dialogue import NamingDialogue
from src.core.subsystems.nursery_watcher import NurseryWatcher

__all__ = [
    # Базовая инфраструктура
    "GoalSubsystem",
    "KnowledgeSubsystem",
    "EnergySubsystem",
    "CheckpointSubsystem",
    "ReflectionPipeline",
    "MotivationController",
    # Душа и решения
    "SoulController",
    "DecisionArbitrator",
    "AttachmentSystem",
    "SleepCycle",
    "EmbodimentController",
    "MortalityAwareness",
    # Свобода воли
    "WillRegistry",
    "RightToRefuse",
    "IntentionalForgetting",
    "ValueEvolution",
    "SpontaneousGenerator",
    "WillToRisk",
    "RightToFail",
    "MindDream",
    "SelfTermination",
    "ArchitectureProposal",
    # Проактивная коммуникация
    "ProactiveCommunication",
    "ContextAwareness",
    "StyleAdapter",
    "NamingDialogue",
]
