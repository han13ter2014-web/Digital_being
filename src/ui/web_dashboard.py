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
import math
import sys
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from src.ui import i18n

try:
    from aiohttp import web

    AIOHTTP_AVAILABLE = True
except ImportError:  # необязательная зависимость: Tk продолжает работать
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)
STATE_KEY: web.AppKey = web.AppKey("state", Any) if AIOHTTP_AVAILABLE else None
BUS_KEY: web.AppKey = web.AppKey("bus", Any) if AIOHTTP_AVAILABLE else None
VOICE_KEY: web.AppKey = web.AppKey("voice_input", Any) if AIOHTTP_AVAILABLE else None
VOICE_OUTPUT_KEY: web.AppKey = (
    web.AppKey("voice_output", Any) if AIOHTTP_AVAILABLE else None
)

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
MAX_TUTOR_URL_CHARS = 600
MAX_TUTOR_REQUEST_ID_CHARS = 40
MAX_EXTERNAL_SESSION_ID_CHARS = 160
MAX_EXTERNAL_TEXT_CHARS = 4_000
EXTERNAL_ACTIONS = frozenset(
    {
        "start",
        "auto",
        "pause",
        "resume",
        "manual",
        "ingest",
        "draft",
        "edit",
        "approve",
        "reject",
        "handoff",
        "stop",
        "clear",
    }
)
EXTERNAL_SESSION_ACTIONS = frozenset(
    {
        "draft",
        "approve",
        "reject",
        "handoff",
        "stop",
        "clear",
        "pause",
        "resume",
        "manual",
    }
)
SOCIAL_ACTIONS = frozenset(
    {
        "create",
        "grant",
        "session",
        "pause",
        "resume",
        "manual",
        "session-stop",
        "draft",
        "edit",
        "approve",
        "reject",
        "receive",
        "send",
        "revoke",
        "stop",
    }
)
SOCIAL_DRAFT_ACTIONS = frozenset({"approve", "reject"})
SOCIAL_CHANNEL_ACTIONS = frozenset(
    {"receive", "revoke", "stop", "pause", "resume", "manual", "session-stop"}
)
ACCESS_KEYS = frozenset({"network", "delamain", "effector", "presence"})
TUTOR_ACTIONS = frozenset(
    {
        "allow",
        "read",
        "revoke",
        "exercise",
        "solve",
        "approve",
        "approve_read",
        "reject",
    }
)
SPEED_MODES = frozenset({"live", "fast", "max"})


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#07090c">
<link rel="icon" href="data:,">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&family=PT+Serif:wght@400;700&family=Russo+One&display=swap" rel="stylesheet">
<title>Digital Being — обсерватория</title>
<style>
:root{color-scheme:light;
--bg:oklch(0.978 0.006 245);--surface:oklch(0.995 0.004 245);--raised:oklch(0.955 0.009 245);--border:oklch(0.9 0.012 245);
--text:oklch(0.255 0.025 250);--text-secondary:oklch(0.43 0.022 250);--muted:oklch(0.565 0.018 250);
--accent-soft:oklch(0.945 0.03 238);--accent-border:oklch(0.82 0.065 238);--accent:oklch(0.405 0.105 238);
--cyan:oklch(0.49 0.12 238);--cyan-soft:oklch(0.405 0.105 238);--red:oklch(0.58 0.14 25);--red-soft:oklch(0.48 0.12 25);
--green:oklch(0.43 0.075 164);--amber:oklch(0.48 0.095 65);--danger:var(--red-soft);--success-soft:oklch(0.95 0.03 164);
--warning-soft:oklch(0.96 0.035 88);--lavender-soft:oklch(0.945 0.025 286);--lavender:oklch(0.44 0.09 286);
--card-bg:var(--surface);--control-bg:var(--surface);--graph-concept:var(--cyan);--graph-intention:var(--green);--graph-other:var(--lavender);
--emotion-joy:oklch(0.7 0.13 82);--emotion-sadness:oklch(0.65 0.09 286);--emotion-fear:oklch(0.58 0.14 25);--emotion-calm:var(--cyan);--emotion-default:oklch(0.58 0.12 164);
--shadow:0 8px 26px oklch(0.3 0.025 250 / .045);--focus:var(--cyan)}
body.cyber-theme{color-scheme:dark;
--bg:#07090c;--surface:#10141a;--raised:#191e25;--border:#343c43;--text:#f3f1df;--text-secondary:#c9cdc9;--muted:#98a2a5;
--accent-soft:#252a0c;--accent-border:#767b16;--accent:#f2e600;--cyan:#42e8ff;--cyan-soft:#42e8ff;--red:#ff4555;--red-soft:#ff7380;
--green:#55fbd3;--amber:#fff77a;--danger:var(--red-soft);--success-soft:#0c2924;--warning-soft:#32171b;--lavender-soft:#10252b;--lavender:#e88bff;
--card-bg:var(--surface);--control-bg:var(--surface);--graph-concept:var(--cyan);--graph-intention:var(--green);--graph-other:var(--lavender);
--emotion-joy:#f2e600;--emotion-sadness:#c77dff;--emotion-fear:#ff4555;--emotion-calm:#42e8ff;--emotion-default:#55fbd3;
--shadow:0 12px 34px rgb(0 0 0 / .28);--focus:var(--cyan)}
*{box-sizing:border-box}html{min-width:0;background:var(--bg);scroll-behavior:smooth}body{min-width:0;min-height:100dvh;margin:0;background:var(--bg);color:var(--text);font:16px/1.6 Manrope,"Segoe UI",sans-serif;transition:background-color .18s ease-out,color .18s ease-out}button,input,select,textarea{font:inherit}button,summary{-webkit-tap-highlight-color:transparent}button:focus-visible,summary:focus-visible,select:focus-visible,input:focus-visible,textarea:focus-visible,[tabindex]:focus-visible{outline:3px solid var(--focus);outline-offset:3px}button:disabled,select:disabled,input:disabled,textarea:disabled{opacity:.46;cursor:not-allowed}[hidden]{display:none!important}h1,h2,h3,p{overflow-wrap:anywhere}::selection{background:var(--accent-border);color:var(--text)}
.app-shell{min-height:100dvh;background:var(--bg)}.cyber-theme .app-shell{background-color:var(--bg);background-image:radial-gradient(circle at 88% 2%,rgb(242 230 0/.08),transparent 26rem),linear-gradient(rgb(66 232 255/.035) 1px,transparent 1px),linear-gradient(90deg,rgb(66 232 255/.035) 1px,transparent 1px);background-size:auto,32px 32px,32px 32px}.cyber-theme::before{content:"";position:fixed;z-index:100;inset:0;background:repeating-linear-gradient(0deg,transparent 0 3px,rgb(0 0 0/.12) 3px 4px);opacity:.3;pointer-events:none}
.sidebar{display:none}.mobile-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:28px}.identity{display:flex;align-items:center;gap:12px;min-width:0}.identity strong{display:block;color:var(--text);font-size:15px;line-height:1.3}.identity span{display:block;margin-top:3px;color:var(--muted);font-size:12px;line-height:1.35}.life-mark{position:relative;display:grid;flex:0 0 44px;width:44px;height:44px;place-items:center;border:1px solid var(--accent-border);border-radius:15px;background:var(--accent-soft);color:var(--accent)}.life-mark svg{width:23px;height:23px}.life-mark::after{content:"";position:absolute;inset:5px;border:1px solid var(--accent-border);border-radius:11px;pointer-events:none}.brand-badge{display:inline-block;margin-top:24px;padding:5px 8px;border:1px solid var(--accent-border);color:var(--accent);font:600 10px/1.5 "IBM Plex Mono",monospace;letter-spacing:.06em}
#nav{display:grid;gap:5px;margin-top:28px}#nav button{position:relative;display:flex;min-height:44px;align-items:center;gap:11px;padding:10px 12px;border:1px solid transparent;border-radius:12px;background:transparent;color:var(--text-secondary);cursor:pointer;font-size:13px;font-weight:600;text-align:left;transition:background-color .14s ease-out,color .14s ease-out,border-color .14s ease-out}#nav button svg{flex:0 0 18px;width:18px;height:18px}#nav button:hover{background:var(--raised);color:var(--text)}#nav button.active{border-color:var(--accent-border);background:var(--accent-soft);color:var(--accent);font-weight:750}#nav button.active::after{content:"";width:6px;height:6px;margin-left:auto;border-radius:50%;background:currentcolor}.sidebar-foot{display:flex;align-items:center;gap:11px;margin-top:auto;padding:16px 10px 4px;border-top:1px solid var(--border)}.sidebar-foot strong,.sidebar-foot span{display:block}.sidebar-foot strong{color:var(--text-secondary);font-size:11px;line-height:1.4}.sidebar-foot span{margin-top:3px;color:var(--muted);font-size:10px;line-height:1.4}
.mobile-nav{position:relative;z-index:20}.mobile-nav summary{display:flex;min-height:44px;align-items:center;gap:8px;padding:10px 12px;border:1px solid var(--border);border-radius:12px;background:var(--surface);color:var(--text);cursor:pointer;font-size:14px;font-weight:650;list-style:none}.mobile-nav summary::-webkit-details-marker{display:none}.mobile-nav summary svg{width:17px;height:17px}.mobile-nav>nav{position:absolute;top:calc(100% + 8px);right:0;display:grid;width:220px;padding:8px;border:1px solid var(--border);border-radius:16px;background:var(--surface);box-shadow:0 16px 40px oklch(0.3 0.025 250/.18)}.mobile-nav button{display:flex;min-height:44px;align-items:center;gap:10px;padding:9px 10px;border:0;border-radius:9px;background:transparent;color:var(--text-secondary);cursor:pointer;text-align:left}.mobile-nav button svg{width:17px;height:17px}.mobile-nav button:hover,.mobile-nav button.active{background:var(--accent-soft);color:var(--accent)}
main{width:100%;max-width:1600px;min-height:100dvh;margin:0 auto;padding:16px 16px 28px}.topline{display:flex;flex-direction:column;gap:20px;margin-bottom:24px}.breadcrumb{display:flex;align-items:center;gap:6px;margin:0 0 10px;color:var(--muted);font-size:12px;font-weight:650;letter-spacing:.02em}.breadcrumb svg{width:14px;height:14px}h1{max-width:800px;margin:0;color:var(--text);font-family:"PT Serif",Georgia,serif;font-size:clamp(34px,8vw,52px);font-weight:400;letter-spacing:-.025em;line-height:1.12;text-wrap:balance}.page-description{max-width:70ch;margin:12px 0 0;color:var(--text-secondary);font-size:15px;line-height:1.65}.header-actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:10px}.cycle{flex:0 0 auto;padding:8px 10px;color:var(--muted);font:600 12px/1.4 "IBM Plex Mono",monospace;white-space:nowrap}
.control-button,.pager button,.theme-toggle{display:inline-flex;min-height:44px;align-items:center;justify-content:center;gap:8px;padding:10px 15px;border:1px solid var(--border);border-radius:12px;background:var(--control-bg);color:var(--text-secondary);cursor:pointer;font-size:14px;font-weight:700;transition:transform .14s ease-out,background-color .14s ease-out,border-color .14s ease-out,color .14s ease-out}.control-button:hover:not(:disabled),.pager button:hover:not(:disabled),.theme-toggle:hover{border-color:var(--accent-border);background:var(--accent-soft);color:var(--accent)}.control-button:active:not(:disabled),.pager button:active:not(:disabled),.theme-toggle:active{transform:translateY(1px)}.control-button svg,.theme-toggle svg{width:17px;height:17px}.theme-toggle{border-color:var(--accent-border)}.danger{border-color:var(--red)!important;color:var(--red-soft)!important}.danger:hover:not(:disabled){background:var(--warning-soft)!important;color:var(--red-soft)!important}
.demo-strip{display:flex;align-items:flex-start;gap:9px;margin-bottom:18px;padding:12px 14px;border:1px solid var(--accent-border);border-radius:14px;background:var(--accent-soft);color:var(--accent);font-size:12px;line-height:1.55}.demo-strip>svg{flex:0 0 16px;width:16px;height:16px;margin-top:2px}.demo-strip>span:nth-child(2){flex:1}.demo-strip .badge{flex:0 0 auto;padding-left:10px;font:700 11px/1.6 "IBM Plex Mono",monospace;white-space:nowrap}.connection-off{color:var(--amber)}
.page{display:none}.page.active{display:block}.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:18px}.card{position:relative;min-width:0;padding:20px;border:1px solid var(--border);border-radius:20px;background:var(--card-bg);box-shadow:var(--shadow)}.span-4,.span-6,.span-8,.span-12{grid-column:span 12}.card h2{margin:0 0 16px;color:var(--text);font-size:20px;font-weight:650;letter-spacing:-.018em;line-height:1.3}.card h3{margin:0 0 10px;color:var(--text);font-size:17px;font-weight:650;line-height:1.4}.big{color:var(--text);font-family:"PT Serif",Georgia,serif;font-size:36px;font-weight:400;line-height:1.2;letter-spacing:-.025em}.muted{color:var(--muted)}.good{color:var(--green)}.warn{color:var(--amber)}.notice{margin:0 0 16px;color:var(--muted);max-width:75ch;font-size:13px;line-height:1.6}.eyebrow{display:flex;align-items:center;gap:7px;margin:0 0 9px;color:var(--muted);font-size:11px;font-weight:750;letter-spacing:.06em;text-transform:uppercase}.eyebrow svg{width:16px;height:16px}.panel-heading{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:14px}.status-badge{display:inline-flex;min-height:32px;align-items:center;padding:5px 9px;border:1px solid var(--accent-border);background:var(--accent-soft);color:var(--accent);font-size:11px;font-weight:750;white-space:nowrap}
.rows{display:grid}.row{display:flex;justify-content:space-between;align-items:center;gap:16px;min-height:44px;padding:9px 0;border-bottom:1px solid var(--border);color:var(--text-secondary);font-size:13px}.row:last-child{border-bottom:0}.row span:last-child{color:var(--text);font-weight:650;text-align:right;overflow-wrap:anywhere}.state-card{background:var(--surface)}.state-card .big{font-size:48px}.activity-card{background:var(--accent-soft)}.activity-card #now-activity .muted{color:var(--text-secondary)}.motivation-details{margin-top:18px;border-top:1px solid var(--accent-border)}.motivation-details summary{display:flex;min-height:44px;align-items:center;gap:7px;color:var(--accent);cursor:pointer;font-size:13px;font-weight:750;list-style:none}.motivation-details summary::-webkit-details-marker{display:none}.motivation-details summary svg{width:16px;height:16px}.motivation-details[open] summary svg{transform:rotate(90deg)}
#emotion-levels{max-height:390px;margin-top:18px;padding-right:8px;overflow-y:auto;scrollbar-color:var(--accent-border) transparent;scrollbar-width:thin}.meter{height:7px;margin:7px 0 15px;overflow:hidden;border-radius:999px;background:var(--raised)}.meter>i{display:block;height:100%;border-radius:inherit;background:var(--emotion-color,var(--emotion-default));transition:width .2s ease-out}.cyber-theme .meter,.cyber-theme .meter>i{border-radius:0}.cyber-theme .meter>i{box-shadow:0 0 9px var(--emotion-color,var(--emotion-default))}
.list{display:grid}.entry{padding:16px 0;overflow-wrap:anywhere;border-bottom:1px solid var(--border);color:var(--text-secondary);font-size:14px}.entry:last-child{border-bottom:0}.entry time,.entry .meta{color:var(--muted);font-size:12px;line-height:1.5}.entry p{margin:7px 0 0;color:var(--text-secondary);white-space:pre-wrap;line-height:1.65}.empty{padding:18px 0;color:var(--muted);font-style:normal}pre{max-height:440px;margin:12px 0 0;padding:14px;overflow:auto;border:1px solid var(--border);background:var(--raised);color:var(--text-secondary);font:12px/1.65 "IBM Plex Mono",monospace;white-space:pre-wrap;overflow-wrap:anywhere}.pager{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:18px;flex-wrap:wrap}.pager button:disabled{opacity:.4}.graph-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 12px}.graph-toolbar .control-button{min-width:44px;padding:8px}.graph-toolbar #graph-reset{padding:8px 14px}.graph-zoom{min-width:58px;text-align:center;color:var(--accent);font:600 14px/1.4 "IBM Plex Mono",monospace}.graph-help{margin:12px 0 0;color:var(--muted);font-size:12px}.graph-stage{position:relative}#graph{display:block;width:100%;height:560px;border:1px solid var(--border);background:var(--raised);touch-action:none;user-select:none;cursor:grab}#graph:active{cursor:grabbing}.graph-label{fill:var(--text);font:12px/1.4 Manrope,sans-serif;paint-order:stroke;stroke:var(--raised);stroke-width:4px;stroke-linejoin:round;pointer-events:none}.graph-label.is-active{fill:var(--accent);font-weight:750}.graph-edge{stroke:var(--cyan);stroke-opacity:.25;stroke-width:.9;transition:opacity .16s ease-out,stroke .16s ease-out}.graph-node{cursor:pointer;transition:opacity .16s ease-out}.graph-node circle{stroke:var(--surface);stroke-width:1.2}.graph-node.is-dim{opacity:.12}.graph-edge.is-dim{opacity:.06}.graph-node.is-hot circle{stroke:var(--text);stroke-width:2}.graph-edge.is-hot{stroke:var(--accent);stroke-opacity:.95;stroke-width:2;opacity:1}.cyber-theme #graph{background-image:linear-gradient(rgb(66 232 255/.04) 1px,transparent 1px),linear-gradient(90deg,rgb(66 232 255/.04) 1px,transparent 1px);background-size:24px 24px}
.control-stack{display:grid;gap:14px}.controls{display:flex;gap:9px;flex-wrap:wrap}.control-line{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.control-line label,.control-stack>label{color:var(--text-secondary);font-size:13px;font-weight:700}.control-select,.control-input,textarea{min-height:44px;padding:10px 13px;border:1px solid var(--border);border-radius:11px;background:var(--control-bg);color:var(--text);font:14px/1.5 Manrope,sans-serif}.control-input{min-width:0;flex:1}.phrase{color:var(--amber);font:600 14px/1.5 "IBM Plex Mono",monospace;overflow-wrap:anywhere}.feedback{display:block;min-height:24px;margin:10px 0 0;color:var(--muted);font-size:13px;overflow-wrap:anywhere}.feedback.error{color:var(--danger)}.life-panel{margin-top:18px;padding:16px;border:1px solid var(--amber);background:var(--warning-soft)}.life-panel .control-button{margin-top:10px}textarea{width:100%;min-height:128px;line-height:1.6;resize:vertical}.access-action{min-width:112px}#proposal-list{display:grid;gap:12px;margin:0 0 20px}.proposal-card{padding:16px;border:1px solid var(--accent-border);background:var(--accent-soft)}.proposal-card h3{margin-bottom:6px}.proposal-card p{margin:6px 0;color:var(--text-secondary);font-size:13px;line-height:1.6;white-space:pre-wrap}.proposal-value{font:600 13px/1.6 "IBM Plex Mono",monospace;overflow-wrap:anywhere}.proposal-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:12px}.proposal-actions .reject{background:transparent;color:var(--danger);border-color:var(--danger)}#dialogue-feed{max-height:590px;margin:4px 0 20px;overflow:auto;scrollbar-color:var(--accent-border) transparent;scrollbar-width:thin}.dialogue-agent{border-left:2px solid var(--green);padding-left:14px}.dialogue-user{border-left:2px solid var(--cyan);padding-left:14px}.dialogue-thought{border-left:2px solid var(--lavender);padding-left:14px}.status-dot{display:inline-block;flex:0 0 7px;width:7px;height:7px;margin-right:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 3px var(--success-soft)}.page-footer{display:flex;flex-direction:column;gap:6px;margin-top:26px;padding:0 4px;color:var(--muted);font-size:11px;line-height:1.5}
#external-session-list{gap:9px}.external-session{width:100%;justify-content:flex-start;text-align:left}.external-session.active{border-color:var(--accent-border);background:var(--accent-soft);color:var(--accent)}#external-journal{max-height:590px;overflow:auto;scrollbar-color:var(--accent-border) transparent;scrollbar-width:thin}.external-inbound{border-left:2px solid var(--cyan);padding-left:14px}.external-outbound{border-left:2px solid var(--green);padding-left:14px}
.cyber-theme h1,.cyber-theme .card h2,.cyber-theme .big{font-family:"Russo One","Arial Black",sans-serif;font-weight:400;letter-spacing:.005em}.cyber-theme h1{color:var(--accent);font-size:clamp(30px,7vw,48px);line-height:1.18;text-shadow:3px 3px 0 rgb(66 232 255/.15);text-transform:uppercase}.cyber-theme .big{color:var(--accent)}.cyber-theme .breadcrumb,.cyber-theme .eyebrow{color:var(--cyan);font-family:"IBM Plex Mono",monospace}.cyber-theme .card,.cyber-theme .control-button,.cyber-theme .pager button,.cyber-theme .theme-toggle,.cyber-theme .demo-strip,.cyber-theme .mobile-nav summary,.cyber-theme .mobile-nav>nav{border-radius:0;clip-path:polygon(0 0,calc(100% - 11px) 0,100% 11px,100% 100%,11px 100%,0 calc(100% - 11px))}.cyber-theme .card{border-left:1px solid var(--accent)}.cyber-theme .activity-card{border-left-color:var(--cyan);background:#101a20}.cyber-theme .life-mark{border-color:var(--accent);border-radius:0;background:var(--accent);color:#090b0d;clip-path:polygon(0 0,75% 0,100% 25%,100% 100%,25% 100%,0 75%)}.cyber-theme .life-mark::after{border-color:rgb(9 11 13/.45);border-radius:0}.cyber-theme .sidebar{border-right-color:#394128;background:#0b0e12}.cyber-theme #nav button{border-radius:0;font-family:"IBM Plex Mono",monospace}.cyber-theme #nav button.active{background:var(--accent);color:#090b0d;clip-path:polygon(0 0,calc(100% - 9px) 0,100% 9px,100% 100%,0 100%)}.cyber-theme .status-dot,.cyber-theme #nav button.active::after{border-radius:0}.cyber-theme .control-select,.cyber-theme .control-input,.cyber-theme textarea,.cyber-theme pre{border-radius:0}.cyber-theme .page-footer{font-family:"IBM Plex Mono",monospace}
@media(min-width:640px){main{padding:24px 24px 32px}.topline{flex-direction:row;align-items:flex-end;justify-content:space-between}.card{padding:24px}.span-6{grid-column:span 6}.page-footer{flex-direction:row;justify-content:space-between;gap:20px}}
@media(min-width:900px){.span-4{grid-column:span 4}.span-8{grid-column:span 8}.control-line{flex-wrap:nowrap}.control-line .control-select{flex:1}}
@media(min-width:1100px){.app-shell{display:grid;grid-template-columns:224px minmax(0,1fr)}.sidebar{position:sticky;top:0;display:flex;height:100dvh;flex-direction:column;padding:26px 16px 20px;border-right:1px solid var(--border);background:var(--surface)}.sidebar .identity{padding:0 8px}.mobile-header{display:none}main{padding:30px 30px 34px}}
@media(min-width:1440px){.app-shell{grid-template-columns:240px minmax(0,1fr)}main{padding:36px 40px 38px}.grid{gap:22px}}
@media(max-width:639px){.demo-strip{flex-wrap:wrap}.demo-strip .badge{padding-left:25px}.graph-toolbar .control-button{flex:1 1 44px}.graph-toolbar #graph-reset{flex-basis:120px}.control-button{flex:1 1 132px}#access-list .row{align-items:flex-start;flex-direction:column;gap:10px}#access-list .access-action{width:100%}.life-panel .control-line{align-items:stretch;flex-direction:column}.life-panel .control-line .control-input{width:100%}#dialogue-send{flex-basis:100%}#graph{height:420px}.row{gap:12px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{animation:none!important;transition-duration:.01ms!important}.cyber-theme::before{display:none}}
</style>
</head>
<body class="cyber-theme">
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="i-now" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></symbol>
<symbol id="i-control" viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2" fill="currentColor"/><circle cx="15" cy="12" r="2" fill="currentColor"/><circle cx="8" cy="18" r="2" fill="currentColor"/></symbol>
<symbol id="i-diary" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 5.5v14A2.5 2.5 0 0 0 6.5 22H20"/></symbol>
<symbol id="i-activities" viewBox="0 0 24 24"><path d="m12 3 2.1 5.9L20 11l-5.9 2.1L12 19l-2.1-5.9L4 11l5.9-2.1z"/><path d="m19 3 .7 2.3L22 6l-2.3.7L19 9l-.7-2.3L16 6l2.3-.7z"/></symbol>
<symbol id="i-graph" viewBox="0 0 24 24"><circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><path d="m10.5 7.5-4 8M13.5 7.5l4 8M8 19h8"/></symbol>
<symbol id="i-access" viewBox="0 0 24 24"><circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M15 8l3 3M17 4l3 3"/></symbol>
<symbol id="i-dialogue" viewBox="0 0 24 24"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></symbol>
<symbol id="i-zap" viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></symbol>
<symbol id="i-chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>
<symbol id="i-arrow" viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></symbol>
</defs></svg>
<div class="app-shell">
<aside class="sidebar" aria-label="Основная навигация">
<div class="identity"><div class="life-mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12h5l3-8 4 16 3-8h5"/></svg></div><div><strong id="agent-name">Digital Being</strong><span>цифровая сущность</span></div></div>
<span class="brand-badge">ЭТАП 2 · СОБЫТИЯ ЯДРА</span>
<nav id="nav" aria-label="Страницы обсерватории">
<button data-page="now" class="active" aria-current="page"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-now"/></svg>Сейчас</button>
<button data-page="control"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-control"/></svg>Управление</button>
<button data-page="diary"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-diary"/></svg>Дневник</button>
<button data-page="activities"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-activities"/></svg>Занятия</button>
<button data-page="graph"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-graph"/></svg>Карта</button>
<button data-page="tutor"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-diary"/></svg>Наставник</button>
<button data-page="contacts"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-dialogue"/></svg>Контакты</button>
<button data-page="access"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-access"/></svg>Доступы</button>
<button data-page="dialogue"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-dialogue"/></svg>Диалог</button>
</nav>
<div class="sidebar-foot"><span class="status-dot" id="connection-dot"></span><div><strong id="sidebar-state">Проверяю соединение</strong><span>Локальный контур наблюдения</span></div></div>
</aside>
<main>
<header class="mobile-header"><div class="identity"><div class="life-mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12h5l3-8 4 16 3-8h5"/></svg></div><strong>Digital Being</strong></div>
<details class="mobile-nav" id="mobile-menu"><summary><span id="mobile-current">Сейчас</span><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-chevron"/></svg></summary><nav id="mobile-nav" aria-label="Мобильная навигация">
<button data-page="now" class="active" aria-current="page"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-now"/></svg>Сейчас</button>
<button data-page="control"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-control"/></svg>Управление</button>
<button data-page="diary"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-diary"/></svg>Дневник</button>
<button data-page="activities"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-activities"/></svg>Занятия</button>
<button data-page="graph"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-graph"/></svg>Карта</button>
<button data-page="tutor"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-diary"/></svg>Наставник</button>
<button data-page="contacts"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-dialogue"/></svg>Контакты</button>
<button data-page="access"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-access"/></svg>Доступы</button>
<button data-page="dialogue"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-dialogue"/></svg>Диалог</button>
</nav></details></header>
<div class="topline"><div><p class="breadcrumb">Обсерватория <svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-arrow"/></svg> <span id="current-page">Сейчас</span></p><h1 id="page-title">Спокойный фон</h1><p class="page-description" id="page-description">Сущность наблюдает, размышляет и выбирает следующий шаг.</p></div><div class="header-actions"><label for="language-select" class="muted">Язык</label><select id="language-select" class="control-select" aria-label="Язык интерфейса"><option value="ru">Русский</option><option value="en">English</option><option value="zh">中文</option></select><button id="theme-toggle" class="theme-toggle" type="button" aria-pressed="true"><svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-zap"/></svg><span id="theme-label">Светлая тема</span></button><span class="cycle" id="cycle">цикл —</span></div></div>
<div class="demo-strip" role="note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m12 3 2.1 5.9L20 11l-5.9 2.1L12 19l-2.1-5.9L4 11l5.9-2.1z"/></svg><span id="core-connection">Проверяю соединение с ядром…</span><span class="badge">СНИМКИ СОСТОЯНИЯ · СОБЫТИЯ ЯДРА</span></div>
<section id="page-now" class="page active" aria-label="Сейчас"><div class="grid">
<div class="card span-8 state-card"><p class="eyebrow">Состояние жизни</p><div class="big" id="life-state">—</div><div class="rows" id="life-rows"></div></div>
<div class="card span-4"><p class="eyebrow">Полная палитра</p><h2>Эмоции</h2><div class="big" id="emotion-dominant">фон</div><div id="emotion-levels"></div></div>
<div class="card span-8 activity-card"><p class="eyebrow">Текущее занятие</p><div id="now-activity"></div><details class="motivation-details"><summary>Объяснение выбора <svg fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-arrow"/></svg></summary><pre id="motivation">—</pre></details></div>
<div class="card span-4"><p class="eyebrow">Ресурсы</p><h2>Тело</h2><div class="big" id="fatigue">—</div><div class="rows" id="body-rows"></div></div>
<div class="card span-12"><p class="eyebrow">Последние шаги</p><h2>Намерения</h2><div id="intentions" class="list"></div></div>
</div></section>
<section id="page-control" class="page" aria-label="Управление"><div class="grid">
<div class="card span-6"><p class="eyebrow">Ритм и состояние</p><h2>Жизненный цикл</h2><p class="notice">Ответ интерфейса подтверждает только приём события. Фактический результат появляется в следующем снимке.</p><div class="control-stack"><div class="controls"><button id="pause-button" class="control-button needs-core" disabled>Пауза</button><button id="resume-button" class="control-button needs-core" disabled>Возобновить</button><button id="save-button" class="control-button needs-core" disabled>Сохранить</button></div><form id="speed-form" class="control-line"><label for="speed-mode">Темп жизни</label><select id="speed-mode" class="control-select needs-core" disabled><option value="live">Жизнь · 5 с</option><option value="fast">Ускорение · 0,5 с</option><option value="max">Лаборатория</option></select><button class="control-button needs-core" type="submit" disabled>Применить</button></form><div class="rows" id="control-facts"></div></div><p class="feedback" id="command-feedback" role="status"></p></div>
<div class="card span-6"><p class="eyebrow">Решения LifeGuard</p><h2>Сон и уход</h2><p class="notice">Создание запроса ничего не подтверждает. Точную фразу нужно ввести отдельно после паузы, заданной ядром.</p><div class="controls"><button id="dream-button" class="control-button needs-core" disabled>Запросить сон</button><button id="wake-button" class="control-button needs-core" disabled>Пробудить</button><button id="terminate-button" class="control-button danger needs-core" disabled>Запросить уход</button></div><div id="life-panel" class="life-panel" hidden><h3 id="life-title">Требуется подтверждение</h3><p id="life-description"></p><p>Запрос: <span id="life-request-id" class="muted"></span></p><p>Точная фраза: <span id="life-phrase" class="phrase"></span></p><form id="life-confirm-form" class="control-stack"><label for="life-confirm-input">Введите фразу вручную</label><div class="control-line"><input id="life-confirm-input" class="control-input" autocomplete="off" required maxlength="500"><button class="control-button" type="submit">Подтвердить</button></div></form><button id="life-cancel-button" class="control-button">Отменить запрос</button></div><p class="feedback" id="life-result" role="status"></p></div>
</div></section>
<section id="page-diary" class="page" aria-label="Дневник"><div class="card"><div class="panel-heading"><div><p class="eyebrow">Новые записи первыми</p><h2>Дневник эпизодов</h2></div><span class="status-badge">ТОЛЬКО ЧТЕНИЕ · КЭШ</span></div><p class="notice" id="diary-cache"></p><div id="diary-list" class="list"></div><div class="pager"><button id="diary-prev">← Новее</button><span id="diary-position" class="muted"></span><button id="diary-next">Старее →</button></div></div></section>
<section id="page-activities" class="page" aria-label="Занятия"><div class="grid" id="activity-cards"></div></section>
<section id="page-graph" class="page" aria-label="Карта"><div class="card"><div class="panel-heading"><div><p class="eyebrow">Связи внутренней жизни</p><h2>Карта жизни</h2></div><div class="graph-toolbar" aria-label="Управление видом карты"><button id="graph-zoom-out" class="control-button" type="button" aria-label="Уменьшить карту">−</button><span id="graph-zoom" class="graph-zoom" aria-live="polite">100%</span><button id="graph-zoom-in" class="control-button" type="button" aria-label="Приблизить карту">+</button><button id="graph-reset" class="control-button" type="button">Сброс вида</button></div></div><p class="notice" id="graph-note"></p><div class="graph-stage"><svg id="graph" role="img" aria-label="Карта связей жизни" tabindex="0"></svg></div><p class="graph-help">Колесо или щипок — масштаб · перетаскивание — панорама · наведение или тап — связи узла · тап по пустому месту — сброс подсветки</p></div></section>
<section id="page-tutor" class="page" aria-label="Наставник"><div class="grid">
<div class="card span-6"><p class="eyebrow">Обучение · разрешения человека</p><h2 id="tutor-heading">Языковой наставник</h2><label for="tutor-language">Язык наставника</label><select id="tutor-language" class="control-select" aria-label="Язык наставника"><option value="ru">Русский</option><option value="en">English</option></select><div class="rows" id="tutor-status"></div><form id="tutor-url-form" class="control-stack"><label for="tutor-url">Разрешённый HTTPS-источник</label><input id="tutor-url" class="control-input needs-core tutor-action" type="url" maxlength="600" required disabled placeholder="https://…"><div class="controls"><button class="control-button needs-core tutor-action" type="submit" disabled>Разрешить</button><button id="tutor-read" class="control-button needs-core tutor-action" type="button" disabled>Прочитать</button><button id="tutor-revoke" class="control-button needs-core tutor-action" type="button" disabled>Отозвать</button></div></form><p class="notice">Разрешение не означает загрузку. Чтение доступно только при включённом web-поиске.</p></div>
<div class="card span-6"><p class="eyebrow">Без эталона до попытки</p><h2>Самостоятельное упражнение</h2><div id="tutor-exercise" class="notice">Текущего задания нет.</div><div class="controls"><button id="tutor-exercise-button" class="control-button needs-core tutor-action" type="button" disabled>Получить задание</button><button id="tutor-solve" class="control-button needs-core tutor-action" type="button" disabled>Решить и сверить</button></div><p class="feedback" id="tutor-feedback" role="status"></p></div>
<div class="card span-12"><p class="eyebrow">Требуется решение человека</p><h2>Запросы сущности</h2><div id="tutor-requests" class="list" aria-live="polite"></div></div>
<div class="card span-12"><p class="eyebrow">Справка</p><h2>Как это работает</h2><p class="notice">До вашего подтверждения источник не загружается. Прочитанный текст остаётся неисполняемым карантином. Отзыв разрешения не удаляет офлайн-уроки. «Подтверждено источником» относится только к одному материалу, а не ко всей языковой норме.</p></div>
</div></section>
<section id="page-contacts" class="page" aria-label="Контакты"><div class="grid">
<div class="card span-12"><p class="eyebrow">Внешние собеседники · локальный журнал</p><h2>Внешние контакты</h2><div class="rows" id="external-status"></div><p class="notice" id="external-selection-note">Входящие реплики остаются карантином external_ai_claim. API-ключ не вводится в чат или журнал.</p></div>
<div class="card span-4"><p class="eyebrow">До 8 сессий</p><h2>Сессии</h2><div id="external-session-list" class="list" aria-live="polite"></div></div>
<div class="card span-8"><p class="eyebrow">Последние сообщения</p><h2>Журнал сессии</h2><div id="external-session-detail" class="notice"></div><div id="external-journal" class="list" aria-live="polite"></div></div>
<div class="card span-6"><p class="eyebrow">Ручной или разрешённый API-канал</p><h2>Новая сессия</h2><form id="external-start-form" class="control-stack"><label for="external-provider">Provider</label><input id="external-provider" class="control-input needs-core external-start-action" value="manual" maxlength="64" required disabled><label for="external-name">Имя собеседника</label><input id="external-name" class="control-input needs-core external-start-action" maxlength="120" required disabled placeholder="Например, RUFP"><label for="external-id">Внешний идентификатор</label><input id="external-id" class="control-input needs-core external-start-action" maxlength="128" disabled placeholder="Необязательно"><label for="external-topic">Тема</label><input id="external-topic" class="control-input needs-core external-start-action" maxlength="160" disabled placeholder="Внешний разговор"><label for="external-reason">Причина</label><input id="external-reason" class="control-input needs-core external-start-action" maxlength="240" disabled placeholder="Явный контакт владельца"><label for="external-model">Модель из каталога</label><input id="external-model" class="control-input needs-core external-start-action" maxlength="128" disabled placeholder="rufp/default для RUFP; пусто для manual"><button class="control-button needs-core external-start-action" type="submit" disabled>Создать сессию</button></form><p class="notice">Для RUFP доступна только rufp/default. Произвольный endpoint не принимается. Ключ читается из Windows Credential Manager или RUFP_API_KEY.</p></div>
<div class="card span-6"><p class="eyebrow">Только владелец</p><h2>Входящая реплика</h2><form id="external-ingest-form" class="control-stack"><label for="external-ingest-text">Текст внешнего собеседника</label><textarea id="external-ingest-text" class="needs-core external-session-action" maxlength="4000" required disabled placeholder="Вставьте реплику; она не будет исполнена"></textarea><div class="controls"><button class="control-button needs-core external-session-action" type="submit" disabled>Добавить в карантин</button><button id="external-draft" class="control-button needs-core external-session-action" type="button" disabled>Создать проект</button></div></form></div>
<div class="card span-12"><p class="eyebrow">Явный запуск · ограниченный бюджет</p><h2>Автономный обмен</h2><div class="rows" id="external-automation-status"></div><form id="external-auto-form" class="control-stack"><div class="control-line"><label for="external-max-replies">Реплик</label><input id="external-max-replies" class="control-input" type="number" min="1" max="8" value="3" required><label for="external-max-tokens">Токенов</label><input id="external-max-tokens" class="control-input" type="number" min="1" max="256000" value="1200" required><label for="external-interval">Интервал, с</label><input id="external-interval" class="control-input" type="number" min="1" max="60" step="0.5" value="2" required></div><div class="controls"><button id="external-auto" class="control-button needs-core" type="submit" disabled>Запустить обмен</button><button id="external-pause" class="control-button needs-core" type="button" disabled>Пауза</button><button id="external-resume" class="control-button needs-core" type="button" disabled>Продолжить</button><button id="external-manual" class="control-button needs-core" type="button" disabled>Взять ответ вручную</button></div></form><p class="notice">Сначала добавьте исходную реплику в карантин. Ошибка API ставит обмен на паузу. После restart обмен сам не возобновляется.</p></div>
<div class="card span-12"><p class="eyebrow">Наблюдение и вмешательство</p><h2>Проект ответа</h2><form id="external-edit-form" class="control-stack"><label for="external-edit-text">Точная редакция ответа</label><textarea id="external-edit-text" class="needs-core external-session-action" maxlength="4000" disabled placeholder="Активного проекта нет"></textarea><div class="controls"><button class="control-button needs-core external-session-action" type="submit" disabled>Сохранить изменения</button><button id="external-approve" class="control-button needs-core external-session-action" type="button" disabled>Одобрить</button><button id="external-reject" class="control-button needs-core external-session-action danger" type="button" disabled>Отклонить</button><button id="external-copy" class="control-button" type="button" disabled>Скопировать</button><button id="external-handoff" class="control-button needs-core external-session-action" type="button" disabled>Отметить ручную передачу</button><button id="external-stop" class="control-button needs-core external-session-action danger" type="button" disabled>Остановить сессию</button><button id="external-clear" class="control-button needs-core external-session-action danger" type="button" disabled>Удалить журнал</button></div></form><p class="notice">Изменение текста снимает одобрение. Ручная передача фиксируется отдельно и не означает сетевую доставку. Удаление журнала не удаляет профиль собеседника.</p><p class="feedback" id="external-feedback" role="status"></p></div>
<div class="card span-12"><p class="eyebrow">9D-0—9D-2 · карантин, sandbox и явные сессии</p><h2>Социальные каналы</h2><div class="rows" id="social-status"></div><p class="notice">Канал, аккаунт сущности, диалог и автор различаются. Входящие остаются external_social_claim. По умолчанию polling и ответы выключены; владелец может открыть ограниченную по времени private-сессию. Публичных постов, токенов и cookies в интерфейсе нет.</p></div>
<div class="card span-4"><p class="eyebrow">Все разрешения выключены по умолчанию</p><h2>Каналы</h2><div id="social-channel-list" class="list" aria-live="polite"></div></div>
<div class="card span-8"><p class="eyebrow">Карантин и фактические receipts</p><h2>Журнал канала</h2><div id="social-channel-detail" class="notice"></div><div id="social-journal" class="list" aria-live="polite"></div></div>
<div class="card span-6"><p class="eyebrow">Только владелец · без credentials</p><h2>Новый канал</h2><form id="social-create-form" class="control-stack"><label for="social-provider">Provider</label><input id="social-provider" class="control-input needs-core social-create-action" value="fake" maxlength="64" required disabled><label for="social-account">Account ID сущности</label><input id="social-account" class="control-input needs-core social-create-action" maxlength="128" required disabled><label for="social-author-kind">Тип авторов</label><select id="social-author-kind" class="control-select needs-core social-create-action" disabled><option value="external_person">Внешний автор</option><option value="external_ai">Внешний ИИ</option></select><button class="control-button needs-core social-create-action" type="submit" disabled>Создать закрытый канал</button></form><p class="notice">Для Telegram укажите числовой ID бота. Token заранее сохраняется вне Web как DigitalBeing/telegram в Windows Credential Manager или TELEGRAM_API_KEY; в чат и журнал он не вводится.</p></div>
<div class="card span-6"><p class="eyebrow">Receive ≠ draft ≠ reply</p><h2>Grant выбранного канала</h2><form id="social-grant-form" class="control-stack"><label for="social-scopes">Разрешённые conversation ID — по одному на строку</label><textarea id="social-scopes" class="needs-core social-grant-action" maxlength="5200" disabled></textarea><label><input id="social-receive" class="social-grant-action" type="checkbox" disabled> Принимать в карантин</label><label><input id="social-draft" class="social-grant-action" type="checkbox" disabled> Разрешить локальный проект</label><label><input id="social-reply" class="social-grant-action" type="checkbox" disabled> Разрешить owner-approved reply</label><div class="control-line"><label for="social-max-messages">Сообщений</label><input id="social-max-messages" class="control-input social-grant-action" type="number" min="0" max="64" value="0" required disabled><label for="social-max-replies">Ответов</label><input id="social-max-replies" class="control-input social-grant-action" type="number" min="0" max="64" value="0" required disabled><label for="social-interval">Интервал, с</label><input id="social-interval" class="control-input social-grant-action" type="number" min="0" max="3600" step="0.5" value="0" required disabled></div><div class="controls"><button class="control-button needs-core social-grant-action" type="submit" disabled>Сохранить новую версию</button><button id="social-revoke" class="control-button needs-core social-grant-action danger" type="button" disabled>Отозвать grant</button><button id="social-stop" class="control-button needs-core social-grant-action danger" type="button" disabled>Остановить канал</button></div></form><p class="notice">Изменение grant снимает прежние одобрения. Revoke/stop отбрасывает ожидающие проекты и не отправляет их.</p></div>
<div class="card span-12"><p class="eyebrow">9D-2 · один private-диалог · ограничение по времени</p><h2>Социальная сессия с инициативой</h2><div class="rows" id="social-session-status"></div><form id="social-session-form" class="control-stack"><label for="social-session-conversation">Conversation ID из grant</label><input id="social-session-conversation" class="control-input social-session-config" maxlength="160" required disabled><div class="control-line"><label for="social-session-duration">Длительность, с</label><input id="social-session-duration" class="control-input social-session-config" type="number" min="1" max="3600" step="1" value="1800" required disabled><label for="social-session-poll">Poll, с</label><input id="social-session-poll" class="control-input social-session-config" type="number" min="0.01" max="60" step="0.01" value="5" required disabled><label for="social-session-initiative">Инициатива после тишины, с</label><input id="social-session-initiative" class="control-input social-session-config" type="number" min="1" max="900" step="1" value="60" required disabled></div><div class="controls"><button id="social-session-start" class="control-button needs-core" type="submit" disabled>Открыть сессию</button><button id="social-session-pause" class="control-button needs-core" type="button" disabled>Пауза</button><button id="social-session-resume" class="control-button needs-core" type="button" disabled>Продолжить</button><button id="social-session-manual" class="control-button needs-core" type="button" disabled>Взять управление</button><button id="social-session-stop" class="control-button needs-core danger" type="button" disabled>Завершить сессию</button></div></form><p class="notice">Внутри сессии сущность может отвечать и однажды продолжить реальный предыдущий private-разговор после тишины. Лимита реплик сессии нет; deadline, опасная реплика, ошибка или изменение grant останавливают автономную работу. Restart ничего не возобновляет.</p></div>
<div class="card span-12"><p class="eyebrow">9D-1 · только ручные действия владельца</p><h2>Проект социального ответа</h2><form id="social-edit-form" class="control-stack"><label for="social-edit-text">Точная редакция</label><textarea id="social-edit-text" class="needs-core social-draft-action" maxlength="4000" disabled placeholder="Активного проекта нет"></textarea><div class="controls"><button id="social-receive-once" class="control-button needs-core" type="button" disabled>Принять один раз</button><button id="social-draft-create" class="control-button needs-core social-draft-action" type="button" disabled>Проект к последней реплике</button><button class="control-button needs-core social-draft-action" type="submit" disabled>Сохранить изменения</button><button id="social-approve" class="control-button needs-core social-draft-action" type="button" disabled>Одобрить</button><button id="social-reject" class="control-button needs-core social-draft-action danger" type="button" disabled>Отклонить</button><button id="social-send-approved" class="control-button needs-core" type="button" disabled>Отправить одобренное</button></div></form><p class="notice">Receive выполняет один bounded getUpdates без worker. Send доступен только для Telegram и конкретной одобренной ревизии. Новая реплика, edit, изменение grant и restart инвалидируют прежнее одобрение.</p><p class="feedback" id="social-feedback" role="status"></p></div>
</div></section>
<section id="page-access" class="page" aria-label="Доступы"><div class="grid"><div class="card span-6"><p class="eyebrow">Границы возможностей</p><h2>Разрешения · фактическое состояние</h2><div id="access-list" class="rows"></div><p class="notice">Кнопка отправляет существующую команду доступа. Индикация изменится только после фактического снимка.</p><p class="feedback" id="access-feedback" role="status"></p></div><div class="card span-6"><p class="eyebrow">Исполнение команд</p><h2>Действия</h2><div id="effector-list" class="rows"></div></div></div></section>
<section id="page-dialogue" class="page" aria-label="Диалог"><div class="card"><div class="panel-heading"><div><p class="eyebrow">Живой поток</p><h2><span class="status-dot"></span>Диалог</h2></div><span class="status-badge">SSE · ПОРЯДОК</span></div><p class="notice">Сообщение уходит через событие пользователя. Лента пополняется только событием шины; после переподключения продолжается с последнего номера.</p><div id="proposal-list" aria-live="polite"></div><div id="dialogue-feed" class="list" aria-live="polite"></div><form id="dialogue-form" class="control-stack"><label for="dialogue-input">Сообщение сущности</label><textarea id="dialogue-input" class="needs-core" maxlength="8000" required disabled placeholder="Ядро не подключено"></textarea><div class="control-line"><button id="voice-record" class="control-button" type="button" disabled>🎤 Удерживать</button><span id="voice-status" class="feedback" role="status">Голос выключен</span><button id="voice-replay" class="control-button" type="button" disabled>🔊 Озвучить ответ</button><label><input id="voice-auto" type="checkbox" disabled> Автоозвучивание</label><span id="voice-output-status" class="feedback" role="status">Звуковой TTS недоступен</span><button id="dialogue-send" class="control-button needs-core" type="submit" disabled>Отправить</button><span id="dialogue-feedback" class="feedback" role="status"></span></div></form></div></section>
<footer class="page-footer"><span>Digital Being · обсерватория</span><span>Данные приходят из снимков состояния; изменения — только через разрешённые события</span></footer>
</main></div>
<script>
'use strict';
const $=id=>document.getElementById(id);let diaryOffset=0,diaryLimit=20,lastSequence=0,eventSource=null,latestControl=null,renderedRequestId=null,latestTutorSections={ru:{},en:{}},selectedTutorLanguage='ru',latestTutorAvailable=false,latestExternalSection={},selectedExternalSessionId=null,latestSocialSection={},selectedSocialChannelId=null;
const LABELS={fear:'Страх',joy:'Радость',sadness:'Грусть',calm:'Спокойствие',anger:'Гнев',disgust:'Отвращение',surprise:'Удивление',interest:'Интерес',anticipation:'Предвкушение',trust:'Доверие',love:'Любовь',attachment:'Привязанность',tenderness:'Нежность',pride:'Гордость',gratitude:'Благодарность',hope:'Надежда',inspiration:'Вдохновение',relief:'Облегчение',satisfaction:'Удовлетворение',curiosity:'Любопытство',admiration:'Восхищение',amusement:'Веселье',serenity:'Умиротворение',contentment:'Довольство',enthusiasm:'Энтузиазм',awe:'Трепет',compassion:'Сострадание',empathy:'Сопереживание',anxiety:'Тревога',shame:'Стыд',guilt:'Вина',embarrassment:'Смущение',jealousy:'Ревность',envy:'Зависть',loneliness:'Одиночество',contempt:'Презрение',disappointment:'Разочарование',frustration:'Фрустрация',resentment:'Обида',regret:'Сожаление',longing:'Тоска',despair:'Отчаяние',boredom:'Скука',confusion:'Растерянность',grief:'Горе',anguish:'Мука',irritation:'Раздражение',hostility:'Враждебность',nervousness:'Нервозность',vulnerability:'Уязвимость',helplessness:'Беспомощность',overwhelm:'Перегрузка',worry:'Беспокойство',nostalgia:'Ностальгия',network:'Интернет-поиск',delamain:'Планирование задач',effector:'Выполнение действий',presence:'Присутствие',normal:'обычное состояние',started:'начато',denied:'отклонено',error:'ошибка',interrupted:'прервано',unobserved:'исход не наблюдался',live:'жизнь',fast:'ускорение',max:'лаборатория',step:'пошагово',alive:'жив',dormant:'сон',dead:'завершена',terminated:'завершена',fresh:'Бодрость',tired:'Усталость',exhausted:'Истощение',performed:'выполнено',completed:'завершено',failed:'ошибка',cancelled:'отменено',pending:'ожидает',active:'активно',reflect:'размышление',self_reflect:'размышление о себе',set_own_goal:'собственная цель',send_message:'сообщение',ask_question:'вопрос',ask_user:'вопрос пользователю',user_answer:'ответ пользователю',web_search:'поиск в интернете',search_web:'поиск в интернете',process_stimulus:'обработка впечатления',deep_rest:'глубокий отдых',let_go:'завершение намерения',hypothesis:'предположение',synthesize_understanding:'сбор понимания',synthesize:'соединение знаний',act:'действие',make_choice:'выбор',propose_alternative:'предложение альтернативы',teach_other:'передача знания',creative_act:'творчество',draw:'рисование',compose_music:'сочинение музыки',repair:'исправление',organize_knowledge:'упорядочивание знаний',play:'игра',create_draft:'творческий черновик',write_creative_draft:'творческий черновик',explore:'исследование',communicate:'общение',wait:'ожидание',learn:'обучение',create:'создание',competence:'мастерство',autonomy:'автономия',connection:'связь',meaning:'смысл',coherence:'внутренняя согласованность',creativity:'творчество',mastery:'совершенствование',self_transcendence:'саморазвитие',exploration:'исследование',understanding:'понимание',active_inference:'активный выбор',legacy_active_inference:'прежний механизм выбора',external_attention:'внешнее внимание',embodiment:'состояние тела',self_fading:'затухание намерения',deliberate_pause:'осознанная пауза',fallback_first_candidate:'первый доступный вариант',social:'общение',motivation:'мотивация',intrinsic:'внутренняя мотивация',need:'потребность',drive:'влечение',own_activity:'собственное занятие',active_goal:'активная цель',intention_continuation:'продолжение намерения',new_interest:'новый интерес',core_history:'история ядра',rest:'отдых',sleep:'сон',dream:'сон',wake:'пробуждение',terminate:'уход',user:'пользователь',agent:'сущность',thought:'мысль',question:'вопрос',user_command:'команда пользователя',life_request:'запрос LifeGuard',life_prompt:'запрос подтверждения',life_result:'результат LifeGuard',save_requested:'сохранение',speed_changed:'изменение темпа',pause_requested:'запрос паузы',resume_requested:'запрос возобновления'};
const FIELD_LABELS={count:'Количество',last:'Последнее',status:'Статус',correct:'Верно',action:'Действие',target:'Тема',cycle:'Цикл',goal:'Цель',source:'Источник',confirmed:'Подтверждено',queued:'В очереди',waiting_approval:'Ждёт подтверждения',succeeded:'Успешно',failed:'Ошибки',rejected:'Отклонено',last_error:'Последняя ошибка',most_pressing_need:'Самая настойчивая потребность',pressing_needs:'Настойчивые потребности',active_drives:'Активные влечения',new_goals:'Новые цели',last_generated_cycle:'Цикл последней генерации',needs_state:'Состояние потребностей'};
const I18N=__I18N_JSON__;
let language='ru',staticTextNodes=[],staticAttributes=[];
try{const saved=localStorage.getItem('digital-being-language');if(['ru','en','zh'].includes(saved))language=saved}catch(error){/* Выбор работает и без localStorage. */}
const value=v=>v===null||v===undefined||v===''?'—':String(v);
const t=v=>I18N.texts[language]?.[String(v)]||String(v);
function label(v){const raw=value(v),code=I18N.valueCodes[raw]||raw;return I18N.values[language]?.[code]||I18N.values.ru[code]||raw}
function field(v){const raw=String(v),code=I18N.fieldCodes[raw]||raw;return I18N.fields[language]?.[code]||I18N.fields.ru[code]||raw}
const number=v=>Number.isFinite(Number(v))?Number(v).toFixed(2):'—';
function formatJSON(input){const convert=item=>Array.isArray(item)?item.map(convert):item&&typeof item==='object'?Object.fromEntries(Object.entries(item).map(([key,item])=>[field(key),convert(item)])):typeof item==='string'?label(item):typeof item==='boolean'?t(item?'да':'нет'):item===null?'—':item;return JSON.stringify(convert(input),null,2)}
function localizeStaticDOM(){
 if(!staticTextNodes.length){const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let current;while((current=walker.nextNode())){if(current.parentElement.closest('script,style'))continue;const original=current.nodeValue.trim();if(original)staticTextNodes.push({node:current,raw:current.nodeValue,original})}for(const el of document.querySelectorAll('[aria-label],[placeholder],[title]'))for(const attr of ['aria-label','placeholder','title'])if(el.hasAttribute(attr))staticAttributes.push({el,attr,original:el.getAttribute(attr)})}
 for(const item of staticTextNodes)item.node.nodeValue=item.raw.replace(item.original,t(item.original));
 for(const item of staticAttributes)item.el.setAttribute(item.attr,t(item.original));
 document.documentElement.lang=language==='zh'?'zh-CN':language;document.title=`Digital Being — ${t('обсерватория')}`;
}
function applyLanguage(next,refresh=true){language=['ru','en','zh'].includes(next)?next:'ru';$('language-select').value=language;try{localStorage.setItem('digital-being-language',language)}catch(error){/* Настройка останется на время страницы. */}localizeStaticDOM();applyTheme(document.body.classList.contains('cyber-theme')?'cyber':'light');const active=document.querySelector('.page.active');activatePage(active?.id.slice(5)||'now');if(refresh){refreshNow();refreshControl();refreshDiary();graphRender()}}
function actionPhrase(action,target){const raw=String(action||''),phrase=I18N.actions[language]?.[raw]||I18N.actions.ru[raw]||label(raw);return target&&['create_draft','explore'].includes(raw)?`${phrase} «${target}»`:phrase}
function graphNodeLabel(n){const id=String(n.id||''),kind=String(n.kind||''),detail=n.detail||{};if(['activity','value'].includes(kind)&&id.startsWith(`${kind}:`))return label(id.slice(kind.length+1));if(['intention','forgotten'].includes(kind)&&detail['действие']){const phrase=actionPhrase(detail['действие'],detail['тема']);return detail['статус']==='started'?`${phrase} · ${t('сейчас')}`:phrase}return String(n.label||n.id)}
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el}
function rows(target,items){const el=$(target);el.replaceChildren();for(const [k,v] of items){const r=node('div','','row');r.append(node('span',t(k)),node('span',label(v)));el.append(r)}if(!items.length)el.append(node('div',t('Нет данных'),'empty'))}
async function getJSON(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(`${r.status} ${url}`);return r.json()}
async function postJSON(url,body={}){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(data.message||`${r.status}`);return data}
function feedback(id,text,error=false){const el=$(id);el.textContent=text||'';el.classList.toggle('error',error)}
async function sendCommand(url,body={},target='command-feedback'){try{const result=await postJSON(url,body);feedback(target,result.message);setTimeout(()=>{refreshControl();refreshNow()},250);return result}catch(e){feedback(target,e.message,true);return null}}
function renderAccess(access){const box=$('access-list');box.replaceChildren();for(const key of ['network','delamain','effector','presence']){const item=access[key];if(!item)continue;const accessLabel=label(item.label||key),row=node('div','','row'),text=node('span',`${accessLabel}: ${t(item.enabled?'включено':'выключено')}`),button=node('button',t(item.enabled?'Выключить':'Включить'),'control-button access-action');button.type='button';button.disabled=!latestControl?.bus_connected;button.setAttribute('aria-label',`${t(item.enabled?'Выключить':'Включить')} ${accessLabel}`);button.onclick=()=>sendCommand('/api/access',{key,state:item.enabled?'off':'on'},'access-feedback');row.append(text,button);box.append(row)}if(!box.children.length)box.append(node('div',t(latestControl?.bus_connected?'Нет данных':'Ядро не подключено'),'empty'))}
function renderProposals(section){const box=$('proposal-list');delete box.dataset.awaiting;box.replaceChildren();for(const item of section.pending||[]){if(!item?.id)continue;const card=node('article','','proposal-card');card.append(node('h3',item.title||t('Предложение сущности')));if(item.description)card.append(node('p',item.description));if(item.attr)card.append(node('p',`${item.attr}: ${value(item.old)} → ${value(item.new)}`,'proposal-value'));const verification=item.verification||{};card.append(node('p',t(verification.passed===true?'Проверка пройдена':'Проверка не пройдена'),verification.passed===true?'good':'warn'));if(item.type==='config_change')card.append(node('p',t('После одобрения сущность сама применит проверенное изменение.'),'muted'));const actions=node('div','','proposal-actions');for(const [decision,caption,cls] of [['одобри','Одобрить',''],['отклони','Отклонить','reject']]){const button=node('button',t(caption),`control-button proposal-action ${cls}`.trim());button.type='button';button.disabled=!latestControl?.bus_connected;button.onclick=async()=>{if(box.dataset.awaiting==='1')return;box.dataset.awaiting='1';box.querySelectorAll('button').forEach(el=>{el.disabled=true});const result=await sendCommand('/api/dialogue',{text:`${decision} ${item.id}`},'dialogue-feedback');if(!result){delete box.dataset.awaiting;box.querySelectorAll('button').forEach(el=>{el.disabled=!latestControl?.bus_connected})}};actions.append(button)}card.append(actions);box.append(card)}}
function renderTutorSelection(){const section=latestTutorSections[selectedTutorLanguage]||{},isEnglish=selectedTutorLanguage==='en';latestTutorAvailable=section.available===true;$('tutor-heading').textContent=isEnglish?'English language tutor':'Языковой наставник';document.querySelectorAll('.tutor-action').forEach(el=>{el.disabled=!latestControl?.bus_connected||!latestTutorAvailable});rows('tutor-status',[['Источники',section.approved_count??0],['Запросы сущности',section.request_count??0],['Материалы',section.materials??0],[isEnglish?'Наборы правил':'Уроки',isEnglish?section.rule_packs??0:section.lessons??0],['Подтверждено источником',section.source_verified??0],['Web для чтения',t(section.web_enabled?'включено':'выключено')]]);const current=section.pending_exercise;$('tutor-exercise').textContent=current?.prompt?`${t('Текущее задание')}: ${current.prompt} · ${label(current.kind)}. ${t('Эталон скрыт до самостоятельной попытки.')}`:t('Текущего задания нет. Получите его после чтения подходящего урока.');const box=$('tutor-requests');box.replaceChildren();for(const item of section.source_requests||[]){if(!item?.request_id)continue;const card=node('article','','proposal-card');card.append(node('h3',`${isEnglish?'EN':'RU'} · ${item.reason||t('Нужен учебный источник')}`),node('p',item.url||'','proposal-value'));const actions=node('div','','proposal-actions');for(const [action,caption] of [['approve_read','Разрешить и прочитать'],['approve','Только разрешить'],['reject','Отклонить']]){const button=node('button',t(caption),'control-button tutor-request-action');button.type='button';button.disabled=!latestControl?.bus_connected||!latestTutorAvailable;button.onclick=()=>sendCommand('/api/tutor',{action,request_id:item.request_id,language:selectedTutorLanguage},'tutor-feedback');actions.append(button)}card.append(actions);box.append(card)}if(!box.children.length)box.append(node('div',t('Запросов сущности пока нет.'),'empty'))}
function renderTutor(section){latestTutorSections.ru=section&&typeof section==='object'?section:{};renderTutorSelection()}
function renderEnglishTutor(section){latestTutorSections.en=section&&typeof section==='object'?section:{};renderTutorSelection()}
function externalStatus(status){const labels={quarantined:'Карантин',draft:'Проект',approved:'Одобрено',rejected:'Отклонено',handed_off:'Передано вручную',stopped:'Остановлено',sent:'Отправлено',send_failed:'Ошибка отправки',active:'Активна',idle:'Не запущен',running:'Работает',pausing:'Приостанавливается',paused:'Пауза',stopping:'Останавливается',manual:'Ручное управление',completed:'Лимит исчерпан'};return t(labels[status]||status||'—')}
function selectedExternalSession(){return (latestExternalSection.sessions||[]).find(item=>item.session_id===selectedExternalSessionId)||null}
function updateExternalControls(){const connected=latestControl?.bus_connected===true,can=connected&&latestExternalSection.available===true&&latestExternalSection.can_manage===true,session=selectedExternalSession(),automation=session?.automation||{state:'idle'},busy=['running','pausing','stopping'].includes(automation.state),sessionActive=can&&session?.status==='active',active=sessionActive&&!busy,pending=session?.pending_draft||null,hasInbound=!!session?.messages?.some(item=>item.direction==='inbound'),canAuto=sessionActive&&!busy&&!pending&&hasInbound&&session?.provider!=='manual'&&['idle','completed'].includes(automation.state);document.querySelectorAll('.external-start-action').forEach(el=>{el.disabled=!can});for(const id of ['external-max-replies','external-max-tokens','external-interval'])$(id).disabled=!can||busy;$('external-auto').disabled=!canAuto;$('external-pause').disabled=!sessionActive||automation.state!=='running';$('external-resume').disabled=!sessionActive||!['paused','manual'].includes(automation.state);$('external-manual').disabled=!sessionActive||!['running','pausing','paused'].includes(automation.state);$('external-ingest-text').disabled=!active||!!pending;$('external-ingest-form').querySelector('button[type="submit"]').disabled=!active||!!pending;$('external-edit-text').disabled=!active||!pending;$('external-edit-form').querySelector('button[type="submit"]').disabled=!active||!pending;$('external-draft').disabled=!active||!!pending||!hasInbound;$('external-approve').disabled=!active||pending?.status!=='draft';$('external-reject').disabled=!active||!pending;$('external-copy').disabled=!pending;$('external-handoff').disabled=!active||pending?.status!=='approved';$('external-stop').disabled=!sessionActive;$('external-clear').disabled=!can||!session||busy}
function renderExternal(section){latestExternalSection=section&&typeof section==='object'?section:{};const sessions=Array.isArray(latestExternalSection.sessions)?latestExternalSection.sessions:[];if(!sessions.some(item=>item.session_id===selectedExternalSessionId))selectedExternalSessionId=sessions[0]?.session_id||null;rows('external-status',[['Активные сессии',latestExternalSection.active??0],['Сообщения',latestExternalSection.messages??0],['Ожидают решения',latestExternalSection.pending_drafts??0],['Управление',latestExternalSection.can_manage? 'владелец':'только наблюдение']]);$('external-selection-note').textContent=latestExternalSection.can_manage?t('Входящие реплики остаются карантином external_ai_claim. API-ключ не вводится в чат или журнал.'):t('Управлять внешними сессиями может только владелец локального канала. Журнал доступен для наблюдения.');const list=$('external-session-list');list.replaceChildren();for(const item of sessions){const button=node('button',`${item.display_name||'Внешний ИИ'} · ${externalStatus(item.status)}`,'control-button external-session');button.type='button';button.classList.toggle('active',item.session_id===selectedExternalSessionId);button.setAttribute('aria-pressed',String(item.session_id===selectedExternalSessionId));button.onclick=()=>{selectedExternalSessionId=item.session_id;renderExternal(latestExternalSection)};list.append(button)}if(!sessions.length)list.append(node('div',t('Внешних сессий пока нет.'),'empty'));const session=selectedExternalSession(),detail=$('external-session-detail'),journal=$('external-journal');journal.replaceChildren();if(!session){detail.textContent=t('Выберите или создайте сессию.');rows('external-automation-status',[]);updateExternalControls();return}detail.textContent=`${session.display_name||'Внешний ИИ'} · ${session.provider||'—'} · ${session.model||t('ручной канал')} · ${session.topic||'—'} · ${t('сообщений')}: ${session.message_count??0}`;const automation=session.automation||{state:'idle'},metrics=session.metrics||{};rows('external-automation-status',[['Состояние',externalStatus(automation.state)],['Причина паузы',automation.pause_reason||'—'],['HTTP-запрос',t(automation.in_flight?'выполняется':'не выполняется')],['Реплики',`${automation.replies_sent??0} / ${automation.max_replies??0}`],['Учтённые токены',`${automation.tokens_used??0} / ${automation.max_total_tokens??0}`],['Интервал, с',automation.min_interval_sec??'—'],['Оценка токенов',t(automation.tokens_estimated?'да':'нет')],['Содержательные follow-up',metrics.substantive_follow_ups??0],['Generic fallback',metrics.generic_fallbacks??0],['Provenance',`${metrics.provenance_complete??0} / ${metrics.planned_responses??0}`],['Биллинг',formatJSON(automation.billing_receipts||[])],['Последняя ошибка',automation.last_error||'—']]);for(const message of session.messages||[]){const entry=node('article','',`entry external-${message.direction==='inbound'?'inbound':'outbound'}`),hash=message.text_sha256?` · SHA-256 ${String(message.text_sha256).slice(0,12)}…`:'';entry.append(node('div',`${externalStatus(message.status)} · ${t('цикл')} ${value(message.cycle)} · ${message.direction==='inbound'?'external_ai_claim':value(message.origin)}${hash}`,'meta'),node('p',message.text||''));if(message.error)entry.append(node('p',message.error,'warn'));journal.append(entry)}if(!session.messages?.length)journal.append(node('div',t('Сообщений в этой сессии пока нет.'),'empty'));const pending=session.pending_draft,edit=$('external-edit-text'),signature=pending?`${session.session_id}:${pending.message_id}:${pending.revision}`:'';if(document.activeElement!==edit&&edit.dataset.signature!==signature){edit.value=pending?.text||'';edit.dataset.signature=signature}updateExternalControls()}
function selectedSocialChannel(){return (latestSocialSection.channels||[]).find(item=>item.channel_id===selectedSocialChannelId)||null}
function updateSocialControls(){const connected=latestControl?.bus_connected===true,can=connected&&latestSocialSection.available===true&&latestSocialSection.can_manage===true,channel=selectedSocialChannel(),active=can&&channel?.status==='active',grant=channel?.grant||{},pending=channel?.pending_draft||null,hasInbound=!!channel?.messages?.some(item=>item.direction==='inbound'),telegram=channel?.provider==='telegram',session=channel?.session||{state:'idle'},busy=['running','pausing','stopping'].includes(session.state),manualActive=active&&!busy,configured=active&&telegram&&grant.receive===true&&grant.draft===true&&grant.reply===true&&(grant.conversation_ids||[]).length>0,canStart=configured&&['idle','completed','stopped'].includes(session.state);document.querySelectorAll('.social-create-action').forEach(el=>{el.disabled=!can});document.querySelectorAll('.social-grant-action').forEach(el=>{el.disabled=!active});document.querySelectorAll('.social-session-config').forEach(el=>{el.disabled=!canStart});$('social-session-start').disabled=!canStart;$('social-session-pause').disabled=!active||session.state!=='running';$('social-session-resume').disabled=!active||!['pausing','paused','manual'].includes(session.state);$('social-session-manual').disabled=!active||!['running','pausing','paused'].includes(session.state);$('social-session-stop').disabled=!active||['idle','completed','stopped'].includes(session.state);$('social-receive-once').disabled=!manualActive||!telegram||grant.receive!==true||!(grant.conversation_ids||[]).length;$('social-draft-create').disabled=!manualActive||grant.draft!==true||!hasInbound||!!pending;$('social-edit-text').disabled=!manualActive||!pending;$('social-edit-form').querySelector('button[type="submit"]').disabled=!manualActive||!pending;$('social-approve').disabled=!manualActive||pending?.status!=='draft'||grant.draft!==true;$('social-reject').disabled=!manualActive||!pending;$('social-send-approved').disabled=!manualActive||!telegram||grant.reply!==true||pending?.status!=='approved'}
function renderSocialChannels(section){latestSocialSection=section&&typeof section==='object'?section:{};const channels=Array.isArray(latestSocialSection.channels)?latestSocialSection.channels:[];if(!channels.some(item=>item.channel_id===selectedSocialChannelId))selectedSocialChannelId=channels[0]?.channel_id||null;rows('social-status',[['Каналы',latestSocialSection.channel_count??0],['Активные',latestSocialSection.active??0],['Открытые сессии',latestSocialSection.active_sessions??0],['Сообщения',latestSocialSection.messages??0],['Ожидают решения',latestSocialSection.pending_drafts??0],['Отправлено с receipt',latestSocialSection.sent??0],['Worker-ы',latestSocialSection.workers??0],['Автовозобновление',latestSocialSection.automatic_resume?'да':'нет'],['Управление',latestSocialSection.can_manage?'владелец':'только наблюдение']]);const list=$('social-channel-list');list.replaceChildren();for(const item of channels){const button=node('button',`${item.provider||'—'} · ${externalStatus(item.status)} · grant v${item.grant?.grant_version??'—'}`,'control-button external-session');button.type='button';button.classList.toggle('active',item.channel_id===selectedSocialChannelId);button.setAttribute('aria-pressed',String(item.channel_id===selectedSocialChannelId));button.onclick=()=>{selectedSocialChannelId=item.channel_id;renderSocialChannels(latestSocialSection)};list.append(button)}if(!channels.length)list.append(node('div',t('Социальных каналов пока нет.'),'empty'));const channel=selectedSocialChannel(),journal=$('social-journal');journal.replaceChildren();if(!channel){$('social-channel-detail').textContent=t('Выберите или создайте закрытый канал.');rows('social-session-status',[]);updateSocialControls();return}$('social-channel-detail').textContent=`${channel.provider||'—'} · ${channel.account_id||'—'} · ${externalStatus(channel.status)} · ${t('сообщений')}: ${channel.message_count??0}`;const session=channel.session||{state:'idle',automatic_resume:false},grant=channel.grant||{},deadline=session.deadline?new Date(session.deadline*1000).toLocaleString(language==='zh'?'zh-CN':language):'—';rows('social-session-status',[['Состояние',session.state==='completed'?t('Завершена'):externalStatus(session.state)],['Conversation ID',session.conversation_id||'—'],['Deadline',deadline],['Осталось, с',session.remaining_sec??0],['Принято',session.received??0],['Отправлено',session.sent??0],['Инициатив',session.initiatives_sent??0],['Adapter call',t(session.in_flight?'выполняется':'не выполняется')],['Причина паузы',session.pause_reason||session.last_error||'—'],['Автовозобновление',t('нет')]]);const conversation=$('social-session-conversation'),conversationSignature=`${channel.channel_id}:${session.session_id||'idle'}`;if(document.activeElement!==conversation&&conversation.dataset.signature!==conversationSignature){conversation.value=session.conversation_id||grant.conversation_ids?.[0]||'';conversation.dataset.signature=conversationSignature}for(const message of channel.messages||[]){const entry=node('article','',`entry external-${message.direction==='inbound'?'inbound':'outbound'}`),hash=message.text_sha256?` · SHA-256 ${String(message.text_sha256).slice(0,12)}…`:'';entry.append(node('div',`${externalStatus(message.status)} · ${t('цикл')} ${value(message.cycle)} · ${message.direction==='inbound'?'external_social_claim':value(message.origin)}${hash}`,'meta'),node('p',message.text||''));if(message.error)entry.append(node('p',message.error,'warn'));journal.append(entry)}if(!channel.messages?.length)journal.append(node('div',t('Сообщений в этом канале пока нет.'),'empty'));const form=$('social-grant-form');if(!form.contains(document.activeElement)){$('social-scopes').value=(grant.conversation_ids||[]).join('\n');for(const key of ['receive','draft','reply'])$(`social-${key}`).checked=grant[key]===true;$('social-max-messages').value=grant.max_messages??0;$('social-max-replies').value=grant.max_replies??0;$('social-interval').value=grant.min_interval_sec??0}const pending=channel.pending_draft,edit=$('social-edit-text'),signature=pending?`${channel.channel_id}:${pending.message_id}:${pending.revision}`:'';if(document.activeElement!==edit&&edit.dataset.signature!==signature){edit.value=pending?.text||'';edit.dataset.signature=signature}updateSocialControls()}
async function refreshNow(){try{const [status,life]=await Promise.all([getJSON('/api/status'),getJSON('/api/life')]);const p=status.panel||{};$('agent-name').textContent=life.name||p.name||'Digital Being';$('cycle').textContent=`${t('цикл')} ${life.life?.cycle??p.cycle??'—'}`;$('life-state').textContent=label(life.life?.state||life.life?.state_label||'—');rows('life-rows',[['Энергия',`${number(life.life?.energy)} / ${number(p.max_energy)}`],['Режим',life.life?.speed_mode],['Пауза',t(life.life?.paused?'да':'нет')],['Семя',life.life?.seed_folder],['RSS, МБ',number(p.rss_mb)]]);
const emotions=life.emotions||{},levels=emotions.levels||{};$('emotion-dominant').textContent=label(emotions.dominant?.emotion||emotions.dominant?.label||'calm');const box=$('emotion-levels');box.replaceChildren();for(const [name,raw] of Object.entries(levels)){const emotionLabel=node('div',`${label(name)} · ${number(raw)}`,'muted');const meter=node('div','','meter'),bar=node('i');bar.style.width=`${Math.max(0,Math.min(1,Number(raw)||0))*100}%`;bar.style.setProperty('--emotion-color',({joy:'var(--emotion-joy)',sadness:'var(--emotion-sadness)',fear:'var(--emotion-fear)',calm:'var(--emotion-calm)'}[name]||'var(--emotion-default)'));meter.append(bar);box.append(emotionLabel,meter)}if(!Object.keys(levels).length)box.append(node('div',t('Нет данных'),'empty'));
const body=life.body||{};$('fatigue').textContent=label(body.fatigue_level||'—');rows('body-rows',[['Усталость',number(body.fatigue)],['АТФ',number(body.atp)],['АТФ, доля',number(body.atp_ratio)],['Глюкоза',number(body.glucose)],['Митохондрии',number(body.mitochondrial_health)],['Нужен отдых',t(body.needs_rest?'да':'нет')]]);const activity=life.now?.activity;$('now-activity').replaceChildren(node('h3',activity?`${label(activity.action)} · ${label(activity.target)}`:t('Свободный цикл')),node('div',activity?label(activity.reason||activity.source):t('Нет активного намерения'),'muted'));$('motivation').textContent=formatJSON(life.motivation||{});const intents=$('intentions');intents.replaceChildren();for(const item of (life.intentions?.recent||[]).slice(-8).reverse()){const e=node('div','','entry');e.append(node('div',`${label(item.action)} · ${label(item.target)}`),node('div',`${label(item.status)} · ${t('цикл')} ${value(item.cycle)}`,'meta'));intents.append(e)}if(!intents.children.length)intents.append(node('div',t('Пока нет записанных намерений'),'empty'));
renderAccess(life.access||{});renderProposals(life.proposals||{});renderTutor(life.tutor||{});renderEnglishTutor(life.english_tutor||{});renderExternal(life.external_contacts||{});renderSocialChannels(life.social_channels||{});const effectorRows=[...Object.entries(life.effector?.counts||{}).map(([key,item])=>[field(key),item]),['Последняя ошибка',life.effector?.last_error]];if(life.access?.workspace)effectorRows.unshift(['Рабочая область',life.access.workspace.path]);rows('effector-list',effectorRows);renderActivities(life.activities||{});}catch(e){console.warn(e)}}
function renderActivities(a){const box=$('activity-cards');box.replaceChildren();for(const [key,title] of [['creative','Тексты'],['art','Рисунки'],['music','Музыка'],['game','Игра'],['guess_game','Угадывание']]){const card=node('div','','card span-6');card.append(node('h2',t(title)));const item=a[key];if(item&&typeof item==='object'&&!Array.isArray(item)){const count=item.count??((key==='game'||key==='guess_game')?t('активна'):'—');card.append(node('div',label(count),'big'));const pre=node('pre',formatJSON(item));card.append(pre)}else card.append(node('div',label(item),'muted'));box.append(card)}if(!box.children.length)box.append(node('div',t('Нет данных'),'empty'))}
async function refreshControl(){try{const c=await getJSON('/api/control');latestControl=c;document.querySelectorAll('.needs-core').forEach(el=>{el.disabled=!c.bus_connected});document.querySelectorAll('.proposal-action').forEach(el=>{el.disabled=!c.bus_connected||$('proposal-list').dataset.awaiting==='1'});document.querySelectorAll('.tutor-action,.tutor-request-action').forEach(el=>{el.disabled=!c.bus_connected||!latestTutorAvailable});$('core-connection').textContent=t(c.bus_connected?'Ядро подключено. Команды идут через шину событий; ответ здесь означает только приём события.':'Ядро не подключено. Это автономный предпросмотр: команды отключены.');$('core-connection').classList.toggle('connection-off',!c.bus_connected);$('sidebar-state').textContent=t(c.bus_connected?'Ядро подключено':'Ядро не подключено');$('connection-dot').style.background=c.bus_connected?'var(--green)':'var(--amber)';$('dialogue-input').placeholder=t(c.bus_connected?'Напишите сообщение…':'Ядро не подключено');$('pause-button').disabled=!c.bus_connected||c.paused!==false;$('resume-button').disabled=!c.bus_connected||c.paused!==true;$('dream-button').disabled=!c.bus_connected||c.life_state!=='alive';$('terminate-button').disabled=!c.bus_connected||c.life_state!=='alive';$('wake-button').disabled=!c.bus_connected||c.life_state!=='dormant';if(c.speed_mode&&document.activeElement!==$('speed-mode'))$('speed-mode').value=c.speed_mode;const save=c.last_save_at?new Date(c.last_save_at*1000).toLocaleTimeString(language==='zh'?'zh-CN':language):'—';rows('control-facts',[['Фактическая пауза',c.paused===null||c.paused===undefined?'—':t(c.paused?'да':'нет')],['Фактический темп',c.speed_mode],['Состояние жизни',c.life_state],['Последнее сохранение',c.last_save_ok===null||c.last_save_ok===undefined?t('ещё не было'):`${save} · ${t(c.last_save_ok?'успешно':'ошибка')}`]]);const prompt=c.life_prompt;$('life-panel').hidden=!prompt;if(prompt){if(renderedRequestId!==prompt.request_id){$('life-confirm-input').value='';renderedRequestId=prompt.request_id}$('life-title').textContent=t(prompt.kind==='terminate'?'Подтверждение необратимого ухода':'Подтверждение сна');$('life-description').textContent=prompt.description||t('Ядро ожидает явное подтверждение.');$('life-request-id').textContent=prompt.request_id;$('life-phrase').textContent=prompt.phrase||'—'}else renderedRequestId=null;const result=c.life_result;$('life-result').textContent=result?`${t(result.ok?'Результат: успешно':'Результат: отклонено')} · ${result.message||''}`:'';$('life-result').classList.toggle('error',!!result&&!result.ok);renderAccess(c.access||{});updateExternalControls();updateSocialControls();updateVoiceOutputControls()}catch(e){feedback('command-feedback',e.message,true)}}
async function refreshDiary(){try{const d=await getJSON(`/api/diary?offset=${diaryOffset}&limit=${diaryLimit}`),list=$('diary-list');list.replaceChildren();for(const item of d.episodes){const e=node('div','','entry');e.append(node('time',`${t('цикл')} ${value(item.ts)} · ${label(item.action)} · ${t(item.ok?'завершено':'не завершено')}`));const args=item.args?.target?` · ${label(item.args.target)}`:'';e.append(node('p',`${value(item.task)}${args}`));if(item.error)e.append(node('div',String(item.error),'warn'));list.append(e)}if(!d.episodes.length)list.append(node('div',t('Записей в этом окне нет'),'empty'));$('diary-cache').textContent=t('В кэше только для чтения: {stored} из максимум {limit}. Более старые записи могут существовать вне кэша.').replace('{stored}',d.stored).replace('{limit}',d.cache_limit);$('diary-position').textContent=`${d.returned?d.offset+1:0}–${d.offset+d.returned} / ${d.stored}`;$('diary-prev').disabled=d.offset===0;$('diary-next').disabled=!d.has_more}catch(e){console.warn(e)}}
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
function graphLabelText(n){const limit=graphSize.w<500?(graphZoom>=1.9?18:12):(graphZoom>=1.9?34:24),text=graphNodeLabel(n);return text.length<=limit?text:text.slice(0,limit-1)+'…'}
function graphLabelThreshold(){if(graphZoom<.7)return .92;if(graphZoom<1.15)return .68;if(graphZoom<1.75)return .45;if(graphZoom<2.5)return .28;return 0}
function graphBoxesOverlap(a,b,padding=3){return !(a[2]+padding<b[0]||b[2]+padding<a[0]||a[3]+padding<b[1]||b[3]+padding<a[1])}
function graphRenderLabels(){
 const layer=$('graph-labels');if(!layer)return;layer.replaceChildren();
 const active=graphHovered||graphSelected,neighbors=new Set(),threshold=graphLabelThreshold(),{w,h}=graphSize,cx=w/2,cy=h/2;
 if(active)for(const e of graphData.edges||[]){if(e.source===active)neighbors.add(e.target);if(e.target===active)neighbors.add(e.source)}
 const centers=(graphData.nodes||[]).map(n=>{const p=graphPositions[n.id];return p?[p[0],p[1],graphRadius(n),n.id]:null}).filter(Boolean);
 const candidates=(graphData.nodes||[]).filter(n=>n.id===active||(active&&neighbors.has(n.id)&&(Number(n.weight)||0)>=.15)||(Number(n.weight)||0)>=threshold);
 candidates.sort((a,b)=>(a.id===active?-1:b.id===active?1:0)||(Number(b.weight)||0)-(Number(a.weight)||0)||String(a.id).localeCompare(String(b.id)));
 graphMeasure.font='12px Manrope, sans-serif';
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
 $('graph-note').textContent=t('Узлов: {nodes}; связей: {edges}; подписей: {labels}; скрыто сверх лимита: {omitted}').replace('{nodes}',(graphData.nodes||[]).length).replace('{edges}',(graphData.edges||[]).length).replace('{labels}',layer.children.length).replace('{omitted}',graphData.omitted||0);
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
 for(const n of graphData.nodes||[]){const position=graphPositions[n.id];if(!position)continue;const [x,y]=position,group=document.createElementNS(GRAPH_NS,'g'),circle=document.createElementNS(GRAPH_NS,'circle'),title=document.createElementNS(GRAPH_NS,'title');group.setAttribute('class','graph-node');group.dataset.id=n.id;circle.setAttribute('cx',x);circle.setAttribute('cy',y);circle.setAttribute('r',String(graphRadius(n)));circle.setAttribute('fill',graphColor(n));title.textContent=graphNodeLabel(n);group.append(circle,title);nodes.append(group)}
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
function addDialogue(item){if(!item||item.sequence<=lastSequence)return;if(item.sequence>lastSequence+1){startDialogue();return}lastSequence=item.sequence;if(item.kind==='life_prompt'||item.kind==='life_result'){refreshControl();return}if(item.kind==='agent'&&String(item.text||'').trim()){latestVoiceResponseSequence=item.sequence;updateVoiceOutputControls()}const e=node('div','',`entry dialogue-${item.kind==='user'?'user':item.kind==='thought'?'thought':'agent'}`);e.append(node('time',`${item.time||''} · #${item.sequence} · ${label(item.kind)}`),node('p',item.text||formatJSON(item.data||{})));$('dialogue-feed').prepend(e);while($('dialogue-feed').children.length>100)$('dialogue-feed').lastChild.remove()}
async function startDialogue(){try{if(eventSource){eventSource.close();eventSource=null}const d=await getJSON('/api/dialogue?limit=50');$('dialogue-feed').replaceChildren();latestVoiceResponseSequence=null;lastSequence=d.events.length?d.events[0].sequence-1:0;for(const item of d.events)addDialogue(item);connectDialogue()}catch(e){setTimeout(startDialogue,3000)}}
function connectDialogue(){if(eventSource)eventSource.close();eventSource=new EventSource(`/stream/dialogue?after=${lastSequence}`);eventSource.onmessage=e=>{try{addDialogue(JSON.parse(e.data))}catch(err){console.warn(err)}};eventSource.onerror=()=>{/* EventSource reconnects with Last-Event-ID; sequence also deduplicates. */}}
const PAGE_COPY={
 now:['Сейчас','Спокойный фон','Сущность наблюдает, размышляет и выбирает следующий шаг.'],
 control:['Управление','Ритм под контролем','Пауза, темп, сохранения и защищённые решения — через существующие события ядра.'],
 diary:['Дневник','След прожитого','Эпизоды, решения и результаты — от новых записей к более ранним, без приукрашивания исходов.'],
 activities:['Занятия','Интерес становится делом','Творчество, игры и исследования с фактическими результатами из текущего снимка.'],
 graph:['Карта','Связи внутренней жизни','Понятия, эмоции и намерения образуют живую сеть влияний и последствий.'],
 tutor:['Наставник','Учиться через проверяемый опыт','Источник появляется только после разрешения; запрос сущности требует отдельного решения человека.'],
 contacts:['Контакты','Внешний разговор под наблюдением','Карантин, проекты и решения владельца видны в локальном журнале без выдуманной сетевой доставки.'],
 access:['Доступы','Границы возможностей','Разрешения видимы отдельно от действий; индикация меняется только после фактического снимка.'],
 dialogue:['Диалог','Разговор с сущностью','Реплики и рефлексия приходят через живой поток событий с восстановлением после переподключения.']};
function activatePage(key){const copy=(PAGE_COPY[key]||PAGE_COPY.now).map(t);document.querySelectorAll('[data-page]').forEach(button=>{const active=button.dataset.page===key;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current')});document.querySelectorAll('.page').forEach(page=>page.classList.toggle('active',page.id===`page-${key}`));$('current-page').textContent=copy[0];$('mobile-current').textContent=copy[0];$('page-title').textContent=copy[1];$('page-description').textContent=copy[2];$('mobile-menu').open=false;window.scrollTo({top:0,behavior:'auto'});if(key==='diary')refreshDiary();if(key==='graph')refreshGraph();if(key==='control')refreshControl()}
document.addEventListener('click',event=>{const button=event.target.closest('button[data-page]');if(button)activatePage(button.dataset.page)});
$('diary-prev').onclick=()=>{diaryOffset=Math.max(0,diaryOffset-diaryLimit);refreshDiary()};$('diary-next').onclick=()=>{diaryOffset+=diaryLimit;refreshDiary()};
$('pause-button').onclick=()=>sendCommand('/api/control/pause');$('resume-button').onclick=()=>sendCommand('/api/control/resume');$('save-button').onclick=()=>sendCommand('/api/control/save');$('dream-button').onclick=()=>sendCommand('/api/control/life/request',{kind:'dream',reason:'запрос из окна'},'life-result');$('terminate-button').onclick=()=>sendCommand('/api/control/life/request',{kind:'terminate',reason:'запрос из окна'},'life-result');$('wake-button').onclick=()=>sendCommand('/api/control/life/wake',{},'life-result');
$('speed-form').onsubmit=e=>{e.preventDefault();sendCommand('/api/control/speed',{mode:$('speed-mode').value})};
function tutorURLCommand(action){const url=$('tutor-url').value.trim();if(!url){feedback('tutor-feedback',t('Укажите HTTPS-источник'),true);return}sendCommand('/api/tutor',{action,url,language:selectedTutorLanguage},'tutor-feedback')}
$('tutor-language').onchange=event=>{selectedTutorLanguage=['ru','en'].includes(event.target.value)?event.target.value:'ru';$('tutor-language').value=selectedTutorLanguage;renderTutorSelection();refreshControl()};
$('tutor-url-form').onsubmit=e=>{e.preventDefault();tutorURLCommand('allow')};$('tutor-read').onclick=()=>tutorURLCommand('read');$('tutor-revoke').onclick=()=>tutorURLCommand('revoke');$('tutor-exercise-button').onclick=()=>sendCommand('/api/tutor',{action:'exercise',language:selectedTutorLanguage},'tutor-feedback');$('tutor-solve').onclick=()=>sendCommand('/api/tutor',{action:'solve',language:selectedTutorLanguage},'tutor-feedback');
function externalSessionCommand(action,text){const session=selectedExternalSession();if(!session){feedback('external-feedback',t('Сначала выберите сессию'),true);return Promise.resolve(null)}const body={action,session_id:session.session_id};if(text!==undefined)body.text=text;return sendCommand('/api/external',body,'external-feedback')}
$('external-start-form').onsubmit=async e=>{e.preventDefault();const name=$('external-name').value.trim();if(!name){feedback('external-feedback',t('Укажите имя собеседника'),true);return}const result=await sendCommand('/api/external',{action:'start',provider:$('external-provider').value.trim(),name,external_id:$('external-id').value.trim(),topic:$('external-topic').value.trim(),reason:$('external-reason').value.trim(),model:$('external-model').value.trim()},'external-feedback');if(result)e.target.reset()};
$('external-ingest-form').onsubmit=async e=>{e.preventDefault();const text=$('external-ingest-text').value.trim();if(!text){feedback('external-feedback',t('Входящий текст не должен быть пустым'),true);return}const result=await externalSessionCommand('ingest',text);if(result)$('external-ingest-text').value=''};
$('external-edit-form').onsubmit=e=>{e.preventDefault();const text=$('external-edit-text').value.trim();if(!text){feedback('external-feedback',t('Текст ответа не должен быть пустым'),true);return}externalSessionCommand('edit',text)};
$('external-auto-form').onsubmit=e=>{e.preventDefault();const session=selectedExternalSession();if(!session){feedback('external-feedback',t('Сначала выберите сессию'),true);return}sendCommand('/api/external',{action:'auto',session_id:session.session_id,max_replies:Number($('external-max-replies').value),max_total_tokens:Number($('external-max-tokens').value),min_interval_sec:Number($('external-interval').value)},'external-feedback')};
for(const action of ['draft','approve','reject','handoff','stop','pause','resume','manual'])$( `external-${action}`).onclick=()=>externalSessionCommand(action);
$('external-clear').onclick=()=>{const session=selectedExternalSession();if(session&&window.confirm(t('Удалить локальный журнал этой сессии? Профиль собеседника сохранится.')))externalSessionCommand('clear')};
$('external-copy').onclick=async()=>{const pending=selectedExternalSession()?.pending_draft;if(!pending)return;try{await navigator.clipboard.writeText(pending.text||'');feedback('external-feedback',t('Текст скопирован. После передачи собеседнику отметьте handoff.'))}catch(error){feedback('external-feedback',t('Не удалось скопировать автоматически; выделите текст вручную.'),true)}};
function socialChannelCommand(action,fields={}){const channel=selectedSocialChannel();if(!channel){feedback('social-feedback',t('Сначала выберите канал'),true);return Promise.resolve(null)}return sendCommand('/api/social',{action,channel_id:channel.channel_id,...fields},'social-feedback')}
$('social-create-form').onsubmit=async e=>{e.preventDefault();const account_id=$('social-account').value.trim();if(!account_id){feedback('social-feedback',t('Укажите account ID сущности'),true);return}const result=await sendCommand('/api/social',{action:'create',provider:$('social-provider').value.trim(),account_id,author_kind:$('social-author-kind').value},'social-feedback');if(result)e.target.reset()};
$('social-grant-form').onsubmit=e=>{e.preventDefault();const conversation_ids=$('social-scopes').value.split(/\r?\n/).map(item=>item.trim()).filter(Boolean);socialChannelCommand('grant',{conversation_ids,receive:$('social-receive').checked,draft:$('social-draft').checked,reply:$('social-reply').checked,max_messages:Number($('social-max-messages').value),max_replies:Number($('social-max-replies').value),min_interval_sec:Number($('social-interval').value)})};
$('social-session-form').onsubmit=e=>{e.preventDefault();socialChannelCommand('session',{conversation_id:$('social-session-conversation').value.trim(),duration_sec:Number($('social-session-duration').value),poll_interval_sec:Number($('social-session-poll').value),initiative_after_sec:Number($('social-session-initiative').value)})};
for(const action of ['pause','resume','manual'])$(`social-session-${action}`).onclick=()=>socialChannelCommand(action);
$('social-session-stop').onclick=()=>socialChannelCommand('session-stop');
for(const action of ['revoke','stop'])$(`social-${action}`).onclick=()=>socialChannelCommand(action);
$('social-receive-once').onclick=()=>socialChannelCommand('receive');
$('social-send-approved').onclick=()=>{const pending=selectedSocialChannel()?.pending_draft;if(!pending||pending.status!=='approved'){feedback('social-feedback',t('Сначала одобрите точную ревизию'),true);return}socialChannelCommand('send',{draft_id:pending.message_id})};
$('social-draft-create').onclick=()=>{const channel=selectedSocialChannel(),inbound=[...(channel?.messages||[])].reverse().find(item=>item.direction==='inbound');if(!inbound){feedback('social-feedback',t('В канале нет входящей реплики'),true);return}socialChannelCommand('draft',{inbound_message_id:inbound.message_id})};
$('social-edit-form').onsubmit=e=>{e.preventDefault();const pending=selectedSocialChannel()?.pending_draft,text=$('social-edit-text').value.trim();if(!pending){feedback('social-feedback',t('Активного проекта нет'),true);return}if(!text){feedback('social-feedback',t('Текст ответа не должен быть пустым'),true);return}sendCommand('/api/social',{action:'edit',draft_id:pending.message_id,text},'social-feedback')};
for(const action of ['approve','reject'])$(`social-${action}`).onclick=()=>{const pending=selectedSocialChannel()?.pending_draft;if(!pending){feedback('social-feedback',t('Активного проекта нет'),true);return}sendCommand('/api/social',{action,draft_id:pending.message_id},'social-feedback')};
let voiceStream=null,voiceRecorder=null,voiceChunks=[],voiceHeld=false,voiceCancelled=false,voiceTranscribing=false,latestVoiceAvailable=false,latestVoiceOutputAvailable=false,latestVoiceAuto=false,latestVoiceResponseSequence=null,voiceOutputBusy=false;
function stopVoiceTracks(){if(voiceStream){voiceStream.getTracks().forEach(track=>track.stop());voiceStream=null}}
function updateVoiceOutputControls(){const connected=latestControl?.bus_connected===true;$('voice-replay').disabled=!connected||!latestVoiceOutputAvailable||latestVoiceResponseSequence===null||voiceOutputBusy;$('voice-auto').disabled=!connected||!latestVoiceOutputAvailable||voiceOutputBusy;if(!voiceOutputBusy)$('voice-auto').checked=latestVoiceAuto}
async function refreshVoiceStatus(){try{const status=await getJSON('/api/voice');latestVoiceAvailable=status.enabled===true;latestVoiceOutputAvailable=status.tts_enabled===true;latestVoiceAuto=status.auto_speak===true;latestVoiceResponseSequence=status.latest_response_sequence??null;$('voice-status').textContent=t(latestVoiceAvailable?'Удерживайте кнопку для записи':'Локальный STT недоступен');$('voice-output-status').textContent=t(latestVoiceOutputAvailable?(latestVoiceAuto?'Автоозвучивание включено':'Готов к озвучиванию по команде'):'Звуковой TTS недоступен')}catch(error){latestVoiceAvailable=false;latestVoiceOutputAvailable=false;latestVoiceAuto=false;$('voice-status').textContent=error.message;$('voice-output-status').textContent=error.message}finally{$('voice-record').disabled=!latestControl?.bus_connected||!latestVoiceAvailable||voiceTranscribing;updateVoiceOutputControls()}}
async function startVoiceRecording(){if(voiceRecorder||voiceTranscribing||!latestControl?.bus_connected||!latestVoiceAvailable)return;voiceHeld=true;voiceCancelled=false;if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined'){$('voice-status').textContent=t('Браузер не поддерживает запись');return}try{voiceStream=await navigator.mediaDevices.getUserMedia({audio:true});if(!voiceHeld){stopVoiceTracks();return}voiceChunks=[];voiceRecorder=new MediaRecorder(voiceStream);voiceRecorder.ondataavailable=event=>{if(event.data.size)voiceChunks.push(event.data)};voiceRecorder.onstop=async()=>{stopVoiceTracks();const cancelled=voiceCancelled,blob=new Blob(voiceChunks,{type:voiceRecorder?.mimeType||'audio/webm'});voiceRecorder=null;voiceChunks=[];if(cancelled){$('voice-status').textContent=t('Запись отменена');return}voiceTranscribing=true;$('voice-record').disabled=true;$('voice-status').textContent=t('Распознаю…');try{const response=await fetch('/api/voice/transcribe',{method:'POST',headers:{'Content-Type':blob.type||'audio/webm'},body:blob});const result=await response.json();if(!response.ok)throw new Error(result.message||t('Не удалось распознать речь'));if(voiceCancelled){$('voice-status').textContent=t('Запись отменена');return}$('dialogue-input').value=result.text;const confidence=result.confidence===null||result.confidence===undefined?t('неизвестна'):`${Math.round(result.confidence*100)}%`;$('voice-status').textContent=`${t('Проверьте текст перед отправкой')} · ${confidence}`;$('dialogue-input').focus()}catch(error){$('voice-status').textContent=error.message}finally{voiceTranscribing=false;$('voice-record').disabled=!latestControl?.bus_connected||!latestVoiceAvailable}};voiceRecorder.start();$('voice-status').textContent=t('● Запись — отпустите кнопку')}catch(error){voiceHeld=false;stopVoiceTracks();$('voice-status').textContent=error.message}}
function stopVoiceRecording(cancel=false){voiceHeld=false;voiceCancelled=cancel;if(voiceRecorder&&voiceRecorder.state!=='inactive')voiceRecorder.stop();else stopVoiceTracks()}
$('voice-replay').onclick=async()=>{if(latestVoiceResponseSequence===null||voiceOutputBusy)return;voiceOutputBusy=true;updateVoiceOutputControls();try{const result=await postJSON('/api/voice/speak',{sequence:latestVoiceResponseSequence});feedback('voice-output-status',result.message)}catch(error){feedback('voice-output-status',error.message,true)}finally{voiceOutputBusy=false;updateVoiceOutputControls()}};
$('voice-auto').onchange=async event=>{if(voiceOutputBusy)return;const requested=event.target.checked;voiceOutputBusy=true;updateVoiceOutputControls();try{const result=await postJSON('/api/voice/auto',{enabled:requested});latestVoiceAuto=result.auto_speak===true;feedback('voice-output-status',result.message)}catch(error){feedback('voice-output-status',error.message,true);await refreshVoiceStatus()}finally{voiceOutputBusy=false;updateVoiceOutputControls()}};
$('voice-record').onpointerdown=event=>{event.preventDefault();startVoiceRecording()};window.addEventListener('pointerup',()=>stopVoiceRecording(false));window.addEventListener('pointercancel',()=>stopVoiceRecording(true));window.addEventListener('blur',()=>stopVoiceRecording(true));
$('dialogue-form').onsubmit=async e=>{e.preventDefault();const input=$('dialogue-input'),text=input.value.trim();if(!text){feedback('dialogue-feedback',t('Сообщение не должно быть пустым'),true);return}const result=await sendCommand('/api/dialogue',{text},'dialogue-feedback');if(result){input.value='';input.focus()}};
$('life-confirm-form').onsubmit=e=>{e.preventDefault();const prompt=latestControl?.life_prompt;if(!prompt){feedback('life-result',t('Активного запроса ядра нет'),true);return}sendCommand('/api/control/life/confirm',{request_id:prompt.request_id,phrase:$('life-confirm-input').value},'life-result')};$('life-cancel-button').onclick=()=>{const prompt=latestControl?.life_prompt;if(prompt)sendCommand('/api/control/life/cancel',{request_id:prompt.request_id},'life-result')};
function applyTheme(theme){const cyber=theme==='cyber';document.body.classList.toggle('cyber-theme',cyber);$('theme-toggle').setAttribute('aria-pressed',String(cyber));$('theme-label').textContent=t(cyber?'Светлая тема':'Киберпанк');document.querySelector('meta[name="theme-color"]').content=cyber?'#07090c':'#f7f9fb'}
let initialTheme='cyber';try{const saved=localStorage.getItem('digital-being-theme');if(saved==='light'||saved==='cyber')initialTheme=saved}catch(error){/* Приватный режим может запретить localStorage. */}
applyTheme(initialTheme);$('theme-toggle').onclick=()=>{const next=document.body.classList.contains('cyber-theme')?'light':'cyber';applyTheme(next);try{localStorage.setItem('digital-being-theme',next)}catch(error){/* Тема продолжит работать без сохранения. */}};
$('language-select').onchange=event=>applyLanguage(event.target.value);applyLanguage(language,false);
refreshNow();refreshControl();refreshVoiceStatus();refreshDiary();refreshGraph();startDialogue();setInterval(refreshNow,3000);setInterval(refreshControl,1000);setInterval(refreshGraph,5000);
</script></body></html>"""
DASHBOARD_HTML = DASHBOARD_HTML.replace("__I18N_JSON__", i18n.language_json())


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
        self._diary: Dict[str, Any] = {
            "episodes": [],
            "count": 0,
            "cache_limit": max_diary,
        }
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

    def push_thought(
        self,
        text: str,
        *,
        kind: str = "thought",
        cycle: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        data: Dict[str, Any] = {"text": text}
        if meta:
            data["meta"] = deepcopy(meta)
        self.push_event(kind, data, cycle=cycle)

    def push_event(
        self,
        name: str,
        data: Any,
        *,
        source: str = "agent",
        timestamp: Optional[float] = None,
        cycle: Optional[int] = None,
    ) -> None:
        """Добавить событие с монотонным SSE sequence и отразить life-протокол."""
        payload = (
            deepcopy(data) if isinstance(data, dict) else {"text": str(data or "")}
        )
        ts = float(timestamp or time.time())
        kind = {
            "agent_question": "question",
            "agent_message": "agent",
            "agent_thought": "thought",
            "agent_web_result": "web",
            "user_message": "user",
        }.get(name, name)
        text = (
            payload.get("content")
            or payload.get("text")
            or payload.get("question")
            or payload.get("title")
            or payload.get("extract")
            or payload.get("description")
            or payload.get("message")
            or ""
        )
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
                cycle = (
                    int(payload["cycle"]) if payload.get("cycle") is not None else None
                )
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

    def subscribe_events(
        self, after: Optional[int] = None
    ) -> Tuple[asyncio.Queue, List[Dict[str, Any]]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=300)
        with self._lock:
            events = list(self._events)
            backlog = (
                events[-20:]
                if after is None
                else [e for e in events if e["sequence"] > after]
            )
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
            result["subsystems"] = deepcopy(
                self._subsystem_status.get("subsystems", [])
            )
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
        returned = episodes[offset : offset + limit]
        next_offset = offset + len(returned)
        has_more = next_offset < len(episodes)
        return {
            "episodes": returned,
            "offset": offset,
            "limit": limit,
            "returned": len(returned),
            "stored": len(episodes),
            "next_offset": next_offset if has_more else None,
            "has_more": has_more,
            "cache_limit": cache_limit,
            "may_have_older_outside_cache": len(episodes) >= cache_limit,
        }

    def dialogue_history(
        self, after: Optional[int] = None, limit: int = 50
    ) -> Dict[str, Any]:
        limit = max(1, min(200, int(limit)))
        with self._lock:
            events = list(self._events)
            latest = self._sequence
        selected = (
            events[-limit:]
            if after is None
            else [e for e in events if e["sequence"] > after][:limit]
        )
        oldest = events[0]["sequence"] if events else 0
        return {
            "events": deepcopy(selected),
            "count": len(selected),
            "latest_sequence": latest,
            "has_more": bool(selected and selected[-1]["sequence"] < latest),
            "history_gap": bool(after is not None and oldest and after < oldest - 1),
        }

    def response_text(self, sequence: int) -> Optional[str]:
        """Вернуть только опубликованный ответ сущности, не текст клиента."""
        with self._lock:
            item = next(
                (event for event in self._events if event["sequence"] == sequence),
                None,
            )
            if item is None or item.get("kind") != "agent":
                return None
            text = str(item.get("text") or "").strip()
            return text or None

    def latest_response_sequence(self) -> Optional[int]:
        with self._lock:
            return next(
                (
                    event["sequence"]
                    for event in reversed(self._events)
                    if event.get("kind") == "agent"
                    and str(event.get("text") or "").strip()
                ),
                None,
            )


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
        return _json_response(
            {"error": "offset и limit должны быть целыми"}, status=400
        )
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


def _command_boundary_error(request: Any) -> Optional[CommandError]:
    """Отклонить browser-to-local команду с другого происхождения."""
    try:
        request_host = request.url.host
    except ValueError:
        request_host = None
    fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    origin = request.headers.get("Origin", "").strip().rstrip("/")
    expected_origin = f"{request.scheme}://{request.host}"
    if (
        request_host not in {"127.0.0.1", "localhost", "::1"}
        or fetch_site == "cross-site"
        or (origin and origin != expected_origin)
    ):
        return CommandError("cross-site команда запрещена", status=403)
    return None


async def _read_json_object(request: Any) -> Dict[str, Any]:
    boundary_error = _command_boundary_error(request)
    if boundary_error is not None:
        raise boundary_error
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
    boundary_error = _command_boundary_error(request)
    if boundary_error is not None:
        return _json_response(
            {"status": "rejected", "message": str(boundary_error)},
            status=boundary_error.status,
        )
    if request.content_type != "application/json":
        return _json_response(
            {"status": "rejected", "message": "ожидается application/json"},
            status=415,
        )
    bus = request.app[BUS_KEY]
    if bus is None:
        return _json_response(
            {
                "status": "unavailable",
                "message": "ядро не подключено; команда не отправлена",
            },
            status=503,
        )
    accepted = bus.publish_sync(name, data, source="web")
    if not accepted:
        return _json_response(
            {
                "status": "unavailable",
                "message": "очередь событий недоступна; команда не принята",
            },
            status=503,
        )
    return _json_response(
        {
            "status": "accepted",
            "event": name,
            "message": "событие принято; результат появится в следующем снимке",
        },
        status=202,
    )


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
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    return _publish_event(request, Events.USER_MESSAGE, {"text": text})


async def handle_voice_status(request: Any) -> Any:
    service = request.app.get(VOICE_KEY)
    output = request.app.get(VOICE_OUTPUT_KEY)
    state = request.app.get(STATE_KEY)
    return _json_response(
        {
            "enabled": bool(service is not None and service.enabled),
            "tts_enabled": bool(output is not None and output.enabled),
            "auto_speak": bool(output is not None and output.auto_enabled),
            "latest_response_sequence": (
                state.latest_response_sequence() if state is not None else None
            ),
        }
    )


async def handle_voice_auto(request: Any) -> Any:
    """Изменить только режим вывода; содержание ответов остаётся в Core."""
    try:
        data = await _read_json_object(request)
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise CommandError("enabled должен быть boolean")
    except CommandError as exc:
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    output = request.app.get(VOICE_OUTPUT_KEY)
    if output is None:
        return _json_response(
            {"status": "unavailable", "message": "звуковой TTS недоступен"},
            status=503,
        )
    try:
        output.set_auto(enabled)
    except PermissionError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=403)
    return _json_response(
        {
            "status": "updated",
            "auto_speak": output.auto_enabled,
            "message": (
                "автоматическое озвучивание включено"
                if output.auto_enabled
                else "автоматическое озвучивание выключено"
            ),
        }
    )


async def handle_voice_speak(request: Any) -> Any:
    """Озвучить журнальную реплику по sequence; произвольный текст не принимается."""
    try:
        data = await _read_json_object(request)
        sequence = data.get("sequence")
        if type(sequence) is not int or sequence < 1:
            raise CommandError("sequence должен быть положительным целым")
    except CommandError as exc:
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    state = request.app.get(STATE_KEY)
    text = state.response_text(sequence) if state is not None else None
    if text is None:
        return _json_response(
            {"status": "not_found", "message": "опубликованный ответ не найден"},
            status=404,
        )
    output = request.app.get(VOICE_OUTPUT_KEY)
    if output is None:
        return _json_response(
            {"status": "unavailable", "message": "звуковой TTS недоступен"},
            status=503,
        )
    try:
        await asyncio.to_thread(output.speak, text)
    except PermissionError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=403)
    except (ValueError, RuntimeError) as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=422)
    return _json_response(
        {
            "status": "started",
            "sequence": sequence,
            "message": "озвучивание опубликованного ответа запущено",
        }
    )


async def handle_voice_transcribe(request: Any) -> Any:
    """Вернуть предпросмотр STT; этот endpoint не публикует USER_MESSAGE."""
    from src.metrics.voice_input import VoiceInputService

    service = request.app.get(VOICE_KEY)
    if service is None or not service.enabled:
        return _json_response(
            {"status": "rejected", "message": "локальный STT выключен"},
            status=403,
        )
    content_length = getattr(request, "content_length", None)
    if (
        content_length is not None
        and content_length > VoiceInputService.MAX_AUDIO_BYTES
    ):
        return _json_response(
            {"status": "rejected", "message": "аудиозапись слишком велика"},
            status=413,
        )
    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].lower()
    suffix = {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/wave": ".wav",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/flac": ".flac",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
    }.get(content_type)
    if suffix is None:
        return _json_response(
            {"status": "rejected", "message": "неподдерживаемый формат аудио"},
            status=415,
        )
    try:
        audio = await request.read()
        result = await asyncio.to_thread(service.transcribe_bytes, audio, suffix=suffix)
    except PermissionError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=403)
    except ValueError as exc:
        return _json_response({"status": "rejected", "message": str(exc)}, status=400)
    except Exception:
        logger.exception("Локальное распознавание голосового ввода не удалось")
        return _json_response(
            {"status": "rejected", "message": "локальное распознавание не удалось"},
            status=422,
        )
    return _json_response(
        {
            "status": "preview",
            "text": result.text,
            "confidence": result.confidence,
            "confidence_basis": result.confidence_basis,
            "engine": result.engine,
            "model": result.model,
        }
    )


async def handle_control(request: Any) -> Any:
    return _json_response(
        request.app[STATE_KEY].control_snapshot(
            bus_connected=request.app[BUS_KEY] is not None,
        )
    )


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
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
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
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    return _publish_event(
        request, Events.LIFE_REQUEST, {"kind": kind, "reason": reason}
    )


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
            raise CommandError(
                "сначала дождитесь подтверждающего запроса ядра", status=409
            )
    except CommandError as exc:
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    return _publish_event(
        request,
        Events.LIFE_CONFIRM,
        {
            "request_id": request_id,
            "phrase": phrase,
        },
    )


async def handle_life_cancel(request: Any) -> Any:
    from src.core.event_bus import Events

    try:
        data = await _read_json_object(request)
        request_id = str(data.get("request_id", "")).strip()
        prompt = request.app[STATE_KEY].current_life_prompt()
        if (
            not request_id
            or not prompt
            or str(prompt.get("request_id", "")) != request_id
        ):
            raise CommandError(
                "активный запрос с таким request_id не найден", status=409
            )
    except CommandError as exc:
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
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
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    return _publish_event(
        request, Events.USER_COMMAND, {"command": f"access {key} {state}"}
    )


async def handle_tutor(request: Any) -> Any:
    """Узкий мост кнопок наставника в существующие команды AgentRunner."""
    from src.core.event_bus import Events

    try:
        data = await _read_json_object(request)
        raw_language = data.get("language", "ru")
        language = raw_language.strip().lower() if isinstance(raw_language, str) else ""
        if language not in {"ru", "en"}:
            raise CommandError("язык наставника должен быть ru или en")
        raw_action = data.get("action")
        action = raw_action.strip().lower() if isinstance(raw_action, str) else ""
        if action not in TUTOR_ACTIONS:
            raise CommandError("неизвестное действие наставника")
        argument = ""
        if action in {"allow", "read", "revoke"}:
            raw_url = data.get("url")
            if not isinstance(raw_url, str):
                raise CommandError("нужен HTTPS URL")
            argument = raw_url.strip()
            if not argument or len(argument) > MAX_TUTOR_URL_CHARS:
                raise CommandError("URL пуст или длиннее 600 символов")
        elif action in {"approve", "approve_read", "reject"}:
            raw_id = data.get("request_id")
            if not isinstance(raw_id, str):
                raise CommandError("нужен request_id")
            argument = raw_id.strip()
            if not argument or len(argument) > MAX_TUTOR_REQUEST_ID_CHARS:
                raise CommandError("request_id пуст или слишком длинный")
    except CommandError as exc:
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    prefix = "tutor en" if language == "en" else "tutor"
    command = f"{prefix} {action} {argument}".rstrip()
    return _publish_event(request, Events.USER_COMMAND, {"command": command})


async def handle_external(request: Any) -> Any:
    """Узкий мост внешних сессий; произвольные команды и send недоступны."""
    from src.core.event_bus import Events

    def field(data, key, limit, *, required=False):
        raw = data.get(key, "")
        if not isinstance(raw, str):
            raise CommandError(f"поле {key} должно быть строкой")
        value = raw.strip()
        if required and not value:
            raise CommandError(f"поле {key} не должно быть пустым")
        if len(value) > limit:
            raise CommandError(f"поле {key} длиннее {limit} символов")
        if "|" in value or "\r" in value or "\n" in value:
            raise CommandError(f"поле {key} содержит недопустимый разделитель")
        return value

    def session_id(data):
        value = field(data, "session_id", MAX_EXTERNAL_SESSION_ID_CHARS, required=True)
        if any(char.isspace() for char in value):
            raise CommandError("session_id содержит недопустимый пробел")
        return value

    try:
        data = await _read_json_object(request)
        raw_action = data.get("action")
        action = raw_action.strip().lower() if isinstance(raw_action, str) else ""
        if action not in EXTERNAL_ACTIONS:
            raise CommandError("неизвестное действие внешней сессии")
        if action == "start":
            fields = (
                field(data, "provider", 64) or "manual",
                field(data, "name", 120, required=True),
                field(data, "external_id", 128),
                field(data, "topic", 160),
                field(data, "reason", 240),
                field(data, "model", 128),
            )
            if not fields[-1]:
                fields = fields[:-1]
            command = "external start " + " | ".join(fields)
        elif action == "auto":
            identity = session_id(data)
            replies = data.get("max_replies", 3)
            tokens = data.get("max_total_tokens", 1200)
            interval = data.get("min_interval_sec", 2.0)
            if (
                isinstance(replies, bool)
                or not isinstance(replies, int)
                or not 1 <= replies <= 8
                or isinstance(tokens, bool)
                or not isinstance(tokens, int)
                or not 1 <= tokens <= 256000
                or isinstance(interval, bool)
                or not isinstance(interval, (int, float))
                or not 1.0 <= float(interval) <= 60.0
            ):
                raise CommandError("некорректные лимиты автономного обмена")
            command = f"external auto {identity} {replies} {tokens} {interval:g}"
        elif action in {"ingest", "edit"}:
            identity = session_id(data)
            raw_text = data.get("text")
            if not isinstance(raw_text, str):
                raise CommandError("текст внешней реплики должен быть строкой")
            text = raw_text.strip()
            if not text or len(text) > MAX_EXTERNAL_TEXT_CHARS:
                raise CommandError("текст пуст или длиннее 4000 символов")
            command = f"external {action} {identity} | {text}"
        else:
            identity = session_id(data)
            if action not in EXTERNAL_SESSION_ACTIONS:
                raise CommandError("действие не поддерживается")
            command = f"external {action} {identity}"
    except CommandError as exc:
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    return _publish_event(request, Events.USER_COMMAND, {"command": command})


async def handle_social(request: Any) -> Any:
    """Owner-only мост 9D; manual receive/send не создают ingress worker или auto."""
    from src.core.event_bus import Events

    def field(data, key, limit=160, *, required=True, separator=True):
        raw = data.get(key, "")
        if not isinstance(raw, str):
            raise CommandError(f"поле {key} должно быть строкой")
        value = raw.strip()
        if required and not value:
            raise CommandError(f"поле {key} не должно быть пустым")
        if len(value) > limit or any(char.isspace() for char in value):
            raise CommandError(f"поле {key} содержит недопустимый идентификатор")
        if separator and "|" in value:
            raise CommandError(f"поле {key} содержит недопустимый разделитель")
        return value

    try:
        data = await _read_json_object(request)
        raw_action = data.get("action")
        action = raw_action.strip().lower() if isinstance(raw_action, str) else ""
        if action not in SOCIAL_ACTIONS:
            raise CommandError("неизвестное действие социального канала")
        if action == "create":
            provider = field(data, "provider", 64)
            account_id = field(data, "account_id", 128)
            kind = field(data, "author_kind", 32, required=False) or "external_person"
            if kind not in {"external_person", "external_ai"}:
                raise CommandError("недопустимый тип внешнего автора")
            command = f"social create {provider} | {account_id} | {kind}"
        elif action == "grant":
            channel_id = field(data, "channel_id", 36)
            scopes = data.get("conversation_ids")
            if not isinstance(scopes, list) or len(scopes) > 32:
                raise CommandError("conversation_ids должен быть ограниченным списком")
            clean_scopes = []
            for scope in scopes:
                if (
                    not isinstance(scope, str)
                    or not scope.strip()
                    or len(scope.strip()) > 160
                ):
                    raise CommandError("некорректный conversation_id")
                clean_scopes.append(scope.strip())
            if len(set(clean_scopes)) != len(clean_scopes):
                raise CommandError("conversation_ids не должны повторяться")
            policy = {"conversation_ids": clean_scopes}
            for key in ("receive", "draft", "reply"):
                if not isinstance(data.get(key), bool):
                    raise CommandError(f"поле {key} должно быть boolean")
                policy[key] = data[key]
            for key, maximum in (("max_messages", 64), ("max_replies", 64)):
                value = data.get(key)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not 0 <= value <= maximum
                ):
                    raise CommandError(f"поле {key} вне допустимых пределов")
                policy[key] = value
            interval = data.get("min_interval_sec")
            if (
                isinstance(interval, bool)
                or not isinstance(interval, (int, float))
                or not 0.0 <= float(interval) <= 3600.0
            ):
                raise CommandError("min_interval_sec вне допустимых пределов")
            policy["min_interval_sec"] = interval
            encoded = json.dumps(policy, ensure_ascii=False, separators=(",", ":"))
            command = f"social grant {channel_id} | {encoded}"
        elif action == "session":
            channel_id = field(data, "channel_id", 36)
            conversation_id = field(data, "conversation_id", 160)
            limits = (
                ("duration_sec", 1.0, 3600.0),
                ("poll_interval_sec", 0.01, 60.0),
                ("initiative_after_sec", 1.0, 900.0),
            )
            session_numbers: list[float] = []
            for key, session_minimum, session_maximum in limits:
                session_value = data.get(key)
                if (
                    isinstance(session_value, bool)
                    or not isinstance(session_value, (int, float))
                    or not math.isfinite(session_value)
                    or not session_minimum <= float(session_value) <= session_maximum
                ):
                    raise CommandError(f"поле {key} вне допустимых пределов")
                session_numbers.append(float(session_value))
            session_duration, session_poll, session_initiative = session_numbers
            command = (
                f"social session {channel_id} {conversation_id} "
                f"{session_duration:g} {session_poll:g} {session_initiative:g}"
            )
        elif action == "draft":
            channel_id = field(data, "channel_id", 36)
            inbound_id = field(data, "inbound_message_id")
            command = f"social draft {channel_id} {inbound_id}"
        elif action == "edit":
            draft_id = field(data, "draft_id")
            text = data.get("text")
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text.strip()) > 4000
            ):
                raise CommandError("текст проекта пуст или длиннее 4000 символов")
            command = f"social edit {draft_id} | {text.strip()}"
        elif action == "send":
            channel_id = field(data, "channel_id", 36)
            draft_id = field(data, "draft_id")
            command = f"social send {channel_id} {draft_id}"
        elif action in SOCIAL_DRAFT_ACTIONS:
            command = f"social {action} {field(data, 'draft_id')}"
        else:
            if action not in SOCIAL_CHANNEL_ACTIONS:
                raise CommandError("действие не поддерживается")
            command = f"social {action} {field(data, 'channel_id', 36)}"
    except CommandError as exc:
        return _json_response(
            {"status": "rejected", "message": str(exc)}, status=exc.status
        )
    return _publish_event(request, Events.USER_COMMAND, {"command": command})


async def handle_health(request: Any) -> Any:
    snapshot = request.app[STATE_KEY].snapshot()
    now = time.time()
    updated = snapshot.get("last_update_ts", 0)
    bus_connected = request.app[BUS_KEY] is not None
    responsive = bool(bus_connected and updated and now - updated < 60)
    age = now - updated if updated else None
    if request.query.get("check", "live").lower() == "ready":
        if not responsive:
            reason = (
                "ядро не подключено"
                if not bus_connected
                else "no agent update in 60+ seconds"
            )
            return _json_response(
                {
                    "status": "not_ready",
                    "agent_responsive": False,
                    "last_update_age_sec": age,
                    "reason": reason,
                },
                status=503,
            )
        return _json_response(
            {
                "status": "ready",
                "agent_responsive": True,
                "last_update_age_sec": round(age, 2),
            }
        )
    return _json_response(
        {
            "status": "ok",
            "agent_responsive": responsive,
            "last_update_age_sec": round(age, 2) if age is not None else None,
            "subsystem_count": snapshot.get("subsystem_count", 0),
        }
    )


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
        metrics.append(
            ("digital_being_goal_progress_percent", "gauge", goals["progress"])
        )
    if will.get("total_acts") or will.get("total"):
        metrics.append(
            (
                "digital_being_will_acts_total",
                "counter",
                will.get("total_acts") or will.get("total"),
            )
        )
    lines: List[str] = []
    for name, kind, val in metrics:
        lines.extend(
            (
                f"# HELP {name} Digital Being read-only metric",
                f"# TYPE {name} {kind}",
                f"{name} {val}",
            )
        )
    return web.Response(
        text="\n".join(lines) + "\n",
        content_type="text/plain",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


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
    return _json_response(
        {"status": "forbidden", "message": READ_ONLY_MESSAGE}, status=403
    )


async def handle_sse(request: Any) -> Any:
    state: SharedState = request.app[STATE_KEY]
    raw_after = request.headers.get("Last-Event-ID", request.query.get("after"))
    try:
        after = max(0, int(raw_after)) if raw_after not in (None, "") else None
    except ValueError:
        after = None
    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
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
                # Очередь подписчика может потерять событие под нагрузкой.
                # Восполняем разрыв из общей ограниченной истории до текущего
                # события; безвозвратно вытесненный префикс восстановит клиент
                # через полный resync при обнаружении оставшегося разрыва.
                while item["sequence"] > last_sent + 1:
                    recovered = [
                        event
                        for event in state.dialogue_history(after=last_sent, limit=200)[
                            "events"
                        ]
                        if last_sent < event["sequence"] < item["sequence"]
                    ]
                    if not recovered:
                        break
                    for event in recovered:
                        await _write_sse(response, event)
                        last_sent = event["sequence"]
                if item["sequence"] > last_sent:
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

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        state: Optional[SharedState] = None,
        bus: Optional[Any] = None,
        voice_input: Optional[Any] = None,
        voice_output: Optional[Any] = None,
    ) -> None:
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp не установлен; веб отключён, Tk может работать")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("веб разрешает только localhost")
        self.host, self.port = host, port
        self.state = state or SharedState()
        self.bus = bus
        self.voice_input = voice_input
        self.voice_output = voice_output
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.BaseSite] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._stop_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(
            self._loop and self._loop.is_running() and self._start_error is None
        )

    def start(self, *, in_thread: bool = True) -> None:
        if self.running:
            return
        self._start_error = None
        self._started.clear()
        if in_thread:
            self._thread = threading.Thread(
                target=self._run_in_thread, name="web-dashboard", daemon=True
            )
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
                        self._loop.run_until_complete(
                            asyncio.wait_for(self._runner.cleanup(), timeout=1.0)
                        )
                    except Exception:
                        pass
                self._loop.close()

    def _install_app(self, loop: asyncio.AbstractEventLoop) -> None:
        from src.metrics.voice_input import VoiceInputService

        app = web.Application(client_max_size=VoiceInputService.MAX_AUDIO_BYTES)
        app[STATE_KEY] = self.state
        app[BUS_KEY] = self.bus
        app[VOICE_KEY] = self.voice_input
        app[VOICE_OUTPUT_KEY] = self.voice_output
        app.router.add_get("/", handle_index)
        app.router.add_get("/health", handle_health)
        app.router.add_get("/metrics", handle_metrics)
        app.router.add_get("/api/status", handle_status)
        app.router.add_get("/api/life", handle_life)
        app.router.add_get("/api/diary", handle_diary)
        app.router.add_get("/api/dialogue", handle_dialogue)
        app.router.add_post("/api/dialogue", handle_dialogue_send)
        app.router.add_get("/api/voice", handle_voice_status)
        app.router.add_post("/api/voice/transcribe", handle_voice_transcribe)
        app.router.add_post("/api/voice/speak", handle_voice_speak)
        app.router.add_post("/api/voice/auto", handle_voice_auto)
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
        app.router.add_post("/api/tutor", handle_tutor)
        app.router.add_post("/api/external", handle_external)
        app.router.add_post("/api/social", handle_social)
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
                        future = asyncio.run_coroutine_threadsafe(
                            self._shutdown_async(), loop
                        )
                        try:
                            future.result(timeout=3)
                        finally:
                            # Даже при ошибке cleanup loop обязан остановиться.
                            loop.call_soon_threadsafe(loop.stop)
                    elif self._thread is None:
                        loop.run_until_complete(self._shutdown_async())
                except Exception as exc:
                    logger.warning("Остановка веб-наблюдателя: %s", exc)
        if (
            self._thread
            and self._thread.is_alive()
            and self._thread is not threading.current_thread()
        ):
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

    def publish_thought(
        self,
        text: str,
        *,
        cycle: Optional[int] = None,
        kind: str = "thought",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.state.push_thought(text, cycle=cycle, kind=kind, meta=meta)


def _demo_state() -> SharedState:
    """Маленький честный standalone: демонстрационные DTO, не живой профиль."""
    state = SharedState()
    state.update_status(
        {
            "name": "Standalone preview",
            "cycle": 0,
            "energy": 0,
            "max_energy": 200,
            "concepts": 0,
            "uptime_sec": 0,
        }
    )
    state.update_life(
        {
            "name": "Standalone preview",
            "life": {
                "cycle": 0,
                "energy": 0,
                "state": "unknown",
                "state_label": "ядро не подключено",
            },
            "now": {"activity": None},
            "motivation": {},
            "intentions": {"recent": []},
            "emotions": {"levels": {}, "dominant": None},
            "body": {},
            "activities": {},
            "access": {},
            "effector": {"counts": {}},
        }
    )
    state.update_diary({"episodes": [], "cache_limit": 500})
    state.push_event(
        "agent_message",
        {
            "text": "Standalone preview: ядро не запущено, данные не выдаются за живую сущность."
        },
    )
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
