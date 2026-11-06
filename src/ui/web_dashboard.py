"""Read-only веб-наблюдатель поверх общих DTO оболочки (К9, этап 1).

Сервер не получает ``DigitalBeing`` и не читает Core. Runtime заранее собирает
те же снимки, что передаёт Tk, и публикует их в :class:`SharedState`.
HTTP отвечает только чтением; единственный прежний мутирующий маршрут
``POST /api/action`` оставлен как явный барьер и всегда возвращает 403.

Запуск standalone-предпросмотра без ядра::

    python -m src.ui.web_dashboard --host 127.0.0.1 --port 8765

Рабочий экран рядом с Tk создаётся в ``main.py``. Транспорт — aiohttp и SSE;
FastAPI/Tauri и канал отправки сообщений на этом этапе отсутствуют.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import logging
import sys
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:  # необязательная зависимость: Tk продолжает работать
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)
STATE_KEY: web.AppKey = web.AppKey("state", Any) if AIOHTTP_AVAILABLE else None

DIALOGUE_EVENTS = (
    "agent_question",
    "agent_message",
    "agent_thought",
    "agent_web_result",
    "user_message",
)
READ_ONLY_MESSAGE = "этап 1 read-only: наблюдение без управления и отправки сообщений"


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Digital Being — обсерватория</title>
<style>
:root{color-scheme:dark;--bg:#0b0f14;--surface:#121923;--raised:#182230;--border:#273548;
--text:#e5edf5;--muted:#8b9aae;--blue:#69a9ff;--green:#63d6a4;--amber:#e8bd68;--danger:#ef7d86}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Segoe UI",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:rgba(11,15,20,.96);border-bottom:1px solid var(--border);padding:16px 24px}
.brand{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.brand h1{font-size:20px;margin:0}.brand .cycle{color:var(--muted)}
.badge{font-size:12px;color:var(--green);border:1px solid #285b4a;border-radius:999px;padding:3px 9px}
nav{display:flex;gap:6px;overflow:auto;margin-top:14px}nav button, .pager button{background:transparent;color:var(--muted);border:1px solid transparent;border-radius:7px;padding:7px 12px;min-height:44px;cursor:pointer;white-space:nowrap}
nav button.active,nav button:hover{background:var(--raised);color:var(--text);border-color:var(--border)}
nav button:focus-visible,.pager button:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
main{max-width:1320px;margin:auto;padding:22px}.page{display:none}.page.active{display:block}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;min-width:0}
.span-4{grid-column:span 4}.span-6{grid-column:span 6}.span-8{grid-column:span 8}.span-12{grid-column:span 12}
h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 14px}h3{font-size:15px;margin:0 0 8px}
.big{font-size:28px;font-weight:650}.muted{color:var(--muted)}.good{color:var(--green)}.warn{color:var(--amber)}
.rows{display:grid;gap:8px}.row{display:flex;justify-content:space-between;gap:18px;border-bottom:1px solid rgba(39,53,72,.6);padding-bottom:7px}.row span:last-child{text-align:right;overflow-wrap:anywhere}
.meter{height:6px;background:#263142;border-radius:6px;overflow:hidden;margin:6px 0 12px}.meter>i{display:block;height:100%;background:var(--blue)}
.list{display:grid;gap:10px}.entry{background:var(--raised);border-radius:8px;padding:11px 12px;overflow-wrap:anywhere}.entry time,.entry .meta{font-size:12px;color:var(--muted)}
.entry p{margin:6px 0 0;white-space:pre-wrap}.empty{color:var(--muted);font-style:italic;padding:18px 0}
pre{margin:0;max-height:540px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;color:#bdcadb;font:12px/1.55 Consolas,monospace}
.pager{display:flex;align-items:center;gap:8px;margin-top:14px}.pager button{border-color:var(--border)}.pager button:disabled{opacity:.35;cursor:default}
#graph{width:100%;height:600px;background:#0e141d;border-radius:9px}.graph-label{fill:#dce7f5;font-size:11px}.graph-edge{stroke:#4d647f;stroke-opacity:.5}
#dialogue-feed{max-height:680px;overflow:auto}.dialogue-agent{border-left:3px solid var(--green)}.dialogue-user{border-left:3px solid var(--blue)}.dialogue-thought{border-left:3px solid var(--muted)}
.notice{color:var(--muted);margin:0 0 14px}.status-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);margin-right:6px}
@media(max-width:850px){.span-4,.span-6,.span-8{grid-column:span 12}main{padding:14px}header{padding:14px}.big{font-size:23px}#graph{height:480px}}
</style>
</head>
<body>
<header><div class="brand"><h1 id="agent-name">Digital Being</h1><span class="cycle" id="cycle">цикл —</span><span class="badge">ЭТАП 1 · ТОЛЬКО НАБЛЮДЕНИЕ</span></div>
<nav id="nav"><button data-page="now" class="active">Сейчас</button><button data-page="diary">Дневник</button><button data-page="activities">Занятия</button><button data-page="graph">Карта</button><button data-page="access">Доступы</button><button data-page="dialogue">Диалог</button></nav></header>
<main>
<section id="page-now" class="page active"><div class="grid">
<div class="card span-4"><h2>Состояние</h2><div class="big" id="life-state">—</div><div class="rows" id="life-rows"></div></div>
<div class="card span-4"><h2>Эмоции</h2><div class="big" id="emotion-dominant">фон</div><div id="emotion-levels"></div></div>
<div class="card span-4"><h2>Тело</h2><div class="big" id="fatigue">—</div><div class="rows" id="body-rows"></div></div>
<div class="card span-6"><h2>Сейчас</h2><div id="now-activity"></div><h3>Объяснение выбора</h3><pre id="motivation">—</pre></div>
<div class="card span-6"><h2>Намерения</h2><div id="intentions" class="list"></div></div>
</div></section>
<section id="page-diary" class="page"><div class="card"><h2>Дневник · новые записи первыми</h2><p class="notice" id="diary-cache"></p><div id="diary-list" class="list"></div><div class="pager"><button id="diary-prev">← Новее</button><span id="diary-position" class="muted"></span><button id="diary-next">Старее →</button></div></div></section>
<section id="page-activities" class="page"><div class="grid" id="activity-cards"></div></section>
<section id="page-graph" class="page"><div class="card"><h2>Карта жизни</h2><p class="notice" id="graph-note"></p><svg id="graph" role="img" aria-label="Карта связей жизни"></svg></div></section>
<section id="page-access" class="page"><div class="grid"><div class="card span-6"><h2>Разрешения · фактическое состояние</h2><div id="access-list" class="rows"></div><p class="notice">В браузере переключателей нет: решения о доступах остаются в Tk.</p></div><div class="card span-6"><h2>Effector</h2><div id="effector-list" class="rows"></div></div></div></section>
<section id="page-dialogue" class="page"><div class="card"><h2><span class="status-dot"></span>Диалог · живой поток</h2><p class="notice">Отправка сообщений отключена. При reconnect поток продолжается с последнего принятого sequence.</p><div id="dialogue-feed" class="list"></div></div></section>
</main>
<script>
'use strict';
const $=id=>document.getElementById(id);let diaryOffset=0,diaryLimit=20,lastSequence=0,eventSource=null;
const value=v=>v===null||v===undefined||v===''?'—':String(v);const number=v=>Number.isFinite(Number(v))?Number(v).toFixed(2):'—';
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el}
function rows(target,items){const el=$(target);el.replaceChildren();for(const [k,v] of items){const r=node('div','','row');r.append(node('span',k),node('span',value(v)));el.append(r)}if(!items.length)el.append(node('div','Нет данных','empty'))}
async function getJSON(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(`${r.status} ${url}`);return r.json()}
async function refreshNow(){try{const [status,life]=await Promise.all([getJSON('/api/status'),getJSON('/api/life')]);const p=status.panel||{};$('agent-name').textContent=life.name||p.name||'Digital Being';$('cycle').textContent=`цикл ${life.life?.cycle??p.cycle??'—'}`;$('life-state').textContent=life.life?.state_label||'—';rows('life-rows',[['Энергия',`${number(life.life?.energy)} / ${number(p.max_energy)}`],['Режим',life.life?.speed_mode],['Пауза',life.life?.paused?'да':'нет'],['Семя',life.life?.seed_folder],['RSS, МБ',number(p.rss_mb)]]);
const emotions=life.emotions||{},levels=emotions.levels||{};$('emotion-dominant').textContent=emotions.dominant?.label||'спокойный фон';const box=$('emotion-levels');box.replaceChildren();for(const [name,raw] of Object.entries(levels)){const label=node('div',`${name} · ${number(raw)}`,'muted');const meter=node('div','','meter'),bar=node('i');bar.style.width=`${Math.max(0,Math.min(1,Number(raw)||0))*100}%`;meter.append(bar);box.append(label,meter)}if(!Object.keys(levels).length)box.append(node('div','Нет данных','empty'));
const body=life.body||{};$('fatigue').textContent=body.fatigue_level||'—';rows('body-rows',[['Усталость',number(body.fatigue)],['АТФ',number(body.atp)],['АТФ, доля',number(body.atp_ratio)],['Глюкоза',number(body.glucose)],['Митохондрии',number(body.mitochondrial_health)],['Нужен отдых',body.needs_rest?'да':'нет']]);const activity=life.now?.activity;$('now-activity').replaceChildren(node('h3',activity?`${value(activity.action)} · ${value(activity.target)}`:'Свободный цикл'),node('div',activity?value(activity.reason||activity.source):'Нет активного намерения','muted'));$('motivation').textContent=JSON.stringify(life.motivation||{},null,2);const intents=$('intentions');intents.replaceChildren();for(const item of (life.intentions?.recent||[]).slice(-8).reverse()){const e=node('div','','entry');e.append(node('div',`${value(item.action)} · ${value(item.target)}`),node('div',`${value(item.status)} · цикл ${value(item.cycle)}`,'meta'));intents.append(e)}if(!intents.children.length)intents.append(node('div','Пока нет записанных намерений','empty'));
rows('access-list',Object.entries(life.access||{}).filter(([k])=>k!=='workspace').map(([,v])=>[v.label,v.enabled?'включено':'выключено']));const effectorRows=[...Object.entries(life.effector?.counts||{}),['Последняя ошибка',life.effector?.last_error]];if(life.access?.workspace)effectorRows.unshift(['Рабочая область',life.access.workspace.path]);rows('effector-list',effectorRows);renderActivities(life.activities||{});}catch(e){console.warn(e)}}
function renderAccessNote(life){if(!life.access?.workspace)return}
function renderActivities(a){const box=$('activity-cards');box.replaceChildren();for(const [key,title] of [['creative','Тексты'],['art','Рисунки'],['music','Музыка'],['game','Игра'],['guess_game','Угадывание']]){const card=node('div','','card span-6');card.append(node('h2',title));const item=a[key];if(item&&typeof item==='object'&&!Array.isArray(item)){const count=item.count??((key==='game'||key==='guess_game')?'активна':'—');card.append(node('div',String(count),'big'));const pre=node('pre',JSON.stringify(item,null,2));card.append(pre)}else card.append(node('div',value(item),'muted'));box.append(card)}if(!box.children.length)box.append(node('div','Нет данных','empty'))}
async function refreshDiary(){try{const d=await getJSON(`/api/diary?offset=${diaryOffset}&limit=${diaryLimit}`),list=$('diary-list');list.replaceChildren();for(const item of d.episodes){const e=node('div','','entry');e.append(node('time',`цикл ${value(item.ts)} · ${value(item.action)} · ${item.ok?'завершено':'не завершено'}`));const args=item.args?.target?` · ${item.args.target}`:'';e.append(node('p',`${value(item.task)}${args}`));if(item.error)e.append(node('div',String(item.error),'warn'));list.append(e)}if(!d.episodes.length)list.append(node('div','Записей в этом окне нет','empty'));$('diary-cache').textContent=`В read-only кэше: ${d.stored} из максимум ${d.cache_limit}. Более старые записи могут существовать вне кэша.`;$('diary-position').textContent=`${d.returned?d.offset+1:0}–${d.offset+d.returned} / ${d.stored}`;$('diary-prev').disabled=d.offset===0;$('diary-next').disabled=!d.has_more}catch(e){console.warn(e)}}
async function refreshGraph(){try{const g=await getJSON('/api/graph'),svg=$('graph');svg.replaceChildren();const nodes=g.nodes||[],edges=g.edges||[],w=1100,h=600,cx=w/2,cy=h/2,r=Math.min(w,h)*.39,positions={};svg.setAttribute('viewBox',`0 0 ${w} ${h}`);nodes.forEach((n,i)=>{const a=(Math.PI*2*i/Math.max(1,nodes.length))-Math.PI/2;positions[n.id]=[cx+r*Math.cos(a),cy+r*Math.sin(a)]});const ns='http://www.w3.org/2000/svg';for(const e of edges){const p=positions[e.source],q=positions[e.target];if(!p||!q)continue;const line=document.createElementNS(ns,'line');line.setAttribute('x1',p[0]);line.setAttribute('y1',p[1]);line.setAttribute('x2',q[0]);line.setAttribute('y2',q[1]);line.setAttribute('class','graph-edge');svg.append(line)}nodes.forEach(n=>{const [x,y]=positions[n.id],group=document.createElementNS(ns,'g'),circle=document.createElementNS(ns,'circle'),label=document.createElementNS(ns,'text');circle.setAttribute('cx',x);circle.setAttribute('cy',y);circle.setAttribute('r',String(5+10*(n.weight||0)));circle.setAttribute('fill',n.kind==='concept'?'#69a9ff':n.kind==='intention'?'#63d6a4':'#e8bd68');label.setAttribute('x',x+12);label.setAttribute('y',y+4);label.setAttribute('class','graph-label');label.textContent=String(n.label).slice(0,28);group.append(circle,label);svg.append(group)});$('graph-note').textContent=`Узлов: ${nodes.length}; связей: ${edges.length}; скрыто сверх лимита: ${g.omitted||0}`}catch(e){console.warn(e)}}
function addDialogue(item){if(!item||item.sequence<=lastSequence)return;lastSequence=Math.max(lastSequence,item.sequence);const e=node('div','',`entry dialogue-${item.kind==='user'?'user':item.kind==='thought'?'thought':'agent'}`);e.append(node('time',`${item.time||''} · #${item.sequence} · ${item.kind}`),node('p',item.text||JSON.stringify(item.data||{})));$('dialogue-feed').prepend(e);while($('dialogue-feed').children.length>100)$('dialogue-feed').lastChild.remove()}
async function startDialogue(){try{const d=await getJSON('/api/dialogue?limit=50');for(const item of d.events)addDialogue(item);connectDialogue()}catch(e){setTimeout(startDialogue,3000)}}
function connectDialogue(){if(eventSource)eventSource.close();eventSource=new EventSource(`/stream/dialogue?after=${lastSequence}`);eventSource.onmessage=e=>{try{addDialogue(JSON.parse(e.data))}catch(err){console.warn(err)}};eventSource.onerror=()=>{/* EventSource reconnects with Last-Event-ID; sequence also deduplicates. */}}
$('nav').addEventListener('click',e=>{const button=e.target.closest('button[data-page]');if(!button)return;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===`page-${button.dataset.page}`));if(button.dataset.page==='diary')refreshDiary();if(button.dataset.page==='graph')refreshGraph()});
$('diary-prev').onclick=()=>{diaryOffset=Math.max(0,diaryOffset-diaryLimit);refreshDiary()};$('diary-next').onclick=()=>{diaryOffset+=diaryLimit;refreshDiary()};
refreshNow();refreshDiary();refreshGraph();startDialogue();setInterval(refreshNow,3000);setInterval(refreshGraph,5000);
</script></body></html>"""


