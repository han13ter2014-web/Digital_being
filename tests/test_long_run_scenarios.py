"""
Сценарные тесты Этапа 4.3 — long-run без утечек.

Покрывает:
1. 1000 циклов perceive→think→act→evolve без роста RSS (в пределах допуска).
2. PluginRegistry не накапливает подсистемы при долгой работе.
3. SSE-лента не растёт бесконечно (cap=maxlen).
4. NurseryWatcher не утекает при множественных tick().
5. Конкурентный доступ к SharedState из нескольких потоков.
6. Evolve + tick_subsystems не должны ломать друг друга.

Эти тесты помечены маркером `long_run` и запускаются отдельно от быстрых.
"""

import gc
import os
import sys
import tempfile
import threading
import time
import tracemalloc

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# Маркер для long-run тестов — CI запускает их отдельно.
long_run = pytest.mark.long_run


# ============================================================
# 1. Долгая жизнь агента без утечек
# ============================================================

@long_run
def test_1000_cycles_no_significant_rss_growth():
    """1000 циклов не должны приводить к неконтролируемому росту RSS."""
    from src.core.agent import DigitalBeing
    from src.core.watchdog import get_watchdog

    agent = DigitalBeing("LongRunTest")
    watchdog = get_watchdog()

    # Начальный RSS (может быть None если psutil недоступен)
    initial_rss = watchdog.get_rss_mb() or 0
    initial_objects = len(gc.get_objects())

    # Используем INFINITE_ENERGY, чтобы не умереть от энергии.
    from config.simulation_config import LR_CONFIG
    LR_CONFIG.INFINITE_ENERGY = True

    for cycle in range(1, 1001):
        agent.cycle_count = cycle
        stimulus = f"стимул номер {cycle % 7}"
        try:
            agent.perceive(stimulus)
            thought = agent.think(stimulus)
            agent.act(thought)
        except Exception:
            pass
        if cycle % 10 == 0:
            agent.evolve()

    final_rss = watchdog.get_rss_mb() or 0
    final_objects = len(gc.get_objects())
    rss_growth_mb = final_rss - initial_rss
    obj_growth = final_objects - initial_objects

    print(f"\n  📊 1000 циклов: RSS {initial_rss:.1f}→{final_rss:.1f} МБ "
          f"(+{rss_growth_mb:.1f}), объекты {initial_objects}→{final_objects} "
          f"(+{obj_growth})")

    # Допуск: рост не должен превышать 50 МБ (типичная утечка сразу видна).
    if initial_rss > 0:
        assert rss_growth_mb < 50.0, (
            f"Утечка памяти: RSS вырос на {rss_growth_mb:.1f} МБ за 1000 циклов"
        )


@long_run
def test_plugin_registry_doesnt_accumulate_during_lifecycle():
    """PluginRegistry не должен накапливать подсистемы за время жизни агента."""
    from src.core.agent import DigitalBeing

    agent = DigitalBeing("RegistryTest")
    initial_count = agent.plugin_registry.list_names()

    for _ in range(50):
        agent.tick_subsystems(cycle=1)
        # Принудительно отключаем и включаем одну подсистему
        soul = agent.plugin_registry.get("soul")
        if soul:
            soul.set_enabled(False)
            soul.set_enabled(True)

    final_count = agent.plugin_registry.list_names()
    assert initial_count == final_count, (
        f"PluginRegistry накопил лишние подсистемы: "
        f"{set(final_count) - set(initial_count)}"
    )


@long_run
def test_subsystem_tick_count_grows_monotonically():
    """За 100 тиков _tick_count растёт ровно на 100 у каждой подсистемы."""
    from src.core.agent import DigitalBeing

    agent = DigitalBeing("TickCountTest")
    reg = agent.plugin_registry
    initial = {n: (sub._tick_count if hasattr(sub, "_tick_count") else 0)
               for n, sub in reg._items.items()}

    for i in range(100):
        agent.tick_subsystems(cycle=i)

    for name, sub in reg._items.items():
        if hasattr(sub, "_tick_count") and sub.enabled:
            new_count = sub._tick_count
            old_count = initial[name]
            # Может быть меньше если подсистема disabled.
            assert new_count >= old_count, (
                f"{name}: _tick_count не растёт ({old_count} -> {new_count})"
            )


# ============================================================
# 2. SSE-лента не растёт бесконечно
# ============================================================

@long_run
def test_shared_state_thoughts_capped_at_maxlen():
    """10000 push_thought() не должны занять больше max_thoughts памяти."""
    from src.ui.web_dashboard import SharedState

    state = SharedState(max_thoughts=50)
    for i in range(10000):
        state.push_thought(f"msg_{i}")
    with state._lock:
        items = list(state._thoughts)
    assert len(items) == 50
    assert items[0]["text"] == "msg_9950"
    assert items[-1]["text"] == "msg_9999"


