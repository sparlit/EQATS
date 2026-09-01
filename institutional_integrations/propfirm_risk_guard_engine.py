"""
PropFirm Risk Guard Engine (EQATS Institutional Adaptation)
Adapted from whaleclap/propfirm-risk-guard & PTHAICAP/trading-risk-monitor

Provides an event-driven risk engine for prop trading challenges and funded accounts.
Supports:
- Trailing Intraday & EOD Drawdown with dynamic ratcheting equity floors (locks at initial balance or fixed peak)
- Dynamic Daily Loss resetting at session roll
- Session Cutoff Scrambler (pre-warning and mandatory position flattener)
- Consistency Score Auditor (max single-day profit % rule enforcement)
- News Blackout Window Enforcement
- HTML/SVG Risk Dashboard Snapshot Generator
"""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

class RiskSeverity(str, Enum):
    INFO = 'INFO'
    WARN = 'WARN'
    FLATTEN = 'FLATTEN'
    BREACH = 'BREACH'

@dataclass
class RiskTick:
    timestamp: datetime
    equity: float
    position_size: float = 0.0
    price: float = 0.0
    symbol: str = 'SYSTEM'

@dataclass
class GuardEvent:
    timestamp: datetime
    severity: RiskSeverity
    rule_name: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class NewsWindow:
    label: str
    start_time: time
    end_time: time

@dataclass
class TrailingDDConfig:
    max_drawdown: float
    mode: str = 'intraday_peak'
    lock_at_initial: bool = True
    lock_equity_buffer: float = 0.0

@dataclass
class DailyLossConfig:
    limit: float
    mode: str = 'from_day_start'

@dataclass
class CutoffConfig:
    cutoff_time: time
    warning_seconds: float = 300.0
    flatten_buffer_seconds: float = 60.0

@dataclass
class ConsistencyConfig:
    max_single_day_pct: float = 30.0

@dataclass
class RiskGuardSnapshot:
    timestamp: datetime
    equity: float
    position_size: float
    watermark: float
    floor: float
    cushion_usd: float
    day_start_equity: float
    day_pnl: float
    daily_loss_used: float
    daily_loss_limit: float
    seconds_to_cutoff: Optional[float]
    consistency_passed: bool
    consistency_top_day_pct: float
    breached: bool
    breach_reason: Optional[str]

class TrailingDrawdownRule:

    def __init__(self, config: TrailingDDConfig, initial_balance: float) -> None:
        self.config = config
        self.initial_balance = initial_balance
        self.watermark = initial_balance
        self.floor = initial_balance - config.max_drawdown
        self.frozen = False

    def cushion(self, equity: float) -> float:
        return equity - self.floor

    def update_peak(self, high_equity: float) -> Optional[GuardEvent]:
        if high_equity > self.watermark and (not self.frozen):
            self.watermark = high_equity
            new_floor = self.watermark - self.config.max_drawdown
            if self.config.lock_at_initial and new_floor >= self.initial_balance + self.config.lock_equity_buffer:
                self.floor = self.initial_balance + self.config.lock_equity_buffer
                self.frozen = True
            else:
                self.floor = new_floor
        return None

    def evaluate(self, tick: RiskTick) -> List[GuardEvent]:
        events = []
        if self.config.mode == 'intraday_peak':
            self.update_peak(tick.equity)
        if tick.equity <= self.floor:
            events.append(GuardEvent(timestamp=tick.timestamp, severity=RiskSeverity.BREACH, rule_name='trailing_drawdown', message=f'Equity ${tick.equity:,.2f} breached trailing floor ${self.floor:,.2f}', details={'equity': tick.equity, 'floor': self.floor, 'watermark': self.watermark}))
        elif self.cushion(tick.equity) <= self.config.max_drawdown * 0.15:
            events.append(GuardEvent(timestamp=tick.timestamp, severity=RiskSeverity.WARN, rule_name='trailing_drawdown', message=f'Low drawdown cushion: ${self.cushion(tick.equity):,.2f} remaining above floor ${self.floor:,.2f}', details={'equity': tick.equity, 'floor': self.floor, 'cushion': self.cushion(tick.equity)}))
        return events

