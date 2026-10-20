"""
test_benchmarks.py — pytest-benchmark suite для автодетекции регрессий.

Покрывает горячие точки, которые вызываются каждый цикл:
- mental_models.tick_cycle() + encounter_concept()
- MentalModel.find_related_concepts() (холодный/тёплый путь)
- MentalModel.apply_concept_limit() (форс-забывание)
- Concept.connect_to() + поиск связей
- Watchdog.on_cycle_*() (с/без psutil)
- metrics_collector.collect_metrics() (singleton)
- CheckpointSerializer.dump_dict() / gzip round-trip

Использование:
    python -m pytest tests/benchmarks/ --benchmark-only
    python -m pytest tests/benchmarks/ --benchmark-only --benchmark-compare=baseline.json

Базовый снимок (baseline.json) — коммитится в репо. При существенном
замедлении CI может падать, требуя ревью.
"""
import gzip
import os
import sys
import time
import random

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Принудительно UTF-8 (Windows-cmd: cp1251).
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ============================================================
# MentalModel — горячая точка цикла (вызывается N раз в секунду)
# ============================================================
class TestMentalModelBenchmarks:
    """Производительность MentalModel — критический путь цикла."""

    def _make_populated_mm(self, n_concepts: int = 200):
        """Создаёт MentalModel с N концепциями и связями."""
        from src.cognition.mental_models import MentalModel
        mm = MentalModel(name="bench")
        for i in range(n_concepts):
            mm.encounter_concept(f"c_{i}", f"ctx_{i}", "outcome", 0.5)
            if i > 0:
                # Каждая новая концепция связана с 2-3 предыдущими.
                for j in range(max(0, i - 3), i):
                    mm.concepts[f"c_{i}"].connect_to(f"c_{j}", 0.6)
        return mm

    def test_bench_encounter_concept(self, benchmark):
        """encounter_concept — добавление новой концепции. Цель: < 5 мс."""
        from src.cognition.mental_models import MentalModel
        mm = MentalModel(name="bench")
        counter = {"i": 0}

        def run():
            i = counter["i"]
            mm.encounter_concept(f"c_{i}", f"ctx_{i}", "outcome", 0.5)
            counter["i"] += 1
            return i

        result = benchmark(run)
        assert result is not None  # Sanity-check: функция не упала.

    def test_bench_tick_cycle(self, benchmark):
        """tick_cycle — фоновая обработка. Цель: < 50 мс для 200 концепций."""
        mm = self._make_populated_mm(n_concepts=200)
        benchmark(mm.tick_cycle)

    def test_bench_find_related_cold(self, benchmark):
        """find_related_concepts (холодный путь, без кеша). Цель: < 20 мс."""
        mm = self._make_populated_mm(n_concepts=200)
        mm._find_related_cache = None  # сбрасываем кеш принудительно
        # tick_cycle заполнит кеш — для чистоты бенчмарка пропускаем.

        def run():
            mm._find_related_cache = None  # каждый раз холодный
            return mm.find_related_concepts("c_100", max_distance=2)

        result = benchmark(run)
        assert isinstance(result, list)

    def test_bench_find_related_warm(self, benchmark):
        """find_related_concepts (тёплый путь, с кешем). Цель: < 1 мс."""
        mm = self._make_populated_mm(n_concepts=200)
        mm.tick_cycle()  # заполняем кеш
        result = benchmark(mm.find_related_concepts, "c_100", 2)
        assert isinstance(result, list)

    def test_bench_apply_concept_limit_no_op(self, benchmark):
        """apply_concept_limit когда лимит не превышен. Цель: < 1 мс."""
        from src.cognition.mental_models import MentalModel
        mm = MentalModel(name="bench")
        for i in range(10):  # сильно ниже MAX_CONCEPTS
            mm.encounter_concept(f"c_{i}", f"ctx_{i}", "o", 0.5)
        result = benchmark(mm.apply_concept_limit)
        assert result == 0  # ничего не забыли

    def test_bench_apply_concept_limit_overflow(self, benchmark):
        """apply_concept_limit при переполнении (200 → 100). Цель: < 50 мс."""
        from config import simulation_config
        from src.cognition.mental_models import MentalModel

        mm = self._make_populated_mm(n_concepts=200)
        original = simulation_config.LR_CONFIG.MAX_CONCEPTS

        def run():
            simulation_config.LR_CONFIG.MAX_CONCEPTS = 100
            try:
                return mm.apply_concept_limit()
            finally:
                simulation_config.LR_CONFIG.MAX_CONCEPTS = original

        forgotten = benchmark(run)
        assert forgotten >= 0


# ============================================================
# Watchdog — вызывается каждый цикл
# ============================================================
class TestWatchdogBenchmarks:
    """Производительность Watchdog.on_cycle_*."""

    def test_bench_watchdog_on_cycle_end(self, benchmark):
        """on_cycle_end — фиксация длительности цикла. Цель: < 1 мс."""
        from src.core.watchdog import Watchdog

        wd = Watchdog(max_rss_mb=10_000.0, max_cycle_seconds=60.0, check_interval_cycles=1000)

        def run():
            wd.on_cycle_start()
            wd.on_cycle_end()
            return wd.get_status()

        benchmark(run)

    def test_bench_watchdog_get_status(self, benchmark):
        """get_status — лёгкий словарь для dashboard. Цель: < 100 мкс."""
        from src.core.watchdog import Watchdog

        wd = Watchdog(max_rss_mb=10_000.0, max_cycle_seconds=60.0, check_interval_cycles=10)
        # Прогреваем — 10 циклов.
        for _ in range(10):
            wd.on_cycle_start()
            wd.on_cycle_end()
        benchmark(wd.get_status)


