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


"""Independent one-risk-unit trades for controlled daily-entry experiments.

No pooled-capital claims: simultaneous trades are not sized as a portfolio.
Every variant uses the same exits and costs; revised exits are a separate run.
"""

import math
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ExecutionConfig:
    fee_bps: float = 10.0  # assumption per side, not a broker tariff
    slippage_bps: float = 5.0
    expiry_sessions: int = 5
    cooldown_sessions: int = 5
    max_hold_sessions: int = 66
    max_gap_pct: float = 3.0
    partial_fraction: float = 0.4
    trail: bool = False

    def validate(self):
        if not (0 <= self.fee_bps < 10000 and 0 <= self.slippage_bps < 10000):
            msg = "Invalid execution costs"
            raise ValueError(msg)
        if min(self.expiry_sessions, self.max_hold_sessions) < 1 or self.cooldown_sessions < 0:
            msg = "Invalid session limits"
            raise ValueError(msg)
        if not 0 <= self.partial_fraction < 1 or self.max_gap_pct < 0:
            msg = "Invalid partial fraction or gap limit"
            raise ValueError(msg)


def replay(
    d: pd.DataFrame,
    signals: pd.Series,
    symbol: str,
    *,
    start: str,
    end: str,
    config: ExecutionConfig = ExecutionConfig(),
    session_calendar: list[str] | None = None,
) -> dict:
    """Closed EOD signal -> subsequent OHLC trigger. Stop first if ambiguous.

    Entry-bar MFE/MAE are omitted because intrabar ordering is unknowable.
    Missing symbol sessions cancel pending orders and freeze open positions.
    Large price discontinuities require corporate-action review, not fake profit.
    """
    config.validate()
    selected = d.trade_date.ge(start) & d.trade_date.le(end)
    if not (signals & selected).any():
        return {"trades": [], "open": [], "pending": [], "events": []}
    slip, fee = config.slippage_bps / 10000, config.fee_bps / 10000
    trades, events = [], []
    position = pending = None
    cooldown_until = -1
    calendar = {day: i for i, day in enumerate(session_calendar or d.trade_date.dt.strftime("%Y-%m-%d").tolist())}
    last_session = None
    columns = [
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "valid",
        "deteriorating",
        "support",
        "atr",
        "trigger",
        "stop",
        "setup",
        "weekly_permission",
        "distance_ema_atr",
        "distance_hull_atr",
        "room_known",
        "room_r",
    ]
    if "enforce_room" in d:
        columns.append("enforce_room")
    period = d.loc[selected, columns]
    for index, r in zip(period.index, period.to_dict("records"), strict=False):
        day = pd.Timestamp(r["trade_date"]).date().isoformat()
        if day < start or day > end:
            continue
        session = calendar[day]
        missing = last_session is not None and session != last_session + 1
        last_session = session
        if missing or not r["valid"]:
            pending = None
            if position:
                position["status"] = "REVIEW"
            events.append({"date": day, "reason": "MISSING_OR_INVALID_SESSION"})
        previous_close = float(d.close.iloc[index - 1]) if index else r["open"]
        discontinuity = abs(r["open"] / previous_close - 1) > 0.25
        locked = r["high"] == r["low"]
        if discontinuity:
            pending = None
            if position:
                position["status"] = "REVIEW"
            events.append({"date": day, "reason": "PRICE_DISCONTINUITY_REVIEW"})
        if position and position["status"] == "REVIEW":
            continue
        entered_today = False
        if pending and not position:
            if (
                session - pending["signal_session"] > config.expiry_sessions
                or r["open"] <= pending["stop"]
                or (r["high"] < pending["trigger"] and r["low"] <= pending["stop"])
            ):
                pending = None
            elif not locked and r["high"] >= pending["trigger"]:
                fill = max(r["open"], pending["trigger"]) * (1 + slip)
                risk = fill - pending["stop"]
                gap = abs(r["open"] / previous_close - 1) * 100
                if fill <= pending["entry_cap"] and gap <= config.max_gap_pct and risk > 0 and risk / fill <= 0.08:
                    # Resistance room is rechecked against actual gap/slippage.
                    room = pending.get("resistance")
                    if room is None or (room - fill) / risk >= pending["minimum_room"]:
                        position = {
                            **pending,
                            "symbol": symbol,
                            "entry": fill,
                            "initial_stop": pending["stop"],
                            "risk": risk,
                            "entry_date": day,
                            "entry_session": session,
                            "entry_delay_sessions": session - pending["signal_session"],
                            "entry_premium_pct": (fill / pending["trigger"] - 1) * 100,
                            "remaining": 1.0,
                            "pnl": -fill * fee,
                            "fees": fill * fee,
                            "target1": fill + 1.5 * risk,
                            "target2": fill + 3 * risk,
                            "t1_hit": False,
                            "t2_hit": False,
                            "status": "OPEN",
                            "mfe_r": None,
                            "mae_r": None,
                            "last_price": r["close"],
                        }
                        entered_today = True
                        pending = None
                else:
                    events.append({"date": day, "reason": "GAP_OR_RISK_BLOCKED"})
        if position:
            p = position
            p["last_price"] = r["close"]
            p["mark_date"] = day
            exit_price, reason = None, None
            # Never assume a locked candle provides an executable exit.
            if not locked:
                if p.get("exit_due") and not entered_today:
                    exit_price, reason = r["open"], "TREND_EXIT"
                elif r["low"] <= p["stop"]:
                    exit_price, reason = min(r["open"], p["stop"]), "STOP"
                elif not entered_today:
                    # On stop days, high/low order is unknown. Excursion metrics
                    # conservatively exclude the exit candle entirely.
                    if r["high"] >= p["target2"]:
                        p["t2_hit"] = True
                        exit_price, reason = p["target2"], "TARGET_2"
                    elif session - p["entry_session"] >= config.max_hold_sessions:
                        exit_price, reason = r["close"], "TIME_EXIT"
                    elif config.trail and r["deteriorating"]:
                        # A close-based decision executes at the next open.
                        p["exit_next_open"] = True
                    if exit_price is None:
                        p["mfe_r"] = max(p["mfe_r"] or 0, (r["high"] - p["entry"]) / p["risk"])
                        p["mae_r"] = min(p["mae_r"] or 0, (r["low"] - p["entry"]) / p["risk"])
                    if not p["t1_hit"] and r["high"] >= p["target1"]:
                        fraction = config.partial_fraction
                        price = p["target1"] * (1 - slip)
                        p["pnl"] += fraction * (price - p["entry"]) - fraction * price * fee
                        p["fees"] += fraction * price * fee
                        p["remaining"] -= fraction
                        p["t1_hit"] = True
                        if config.trail:
                            p["stop"] = max(p["stop"], p["entry"])
            if exit_price is not None:
                price = exit_price * (1 - slip)
                p["pnl"] += p["remaining"] * (price - p["entry"]) - p["remaining"] * price * fee
                p["fees"] += p["remaining"] * price * fee
                p.update(
                    exit_date=day,
                    exit_price=price,
                    exit_reason=reason,
                    status="CLOSED",
                    net_r=p["pnl"] / p["risk"],
                    holding_sessions=session - p["entry_session"],
                    giveback_r=None if p["mfe_r"] is None else max(0, p["mfe_r"] - p["pnl"] / p["risk"]),
                )
                trades.append(p)
                position = None
                cooldown_until = session + config.cooldown_sessions
            elif config.trail and not entered_today:
                # Today's calculated stop can only apply from the next session.
                structural = r["support"] - 0.2 * r["atr"]
                if math.isfinite(structural) and structural < r["close"]:
                    p["stop"] = max(p["stop"], structural)
                p["exit_due"] = p.get("exit_due", False) or p.pop("exit_next_open", False)
        if (
            not position
            and not pending
            and session > cooldown_until
            and not missing
            and not discontinuity
            and not locked
            and bool(signals.iloc[index])
        ):
            pending = {
                "signal_date": day,
                "signal_session": session,
                "trigger": r["trigger"],
                "entry_cap": r["trigger"] + 0.5 * r["atr"],
                "stop": r["stop"],
                "setup": r["setup"],
                "weekly_permission": r["weekly_permission"],
                "distance_ema_atr": r["distance_ema_atr"],
                "distance_hull_atr": r["distance_hull_atr"],
                "resistance": None,
                "minimum_room": 0.0,
            }
            # Optional mask marks the variants that enforce room; control arms
            # must not accidentally inherit the experimental location filter.
            if bool(r.get("enforce_room", False)) and r["room_known"]:
                pending["resistance"] = r["trigger"] + r["room_r"] * (r["trigger"] - r["stop"])
                pending["minimum_room"] = 1.5
    return {
        "trades": trades,
        "open": [position] if position else [],
        "pending": [pending] if pending else [],
        "events": events,
    }