class DailyLossRule:

    def __init__(self, config: DailyLossConfig) -> None:
        self.config = config

    def loss_used(self, day_start_equity: float, current_equity: float) -> float:
        loss = day_start_equity - current_equity
        return max(0.0, loss)

    def evaluate(self, tick: RiskTick, day_start_equity: float) -> List[GuardEvent]:
        events = []
        used = self.loss_used(day_start_equity, tick.equity)
        if used >= self.config.limit:
            events.append(GuardEvent(timestamp=tick.timestamp, severity=RiskSeverity.BREACH, rule_name='daily_loss', message=f'Daily loss ${used:,.2f} exceeded limit ${self.config.limit:,.2f}', details={'used': used, 'limit': self.config.limit, 'day_start': day_start_equity}))
        elif used >= self.config.limit * 0.8:
            events.append(GuardEvent(timestamp=tick.timestamp, severity=RiskSeverity.WARN, rule_name='daily_loss', message=f'Daily loss limit warning: ${used:,.2f} / ${self.config.limit:,.2f} used', details={'used': used, 'limit': self.config.limit}))
        return events

class CutoffRule:

    def __init__(self, config: CutoffConfig) -> None:
        self.config = config
        self._warned = False
        self._flattened = False

    def seconds_to_cutoff(self, ts: datetime) -> float:
        cutoff_dt = datetime.combine(ts.date(), self.config.cutoff_time)
        if ts > cutoff_dt:
            cutoff_dt += timedelta(days=1)
        return (cutoff_dt - ts).total_seconds()

    def evaluate(self, tick: RiskTick) -> List[GuardEvent]:
        events = []
        secs = self.seconds_to_cutoff(tick.timestamp)
        if secs <= self.config.flatten_buffer_seconds and tick.position_size != 0 and (not self._flattened):
            self._flattened = True
            events.append(GuardEvent(timestamp=tick.timestamp, severity=RiskSeverity.FLATTEN, rule_name='cutoff_scrambler', message=f'Market cutoff scramble active ({secs:.0f}s left) - FLATTEN position size {tick.position_size}', details={'position_size': tick.position_size, 'seconds_to_cutoff': secs}))
        elif secs <= self.config.warning_seconds and tick.position_size != 0 and (not self._warned):
            self._warned = True
            events.append(GuardEvent(timestamp=tick.timestamp, severity=RiskSeverity.WARN, rule_name='cutoff_scrambler', message=f'Session cutoff approaching in {secs / 60.0:.1f} minutes', details={'seconds_to_cutoff': secs}))
        return events

    def reset_day(self) -> None:
        self._warned = False
        self._flattened = False

class ConsistencyRule:

    def __init__(self, config: ConsistencyConfig) -> None:
        self.config = config

    def evaluate_pnls(self, completed_pnls: List[float], current_day_pnl: float) -> Tuple[bool, float]:
        all_pnls = [p for p in completed_pnls + [current_day_pnl] if p > 0]
        if not all_pnls:
            return (True, 0.0)
        total_positive_pnl = sum(all_pnls)
        max_day = max(all_pnls)
        top_pct = max_day / total_positive_pnl * 100.0 if total_positive_pnl > 0 else 0.0
        passed = top_pct <= self.config.max_single_day_pct
        return (passed, top_pct)

