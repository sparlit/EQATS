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


"""Add top surveillance stocks to paper trading.

Selects high-strength surveillance signals with market cap > ₹1000 Cr
and opens paper positions using the same risk management as paper_track.py.

Usage:
    python scripts/surveillance_paper_trade.py [--dry-run] [--top N] [--capital 100000]
"""


import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datetime import date

import sqlalchemy as sa
import yfinance as yf
from indian_quant.config.connections import get_engine
from indian_quant.portfolio.kelly import dynamic_kelly_params, kelly_fraction, kelly_position
from indian_quant.storage.pg_metadata import PgMetadataStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Surveillance trading config — separate portfolio from delivery momentum
HORIZONS = [
    {"days": 15, "label": "15d", "stop_pct": 0.05, "capital_pct": 0.25},
]
MIN_STRENGTH = 65
MIN_MCAP = 1000  # ₹1000 Cr minimum market cap
MAX_SURVEILLANCE_POSITIONS = 7  # Cap per hypothesis portfolio (top 7)
CAPITAL = 100_000  # ₹1L per position pool


def get_top_signals(engine, top_n: int = 10) -> list[dict]:
    """Get top surveillance signals with market cap filter."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
            SELECT sig.symbol, sig.signal_type, sig.strength, sig.price,
                   sig.ret_1m, sig.ret_3m, sig.vol_20d,
                   c.market_cap_cr, c.sector, c.close as cached_close
            FROM surveillance_signals sig
            JOIN cached_signals c ON sig.symbol = c.symbol
            WHERE sig.signal_date = (SELECT MAX(signal_date) FROM surveillance_signals)
              AND sig.strength >= :min_strength
              AND c.market_cap_cr >= :min_mcap
              AND sig.signal_type != 'avoid'
            ORDER BY sig.strength DESC
            LIMIT :top_n
        """),
            {"min_strength": MIN_STRENGTH, "min_mcap": MIN_MCAP, "top_n": top_n},
        ).fetchall()

        return [
            {
                "symbol": r[0],
                "signal_type": r[1],
                "strength": r[2],
                "price": r[3],
                "ret_1m": r[4],
                "ret_3m": r[5],
                "vol_20d": r[6],
                "mcap": r[7],
                "sector": r[8],
                "cached_close": r[9],
            }
            for r in rows
        ]


