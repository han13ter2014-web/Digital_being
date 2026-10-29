"""
Web Dashboard — лёгкий aiohttp-сервер (Этап 3.1).

Архитектурное решение:
- Сервер НЕ блокирует основной цикл — запускается в фоне (asyncio.create_task).
- Состояние читается из PluginRegistry (Этап 3.5) — единый снимок всех подсистем.
- SSE-лента /stream/thoughts отдаёт "мысли" агента по мере их появления.
- Кнопки управления (/api/...) вызывают методы агента через thread-safe очередь.
- HTML-страница минимальная: статус, кнопки, лента. Без JS-фреймворков.

Запуск:
    from src.ui.web_dashboard import WebDashboard
    dash = WebDashboard(agent, port=8765)
    dash.start()
    # ... main loop ...
    dash.stop()

Или отдельно (без агента):
    python -m src.ui.web_dashboard --port 8765

Безопасность:
- Сервер слушает 127.0.0.1 (только localhost) по умолчанию.
- POST-запросы проверяются на source (CSRF не критичен для localhost).
- Действия кнопок попадают в очередь и применяются из основного цикла —
  это исключает race condition.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, TYPE_CHECKING

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


# ============================================================
# aiohttp AppKey — рекомендуемый способ хранить state в app
# (вместо устаревшего app["state"]).
# ============================================================
STATE_KEY: web.AppKey = web.AppKey("state", Any) if AIOHTTP_AVAILABLE else None


# ============================================================
# HTML-страница (минималистичный dashboard)
# ============================================================

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Digital Being — Dashboard</title>
<style>
  body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
         background: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }
  h1, h2 { color: #58a6ff; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .panel { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
           padding: 16px; }
  pre { background: #0d1117; padding: 8px; border-radius: 4px; overflow-x: auto;
        white-space: pre-wrap; word-wrap: break-word; max-height: 400px;
        overflow-y: auto; }
  .stat { display: inline-block; margin: 4px 12px 4px 0; }
  .stat .label { color: #8b949e; font-size: 0.85em; }
  .stat .value { color: #f0f6fc; font-weight: bold; margin-left: 6px; }
  button { background: #238636; color: white; border: none; padding: 8px 14px;
           border-radius: 6px; cursor: pointer; margin-right: 8px;
           font-size: 0.95em; }
  button:hover { background: #2ea043; }
  button.warn { background: #9e6a03; }
  button.danger { background: #da3633; }
  button:disabled { background: #484f58; cursor: not-allowed; }
  #thoughts { max-height: 500px; }
  .thought { border-left: 3px solid #58a6ff; padding-left: 10px; margin: 6px 0;
             font-family: monospace; font-size: 0.9em; }
  .thought time { color: #6e7681; margin-right: 8px; }
  .empty { color: #6e7681; font-style: italic; }
  .badge { background: #1f6feb; color: white; padding: 2px 8px;
           border-radius: 10px; font-size: 0.8em; margin-left: 8px; }
</style>
</head>
<body>
<h1>🌐 Digital Being — Dashboard</h1>

<div class="grid">
  <div class="panel">
    <h2>📊 Статус <span id="cycle_badge" class="badge">—</span></h2>
    <div id="status">
      <div class="stat"><span class="label">Имя:</span><span class="value" id="agent_name">—</span></div>
      <div class="stat"><span class="label">Энергия:</span><span class="value" id="energy">—</span></div>
      <div class="stat"><span class="label">Интеллект:</span><span class="value" id="intel">—</span></div>
      <div class="stat"><span class="label">Циклов:</span><span class="value" id="cycles">—</span></div>
      <div class="stat"><span class="label">Целей завершено:</span><span class="value" id="goals">—</span></div>
      <div class="stat"><span class="label">Концепций:</span><span class="value" id="concepts">—</span></div>
      <div class="stat"><span class="label">RSS (МБ):</span><span class="value" id="rss">—</span></div>
      <div class="stat"><span class="label">Подсистем:</span><span class="value" id="subsystems">—</span></div>
      <div class="stat"><span class="label">Жив:</span><span class="value" id="alive">—</span></div>
    </div>
  </div>

  <div class="panel">
    <h2>🎮 Управление</h2>
    <p>
      <button onclick="act('pause')">⏸ Пауза</button>
      <button onclick="act('resume')">▶ Продолжить</button>
      <button onclick="act('save')">💾 Сохранить</button>
      <button onclick="act('reflect')">🔍 Рефлексия</button>
    </p>
    <p>
      <button onclick="act('status')" class="warn">📋 Полный статус</button>
      <button onclick="act('thought')">💭 Попросить мысль</button>
    </p>
    <p>
      <button onclick="act('shutdown')" class="danger">🛑 Завершить</button>
    </p>
    <div id="action_result" class="empty">Действие: <span id="action_status">—</span></div>
  </div>
</div>

<div class="panel">
  <h2>💭 Лента мыслей (SSE)</h2>
  <div id="thoughts"></div>
  <div class="empty">Последние <span id="thoughts_count">0</span> мыслей</div>
</div>

<div class="panel">
  <h2>🔌 Подсистемы</h2>
  <pre id="subsystems_view">загрузка...</pre>
</div>

<script>
const thoughtsEl = document.getElementById('thoughts');
const thoughtsCountEl = document.getElementById('thoughts_count');
let thoughtCount = 0;

function addThought(text, time) {
  const el = document.createElement('div');
  el.className = 'thought';
  el.innerHTML = `<time>${time}</time>${text}`;
  thoughtsEl.insertBefore(el, thoughtsEl.firstChild);
  thoughtCount++;
  thoughtsCountEl.textContent = thoughtCount;
  // Держим максимум 50 видимых
  while (thoughtsEl.children.length > 50) thoughtsEl.removeChild(thoughtsEl.lastChild);
}

async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    if (!r.ok) return;
    const d = await r.json();
    document.getElementById('cycle_badge').textContent = 'cycle ' + (d.agent?.cycle_count ?? '?');
    document.getElementById('agent_name').textContent = d.agent?.name ?? '—';
    document.getElementById('energy').textContent = Math.round(d.agent?.energy ?? 0);
    document.getElementById('intel').textContent = d.agent?.intelligence ?? 0;
    document.getElementById('cycles').textContent = d.agent?.cycle_count ?? 0;
    document.getElementById('goals').textContent = d.agent?.completed_goals ?? 0;
    document.getElementById('concepts').textContent = d.mental_models?.total_concepts ?? 0;
    document.getElementById('rss').textContent = d.system?.current_rss_mb ?? 0;
    document.getElementById('subsystems').textContent = d.subsystem_count ?? 0;
    document.getElementById('alive').textContent = d.agent?.is_alive ? '💚 да' : '💀 нет';
    document.getElementById('subsystems_view').textContent = JSON.stringify(d.subsystems, null, 2);
  } catch (e) { console.error(e); }
}

async function act(action) {
  const statusEl = document.getElementById('action_status');
  statusEl.textContent = '⏳ ' + action;
  try {
    const r = await fetch('/api/action', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: action})
    });
    const d = await r.json();
    statusEl.textContent = d.status + (d.message ? ': ' + d.message : '');
  } catch (e) {
    statusEl.textContent = '❌ ' + e.message;
  }
}

// SSE — лента мыслей
const es = new EventSource('/stream/thoughts');
es.onmessage = (ev) => {
  try {
    const data = JSON.parse(ev.data);
    addThought(data.text || JSON.stringify(data), data.time || new Date().toLocaleTimeString());
  } catch (e) { console.error('SSE parse error', e); }
};
es.onerror = () => { console.warn('SSE disconnected, retrying...'); };

// Статус каждые 3 секунды
refreshStatus();
setInterval(refreshStatus, 3000);
</script>
</body>
</html>
"""


