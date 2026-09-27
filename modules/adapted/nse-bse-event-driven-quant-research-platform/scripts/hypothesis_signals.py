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


"""Generate signals for all active hypotheses.

Reads hypothesis_stocks, computes signals per hypothesis, records them,
and creates trades for top-N signals.

Usage:
    python scripts/hypothesis_signals.py [--date YYYY-MM-DD] [--hypothesis NAME] [--dry-run]
"""


import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from indian_quant.config.connections import get_engine
from indian_quant.features.delivery import add_features, prepare_frame
from indian_quant.hypotheses import DeliveryMomentum
from indian_quant.hypotheses.registry import (
    HypothesisRegistry,
    get_hypothesis,
    list_hypotheses,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

NSE_DELIVERY_DIR = Path("data/normalized/delivery/NSE")


def load_stock_frame(symbol: str, delivery_dir: Path = NSE_DELIVERY_DIR) -> pd.DataFrame | None:
    """Load and prepare a single stock's delivery frame."""
    path = delivery_dir / f"{symbol}.parquet"
    if not path.exists():
        return None
    raw = pd.read_parquet(path)
    return prepare_frame(raw, min_rows=40)


def run_signals(
    registry: HypothesisRegistry,
    hypothesis_name: str | None = None,
    signal_date: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Generate signals for one or all hypotheses."""
    get_engine()
    results = {}

    # Get hypotheses to process
    if hypothesis_name:
        hypo_rows = [registry.get(hypothesis_name)]
        if not hypo_rows or not hypo_rows[0]:
            log.error(f"Hypothesis '{hypothesis_name}' not found")
            return {}
    else:
        hypo_rows = [h for h in registry.list_all() if h.get("is_active", True)]

    for hypo_row in hypo_rows:
        hypo_id = hypo_row["id"]
        hypo_name = hypo_row["name"]
        log.info(f"Processing hypothesis: {hypo_name} (id={hypo_id})")

        # Get active symbols for this hypothesis
        symbols = registry.get_active_symbols(hypo_id)
        if not symbols:
            log.info(f"  No active stocks for {hypo_name}, skipping")
            results[hypo_name] = {"signals": 0, "trades": 0, "skipped": "no stocks"}
            continue

        log.info(f"  {len(symbols)} active stocks")

        # Instantiate hypothesis class
        try:
            hypothesis = get_hypothesis(hypo_name)
        except KeyError:
            log.warning(f"  Hypothesis class '{hypo_name}' not registered, skipping")
            results[hypo_name] = {"signals": 0, "trades": 0, "skipped": "class not registered"}
            continue

        # Load frames for all symbols
        frames: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            frame = load_stock_frame(sym)
            if frame is not None:
                frames[sym] = frame

        log.info(f"  Loaded {len(frames)} frames")

        # Compute signals
        all_signals = hypothesis.compute_signals_batch(frames, signal_date=signal_date)
        log.info(f"  Raw signals: {len(all_signals)}")

        # Rank and take top N
        ranked = hypothesis.rank_signals(all_signals)
        log.info(f"  Top signals: {len(ranked)}")

        if dry_run:
            for sig in ranked:
                log.info(
                    f"    {sig.symbol} strength={sig.strength} z={sig.deliv_z} "
                    f"entry={sig.entry_price} stop={sig.stop_loss}"
                )
            results[hypo_name] = {
                "signals": len(all_signals),
                "trades": len(ranked),
                "dry_run": True,
                "details": [{"symbol": s.symbol, "strength": s.strength} for s in ranked],
            }
            continue

        # Record signals in DB (skip duplicates)
        recorded = 0
        trades_created = 0
        seen_keys = set()
        for sig in ranked:
            dedup_key = (sig.symbol, sig.signal_date, sig.signal_type)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            signal_id = registry.record_signal(
                hypothesis_id=hypo_id,
                symbol=sig.symbol,
                signal_date=sig.signal_date,
                signal_type=sig.signal_type,
                strength=sig.strength,
                entry_price=sig.entry_price,
                stop_loss=sig.stop_loss,
                target_price=sig.target_price,
                close=sig.close,
                deliv_z=sig.deliv_z,
                vol_z=sig.vol_z,
                rsi=sig.rsi,
                macd_hist=sig.macd_hist,
                turnover=sig.turnover,
                market_cap_cr=sig.market_cap_cr,
                notes=sig.notes,
            )
            recorded += 1

            # Create trade if not already open for this symbol+hypothesis
            existing = registry.open_trades(hypo_id)
            open_syms = {t["symbol"] for t in existing}
            # Position cap: max 7 open per hypothesis (do not exceed)
            if sig.symbol not in open_syms and len(existing) < hypothesis.max_positions:
                # House rule: ₹1L notional per trade
                capital_per_pos = 100_000
                qty = max(1, int(capital_per_pos / sig.entry_price))

                registry.open_trade(
                    hypothesis_id=hypo_id,
                    symbol=sig.symbol,
                    entry_date=sig.signal_date,
                    entry_price=sig.entry_price,
                    qty=qty,
                    signal_id=signal_id,
                    stop_pct=hypothesis.default_stop_pct,
                    horizon_days=hypothesis.default_horizon_days,
                )
                trades_created += 1

                # Also write to paper_signals for live paper trading UI
                from datetime import datetime as _dt

                import sqlalchemy as _sa

                position_value = qty * sig.entry_price
                stop_dist = sig.entry_price * hypothesis.default_stop_pct
                risk_amount = qty * stop_dist
                _eng = get_engine()
                with _eng.begin() as _conn:
                    paper_id = _conn.execute(
                        _sa.text("""
                        INSERT INTO paper_signals
                            (created_at, symbol, segment, side, close_at_signal, qty,
                             horizon_days, stop_pct, status, note,
                             entry_date, position_value, risk_amount, horizon_label,
                             capital_allocated, conviction_score, kelly_fraction, hypothesis_id)
                        VALUES (:created_at, :symbol, :segment, 'BUY', :close, :qty,
                                :horizon, :stop, 'OPEN', :note,
                                :entry_date, :pos_val, :risk, :hz_label,
                                :cap, :conviction, 0.0, :hypo_id)
                        RETURNING id
                    """),
                        {
                            "created_at": _dt.now().isoformat()[:19],
                            "symbol": sig.symbol,
                            "segment": "NSE_EQ",
                            "close": sig.entry_price,
                            "qty": qty,
                            "horizon": hypothesis.default_horizon_days,
                            "stop": hypothesis.default_stop_pct,
                            "note": (
                                f"{hypo_name} {sig.signal_type} "
                                f"vol_ratio={sig.vol_z:.1f} stop=₹{sig.stop_loss:.2f} "
                                f"target=₹{sig.target_price:.2f}"
                            ),
                            "entry_date": sig.signal_date,
                            "pos_val": round(position_value, 2),
                            "risk": round(risk_amount, 2),
                            "hz_label": f"{hypothesis.default_horizon_days}d",
                            "cap": capital_per_pos,
                            "conviction": round(sig.strength / 100, 4),
                            "hypo_id": hypo_id,
                        },
                    ).scalar()
                # Auto-journal: sync journal with live trade
                from indian_quant.storage.pg_metadata import PgMetadataStore

                _md = PgMetadataStore(_eng)
                _md.journal_record_on_entry(
                    paper_trade_id=paper_id,
                    symbol=sig.symbol,
                    entry_date=str(sig.signal_date),
                    entry_price=float(sig.entry_price),
                    entry_signal=f"{hypo_name} {sig.signal_type}",
                    setup_type=hypo_name,
                    stop_loss=round(float(sig.stop_loss), 2),
                    target_price=round(float(sig.target_price), 2),
                    position_size=qty,
                    risk_amount=round(risk_amount, 2),
                    conviction=round(sig.strength / 100, 4),
                )
                log.info(
                    f"    TRADE: {sig.symbol} qty={qty} @ {sig.entry_price} "
                    f"stop={sig.stop_loss} target={sig.target_price}"
                )

        results[hypo_name] = {
            "signals": len(all_signals),
            "recorded": recorded,
            "trades_created": trades_created,
        }
        log.info(f"  Recorded {recorded} signals, created {trades_created} trades")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate hypothesis signals")
    parser.add_argument("--date", help="Signal date (YYYY-MM-DD)")
    parser.add_argument("--hypothesis", help="Process only this hypothesis")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()

    engine = get_engine()
    registry = HypothesisRegistry(engine)

    results = run_signals(registry, hypothesis_name=args.hypothesis, signal_date=args.date, dry_run=args.dry_run)
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
