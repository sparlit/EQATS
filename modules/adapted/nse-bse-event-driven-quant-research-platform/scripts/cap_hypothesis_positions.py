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


"""Cap open paper positions per hypothesis to the top N by strength.

Keeps the strongest N open trades per hypothesis (ranked by conviction_score,
then entry_date DESC as tiebreaker) and settles the excess at current price.

Works on paper_signals (single source of truth). Linked hypothesis_trades
rows are settled to stay in sync.

Usage:
    python scripts/cap_hypothesis_positions.py            # cap all to 7
    python scripts/cap_hypothesis_positions.py --top 7    # custom cap
    python scripts/cap_hypothesis_positions.py --dry-run  # preview only
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

DEFAULT_TOP_N = 7


def strength_rank(row: dict) -> tuple[float, str]:
    """Rank key for an open paper signal: conviction, then recency."""
    conv = row.get("conviction_score") or 0.0
    entry = str(row.get("entry_date") or "")[:10]
    return (float(conv), entry)


def _get_price(symbol: str) -> float | None:
    """Fetch current price via yfinance."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(period="1d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def cap_hypothesis(
    registry: HypothesisRegistry,
    engine: sa.Engine,
    top_n: int,
    dry_run: bool = False,
) -> dict:
    """Settle excess open paper trades per hypothesis, keeping top_n strongest.

    Also settles matching OPEN rows in hypothesis_trades (audit trail) so the
    two tables stay consistent.
    """
    today = date.today()
    results: dict[str, dict] = {}

    open_trades = registry.open_trades()
    by_hypo: dict[int, list[dict]] = {}
    for t in open_trades:
        by_hypo.setdefault(t["hypothesis_id"], []).append(t)

    for hypo_id, trades in sorted(by_hypo.items()):
        if len(trades) <= top_n:
            log.info(f"hypo {hypo_id}: {len(trades)} open (<= {top_n}), no action")
            continue

        # Sort strongest first, keep top_n
        trades_sorted = sorted(trades, key=strength_rank, reverse=True)
        keep = trades_sorted[:top_n]
        excess = trades_sorted[top_n:]

        log.info(f"hypo {hypo_id}: {len(trades)} open -> keep {len(keep)}, settle {len(excess)}")

        for t in excess:
            symbol = t["symbol"]
            entry_price = t["entry_price"] or t.get("close_at_signal") or 0.0
            entry_date = str(t.get("entry_date") or "")[:10]
            ps_id = t["id"]
            # Only settle the specific paper signal id, not by symbol.
            price = _get_price(symbol)
            if price is None:
                log.warning(
                    f"  {symbol} (ps id {ps_id}): no price, closing at entry {entry_price:.2f}"
                )
                price = entry_price

            if dry_run:
                log.info(f"  [dry] would settle {symbol} (ps id {ps_id}) at {price:.2f}")
                results[str(ps_id)] = {
                    "symbol": symbol,
                    "action": "dry_run",
                    "price": price,
                }
                continue

            result = registry.close_trade(
                trade_id=ps_id,
                exit_date=str(today),
                exit_price=price,
                exit_reason="CAP_REACHED",
                notes=f"Position cap {top_n}/hypothesis exceeded; settled at market.",
            )
            log.info(
                f"  SETTLED {symbol} (ps id {ps_id}) at {price:.2f} "
                f"net_bps={result.get('net_bps', 0):.1f}"
            )

            # Settle matching hypothesis_trades rows (audit trail) directly,
            # replicating registry._close_hypothesis_trade to avoid id collisions.
            with engine.begin() as conn:
                ht_rows = (
                    conn.execute(
                        sa.text("""
                    SELECT * FROM hypothesis_trades
                    WHERE status = 'OPEN' AND hypothesis_id = :hid
                      AND symbol = :sym AND entry_date = CAST(:edate AS date)
                """),
                        {"hid": hypo_id, "sym": symbol, "edate": entry_date},
                    )
                    .mappings()
                    .fetchall()
                )
                for ht in ht_rows:
                    ht = dict(ht)
                    ep = ht["entry_price"] or 0.0
                    gross_bps = ((price / ep) - 1) * 10_000 if ep else 0.0
                    net_bps = gross_bps - 107.0
                    return_pct = gross_bps / 100.0
                    try:
                        ed = datetime.strptime(str(ht["entry_date"])[:10], "%Y-%m-%d").date()
                        days_held = (today - ed).days
                    except Exception:
                        days_held = 0
                    conn.execute(
                        sa.text("""
                        UPDATE hypothesis_trades SET
                            exit_date = :xd, exit_price = :xp, exit_value = :xp * qty,
                            exit_reason = 'CAP_REACHED', gross_bps = :gb, net_bps = :nb,
                            return_pct = :rp, days_held = :dh, status = 'SETTLED',
                            notes = :notes
                        WHERE id = :id
                    """),
                        {
                            "xd": str(today),
                            "xp": price,
                            "gb": gross_bps,
                            "nb": net_bps,
                            "rp": return_pct,
                            "dh": days_held,
                            "notes": f"Position cap {top_n}/hypothesis exceeded; settled at market.",
                            "id": ht["id"],
                        },
                    )
                    log.info(f"    + settled ht id {ht['id']}")

            results[str(ps_id)] = {
                "symbol": symbol,
                "action": "settled",
                "price": price,
            }

    return results


