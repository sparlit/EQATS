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


"""Independent Old NSE discovery and EOD Hull PAPER scanner.

The Python Hull rules are the operating rules for this system. They are not
presented as a TradingView/Pine export or a live-trading instruction.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from v2.database import V2Database
from v2.tradeability import evaluate_tradeability
from v2.tradeability import summarize as summarize_tradeability

from .discovery import discover, load_market_data
from .multi_horizon.config import shadow_enabled
from .multi_horizon.engine import run_shadow


def _wma(series: pd.Series, length: int) -> pd.Series:
    weights = list(range(1, length + 1))
    return series.rolling(length).apply(lambda values: float((values * weights).sum() / sum(weights)), raw=True)


def _hma(series: pd.Series, length: int) -> pd.Series:
    return _wma(2 * _wma(series, length // 2) - _wma(series, length), int(length**0.5))


def _tradeable_prices(prices: pd.DataFrame, db_path: str | Path) -> tuple[pd.DataFrame, dict]:
    """Apply the common current-security gate before either Old+Hull path.

    The Old+Hull system retains independent PAPER scoring and state; it only
    shares the read-only universe safety gate used by the other scanners.
    """
    if prices.empty:
        return prices, {"evaluated": 0, "eligible": 0, "rejected": 0}
    trade_date = pd.Timestamp(prices["trade_date"].max()).date().isoformat()
    database = V2Database(db_path)
    master = database.load_symbol_master(trade_date)
    metadata = {str(row["symbol"]): row.to_dict() for _, row in master.iterrows()} if not master.empty else {}
    restricted = database.load_restricted_symbols(trade_date)
    lifecycle_registry = database.load_lifecycle_registry()
    session_calendar = tuple(sorted(pd.to_datetime(prices["trade_date"]).dt.date.astype(str).unique()))
    gateway = {
        str(symbol): evaluate_tradeability(
            str(symbol),
            frame,
            market_date=trade_date,
            master_row=metadata.get(str(symbol)),
            restricted_reason=restricted.get(str(symbol)),
            lifecycle_event=lifecycle_registry.get(str(symbol)),
            session_calendar=session_calendar,
            require_metadata=bool(metadata),
        )
        for symbol, frame in prices.groupby("symbol", sort=True)
    }
    allowed = {symbol for symbol, result in gateway.items() if result.eligible and not result.entry_blocked}
    return prices[prices["symbol"].astype(str).isin(allowed)].copy(), summarize_tradeability(gateway)


def alignment(frame: pd.DataFrame) -> dict:
    """Reduced EOD Hull confirmation: visual alignment, not Pine parity."""
    data = frame.sort_values("trade_date").copy()
    close = pd.to_numeric(data["close"], errors="coerce")
    daily_fast, daily_slow = _hma(close, 21), _hma(close, 51)
    states = {
        "daily": bool(
            close.iloc[-1] > daily_slow.iloc[-1]
            and daily_fast.iloc[-1] > daily_slow.iloc[-1]
            and daily_fast.iloc[-1] > daily_fast.iloc[-2]
        )
    }
    indexed = data.set_index("trade_date")["close"]
    for label, rule in {"weekly": "W-FRI", "monthly": "ME", "3m": "QE", "6m": "2QE"}.items():
        series = indexed.resample(rule).last().dropna()
        if len(series) < 3:
            states[label] = False
            continue
        fast = _hma(series, min(3, max(2, len(series) // 2)))
        slow = _hma(series, min(5, max(3, len(series) - 1)))
        states[label] = bool(
            pd.notna(fast.iloc[-1])
            and pd.notna(slow.iloc[-1])
            and fast.iloc[-1] > slow.iloc[-1]
            and fast.iloc[-1] >= fast.iloc[-2]
        )
    aligned_count = sum(states.values())
    confirmed = bool(states["daily"] and aligned_count >= 3)
    return {
        "timeframes": states,
        "aligned_count": aligned_count,
        "aligned": confirmed,
        "state": "CONFIRMING" if confirmed else "WATCH",
    }


def run_local(
    db_path: str = "nse_scanner.db",
    as_of: str | None = None,
    top_n: int = 25,
    comparison_state_path: str | Path | None = None,
    paper_state_path: str | Path | None = None,
) -> dict:
    """Run the frozen baseline; optionally attach a non-delivered shadow comparison."""
    prices = load_market_data(db_path, as_of)
    prices, tradeability = _tradeable_prices(prices, db_path)
    result = discover(prices, top_n=top_n)
    rows = result.shortlist.to_dict(orient="records")
    frames = dict(prices.groupby("symbol"))
    for row in rows:
        confirmation = alignment(frames[row["symbol"]])
        ready = bool(row["discovery_score"] >= 75 and confirmation["aligned"])
        row.update(
            {
                "hull_state": "READY" if ready else confirmation["state"],
                "timeframes": confirmation["timeframes"],
                "paper_entry_enabled": ready,
                "reason": "python_hull_rules_active",
            }
        )
    report = {
        "system": "OLD_NSE_HULL_PAPER",
        "generated_at": datetime.now().astimezone().isoformat(),
        "as_of_date": result.as_of_date,
        "parity": "PYTHON_RULES_ACTIVE",
        "paper_entries_enabled": True,
        "eligible": result.eligible,
        "discovery_qualified": len(rows),
        "ready": sum(r["hull_state"] == "READY" for r in rows),
        "watch": sum(r["hull_state"] == "WATCH" for r in rows),
        "rejected": result.rejected,
        "shortlist": rows,
        "state": "PAPER_EOD_ACTIVE",
        "tradeability": tradeability,
    }
    if shadow_enabled():
        # The report artifact is the comparison surface during the 20-session
        # evaluation. It never changes the baseline shortlist or Telegram UX.
        report["multi_horizon_shadow"] = run_shadow(
            prices, db_path, [row["symbol"] for row in rows], comparison_state_path, paper_state_path
        )
    return report


def render_radar(report: dict) -> str:
    lines = [
        "🪜 <b>OLD NSE + HULL — DAILY WATCHLIST</b>",
        "<b>SIMULATED WATCHLIST • NO LIVE ORDERS</b>",
        f"<b>Data:</b> {report.get('as_of_date') or 'N/A'} EOD",
        "",
        f"Stocks checked: {report['eligible']} | Setups found: {report['discovery_qualified']}",
        f"🟢 Watch for entry: {report['ready']} | 🟡 Wait for confirmation: {report['watch']}",
        "A watchlist is not a position. It becomes a simulated position only after the next-session trigger.",
    ]
    if report["shortlist"]:
        lines.extend(["", "<b>Today’s watchlist</b>"])
        for row in report["shortlist"][:10]:
            label = "Watch for entry" if row.get("hull_state") == "READY" else "Watchlist—wait for confirmation"
            signals = ", ".join(str(item).replace("_", " ") for item in row.get("early_signals", ())[:2])
            reason = (
                signals.replace("price accelerating", "price is improving").replace(
                    "relative strength accelerating", "strength versus peers is improving"
                )
                or "price structure is improving"
            )
            close, atr = float(row.get("close") or 0), float(row.get("atr14") or 0)
            entry = (
                f"₹{max(0.01, close + 0.10 * atr):,.2f}–₹{max(0.01, close + 0.25 * atr):,.2f}"
                if close > 0 and atr > 0
                else "Set after confirmation"
            )
            symbol = row["symbol"]
            url = f"https://www.tradingview.com/chart/?symbol=NSE%3A{symbol}"
            icon = "🟢" if row.get("hull_state") == "READY" else "🟡"
            lines.extend(
                [
                    "",
                    "━━━━━━━━━━━━━━",
                    f'{icon} <b><a href="{url}">{symbol}</a> • {label} • {row["discovery_score"]:.0f}/100</b>',
                    f"CMP ₹{close:,.2f}" if close else "CMP unavailable",
                    f"Planned entry: {entry}",
                    f"Why it is here: {reason}",
                    "Next: Wait for the next trading day’s confirmation.",
                ]
            )
    return "\n".join(lines)


def render_paper_trades(report: dict) -> str:
    """Compatibility text for a portfolio topic before a baseline lifecycle exists."""
    return "\n".join(
        [
            "💼 <b>OLD NSE + HULL — PORTFOLIO</b>",
            "SIMULATED PORTFOLIO • NO LIVE ORDERS",
            f"Data: {report.get('as_of_date') or 'N/A'} EOD",
            "",
            "No simulated positions are being tracked for this baseline yet.",
            "Today’s candidates are in the Daily Watchlist; a watchlist item is not a portfolio position.",
        ]
    )


def render_period_report(report: dict, period: str, shadow_summary: dict | None = None) -> str:
    title = "WEEKLY SUMMARY" if period == "weekly" else "MONTHLY SUMMARY"
    lines = [
        f"📅 <b>OLD NSE + HULL — {title}</b>",
        "SIMULATED WATCHLIST • NO LIVE ORDERS",
        f"Latest data: {report.get('as_of_date') or 'N/A'} EOD",
        "",
        f"Setups found: {report['discovery_qualified']}",
        f"Watch for entry: {report['ready']} | Wait for confirmation: {report['watch']}",
        "",
        "Portfolio status: no baseline simulated lifecycle has started yet.",
        "Next: Use the daily watchlist for new setups. Technical model comparison is reported separately.",
    ]
    return "\n".join(lines)


def render_validation_report(summary: dict | None) -> str:
    """Keep experimental model comparison out of the normal user watchlist."""
    summary = summary or {}
    observed, target = summary.get("sessions_observed", 0), summary.get("target_sessions", 20)
    remaining = max(0, target - observed)
    status = "Ready for manual review" if summary.get("validation_ready") else "Still collecting evidence"
    return "\n".join(
        [
            "⚙️ <b>OLD NSE + HULL — SYSTEM VALIDATION</b>",
            "ADMINISTRATIVE COMPARISON • NOT A WATCHLIST",
            "",
            f"Observation progress: {observed}/{target} trading sessions ({remaining} remaining)",
            f"Average setups: baseline {summary.get('average_baseline_candidates', 0)} | experimental model {summary.get('average_shadow_candidates', 0)}",
            f"Average overlap: {summary.get('average_overlap', 0)}",
            "",
            f"Status: <b>{status}</b>",
            "What this means: this checks whether the experimental model agrees with the main watchlist. It does not change entries or create orders.",
        ]
    )


def save_report(report: dict, output: str | Path) -> None:
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2), encoding="utf-8")
