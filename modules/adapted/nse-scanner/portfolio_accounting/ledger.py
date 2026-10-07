from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""Transactional, restart-safe Penny/Ladder PAPER fills and cash accounting.

SQLite holds the complete state and immutable session inputs in one transaction.
This ledger never imports a broker or Telegram client. It starts a new explicitly
labelled accounting cohort; legacy event-only positions are not invented fills.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import floor
from pathlib import Path

from .snapshot import build_snapshot, number


@dataclass(frozen=True)
class LedgerConfig:
    capital: float = 300_000.0
    risk_fraction: float = 0.01
    max_position_fraction: float = 0.20
    max_total_risk_fraction: float = 0.05
    max_open: int = 8
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    max_gap_pct: float = 3.0
    penny_expiry_sessions: int = 5

    def validate(self):
        for value in asdict(self).values():
            number(value)
        if self.capital <= 0 or self.max_open < 1 or self.penny_expiry_sessions < 1:
            raise ValueError("Invalid ledger capacity")
        if not all(
            0 < value <= 1
            for value in (
                self.risk_fraction,
                self.max_position_fraction,
                self.max_total_risk_fraction,
            )
        ):
            raise ValueError("Invalid allocation fraction")
        if min(self.fee_bps, self.slippage_bps, self.max_gap_pct) < 0 or self.slippage_bps >= 10000:
            raise ValueError("Invalid execution cost")


def _summary(state: dict, day: str) -> dict:
    return build_snapshot(
        state["scanner"],
        day,
        state["config"]["capital"],
        state["positions"],
        state["pending"],
        legacy=state["legacy"],
        provenance=state["provenance"],
        execution_model="NEXT_SESSION_OHLC_STOP_FIRST_V1",
    )


def _bar(raw: dict | None, day: str) -> dict | None:
    if not raw or str(raw.get("date")) != day:
        return None
    values = {k: number(raw[k]) for k in ("open", "high", "low", "close")}
    if (
        min(values.values()) <= 0
        or not values["low"]
        <= min(values["open"], values["close"])
        <= max(values["open"], values["close"])
        <= values["high"]
    ):
        raise ValueError("Invalid OHLC bar")
    return {**raw, **values}


def _apply(state: dict, day: str, bars: dict, candidates: list[dict], config: LedgerConfig) -> dict:
    events = []

    def event(kind, trade, **extra):
        events.append(
            {
                "date": day,
                "event": kind,
                "trade_id": trade["trade_id"],
                "symbol": trade["symbol"],
                **extra,
            }
        )

    def manage(p, bar, *, entry_day=False):
        p.update(last_price=bar["close"], mark_date=day)
        if bar.get("review_required"):
            p["status"] = "REVIEW"
            event("REVIEW_REQUIRED", p)
            return
        # Do not automatically resume a holding frozen for a corporate action.
        if p["status"] == "REVIEW":
            return
        exit_price, reason = None, None
        if bar["low"] <= p["stop"]:
            if bar.get("exit_blocked"):
                event("EXIT_BLOCKED", p)
                return
            exit_price = min(bar["open"], p["stop"]) * (1 - config.slippage_bps / 10000)
            reason = "STOP"
        # On an entry bar, target/entry order is unknown. Only adverse fills are
        # modelled; no favourable same-bar target proceeds are manufactured.
        elif not entry_day and bar["high"] >= p["target2"]:
            if bar.get("exit_blocked"):
                event("EXIT_BLOCKED", p)
                return
            exit_price = p["target2"] * (1 - config.slippage_bps / 10000)
            reason = "TARGET_2"
        elif not entry_day and bar["high"] >= p["target1"] and not p.get("target1_hit"):
            p["target1_hit"] = True
            # The recovered Penny lifecycle moves SL to entry at T1. Ladder's
            # existing implemented lifecycle records T1 only; do not invent a trail.
            if state["scanner"] == "Penny":
                p["stop"] = max(p["stop"], p["entry"])
            event("TARGET_1", p)
        if exit_price is not None:
            qty = p["remaining_quantity"]
            p["realised_pnl"] += qty * (exit_price - p["entry"])
            p["fees"] += qty * exit_price * config.fee_bps / 10000
            p.update(remaining_quantity=0, exit_price=exit_price, exit_date=day, status="CLOSED")
            event(reason, p, price=exit_price, quantity=qty)

    for p in state["positions"]:
        if p["remaining_quantity"]:
            bar = _bar(bars.get(p["symbol"]), day)
            if bar:
                manage(p, bar)

    survivors = []
    for pending in state["pending"]:
        pending["sessions_waited"] += 1
        if (
            state["scanner"] == "Penny"
            and pending["sessions_waited"] > config.penny_expiry_sessions
        ):
            event("EXPIRED", pending)
            continue
        bar = _bar(bars.get(pending["symbol"]), day)
        if not bar or not bar.get("entry_allowed", False) or bar.get("entry_blocked"):
            survivors.append(pending)
            continue
        entry, cap = pending["entry"], pending["entry_high"]
        if bar["high"] < entry:
            survivors.append(pending)
            continue
        fill = max(bar["open"], entry) * (1 + config.slippage_bps / 10000)
        previous = number(bar.get("prev_close"), default=bar["open"])
        gap = abs(bar["open"] / previous - 1) * 100 if previous > 0 else float("inf")
        if fill > cap or gap > config.max_gap_pct or fill >= pending["target1"]:
            event("ENTRY_GAP_BLOCKED", pending)
            survivors.append(pending)
            continue
        risk = fill - pending["stop"]
        if risk <= 0 or risk / fill * 100 > pending["max_stop_pct"]:
            event("ENTRY_RISK_BLOCKED", pending)
            survivors.append(pending)
            continue
        snapshot = _summary(state, day)
        open_risk = sum(
            p["remaining_quantity"] * max(p["entry"] - p["stop"], 0) for p in state["positions"]
        )
        quantity = max(
            0,
            min(
                floor(config.capital * config.risk_fraction / risk),
                floor(config.capital * config.max_position_fraction / fill),
                floor(max(0, snapshot["available_cash"]) / (fill * (1 + config.fee_bps / 10000))),
                floor(max(0, config.capital * config.max_total_risk_fraction - open_risk) / risk),
            ),
        )
        if snapshot["open_positions"] >= config.max_open or quantity < 1:
            event("CAPACITY_BLOCKED", pending)
            survivors.append(pending)
            continue
        p = {
            **pending,
            "entry": fill,
            "initial_stop": pending["stop"],
            "entry_date": day,
            "quantity": quantity,
            "remaining_quantity": quantity,
            "realised_pnl": 0.0,
            "fees": quantity * fill * config.fee_bps / 10000,
            "status": "OPEN",
            "last_price": bar["close"],
            "mark_date": day,
        }
        state["positions"].append(p)
        event("ENTRY", p, price=fill, quantity=quantity)
        manage(p, bar, entry_day=True)
    state["pending"] = survivors
    active = {p["symbol"] for p in state["positions"] if p["remaining_quantity"]}
    active.update(p["symbol"] for p in state["pending"])
    closed_today = {p["symbol"] for p in state["positions"] if p.get("exit_date") == day}
    for c in sorted(candidates, key=lambda r: (-number(r.get("score"), default=0), r["symbol"])):
        if c["symbol"] in active or c["symbol"] in closed_today:
            continue
        if len(active) >= config.max_open:
            break
        values = {
            k: number(c[k])
            for k in ("entry", "entry_high", "stop", "target1", "target2", "max_stop_pct")
        }
        if (
            not 0 < values["stop"] < values["entry"] < values["target1"] <= values["target2"]
            or values["entry_high"] < values["entry"]
        ):
            raise ValueError("Invalid candidate geometry")
        identity = f"{state['scanner']}:{c['symbol']}:{day}"
        p = {
            **c,
            **values,
            "trade_id": identity,
            "created_date": day,
            "sessions_waited": 0,
            "status": "PENDING",
            "reserved_capital": 0.0,
        }
        state["pending"].append(p)
        active.add(c["symbol"])
        event("PENDING", p)
    state["events"].extend(events)
    state["last_date"] = day
    result = _summary(state, day)
    if any(b.get("metadata_available") is False for b in bars.values()):
        result["warnings"].append(
            "Security master unavailable; using the existing scanner gateway fallback for this session."
        )
    if result["available_cash"] < -0.01:
        raise ValueError("New paper ledger cannot borrow cash")
    result["events_today"] = events
    return result


