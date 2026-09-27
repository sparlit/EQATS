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


"""Live paper trading update — mark-to-market open positions via Upstox.

Fetches live LTP for all OPEN paper positions, evaluates stop/target/horizon
exit rules and settles hits via the registry. Reports unrealized P&L.

Usage:
    python scripts/live_paper_update.py [--dry-run]
"""


import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sqlalchemy as sa
from indian_quant.config.connections import get_engine
from indian_quant.hypotheses.registry import HypothesisRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def get_upstox_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch live LTP via Upstox for the given symbols."""
    import httpx
    import pandas as pd
    from indian_quant.config.settings import UpstoxConfig

    uc = UpstoxConfig()
    token = uc.resolve_token()
    if not token:
        log.warning("No Upstox token available")
        return {}

    master_path = Path("data/upstox_master.csv.gz")
    if not master_path.exists():
        log.warning("Upstox master file missing")
        return {}

    master = pd.read_csv(master_path, compression="gzip", dtype=str)
    nse = master[master["exchange"] == "NSE_EQ"]
    sym_to_key = dict(zip(nse["tradingsymbol"], nse["instrument_key"], strict=False))

    keys = [sym_to_key[s] for s in symbols if s in sym_to_key]
    missing = [s for s in symbols if s not in sym_to_key]
    if missing:
        log.warning(f"No Upstox instrument key for: {', '.join(missing)}")

    prices: dict[str, float] = {}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    for i in range(0, len(keys), 500):
        batch = keys[i : i + 500]
        try:
            resp = httpx.get(
                "https://api.upstox.com/v2/market-quote/quotes",
                params={"instrument_key": ",".join(batch)},
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                for key, val in resp.json().get("data", {}).items():
                    if isinstance(val, dict) and val.get("last_price"):
                        parts = key.split(":")
                        sym = parts[-1] if len(parts) > 1 else key
                        prices[sym] = float(val["last_price"])
            else:
                log.warning(f"Upstox batch {i}: HTTP {resp.status_code}")
        except Exception as e:
            log.warning(f"Upstox batch {i} failed: {e}")
    return prices


def main() -> int:
    parser = argparse.ArgumentParser(description="Live paper trading mark-to-market + settle")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = get_engine()
    registry = HypothesisRegistry(engine)
    today = date.today()

    with engine.connect() as conn:
        open_rows = (
            conn.execute(
                sa.text("""
            SELECT id, hypothesis_id, symbol, entry_date, close_at_signal,
                   stop_pct, horizon_days
            FROM paper_signals WHERE status = 'OPEN'
        """)
            )
            .mappings()
            .fetchall()
        )

    if not open_rows:
        log.info("No open paper positions")
        return 0

    symbols = sorted({r["symbol"] for r in open_rows})
    prices = get_upstox_prices(symbols)
    log.info(f"Live prices for {len(prices)}/{len(symbols)} symbols from Upstox")

    settled, held = 0, 0
    for t in open_rows:
        sym = t["symbol"]
        entry = float(t["close_at_signal"])
        stop_pct = float(t["stop_pct"] or 0.05)
        horizon = int(t["horizon_days"] or 15)
        price = prices.get(sym)

        if price is None:
            log.info(f"  {sym} (hypo{t['hypothesis_id']}): no live price, holding")
            continue

        pct = (price / entry - 1) * 100
        try:
            ed = datetime.strptime(str(t["entry_date"])[:10], "%Y-%m-%d").date()
            days_held = (today - ed).days
        except Exception:
            days_held = 0

        stop_price = entry * (1 - stop_pct)
        target_price = entry * (1 + stop_pct * 2)
        exit_reason = None
        if price <= stop_price:
            exit_reason = "STOP"
        elif price >= target_price:
            exit_reason = "TARGET"
        elif days_held >= horizon:
            exit_reason = "HORIZON"

        if exit_reason:
            log.info(
                f"  {sym} (hypo{t['hypothesis_id']}): {exit_reason} "
                f"entry=₹{entry:.2f} live=₹{price:.2f} ({pct:+.1f}%) days={days_held}"
            )
            if args.dry_run:
                settled += 1
                continue
            registry.close_trade(
                trade_id=t["id"],
                exit_date=str(today),
                exit_price=price,
                exit_reason=exit_reason,
                notes=f"Live update: {exit_reason}, days_held={days_held}",
            )
            settled += 1
        else:
            held += 1
            log.info(
                f"  {sym} (hypo{t['hypothesis_id']}): HOLD entry=₹{entry:.2f} "
                f"live=₹{price:.2f} ({pct:+.1f}%) days={days_held}/{horizon}"
            )

    log.info(f"Settled: {settled}, Holding: {held}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