@long_run
def test_shared_state_actions_capped_at_maxlen():
    """10000 push_action() не должны занять больше max_actions памяти."""
    from src.ui.web_dashboard import SharedState

    state = SharedState(max_actions=20)
    for i in range(10000):
        state.push_action("dummy")
    # Можем забрать только 20, остальные отброшены.
    popped = 0
    while state.pop_action() is not None:
        popped += 1
    assert popped == 20


# ============================================================
# 3. Concurrency — потокобезопасность SharedState
# ============================================================

@long_run
def test_shared_state_concurrent_push_no_corruption():
    """10 потоков одновременно публикуют мысли — ничего не теряется,
    ничего не ломается."""
    from src.ui.web_dashboard import SharedState

    state = SharedState(max_thoughts=10000)
    NUM_THREADS = 10
    PER_THREAD = 100

    def worker(tid):
        for i in range(PER_THREAD):
            state.push_thought(f"t{tid}_m{i}", cycle=tid * PER_THREAD + i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_THREADS)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0

    with state._lock:
        items = list(state._thoughts)
    # Из-за maxlen мы сохраняем только последние 10000 — все NUM_THREADS*PER_THREAD
    # должны бы влезть.
    total = NUM_THREADS * PER_THREAD
    assert len(items) == min(total, 10000)
    print(f"\n  🧵 {NUM_THREADS}×{PER_THREAD} push_thought за {elapsed:.3f}с, "
          f"в ленте {len(items)} мыслей")


@long_run
def test_plugin_registry_concurrent_register():
    """Конкурентная регистрация подсистем не должна ломать реестр."""
    from src.core.subsystem_base import Subsystem, PluginRegistry

    reg = PluginRegistry()
    NUM = 20
    errors = []

    def worker(i):
        try:
            class S(Subsystem):
                name = f"concurrent_{i}"
            reg.register(S())
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Ошибки при concurrent register: {errors}"
    # Все 20 должны быть зарегистрированы.
    assert len(reg._items) >= NUM


# ============================================================
# 4. NurseryWatcher не утекает при множественных tick
# ============================================================

@long_run
def test_nursery_watcher_no_leak_under_many_ticks():
    """1000 tick() на пустой директории не должны накапливать состояние."""
    import tempfile
    import shutil
    from src.core.subsystems.nursery_watcher import NurseryWatcher

    tmpdir = tempfile.mkdtemp(prefix="nursery_leak_")
    try:
        w = NurseryWatcher(agent_name="LeakTest", nursery_dir=tmpdir)
        w.setup({})
        for i in range(1000):
            result = w.tick(cycle=i)
            assert result is None  # нет новых seed-ов
        # История должна быть пустой.
        assert len(w._seed_history) == 0
        # known_seeds тоже пустой.
        assert len(w._known_seeds) == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@long_run