class SharedState:
    """Потокобезопасное хранилище уже собранных DTO и журнала SSE.

    Ни одного объекта Core здесь нет. Все входящие словари копируются, чтобы
    HTTP-reader не наблюдал мутацию словаря во время сериализации.
    """

    def __init__(self, max_thoughts: int = 300, max_diary: int = 500) -> None:
        self._lock = threading.RLock()
        self._status: Dict[str, Any] = {}
        self._life: Dict[str, Any] = {}
        self._graph: Dict[str, Any] = {}
        self._diary: Dict[str, Any] = {"episodes": [], "count": 0,
                                       "cache_limit": max_diary}
        self._subsystem_status: Dict[str, Any] = {}
        self._last_update_ts = 0.0
        self._sequence = 0
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_thoughts)
        # Совместимое имя для существующих диагностических тестов ленты.
        self._thoughts = self._events
        self._sse_subscribers: List[asyncio.Queue] = []
        self._sse_tasks: set[asyncio.Task] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def update_status(self, status: Dict[str, Any]) -> None:
        with self._lock:
            self._status = deepcopy(dict(status or {}))
            self._last_update_ts = time.time()

    def update_life(self, life: Dict[str, Any]) -> None:
        with self._lock:
            self._life = deepcopy(dict(life or {}))
            self._last_update_ts = time.time()

    def update_graph(self, graph: Dict[str, Any]) -> None:
        with self._lock:
            self._graph = deepcopy(dict(graph or {}))

    def update_diary(self, diary: Dict[str, Any]) -> None:
        with self._lock:
            self._diary = deepcopy(dict(diary or {}))
            self._diary.setdefault("episodes", [])
            self._diary.setdefault("cache_limit", 500)

    def update_subsystems(self, status: Dict[str, Any]) -> None:
        with self._lock:
            self._subsystem_status = deepcopy(dict(status or {}))

    def push_thought(self, text: str, *, kind: str = "thought",
                     cycle: Optional[int] = None,
                     meta: Optional[Dict[str, Any]] = None) -> None:
        data: Dict[str, Any] = {"text": text}
        if meta:
            data["meta"] = deepcopy(meta)
        self.push_event(kind, data, cycle=cycle)

    def push_event(self, name: str, data: Any, *, source: str = "agent",
                   timestamp: Optional[float] = None,
                   cycle: Optional[int] = None) -> None:
        """Добавить одно событие диалога с монотонным SSE sequence."""
        payload = deepcopy(data) if isinstance(data, dict) else {"text": str(data or "")}
        ts = float(timestamp or time.time())
        kind = {
            "agent_question": "question", "agent_message": "agent",
            "agent_thought": "thought", "agent_web_result": "web",
            "user_message": "user",
        }.get(name, name)
        text = (payload.get("content") or payload.get("text")
                or payload.get("question") or payload.get("title")
                or payload.get("extract") or "")
        if cycle is None:
            try:
                cycle = int(payload["cycle"]) if payload.get("cycle") is not None else None
            except (TypeError, ValueError):
                cycle = None
        with self._lock:
            self._sequence += 1
            item = {
                "sequence": self._sequence,
                "id": payload.get("id"),
                "kind": kind,
                "text": str(text),
                "data": payload,
                "source": source,
                "cycle": cycle,
                "time": time.strftime("%H:%M:%S", time.localtime(ts)),
                "ts": ts,
            }
            self._events.append(item)
        self._broadcast(item)

    def _broadcast(self, item: Dict[str, Any]) -> None:
        if not self._sse_subscribers or self._loop is None:
            return
        for queue in list(self._sse_subscribers):
            try:
                if not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._safe_put_nowait, queue, item)
            except RuntimeError:
                continue

    @staticmethod
    def _safe_put_nowait(queue: asyncio.Queue, item: Any) -> None:
        try:
            queue.put_nowait(deepcopy(item))
        except asyncio.QueueFull:
            # Ограниченный журнал + Last-Event-ID восполняет пропуск после reconnect.
            pass

    def subscribe_events(self, after: Optional[int] = None) -> Tuple[asyncio.Queue, List[Dict[str, Any]]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=300)
        with self._lock:
            events = list(self._events)
            backlog = events[-20:] if after is None else [e for e in events if e["sequence"] > after]
            self._sse_subscribers.append(queue)
        return queue, deepcopy(backlog)

    def unsubscribe_events(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._sse_subscribers:
                self._sse_subscribers.remove(queue)

    def register_sse_task(self, task: Optional[asyncio.Task]) -> None:
        if task is not None:
            with self._lock:
                self._sse_tasks.add(task)

    def unregister_sse_task(self, task: Optional[asyncio.Task]) -> None:
        if task is not None:
            with self._lock:
                self._sse_tasks.discard(task)

    async def close_sse_tasks(self) -> None:
        """Завершить handlers до закрытия loop, дождавшись их finally."""
        with self._lock:
            tasks = [task for task in self._sse_tasks if not task.done()]
        current = asyncio.current_task()
        tasks = [task for task in tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # Старые имена остаются узкими alias; никаких действий через них нет.
    subscribe_thoughts = subscribe_events
    unsubscribe_thoughts = unsubscribe_events

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            status = deepcopy(self._status)
            life = deepcopy(self._life)
            if "agent" in status:  # совместимость раннего standalone/метрик
                result = status
            else:
                life_data = life.get("life", {})
                result = {
                    "agent": {
                        "name": status.get("name", life.get("name", "?")),
                        "cycle_count": status.get("cycle", life_data.get("cycle", 0)),
                        "energy": status.get("energy", life_data.get("energy", 0)),
                        "intelligence": status.get("intelligence", 1),
                        "completed_goals": status.get("goals_completed", 0),
                        "success_streak": 0,
                        "is_alive": life_data.get("state") == "alive",
                    },
                    "mental_models": {"total_concepts": status.get("concepts", 0)},
                    "system": {"current_rss_mb": status.get("rss_mb")},
                    "goals": {},
                    "will": {},
                    "panel": status,
                }
            result["life"] = deepcopy(life.get("life", {}))
            result["subsystem_count"] = self._subsystem_status.get("subsystem_count", 0)
            result["subsystems"] = deepcopy(self._subsystem_status.get("subsystems", []))
            result["last_update_ts"] = self._last_update_ts
            result["uptime_sec"] = status.get("uptime_sec", 0) or 0
            return result

    def life_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._life)

    def graph_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._graph)

    def life_section(self, name: str) -> Any:
        with self._lock:
            return deepcopy(self._life.get(name, {}))

    def diary_page(self, offset: int = 0, limit: int = 20) -> Dict[str, Any]:
        offset = max(0, int(offset))
        limit = max(1, min(100, int(limit)))
        with self._lock:
            episodes = deepcopy(self._diary.get("episodes", []))
            cache_limit = int(self._diary.get("cache_limit", 500) or 500)
        returned = episodes[offset:offset + limit]
        next_offset = offset + len(returned)
        has_more = next_offset < len(episodes)
        return {
            "episodes": returned, "offset": offset, "limit": limit,
            "returned": len(returned), "stored": len(episodes),
            "next_offset": next_offset if has_more else None,
            "has_more": has_more, "cache_limit": cache_limit,
            "may_have_older_outside_cache": len(episodes) >= cache_limit,
        }

    def dialogue_history(self, after: Optional[int] = None,
                         limit: int = 50) -> Dict[str, Any]:
        limit = max(1, min(200, int(limit)))
        with self._lock:
            events = list(self._events)
            latest = self._sequence
        selected = events[-limit:] if after is None else [e for e in events if e["sequence"] > after][:limit]
        oldest = events[0]["sequence"] if events else 0
        return {
            "events": deepcopy(selected), "count": len(selected),
            "latest_sequence": latest,
            "has_more": bool(selected and selected[-1]["sequence"] < latest),
            "history_gap": bool(after is not None and oldest and after < oldest - 1),
        }


