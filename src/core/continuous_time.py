"""
Непрерывное время / Event-Driven архитектура.

Retention (удержание прошлости) + Protension (ожидание будущего) + Subjective Time
"""

import time
import heapq
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from collections import deque
from enum import Enum
from src.core.buffered_logger import get_logger

logger = get_logger()


class EventType(Enum):
    STIMULUS = "stimulus"
    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"
    INTEROCEPTION = "interoception"
    MOTIVATION = "motivation"
    SOCIAL = "social"
    LEARNING = "learning"
    CHECKPOINT = "checkpoint"
    TICK = "tick"


@dataclass
class Event:
    event_type: EventType
    timestamp: float
    subjective_time: float
    dt: float
    payload: Dict
    causality: List[str] = field(default_factory=list)
    event_id: str = ""
    
    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"{self.event_type.value}_{self.timestamp:.6f}"


class RetentionBuffer:
    def __init__(self, max_duration: float = 300.0, compression_rate: float = 0.95):
        self.max_duration = max_duration
        self.compression_rate = compression_rate
        self.events: deque = deque(maxlen=10000)
        self.compressed_segments: List[Dict] = []
        
    def append(self, event: Event):
        self.events.append(event)
        self._maybe_compress()
    
    def _maybe_compress(self):
        if len(self.events) < 100:
            return
        now = time.monotonic()
        cutoff = now - self.max_duration
        old_events = [e for e in self.events if e.timestamp < cutoff]
        
        if len(old_events) > 10:
            segment = {
                'start_time': old_events[0].timestamp,
                'end_time': old_events[-1].timestamp,
                'event_count': len(old_events),
                'dominant_types': self._dominant_types(old_events),
                'summary': self._summarize(old_events),
                'subjective_duration': old_events[-1].subjective_time - old_events[0].subjective_time
            }
            self.compressed_segments.append(segment)
            self.events = deque([e for e in self.events if e.timestamp >= cutoff], 
                               maxlen=self.events.maxlen)
    
    def _dominant_types(self, events: List[Event]) -> Dict[str, int]:
        counts = {}
        for e in events:
            counts[e.event_type.value] = counts.get(e.event_type.value, 0) + 1
        return counts
    
    def _summarize(self, events: List[Event]) -> str:
        types = self._dominant_types(events)
        top = sorted(types.items(), key=lambda x: -x[1])[:3]
        return f"Segment: {', '.join(f'{t}({c})' for t,c in top)}"
    
    def get_recent(self, duration: float = 10.0) -> List[Event]:
        now = time.monotonic()
        cutoff = now - duration
        return [e for e in self.events if e.timestamp >= cutoff]
    
    def get_retention_span(self) -> float:
        if not self.events:
            return 0.0
        return self.events[-1].subjective_time - self.events[0].subjective_time


class ProtensionBuffer:
    def __init__(self, horizon: float = 30.0):
        self.horizon = horizon
        self.predictions: List[Dict] = []
        self.active_intentions: List[Dict] = []
        
    def add_prediction(self, prediction: Dict):
        pred = {
            'timestamp': time.monotonic(),
            'expected_time': prediction.get('expected_time', time.monotonic() + 1.0),
            'content': prediction,
            'confidence': prediction.get('confidence', 0.5),
            'source': prediction.get('source', 'unknown')
        }
        self.predictions.append(pred)
        self._prune()
    
    def add_intention(self, intention: Dict):
        intent = {
            'timestamp': time.monotonic(),
            'action': intention.get('action'),
            'expected_outcome': intention.get('expected_outcome'),
            'priority': intention.get('priority', 0.5),
            'deadline': intention.get('deadline', time.monotonic() + 60.0)
        }
        self.active_intentions.append(intent)
        self._prune()
    
    def _prune(self):
        now = time.monotonic()
        cutoff = now - self.horizon
        self.predictions = [p for p in self.predictions if p['expected_time'] > cutoff]
        self.active_intentions = [i for i in self.active_intentions if i['deadline'] > cutoff]
    
    def get_expected_events(self, window: float = 5.0) -> List[Dict]:
        now = time.monotonic()
        return [p for p in self.predictions 
                if now < p['expected_time'] < now + window]
    
    def get_pending_intentions(self) -> List[Dict]:
        return sorted(self.active_intentions, key=lambda x: x['deadline'])
    
    def match_observation(self, observation: Dict) -> List[Dict]:
        matched = []
        for p in self.predictions:
            if self._matches(p['content'], observation):
                matched.append(p)
        return matched
    
    def _matches(self, pred: Dict, obs: Dict) -> bool:
        for k, v in pred.items():
            if k in obs and obs[k] != v:
                return False
        return True


class SubjectiveTime:
    def __init__(self):
        self.dilation = 1.0
        self.base_rate = 1.0
        self.history: deque = deque(maxlen=100)
        
    def update(self, cognitive_load: float, novelty: float, 
               arousal: float, flow: float):
        self.dilation = 1.0
        self.dilation += cognitive_load * 0.5
        self.dilation += novelty * 0.8
        self.dilation += arousal * 0.3
        self.dilation -= flow * 0.6
        self.dilation = np.clip(self.dilation, 0.3, 3.0)
        self.history.append(self.dilation)
    
    def subjective_dt(self, objective_dt: float) -> float:
        return objective_dt * self.dilation
    
    def get_status(self) -> Dict:
        return {
            'dilation': self.dilation,
            'mean_dilation': np.mean(self.history) if self.history else 1.0,
            'time_feeling': self._time_feeling()
        }
    
    def _time_feeling(self) -> str:
        if self.dilation > 1.5: return "dragging"
        elif self.dilation > 1.2: return "slow"
        elif self.dilation < 0.7: return "flying"
        elif self.dilation < 0.9: return "flowing"
        else: return "normal"