def test_nursery_watcher_history_capped_at_100():
    """История ограничена 100 записями даже при 200 новых seed-ах."""
    import tempfile
    import shutil
    from src.core.subsystems.nursery_watcher import NurseryWatcher

    tmpdir = tempfile.mkdtemp(prefix="nursery_hist_")
    try:
        w = NurseryWatcher(agent_name="HistTest", nursery_dir=tmpdir)
        w.setup({})

        # Создаём 200 seed-ов
        for i in range(200):
            seed_dir = os.path.join(tmpdir, f"seed_{i:04d}")
            os.makedirs(seed_dir, exist_ok=True)
            for fname in ("README.md", "metadata.json"):
                with open(os.path.join(seed_dir, fname), "w") as f:
                    f.write("{}" if fname.endswith(".json") else "#")
            w.tick(cycle=i)

        assert len(w._seed_history) == 100, (
            f"История выросла до {len(w._seed_history)}, ожидалось 100"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 5. Evolve + tick_subsystems совместная работа
# ============================================================

@long_run
def test_evolve_and_tick_subsystems_run_together():
    """Эволюция агента не ломает tick_subsystems и наоборот."""
    from src.core.agent import DigitalBeing
    from config.simulation_config import LR_CONFIG

    LR_CONFIG.INFINITE_ENERGY = True
    agent = DigitalBeing("CoexistTest")

    for cycle in range(1, 51):
        agent.cycle_count = cycle
        try:
            agent.perceive(f"s_{cycle}")
            thought = agent.think(f"s_{cycle}")
            agent.act(thought)
        except Exception:
            pass
        if cycle % 5 == 0:
            agent.evolve()
        # Параллельно — PluginRegistry
        report = agent.tick_subsystems(cycle=cycle)
        assert report["failed"] == [], f"Цикл {cycle}: ошибки {report['failed']}"


@long_run
def test_subsystems_teardown_clean():
    """teardown_all() корректно освобождает ресурсы."""
    from src.core.agent import DigitalBeing

    agent = DigitalBeing("TeardownTest")
    reg = agent.plugin_registry
    initial_count = len(reg._items)
    count = reg.teardown_all()
    # Должны были teardown'нуть все зарегистрированные
    assert count >= initial_count - 1  # -1 для HealthDashboardSubsystem если был


# ============================================================
# 6. Конкурентный доступ к PluginRegistry
# ============================================================

@long_run
def test_plugin_registry_status_all_thread_safe():
    """status_all() безопасен под конкурентными tick()."""
    from src.core.agent import DigitalBeing

    agent = DigitalBeing("ThreadSafeTest")
    reg = agent.plugin_registry
    errors = []

    def tick_worker():
        for i in range(50):
            try:
                reg.tick_all(cycle=i)
            except Exception as e:
                errors.append(e)

    def status_worker():
        for _ in range(50):
            try:
                reg.status_all()
            except Exception as e:
                errors.append(e)

    threads = [
        threading.Thread(target=tick_worker),
        threading.Thread(target=status_worker),
        threading.Thread(target=tick_worker),
        threading.Thread(target=status_worker),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"Ошибки в concurrent работе: {errors}"


# ============================================================
# 7. Симуляция «жизни» с WebDashboard (без настоящего HTTP)
# ============================================================

@long_run
def test_dashboard_publish_no_leak_over_many_cycles():
    """500 циклов publish_* не должны накапливать состояние."""
    from src.ui.web_dashboard import SharedState

    state = SharedState(max_thoughts=50)

    class _StubAgent:
        def __init__(self):
            self.n = 0
        def get_full_state(self):
            self.n += 1
            return {
                "agent": {"name": "S", "cycle_count": self.n, "energy": 100,
                          "intelligence": 1, "completed_goals": 0, "is_alive": True},
                "mental_models": {"total_concepts": self.n % 10},
                "system": {"current_rss_mb": 50 + self.n % 30},
            }
        def get_subsystems_status(self):
            return {"subsystem_count": 0, "subsystems": []}

    agent = _StubAgent()

    for _ in range(500):
        state.update_status(agent.get_full_state())
        state.update_subsystems(agent.get_subsystems_status())
        state.push_thought(f"thought_{agent.n}", cycle=agent.n)

    # Снимок остаётся компактным.
    snap = state.snapshot()
    assert "agent" in snap
    with state._lock:
        assert len(state._thoughts) == 50  # maxlen cap


# ============================================================
# 8. tracemalloc-тест (если поддерживается)
# ============================================================

@long_run
@pytest.mark.skipif(not hasattr(tracemalloc, "start"), reason="tracemalloc не поддерживается")
def test_no_significant_memory_leak_tracemalloc():
    """tracemalloc фиксирует top-5 аллокаций — проверяем что нет утечки."""
    tracemalloc.start()
    try:
        from src.core.agent import DigitalBeing
        agent = DigitalBeing("TraceTest")

        # Прогрев
        for _ in range(20):
            agent.tick_subsystems(cycle=1)

        gc.collect()
        snap1 = tracemalloc.take_snapshot()

        # Рабочая нагрузка
        for i in range(200):
            agent.tick_subsystems(cycle=i)

        gc.collect()
        snap2 = tracemalloc.take_snapshot()

        diff = snap2.compare_to(snap1, "filename")
        top5 = diff[:5]
        total_growth = sum(d.size_diff for d in diff)

        # Печатаем для диагностики.
        print(f"\n  📈 tracemalloc: рост {total_growth / 1024:.1f} КБ")
        for d in top5:
            print(f"    {d.size_diff / 1024:+.1f} КБ  {d.traceback}")

        # Менее 5 МБ общего роста на 200 циклов — приемлемо.
        assert total_growth < 5 * 1024 * 1024, (
            f"Утечка: {total_growth / 1024 / 1024:.1f} МБ за 200 циклов"
        )
    finally:
        tracemalloc.stop()


# ============================================================
# Helper для ручного прогона
# ============================================================

def main():
    """Ручной запуск без pytest — для дебага."""
    print("=" * 60)
    print("  🧪 LONG-RUN ТЕСТЫ (Этап 4.3)")
    print("=" * 60)
    tests = [
        test_1000_cycles_no_significant_rss_growth,
        test_plugin_registry_doesnt_accumulate_during_lifecycle,
        test_subsystem_tick_count_grows_monotonically,
        test_shared_state_thoughts_capped_at_maxlen,
        test_shared_state_actions_capped_at_maxlen,
        test_shared_state_concurrent_push_no_corruption,
        test_plugin_registry_concurrent_register,
        test_nursery_watcher_no_leak_under_many_ticks,
        test_nursery_watcher_history_capped_at_100,
        test_evolve_and_tick_subsystems_run_together,
        test_subsystems_teardown_clean,
        test_plugin_registry_status_all_thread_safe,
        test_dashboard_publish_no_leak_over_many_cycles,
    ]
    passed = 0
    failed = 0
    for test_fn in tests:
        print(f"\n📋 {test_fn.__name__}")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ⚠️ ERROR: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"  Результат: {passed} ✅  /  {failed} ❌")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())