def settle_orphan_ht_trades(engine: sa.Engine, dry_run: bool = False) -> int:
    """Settle stale OPEN hypothesis_trades rows (audit trail cleanup).

    Two groups are settled:
      1. Orphans — OPEN rows with no matching OPEN paper signal (their paper
         position already settled). Closed at entry (flat).
      2. Duplicates — for rows that DO match an OPEN paper position, keep the
         lowest-id row per (hypo, symbol, entry_date) and settle the rest.
    """
    today = date.today()
    settled = 0
    with engine.connect() as conn:
        # Group 1: orphans
        orphans = (
            conn.execute(
                sa.text("""
            SELECT ht.id, ht.hypothesis_id, ht.symbol, ht.entry_date,
                   ht.entry_price, ht.qty
            FROM hypothesis_trades ht
            WHERE ht.status = 'OPEN' AND NOT EXISTS (
                SELECT 1 FROM paper_signals ps
                WHERE ps.status = 'OPEN' AND ps.hypothesis_id = ht.hypothesis_id
                  AND ps.symbol = ht.symbol AND ps.entry_date::date = ht.entry_date
            )
            ORDER BY ht.id
        """)
            )
            .mappings()
            .fetchall()
        )
        # Group 2: duplicates beyond the first per (hypo, symbol, entry_date)
        dups = (
            conn.execute(
                sa.text("""
            SELECT ht.id, ht.hypothesis_id, ht.symbol, ht.entry_date,
                   ht.entry_price, ht.qty
            FROM hypothesis_trades ht
            JOIN (
                SELECT hypothesis_id, symbol, entry_date, MIN(id) AS keep_id
                FROM hypothesis_trades
                WHERE status = 'OPEN'
                GROUP BY hypothesis_id, symbol, entry_date
                HAVING COUNT(*) > 1
            ) k ON k.hypothesis_id = ht.hypothesis_id
               AND k.symbol = ht.symbol AND k.entry_date = ht.entry_date
            WHERE ht.status = 'OPEN' AND ht.id <> k.keep_id
            ORDER BY ht.id
        """)
            )
            .mappings()
            .fetchall()
        )

    rows = orphans + dups
    if not rows:
        log.info("No orphan/duplicate hypothesis_trades rows to settle")
        return 0

    log.info(
        f"{len(rows)} stale hypothesis_trades rows to settle "
        f"({len(orphans)} orphan, {len(dups)} duplicate)"
    )
    for row in rows:
        ht = dict(row)
        if dry_run:
            log.info(f"  [dry] would settle ht id {ht['id']} {ht['symbol']} {ht['entry_date']}")
            settled += 1
            continue
        price = ht["entry_price"] or 0.0
        reason = "LEGACY_ORPHAN" if ht in orphans else "DUP_ROW"
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                UPDATE hypothesis_trades SET
                    exit_date = :xd, exit_price = :xp, exit_value = :xp * qty,
                    exit_reason = :reason, gross_bps = 0, net_bps = -107,
                    return_pct = 0, days_held = 0, status = 'SETTLED',
                    notes = 'Audit cleanup: stale/duplicate row.'
                WHERE id = :id
            """),
                {"xd": str(today), "xp": price, "reason": reason, "id": ht["id"]},
            )
        log.info(f"  settled ht id {ht['id']} {ht['symbol']} ({reason})")
        settled += 1
    return settled


def main() -> int:
    parser = argparse.ArgumentParser(description="Cap open paper positions per hypothesis")
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"Max open positions per hypothesis (default: {DEFAULT_TOP_N})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    args = parser.parse_args()

    engine = get_engine()
    registry = HypothesisRegistry(engine)

    results = cap_hypothesis(registry, engine, top_n=args.top, dry_run=args.dry_run)
    orphan_settled = settle_orphan_ht_trades(engine, dry_run=args.dry_run)
    log.info(f"Total settled/excess: {len(results)}; orphan ht settled: {orphan_settled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