# ============================================================
# SharedState — потокобезопасное хранилище между web и main loop
# ============================================================

class SharedState:
    """Потокобезопасный мост между основным циклом агента и aiohttp-сервером.

    - main loop вызывает state.update_status(...) и state.push_thought(...) каждый цикл;
    - сервер читает state.snapshot() в HTTP-обработчиках;
    - пользователь жмёт кнопку → request → state.pop_action() читается в main loop.
    """

    def __init__(self, max_thoughts: int = 100, max_actions: int = 50) -> None:
        self._lock = threading.RLock()
        self._status: Dict[str, Any] = {}
        self._thoughts: Deque[Dict[str, Any]] = deque(maxlen=max_thoughts)
        self._actions: Deque[Dict[str, Any]] = deque(maxlen=max_actions)
        self._subsystem_status: Dict[str, Any] = {}
        self._last_update_ts: float = 0.0
        # Клиенты SSE получают новые мысли через подписку
        self._sse_subscribers: List[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Привязать loop — publish_thought сможет звать call_soon_threadsafe."""
        self._loop = loop

    def update_status(self, status: Dict[str, Any]) -> None:
        with self._lock:
            self._status = dict(status)
            self._last_update_ts = time.time()

    def update_subsystems(self, status: Dict[str, Any]) -> None:
        with self._lock:
            self._subsystem_status = dict(status)

    def push_thought(self, text: str, *, kind: str = "thought",
                      cycle: Optional[int] = None,
                      meta: Optional[Dict[str, Any]] = None) -> None:
        """Добавить мысль в ленту (из основного цикла). Потокобезопасно."""
        payload = {
            "text": text,
            "kind": kind,
            "cycle": cycle,
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
        }
        if meta:
            payload["meta"] = meta
        with self._lock:
            self._thoughts.append(payload)
        # Доставить подписчикам SSE
        self._broadcast_thought(payload)

    def _broadcast_thought(self, payload: Dict[str, Any]) -> None:
        """Доставить событие SSE-подписчикам. Thread-safe."""
        if not self._sse_subscribers or self._loop is None:
            return
        for q in list(self._sse_subscribers):
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._safe_put_nowait, q, payload)
            except RuntimeError:
                pass

    @staticmethod
    def _safe_put_nowait(q: asyncio.Queue, item: Any) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            pass

    def subscribe_thoughts(self) -> asyncio.Queue:
        """Подписаться на мысли (возвращает очередь)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._sse_subscribers.append(q)
            # Сразу отдадим последние N мыслей
            for t in list(self._thoughts)[-20:]:
                try:
                    q.put_nowait(t)
                except asyncio.QueueFull:
                    break
        return q

    def unsubscribe_thoughts(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._sse_subscribers:
                self._sse_subscribers.remove(q)

    def push_action(self, action: str, args: Optional[Dict[str, Any]] = None) -> None:
        """Пользователь нажал кнопку (из HTTP-handler)."""
        with self._lock:
            self._actions.append({"action": action, "args": args or {}, "ts": time.time()})

    def pop_action(self, timeout: float = 0.0) -> Optional[Dict[str, Any]]:
        """Забрать действие (из основного цикла)."""
        with self._lock:
            if self._actions:
                return self._actions.popleft()
        return None

    def snapshot(self) -> Dict[str, Any]:
        """Снимок для /api/status и /metrics.

        Возвращает белый список полей из self._status плюс служебные
        (subsystem_count, subsystems, last_update_ts). Это безопасно:
        неизвестные ключи игнорируются.
        """
        with self._lock:
            return {
                "agent": dict(self._status.get("agent", {})),
                "mental_models": dict(self._status.get("mental_models", {})),
                "system": dict(self._status.get("system", {})),
                "goals": dict(self._status.get("goals", {})),
                "will": dict(self._status.get("will", {})),
                "subsystem_count": self._subsystem_status.get("subsystem_count", 0),
                "subsystems": list(self._subsystem_status.get("subsystems", [])),
                "last_update_ts": self._last_update_ts,
            }


# ============================================================
# HTTP-handlers
# ============================================================

def _json_response(data: Any, status: int = 200) -> Any:
    return web.json_response(data, status=status)


async def handle_index(request: Any) -> Any:
    """Главная страница — HTML dashboard."""
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


async def handle_status(request: Any) -> Any:
    """JSON-снимок состояния."""
    state: SharedState = request.app[STATE_KEY]
    return _json_response(state.snapshot())


async def handle_health(request: Any) -> Any:
    """GET /health — liveness/readiness для внешнего мониторинга.

    Полезно для:
    - Kubernetes livenessProbe/readinessProbe.
    - Prometheus blackbox_exporter.
    - systemd / Docker healthcheck.
    - систем мониторинга (UptimeRobot, Healthchecks.io).

    Возвращает простой JSON-статус. Никогда не возвращает 5xx — агент
    «всегда жив» в трей-режиме (политика «энергия управляет темпом»).

    Query-параметры:
        ?check=ready  — readiness (проверяет, что есть данные от агента)
        ?check=live   — liveness (по умолчанию: всегда 200, если сервер жив)

    Пример:
        curl http://127.0.0.1:8765/health
        # {"status": "ok", "uptime_sec": 123.4, "agent_responsive": true}

        curl http://127.0.0.1:8765/health?check=ready
        # {"status": "ready", "agent_responsive": true, "last_update_age_sec": 2.3}
    """
    state: SharedState = request.app[STATE_KEY]
    check = request.query.get("check", "live").lower()

    now = time.time()
    snapshot = state.snapshot()
    agent_responsive = (
        snapshot.get("last_update_ts", 0) > 0
        and (now - snapshot.get("last_update_ts", 0)) < 60
    )
    last_update_age = (
        now - snapshot["last_update_ts"]
        if snapshot.get("last_update_ts")
        else None
    )

    if check == "ready":
        # Readiness — готов ли обслуживать запросы.
        if not agent_responsive:
            return _json_response(
                {
                    "status": "not_ready",
                    "agent_responsive": False,
                    "last_update_age_sec": last_update_age,
                    "reason": "no agent update in 60+ seconds",
                },
                status=503,
            )
        return _json_response({
            "status": "ready",
            "agent_responsive": True,
            "last_update_age_sec": round(last_update_age, 2)
                                  if last_update_age is not None else None,
        })

    # Liveness (по умолчанию) — сервер отвечает.
    return _json_response({
        "status": "ok",
        "agent_responsive": agent_responsive,
        "last_update_age_sec": round(last_update_age, 2)
                              if last_update_age is not None else None,
        "subsystem_count": snapshot.get("subsystem_count", 0),
    })


async def handle_metrics(request: Any) -> Any:
    """GET /metrics — Prometheus-совместимый text-format экспорт (Этап 6).

    Используется для:
    - Prometheus scrape (по умолчанию каждые 15-30 сек).
    - Grafana dashboards.
    - Alertmanager (например, alert если digital_being_energy < 20).

    Формат: text/plain; version=0.0.4 (стандарт Prometheus exposition).
    Никаких внешних зависимостей — генерируем руками из SharedState.

    Пример:
        curl http://127.0.0.1:8765/metrics
        # # HELP digital_being_energy Current energy level (0-200)
        # # TYPE digital_being_energy gauge
        # digital_being_energy 145
        # ...
    """
    state: SharedState = request.app[STATE_KEY]
    snapshot = state.snapshot()

    # === Сбор метрик из snapshot ===
    agent_data = snapshot.get("agent", {}) or {}
    mental_models = snapshot.get("mental_models", {}) or {}
    goals = snapshot.get("goals", {}) or {}
    will = snapshot.get("will", {}) or {}

    lines: List[str] = []

    # --- Gauges (текущее значение) ---
    lines.append("# HELP digital_being_energy Current energy level (0-200)")
    lines.append("# TYPE digital_being_energy gauge")
    lines.append(f"digital_being_energy {agent_data.get('energy', 0)}")

    lines.append("# HELP digital_being_intelligence Current intelligence level (1+)")
    lines.append("# TYPE digital_being_intelligence gauge")
    lines.append(f"digital_being_intelligence {agent_data.get('intelligence', 1)}")

    lines.append("# HELP digital_being_cycle_count Total cycles since birth")
    lines.append("# TYPE digital_being_cycle_count counter")
    lines.append(f"digital_being_cycle_count {agent_data.get('cycle_count', 0)}")

    lines.append("# HELP digital_being_completed_goals Total completed goals")
    lines.append("# TYPE digital_being_completed_goals counter")
    lines.append(f"digital_being_completed_goals {agent_data.get('completed_goals', 0)}")

    lines.append("# HELP digital_being_success_streak Current streak of successful actions")
    lines.append("# TYPE digital_being_success_streak gauge")
    lines.append(f"digital_being_success_streak {agent_data.get('success_streak', 0)}")

    lines.append("# HELP digital_being_concepts_total Total concepts in mental models")
    lines.append("# TYPE digital_being_concepts_total gauge")
    lines.append(f"digital_being_concepts_total {mental_models.get('total_concepts', 0)}")

    lines.append("# HELP digital_being_subsystem_count Number of active subsystems")
    lines.append("# TYPE digital_being_subsystem_count gauge")
    lines.append(f"digital_being_subsystem_count {snapshot.get('subsystem_count', 0)}")

    lines.append("# HELP digital_being_uptime_seconds Seconds since server start")
    lines.append("# TYPE digital_being_uptime_seconds gauge")
    lines.append(f"digital_being_uptime_seconds {snapshot.get('uptime_sec', 0)}")

    # --- Goal progress (если есть) ---
    progress = goals.get("progress")
    if progress is not None:
        lines.append("# HELP digital_being_goal_progress_percent Active goal progress (0-100)")
        lines.append("# TYPE digital_being_goal_progress_percent gauge")
        lines.append(f"digital_being_goal_progress_percent {progress}")

    # --- Will stats (волюнтаристика) ---
    total_will = will.get("total_acts") or will.get("total") or 0
    if total_will:
        lines.append("# HELP digital_being_will_acts_total Total voluntary acts recorded")
        lines.append("# TYPE digital_being_will_acts_total counter")
        lines.append(f"digital_being_will_acts_total {total_will}")

    return web.Response(
        text="\n".join(lines) + "\n",
        content_type="text/plain",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


async def handle_subsystems(request: Any) -> Any:
    """Снимок всех подсистем (Этап 3.5)."""
    state: SharedState = request.app[STATE_KEY]
    return _json_response({"subsystems": state.snapshot().get("subsystems", [])})


async def handle_thoughts_history(request: Any) -> Any:
    """Последние мысли (REST-вариант ленты)."""
    state: SharedState = request.app[STATE_KEY]
    n = int(request.query.get("n", "20"))
    with state._lock:
        items = list(state._thoughts)[-n:]
    return _json_response({"thoughts": items, "count": len(items)})


async def handle_action(request: Any) -> Any:
    """POST /api/action — кнопка управления."""
    state: SharedState = request.app[STATE_KEY]
    try:
        body = await request.json()
    except Exception:
        return _json_response({"status": "error", "message": "invalid JSON"}, status=400)

    action = body.get("action")
    if not action:
        return _json_response({"status": "error", "message": "action required"}, status=400)

    valid = {"pause", "resume", "save", "reflect", "status", "thought", "shutdown",
             "set_goal", "add_quiet_app"}
    if action not in valid:
        return _json_response({
            "status": "error",
            "message": f"unknown action: {action}. Valid: {sorted(valid)}",
        }, status=400)

    args = body.get("args") or {}
    if action == "set_goal" and not args.get("title"):
        return _json_response({
            "status": "error",
            "message": "set_goal requires args.title",
        }, status=400)
    if action == "add_quiet_app" and not args.get("app"):
        return _json_response({
            "status": "error",
            "message": "add_quiet_app requires args.app",
        }, status=400)

    state.push_action(action, args)
    return _json_response({
        "status": "queued",
        "action": action,
        "args": args,
    })


async def handle_sse_thoughts(request: Any) -> Any:
    """SSE-поток мыслей. EventSource на стороне браузера."""
    state: SharedState = request.app[STATE_KEY]

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    q = state.subscribe_thoughts()
    try:
        # Heartbeat каждые 15с (чтобы прокси не закрывали соединение).
        last_heartbeat = time.time()
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=5.0)
                data = json.dumps(item, ensure_ascii=False)
                payload = f"data: {data}\n\n".encode("utf-8")
                await response.write(payload)
            except asyncio.TimeoutError:
                now = time.time()
                if now - last_heartbeat >= 15.0:
                    await response.write(b": heartbeat\n\n")
                    last_heartbeat = now
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        state.unsubscribe_thoughts(q)
    return response


# ============================================================
# WebDashboard — главный класс
# ============================================================

class WebDashboard:
    """Лёгкий aiohttp-сервер для наблюдения и управления агентом.

    Использование:
        dash = WebDashboard(agent, port=8765)
        dash.start()
        # в главном цикле:
        while True:
            dash.publish_status(...)   # обновить снимок
            dash.publish_thought(...)  # добавить мысль
            action = dash.pop_action() # обработать нажатие
            ...
        dash.stop()
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8765

    def __init__(self, agent: Any = None, *, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT,
                 state: Optional[SharedState] = None) -> None:
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError(
                "aiohttp не установлен. Установите: pip install aiohttp"
            )
        self.agent = agent
        self.host = host
        self.port = port
        self.state = state or SharedState()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.BaseSite] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stopped = threading.Event()
        self._started = threading.Event()
        self._start_error: Optional[BaseException] = None

    # ----------------------------------------------------------------
    # Запуск / остановка
    # ----------------------------------------------------------------

    def start(self, *, in_thread: bool = True) -> None:
        """Запустить сервер. По умолчанию — в отдельном потоке.

        Если in_thread=False — нужно вызвать run_forever() из async-контекста.
        """
        if in_thread:
            self._thread = threading.Thread(
                target=self._run_in_thread,
                name="web-dashboard",
                daemon=True,
            )
            self._thread.start()
            self._started.wait(timeout=10.0)
            if self._start_error is not None:
                raise self._start_error
        else:
            # Создаём loop в текущем потоке (для тестов)
            self._loop = asyncio.new_event_loop()
            self._install_app(self._loop)

    def _run_in_thread(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self.state.attach_loop(self._loop)
            self._install_app(self._loop)
            self._started.set()
            self._loop.run_forever()
        except Exception as e:
            self._start_error = e
            logger.exception(f"[web_dashboard] ошибка запуска: {e}")
            self._started.set()
        finally:
            if self._loop and not self._loop.is_closed():
                self._loop.close()

    def _install_app(self, loop: asyncio.AbstractEventLoop) -> None:
        app = web.Application()
        # Используем web.AppKey — рекомендуемый aiohttp-способ хранения
        # в app-контексте (без DeprecationWarning).
        app[STATE_KEY] = self.state
        app.router.add_get("/", handle_index)
        app.router.add_get("/health", handle_health)
        app.router.add_get("/metrics", handle_metrics)  # Prometheus scrape (Этап 6)
        app.router.add_get("/api/status", handle_status)
        app.router.add_get("/api/subsystems", handle_subsystems)
        app.router.add_get("/api/thoughts", handle_thoughts_history)
        app.router.add_post("/api/action", handle_action)
        app.router.add_get("/stream/thoughts", handle_sse_thoughts)

        self._runner = web.AppRunner(app, access_log=None)
        loop.run_until_complete(self._runner.setup())
        self._site = web.TCPSite(self._runner, host=self.host, port=self.port)
        loop.run_until_complete(self._site.start())
        logger.info(f"[web_dashboard] http://{self.host}:{self.port}/")

    def stop(self) -> None:
        """Остановить сервер. Безопасно вызывать из любого потока."""
        self._stopped.set()
        if self._loop and not self._loop.is_closed():
            try:
                # Планируем остановку через loop.call_soon_threadsafe
                async def _shutdown():
                    if self._site is not None:
                        await self._site.stop()
                    if self._runner is not None:
                        await self._runner.cleanup()
                    self._loop.stop()

                future = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
                try:
                    future.result(timeout=5.0)
                except Exception as e:
                    logger.warning(f"[web_dashboard] shutdown ошибка: {e}")
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    # ----------------------------------------------------------------
    # Удобные методы для основного цикла
    # ----------------------------------------------------------------

    def publish_status(self, status: Optional[Dict[str, Any]] = None) -> None:
        """Обновить снимок статуса (читается из агента, если не передан)."""
        if status is None and self.agent is not None:
            try:
                status = self.agent.get_full_state()
            except Exception:
                status = {}
        self.state.update_status(status or {})

    def publish_subsystems(self, status: Optional[Dict[str, Any]] = None) -> None:
        if status is None and self.agent is not None:
            try:
                status = self.agent.get_subsystems_status()
            except Exception:
                status = {}
        self.state.update_subsystems(status or {})

    def publish_thought(self, text: str, *, cycle: Optional[int] = None,
                        kind: str = "thought",
                        meta: Optional[Dict[str, Any]] = None) -> None:
        self.state.push_thought(text, cycle=cycle, kind=kind, meta=meta)

    def pop_action(self, timeout: float = 0.0) -> Optional[Dict[str, Any]]:
        return self.state.pop_action(timeout=timeout)

    def apply_action(self, action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Применить действие к агенту. Возвращает отчёт."""
        if self.agent is None:
            return {"status": "no_agent"}
        name = action.get("action")
        args = action.get("args") or {}
        try:
            if name == "pause":
                # Устанавливаем флаг — main loop должен его уважать
                if not hasattr(self.agent, "_dashboard_paused"):
                    self.agent._dashboard_paused = False
                self.agent._dashboard_paused = True
                return {"status": "ok", "message": "поставлен на паузу"}
            elif name == "resume":
                if hasattr(self.agent, "_dashboard_paused"):
                    self.agent._dashboard_paused = False
                return {"status": "ok", "message": "продолжает"}
            elif name == "save":
                if hasattr(self.agent, "save_state"):
                    self.agent.save_state()
                if hasattr(self.agent, "save_mental_models"):
                    self.agent.save_mental_models()
                return {"status": "ok", "message": "сохранено"}
            elif name == "reflect":
                if hasattr(self.agent, "reflect"):
                    self.agent.reflect()
                return {"status": "ok", "message": "рефлексия выполнена"}
            elif name == "status":
                return {"status": "ok", "state": self.agent.get_full_state()}
            elif name == "thought":
                if hasattr(self.agent, "think"):
                    try:
                        thought = self.agent.think("вопрос от пользователя через дашборд")
                        if hasattr(self.agent, "act"):
                            self.agent.act(thought)
                        return {"status": "ok", "thought": str(thought)}
                    except Exception as e:
                        return {"status": "error", "message": str(e)}
                return {"status": "no_think_method"}
            elif name == "shutdown":
                # Помечаем агента как «запрошен выход» — main loop проверит.
                # Флаг ставим всегда (даже если у агента нет is_alive — main loop
                # может быть встроенным).
                self.agent._dashboard_shutdown_requested = True
                return {"status": "ok", "message": "запрошено завершение"}
            elif name == "set_goal":
                title = args.get("title")
                difficulty = int(args.get("difficulty", 1))
                if hasattr(self.agent, "set_goal"):
                    goal_id = self.agent.set_goal(title, difficulty=difficulty)
                    return {"status": "ok", "goal_id": goal_id}
                return {"status": "no_set_goal"}
            elif name == "add_quiet_app":
                app_name = args.get("app")
                if hasattr(self.agent, "add_quiet_app"):
                    self.agent.add_quiet_app(app_name)
                    return {"status": "ok", "app": app_name}
                return {"status": "no_quiet_method"}
        except Exception as e:
            logger.warning(f"[web_dashboard] apply_action ошибка: {e}")
            return {"status": "error", "message": str(e)}
        return {"status": "unknown_action"}


# ============================================================
# CLI — запуск без агента (только просмотр)
# ============================================================

def _cli_main(host: str, port: int) -> int:
    """Простой режим — без агента, ручной ввод мыслей."""
    print(f"⚠️  Запущен CLI-режим без aiohttp-сервера.")
    print(f"   Для полного dashboard: pip install aiohttp")
    print(f"   http://{host}:{port}/ (только статическая страница)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Digital Being Web Dashboard")
    parser.add_argument("--host", default=WebDashboard.DEFAULT_HOST,
                        help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=WebDashboard.DEFAULT_PORT,
                        help="bind port (default: 8765)")
    args = parser.parse_args()

    if not AIOHTTP_AVAILABLE:
        print("⚠️  aiohttp не установлен. Минимальный режим.")
        return _cli_main(args.host, args.port)

    # Standalone-демо без агента: публикуем фейковые данные.
    state = SharedState()
    state.push_thought("🌐 Dashboard запущен в standalone-режиме (без агента)")
    state.push_thought("⚠️  Подключите агента: dash = WebDashboard(agent, port=...)")

    # Имитация активности
    counter = {"n": 0}

    def fake_publisher():
        while not state._stopped.is_set():
            counter["n"] += 1
            state.push_thought(
                f"💓 tick #{counter['n']} — standalone режим",
                cycle=counter["n"],
            )
            state.update_status({
                "agent": {
                    "name": "Standalone",
                    "energy": 100,
                    "intelligence": 1,
                    "cycle_count": counter["n"],
                    "is_alive": True,
                    "completed_goals": 0,
                },
                "mental_models": {"total_concepts": 0},
                "system": {"current_rss_mb": 0},
            })
            time.sleep(3.0)

    t = threading.Thread(target=fake_publisher, daemon=True)
    t.start()

    dash = WebDashboard(agent=None, host=args.host, port=args.port, state=state)
    print(f"🌐 Откройте http://{args.host}:{args.port}/")
    try:
        dash.start(in_thread=False)
    except KeyboardInterrupt:
        pass
    finally:
        dash.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())