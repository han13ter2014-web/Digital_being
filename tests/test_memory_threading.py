"""Тикет многопоточной записи: эпизоды жизни терялись из-за привязки SQLite к потоку.

До фикса ``record_life_episode``, вызванный из потока эффекторов, падал с
«SQLite objects created in a thread can only be used in that same thread» —
в смоук-прогоне на 30 минут 141 эпизод не был записан (лог
``[LIFE_EPISODE] не записан``). Память сущности обязана принимать записи
из любого потока процесса, а конкурентная запись одного и того же факта
не должна разрывать check-then-act на ограничении UNIQUE.

Критерий стабильности: весь файл проходит 20 прогонов подряд.
"""

from __future__ import annotations

import threading

from src.delamain.memory import MemoryStore


def _spawn(threads):
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_record_life_episode_from_foreign_threads(tmp_path):
    """Записи из чужих потоков не падают и не теряются."""
    store = MemoryStore(tmp_path / "memory.db")
    errors: list[BaseException] = []
    per_thread = 25

    def worker(index: int) -> None:
        try:
            for j in range(per_thread):
                store.record_life_episode(
                    life_id="life-test",
                    intention_id=f"intention-{index}-{j}",
                    action="deep_rest",
                    status="performed",
                )
        except BaseException as exc:  # noqa: BLE001 - собираем всё
            errors.append(exc)

    _spawn([threading.Thread(target=worker, args=(i,)) for i in range(4)])

    assert errors == []
    episodes = store.recent_life_episodes(life_id="life-test", limit=200)
    # Не «нет исключений», а «нет потерь»: ровно M×N записей, и каждый
    # intention_id на месте — ни одного пропуска.
    expected = {f"intention-{i}-{j}" for i in range(4) for j in range(per_thread)}
    recorded = {episode["task_id"] for episode in episodes}
    assert len(episodes) == 4 * per_thread
    assert recorded == expected
    store.close()


def test_same_fact_concurrent_upsert(tmp_path):
    """Check-then-act на ОДНОМ факте: потоки не рвутся на UNIQUE.

    Реальная гонка тикета многопоточной записи: несколько потоков одновременно запоминают
    один и тот же факт. Каждый проходит путь «SELECT → нет → INSERT»;
    без общего замка второй INSERT бьётся о UNIQUE constraint, и запись
    теряется. Все потоки обязаны выжить, факт обязан остаться ровно один.
    """
    store = MemoryStore(tmp_path / "memory.db")
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for _ in range(50):
                store.remember_fact("дом", "Нова живёт в компьютере")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    _spawn([threading.Thread(target=writer) for _ in range(4)])

    assert errors == []
    matching = [
        fact
        for fact in store.recent_facts(limit=200)
        if fact["key"] == "дом" and fact["value"] == "Нова живёт в компьютере"
    ]
    assert len(matching) == 1
    store.close()


def test_recall_while_remembering_same_topic(tmp_path):
    """Реалистичный профиль: чтение и запись одной темы параллельно.

    Пока один поток запоминает факты об «обучении», другие непрерывно
    вспоминают по той же теме и пишут ту же самомодель. Ни одно чтение
    не должно упасть на полузаписанном состоянии, ни одна запись —
    потеряться.
    """
    store = MemoryStore(tmp_path / "memory.db")
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for i in range(30):
                store.remember_fact("обучение", f"факт об обучении {i}")
                store.set_self_model("последняя тема", f"обучение {i}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(60):
                store.recall_facts("обучение")
                store.recent_facts(limit=5)
                store.get_self_model("последняя тема")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    _spawn(
        [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
    )

    assert errors == []
    facts = store.recall_facts("обучение", limit=50)
    assert len({fact["value"] for fact in facts}) == 30
    store.close()