def _json_response(data: Any, status: int = 200) -> Any:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


async def handle_index(request: Any) -> Any:
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


async def handle_status(request: Any) -> Any:
    return _json_response(request.app[STATE_KEY].snapshot())


async def handle_life(request: Any) -> Any:
    return _json_response(request.app[STATE_KEY].life_snapshot())


async def handle_diary(request: Any) -> Any:
    state: SharedState = request.app[STATE_KEY]
    try:
        offset = int(request.query.get("offset", "0"))
        limit = int(request.query.get("limit", "20"))
    except ValueError:
        return _json_response({"error": "offset и limit должны быть целыми"}, status=400)
    return _json_response(state.diary_page(offset, limit))


async def handle_life_section(request: Any) -> Any:
    state: SharedState = request.app[STATE_KEY]
    section = request.path.rsplit("/", 1)[-1]
    if section == "graph":
        return _json_response(state.graph_snapshot())
    if section not in {"activities", "access", "emotions", "body"}:
        return _json_response({"error": "unknown read-only section"}, status=404)
    return _json_response({section: state.life_section(section)})


async def handle_dialogue(request: Any) -> Any:
    state: SharedState = request.app[STATE_KEY]
    raw_after = request.query.get("after")
    try:
        after = int(raw_after) if raw_after is not None else None
        limit = int(request.query.get("limit", "50"))
    except ValueError:
        return _json_response({"error": "after и limit должны быть целыми"}, status=400)
    return _json_response(state.dialogue_history(after, limit))


