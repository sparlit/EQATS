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


"""Settle hypothesis trades based on horizon/stop rules.

Reads open trades, fetches current price, closes if horizon exceeded or stop hit.

Usage:
    python scripts/hypothesis_settle.py [--hypothesis NAME] [--dry-run]
"""


import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yfinance as yf
from indian_quant.config.connections import get_engine
from indian_quant.hypotheses import DeliveryMomentum
from indian_quant.hypotheses.registry import HypothesisRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def get_current_price(symbol: str) -> float | None:
    """Fetch current price via yfinance."""
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(period="1d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def run_settle(registry: HypothesisRegistry, hypothesis_name: str | None = None, dry_run: bool = False) -> dict:
    """Settle open trades for one or all hypotheses."""
    get_engine()
    today = date.today()
    results = {}

    open_trades = registry.open_trades()
    if hypothesis_name:
        # Filter by hypothesis name
        hypo_row = registry.get(hypothesis_name)
        if not hypo_row:
            log.error(f"Hypothesis '{hypothesis_name}' not found")
            return {}
        hypo_id = hypo_row["id"]
        open_trades = [t for t in open_trades if t["hypothesis_id"] == hypo_id]

    log.info(f"Open trades to evaluate: {len(open_trades)}")

    for trade in open_trades:
        symbol = trade["symbol"]
        entry_date = trade["entry_date"]
        entry_price = trade["entry_price"]
        stop_pct = trade["stop_pct"] or 0.07
        horizon_days = trade["horizon_days"] or 10
        trade_id = trade["id"]
        hypo_id = trade["hypothesis_id"]

        # Calculate days held
        if isinstance(entry_date, str):
            entry_dt = datetime.strptime(str(entry_date)[:10], "%Y-%m-%d").date()
        else:
            entry_dt = entry_date
        days_held = (today - entry_dt).days

        # Get current price
        current_price = get_current_price(symbol)
        if current_price is None:
            log.warning(f"  Could not fetch price for {symbol}, skipping")
            continue

        # Determine exit reason
        exit_reason = None
        stop_price = entry_price * (1 - stop_pct)
        target_price = entry_price * (1 + stop_pct * 2)

        if current_price <= stop_price:
            exit_reason = "STOP"
        elif current_price >= target_price:
            exit_reason = "TARGET"
        elif days_held >= horizon_days:
            exit_reason = "HORIZON"

        if exit_reason is None:
            continue

        log.info(
            f"  {symbol}: {exit_reason} | entry={entry_price} current={current_price} "
            f"days={days_held} stop={stop_price}"
        )

        if dry_run:
            results[symbol] = {"exit_reason": exit_reason, "current_price": current_price}
            continue

        # Close the trade
        result = registry.close_trade(
            trade_id=trade_id,
            exit_date=str(today),
            exit_price=current_price,
            exit_reason=exit_reason,
            notes=f"Auto-settled: {exit_reason}, days_held={days_held}",
        )
        net_bps = result.get("net_bps", 0)
        log.info(f"    Closed: net_bps={net_bps:.1f}")
        results[symbol] = {"exit_reason": exit_reason, "net_bps": net_bps}

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle hypothesis trades")
    parser.add_argument("--hypothesis", help="Settle only this hypothesis")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()

    engine = get_engine()
    registry = HypothesisRegistry(engine)

    results = run_settle(registry, hypothesis_name=args.hypothesis, dry_run=args.dry_run)
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
