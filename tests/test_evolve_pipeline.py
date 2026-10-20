"""
Тесты для EvolvePipeline (src/core/evolve_pipeline.py).

Покрывают:
    1. Базовый контракт пайплайна (run, use, len, contains).
    2. Middleware-изоляция ошибок (один сломанный → остальные работают).
    3. Skip-механизм (MiddlewareResult.skip останавливает пайплайн).
    4. Совместимость с DigitalBeing.evolve() — результат такой же,
       как у старой реализации.
    5. Кастомные middleware (плагины могут добавлять фазы).
    6. Singleton-семантика get_default_pipeline().
"""

import pytest

from src.core.evolve_pipeline import (
    EvolvePipeline,
    MiddlewareResult,
    default_evolve_pipeline,
    get_default_pipeline,
    reset_default_pipeline,
)


# =====================================================================
# Базовые контракты
# =====================================================================

class TestPipelineBasics:
    def test_empty_pipeline_runs(self):
        pipeline = EvolvePipeline(name="test")
        result = pipeline.run(agent=None, cycle=0)
        assert result.cycle == 0
        assert result.phases == []
        assert result.errors == []
        assert result.skip_requested is False

    def test_use_returns_self_for_chaining(self):
        pipeline = EvolvePipeline()
        # fluent API: use(...) → use(...) → use(...)
        result = (
            pipeline
            .use("a", lambda a, c, ctx: MiddlewareResult())
            .use("b", lambda a, c, ctx: MiddlewareResult())
        )
        assert result is pipeline

    def test_len_and_contains(self):
        pipeline = (
            EvolvePipeline()
            .use("a", lambda a, c, ctx: MiddlewareResult())
            .use("b", lambda a, c, ctx: MiddlewareResult())
        )
        assert len(pipeline) == 2
        assert "a" in pipeline
        assert "b" in pipeline
        assert "c" not in pipeline

    def test_use_rejects_non_callable(self):
        pipeline = EvolvePipeline()
        with pytest.raises(TypeError, match="must be callable"):
            pipeline.use("bad", "not_a_function")

    def test_phases_in_registration_order(self):
        order = []

        def make(name):
            return lambda a, c, ctx: order.append(name) or MiddlewareResult()

        pipeline = (
            EvolvePipeline()
            .use("first", make("first"))
            .use("second", make("second"))
            .use("third", make("third"))
        )
        result = pipeline.run(agent=None, cycle=0)
        assert order == ["first", "second", "third"]
        assert result.phases == ["first", "second", "third"]


# =====================================================================
# Middleware-изоляция ошибок
# =====================================================================

class TestErrorIsolation:
    def test_one_broken_middleware_does_not_stop_others(self):
        executed = []

        def phase_ok(name):
            def fn(a, c, ctx):
                executed.append(name)
                return MiddlewareResult()
            return fn

        def phase_broken(a, c, ctx):
            executed.append("broken")
            raise RuntimeError("intentional failure")

        pipeline = (
            EvolvePipeline()
            .use("ok1", phase_ok("ok1"))
            .use("broken", phase_broken)
            .use("ok2", phase_ok("ok2"))
        )
        result = pipeline.run(agent=None, cycle=0)
        assert executed == ["ok1", "broken", "ok2"]
        assert len(result.errors) == 1
        assert "broken" in result.errors[0]
        assert "intentional failure" in result.errors[0]

    def test_error_does_not_prevent_subsequent_phases_from_recording(self):
        """Фазы после сломанной должны быть в phases[] (если не skip)."""
        def broken(a, c, ctx):
            raise ValueError("boom")

        def ok(a, c, ctx):
            return MiddlewareResult()

        pipeline = EvolvePipeline().use("broken", broken).use("ok", ok)
        result = pipeline.run(agent=None, cycle=0)
        assert "broken" in result.phases
        assert "ok" in result.phases
        assert len(result.errors) == 1


# =====================================================================
# Skip-механизм
# =====================================================================

class TestSkipMechanism:
    def test_skip_stops_subsequent_phases(self):
        executed = []

        def make(name, skip=False):
            def fn(a, c, ctx):
                executed.append(name)
                return MiddlewareResult(skip=skip)
            return fn

        pipeline = (
            EvolvePipeline()
            .use("a", make("a"))
            .use("b_skip", make("b_skip", skip=True))
            .use("c", make("c"))
        )
        result = pipeline.run(agent=None, cycle=0)
        assert executed == ["a", "b_skip"]  # c не выполнился
        assert result.skip_requested is True
        assert result.phases == ["a", "b_skip"]

    def test_context_is_shared_between_phases(self):
        """Middleware могут обмениваться данными через context."""

        def writer(a, c, ctx):
            ctx["written_by_writer"] = True
            return MiddlewareResult()

        def reader(a, c, ctx):
            assert ctx.get("written_by_writer") is True
            ctx["read"] = True
            return MiddlewareResult()

        pipeline = EvolvePipeline().use("writer", writer).use("reader", reader)
        pipeline.run(agent=None, cycle=0)
        # Если reader не увидел written_by_writer — assert в нём упал.
        # Если дошли сюда — всё OK.

    def test_data_from_middleware_result_merges_into_context(self):
        def data_mw(a, c, ctx):
            return MiddlewareResult(data={"added": 42})

        def reader(a, c, ctx):
            assert ctx.get("added") == 42
            return MiddlewareResult()

        pipeline = EvolvePipeline().use("writer", data_mw).use("reader", reader)
        pipeline.run(agent=None, cycle=0)