async def handle_health(request: Any) -> Any:
    snapshot = request.app[STATE_KEY].snapshot()
    now = time.time()
    updated = snapshot.get("last_update_ts", 0)
    responsive = bool(updated and now - updated < 60)
    age = now - updated if updated else None
    if request.query.get("check", "live").lower() == "ready":
        if not responsive:
            return _json_response({"status": "not_ready", "agent_responsive": False,
                                   "last_update_age_sec": age,
                                   "reason": "no agent update in 60+ seconds"}, status=503)
        return _json_response({"status": "ready", "agent_responsive": True,
                               "last_update_age_sec": round(age, 2)})
    return _json_response({"status": "ok", "agent_responsive": responsive,
                           "last_update_age_sec": round(age, 2) if age is not None else None,
                           "subsystem_count": snapshot.get("subsystem_count", 0)})


async def handle_metrics(request: Any) -> Any:
    snap = request.app[STATE_KEY].snapshot()
    agent = snap.get("agent", {}) or {}
    mental = snap.get("mental_models", {}) or {}
    goals = snap.get("goals", {}) or {}
    will = snap.get("will", {}) or {}
    metrics = [
        ("digital_being_energy", "gauge", agent.get("energy", 0)),
        ("digital_being_intelligence", "gauge", agent.get("intelligence", 1)),
        ("digital_being_cycle_count", "counter", agent.get("cycle_count", 0)),
        ("digital_being_completed_goals", "counter", agent.get("completed_goals", 0)),
        ("digital_being_success_streak", "gauge", agent.get("success_streak", 0)),
        ("digital_being_concepts_total", "gauge", mental.get("total_concepts", 0)),
        ("digital_being_subsystem_count", "gauge", snap.get("subsystem_count", 0)),
        ("digital_being_uptime_seconds", "gauge", snap.get("uptime_sec", 0)),
    ]
    if goals.get("progress") is not None:
        metrics.append(("digital_being_goal_progress_percent", "gauge", goals["progress"]))
    if will.get("total_acts") or will.get("total"):
        metrics.append(("digital_being_will_acts_total", "counter",
                        will.get("total_acts") or will.get("total")))
    lines: List[str] = []
    for name, kind, val in metrics:
        lines.extend((f"# HELP {name} Digital Being read-only metric",
                      f"# TYPE {name} {kind}", f"{name} {val}"))
    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain",
                        charset="utf-8", headers={"Cache-Control": "no-store"})


