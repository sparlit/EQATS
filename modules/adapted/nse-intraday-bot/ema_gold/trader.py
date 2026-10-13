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
EMA trend strategy — PAPER / LIVE trader for Gold on MT5.

    python ema_gold/trader.py          # PAPER mode (default): logs signals +
                                       # simulated fills, places NO real orders
    Set "live_trading": true in ema_gold/config.json to place real MT5 orders.

Every closed H1 candle is evaluated with the SAME rules as the backtest
(strategy.py). Paper fills are logged to ema_gold/paper_trades.csv and
sent to Telegram. Risk limits (daily loss, max drawdown halt) apply in
both modes.
"""
import csv
import json
import os
import sys
import time
from datetime import UTC, datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ema_gold.strategy import (
    add_indicators,
    blocked_by_time,
    entry_signal,
    initial_stops,
    load_config,
    position_size,
)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("pip install MetaTrader5")
    sys.exit(1)

try:
    from notifier import telegram_send  # repo-root notifier
except Exception:

    def telegram_send(text, **k):
        return False


_DIR = os.path.dirname(os.path.abspath(__file__))
PAPER_LOG = os.path.join(_DIR, "paper_trades.csv")
STATE_F = os.path.join(_DIR, "trader_state.json")
LOG_COLS = [
    "time",
    "mode",
    "event",
    "direction",
    "price",
    "sl",
    "tp",
    "units_or_lots",
    "pnl",
    "equity",
    "reason",
]


def _log_row(**kw):
    new = not os.path.exists(PAPER_LOG)
    with open(PAPER_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow({c: kw.get(c, "") for c in LOG_COLS})


def _load_state(cfg):
    if os.path.exists(STATE_F):
        with open(STATE_F, encoding="utf-8") as f:
            return json.load(f)
    return {
        "equity": cfg["start_equity"],
        "peak": cfg["start_equity"],
        "halted": False,
        "day": "",
        "day_pnl": 0.0,
        "position": None,
    }


def _save_state(st):
    with open(STATE_F, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, default=str)


def _connect(cfg):
    root = {}
    try:
        with open(os.path.join(_DIR, "..", "mt5_config.json"), encoding="utf-8") as f:
            root = json.load(f)
    except Exception:
        pass
    if not mt5.initialize(path=root.get("path") or None):
        return False
    return mt5.account_info() is not None


def _bars(cfg, n=260):
    tf = getattr(mt5, f"TIMEFRAME_{cfg.get('timeframe', 'H1')}")
    r = mt5.copy_rates_from_pos(cfg["symbol"], tf, 0, n)
    if r is None or len(r) < cfg["ema_trend"] + 10:
        return None
    df = pd.DataFrame(r)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df.set_index("time")[["open", "high", "low", "close"]].astype(float)


def _live_order(cfg, direction, sl, tp, lots):
    t = mt5.symbol_info_tick(cfg["symbol"])
    price = t.ask if direction == "LONG" else t.bid
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": cfg["symbol"],
        "volume": lots,
        "type": mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "deviation": 20,
        "magic": cfg["magic"],
        "comment": "EMA-trend",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    return (r is not None and r.retcode == mt5.TRADE_RETCODE_DONE), price


def main():
    cfg = load_config()
    live = bool(cfg.get("live_trading", False))
    mode = "LIVE" if live else "PAPER"
    print(f"=== EMA Gold trader — {mode} MODE ===")
    if not live:
        print("(no real orders will be placed; set live_trading=true to go live)")

    if not _connect(cfg):
        print("MT5 not connected — open the terminal and log in.")
        sys.exit(1)

    st = _load_state(cfg)
    telegram_send(
        f"📐 EMA Gold trader started — {mode} mode\n"
        f"EMA {cfg['ema_fast']}/{cfg['ema_slow']}/{cfg['ema_trend']}, "
        f"ADX>{cfg['adx_min']}, SL {cfg['sl_atr_mult']}xATR, "
        f"TP {cfg['tp_atr_mult']}xATR, risk {cfg['risk_pct']}%"
    )

    last_bar = None
    while True:
        try:
            df = _bars(cfg)
            if df is None:
                time.sleep(cfg["poll_seconds"])
                continue
            closed = df.index[-2]  # last CLOSED bar
            cur = df.iloc[-1]  # forming bar (for fills/exits)
            now = datetime.now(UTC)

            # daily reset
            today = str(now.date())
            if st["day"] != today:
                st["day"], st["day_pnl"] = today, 0.0

            # ── manage open PAPER position every poll ──
            pos = st.get("position")
            if pos and not live:
                px_hi, px_lo = float(cur["high"]), float(cur["low"])
                closed_reason = None
                if pos["dir"] == "LONG" and px_lo <= pos["sl"]:
                    closed_reason, px = "stop-loss", pos["sl"]
                elif pos["dir"] == "LONG" and px_hi >= pos["tp"]:
                    closed_reason, px = "take-profit", pos["tp"]
                elif pos["dir"] == "SHORT" and px_hi >= pos["sl"]:
                    closed_reason, px = "stop-loss", pos["sl"]
                elif pos["dir"] == "SHORT" and px_lo <= pos["tp"]:
                    closed_reason, px = "take-profit", pos["tp"]
                if closed_reason:
                    pnl = (
                        (px - pos["entry"]) * pos["units"]
                        if pos["dir"] == "LONG"
                        else (pos["entry"] - px) * pos["units"]
                    )
                    st["equity"] += pnl
                    st["peak"] = max(st["peak"], st["equity"])
                    st["day_pnl"] += pnl
                    st["position"] = None
                    _log_row(
                        time=now,
                        mode=mode,
                        event="EXIT",
                        direction=pos["dir"],
                        price=round(px, 2),
                        pnl=round(pnl, 2),
                        equity=round(st["equity"], 2),
                        reason=closed_reason,
                    )
                    telegram_send(
                        f"📐 PAPER exit {pos['dir']} GOLD @ {px:.2f} "
                        f"({closed_reason})  P&L {pnl:+.2f}  "
                        f"equity {st['equity']:.2f}"
                    )

            # ── evaluate new CLOSED bar once ──
            if closed != last_bar:
                last_bar = closed
                ind = add_indicators(df.iloc[:-1], cfg)  # closed bars only
                row = ind.iloc[-1]

                # cross-back exit
                pos = st.get("position")
                if pos and cfg.get("exit_on_cross_back", True):
                    if (pos["dir"] == "LONG" and row["cross_dn"]) or (
                        pos["dir"] == "SHORT" and row["cross_up"]
                    ):
                        px = float(row["close"])
                        pnl = (
                            (px - pos["entry"]) * pos["units"]
                            if pos["dir"] == "LONG"
                            else (pos["entry"] - px) * pos["units"]
                        )
                        st["equity"] += pnl
                        st["day_pnl"] += pnl
                        st["peak"] = max(st["peak"], st["equity"])
                        st["position"] = None
                        _log_row(
                            time=now,
                            mode=mode,
                            event="EXIT",
                            direction=pos["dir"],
                            price=round(px, 2),
                            pnl=round(pnl, 2),
                            equity=round(st["equity"], 2),
                            reason="ema-cross-back",
                        )
                        telegram_send(
                            f"📐 PAPER exit {pos['dir']} GOLD @ {px:.2f} "
                            f"(cross-back)  P&L {pnl:+.2f}"
                        )

                # risk halts
                if st["halted"]:
                    pass
                elif st["equity"] <= st["peak"] * (1 - cfg["max_drawdown_halt_pct"] / 100):
                    st["halted"] = True
                    telegram_send("🛑 EMA Gold trader HALTED — max drawdown breached")
                elif st["day_pnl"] <= -cfg["daily_loss_limit_pct"] / 100 * st["equity"]:
                    print("[RISK] daily loss limit hit — no entries until tomorrow")
                elif st.get("position") is None:
                    why = blocked_by_time(pd.Timestamp(closed), cfg)
                    sig = None if why else entry_signal(row, cfg)
                    if sig:
                        atr_v = float(row["atr"])
                        t = mt5.symbol_info_tick(cfg["symbol"])
                        entry = t.ask if sig == "LONG" else t.bid
                        sl, tp = initial_stops(sig, entry, atr_v, cfg)
                        units = position_size(st["equity"], cfg["risk_pct"], abs(entry - sl))
                        reason = (
                            f"EMA cross {'up' if sig == 'LONG' else 'down'} + "
                            f"ADX {row['adx']:.0f} + trend filter"
                        )
                        if live:
                            si = mt5.symbol_info(cfg["symbol"])
                            tickval = si.trade_tick_value / si.trade_tick_size
                            lots = max(
                                cfg["lot_min"],
                                min(cfg["lot_max"], round(units / tickval / 100, 2) * 100),
                            )
                            ok, fill = _live_order(cfg, sig, sl, tp, lots)
                            _log_row(
                                time=now,
                                mode=mode,
                                event="ENTRY" if ok else "ORDER-FAIL",
                                direction=sig,
                                price=round(fill, 2),
                                sl=round(sl, 2),
                                tp=round(tp, 2),
                                units_or_lots=lots,
                                equity="live",
                                reason=reason,
                            )
                            telegram_send(
                                f"📐 LIVE {sig} GOLD @ {fill:.2f} "
                                f"SL {sl:.2f} TP {tp:.2f} ({reason})"
                            )
                        else:
                            st["position"] = {
                                "dir": sig,
                                "entry": entry,
                                "sl": sl,
                                "tp": tp,
                                "units": units,
                                "opened": str(now),
                            }
                            _log_row(
                                time=now,
                                mode=mode,
                                event="ENTRY",
                                direction=sig,
                                price=round(entry, 2),
                                sl=round(sl, 2),
                                tp=round(tp, 2),
                                units_or_lots=round(units, 4),
                                equity=round(st["equity"], 2),
                                reason=reason,
                            )
                            telegram_send(
                                f"📐 PAPER {sig} GOLD @ {entry:.2f}\n"
                                f"SL {sl:.2f}  TP {tp:.2f}\n{reason}"
                            )
                print(
                    f"[{now:%H:%M}] closed bar {closed}  "
                    f"pos={'yes' if st.get('position') else 'no'}  "
                    f"equity={st['equity']:.2f}"
                )
            _save_state(st)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[ERROR] {e}")
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    main()
