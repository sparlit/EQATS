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


"""
Daily performance report for the MT5 auto-trader (Gold + BTC).
Pulls closed-trade history from MT5, computes win rate + P&L (today and
all-time), and sends a summary to Telegram. Run daily (see schedule below).
"""
import json
import sys
from datetime import UTC, datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("MetaTrader5 not installed")
    sys.exit(1)

import notifier  # uses TELEGRAM_TOKEN/CHAT_ID from config.py

MAGIC = 20250101  # must match mt5_trader.MAGIC


def _connect():
    c = json.load(open("mt5_config.json", encoding="utf-8"))
    path = c.get("path") or None
    if mt5.initialize(path=path) and mt5.account_info():
        return True
    return mt5.initialize(path=path, login=int(c["login"]), password=c["password"], server=c["server"])


def _summarize(deals):
    """Return (n, wins, losses, net_pnl) for our closing deals."""
    n = wins = losses = 0
    pnl = 0.0
    by_sym = {}
    for d in deals:
        if d.magic != MAGIC or d.entry != mt5.DEAL_ENTRY_OUT:
            continue
        n += 1
        p = d.profit + d.swap + d.commission
        pnl += p
        if p >= 0:
            wins += 1
        else:
            losses += 1
        by_sym.setdefault(d.symbol, [0, 0.0])
        by_sym[d.symbol][0] += 1
        by_sym[d.symbol][1] += p
    return n, wins, losses, pnl, by_sym


def main():
    if not _connect():
        print("connect failed:", mt5.last_error())
        return

    now = datetime.now(UTC)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=365)

    today_deals = mt5.history_deals_get(day0, now) or []
    all_deals = mt5.history_deals_get(start, now) or []
    info = mt5.account_info()
    open_pos = mt5.positions_get() or []
    float_pnl = sum(p.profit for p in open_pos if p.magic == MAGIC)

    tn, tw, tl, tpnl, _ = _summarize(today_deals)
    an, aw, al, apnl, by_sym = _summarize(all_deals)

    def wr(w, n):
        return f"{round(w / n * 100, 1)}%" if n else "—"

    lines = [
        f"📊 DAILY REPORT — {now.strftime('%d %b %Y')}",
        f"Account #{info.login} (DEMO)  Balance ${info.balance:,.2f}",
        "",
        "── TODAY ──",
        f"Trades: {tn}  |  Win rate: {wr(tw, tn)}  ({tw}W / {tl}L)",
        f"P&L: {tpnl:+.2f} USD",
        "",
        "── ALL-TIME (this bot) ──",
        f"Trades: {an}  |  Win rate: {wr(aw, an)}  ({aw}W / {al}L)",
        f"Net P&L: {apnl:+.2f} USD",
    ]
    for sym, (cnt, p) in by_sym.items():
        lines.append(f"   {sym}: {cnt} trades, {p:+.2f} USD")
    if open_pos:
        lines += ["", f"── OPEN NOW ({len(open_pos)}) ──", f"Floating P&L: {float_pnl:+.2f} USD"]
        for p in open_pos:
            side = "BUY" if p.type == 0 else "SELL"
            lines.append(f"   {p.symbol} {side} {p.volume}  {p.profit:+.2f}")
    lines += ["", "Strategy: Gold 5m / BTC 15m · fixed SL · dynamic target"]

    msg = "\n".join(lines)
    print(msg)
    ok = notifier.telegram_send(msg)
    print("Telegram sent:", ok)
    mt5.shutdown()


if __name__ == "__main__":
    main()
