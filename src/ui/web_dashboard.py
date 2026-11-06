"""Локальный веб-интерфейс поверх общих DTO и существующего EventBus.

Сервер не получает ``DigitalBeing`` и не читает Core. Runtime заранее собирает
те же снимки, что передаёт Tk, и публикует их в :class:`SharedState`. Мутации
этапа 2 — только публикация тех же событий, что использует Tk; решения остаются
в AgentRunner/LifeController/LifeGuard. Прежний общий ``POST /api/action``
оставлен закрытым, чтобы не появился второй произвольный командный путь.

Запуск standalone-предпросмотра без ядра::

    python -m src.ui.web_dashboard --host 127.0.0.1 --port 8765

Standalone честно показывает отсутствие ядра и не принимает мутации. Рабочий
экран рядом с Tk создаётся в ``main.py``. Транспорт — aiohttp и SSE.
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
BUS_KEY: web.AppKey = web.AppKey("bus", Any) if AIOHTTP_AVAILABLE else None

DIALOGUE_EVENTS = (
    "agent_question",
    "agent_message",
    "agent_thought",
    "agent_web_result",
    "user_message",
)
CONTROL_EVENTS = ("life_prompt", "life_result")
READ_ONLY_MESSAGE = "устаревший общий маршрут закрыт: используйте узкие команды этапа 2"
MAX_JSON_BYTES = 16_384
MAX_DIALOGUE_CHARS = 8_000
MAX_REASON_CHARS = 500
MAX_PHRASE_CHARS = 500
ACCESS_KEYS = frozenset({"network", "delamain", "effector", "presence"})
SPEED_MODES = frozenset({"live", "fast", "max"})


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Digital Being — обсерватория</title>
<style>
:root{color-scheme:dark;
--p-bg:oklch(0.16 0.025 255);--p-surface:oklch(0.205 0.03 255);--p-raised:oklch(0.255 0.035 255);
--p-text:oklch(0.93 0.02 220);--p-muted:oklch(0.75 0.035 240);--p-border:oklch(0.37 0.055 245);
--p-cyan:oklch(0.86 0.15 195);--p-cyan-soft:oklch(0.79 0.09 205);--p-red:oklch(0.68 0.24 25);
--p-red-soft:oklch(0.79 0.15 25);--p-green:oklch(0.82 0.11 165);--p-amber:oklch(0.84 0.12 85);
--emotion-joy:oklch(0.85 0.12 95);--emotion-sadness:oklch(0.73 0.09 260);
--emotion-fear:oklch(0.77 0.09 310);--emotion-calm:oklch(0.82 0.1 165);--emotion-default:oklch(0.79 0.09 205);
--bg:var(--p-bg);--surface:var(--p-surface);--raised:var(--p-raised);--border:var(--p-border);
--text:var(--p-text);--muted:var(--p-muted);--cyan:var(--p-cyan);--cyan-soft:var(--p-cyan-soft);
--red:var(--p-red);--red-soft:var(--p-red-soft);--green:var(--p-green);--amber:var(--p-amber);--danger:var(--p-red-soft);
--card-bg:var(--surface);--control-bg:var(--raised);--graph-concept:var(--cyan);--graph-intention:var(--green);--graph-other:var(--red-soft)}
*{box-sizing:border-box}html{min-width:0;background:var(--bg)}body{position:relative;min-height:100dvh;margin:0;background:var(--bg);background-image:linear-gradient(oklch(0.55 0.06 230 / .035) 1px,transparent 1px),linear-gradient(90deg,oklch(0.55 0.06 230 / .035) 1px,transparent 1px);background-size:48px 48px;color:var(--text);font:16px/1.6 Bahnschrift,"Arial Narrow",sans-serif}
body::before{content:"";position:fixed;inset:0;z-index:2;pointer-events:none;background:repeating-linear-gradient(0deg,transparent 0 3px,oklch(0.9 0.08 195 / .014) 3px 4px)}
header{position:sticky;top:0;z-index:20;background:oklch(0.17 0.028 255 / .94);border-bottom:1px solid oklch(0.65 0.1 210 / .35);padding:20px 28px 12px;backdrop-filter:blur(16px)}
.brand{display:flex;align-items:center;gap:12px 16px;flex-wrap:wrap}.brand h1{margin:0;color:var(--red-soft);font-size:26px;font-weight:650;line-height:1.2;letter-spacing:.08em;text-transform:uppercase;text-shadow:0 0 22px oklch(0.68 0.24 25 / .28)}.brand .cycle{color:var(--muted);font:14px/1.4 Consolas,monospace;letter-spacing:.04em}
.badge{padding:4px 9px;border:1px solid oklch(0.68 0.24 25 / .55);border-radius:2px;color:var(--red-soft);font-size:12px;font-weight:600;line-height:1.4;letter-spacing:.08em}
nav{display:flex;gap:6px;margin-top:16px;overflow-x:auto;scrollbar-width:thin;scrollbar-color:var(--border) transparent}nav button,.pager button{min-height:44px;padding:9px 14px;border:1px solid transparent;border-radius:3px;background:transparent;color:var(--muted);font:600 14px/1.4 Bahnschrift,"Arial Narrow",sans-serif;letter-spacing:.035em;white-space:nowrap;cursor:pointer;transition:color .16s ease-out,background-color .16s ease-out,border-color .16s ease-out,box-shadow .16s ease-out,transform .16s ease-out}
nav button.active{border-color:oklch(0.86 0.15 195 / .5);background:oklch(0.35 0.07 220 / .42);color:var(--cyan);box-shadow:inset 0 -1px var(--cyan),0 0 18px oklch(0.86 0.15 195 / .08)}nav button:hover:not(.active){border-color:oklch(0.68 0.24 25 / .48);background:oklch(0.3 0.07 25 / .25);color:var(--red-soft)}nav button:active,.pager button:active:not(:disabled){transform:translateY(1px)}
button:focus-visible,select:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--cyan);outline-offset:3px;box-shadow:0 0 0 1px var(--bg),0 0 16px oklch(0.86 0.15 195 / .2)}
main{position:relative;z-index:1;max-width:1400px;margin:auto;padding:24px 28px 40px}.page{display:none}.page.active{display:block}
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:16px}.card{position:relative;min-width:0;padding:20px;overflow:hidden;border:1px solid oklch(0.45 0.06 240 / .62);border-radius:4px;background:var(--card-bg);box-shadow:0 12px 32px oklch(0.08 0.02 255 / .2);clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px))}
.card::before{content:"";position:absolute;top:0;right:0;width:24px;height:24px;border-top:1px solid var(--cyan);border-right:1px solid var(--cyan);opacity:.6;pointer-events:none}.card::after{content:"";position:absolute;bottom:0;left:12px;width:36px;height:1px;background:var(--red);opacity:.65;pointer-events:none}
.span-4{grid-column:span 4}.span-6{grid-column:span 6}.span-8{grid-column:span 8}.span-12{grid-column:span 12}
h2{margin:0 0 16px;color:var(--cyan-soft);font-size:13px;font-weight:650;line-height:1.5;letter-spacing:.13em;text-transform:uppercase}h3{margin:0 0 10px;color:var(--text);font-size:18px;font-weight:600;line-height:1.4}
.big{color:var(--text);font-size:32px;font-weight:600;line-height:1.25;letter-spacing:.015em}.muted{color:var(--muted)}.good{color:var(--green)}.warn{color:var(--amber)}
.rows{display:grid;gap:0}.row{display:flex;justify-content:space-between;align-items:center;gap:16px;min-height:44px;padding:9px 0;border-bottom:1px solid oklch(0.45 0.06 240 / .35)}.row:last-child{border-bottom:0}.row span:last-child{text-align:right;overflow-wrap:anywhere}
.meter{height:5px;margin:7px 0 14px;overflow:hidden;border-radius:1px;background:oklch(0.34 0.04 250 / .75)}.meter>i{display:block;height:100%;background:var(--emotion-color,var(--emotion-default));box-shadow:0 0 10px var(--emotion-color,var(--emotion-default));transition:width .2s ease-out}
.list{display:grid;gap:10px}.entry{padding:12px 14px;overflow-wrap:anywhere;border:1px solid oklch(0.45 0.06 240 / .32);border-radius:3px;background:oklch(0.24 0.033 255 / .82)}.entry time,.entry .meta{color:var(--muted);font-size:12px;line-height:1.5}.entry p{margin:7px 0 0;white-space:pre-wrap}.empty{padding:18px 0;color:var(--muted);font-style:normal}
pre{max-height:540px;margin:12px 0 0;overflow:auto;color:oklch(0.84 0.035 230);font:13px/1.6 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.pager{display:flex;align-items:center;gap:10px;margin-top:16px;flex-wrap:wrap}.pager button{border-color:var(--border);background:var(--control-bg)}.pager button:hover:not(:disabled){border-color:var(--cyan);color:var(--cyan)}.pager button:disabled{opacity:.4;cursor:not-allowed}
.graph-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 12px}.graph-toolbar .control-button{min-width:44px;flex:0 0 44px;padding:8px}.graph-toolbar #graph-reset{flex:0 1 150px;padding:8px 14px}.graph-zoom{min-width:58px;text-align:center;color:var(--cyan);font:600 14px/1.4 Consolas,monospace}.graph-help{margin:0 0 12px;color:var(--muted);font-size:13px}.graph-stage{position:relative}#graph{display:block;width:100%;height:600px;border:1px solid oklch(0.45 0.06 240 / .35);border-radius:3px;background:oklch(0.145 0.025 255);touch-action:none;user-select:none;cursor:grab}#graph:active{cursor:grabbing}#graph:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}.graph-label{fill:var(--text);font:12px/1.4 Bahnschrift,"Arial Narrow",sans-serif;paint-order:stroke;stroke:oklch(0.145 0.025 255);stroke-width:4px;stroke-linejoin:round;pointer-events:none}.graph-label.is-active{fill:var(--red-soft);font-weight:650}.graph-edge{stroke:var(--cyan-soft);stroke-opacity:.25;stroke-width:.8;transition:opacity .16s ease-out,stroke .16s ease-out}.graph-node{cursor:pointer;transition:opacity .16s ease-out}.graph-node circle{stroke:oklch(0.9 0.03 220 / .16);stroke-width:.7}.graph-node.is-dim{opacity:.12}.graph-edge.is-dim{opacity:.06}.graph-node.is-hot circle{stroke:var(--text);stroke-width:1.8}.graph-edge.is-hot{stroke:var(--red-soft);stroke-opacity:.95;stroke-width:1.8;opacity:1}
#dialogue-feed{max-height:680px;margin-top:16px;overflow:auto}.dialogue-agent{border-left:1px solid var(--green)}.dialogue-user{border-left:1px solid var(--cyan)}.dialogue-thought{border-left:1px solid var(--muted)}
.notice{margin:0 0 16px;color:var(--muted);max-width:75ch}.status-dot{display:inline-block;width:7px;height:7px;margin-right:8px;border-radius:50%;background:var(--green);box-shadow:0 0 10px oklch(0.82 0.11 165 / .55)}
[hidden]{display:none!important}.controls{display:flex;gap:8px;flex-wrap:wrap}.control-button,.control-select,.control-input,textarea{min-height:44px;padding:10px 14px;border:1px solid var(--border);border-radius:3px;background:var(--control-bg);color:var(--text);font:16px/1.5 Bahnschrift,"Arial Narrow",sans-serif}.control-button{font-size:14px;font-weight:600;letter-spacing:.025em;cursor:pointer;transition:color .16s ease-out,background-color .16s ease-out,border-color .16s ease-out,box-shadow .16s ease-out,transform .16s ease-out}.control-button:hover:not(:disabled){border-color:var(--cyan);background:oklch(0.32 0.06 225);color:var(--cyan);box-shadow:0 0 16px oklch(0.86 0.15 195 / .1)}.control-button:active:not(:disabled){transform:translateY(1px)}.control-button:disabled,.control-select:disabled,.control-input:disabled,textarea:disabled{opacity:.48;cursor:not-allowed}.danger{border-color:oklch(0.68 0.24 25 / .65);color:var(--red-soft)}.danger:hover:not(:disabled){border-color:var(--red);background:oklch(0.3 0.07 25);color:var(--red-soft);box-shadow:0 0 16px oklch(0.68 0.24 25 / .12)}.control-stack{display:grid;gap:12px}.control-line{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.control-input{min-width:0;flex:1}.phrase{color:var(--amber);font:600 16px/1.5 Consolas,monospace;overflow-wrap:anywhere}.feedback{min-height:24px;margin:10px 0 0;color:var(--muted);overflow-wrap:anywhere}.feedback.error{color:var(--danger)}.life-panel{margin-top:16px;padding:16px;border:1px solid oklch(0.84 0.12 85 / .45);border-radius:3px;background:oklch(0.23 0.04 80 / .55)}textarea{width:100%;min-height:112px;resize:vertical}.access-action{min-width:112px}.connection-off{color:var(--amber)}
@media(max-width:850px){.span-4,.span-6,.span-8{grid-column:span 12}main{padding:16px 12px 32px}header{padding:16px 12px 10px}.brand{gap:8px 12px}.brand h1{font-size:22px}.grid{gap:12px}.card{padding:16px}.big{font-size:27px}#graph{height:440px}.control-button{flex:1 1 132px}#access-list .row{align-items:flex-start;flex-direction:column;gap:10px}#access-list .access-action{width:100%;min-height:44px;flex:0 0 44px}.life-panel .control-line{align-items:stretch;flex-direction:column}.life-panel .control-line .control-input{width:100%;flex:1 0 44px}.life-panel .control-line .control-button{width:100%;min-height:44px;flex:0 0 44px}#dialogue-send{flex-basis:100%}.row{gap:12px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation:none!important;transition-duration:.01ms!important}}
</style>
</head>
<body>
<header><div class="brand"><h1 id="agent-name">Digital Being</h1><span class="cycle" id="cycle">цикл —</span><span class="badge">ЭТАП 2 · СОБЫТИЯ ЯДРА</span></div>
<nav id="nav"><button data-page="now" class="active">Сейчас</button><button data-page="control">Управление</button><button data-page="diary">Дневник</button><button data-page="activities">Занятия</button><button data-page="graph">Карта</button><button data-page="access">Доступы</button><button data-page="dialogue">Диалог</button></nav></header>
<main>
<section id="page-now" class="page active"><div class="grid">
<div class="card span-4"><h2>Состояние</h2><div class="big" id="life-state">—</div><div class="rows" id="life-rows"></div></div>
<div class="card span-4"><h2>Эмоции</h2><div class="big" id="emotion-dominant">фон</div><div id="emotion-levels"></div></div>
<div class="card span-4"><h2>Тело</h2><div class="big" id="fatigue">—</div><div class="rows" id="body-rows"></div></div>
<div class="card span-6"><h2>Сейчас</h2><div id="now-activity"></div><h3>Объяснение выбора</h3><pre id="motivation">—</pre></div>
<div class="card span-6"><h2>Намерения</h2><div id="intentions" class="list"></div></div>
</div></section>
<section id="page-control" class="page"><div class="grid">
<div class="card span-6"><h2>Ритм и состояние</h2><p class="notice" id="core-connection">Проверяю соединение с ядром…</p><div class="control-stack"><div class="controls"><button id="pause-button" class="control-button needs-core" disabled>Пауза</button><button id="resume-button" class="control-button needs-core" disabled>Возобновить</button><button id="save-button" class="control-button needs-core" disabled>Сохранить</button></div><form id="speed-form" class="control-line"><label for="speed-mode">Темп жизни</label><select id="speed-mode" class="control-select needs-core" disabled><option value="live">Жизнь · 5 с</option><option value="fast">Ускорение · 0,5 с</option><option value="max">Лаборатория</option></select><button class="control-button needs-core" type="submit" disabled>Применить</button></form><div class="rows" id="control-facts"></div></div><p class="feedback" id="command-feedback" role="status"></p></div>
<div class="card span-6"><h2>Сон и уход · решения LifeGuard</h2><p class="notice">Создание запроса ничего не подтверждает. Точную фразу нужно ввести отдельно после паузы, заданной ядром.</p><div class="controls"><button id="dream-button" class="control-button needs-core" disabled>Запросить сон</button><button id="wake-button" class="control-button needs-core" disabled>Пробудить</button><button id="terminate-button" class="control-button danger needs-core" disabled>Запросить уход</button></div><div id="life-panel" class="life-panel" hidden><h3 id="life-title">Требуется подтверждение</h3><p id="life-description"></p><p>Запрос: <span id="life-request-id" class="muted"></span></p><p>Точная фраза: <span id="life-phrase" class="phrase"></span></p><form id="life-confirm-form" class="control-stack"><label for="life-confirm-input">Введите фразу вручную</label><div class="control-line"><input id="life-confirm-input" class="control-input" autocomplete="off" required maxlength="500"><button class="control-button" type="submit">Подтвердить</button></div></form><button id="life-cancel-button" class="control-button">Отменить запрос</button></div><p class="feedback" id="life-result" role="status"></p></div>
</div></section>
<section id="page-diary" class="page"><div class="card"><h2>Дневник · новые записи первыми</h2><p class="notice" id="diary-cache"></p><div id="diary-list" class="list"></div><div class="pager"><button id="diary-prev">← Новее</button><span id="diary-position" class="muted"></span><button id="diary-next">Старее →</button></div></div></section>
<section id="page-activities" class="page"><div class="grid" id="activity-cards"></div></section>
<section id="page-graph" class="page"><div class="card"><h2>Карта жизни</h2><div class="graph-toolbar" aria-label="Управление видом карты"><button id="graph-zoom-out" class="control-button" type="button" aria-label="Уменьшить карту">−</button><span id="graph-zoom" class="graph-zoom" aria-live="polite">100%</span><button id="graph-zoom-in" class="control-button" type="button" aria-label="Приблизить карту">+</button><button id="graph-reset" class="control-button" type="button">Сброс вида</button></div><p class="notice" id="graph-note"></p><p class="graph-help">Колесо или щипок — масштаб · перетаскивание — панорама · наведение или тап — связи узла · тап по пустому месту — сброс подсветки</p><div class="graph-stage"><svg id="graph" role="img" aria-label="Карта связей жизни" tabindex="0"></svg></div></div></section>
<section id="page-access" class="page"><div class="grid"><div class="card span-6"><h2>Разрешения · фактическое состояние</h2><div id="access-list" class="rows"></div><p class="notice">Кнопка отправляет существующую команду access. Индикация изменится только после фактического снимка.</p></div><div class="card span-6"><h2>Effector</h2><div id="effector-list" class="rows"></div></div></div></section>
<section id="page-dialogue" class="page"><div class="card"><h2><span class="status-dot"></span>Диалог · живой поток</h2><p class="notice">Сообщение уходит через USER_MESSAGE. Лента пополняется только событием шины; reconnect продолжается с последнего sequence.</p><form id="dialogue-form" class="control-stack"><label for="dialogue-input">Сообщение сущности</label><textarea id="dialogue-input" class="needs-core" maxlength="8000" required disabled placeholder="Ядро не подключено"></textarea><div class="control-line"><button id="dialogue-send" class="control-button needs-core" type="submit" disabled>Отправить через EventBus</button><span id="dialogue-feedback" class="feedback" role="status"></span></div></form><div id="dialogue-feed" class="list"></div></div></section>
</main>
<script>
'use strict';
const $=id=>document.getElementById(id);let diaryOffset=0,diaryLimit=20,lastSequence=0,eventSource=null,latestControl=null,renderedRequestId=null;
const value=v=>v===null||v===undefined||v===''?'—':String(v);const number=v=>Number.isFinite(Number(v))?Number(v).toFixed(2):'—';
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el}
function rows(target,items){const el=$(target);el.replaceChildren();for(const [k,v] of items){const r=node('div','','row');r.append(node('span',k),node('span',value(v)));el.append(r)}if(!items.length)el.append(node('div','Нет данных','empty'))}
async function getJSON(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(`${r.status} ${url}`);return r.json()}
async function postJSON(url,body={}){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(data.message||`${r.status}`);return data}
function feedback(id,text,error=false){const el=$(id);el.textContent=text||'';el.classList.toggle('error',error)}
async function sendCommand(url,body={},target='command-feedback'){try{const result=await postJSON(url,body);feedback(target,result.message);setTimeout(()=>{refreshControl();refreshNow()},250);return result}catch(e){feedback(target,e.message,true);return null}}
function renderAccess(access){const box=$('access-list');box.replaceChildren();for(const key of ['network','delamain','effector','presence']){const item=access[key];if(!item)continue;const row=node('div','','row'),text=node('span',`${item.label||key}: ${item.enabled?'включено':'выключено'}`),button=node('button',item.enabled?'Выключить':'Включить','control-button access-action');button.type='button';button.disabled=!latestControl?.bus_connected;button.setAttribute('aria-label',`${item.enabled?'Выключить':'Включить'} ${item.label||key}`);button.onclick=()=>sendCommand('/api/access',{key,state:item.enabled?'off':'on'});row.append(text,button);box.append(row)}if(!box.children.length)box.append(node('div',latestControl?.bus_connected?'Нет данных':'Ядро не подключено','empty'))}
async function refreshNow(){try{const [status,life]=await Promise.all([getJSON('/api/status'),getJSON('/api/life')]);const p=status.panel||{};$('agent-name').textContent=life.name||p.name||'Digital Being';$('cycle').textContent=`цикл ${life.life?.cycle??p.cycle??'—'}`;$('life-state').textContent=life.life?.state_label||'—';rows('life-rows',[['Энергия',`${number(life.life?.energy)} / ${number(p.max_energy)}`],['Режим',life.life?.speed_mode],['Пауза',life.life?.paused?'да':'нет'],['Семя',life.life?.seed_folder],['RSS, МБ',number(p.rss_mb)]]);
const emotions=life.emotions||{},levels=emotions.levels||{};$('emotion-dominant').textContent=emotions.dominant?.label||'спокойный фон';const box=$('emotion-levels');box.replaceChildren();for(const [name,raw] of Object.entries(levels)){const label=node('div',`${name} · ${number(raw)}`,'muted');const meter=node('div','','meter'),bar=node('i');bar.style.width=`${Math.max(0,Math.min(1,Number(raw)||0))*100}%`;bar.style.setProperty('--emotion-color',({joy:'var(--emotion-joy)',sadness:'var(--emotion-sadness)',fear:'var(--emotion-fear)',calm:'var(--emotion-calm)'}[name]||'var(--emotion-default)'));meter.append(bar);box.append(label,meter)}if(!Object.keys(levels).length)box.append(node('div','Нет данных','empty'));
const body=life.body||{};$('fatigue').textContent=body.fatigue_level||'—';rows('body-rows',[['Усталость',number(body.fatigue)],['АТФ',number(body.atp)],['АТФ, доля',number(body.atp_ratio)],['Глюкоза',number(body.glucose)],['Митохондрии',number(body.mitochondrial_health)],['Нужен отдых',body.needs_rest?'да':'нет']]);const activity=life.now?.activity;$('now-activity').replaceChildren(node('h3',activity?`${value(activity.action)} · ${value(activity.target)}`:'Свободный цикл'),node('div',activity?value(activity.reason||activity.source):'Нет активного намерения','muted'));$('motivation').textContent=JSON.stringify(life.motivation||{},null,2);const intents=$('intentions');intents.replaceChildren();for(const item of (life.intentions?.recent||[]).slice(-8).reverse()){const e=node('div','','entry');e.append(node('div',`${value(item.action)} · ${value(item.target)}`),node('div',`${value(item.status)} · цикл ${value(item.cycle)}`,'meta'));intents.append(e)}if(!intents.children.length)intents.append(node('div','Пока нет записанных намерений','empty'));
renderAccess(life.access||{});const effectorRows=[...Object.entries(life.effector?.counts||{}),['Последняя ошибка',life.effector?.last_error]];if(life.access?.workspace)effectorRows.unshift(['Рабочая область',life.access.workspace.path]);rows('effector-list',effectorRows);renderActivities(life.activities||{});}catch(e){console.warn(e)}}
function renderActivities(a){const box=$('activity-cards');box.replaceChildren();for(const [key,title] of [['creative','Тексты'],['art','Рисунки'],['music','Музыка'],['game','Игра'],['guess_game','Угадывание']]){const card=node('div','','card span-6');card.append(node('h2',title));const item=a[key];if(item&&typeof item==='object'&&!Array.isArray(item)){const count=item.count??((key==='game'||key==='guess_game')?'активна':'—');card.append(node('div',String(count),'big'));const pre=node('pre',JSON.stringify(item,null,2));card.append(pre)}else card.append(node('div',value(item),'muted'));box.append(card)}if(!box.children.length)box.append(node('div','Нет данных','empty'))}
async function refreshControl(){try{const c=await getJSON('/api/control');latestControl=c;document.querySelectorAll('.needs-core').forEach(el=>{el.disabled=!c.bus_connected});$('core-connection').textContent=c.bus_connected?'Ядро подключено. Команды идут через EventBus; ответ здесь означает только приём события.':'Ядро не подключено. Это standalone-превью: команды отключены.';$('core-connection').classList.toggle('connection-off',!c.bus_connected);$('dialogue-input').placeholder=c.bus_connected?'Напишите сообщение…':'Ядро не подключено';$('pause-button').disabled=!c.bus_connected||c.paused!==false;$('resume-button').disabled=!c.bus_connected||c.paused!==true;$('dream-button').disabled=!c.bus_connected||c.life_state!=='alive';$('terminate-button').disabled=!c.bus_connected||c.life_state!=='alive';$('wake-button').disabled=!c.bus_connected||c.life_state!=='dormant';if(c.speed_mode&&document.activeElement!==$('speed-mode'))$('speed-mode').value=c.speed_mode;const save=c.last_save_at?new Date(c.last_save_at*1000).toLocaleTimeString():'—';rows('control-facts',[['Фактическая пауза',c.paused===null||c.paused===undefined?'—':c.paused?'да':'нет'],['Фактический темп',c.speed_mode],['Состояние жизни',c.life_state],['Последнее сохранение',c.last_save_ok===null||c.last_save_ok===undefined?'ещё не было':`${save} · ${c.last_save_ok?'успешно':'ошибка'}`]]);const prompt=c.life_prompt;$('life-panel').hidden=!prompt;if(prompt){if(renderedRequestId!==prompt.request_id){$('life-confirm-input').value='';renderedRequestId=prompt.request_id}$('life-title').textContent=prompt.kind==='terminate'?'Подтверждение необратимого ухода':'Подтверждение сна';$('life-description').textContent=prompt.description||'Ядро ожидает явное подтверждение.';$('life-request-id').textContent=prompt.request_id;$('life-phrase').textContent=prompt.phrase||'—'}else renderedRequestId=null;const result=c.life_result;$('life-result').textContent=result?`${result.ok?'Результат: успешно':'Результат: отклонено'} · ${result.message||''}`:'';$('life-result').classList.toggle('error',!!result&&!result.ok);renderAccess(c.access||{})}catch(e){feedback('command-feedback',e.message,true)}}
async function refreshDiary(){try{const d=await getJSON(`/api/diary?offset=${diaryOffset}&limit=${diaryLimit}`),list=$('diary-list');list.replaceChildren();for(const item of d.episodes){const e=node('div','','entry');e.append(node('time',`цикл ${value(item.ts)} · ${value(item.action)} · ${item.ok?'завершено':'не завершено'}`));const args=item.args?.target?` · ${item.args.target}`:'';e.append(node('p',`${value(item.task)}${args}`));if(item.error)e.append(node('div',String(item.error),'warn'));list.append(e)}if(!d.episodes.length)list.append(node('div','Записей в этом окне нет','empty'));$('diary-cache').textContent=`В read-only кэше: ${d.stored} из максимум ${d.cache_limit}. Более старые записи могут существовать вне кэша.`;$('diary-position').textContent=`${d.returned?d.offset+1:0}–${d.offset+d.returned} / ${d.stored}`;$('diary-prev').disabled=d.offset===0;$('diary-next').disabled=!d.has_more}catch(e){console.warn(e)}}
const GRAPH_NS='http://www.w3.org/2000/svg';
let graphData={nodes:[],edges:[]},graphPositions={},graphSize={w:0,h:0},graphZoom=1,graphPan={x:0,y:0},graphSelected=null,graphHovered=null,graphGesture=null;
const graphPointers=new Map(),graphClamp=(v,min,max)=>Math.max(min,Math.min(max,v));
function graphRadius(n){return 5+10*Math.max(0,Math.min(1,Number(n.weight)||0))+(n.kind==='value'?2:0)}
function graphColor(n){return n.kind==='concept'?'var(--graph-concept)':n.kind==='intention'?'var(--graph-intention)':'var(--graph-other)'}
function graphLayout(nodes,w,h){
 const cx=w/2,cy=h/2,maxRadius=Math.max(40,Math.min(w,h)/2-26),groups={},positions={};
 for(const n of nodes){const kind=String(n.kind||'other');if(!groups[kind])groups[kind]=[];groups[kind].push(n)}
 function place(items,radius,offset){items.forEach((n,i)=>{const a=offset+Math.PI*2*i/Math.max(1,items.length);positions[n.id]=[cx+radius*Math.cos(a),cy+radius*Math.sin(a)]})}
 const concepts=(groups.concept||[]).slice().sort((a,b)=>(Number(b.weight)||0)-(Number(a.weight)||0)||String(a.id).localeCompare(String(b.id)));
 const rings=[[0,1],[.26,7],[.44,12],[.60,18],[.73,24],[.84,30]];let index=0;
 rings.forEach(([fraction,capacity],ringIndex)=>{const chunk=concepts.slice(index,index+capacity);index+=capacity;place(chunk,maxRadius*fraction,.4*(ringIndex+1))});
 const groupRings={forgotten:[.60,.70],intention:[.68,.78],activity:[.82,.90],value:[.96,1.0]},offsets={forgotten:.9,intention:1.7,activity:2.5,value:3.3};
 for(const [kind,[inner,outer]] of Object.entries(groupRings)){
  const items=(groups[kind]||[]).slice().sort((a,b)=>(Number(b.weight)||0)-(Number(a.weight)||0)||String(a.id).localeCompare(String(b.id)));
  place(items.slice(0,16),maxRadius*inner,offsets[kind]);place(items.slice(16),maxRadius*outer,offsets[kind]+.3);
 }
 const known=new Set(['concept',...Object.keys(groupRings)]);
 for(const kind of Object.keys(groups).filter(kind=>!known.has(kind)).sort())place(groups[kind],maxRadius*.5,0);
 return positions;
}
const graphMeasure=document.createElement('canvas').getContext('2d');
function graphLabelText(n){const limit=graphSize.w<500?(graphZoom>=1.9?18:12):(graphZoom>=1.9?34:24),text=String(n.label||n.id);return text.length<=limit?text:text.slice(0,limit-1)+'…'}
function graphLabelThreshold(){if(graphZoom<.7)return .92;if(graphZoom<1.15)return .68;if(graphZoom<1.75)return .45;if(graphZoom<2.5)return .28;return 0}
function graphBoxesOverlap(a,b,padding=3){return !(a[2]+padding<b[0]||b[2]+padding<a[0]||a[3]+padding<b[1]||b[3]+padding<a[1])}
function graphRenderLabels(){
 const layer=$('graph-labels');if(!layer)return;layer.replaceChildren();
 const active=graphHovered||graphSelected,neighbors=new Set(),threshold=graphLabelThreshold(),{w,h}=graphSize,cx=w/2,cy=h/2;
 if(active)for(const e of graphData.edges||[]){if(e.source===active)neighbors.add(e.target);if(e.target===active)neighbors.add(e.source)}
 const centers=(graphData.nodes||[]).map(n=>{const p=graphPositions[n.id];return p?[p[0],p[1],graphRadius(n),n.id]:null}).filter(Boolean);
 const candidates=(graphData.nodes||[]).filter(n=>n.id===active||(active&&neighbors.has(n.id)&&(Number(n.weight)||0)>=.15)||(Number(n.weight)||0)>=threshold);
 candidates.sort((a,b)=>(a.id===active?-1:b.id===active?1:0)||(Number(b.weight)||0)-(Number(a.weight)||0)||String(a.id).localeCompare(String(b.id)));
 graphMeasure.font='12px Bahnschrift, Arial Narrow, sans-serif';
 const used=[],margin=4/graphZoom,bounds=[-graphPan.x/graphZoom+margin,-graphPan.y/graphZoom+margin,(w-graphPan.x)/graphZoom-margin,(h-graphPan.y)/graphZoom-margin];
 function hitsNode(box,ownId){for(const [x,y,r,id] of centers){if(id===ownId)continue;const nx=Math.min(Math.max(x,box[0]),box[2]),ny=Math.min(Math.max(y,box[1]),box[3]);if((nx-x)**2+(ny-y)**2<(r+4)**2)return true}return false}
 for(const n of candidates){
  const position=graphPositions[n.id];if(!position)continue;
  const [x,y]=position,r=graphRadius(n),text=graphLabelText(n),textWidth=graphMeasure.measureText(text).width+10,textHeight=18,base=Math.atan2(y-cy,x-cx),angles=[0,.72,-.72,Math.PI/2,-Math.PI/2,Math.PI-.72,-Math.PI+.72,Math.PI];
  let fallback=null,placed=null;
  for(const offset of angles){
   const angle=base+offset,distance=r+9+Math.min(textWidth*.45,26),labelX=x+Math.cos(angle)*distance,labelY=y+Math.sin(angle)*distance;
   const box=[labelX-textWidth/2,labelY-textHeight/2,labelX+textWidth/2,labelY+textHeight/2];
   if(box[0]<bounds[0]||box[1]<bounds[1]||box[2]>bounds[2]||box[3]>bounds[3])continue;
   if(!fallback)fallback={box,text};
   if(n.id!==active&&hitsNode(box,n.id))continue;
   if(used.some(other=>graphBoxesOverlap(box,other)))continue;
   placed={box,text};break;
  }
  if(!placed&&fallback&&!used.some(other=>graphBoxesOverlap(fallback.box,other)))placed=fallback;
  if(!placed)continue;
  const [left,top,right,bottom]=placed.box,label=document.createElementNS(GRAPH_NS,'text');
  label.setAttribute('x',String((left+right)/2));label.setAttribute('y',String((top+bottom)/2+4));label.setAttribute('text-anchor','middle');
  label.setAttribute('class',`graph-label${n.id===active?' is-active':''}`);label.dataset.id=n.id;label.textContent=placed.text;layer.append(label);used.push(placed.box);
 }
 $('graph-note').textContent=`Узлов: ${(graphData.nodes||[]).length}; связей: ${(graphData.edges||[]).length}; подписей: ${layer.children.length}; скрыто сверх лимита: ${graphData.omitted||0}`;
}
function graphUpdate(){
 const viewport=$('graph-viewport');if(!viewport)return;
 viewport.setAttribute('transform',`translate(${graphPan.x} ${graphPan.y}) scale(${graphZoom})`);$('graph-zoom').textContent=`${Math.round(graphZoom*100)}%`;
 const active=graphHovered||graphSelected,neighbors=new Set();if(active)neighbors.add(active);
 for(const line of $('graph-edges').children){
  const hot=active&&(line.dataset.source===active||line.dataset.target===active);
  if(hot)neighbors.add(line.dataset.source===active?line.dataset.target:line.dataset.source);
  line.classList.toggle('is-hot',!!hot);line.classList.toggle('is-dim',!!active&&!hot);
 }
 for(const group of $('graph-nodes').children){const related=!active||neighbors.has(group.dataset.id);group.classList.toggle('is-dim',!related);group.classList.toggle('is-hot',group.dataset.id===active)}
 graphRenderLabels();
}
function graphRender(){
 const svg=$('graph'),w=Math.max(320,Math.round(svg.clientWidth||0)),h=Math.max(320,Math.round(svg.clientHeight||0));if(!svg.clientWidth)return;
 graphSize={w,h};graphPositions=graphLayout(graphData.nodes||[],w,h);svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.replaceChildren();
 const viewport=document.createElementNS(GRAPH_NS,'g');viewport.id='graph-viewport';
 const edges=document.createElementNS(GRAPH_NS,'g');edges.id='graph-edges';
 const nodes=document.createElementNS(GRAPH_NS,'g');nodes.id='graph-nodes';
 const labels=document.createElementNS(GRAPH_NS,'g');labels.id='graph-labels';
 for(const e of graphData.edges||[]){const p=graphPositions[e.source],q=graphPositions[e.target];if(!p||!q)continue;const line=document.createElementNS(GRAPH_NS,'line');line.setAttribute('x1',p[0]);line.setAttribute('y1',p[1]);line.setAttribute('x2',q[0]);line.setAttribute('y2',q[1]);line.setAttribute('class','graph-edge');line.dataset.source=e.source;line.dataset.target=e.target;edges.append(line)}
 for(const n of graphData.nodes||[]){const position=graphPositions[n.id];if(!position)continue;const [x,y]=position,group=document.createElementNS(GRAPH_NS,'g'),circle=document.createElementNS(GRAPH_NS,'circle'),title=document.createElementNS(GRAPH_NS,'title');group.setAttribute('class','graph-node');group.dataset.id=n.id;circle.setAttribute('cx',x);circle.setAttribute('cy',y);circle.setAttribute('r',String(graphRadius(n)));circle.setAttribute('fill',graphColor(n));title.textContent=String(n.label||n.id);group.append(circle,title);nodes.append(group)}
 viewport.append(edges,nodes,labels);svg.append(viewport);graphUpdate();
}
async function refreshGraph(){try{if(!$('page-graph').classList.contains('active')||!$('graph').clientWidth)return;graphData=await getJSON('/api/graph');graphRender()}catch(e){console.warn(e)}}
function graphPoint(event){const rect=$('graph').getBoundingClientRect();return{x:event.clientX-rect.left,y:event.clientY-rect.top}}
function graphZoomAt(next,point=null){const svg=$('graph');if(!svg.clientWidth)return;const p=point||{x:svg.clientWidth/2,y:svg.clientHeight/2},zoom=graphClamp(next,.45,4.5),worldX=(p.x-graphPan.x)/graphZoom,worldY=(p.y-graphPan.y)/graphZoom;graphPan={x:p.x-worldX*zoom,y:p.y-worldY*zoom};graphZoom=zoom;graphUpdate()}
function graphResetView(){graphZoom=1;graphPan={x:0,y:0};graphSelected=null;graphHovered=null;graphUpdate()}
$('graph-zoom-in').onclick=()=>graphZoomAt(graphZoom*1.35);$('graph-zoom-out').onclick=()=>graphZoomAt(graphZoom/1.35);$('graph-reset').onclick=graphResetView;
$('graph').addEventListener('wheel',event=>{event.preventDefault();graphZoomAt(graphZoom*Math.exp(-event.deltaY*.0015),graphPoint(event))},{passive:false});
$('graph').addEventListener('keydown',event=>{const moves={ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]};if(event.key==='+'||event.key==='='){event.preventDefault();graphZoomAt(graphZoom*1.35)}else if(event.key==='-'){event.preventDefault();graphZoomAt(graphZoom/1.35)}else if(event.key==='0'){event.preventDefault();graphResetView()}else if(moves[event.key]){event.preventDefault();const [dx,dy]=moves[event.key];graphPan={x:graphPan.x+dx,y:graphPan.y+dy};graphUpdate()}});
$('graph').addEventListener('pointerover',event=>{if(event.pointerType!=='mouse')return;const group=event.target.closest('.graph-node');if(group&&group.dataset.id!==graphHovered){graphHovered=group.dataset.id;graphUpdate()}});
$('graph').addEventListener('pointerout',event=>{if(event.pointerType!=='mouse')return;const group=event.target.closest('.graph-node');if(group&&group.contains(event.relatedTarget))return;if(graphHovered){graphHovered=null;graphUpdate()}});
$('graph').addEventListener('pointerdown',event=>{if(event.pointerType==='mouse'&&event.button!==0)return;const svg=$('graph'),point=graphPoint(event),group=event.target.closest('.graph-node');svg.setPointerCapture(event.pointerId);graphPointers.set(event.pointerId,point);
 if(graphPointers.size===1)graphGesture={last:point,start:point,moved:false,nodeId:group?.dataset.id||null,pinch:false};
 else if(graphPointers.size===2){const [a,b]=[...graphPointers.values()];graphGesture={pinch:true,moved:true,lastDistance:Math.hypot(a.x-b.x,a.y-b.y)}}
});
$('graph').addEventListener('pointermove',event=>{if(!graphPointers.has(event.pointerId))return;const point=graphPoint(event);graphPointers.set(event.pointerId,point);
 if(graphPointers.size===2){const [a,b]=[...graphPointers.values()],distance=Math.hypot(a.x-b.x,a.y-b.y),center={x:(a.x+b.x)/2,y:(a.y+b.y)/2};if(graphGesture?.lastDistance>0)graphZoomAt(graphZoom*distance/graphGesture.lastDistance,center);graphGesture={pinch:true,moved:true,lastDistance:distance};return}
 if(!graphGesture||graphGesture.pinch)return;const dx=point.x-graphGesture.last.x,dy=point.y-graphGesture.last.y;if(Math.hypot(point.x-graphGesture.start.x,point.y-graphGesture.start.y)>4)graphGesture.moved=true;if(graphGesture.moved){graphPan={x:graphPan.x+dx,y:graphPan.y+dy};graphUpdate()}graphGesture.last=point;
});
function graphPointerEnd(event){if(!graphPointers.has(event.pointerId))return;const wasTap=graphPointers.size===1&&graphGesture&&!graphGesture.moved,nodeId=graphGesture?.nodeId;graphPointers.delete(event.pointerId);
 if(wasTap){if(nodeId)graphSelected=graphSelected===nodeId?null:nodeId;else graphSelected=null;graphHovered=null;graphUpdate()}
 if(graphPointers.size===1){const [point]=[...graphPointers.values()];graphGesture={last:point,start:point,moved:true,nodeId:null,pinch:false}}else graphGesture=null;
}
$('graph').addEventListener('pointerup',graphPointerEnd);$('graph').addEventListener('pointercancel',graphPointerEnd);
if(window.ResizeObserver){const observer=new ResizeObserver(()=>{if(!$('page-graph').classList.contains('active'))return;const w=Math.round($('graph').clientWidth),h=Math.round($('graph').clientHeight);if(w&&h&&(w!==graphSize.w||h!==graphSize.h))graphRender()});observer.observe($('graph'))}
function addDialogue(item){if(!item||item.sequence<=lastSequence)return;lastSequence=Math.max(lastSequence,item.sequence);if(item.kind==='life_prompt'||item.kind==='life_result'){refreshControl();return}const e=node('div','',`entry dialogue-${item.kind==='user'?'user':item.kind==='thought'?'thought':'agent'}`);e.append(node('time',`${item.time||''} · #${item.sequence} · ${item.kind}`),node('p',item.text||JSON.stringify(item.data||{})));$('dialogue-feed').prepend(e);while($('dialogue-feed').children.length>100)$('dialogue-feed').lastChild.remove()}
async function startDialogue(){try{const d=await getJSON('/api/dialogue?limit=50');for(const item of d.events)addDialogue(item);connectDialogue()}catch(e){setTimeout(startDialogue,3000)}}
function connectDialogue(){if(eventSource)eventSource.close();eventSource=new EventSource(`/stream/dialogue?after=${lastSequence}`);eventSource.onmessage=e=>{try{addDialogue(JSON.parse(e.data))}catch(err){console.warn(err)}};eventSource.onerror=()=>{/* EventSource reconnects with Last-Event-ID; sequence also deduplicates. */}}
$('nav').addEventListener('click',e=>{const button=e.target.closest('button[data-page]');if(!button)return;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===`page-${button.dataset.page}`));if(button.dataset.page==='diary')refreshDiary();if(button.dataset.page==='graph')refreshGraph();if(button.dataset.page==='control')refreshControl()});
$('diary-prev').onclick=()=>{diaryOffset=Math.max(0,diaryOffset-diaryLimit);refreshDiary()};$('diary-next').onclick=()=>{diaryOffset+=diaryLimit;refreshDiary()};
$('pause-button').onclick=()=>sendCommand('/api/control/pause');$('resume-button').onclick=()=>sendCommand('/api/control/resume');$('save-button').onclick=()=>sendCommand('/api/control/save');$('dream-button').onclick=()=>sendCommand('/api/control/life/request',{kind:'dream',reason:'запрос из окна'},'life-result');$('terminate-button').onclick=()=>sendCommand('/api/control/life/request',{kind:'terminate',reason:'запрос из окна'},'life-result');$('wake-button').onclick=()=>sendCommand('/api/control/life/wake',{},'life-result');
$('speed-form').onsubmit=e=>{e.preventDefault();sendCommand('/api/control/speed',{mode:$('speed-mode').value})};
$('dialogue-form').onsubmit=async e=>{e.preventDefault();const input=$('dialogue-input'),text=input.value.trim();if(!text){feedback('dialogue-feedback','Сообщение не должно быть пустым',true);return}const result=await sendCommand('/api/dialogue',{text},'dialogue-feedback');if(result){input.value='';input.focus()}};
$('life-confirm-form').onsubmit=e=>{e.preventDefault();const prompt=latestControl?.life_prompt;if(!prompt){feedback('life-result','Активного запроса ядра нет',true);return}sendCommand('/api/control/life/confirm',{request_id:prompt.request_id,phrase:$('life-confirm-input').value},'life-result')};$('life-cancel-button').onclick=()=>{const prompt=latestControl?.life_prompt;if(prompt)sendCommand('/api/control/life/cancel',{request_id:prompt.request_id},'life-result')};
refreshNow();refreshControl();refreshDiary();refreshGraph();startDialogue();setInterval(refreshNow,3000);setInterval(refreshControl,1000);setInterval(refreshGraph,5000);
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
        self._life_prompt: Optional[Dict[str, Any]] = None
        self._life_result: Optional[Dict[str, Any]] = None
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
        """Добавить событие с монотонным SSE sequence и отразить life-протокол."""
        payload = deepcopy(data) if isinstance(data, dict) else {"text": str(data or "")}
        ts = float(timestamp or time.time())
        kind = {
            "agent_question": "question", "agent_message": "agent",
            "agent_thought": "thought", "agent_web_result": "web",
            "user_message": "user",
        }.get(name, name)
        text = (payload.get("content") or payload.get("text")
                or payload.get("question") or payload.get("title")
                or payload.get("extract") or payload.get("description")
                or payload.get("message") or "")
        with self._lock:
            if name == "life_prompt":
                self._life_prompt = deepcopy(payload)
                self._life_result = None
            elif name == "life_result":
                self._life_result = deepcopy(payload)
                if payload.get("ok") is True:
                    self._life_prompt = None
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

    def control_snapshot(self, *, bus_connected: bool) -> Dict[str, Any]:
        """Только наблюдаемые DTO: никакого optimistic UI после команд."""
        with self._lock:
            status = deepcopy(self._status)
            return {
                "bus_connected": bool(bus_connected),
                "paused": status.get("paused"),
                "speed_mode": status.get("speed_mode"),
                "available_speeds": sorted(SPEED_MODES),
                "life_state": status.get("life_state", "unknown"),
                "pending_life_request": deepcopy(status.get("pending_life_request")),
                "life_prompt": deepcopy(self._life_prompt),
                "life_result": deepcopy(self._life_result),
                "last_save_ok": status.get("last_save_ok"),
                "last_save_at": status.get("last_save_at"),
                "access": deepcopy(self._life.get("access", {})),
            }

    def current_life_prompt(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return deepcopy(self._life_prompt)

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


class CommandError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


async def _read_json_object(request: Any) -> Dict[str, Any]:
    if request.content_type != "application/json":
        raise CommandError("ожидается application/json", status=415)
    if request.content_length is not None and request.content_length > MAX_JSON_BYTES:
        raise CommandError("слишком большой запрос", status=413)
    raw = await request.content.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise CommandError("слишком большой запрос", status=413)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandError("некорректный JSON") from exc
    if not isinstance(data, dict):
        raise CommandError("тело запроса должно быть JSON-объектом")
    return data


def _publish_event(request: Any, name: str, data: Dict[str, Any]) -> Any:
    """Единственная мутация веба: опубликовать существующее событие Tk."""
    bus = request.app[BUS_KEY]
    if bus is None:
        return _json_response({
            "status": "unavailable", "message": "ядро не подключено; команда не отправлена",
        }, status=503)
    accepted = bus.publish_sync(name, data, source="web")
    if not accepted:
        return _json_response({
            "status": "unavailable", "message": "очередь событий недоступна; команда не принята",
        }, status=503)
    return _json_response({
        "status": "accepted", "event": name,
        "message": "событие принято; результат появится в следующем снимке",
    }, status=202)


async def handle_dialogue_send(request: Any) -> Any:
    from src.core.event_bus import Events
    try:
        data = await _read_json_object(request)
        text = str(data.get("text", "")).strip()
        if not text:
            raise CommandError("сообщение не должно быть пустым")
        if len(text) > MAX_DIALOGUE_CHARS:
            raise CommandError(f"сообщение длиннее {MAX_DIALOGUE_CHARS} символов")
    except CommandError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=exc.status)
    return _publish_event(request, Events.USER_MESSAGE, {"text": text})


async def handle_control(request: Any) -> Any:
    return _json_response(request.app[STATE_KEY].control_snapshot(
        bus_connected=request.app[BUS_KEY] is not None,
    ))


async def handle_pause(request: Any) -> Any:
    from src.core.event_bus import Events
    return _publish_event(request, Events.PAUSE_REQUESTED, {})


async def handle_resume(request: Any) -> Any:
    from src.core.event_bus import Events
    return _publish_event(request, Events.RESUME_REQUESTED, {})


async def handle_save(request: Any) -> Any:
    from src.core.event_bus import Events
    return _publish_event(request, Events.SAVE_REQUESTED, {})


async def handle_speed(request: Any) -> Any:
    from src.core.event_bus import Events
    try:
        data = await _read_json_object(request)
        mode = str(data.get("mode", "")).strip().lower()
        if mode not in SPEED_MODES:
            raise CommandError("темп должен быть live, fast или max")
    except CommandError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=exc.status)
    return _publish_event(request, Events.SPEED_CHANGED, {"mode": mode})


async def handle_life_request(request: Any) -> Any:
    from src.core.event_bus import Events
    try:
        data = await _read_json_object(request)
        kind = str(data.get("kind", "dream")).strip().lower()
        reason = str(data.get("reason", "") or "запрос из окна").strip()
        if kind not in {"dream", "terminate"}:
            raise CommandError("kind должен быть dream или terminate")
        if not reason or len(reason) > MAX_REASON_CHARS:
            raise CommandError("причина пуста или слишком длинна")
    except CommandError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=exc.status)
    return _publish_event(request, Events.LIFE_REQUEST, {"kind": kind, "reason": reason})


async def handle_life_confirm(request: Any) -> Any:
    from src.core.event_bus import Events
    try:
        data = await _read_json_object(request)
        request_id = str(data.get("request_id", "")).strip()
        phrase = str(data.get("phrase", "")).strip()
        if not request_id or not phrase or len(phrase) > MAX_PHRASE_CHARS:
            raise CommandError("нужны request_id и непустая фраза допустимой длины")
        prompt = request.app[STATE_KEY].current_life_prompt()
        if not prompt or str(prompt.get("request_id", "")) != request_id:
            raise CommandError("сначала дождитесь подтверждающего запроса ядра", status=409)
    except CommandError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=exc.status)
    return _publish_event(request, Events.LIFE_CONFIRM, {
        "request_id": request_id, "phrase": phrase,
    })


async def handle_life_cancel(request: Any) -> Any:
    from src.core.event_bus import Events
    try:
        data = await _read_json_object(request)
        request_id = str(data.get("request_id", "")).strip()
        prompt = request.app[STATE_KEY].current_life_prompt()
        if not request_id or not prompt or str(prompt.get("request_id", "")) != request_id:
            raise CommandError("активный запрос с таким request_id не найден", status=409)
    except CommandError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=exc.status)
    return _publish_event(request, Events.LIFE_CANCEL, {"request_id": request_id})


async def handle_life_wake(request: Any) -> Any:
    from src.core.event_bus import Events
    return _publish_event(request, Events.LIFE_WAKE, {})


async def handle_access(request: Any) -> Any:
    from src.core.event_bus import Events
    try:
        data = await _read_json_object(request)
        key = str(data.get("key", "")).strip().lower()
        state = str(data.get("state", "")).strip().lower()
        if key not in ACCESS_KEYS or state not in {"on", "off"}:
            raise CommandError("нужны известный доступ и состояние on/off")
    except CommandError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=exc.status)
    return _publish_event(request, Events.USER_COMMAND, {"command": f"access {key} {state}"})


async def handle_health(request: Any) -> Any:
    snapshot = request.app[STATE_KEY].snapshot()
    now = time.time()
    updated = snapshot.get("last_update_ts", 0)
    bus_connected = request.app[BUS_KEY] is not None
    responsive = bool(bus_connected and updated and now - updated < 60)
    age = now - updated if updated else None
    if request.query.get("check", "live").lower() == "ready":
        if not responsive:
            reason = "ядро не подключено" if not bus_connected else "no agent update in 60+ seconds"
            return _json_response({"status": "not_ready", "agent_responsive": False,
                                   "last_update_age_sec": age,
                                   "reason": reason}, status=503)
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
    """aiohttp-сервер DTO и узких EventBus-команд; Core здесь недоступен."""

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8765

    def __init__(self, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 state: Optional[SharedState] = None, bus: Optional[Any] = None) -> None:
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp не установлен; веб отключён, Tk может работать")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("веб разрешает только localhost")
        self.host, self.port = host, port
        self.state = state or SharedState()
        self.bus = bus
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
        app[BUS_KEY] = self.bus
        app.router.add_get("/", handle_index)
        app.router.add_get("/health", handle_health)
        app.router.add_get("/metrics", handle_metrics)
        app.router.add_get("/api/status", handle_status)
        app.router.add_get("/api/life", handle_life)
        app.router.add_get("/api/diary", handle_diary)
        app.router.add_get("/api/dialogue", handle_dialogue)
        app.router.add_post("/api/dialogue", handle_dialogue_send)
        app.router.add_get("/api/control", handle_control)
        app.router.add_post("/api/control/pause", handle_pause)
        app.router.add_post("/api/control/resume", handle_resume)
        app.router.add_post("/api/control/speed", handle_speed)
        app.router.add_post("/api/control/save", handle_save)
        app.router.add_post("/api/control/life/request", handle_life_request)
        app.router.add_post("/api/control/life/confirm", handle_life_confirm)
        app.router.add_post("/api/control/life/cancel", handle_life_cancel)
        app.router.add_post("/api/control/life/wake", handle_life_wake)
        app.router.add_post("/api/access", handle_access)
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
        logger.info("Веб-интерфейс: http://%s:%s/", self.host, self.port)

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