def get_current_price(symbol: str) -> float | None:
    """Get latest price via yfinance."""
    try:
        data = yf.download(f"{symbol}.NS", period="5d", progress=False)
        close = data["Close"].squeeze()
        if hasattr(close, "iloc"):
            return float(close.iloc[-1])
        return float(close)
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Add surveillance stocks to paper trading")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--top", type=int, default=7, help="Top N signals to trade")
    parser.add_argument("--capital", type=float, default=CAPITAL, help="Capital per position")
    args = parser.parse_args()

    engine = get_engine()
    signals = get_top_signals(engine, args.top)

    if not signals:
        print("No qualifying surveillance signals found")
        return 0

    print("\n=== SURVEILLANCE PAPER TRADE ===")
    print(f"Criteria: strength >= {MIN_STRENGTH}, mcap >= ₹{MIN_MCAP}Cr")
    print(f"Found {len(signals)} qualifying signals\n")

    if args.dry_run:
        print("DRY RUN — no positions opened\n")

    metadata = PgMetadataStore(engine)
    open_papers = metadata.open_papers()
    open_syms = {p["symbol"] for p in open_papers}

    # Count surveillance vs delivery positions separately
    n_surveillance = 0
    n_delivery = 0
    for p in open_papers:
        note = p.get("note", "") or ""
        if "surveillance" in note:
            n_surveillance += 1
        else:
            n_delivery += 1

    print(
        f"Current open positions: {len(open_papers)} total ({n_delivery} delivery, {n_surveillance} surveillance)"
    )
    if open_syms:
        print(f"  Symbols: {', '.join(sorted(open_syms))}")
    print()

    created = 0
    for sig in signals:
        sym = sig["symbol"]

        # Skip if already open
        if sym in open_syms:
            print(f"  SKIP {sym} — already open")
            continue

        # Enforce max surveillance positions (separate from delivery)
        if n_surveillance >= MAX_SURVEILLANCE_POSITIONS:
            print(
                f"  SKIP {sym} — max surveillance positions ({MAX_SURVEILLANCE_POSITIONS}) reached"
            )
            break

        # Get current price
        current_price = get_current_price(sym)
        if current_price is None:
            print(f"  SKIP {sym} — price unavailable")
            continue

        # Size position
        for hz in HORIZONS:
            hz_capital = args.capital * hz["capital_pct"]
            win_rate, avg_win, avg_loss = dynamic_kelly_params(get_engine())
            kf = kelly_fraction(win_rate, avg_win, avg_loss)
            qty = kelly_position(hz_capital, 0.01, current_price, hz["stop_pct"], kf)
            if qty < 1:
                qty = 1
            # House rule: ₹1L notional per trade (kelly→0 with no history floors to 1)
            lakh_qty = max(1, int(100_000 / current_price))
            if qty < lakh_qty:
                qty = lakh_qty

            position_value = qty * current_price
            stop_dist = current_price * hz["stop_pct"]
            risk_amount = qty * stop_dist
            target = current_price * (1 + hz["stop_pct"] * 3)

            note = (
                f"surveillance {sig['signal_type']} str={sig['strength']:.0f} "
                f"mcap=₹{sig['mcap']:.0f}Cr 3M={sig['ret_3m']:+.0f}% "
                f"vol={sig['vol_20d']:.0f}% sector={sig['sector'] or 'N/A'}"
            )

            if not args.dry_run:
                metadata.record_paper_signal(
                    symbol=sym,
                    close_at_signal=current_price,
                    qty=qty,
                    horizon_days=hz["days"],
                    stop_pct=hz["stop_pct"],
                    segment="NSE",
                    entry_date=date.today().isoformat(),
                    position_value=round(position_value, 2),
                    risk_amount=round(risk_amount, 2),
                    horizon_label=hz["label"],
                    capital_allocated=round(hz_capital, 2),
                    conviction_score=round(sig["strength"] / 100, 4),
                    kelly_fraction=round(kf, 6),
                    hypothesis_id=3,
                    note=note,
                )

                # Auto-journal
                with engine.connect() as conn:
                    paper_id = conn.execute(
                        sa.text(
                            "SELECT id FROM paper_signals WHERE symbol=:s AND status='OPEN' ORDER BY id DESC LIMIT 1"
                        ),
                        {"s": sym},
                    ).scalar()
                if paper_id:
                    metadata.journal_record_on_entry(
                        paper_trade_id=paper_id,
                        symbol=sym,
                        entry_date=date.today().isoformat(),
                        entry_price=current_price,
                        entry_signal=note[:200],
                        setup_type=sig["signal_type"][:32],
                        stop_loss=round(current_price * (1 - hz["stop_pct"]), 2),
                        target_price=round(target, 2),
                        position_size=qty,
                        risk_amount=round(risk_amount, 2),
                        conviction=round(sig["strength"] / 100, 4),
                        sector=(sig["sector"] or "")[:32],
                    )

            created += 1
            n_surveillance += 1
            open_syms.add(sym)

            print(
                f"  OPEN {sym:<15} @{current_price:<8.1f} qty={qty:<4} "
                f"val=₹{position_value:>8,.0f} risk=₹{risk_amount:>6,.0f} "
                f"stop={hz['stop_pct'] * 100:.0f}% target=₹{target:.0f} "
                f"[{sig['signal_type']}] str={sig['strength']:.0f} "
                f"mcap=₹{sig['mcap']:.0f}Cr"
            )

    metadata.close()

    print("\n=== SUMMARY ===")
    print(f"Surveillance positions opened: {created}")
    print(f"Total surveillance open: {n_surveillance}")
    print(f"Total delivery open: {n_delivery}")
    print(f"Capital deployed: ₹{created * args.capital * HORIZONS[0]['capital_pct']:,.0f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