def advance(
    path: str | Path,
    scanner: str,
    day: str,
    bars: dict,
    candidates: list[dict],
    *,
    config: LedgerConfig = LedgerConfig(),
    legacy: list[dict] | None = None,
    provenance: str = "FORWARD_PAPER_COHORT",
    previous_session: str | None = None,
) -> dict:
    """A date is immutable: identical retries return its stored report.

    Different inputs for an already completed date fail rather than replaying
    fills or silently repricing history. One database contains one scanner only.
    """
    if scanner not in {"Penny", "Momentum Ladder"}:
        raise ValueError("Only Penny and Ladder use this new lifecycle")
    from datetime import date

    date.fromisoformat(day)
    config.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "bars": bars,
            "candidates": candidates,
            "config": asdict(config),
            "scanner": scanner,
            "provenance": provenance,
        },
        sort_keys=True,
        allow_nan=False,
    )
    digest = sha256(payload.encode()).hexdigest()
    with sqlite3.connect(target, timeout=30) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions (day TEXT PRIMARY KEY, digest TEXT NOT NULL, report TEXT NOT NULL)"
        )
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT digest, report FROM sessions WHERE day=?", (day,)
        ).fetchone()
        if existing:
            if existing[0] != digest:
                raise ValueError(
                    "Completed session inputs changed; use a separate reconstruction ledger"
                )
            return json.loads(existing[1])
        stored = conn.execute("SELECT payload FROM ledger WHERE id=1").fetchone()
        state = (
            json.loads(stored[0])
            if stored
            else {
                "scanner": scanner,
                "config": asdict(config),
                "positions": [],
                "pending": [],
                "events": [],
                "last_date": None,
                "legacy": legacy or [],
                "provenance": provenance,
            }
        )
        if (
            state["scanner"] != scanner
            or state["config"] != asdict(config)
            or state["provenance"] != provenance
        ):
            raise ValueError("Ledger identity/configuration cannot change")
        if state["last_date"] and day <= state["last_date"]:
            raise ValueError("Cannot append an older session")
        if state["last_date"] and previous_session and state["last_date"] != previous_session:
            raise ValueError("Missing market session; replay the missing dates before advancing")
        result = _apply(state, day, bars, candidates, config)
        conn.execute(
            "INSERT OR REPLACE INTO ledger VALUES (1,?)", (json.dumps(state, allow_nan=False),)
        )
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?)",
            (day, digest, json.dumps(result, allow_nan=False)),
        )
        return result
