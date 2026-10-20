"""Пакет эволюции для самоэволюционирующегося ИИ."""

from src.evolution.thinking_patterns import (
    ThinkingPattern,
    ThinkingPatternLibrary,
)
from src.evolution.cognitive_architecture import (
    CognitiveArchitecture,
    CognitiveStyle,
    SelfModifier,
)

__all__ = [
    "ThinkingPattern",
    "ThinkingPatternLibrary",
    "CognitiveArchitecture",
    "CognitiveStyle",
    "SelfModifier",
]