# ============================================================
# CheckpointSerializer — для save_state каждые ~50 циклов
# ============================================================
class TestCheckpointBenchmarks:
    """Производительность сериализации чекпоинтов."""

    def _make_state_dict(self, n_keys: int = 100):
        """Создаёт state-словарь с N ключами разных типов."""
        state = {
            "cycle_count": 12345,
            "energy": 145.5,
            "intelligence": 3.0,
            "is_alive": True,
            "agent_name": "TestAgent_" + "x" * 50,
            "concepts": {f"concept_{i}": {
                "name": f"c_{i}",
                "confidence": random.random(),
                "valence": random.random(),
                "contexts": [f"ctx_{j}" for j in range(5)],
            } for i in range(n_keys)},
            "episodes": [{"ts": time.time(), "text": "x" * 100} for _ in range(20)],
            "meta": {"version": "1.0.0", "tags": ["a", "b", "c"]},
        }
        return state

    def test_bench_checkpoint_dump(self, benchmark, tmp_path):
        """CheckpointSerializer.save — полная запись на диск. Цель: < 100 мс для 100 ключей."""
        from src.core.checkpoint_serializer import CheckpointSerializer
        state = self._make_state_dict(n_keys=100)
        serializer = CheckpointSerializer(checkpoint_dir=str(tmp_path), compress=False)

        def run():
            path = serializer.save(state, "bench_agent", 12345)
            return len(path)

        size = benchmark(run)
        assert size > 0  # путь не пустой

    def test_bench_checkpoint_gzip_roundtrip(self, benchmark, tmp_path):
        """save + gzip компрессия + load. Цель: < 300 мс для 100 ключей."""
        from pathlib import Path
        from src.core.checkpoint_serializer import CheckpointSerializer
        state = self._make_state_dict(n_keys=100)
        serializer = CheckpointSerializer(checkpoint_dir=str(tmp_path), compress=True)
        dest = tmp_path / "ckpt.json.gz"

        def run():
            path_str = serializer.save(state, "bench_agent", 12345)
            path = Path(path_str)
            data = path.read_bytes()
            compressed = gzip.compress(data)
            dest.write_bytes(gzip.decompress(compressed))
            # Для load нужен новый serializer (или тот же) — передаём str
            return CheckpointSerializer().load(str(dest))

        result = benchmark(run)
        assert result["cycle_count"] == 12345


# ============================================================
# MetricsCollector — singleton для /metrics
# ============================================================
class TestMetricsCollectorBenchmarks:
    """Производительность collect_metrics."""

    def test_bench_metrics_collect(self, benchmark):
        """snapshot — снятие всех метрик. Цель: < 5 мс."""
        from src.metrics.metrics_collector import MetricsCollector
        mc = MetricsCollector(maxlen_per_channel=720, agent_name="bench")
        # Добавляем немного данных для реалистичности
        mc.record("energy", 100.0)
        mc.record("intelligence", 1.0)
        mc.increment("cycles_total")
        benchmark(mc.snapshot)


# ============================================================
# Health dashboard — для /health endpoint
# ============================================================
class TestHealthDashboardBenchmarks:
    """Производительность collect_health."""

    def test_bench_health_collect(self, benchmark):
        """collect_health — сбор health-метрик. Цель: < 10 мс."""
        from src.core.health_dashboard import collect_health
        benchmark(collect_health, agent=None)

    def test_bench_health_format(self, benchmark):
        """format_health_report — форматирование отчёта. Цель: < 5 мс."""
        from src.core.health_dashboard import collect_health, format_health_report
        report = collect_health(agent=None)
        benchmark(format_health_report, report)


# ============================================================
# WebDashboard /metrics — Prometheus exposition
# ============================================================
class TestMetricsEndpointBenchmarks:
    """Производительность /metrics endpoint (handle_metrics)."""

    def test_bench_handle_metrics(self, benchmark):
        """handle_metrics — генерация Prometheus text. Цель: < 5 мс."""
        import asyncio
        from src.ui.web_dashboard import SharedState, handle_metrics, STATE_KEY

        state = SharedState()
        state.update_status({
            "agent": {
                "name": "BenchAgent",
                "energy": 145.5,
                "intelligence": 3.0,
                "cycle_count": 12345,
                "completed_goals": 42,
                "success_streak": 5,
            },
            "mental_models": {"total_concepts": 87},
            "system": {"current_rss_mb": 42.0},
        })
        state.update_subsystems({"subsystem_count": 12, "subsystems": []})

        class _Req:
            def __init__(self):
                self.app = {STATE_KEY: state}

        req = _Req()

        def run():
            return asyncio.run(handle_metrics(req))

        result = benchmark(run)
        # Проверяем, что это text/plain
        assert "text/plain" in result.content_type


# ============================================================
# SharedState — потокобезопасный мост
# ============================================================
class TestSharedStateBenchmarks:
    """Производительность SharedState — горячая точка dashboard."""

    def test_bench_shared_state_update_status(self, benchmark):
        """update_status — пишется каждый цикл. Цель: < 50 мкс."""
        from src.ui.web_dashboard import SharedState
        state = SharedState()
        payload = {
            "agent": {"name": "X", "energy": 100, "cycle_count": 5},
            "mental_models": {"total_concepts": 10},
            "system": {"current_rss_mb": 5.0},
        }
        benchmark(state.update_status, payload)

    def test_bench_shared_state_snapshot(self, benchmark):
        """snapshot — читается на каждый HTTP-запрос. Цель: < 100 мкс."""
        from src.ui.web_dashboard import SharedState
        state = SharedState()
        state.update_status({
            "agent": {"name": "X", "energy": 100, "cycle_count": 5},
            "mental_models": {"total_concepts": 10},
            "system": {"current_rss_mb": 5.0},
        })
        benchmark(state.snapshot)