def metrics(trades: list[dict], value_key: str = "net_r") -> dict:
    values = [float(t[value_key]) for t in trades if t.get(value_key) is not None]
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    n = len(values)
    gross_profit, gross_loss = sum(wins), -sum(losses)
    average_win = gross_profit / len(wins) if wins else None
    average_loss = gross_loss / len(losses) if losses else None
    # Wilson interval prevents small samples from looking like reliable edges.
    interval = None
    if n:
        z, p = 1.96, len(wins) / n
        center = (p + z * z / (2 * n)) / (1 + z * z / n)
        radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        interval = [100 * (center - radius), 100 * (center + radius)]

    def average(key):
        v = [t[key] for t in trades if t.get(key) is not None]
        return sum(v) / len(v) if v else None

    return {
        "closed_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": n - len(wins) - len(losses),
        "win_rate_pct": 100 * len(wins) / n if n else None,
        "win_rate_95pct_interval": interval,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net": sum(values),
        "average_winner": average_win,
        "average_loser_abs": average_loss,
        "payoff_ratio": average_win / average_loss if average_win is not None and average_loss else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "expectancy": sum(values) / n if n else None,
        "average_holding_sessions": average("holding_sessions"),
        "average_entry_delay_sessions": average("entry_delay_sessions"),
        "average_entry_premium_pct": average("entry_premium_pct"),
        "average_mfe_r_lower_bound": average("mfe_r"),
        "average_mae_r_partial": average("mae_r"),
        "average_giveback_r_estimate": average("giveback_r"),
        "t1_hits": sum(bool(t.get("t1_hit")) for t in trades),
        "t2_hits": sum(bool(t.get("t2_hit")) for t in trades),
        "exit_reasons": pd.Series([t.get("exit_reason", "UNKNOWN") for t in trades], dtype=str)
        .value_counts()
        .to_dict(),
        "portfolio_max_drawdown": None,
        "portfolio_drawdown_status": "NOT A CAPITAL-CONSTRAINED PORTFOLIO",
    }
