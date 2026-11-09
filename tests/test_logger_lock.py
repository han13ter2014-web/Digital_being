"""«Харднинг-1» (k16-21): BufferedLogger под concurrent-писателями.

Вердикт k16-16 п.1: append в log() и check-then-act в flush() шли без
синхронизации — при конкурентных писателях возможны дубли/потери строк
и перемежение чанков; get_logger() без лока давал бы два инстанса при
первом одновременном вызове. Критерий: ни дублей, ни потерь, ни
перепутанных чанков — при том, что однопоточный путь не изменился.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from src.core.buffered_logger import BufferedLogger


def test_concurrent_append_flush_no_loss_no_duplicates(tmp_path):
    """Два потока, 10k строк: каждая ровно один раз, порядок чанков цел."""
    log_file = tmp_path / "logs" / "agent_log.txt"
    logger = BufferedLogger(log_file=str(log_file), buffer_size=50)
    per_thread = 10_000

    def writer(worker_id: int) -> None:
        for i in range(per_thread):
            logger.log(f"worker-{worker_id}-line-{i}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(writer, w) for w in range(2)]:
            future.result(timeout=120)
    logger.flush()

    text = log_file.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]

    # Ни потерь: каждая из 20k строк на месте.
    assert len(lines) == 2 * per_thread
    expected = {f"worker-{w}-line-{i}" for w in range(2) for i in range(per_thread)}
    seen = {line.split("] ", 1)[1] for line in lines}
    assert seen == expected

    # Ни дублей.
    assert len(seen) == len(lines)


def test_concurrent_explicit_flush_keeps_chunks_intact(tmp_path):
    """Внешний flush из третьего потока не рвёт чанки и не дублирует их."""
    log_file = tmp_path / "logs" / "agent_log.txt"
    logger = BufferedLogger(log_file=str(log_file), buffer_size=100)
    per_thread = 5_000
    stop = threading.Event()

    def writer(worker_id: int) -> None:
        for i in range(per_thread):
            logger.log(f"chunk-{worker_id}-row-{i}")

    def flusher() -> None:
        while not stop.is_set():
            logger.flush()

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(writer, w) for w in range(2)]
        flush_future = pool.submit(flusher)
        for future in futures:
            future.result(timeout=120)
        stop.set()
        flush_future.result(timeout=120)
    logger.flush()

    text = log_file.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    # Каждая строка ровно один раз — flush-поток не задублировал чанки.
    assert len(lines) == 2 * per_thread
    seen = {line.split("] ", 1)[1] for line in lines}
    assert len(seen) == len(lines)


def test_get_logger_single_instance_under_race(monkeypatch, tmp_path):
    """Первый одновременный get_logger из двух потоков — один инстанс."""
    from src.core import buffered_logger as bl

    monkeypatch.setattr(bl, "_logger", None)
    created = []

    original_init = bl.BufferedLogger.__init__

    def _spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(bl.BufferedLogger, "__init__", _spy_init)

    barrier = threading.Barrier(2)

    def first_call():
        barrier.wait(timeout=10)
        return bl.get_logger()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(first_call) for _ in range(2)]
        instances = [future.result(timeout=60) for future in futures]

    assert len(created) == 1  # ровно один инстанс, второй взял готовый
    assert instances[0] is instances[1]
