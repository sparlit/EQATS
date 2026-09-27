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


"""Versioned PAPER execution, promoted from the verified historical exit study."""
from math import floor

from portfolio_accounting.ledger import LedgerConfig, _bar, _summary
from portfolio_accounting.snapshot import number

VARIANTS = ("FIXED_TP2", "TRAIL_STRUCT", "TRAIL_ATR3", "PARTIAL50_STRUCT", "PARTIAL50_ATR3")


def apply_exit(
    state: dict, day: str, bars: dict, candidates: list[dict], config: LedgerConfig, variant="FIXED_TP2"
) -> dict:
    if variant not in VARIANTS:
        msg = "Unknown local exit policy"
        raise ValueError(msg)
    events = []

    def event(kind, trade, **extra):
        events.append({"date": day, "event": kind, "trade_id": trade["trade_id"], "symbol": trade["symbol"], **extra})

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
        elif variant == "FIXED_TP2" and not entry_day and bar["high"] >= p["target2"]:
            if bar.get("exit_blocked"):
                event("EXIT_BLOCKED", p)
                return
            exit_price = p["target2"] * (1 - config.slippage_bps / 10000)
            reason = "TARGET_2"
        elif (
            not entry_day
            and bar["high"] >= p["target1"]
            and not p.get("target1_hit")
            and (variant == "FIXED_TP2" or not bar.get("exit_blocked"))
        ):
            p["target1_hit"] = True
            # The recovered Penny lifecycle moves SL to entry at T1. Ladder's
            # existing implemented lifecycle records T1 only; do not invent a trail.
            if state["scanner"] == "Penny":
                p["stop"] = max(p["stop"], p["entry"])
            if variant.startswith("PARTIAL") and not bar.get("exit_blocked"):
                qty = min(p["remaining_quantity"], p["quantity"] // 2)
                if qty:
                    price = p["target1"] * (1 - config.slippage_bps / 10000)
                    p["realised_pnl"] += qty * (price - p["entry"])
                    p["fees"] += qty * price * config.fee_bps / 10000
                    p["remaining_quantity"] -= qty
                    event("PARTIAL_TP1", p, price=price, quantity=qty)
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
        if state["scanner"] == "Penny" and pending["sessions_waited"] > config.penny_expiry_sessions:
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
        open_risk = sum(p["remaining_quantity"] * max(p["entry"] - p["stop"], 0) for p in state["positions"])
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
        values = {k: number(c[k]) for k in ("entry", "entry_high", "stop", "target1", "target2", "max_stop_pct")}
        if (
            not 0 < values["stop"] < values["entry"] < values["target1"] <= values["target2"]
            or values["entry_high"] < values["entry"]
        ):
            msg = "Invalid candidate geometry"
            raise ValueError(msg)
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
    # New stops are calculated only AFTER this session's exits and entries.
    # They cannot trigger a retrospective intraday exit or fund same-day fills.
    if variant != "FIXED_TP2":
        for p in state["positions"]:
            bar = bars.get(p["symbol"])
            if not p["remaining_quantity"] or p["status"] == "REVIEW" or not bar or bar.get("date") != day:
                continue
            high = max(p["entry"], bar["close"]) if p["entry_date"] == day else bar["high"]
            p["highest_since_entry"] = max(p.get("highest_since_entry", p["entry"]), high)
            if p.get("target1_hit"):
                proposed = (
                    (bar["prior_10_low"] - 0.25 * bar["atr"])
                    if variant.endswith("STRUCT")
                    else (p["highest_since_entry"] - 3 * bar["atr"])
                )
                previous_stop = p["stop"]
                p["stop"] = max(previous_stop, proposed)
                if p["stop"] > previous_stop:
                    event(
                        "TRAIL_FOR_NEXT_SESSION", p, previous_stop=previous_stop, new_stop=p["stop"], context_date=day
                    )
    state["events"].extend(events)
    state["last_date"] = day
    result = _summary(state, day)
    if any(b.get("metadata_available") is False for b in bars.values()):
        result["warnings"].append(
            "Security master unavailable; using the existing scanner gateway fallback for this session."
        )
    if result["available_cash"] < -0.01:
        msg = "New paper ledger cannot borrow cash"
        raise ValueError(msg)
    result["events_today"] = events
    return result
