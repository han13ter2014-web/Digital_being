"""Честность спонтанных порывов: обещать можно только возможное.

Сущность не имеет тела, голоса и холста («Собеседник», верификация
2026-11-01). Промпт «Нарисовать абстрактную идею» или «Посмотреть на
небо» записывал в журнал воли желание, которое сущность заведомо не
может исполнить, — это выдумка о собственных возможностях.
"""

from src.core.subsystems.will_modules import SpontaneousGenerator
from src.core.subsystems.will_registry import WillRegistry


def test_prompts_do_not_promise_impossible_actions():
    impossible_markers = ("Нарисовать", "Посмотреть на небо", "спой", "станцуй")
    for prompt in SpontaneousGenerator.SPONTANEOUS_PROMPTS:
        for marker in impossible_markers:
            assert marker not in prompt, (
                f"сущность не должна желать невозможное: {prompt!r}"
            )


def test_prompts_are_unique_and_nonempty():
    prompts = SpontaneousGenerator.SPONTANEOUS_PROMPTS
    assert prompts
    assert all(isinstance(prompt, str) and prompt.strip() for prompt in prompts)
    assert len(prompts) == len(set(prompts))


def test_generation_uses_only_honest_prompts():
    registry = WillRegistry(agent_name="test")
    generator = SpontaneousGenerator(registry)
    seen = set()
    for cycle in range(50):
        record = generator.maybe_generate(cycle, probability=1.0)
        assert record is not None
        prompt = record["meta"]["prompt"]
        assert prompt in SpontaneousGenerator.SPONTANEOUS_PROMPTS
        seen.add(prompt)
    assert seen == set(SpontaneousGenerator.SPONTANEOUS_PROMPTS)
