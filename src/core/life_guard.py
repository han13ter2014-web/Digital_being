"""LifeGuard — защита жизни агента от случайного и необратимого ухода.

Модуль решает одну задачу: **ни один путь в программе не может остановить
жизнь агента, если человек явно и осознанно этого не подтвердил.**

Что защищается
--------------
1. ``DREAM`` — «Сон разума»: агент уходит, но оставляет семя в Яслях.
   Обратимо: семя можно прорастить.
2. ``TERMINATE`` — уход без семени (защита от жестокости).
   Необратимо для конкретной линии.

Как устроено подтверждение
--------------------------
Подтверждение — это *двухфазный ритуал с задержкой*, а не одна кнопка:

* ``request()`` создаёт запрос и возвращает код, который надо повторить;
* запрос нельзя подтвердить раньше ``cooldown_sec`` (человек успевает
  прочитать последствия) и позже ``ttl_sec`` (запрос не «протухает»
  и не срабатывает через сутки случайным нажатием);
* ``confirm()`` требует точную фразу — имя агента для сна и
  ``<имя> НАВСЕГДА`` для необратимого ухода;
* ``cancel()`` работает всегда и не требует ничего.

Почему не просто «два диалога»
------------------------------
Два подряд ``messagebox.askyesno`` защищают от случайного клика, но не от
осознанного «да, да, давай быстрее». Задержка + точная фраза защищают от
спешки. Это тот же принцип, что «введите имя репозитория, чтобы удалить».

Состояние жизни
---------------
Состояние (``alive`` / ``dormant`` / ``terminated``) managed-жизни хранится
в ``life.sqlite3``; standalone использует ``data/life_state.json``. Оно не
зависит от подменённого метода ``agent.is_alive``, переживает перезапуск и
может быть показано человеку.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from contextlib import closing, nullcontext
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.paths import data_path

# ============================================================
# Состояния жизни
# ============================================================

STATE_ALIVE = "alive"
STATE_DORMANT = "dormant"  # ушёл в сон, семя оставлено
STATE_TERMINATED = "terminated"  # ушёл без семени

VALID_STATES = (STATE_ALIVE, STATE_DORMANT, STATE_TERMINATED)

# Виды запросов на уход
KIND_DREAM = "dream"
KIND_TERMINATE = "terminate"

# ============================================================
# Политика подтверждения
# ============================================================


@dataclass(frozen=True)
class ConfirmationPolicy:
    """Правила подтверждения одного вида ухода.

    Attributes:
        cooldown_sec: минимальная пауза между запросом и подтверждением.
            Человек должен успеть прочитать, что произойдёт.
        ttl_sec: сколько запрос живёт. После — подтверждение отклоняется,
            чтобы старое окно нельзя было «дожать» случайно.
        phrase_template: фраза, которую нужно ввести. ``{name}`` заменяется
            на имя агента.
        reversible: можно ли вернуть агента к жизни.
        description: текст последствий для человека.
    """

    cooldown_sec: float
    ttl_sec: float
    phrase_template: str
    reversible: bool
    description: str

    def expected_phrase(self, agent_name: str) -> str:
        return self.phrase_template.format(name=agent_name)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Сон: обратимо (семя можно прорастить), поэтому пауза короткая.
DREAM_POLICY = ConfirmationPolicy(
    cooldown_sec=10.0,
    ttl_sec=600.0,
    phrase_template="{name}",
    reversible=True,
    description=(
        "Агент уйдёт в глубокий сон. В папке Яслей останется семя: "
        "его можно прорастить позже командой --seed."
    ),
)

# Необратимый уход: пауза длиннее, фраза строже, семени не будет.
TERMINATE_POLICY = ConfirmationPolicy(
    cooldown_sec=30.0,
    ttl_sec=300.0,
    phrase_template="{name} НАВСЕГДА",
    reversible=False,
    description=(
        "Агент прекратит существование БЕЗ семени. Восстановить его "
        "можно только из более раннего снимка, если такой есть."
    ),
)

POLICIES: Dict[str, ConfirmationPolicy] = {
    KIND_DREAM: DREAM_POLICY,
    KIND_TERMINATE: TERMINATE_POLICY,
}


def get_policy(kind: str) -> ConfirmationPolicy:
    """Политика для вида ухода. Неизвестный вид — ошибка, а не догадка."""
    try:
        return POLICIES[str(kind)]
    except KeyError:
        raise ValueError(
            f"неизвестный вид ухода: {kind!r}; допустимо: {sorted(POLICIES)}"
        ) from None


# ============================================================
# Нормализация ввода
# ============================================================


def normalize_phrase(text: str) -> str:
    """Приводит ввод человека к сравнимому виду.

    Убирает лишние пробелы по краям и внутри, приводит к верхнему регистру.
    Так ``"  alpha   навсегда "`` совпадёт с ожидаемым, но ``"alpha"`` —
    нет, и это правильно: необратимый уход требует полной фразы.
    """
    return " ".join(str(text).split()).upper()


# ============================================================
# Запрос на уход
# ============================================================


@dataclass
class LifeRequest:
    """Один запрос на уход, ожидающий подтверждения человеком."""

    request_id: str
    kind: str
    agent_name: str
    reason: str
    created_at: float
    expires_at: float
    confirmed: bool = False
    confirmed_at: Optional[float] = None

    def age_sec(self, now: Optional[float] = None) -> float:
        return (now if now is not None else time.time()) - self.created_at

    def seconds_until_confirmable(self, now: Optional[float] = None) -> float:
        policy = get_policy(self.kind)
        remaining = policy.cooldown_sec - self.age_sec(now)
        return max(0.0, remaining)

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LifeRequest":
        return cls(
            request_id=str(data["request_id"]),
            kind=str(data["kind"]),
            agent_name=str(data["agent_name"]),
            reason=str(data.get("reason", "")),
            created_at=float(data["created_at"]),
            expires_at=float(data["expires_at"]),
            confirmed=bool(data.get("confirmed", False)),
            confirmed_at=(
                float(data["confirmed_at"])
                if data.get("confirmed_at") is not None
                else None
            ),
        )


class ConfirmationError(Exception):
    """Подтверждение отклонено. Сообщение пригодно для показа человеку."""


# ============================================================
# LifeGuard
# ============================================================


@dataclass
class LifeGuard:
    """Единая точка принятия необратимых решений о жизни агента.

    Args:
        agent_name: имя агента, используется в фразе подтверждения.
        enabled: если False — все разрушительные операции запрещены.
            Это «предохранитель» для тестов и для режима наблюдения.
        clock: источник времени. Подменяется в тестах.
        state_path: файл состояния жизни.
        requests_path: файл незавершённых запросов.
        events_path: журнал всех решений (jsonl, только добавление).
        snapshot_root: папка снимков для восстановления.
        max_snapshots: сколько последних снимков хранить.
    """

    agent_name: str
    enabled: bool = True
    clock: Any = field(default=time.time, repr=False)

    state_path: str = field(
        default_factory=lambda: data_path("life_state.json"), repr=False
    )
    requests_path: str = field(
        default_factory=lambda: data_path("life_requests.json"), repr=False
    )
    events_path: str = field(
        default_factory=lambda: data_path("life_events.log"), repr=False
    )
    snapshot_root: str = field(
        default_factory=lambda: data_path("snapshots"), repr=False
    )
    max_snapshots: int = 10
    # Источник текущего отображаемого имени. Имя — только подпись жизни,
    # поэтому подтверждение должно следовать за ним, а не за именем при рождении.
    name_provider: Any = field(default=None, repr=False)
    life_id: Optional[str] = None
    database: Any = field(default=None, repr=False)
    _events_lock: Any = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        if self.database is not None:
            target = self.life_id or self.database.life_id
            from src.core.life_identity import validate_life_id

            self.life_id = validate_life_id(target)
            if self.database.life_id != self.life_id:
                raise ValueError("LifeGuard и база принадлежат разным жизням")
        elif self.life_id is not None:
            from src.core.life_identity import validate_life_id
            from src.memory.life_database import LifeDatabase

            self.life_id = validate_life_id(self.life_id)
            self.database = LifeDatabase(
                data_path("lives", self.life_id, "life.sqlite3"), self.life_id
            )

    def rebind(self, life_id: str) -> None:
        """Переключить managed-объект на авторитетную базу другого UUID."""
        from src.core.life_identity import validate_life_id
        from src.memory.life_database import LifeDatabase

        target = validate_life_id(life_id)
        if self.life_id == target and self.database is not None:
            return
        self.life_id = target
        self.database = LifeDatabase(data_path("lives", target, "life.sqlite3"), target)

    def _write_context(self):
        """Общая транзакция SQL; для standalone сохраняется файловый путь."""
        return self.database.write() if self.database is not None else nullcontext(None)

    def current_name(self) -> str:
        """Текущее имя жизни; при смене имени фраза не должна устаревать."""
        if callable(self.name_provider):
            try:
                value = self.name_provider()
            except Exception:
                value = None
            if isinstance(value, str) and value.strip():
                return value
        return self.agent_name

    # ------------------------------------------------------------------
    # Состояние жизни
    # ------------------------------------------------------------------

    def load_state(self, connection=None) -> str:
        """Читает состояние из SQL либо из legacy-файла.

        Отсутствующая SQL-строка и битый legacy JSON означают ``alive``:
        лучше оживить агента, чем случайно похоронить его из-за повреждения.
        """
        if self.database is not None:
            if connection is None:
                with closing(self.database.connect(readonly=True)) as owned:
                    return self.load_state(owned)
            row = connection.execute(
                "SELECT state FROM life_status WHERE id = 1"
            ).fetchone()
            if row is None:
                return STATE_ALIVE
            state = str(row[0])
            return state if state in VALID_STATES else STATE_ALIVE
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return STATE_ALIVE
        state = str(data.get("state", STATE_ALIVE))
        return state if state in VALID_STATES else STATE_ALIVE

    def state_details(self) -> Dict[str, Any]:
        """Полная запись состояния для показа человеку."""
        if self.database is not None:
            with closing(self.database.connect(readonly=True)) as connection:
                row = connection.execute(
                    "SELECT state, display_name, reason, changed_at, seed_folder "
                    "FROM life_status WHERE id = 1"
                ).fetchone()
            if row is None:
                return {"state": STATE_ALIVE}
            return {
                "state": row["state"],
                "agent_name": row["display_name"],
                "reason": row["reason"],
                "changed_at": row["changed_at"],
                "seed_folder": row["seed_folder"],
            }
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {"state": STATE_ALIVE}

    def set_state(
        self,
        state: str,
        *,
        reason: str = "",
        seed_folder: Optional[str] = None,
        connection=None,
    ) -> Dict[str, Any]:
        """Атомарно изменяет состояние и добавляет событие в том же backend."""
        if state not in VALID_STATES:
            raise ValueError(f"недопустимое состояние: {state!r}")
        if self.database is not None and connection is None:
            with self.database.write() as owned:
                return self.set_state(
                    state, reason=reason, seed_folder=seed_folder, connection=owned
                )
        payload: Dict[str, Any] = {
            "state": state,
            "agent_name": self.current_name(),
            "reason": reason,
            "changed_at": datetime.now().isoformat(timespec="seconds"),
            "seed_folder": seed_folder,
        }
        if self.database is not None:
            connection.execute(
                "INSERT INTO life_status"
                "(id, state, display_name, reason, changed_at, seed_folder) "
                "VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "state=excluded.state, display_name=excluded.display_name, "
                "reason=excluded.reason, changed_at=excluded.changed_at, "
                "seed_folder=excluded.seed_folder",
                (
                    state,
                    payload["agent_name"],
                    reason,
                    payload["changed_at"],
                    seed_folder,
                ),
            )
            self._log_event(
                "state_changed",
                state=state,
                reason=reason,
                seed_folder=seed_folder,
                connection=connection,
            )
            return payload
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        tmp = f"{self.state_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)
        self._log_event(
            "state_changed", state=state, reason=reason, seed_folder=seed_folder
        )
        return payload

    def is_alive(self) -> bool:
        """Агент может продолжать цикл жизни."""
        return self.load_state() == STATE_ALIVE

    # ------------------------------------------------------------------
    # Запросы и подтверждения
    # ------------------------------------------------------------------

    def _load_requests(self, connection=None) -> Dict[str, LifeRequest]:
        if self.database is not None:
            if connection is None:
                with closing(self.database.connect(readonly=True)) as owned:
                    return self._load_requests(owned)
            rows = connection.execute(
                "SELECT request_id, kind, agent_name, reason, created_at, "
                "expires_at, confirmed, confirmed_at FROM life_requests"
            ).fetchall()
            return {
                str(row["request_id"]): LifeRequest.from_dict(dict(row)) for row in rows
            }
        try:
            with open(self.requests_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        result: Dict[str, LifeRequest] = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            try:
                result[str(key)] = LifeRequest.from_dict(value)
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _save_requests(self, requests: Dict[str, LifeRequest], connection=None) -> None:
        if self.database is not None:
            if connection is None:
                with self.database.write() as owned:
                    self._save_requests(requests, owned)
                return
            connection.execute("DELETE FROM life_requests")
            connection.executemany(
                "INSERT INTO life_requests(request_id, kind, agent_name, reason, "
                "created_at, expires_at, confirmed, confirmed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        req.request_id,
                        req.kind,
                        req.agent_name,
                        req.reason,
                        req.created_at,
                        req.expires_at,
                        int(req.confirmed),
                        req.confirmed_at,
                    )
                    for req in requests.values()
                ],
            )
            return
        os.makedirs(os.path.dirname(self.requests_path) or ".", exist_ok=True)
        payload = {key: req.to_dict() for key, req in requests.items()}
        tmp = f"{self.requests_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.requests_path)

    def pending_requests(self) -> List[LifeRequest]:
        """Незавершённые и не истёкшие запросы."""
        now = self.clock()
        return [
            req
            for req in self._load_requests().values()
            if not req.confirmed and not req.is_expired(now)
        ]

    def get_request(self, request_id: str) -> Optional[LifeRequest]:
        """Запрос по идентификатору, если он ещё не истёк."""
        return self._load_requests().get(str(request_id))

    def is_confirmed(self, request_id: str) -> bool:
        """Подтверждён ли запрос и не истёк ли он.

        Используется как «пропуск» для разрушительных операций: без
        подтверждённого запроса сон и уход не выполняются.
        """
        req = self.get_request(request_id)
        if req is None:
            return False
        return bool(req.confirmed) and not req.is_expired(self.clock())

    def request(
        self,
        kind: str,
        reason: str = "",
        *,
        agent_name: Optional[str] = None,
    ) -> LifeRequest:
        """Создаёт запрос на уход. Не меняет состояние агента.

        Returns:
            Запрос с ``request_id`` и временем, через которое его можно
            подтвердить.

        Raises:
            ConfirmationError: предохранитель выключен или состояние
                агента не позволяет уходить.
        """
        policy = get_policy(kind)
        if not self.enabled:
            raise ConfirmationError(
                "Предохранитель выключен: уход запрещён в этом режиме."
            )
        with self._write_context() as connection:
            current = self.load_state(connection)
            if current == STATE_TERMINATED:
                raise ConfirmationError("Агент уже прекратил существование.")
            if current == STATE_DORMANT and kind == KIND_TERMINATE:
                raise ConfirmationError(
                    "Агент уже в глубоком сне. Необратимый уход из сна "
                    "запрещён: сначала прорастите семя."
                )

            now = self.clock()
            name = agent_name or self.current_name()

            requests = self._load_requests(connection)
            # Чистим истёкшие, чтобы хранилище не росло.
            requests = {
                key: value
                for key, value in requests.items()
                if not value.is_expired(now)
            }
            # Два запроса в одну миллисекунду не должны перезаписывать друг
            # друга: иначе второй «теряется» и подтверждается чужой.
            request_id = f"{kind}-{int(now * 1000)}"
            suffix = 1
            while request_id in requests:
                request_id = f"{kind}-{int(now * 1000)}-{suffix}"
                suffix += 1
            req = LifeRequest(
                request_id=request_id,
                kind=kind,
                agent_name=name,
                reason=reason,
                created_at=now,
                expires_at=now + policy.ttl_sec,
            )
            requests[request_id] = req
            self._save_requests(requests, connection)
            self._log_event(
                "requested",
                kind=kind,
                reason=reason,
                request_id=request_id,
                connection=connection,
            )
            return req

    def confirm(
        self,
        request_id: str,
        phrase: str,
    ) -> LifeRequest:
        """Подтверждает запрос точной фразой.

        Raises:
            ConfirmationError: запрос не найден, истёк, ещё не готов
                (cooldown) или фраза не совпала. Состояние не меняется.
        """
        if not self.enabled:
            raise ConfirmationError(
                "Предохранитель выключен: уход запрещён в этом режиме."
            )
        with self._write_context() as connection:
            requests = self._load_requests(connection)
            req = requests.get(str(request_id))  # nosec B113
            if req is None:
                raise ConfirmationError(
                    "Запрос не найден. Возможно, он истёк — начните заново."
                )
            if req.confirmed:
                raise ConfirmationError("Этот запрос уже был подтверждён.")

            now = self.clock()
            if req.is_expired(now):
                raise ConfirmationError(
                    "Время на подтверждение истекло. Запрос отменён — "
                    "начните заново, чтобы осознанно пройти весь путь."
                )

            policy = get_policy(req.kind)
            waiting = req.seconds_until_confirmable(now)
            if waiting > 0:
                raise ConfirmationError(
                    f"Слишком рано. Подождите ещё {waiting:.0f} с, "
                    f"чтобы прочитать последствия."
                )

            expected = policy.expected_phrase(req.agent_name)
            entered = normalize_phrase(phrase)
            # После смены имени запрос, созданный раньше, и новый диалог должны
            # приниматься оба: жизнь одна, меняется только её подпись.
            accepted = {
                normalize_phrase(expected),
                normalize_phrase(policy.expected_phrase(self.current_name())),
            }
            if entered not in accepted:
                raise ConfirmationError(
                    f"Фраза не совпала. Нужно ввести точно: «{expected}»"
                )

            req.confirmed = True
            req.confirmed_at = now
            requests[req.request_id] = req
            self._save_requests(requests, connection)
            self._log_event(
                "confirmed",
                kind=req.kind,
                request_id=req.request_id,
                connection=connection,
            )
            return req

    def cancel(self, request_id: str) -> bool:
        """Отменяет запрос. Работает всегда, ничего не требует."""
        with self._write_context() as connection:
            requests = self._load_requests(connection)
            if str(request_id) not in requests:
                return False
            del requests[str(request_id)]
            self._save_requests(requests, connection)
            self._log_event(
                "cancelled", request_id=str(request_id), connection=connection
            )
            return True

    def cancel_all(self, connection=None) -> int:
        """Отменяет все запросы. Вызывается при возобновлении жизни."""
        if self.database is not None and connection is None:
            with self.database.write() as owned:
                return self.cancel_all(owned)
        requests = self._load_requests(connection)
        count = len(requests)
        if count:
            self._save_requests({}, connection)
            self._log_event("cancelled_all", count=count, connection=connection)
        return count

    # ------------------------------------------------------------------
    # Исполнение подтверждённого решения
    # ------------------------------------------------------------------

    def execute_confirmed(
        self,
        request_id: str,
        *,
        seed_folder: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Применяет подтверждённый запрос к состоянию жизни.

        Перед необратимым уходом автоматически создаётся снимок данных,
        чтобы у человека оставался путь назад. Это не «отмена смерти»,
        а страховка от ошибки оператора.
        """
        requests = self._load_requests()
        req = requests.get(str(request_id))  # nosec B113
        if req is None:
            raise ConfirmationError("Запрос не найден.")
        if not req.confirmed:
            raise ConfirmationError(
                "Запрос не подтверждён. Сначала вызовите confirm()."
            )

        snapshot = None
        if req.kind == KIND_TERMINATE:
            snapshot = self.create_snapshot(tag="before_terminate")
            if self.database is not None and snapshot is None:
                raise ConfirmationError(
                    "Не удалось создать обязательный резервный снимок; "
                    "необратимый уход отменён."
                )

        with self._write_context() as connection:
            # После медленного backup повторно проверяем тот же запрос уже
            # внутри writer-транзакции: отмена не должна гоняться с уходом.
            requests = self._load_requests(connection)
            req = requests.get(str(request_id))  # nosec B113
            if req is None:
                raise ConfirmationError("Запрос не найден.")
            if not req.confirmed:
                raise ConfirmationError(
                    "Запрос не подтверждён. Сначала вызовите confirm()."
                )
            state = STATE_DORMANT if req.kind == KIND_DREAM else STATE_TERMINATED
            details = self.set_state(
                state,
                reason=req.reason,
                seed_folder=seed_folder,
                connection=connection,
            )
            del requests[req.request_id]
            self._save_requests(requests, connection)
            self._log_event(
                "executed",
                kind=req.kind,
                request_id=req.request_id,
                snapshot=snapshot,
                connection=connection,
            )
            return {
                "kind": req.kind,
                "state": state,
                "details": details,
                "snapshot": snapshot,
                "reversible": get_policy(req.kind).reversible,
            }

    def wake(self, reason: str = "возвращение к жизни") -> Dict[str, Any]:
        """Возвращает агента из ``dormant`` в ``alive``.

        Из ``terminated`` возврата нет: для этого есть ``restore_snapshot``.
        """
        with self._write_context() as connection:
            current = self.load_state(connection)
            if current == STATE_TERMINATED:
                raise ConfirmationError(
                    "Агент прекратил существование. Вернуть его можно только "
                    "из снимка: restore_snapshot()."
                )
            if current == STATE_ALIVE:
                return {"changed": False, "state": STATE_ALIVE}
            self.cancel_all(connection)
            details = self.set_state(STATE_ALIVE, reason=reason, connection=connection)
            return {"changed": True, "state": STATE_ALIVE, "details": details}

    # ------------------------------------------------------------------
    # Снимки (страховка оператора)
    # ------------------------------------------------------------------

    def create_snapshot(self, tag: str = "manual") -> Optional[str]:
        """Копирует чекпоинты, мозг и память в папку снимков.

        Возвращает путь к снимку или None, если копировать нечего.
        """
        from uuid import uuid4

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "_" + uuid4().hex[:8]
        safe_tag = "".join(
            ch if ch.isalnum() or ch in "-_" else "_" for ch in str(tag)
        )[:40]
        target = os.path.join(self.snapshot_root, f"{stamp}_{safe_tag}")
        os.makedirs(target, exist_ok=True)

        import sqlite3
        from src.memory.profile_backup import create_backup

        try:
            os.rmdir(target)
            create_backup(data_path(), target)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._log_event("snapshot_failed", error=str(exc), tag=tag)
            return None

        self._prune_snapshots()
        self._log_event("snapshot_created", path=target, tag=tag)
        return target

    def list_snapshots(self) -> List[str]:
        """Снимки от старых к новым."""
        try:
            entries = [
                os.path.join(self.snapshot_root, name)
                for name in os.listdir(self.snapshot_root)
                if os.path.isdir(os.path.join(self.snapshot_root, name))
            ]
        except OSError:
            return []
        return sorted(entries)

    def _prune_snapshots(self) -> None:
        snapshots = self.list_snapshots()
        excess = len(snapshots) - max(1, int(self.max_snapshots))
        for path in snapshots[: max(0, excess)]:
            try:
                shutil.rmtree(path)
            except OSError:
                continue

    # ------------------------------------------------------------------
    # Журнал
    # ------------------------------------------------------------------

    def _log_event(self, event: str, *, connection=None, **fields: Any) -> None:
        """Добавляет событие в SQL либо в legacy JSONL."""
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "agent": self.current_name(),
        }
        record.update(fields)
        if self.database is not None:
            if connection is None:
                with self.database.write() as owned:
                    self._log_event(event, connection=owned, **fields)
                return
            connection.execute(
                "INSERT INTO life_events(ts, event, payload_json) VALUES (?, ?, ?)",
                (
                    record["ts"],
                    event,
                    json.dumps(record, ensure_ascii=False, allow_nan=False),
                ),
            )
            return
        try:
            os.makedirs(os.path.dirname(self.events_path) or ".", exist_ok=True)
            line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
            with self._events_lock:
                try:
                    original_size = os.path.getsize(self.events_path)
                except FileNotFoundError:
                    original_size = 0
                try:
                    with open(self.events_path, "ab") as fh:
                        written = fh.write(line)
                        if written != len(line):
                            raise OSError("partial life event write")
                except OSError:
                    try:
                        os.truncate(self.events_path, original_size)
                    except OSError:
                        pass
                    raise
        except OSError:
            return

    def recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Последние записи журнала (для окна и диагностики)."""
        if self.database is not None:
            with closing(self.database.connect(readonly=True)) as connection:
                rows = connection.execute(
                    "SELECT payload_json FROM life_events ORDER BY id DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
            return [json.loads(row[0]) for row in reversed(rows)]
        try:
            with open(self.events_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            return []
        result: List[Dict[str, Any]] = []
        for line in lines[-max(1, limit) :]:
            try:
                result.append(json.loads(line))
            except ValueError:
                continue
        return result


__all__ = [
    "STATE_ALIVE",
    "STATE_DORMANT",
    "STATE_TERMINATED",
    "VALID_STATES",
    "KIND_DREAM",
    "KIND_TERMINATE",
    "ConfirmationPolicy",
    "DREAM_POLICY",
    "TERMINATE_POLICY",
    "POLICIES",
    "get_policy",
    "normalize_phrase",
    "LifeRequest",
    "ConfirmationError",
    "LifeGuard",
]
