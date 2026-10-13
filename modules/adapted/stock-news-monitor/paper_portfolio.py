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


"""Paper-trading ledger with real-world constraints: whole shares, live NSE
prices, fixed starting capital of Rs 5000. No real money involved.

Usage:
    python paper_portfolio.py status
    python paper_portfolio.py buy TATASTEEL.NS 1
    python paper_portfolio.py sell TATASTEEL.NS 1
"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from newslib import atomic_write_text

LEDGER = Path(__file__).parent / "portfolio.json"
STARTING_CASH = 5000.0
FEES_PCT = 0.0025  # ~0.25% per side: STT, stamp duty, DP charges, spread


def load():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"cash": STARTING_CASH, "positions": {}, "trades": []}


def save(p):
    # Atomic — see newslib.atomic_write_text. write_text truncates first, so a
    # kill mid-write leaves a ledger that no later run can read.
    atomic_write_text(LEDGER, json.dumps(p, indent=2))


def live_price(symbol):
    hist = yf.Ticker(symbol).history(period="1d")
    # yfinance returns placeholder rows with NaN closes mid-session. A NaN here
    # propagates silently into sizing maths and blows up as "cannot convert float
    # NaN to integer" far from the cause, so drop them at the source.
    closes = hist["Close"].dropna() if not hist.empty else hist
    if len(closes) == 0:
        sys.exit(f"No price data for {symbol}")
    return float(closes.iloc[-1])


def record(p, action, symbol, qty, price, fee=0.0):
    p["trades"].append(
        {
            "time": datetime.now(UTC).isoformat(),
            "action": action,
            "symbol": symbol,
            "qty": qty,
            "price": round(price, 2),
            "fee": round(fee, 2),
        }
    )


def buy(p, symbol, qty):
    price = live_price(symbol)
    cost = price * qty
    fee = cost * FEES_PCT
    if cost + fee > p["cash"]:
        sys.exit(f"Not enough cash: need Rs {cost + fee:.2f} (incl fees), have Rs {p['cash']:.2f}")
    pos = p["positions"].get(symbol, {"qty": 0, "avg_cost": 0.0})
    # fee folds into cost basis so P&L reflects real-world friction
    pos["avg_cost"] = (pos["avg_cost"] * pos["qty"] + cost + fee) / (pos["qty"] + qty)
    pos["qty"] += qty
    p["positions"][symbol] = pos
    p["cash"] -= cost + fee
    record(p, "buy", symbol, qty, price, fee)
    print(
        f"BOUGHT {qty} x {symbol} @ Rs {price:.2f} + Rs {fee:.2f} fees "
        f"(cash left Rs {p['cash']:.2f})"
    )


def sell(p, symbol, qty):
    pos = p["positions"].get(symbol)
    if not pos or pos["qty"] < qty:
        sys.exit(f"You don't hold {qty} shares of {symbol}")
    price = live_price(symbol)
    proceeds = price * qty
    fee = proceeds * FEES_PCT
    p["cash"] += proceeds - fee
    pos["qty"] -= qty
    if pos["qty"] == 0:
        del p["positions"][symbol]
    record(p, "sell", symbol, qty, price, fee)
    print(
        f"SOLD {qty} x {symbol} @ Rs {price:.2f} - Rs {fee:.2f} fees (cash now Rs {p['cash']:.2f})"
    )


def status(p):
    total = p["cash"]
    print(f"{'symbol':<15}{'qty':>4}{'avg cost':>10}{'now':>10}{'value':>10}{'P&L':>9}{'P&L%':>8}")
    for symbol, pos in p["positions"].items():
        price = live_price(symbol)
        value = price * pos["qty"]
        cost = pos["avg_cost"] * pos["qty"]
        pnl = value - cost
        total += value
        print(
            f"{symbol:<15}{pos['qty']:>4}{pos['avg_cost']:>10.2f}{price:>10.2f}"
            f"{value:>10.2f}{pnl:>+9.2f}{100 * pnl / cost:>+8.2f}"
        )
    print(f"\nCash: Rs {p['cash']:.2f}")
    print(
        f"Total value: Rs {total:.2f}  ({total - STARTING_CASH:+.2f} vs Rs {STARTING_CASH:.0f} start, "
        f"{100 * (total - STARTING_CASH) / STARTING_CASH:+.2f}%)"
    )
    b = p.get("benchmark")
    if b:
        level = live_price(b["symbol"])
        shadow = b["start_capital"] * level / b["start_level"]
        print(
            f"NIFTY 50 shadow (same Rs {b['start_capital']:.0f} in the index): "
            f"Rs {shadow:.2f} ({100 * (shadow / b['start_capital'] - 1):+.2f}%)"
        )
        print(
            f"System vs index: Rs {total - shadow:+.2f} "
            f"({'ahead' if total >= shadow else 'behind'})"
        )


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("status", "buy", "sell"):
        sys.exit(__doc__)
    p = load()
    if sys.argv[1] == "status":
        status(p)
    else:
        symbol, qty = sys.argv[2].upper(), int(sys.argv[3])
        (buy if sys.argv[1] == "buy" else sell)(p, symbol, qty)
        save(p)


if __name__ == "__main__":
    main()
