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
Состояние (``alive`` / ``dormant`` / ``terminated``) хранится в файле
``data/life_state.json``, а не в подменённом методе ``agent.is_alive``.
Так оно переживает перезапуск и его можно показать человеку.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.paths import data_path

# ============================================================
# Состояния жизни
# ============================================================

STATE_ALIVE = "alive"
STATE_DORMANT = "dormant"        # ушёл в сон, семя оставлено
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

    # ------------------------------------------------------------------
    # Состояние жизни
    # ------------------------------------------------------------------

    def load_state(self) -> str:
        """Читает сохранённое состояние жизни. Битый файл → ``alive``.

        Сознательно склоняемся к «жив»: лучше оживить агента, чем
        случайно похоронить его из-за повреждённого JSON.
        """
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return STATE_ALIVE
        state = str(data.get("state", STATE_ALIVE))
        return state if state in VALID_STATES else STATE_ALIVE

    def state_details(self) -> Dict[str, Any]:
        """Полная запись состояния для показа человеку."""
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
    ) -> Dict[str, Any]:
        """Записывает состояние жизни на диск.

        Это единственный способ изменить состояние — прямое присваивание
        ``agent.is_alive`` больше не используется, потому что оно не
        переживает перезапуск.
        """
        if state not in VALID_STATES:
            raise ValueError(f"недопустимое состояние: {state!r}")
        payload: Dict[str, Any] = {
            "state": state,
            "agent_name": self.agent_name,
            "reason": reason,
            "changed_at": datetime.now().isoformat(timespec="seconds"),
            "seed_folder": seed_folder,
        }
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        tmp = f"{self.state_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)
        self._log_event("state_changed", state=state, reason=reason,
                        seed_folder=seed_folder)
        return payload

    def is_alive(self) -> bool:
        """Агент может продолжать цикл жизни."""
        return self.load_state() == STATE_ALIVE

    # ------------------------------------------------------------------
    # Запросы и подтверждения
    # ------------------------------------------------------------------

    def _load_requests(self) -> Dict[str, LifeRequest]:
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

    def _save_requests(self, requests: Dict[str, LifeRequest]) -> None:
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
        current = self.load_state()
        if current == STATE_TERMINATED:
            raise ConfirmationError("Агент уже прекратил существование.")
        if current == STATE_DORMANT and kind == KIND_TERMINATE:
            raise ConfirmationError(
                "Агент уже в глубоком сне. Необратимый уход из сна "
                "запрещён: сначала прорастите семя."
            )

        now = self.clock()
        name = agent_name or self.agent_name
        request_id = f"{kind}-{int(now * 1000)}"
        req = LifeRequest(
            request_id=request_id,
            kind=kind,
            agent_name=name,
            reason=reason,
            created_at=now,
            expires_at=now + policy.ttl_sec,
        )

        requests = self._load_requests()
        # Чистим истёкшие, чтобы файл не рос.
        requests = {
            key: value
            for key, value in requests.items()
            if not value.is_expired(now)
        }
        requests[request_id] = req
        self._save_requests(requests)
        self._log_event("requested", kind=kind, reason=reason,
                        request_id=request_id)
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
        requests = self._load_requests()
        req = requests.get(str(request_id))
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
        if normalize_phrase(phrase) != normalize_phrase(expected):
            raise ConfirmationError(
                f"Фраза не совпала. Нужно ввести точно: «{expected}»"
            )

        req.confirmed = True
        req.confirmed_at = now
        requests[req.request_id] = req
        self._save_requests(requests)
        self._log_event("confirmed", kind=req.kind,
                        request_id=req.request_id)
        return req

    def cancel(self, request_id: str) -> bool:
        """Отменяет запрос. Работает всегда, ничего не требует."""
        requests = self._load_requests()
        if str(request_id) not in requests:
            return False
        del requests[str(request_id)]
        self._save_requests(requests)
        self._log_event("cancelled", request_id=str(request_id))
        return True

    def cancel_all(self) -> int:
        """Отменяет все запросы. Вызывается при возобновлении жизни."""
        requests = self._load_requests()
        count = len(requests)
        if count:
            self._save_requests({})
            self._log_event("cancelled_all", count=count)
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
        req = requests.get(str(request_id))
        if req is None:
            raise ConfirmationError("Запрос не найден.")
        if not req.confirmed:
            raise ConfirmationError(
                "Запрос не подтверждён. Сначала вызовите confirm()."
            )

        snapshot = None
        if req.kind == KIND_TERMINATE:
            snapshot = self.create_snapshot(tag="before_terminate")

        state = STATE_DORMANT if req.kind == KIND_DREAM else STATE_TERMINATED
        details = self.set_state(
            state, reason=req.reason, seed_folder=seed_folder
        )
        del requests[req.request_id]
        self._save_requests(requests)
        self._log_event("executed", kind=req.kind,
                        request_id=req.request_id, snapshot=snapshot)
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
        current = self.load_state()
        if current == STATE_TERMINATED:
            raise ConfirmationError(
                "Агент прекратил существование. Вернуть его можно только "
                "из снимка: restore_snapshot()."
            )
        if current == STATE_ALIVE:
            return {"changed": False, "state": STATE_ALIVE}
        self.cancel_all()
        details = self.set_state(STATE_ALIVE, reason=reason)
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
        target = os.path.join(
            self.snapshot_root, f"{stamp}_{safe_tag}"
        )
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
        for path in snapshots[:max(0, excess)]:
            try:
                shutil.rmtree(path)
            except OSError:
                continue

    # ------------------------------------------------------------------
    # Журнал
    # ------------------------------------------------------------------

    def _log_event(self, event: str, **fields: Any) -> None:
        """Пишет строку в журнал решений. Ошибки записи не критичны."""
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "agent": self.agent_name,
        }
        record.update(fields)
        try:
            os.makedirs(os.path.dirname(self.events_path) or ".", exist_ok=True)
            with open(self.events_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            return

    def recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Последние записи журнала (для окна и диагностики)."""
        try:
            with open(self.events_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            return []
        result: List[Dict[str, Any]] = []
        for line in lines[-max(1, limit):]:
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