class EventScheduler:
    def __init__(self):
        self.event_queue: List[tuple] = []
        self.current_time = time.monotonic()
        self.event_counter = 0
        self.recurring: Dict[str, Dict] = {}
        
    def schedule(self, delay: float, event_factory: Callable, 
                 event_id: str = None, recurring: bool = False, interval: float = None) -> str:
        self.event_counter += 1
        eid = event_id or f"evt_{self.event_counter}"
        scheduled = self.current_time + delay
        heapq.heappush(self.event_queue, (scheduled, eid, event_factory))
        
        if recurring and interval:
            self.recurring[eid] = {
                'interval': interval,
                'factory': event_factory,
                'next_time': scheduled + interval
            }
        return eid
    
    def schedule_at(self, absolute_time: float, event_factory: Callable, 
                    event_id: str = None) -> str:
        self.event_counter += 1
        eid = event_id or f"evt_{self.event_counter}"
        heapq.heappush(self.event_queue, (absolute_time, eid, event_factory))
        return eid
    
    def cancel(self, event_id: str) -> bool:
        if event_id in self.recurring:
            del self.recurring[event_id]
            return True
        return False
    
    def get_next_event(self) -> Optional[tuple]:
        if not self.event_queue:
            return None
        scheduled, eid, factory = heapq.heappop(self.event_queue)
        
        if eid in self.recurring:
            rec = self.recurring[eid]
            rec['next_time'] += rec['interval']
            heapq.heappush(self.event_queue, (rec['next_time'], eid, rec['factory']))
        
        self.current_time = scheduled
        return (scheduled, eid, factory)
    
    def peek_next_time(self) -> Optional[float]:
        return self.event_queue[0][0] if self.event_queue else None
    
    def time_until_next(self) -> float:
        next_t = self.peek_next_time()
        if next_t is None:
            return float('inf')
        return max(0.0, next_t - time.monotonic())
    
    def get_status(self) -> Dict:
        return {
            'queue_size': len(self.event_queue),
            'recurring_count': len(self.recurring),
            'current_time': self.current_time,
            'next_event_in': self.time_until_next()
        }


class ContinuousTimeEngine:
    def __init__(self, agent):
        self.agent = agent
        self.scheduler = EventScheduler()
        self.retention = RetentionBuffer()
        self.protension = ProtensionBuffer()
        self.subjective_time = SubjectiveTime()
        
        self.running = False
        self.last_tick = time.monotonic()
        self.total_objective_time = 0.0
        self.total_subjective_time = 0.0
        
        logger.log("[CONTINUOUS_TIME] Engine initialized")
    
    def step(self, dt: float = None) -> Dict:
        now = time.monotonic()
        
        if dt is None:
            dt = self.scheduler.time_until_next()
            dt = min(dt, 1.0)
        
        if dt <= 0:
            dt = 0.001
        
        cognitive_load = getattr(self.agent, '_current_cognitive_load', 0.0)
        novelty = getattr(self.agent, '_current_novelty', 0.0)
        arousal = getattr(self.agent, '_current_arousal', 0.0)
        flow = getattr(self.agent, '_current_flow', 0.0)
        
        self.subjective_time.update(cognitive_load, novelty, arousal, flow)
        subjective_dt = self.subjective_time.subjective_dt(dt)
        
        processed = []
        while True:
            next_evt = self.scheduler.get_next_event()
            if next_evt is None:
                break
            scheduled, eid, factory = next_evt
            if scheduled > now + dt:
                heapq.heappush(self.scheduler.event_queue, (scheduled, eid, factory))
                break
            
            try:
                event = factory()
                if event:
                    event.timestamp = scheduled
                    event.subjective_time = self.total_subjective_time
                    event.dt = dt
                    self.retention.append(event)
                    processed.append(event)
            except Exception as e:
                logger.log(f"[CONTINUOUS_TIME] Event {eid} failed: {e}")
        
        self.total_objective_time += dt
        self.total_subjective_time += subjective_dt
        self.last_tick = now
        
        return {
            'dt': dt,
            'subjective_dt': subjective_dt,
            'time_dilation': self.subjective_time.dilation,
            'processed_events': len(processed),
            'events': processed,
            'retention_span': self.retention.get_retention_span(),
            'protension_horizon': len(self.protension.get_expected_events(10.0))
        }
    
    def emit_event(self, event_type: EventType, payload: Dict, 
                   causality: List[str] = None) -> Event:
        now = time.monotonic()
        event = Event(
            event_type=event_type,
            timestamp=now,
            subjective_time=self.total_subjective_time,
            dt=0.0,
            payload=payload,
            causality=causality or []
        )
        self.retention.append(event)
        return event
    
    def predict(self, prediction: Dict):
        self.protension.add_prediction(prediction)
    
    def intend(self, intention: Dict):
        self.protension.add_intention(intention)
    
    def get_status(self) -> Dict:
        return {
            'objective_time': self.total_objective_time,
            'subjective_time': self.total_subjective_time,
            'time_dilation': self.subjective_time.dilation,
            'retention': {
                'events_in_buffer': len(self.retention.events),
                'compressed_segments': len(self.retention.compressed_segments),
                'span': self.retention.get_retention_span()
            },
            'protension': {
                'predictions': len(self.protension.predictions),
                'intentions': len(self.protension.active_intentions),
                'next_expected': self.protension.get_expected_events(5.0)
            },
            'scheduler': self.scheduler.get_status()
        }


def create_continuous_time_engine(agent) -> ContinuousTimeEngine:
    return ContinuousTimeEngine(agent)