async def handle_subsystems(request: Any) -> Any:
    snap = request.app[STATE_KEY].snapshot()
    return _json_response({"subsystems": snap.get("subsystems", [])})


async def handle_thoughts_history(request: Any) -> Any:
    state: SharedState = request.app[STATE_KEY]
    try:
        limit = max(0, min(200, int(request.query.get("n", "20"))))
    except ValueError:
        return _json_response({"error": "n должно быть целым"}, status=400)
    history = state.dialogue_history(limit=200)["events"]
    thoughts = [e for e in history if e["kind"] == "thought"][-limit:]
    return _json_response({"thoughts": thoughts, "count": len(thoughts)})


async def handle_action(request: Any) -> Any:
    """Прежняя дверь управления закрыта без чтения/исполнения тела запроса."""
    return _json_response({"status": "forbidden", "message": READ_ONLY_MESSAGE}, status=403)


async def handle_sse(request: Any) -> Any:
    state: SharedState = request.app[STATE_KEY]
    raw_after = request.headers.get("Last-Event-ID", request.query.get("after"))
    try:
        after = max(0, int(raw_after)) if raw_after not in (None, "") else None
    except ValueError:
        after = None
    response = web.StreamResponse(headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
        "Connection": "keep-alive", "X-Accel-Buffering": "no",
    })
    await response.prepare(request)
    task = asyncio.current_task()
    state.register_sse_task(task)
    queue, backlog = state.subscribe_events(after)
    last_sent = after or 0
    try:
        for item in backlog:
            if item["sequence"] > last_sent:
                await _write_sse(response, item)
                last_sent = item["sequence"]
        heartbeat = time.monotonic()
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=5.0)
                if item["sequence"] <= last_sent:
                    continue
                await _write_sse(response, item)
                last_sent = item["sequence"]
            except asyncio.TimeoutError:
                if time.monotonic() - heartbeat >= 15:
                    await response.write(b": heartbeat\n\n")
                    heartbeat = time.monotonic()
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        state.unsubscribe_events(queue)
        state.unregister_sse_task(task)
    return response