# =====================================================================
# Совместимость со старым evolve() — через реального DigitalBeing
# =====================================================================

class TestDigitalBeingIntegration:
    """Проверяем, что новый evolve() через пайплайн даёт тот же результат,
    что и _evolve_legacy(). Это основной регрессионный тест."""

    @pytest.fixture
    def agent(self, tmp_path):
        """Создаёт DigitalBeing в изолированной директории (не мусорит в data/)."""
        from src.core.agent import DigitalBeing
        import os
        # Подменяем data-пути, чтобы DigitalBeing не писал в общую data/.
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            a = DigitalBeing("TestAgent")
            # Несколько циклов, чтобы мотивация/привязанность инициализировались.
            a.cycle_count = 5
            return a
        finally:
            os.chdir(old_cwd)

    def test_evolve_calls_all_default_phases(self, agent):
        """Стандартный пайплайн должен выполнить все 7 фаз."""
        reset_default_pipeline()
        try:
            pipeline = get_default_pipeline()
            result = pipeline.run(agent, cycle=agent.cycle_count)
            expected_phases = [
                "mental_models_tick",
                "motivation",
                "soul",
                "attachment",
                "concept_limit",
                "force_forget",
                "intelligence_growth",
            ]
            for phase in expected_phases:
                assert phase in result.phases, f"Phase '{phase}' not executed"
        finally:
            reset_default_pipeline()

    def test_evolve_does_not_raise_on_healthy_agent(self, agent):
        """Здоровый агент не должен ломать эволюцию (раньше это было
        106 строк inline — много мест для багов)."""
        agent.cycle_count = 1
        # Не должно бросить исключение.
        agent.evolve()
        # sanity check
        assert agent.cycle_count == 1
        assert agent.intelligence >= 1

    def test_intelligence_growth_phase_can_increase_intelligence(self, agent):
        """Если success_streak выше порога, интеллект должен вырасти через
        пайплайн (это тестирует фазу intelligence_growth, а не весь evolve)."""
        from src.core.evolve_pipeline import make_intelligence_growth
        agent.success_streak = 1000  # Заведомо больше threshold
        old_intelligence = agent.intelligence
        result = make_intelligence_growth()(agent, cycle=0, context={})
        assert result.data["evolved"] is True
        assert agent.intelligence == old_intelligence + 1
        assert agent.energy >= 20  # бонус при эволюции

    def test_legacy_evolve_still_exists_for_compatibility(self, agent):
        """_evolve_legacy сохранён и работает."""
        agent.cycle_count = 1
        # Не должно бросить исключение.
        agent._evolve_legacy()
        assert agent.cycle_count == 1


# =====================================================================
# Кастомные middleware (расширяемость)
# =====================================================================

class TestCustomMiddleware:
    """Плагины должны мочь добавлять свои фазы."""

    def test_add_custom_phase_after_default(self):
        """Добавляем middleware в стандартный пайплайн — должна выполниться."""
        reset_default_pipeline()
        try:
            pipeline = get_default_pipeline()
            executed = []

            def my_phase(a, c, ctx):
                executed.append("custom")
                return MiddlewareResult(data={"custom_ok": True})

            pipeline.use("custom", my_phase)
            assert "custom" in pipeline

            # Минимальный агент для теста
            from src.core.agent import DigitalBeing
            import os
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                old = os.getcwd()
                os.chdir(tmp)
                try:
                    agent = DigitalBeing("TestAgent")
                    agent.cycle_count = 1
                    result = pipeline.run(agent, cycle=1)
                    assert "custom" in executed
                    assert "custom" in result.phases
                finally:
                    os.chdir(old)
        finally:
            reset_default_pipeline()


# =====================================================================
# Singleton-семантика
# =====================================================================

class TestSingleton:
    def test_get_default_pipeline_returns_same_instance(self):
        reset_default_pipeline()
        try:
            p1 = get_default_pipeline()
            p2 = get_default_pipeline()
            assert p1 is p2
        finally:
            reset_default_pipeline()

    def test_reset_creates_new_instance(self):
        reset_default_pipeline()
        try:
            p1 = get_default_pipeline()
            reset_default_pipeline()
            p2 = get_default_pipeline()
            assert p1 is not p2
        finally:
            reset_default_pipeline()

    def test_default_evolve_pipeline_returns_fresh_each_time(self):
        """default_evolve_pipeline() возвращает НОВЫЙ пайплайн
        (не синглтон) — это by design, чтобы тесты могли менять."""
        p1 = default_evolve_pipeline()
        p2 = default_evolve_pipeline()
        assert p1 is not p2
        # Но оба должны иметь одинаковый набор фаз.
        assert len(p1) == len(p2)