class PropFirmRiskGuardEngine:

    def __init__(self, initial_balance: float=100000.0, trailing_config: Optional[TrailingDDConfig]=None, daily_loss_config: Optional[DailyLossConfig]=None, cutoff_config: Optional[CutoffConfig]=None, consistency_config: Optional[ConsistencyConfig]=None, news_windows: Optional[List[NewsWindow]]=None) -> None:
        self.initial_balance = initial_balance
        self.trailing_rule = TrailingDrawdownRule(trailing_config or TrailingDDConfig(max_drawdown=5000.0), initial_balance)
        self.daily_rule = DailyLossRule(daily_loss_config or DailyLossConfig(limit=5000.0))
        self.cutoff_rule = CutoffRule(cutoff_config) if cutoff_config else None
        self.consistency_rule = ConsistencyRule(consistency_config or ConsistencyConfig())
        self.news_windows = news_windows or []
        self.completed_day_pnls: List[float] = []
        self.day_start_equity: float = initial_balance
        self.current_date: Optional[date] = None
        self.last_tick: Optional[RiskTick] = None
        self.breached: bool = False
        self.breach_reason: Optional[str] = None
        self.events: List[GuardEvent] = []
        self._news_warned: Set[str] = set()

    def on_tick(self, tick: RiskTick) -> List[GuardEvent]:
        tick_date = tick.timestamp.date()
        if self.current_date is not None and tick_date != self.current_date:
            if self.last_tick:
                day_pnl = self.last_tick.equity - self.day_start_equity
                self.completed_day_pnls.append(day_pnl)
                if self.trailing_rule.config.mode == 'eod_peak':
                    self.trailing_rule.update_peak(self.last_tick.equity)
            self.day_start_equity = tick.equity
            if self.cutoff_rule:
                self.cutoff_rule.reset_day()
            self._news_warned.clear()
        if self.current_date is None:
            self.day_start_equity = tick.equity
        self.current_date = tick_date
        self.last_tick = tick
        new_events: List[GuardEvent] = []
        dd_events = self.trailing_rule.evaluate(tick)
        new_events.extend(dd_events)
        dl_events = self.daily_rule.evaluate(tick, self.day_start_equity)
        new_events.extend(dl_events)
        if self.cutoff_rule:
            cutoff_events = self.cutoff_rule.evaluate(tick)
            new_events.extend(cutoff_events)
        t = tick.timestamp.time()
        for w in self.news_windows:
            if w.start_time <= t <= w.end_time and tick.position_size != 0:
                if w.label not in self._news_warned:
                    self._news_warned.add(w.label)
                    new_events.append(GuardEvent(timestamp=tick.timestamp, severity=RiskSeverity.FLATTEN, rule_name='news_blackout', message=f"Inside news blackout '{w.label}' with active position {tick.position_size} - FLATTEN", details={'position_size': tick.position_size, 'window': w.label}))
        for ev in new_events:
            self.events.append(ev)
            if ev.severity == RiskSeverity.BREACH and (not self.breached):
                self.breached = True
                self.breach_reason = f'{ev.rule_name}: {ev.message}'
        return new_events

    def snapshot(self) -> RiskGuardSnapshot:
        tick = self.last_tick or RiskTick(datetime.now(), self.initial_balance)
        day_pnl = tick.equity - self.day_start_equity
        dl_used = self.daily_rule.loss_used(self.day_start_equity, tick.equity)
        secs_cutoff = self.cutoff_rule.seconds_to_cutoff(tick.timestamp) if self.cutoff_rule else None
        passed_cons, top_pct = self.consistency_rule.evaluate_pnls(self.completed_day_pnls, day_pnl)
        return RiskGuardSnapshot(timestamp=tick.timestamp, equity=tick.equity, position_size=tick.position_size, watermark=self.trailing_rule.watermark, floor=self.trailing_rule.floor, cushion_usd=self.trailing_rule.cushion(tick.equity), day_start_equity=self.day_start_equity, day_pnl=day_pnl, daily_loss_used=dl_used, daily_loss_limit=self.daily_rule.config.limit, seconds_to_cutoff=secs_cutoff, consistency_passed=passed_cons, consistency_top_day_pct=top_pct, breached=self.breached, breach_reason=self.breach_reason)

    def generate_html_report(self) -> str:
        snap = self.snapshot()
        status_color = '#FF3366' if snap.breached else '#00FF66'
        status_text = f'BREACHED: {snap.breach_reason}' if snap.breached else 'PASSING / ACTIVE'
        html = f'<!DOCTYPE html>\n<html>\n<head>\n    <title>EQATS Risk Guard Dashboard</title>\n    <style>\n        body {{ background: #0b0e14; color: #e1e6ed; font-family: monospace; padding: 20px; }}\n        .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 15px; margin-bottom: 15px; }}\n        .status {{ color: {status_color}; font-size: 1.2em; font-weight: bold; }}\n        .metric {{ display: inline-block; width: 45%; margin-bottom: 10px; }}\n        .value {{ color: #58a6ff; font-weight: bold; }}\n    </style>\n</head>\n<body>\n    <h2>Prop Firm Risk Guard Telemetry</h2>\n    <div class="card">\n        <div class="status">Status: {status_text}</div>\n        <hr border="1" color="#30363d"/>\n        <div class="metric">Current Equity: <span class="value">${snap.equity:,.2f}</span></div>\n        <div class="metric">Peak Watermark: <span class="value">${snap.watermark:,.2f}</span></div>\n        <div class="metric">Trailing Floor: <span class="value">${snap.floor:,.2f}</span></div>\n        <div class="metric">Drawdown Cushion: <span class="value">${snap.cushion_usd:,.2f}</span></div>\n        <div class="metric">Day PnL: <span class="value">${snap.day_pnl:,.2f}</span></div>\n        <div class="metric">Daily Loss Used: <span class="value">${snap.daily_loss_used:,.2f} / ${snap.daily_loss_limit:,.2f}</span></div>\n        <div class="metric">Top Day Profit %: <span class="value">{snap.consistency_top_day_pct:.1f}%</span> (Max Allowed: {self.consistency_rule.config.max_single_day_pct}%)</div>\n    </div>\n</body>\n</html>'
        return html