async def _write_sse(response: Any, item: Dict[str, Any]) -> None:
    data = json.dumps(item, ensure_ascii=False)
    await response.write(f"id: {item['sequence']}\ndata: {data}\n\n".encode("utf-8"))


class WebDashboard:
    """aiohttp-сервер наблюдения; в конструктор передаются только DTO-state и адрес."""

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8765

    def __init__(self, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 state: Optional[SharedState] = None) -> None:
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp не установлен; веб отключён, Tk может работать")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("этап 1 разрешает только localhost")
        self.host, self.port = host, port
        self.state = state or SharedState()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.BaseSite] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._stop_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._loop and self._loop.is_running() and self._start_error is None)

    def start(self, *, in_thread: bool = True) -> None:
        self._start_error = None
        self._started.clear()
        if in_thread:
            self._thread = threading.Thread(target=self._run_in_thread,
                                            name="web-dashboard", daemon=True)
            self._thread.start()
            self._started.wait(timeout=10)
            if self._start_error is not None:
                raise self._start_error
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.state.attach_loop(self._loop)
        try:
            self._install_app(self._loop)
            self._started.set()
            self._loop.run_forever()
        except BaseException as exc:
            self._start_error = exc
            self._started.set()
            raise

    def _run_in_thread(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self.state.attach_loop(self._loop)
            self._install_app(self._loop)
            self._started.set()
            self._loop.run_forever()
        except BaseException as exc:
            self._start_error = exc
            logger.warning("Веб-наблюдатель не запущен: %s", exc)
            self._started.set()
        finally:
            if self._loop and not self._loop.is_closed():
                if self._start_error is not None and self._runner is not None:
                    try:
                        self._loop.run_until_complete(asyncio.wait_for(
                            self._runner.cleanup(), timeout=1.0
                        ))
                    except Exception:
                        pass
                self._loop.close()

    def _install_app(self, loop: asyncio.AbstractEventLoop) -> None:
        app = web.Application()
        app[STATE_KEY] = self.state
        app.router.add_get("/", handle_index)
        app.router.add_get("/health", handle_health)
        app.router.add_get("/metrics", handle_metrics)
        app.router.add_get("/api/status", handle_status)
        app.router.add_get("/api/life", handle_life)
        app.router.add_get("/api/diary", handle_diary)
        app.router.add_get("/api/dialogue", handle_dialogue)
        app.router.add_get("/api/subsystems", handle_subsystems)
        app.router.add_get("/api/thoughts", handle_thoughts_history)
        app.router.add_get("/api/graph", handle_life_section)
        for section in ("activities", "access", "emotions", "body"):
            app.router.add_get(f"/api/{section}", handle_life_section)
        app.router.add_post("/api/action", handle_action)
        app.router.add_get("/stream/dialogue", handle_sse)
        app.router.add_get("/stream/thoughts", handle_sse)
        self._runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)
        loop.run_until_complete(self._runner.setup())
        self._site = web.TCPSite(self._runner, host=self.host, port=self.port)
        loop.run_until_complete(self._site.start())
        logger.info("Read-only веб: http://%s:%s/", self.host, self.port)

    async def _shutdown_async(self) -> None:
        if self._site is not None:
            await self._site.stop()
        await self.state.close_sse_tasks()
        if self._runner is not None:
            await asyncio.wait_for(self._runner.cleanup(), timeout=2.0)

    def stop(self) -> None:
        with self._stop_lock:
            loop = self._loop
            if loop is not None and not loop.is_closed():
                try:
                    if loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop)
                        try:
                            future.result(timeout=3)
                        finally:
                            # Даже при ошибке cleanup loop обязан остановиться.
                            loop.call_soon_threadsafe(loop.stop)
                    elif self._thread is None:
                        loop.run_until_complete(self._shutdown_async())
                except Exception as exc:
                    logger.warning("Остановка веб-наблюдателя: %s", exc)
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        elif self._thread is None and self._loop and not self._loop.is_closed():
            self._loop.close()

    def publish_status(self, status: Dict[str, Any]) -> None:
        self.state.update_status(status)

    def publish_life(self, life: Dict[str, Any]) -> None:
        self.state.update_life(life)

    def publish_graph(self, graph: Dict[str, Any]) -> None:
        self.state.update_graph(graph)

    def publish_diary(self, diary: Dict[str, Any]) -> None:
        self.state.update_diary(diary)

    def publish_subsystems(self, status: Dict[str, Any]) -> None:
        self.state.update_subsystems(status)

    def publish_event(self, name: str, data: Any, **kwargs: Any) -> None:
        self.state.push_event(name, data, **kwargs)

    def publish_thought(self, text: str, *, cycle: Optional[int] = None,
                        kind: str = "thought", meta: Optional[Dict[str, Any]] = None) -> None:
        self.state.push_thought(text, cycle=cycle, kind=kind, meta=meta)


