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


"""CLI for manual hypothesis trade entry/exit and stock management.

Usage:
    python scripts/hypothesis_cli.py list                           # list hypotheses
    python scripts/hypothesis_cli.py stocks <hypo_id>               # list stocks
    python scripts/hypothesis_cli.py add <hypo_id> <SYMBOL>         # add stock
    python scripts/hypothesis_cli.py remove <hypo_id> <SYMBOL>      # remove stock
    python scripts/hypothesis_cli.py open <hypo_id> <SYM> <price> <qty>  # open trade
    python scripts/hypothesis_cli.py close <trade_id> <exit_price> [reason]  # close trade
    python scripts/hypothesis_cli.py trades <hypo_id>               # show open trades
    python scripts/hypothesis_cli.py summary <hypo_id>              # trade summary
    python scripts/hypothesis_cli.py signals <hypo_id>              # latest signals
"""


import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config.connections import get_engine
from indian_quant.hypotheses.registry import HypothesisRegistry


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1

    engine = get_engine()
    reg = HypothesisRegistry(engine)
    cmd = args[0]

    if cmd == "list":
        for h in reg.list_all():
            ts = reg.trade_summary(h["id"])
            status = "ACTIVE" if h["is_active"] else "INACTIVE"
            print(
                f"  {h['id']}: {h['name']:25s} [{status}] stocks={reg.stock_count(h['id'])} "
                f"trades={ts.get('settled', 0)} avg_bps={ts.get('avg_net_bps', '-')}"
            )

    elif cmd == "stocks":
        hid = int(args[1])
        stocks = reg.list_stocks(hid)
        hypo = reg.get_by_id(hid)
        print(f"Hypothesis: {hypo['name']} ({len(stocks)} stocks)")
        for s in stocks:
            print(f"  {s['symbol']:15s} added={s['added_at']} by={s['added_by']}")

    elif cmd == "add":
        hid = int(args[1])
        sym = args[2].upper()
        reg.add_stock(hid, sym, added_by="cli")
        print(f"Added {sym} to hypothesis {hid}")

    elif cmd == "remove":
        hid = int(args[1])
        sym = args[2].upper()
        reason = args[3] if len(args) > 3 else "cli"
        ok = reg.remove_stock(hid, sym, reason)
        print(f"Removed {sym}: {ok}")

    elif cmd == "open":
        hid = int(args[1])
        sym = args[2].upper()
        price = float(args[3])
        qty = int(args[4])
        stop = float(args[5]) if len(args) > 5 else 0.07
        horizon = int(args[6]) if len(args) > 6 else 10
        tid = reg.open_trade(
            hid,
            sym,
            str(date.today()),
            price,
            qty,
            stop_pct=stop,
            horizon_days=horizon,
            notes="cli entry",
        )
        print(f"Opened trade #{tid}: {sym} qty={qty} @ ₹{price}")

    elif cmd == "close":
        tid = int(args[1])
        price = float(args[2])
        reason = args[3] if len(args) > 3 else "MANUAL"
        result = reg.close_trade(tid, str(date.today()), price, reason)
        net = result.get("net_bps", 0)
        print(f"Closed trade #{tid}: net_bps={net:.1f}")

    elif cmd == "trades":
        hid = int(args[1])
        trades = reg.open_trades(hid)
        print(f"Open trades ({len(trades)}):")
        for t in trades:
            print(
                f"  #{t['id']} {t['symbol']:12s} entry=₹{t['entry_price']:.2f} "
                f"qty={t['qty']} value=₹{t['entry_value']:.0f}"
            )

    elif cmd == "summary":
        hid = int(args[1])
        ts = reg.trade_summary(hid)
        hypo = reg.get_by_id(hid)
        print(f"Hypothesis: {hypo['name']}")
        for k, v in ts.items():
            if v is not None:
                print(f"  {k}: {v}")

    elif cmd == "signals":
        hid = int(args[1])
        sigs = reg.latest_signals(hid, limit=10)
        print(f"Latest signals ({len(sigs)}):")
        for s in sigs:
            print(
                f"  {s['signal_date']} {s['symbol']:12s} str={s['strength']:.1f} "
                f"entry=₹{s['entry_price']:.2f} stop=₹{s['stop_loss']:.2f}"
            )

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