def _demo_state() -> SharedState:
    """Маленький честный standalone: это демонстрационные DTO, не живая Тэсс."""
    state = SharedState()
    state.update_status({"name": "Standalone preview", "cycle": 0, "energy": 0,
                         "max_energy": 200, "concepts": 0, "uptime_sec": 0})
    state.update_life({
        "name": "Standalone preview",
        "life": {"cycle": 0, "energy": 0, "state": "unknown", "state_label": "ядро не подключено"},
        "now": {"activity": None}, "motivation": {}, "intentions": {"recent": []},
        "emotions": {"levels": {}, "dominant": None}, "body": {},
        "activities": {}, "access": {}, "effector": {"counts": {}},
    })
    state.update_diary({"episodes": [], "cache_limit": 500})
    state.push_event("agent_message", {"text": "Standalone preview: ядро не запущено, данные не выдаются за живую сущность."})
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Digital Being read-only web")
    parser.add_argument("--host", default=WebDashboard.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=WebDashboard.DEFAULT_PORT)
    args = parser.parse_args()
    if not AIOHTTP_AVAILABLE:
        print("aiohttp не установлен: pip install -e .[web]", file=sys.stderr)
        return 2
    dashboard = WebDashboard(host=args.host, port=args.port, state=_demo_state())
    print(f"Read-only preview: http://{args.host}:{args.port}/")
    try:
        dashboard.start(in_thread=True)
        while dashboard.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        dashboard.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
