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
MT5 Auto-Trader — Gold (XAUUSD) + Bitcoin (BTCUSD)
====================================================
Polls GitHub signals every 30 sec.
New signal → places order on your MT5 DEMO account instantly.
Monitors SL/TP → closes trade + sends Telegram confirmation.

SETUP (one-time):
  1. Open FREE demo at: https://www.xm.com/  (or IC Markets / Exness)
  2. Download MetaTrader 5 terminal from your broker
  3. Log in with demo credentials
  4. pip install MetaTrader5 requests
  5. Create a file called mt5_config.json (see bottom of this file)
  6. Run: python mt5_trader.py

IMPORTANT: MT5 terminal must be OPEN and LOGGED IN while this runs.
           This script must run on Windows (MT5 only works on Windows).
"""

import contextlib
import json
import math
import os
import sys
import time
from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import requests

# ── MT5 Import ────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
except ImportError:
    print("=" * 60)
    print("  MetaTrader5 package not found!")
    print("  Run:  pip install MetaTrader5")
    print("=" * 60)
    sys.exit(1)

# ── SMC structure detectors (used for local 15m/5m signal mode) ────
try:
    from shared.smc_engine import (
        detect_bos_choch,
        detect_fvg,
        detect_liquidity_sweep,
        detect_order_block,
    )

    _SMC_OK = True
except Exception as _e:
    print(f"[MT5] smc_engine import failed ({_e}); 15m mode unavailable.")
    _SMC_OK = False

# ── Load Config ───────────────────────────────────────────────────
CONFIG_FILE = "mt5_config.json"


def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    # Fallback to env vars
    return {
        "login": int(os.environ.get("MT5_LOGIN", "0")),
        "password": os.environ.get("MT5_PASSWORD", ""),
        "server": os.environ.get("MT5_SERVER", ""),
        "path": os.environ.get("MT5_PATH", ""),
        "risk_pct": float(os.environ.get("MT5_RISK_PCT", "1.0")),
        "telegram_token": os.environ.get("TELEGRAM_TOKEN", ""),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "github_user": "lavakus",
        "github_repo": "nse-intraday-bot",
        "assets": ["GOLD", "BTC"],
        "max_positions_per_asset": 1,
    }


CFG = _load_config()

# ── Symbol map  (our name → your broker's MT5 symbol) ─────────────
# XM.com uses XAUUSD and BTCUSD — adjust if your broker differs
SYMBOL_MAP = {
    "GOLD": CFG.get("symbol_gold", "XAUUSD"),
    "XAUUSD": CFG.get("symbol_gold", "XAUUSD"),
    "BTC": CFG.get("symbol_btc", "BTCUSD"),
    "BTCUSDT": CFG.get("symbol_btc", "BTCUSD"),
}

GITHUB_BASE = (
    f"https://raw.githubusercontent.com/"
    f"{CFG.get('github_user', 'lavakus')}/"
    f"{CFG.get('github_repo', 'nse-intraday-bot')}/main"
)
SIGNAL_URLS = {
    "GOLD": f"{GITHUB_BASE}/gold_signals_log.json",
    "BTC": f"{GITHUB_BASE}/btc_signals_log.json",
}

POLL_SEC = 30  # check GitHub every 30 seconds
MAGIC = 20250101  # magic number to identify our bot's trades


# ═══════════════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════════════


def tg(text: str):
    token = CFG.get("telegram_token", "")
    chat_id = CFG.get("telegram_chat_id", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        print(f"[TG] {e}")


# ═══════════════════════════════════════════════════════════════════
# MT5 CONNECTION
# ═══════════════════════════════════════════════════════════════════


def connect() -> bool:
    """Connect to MT5 terminal. Returns True if successful.

    Strategy:
      1) ATTACH to an already-running, logged-in terminal (no password
         needed — recommended; just log in once inside MT5 and keep it open).
      2) Fall back to logging in with the credentials in mt5_config.json.
    """
    path = CFG.get("path") or None

    # ── 1) Attach to a running, logged-in terminal (no creds) ────────
    if mt5.initialize(**({"path": path} if path else {})):
        if mt5.account_info() is not None:
            print("[MT5] Attached to running terminal (manual login).")
        else:
            mt5.shutdown()  # terminal up but no account — try explicit login
    # ── 2) Fall back to explicit login with stored credentials ───────
    if mt5.account_info() is None:
        kwargs = {}
        if path:
            kwargs["path"] = path
        if CFG.get("login"):
            kwargs["login"] = int(CFG["login"])
            kwargs["password"] = CFG["password"]
            kwargs["server"] = CFG["server"]
        if not mt5.initialize(**kwargs):
            print(f"[MT5] Initialize failed: {mt5.last_error()}")
            print(
                "[MT5] TIP: open MetaTrader 5, log in to your XM demo "
                "account, enable Algo Trading, and keep it open."
            )
            return False

    info = mt5.account_info()
    if info is None:
        print(f"[MT5] Account info failed: {mt5.last_error()}")
        print("[MT5] TIP: log in inside the MT5 terminal first, then re-run.")
        return False

    print(
        f"[MT5] Connected — Account #{info.login}  "
        f"Balance: {info.balance:.2f} {info.currency}  "
        f"Server: {info.server}"
    )
    tg(
        f"🤖 MT5 Auto-Trader STARTED\n"
        f"Account: #{info.login} (DEMO)\n"
        f"Balance: {info.balance:.2f} {info.currency}\n"
        f"Watching: {', '.join(CFG.get('assets', ['GOLD', 'BTC']))}\n"
        f"Risk per trade: {CFG.get('risk_pct', 1.0)}% of balance"
    )
    return True


def get_balance() -> float:
    info = mt5.account_info()
    return info.balance if info else 0.0


# ═══════════════════════════════════════════════════════════════════
# LOT SIZE CALCULATOR
# ═══════════════════════════════════════════════════════════════════


def calc_lot(symbol: str, entry: float, sl: float) -> float:
    """
    Risk-based lot size.
    Lot = (account_balance * risk_pct) / (sl_distance * tick_val_per_lot)
    """
    sym_info = mt5.symbol_info(symbol)
    if sym_info is None:
        print(f"[LOT] Symbol {symbol} not found")
        return sym_info

    balance = get_balance()
    risk_amount = balance * (CFG.get("risk_pct", 1.0) / 100.0)
    sl_distance = abs(entry - sl)

    if sl_distance <= 0:
        print(f"[LOT] SL distance is zero for {symbol}")
        return sym_info.volume_min

    # Value of 1 pip per 1 lot = tick_value / tick_size
    tick_size = sym_info.trade_tick_size
    tick_value = sym_info.trade_tick_value
    if tick_size <= 0:
        return sym_info.volume_min

    val_per_pip_per_lot = tick_value / tick_size  # USD per price-unit per lot
    lot = risk_amount / (sl_distance * val_per_pip_per_lot)

    # Snap to broker's step
    step = sym_info.volume_step
    lot = math.floor(lot / step) * step
    lot = max(sym_info.volume_min, min(lot, sym_info.volume_max))
    lot = round(lot, 2)

    print(
        f"[LOT] {symbol}  balance={balance:.2f}  risk={risk_amount:.2f}  "
        f"sl_dist={sl_distance:.4f}  lot={lot}"
    )
    return lot


# ═══════════════════════════════════════════════════════════════════
# ORDER PLACEMENT
# ═══════════════════════════════════════════════════════════════════


def place_order(signal: dict) -> bool:
    """
    Places a market order based on signal dict from our bot.
    Returns True if order placed successfully.
    """
    asset = signal.get("asset", signal.get("symbol", "GOLD"))
    symbol = SYMBOL_MAP.get(asset.upper(), asset)
    direction = signal.get("direction", "LONG")
    tp = signal.get("trade_params", {})

    entry_price = float(tp.get("entry", signal.get("entry", 0)))
    sl_price = float(tp.get("sl", signal.get("sl", 0)))
    t2_price = float(tp.get("t2", signal.get("target", 0)))
    score = signal.get("score", 0)
    sig_id = signal.get("id", "?")

    if not entry_price or not sl_price or not t2_price:
        print(f"[ORDER] Missing price levels for signal #{sig_id}")
        return False

    # Enable symbol trading
    if not mt5.symbol_select(symbol, True):
        print(f"[ORDER] Cannot select symbol {symbol}")
        return False

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"[ORDER] Cannot get tick for {symbol}")
        return False

    order_type = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
    price = tick.ask if direction == "LONG" else tick.bid
    lot = calc_lot(symbol, price, sl_price)

    if lot is None or lot <= 0:
        print(f"[ORDER] Invalid lot size for {symbol}")
        return False

    # ── Faster-exit target ───────────────────────────────────────────
    # Backtest showed a 2R target closes trades much sooner at ~the same
    # efficiency as the far 3R/5R targets. Override the signal's far T2
    # with a tp_r_multiple of the actual risk (entry->SL) from the live
    # entry price. Set tp_r_multiple in mt5_config.json (0 = keep signal T2).
    tp_r = float(CFG.get("tp_r_multiple", 2.0))
    if tp_r > 0:
        risk_dist = abs(price - sl_price)
        t2_price = (price + tp_r * risk_dist) if direction == "LONG" else (price - tp_r * risk_dist)

    # Auto-detect broker's supported filling mode (XM uses FOK, others use IOC)
    sym_info2 = mt5.symbol_info(symbol)
    filling = mt5.ORDER_FILLING_FOK
    if sym_info2 is not None:
        fm = sym_info2.filling_mode
        if fm & 2:  # bit 1 = IOC supported
            filling = mt5.ORDER_FILLING_IOC
        elif fm & 1:  # bit 0 = FOK supported
            filling = mt5.ORDER_FILLING_FOK
        else:
            filling = mt5.ORDER_FILLING_RETURN

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": round(sl_price, 5),
        "tp": round(t2_price, 5),
        "deviation": 20,  # max slippage in points
        "magic": MAGIC,
        "comment": f"BOT#{sig_id} score={score}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    result = mt5.order_send(request)

    if result is None:
        print(f"[ORDER] order_send returned None: {mt5.last_error()}")
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = (
            f"✅ TRADE EXECUTED — {symbol} {'🟢 BUY' if direction == 'LONG' else '🔴 SELL'}\n"
            f"Signal #{sig_id}  Score: {score}/150\n"
            f"Entry : {price:.4f}\n"
            f"SL    : {sl_price:.4f}\n"
            f"TP    : {t2_price:.4f}\n"
            f"Lots  : {lot}\n"
            f"Order : #{result.order}"
        )
        print(f"[ORDER] ✅ {symbol} {direction}  lot={lot}  order=#{result.order}")
        tg(msg)
        return True
    else:
        err = f"❌ TRADE FAILED — {symbol}\nError: {result.retcode} — {result.comment}"
        print(f"[ORDER] ❌ Failed retcode={result.retcode}  comment={result.comment}")
        tg(err)
        return False


# ═══════════════════════════════════════════════════════════════════
# POSITION MONITOR
# ═══════════════════════════════════════════════════════════════════


def count_open_positions(symbol: str) -> int:
    positions = mt5.positions_get(symbol=symbol)
    return len(positions) if positions else 0


def report_closed_trades():
    """
    Check recently closed deals and notify Telegram.
    Runs every poll cycle.
    """
    hist = mt5.history_deals_get(
        datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0), datetime.now(UTC)
    )
    if hist is None:
        return

    for deal in hist:
        if deal.magic != MAGIC:
            continue
        if deal.entry != mt5.DEAL_ENTRY_OUT:  # only closed deals
            continue
        profit = deal.profit
        symbol = deal.symbol
        emoji = "✅" if profit >= 0 else "❌"
        _notify_closed_key = f"{deal.ticket}"
        if _notify_closed_key in _already_reported:
            continue
        _already_reported.add(_notify_closed_key)

        msg = (
            f"{emoji} TRADE CLOSED — {symbol}\n"
            f"Profit: {'+' if profit >= 0 else ''}{profit:.2f} USD\n"
            f"Ticket: #{deal.ticket}"
        )
        tg(msg)
        print(f"[CLOSED] {symbol}  profit={profit:.2f}  ticket={deal.ticket}")


_already_reported: set = set()


# ═══════════════════════════════════════════════════════════════════
# SIGNAL FETCHER
# ═══════════════════════════════════════════════════════════════════


def fetch_signals(asset: str) -> list:
    url = SIGNAL_URLS.get(asset.upper())
    if not url:
        return []
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[FETCH] {asset}: {e}")
    return []


# Max gap between a signal's stored entry and the live price for the signal
# to still count as "fresh". Old signals have prices far from the market.
FRESH_ENTRY_BAND = 0.02  # 2 %


def signal_tradeable(sig: dict, symbol: str) -> tuple:
    """Return (ok, reason).

    Only trade a signal that is still FRESH — its stored entry is near the
    current price — AND whose SL/TP sit on the correct sides of the live
    price. Stale signals (old prices) are skipped here instead of being
    sent to MT5, which would reject them ('invalid stops') and spam alerts.
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, "no live price"
    px = (tick.ask + tick.bid) / 2.0

    tp = sig.get("trade_params", {}) or {}
    entry = float(tp.get("entry", sig.get("entry", 0)) or 0)
    sl = float(tp.get("sl", sig.get("sl", 0)) or 0)
    t2 = float(tp.get("t2", sig.get("target", 0)) or 0)
    direction = sig.get("direction", "LONG")

    if not (entry and sl and t2):
        return False, "missing price levels"
    if abs(px - entry) / px > FRESH_ENTRY_BAND:
        return False, f"stale (entry {entry} vs market {px:.2f})"
    if direction == "LONG" and not (sl < px < t2):
        return False, "SL/TP invalid for LONG at current price"
    if direction == "SHORT" and not (t2 < px < sl):
        return False, "SL/TP invalid for SHORT at current price"
    return True, "fresh"


# ═══════════════════════════════════════════════════════════════════
# LOCAL 15m / 5m SIGNAL GENERATION  (user-requested fast strategy)
# ═══════════════════════════════════════════════════════════════════

# How tight the stop can be (cap), per asset
_SL_CAP = {"GOLD": 0.01, "BTC": 0.02, "XAUUSD": 0.01, "BTCUSD": 0.02}


def _mt5_df(symbol: str, timeframe, n: int = 160):
    """Pull recent candles from MT5 as a lowercase OHLCV DataFrame."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if rates is None or len(rates) < 50:
        return None
    df = pd.DataFrame(rates).rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]].astype(float)


# Per-asset timeframe + fixed stop (read from mt5_config.json "asset_config").
_TF_MAP = {"M5": None, "M15": None, "M30": None, "H1": None}  # filled at runtime


_HTF_MAP = {"M30": "M30", "H1": "H1", "H4": "H4"}


def _asset_cfg(asset: str) -> dict:
    defaults = {
        "GOLD": {"timeframe": "M5", "trend_tf": "H1"},
        "BTC": {"timeframe": "M15", "trend_tf": "H4"},
    }
    a = CFG.get("asset_config", {}).get(asset, {})
    d = defaults.get(asset, {"timeframe": "M15", "trend_tf": "H4"})
    return {
        "timeframe": a.get("timeframe", d["timeframe"]),
        "trend_tf": a.get("trend_tf", d["trend_tf"]),
    }


def _htf_trend_up(symbol: str, tf_name: str):
    """Higher-timeframe trend via EMA50: True=up, False=down, None=unknown."""
    tf_map = {"M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
    mt5.symbol_select(symbol, True)
    df = _mt5_df(symbol, tf_map.get(tf_name, mt5.TIMEFRAME_H1), 120)
    if df is None or len(df) < 55:
        return None
    ema = df["close"].ewm(span=50, adjust=False).mean()
    return float(df["close"].iloc[-1]) > float(ema.iloc[-1])


def generate_local_signal(symbol: str, asset: str) -> dict | None:
    """
    Per-asset setup: detect structure on the asset's timeframe (Gold=M5,
    BTC=M15), confirmed by FVG or liquidity sweep, and ALIGNED with the
    higher-timeframe trend (Gold 1H / BTC 4H — backtested most profitable).
      Entry  : current price
      Stop   : at the structure ORDER BLOCK (capped); risk per trade still
               fixed at 2% of balance via lot sizing -> capital protected.
      Target : DYNAMIC -> next structure level (recent 50-bar extreme),
               falling back to 3R if that level is < 1.5R away.
    """
    if not _SMC_OK:
        return None
    tf_map = {
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
    }
    acfg = _asset_cfg(asset)
    tf = tf_map.get(acfg["timeframe"], mt5.TIMEFRAME_M15)
    cap = _SL_CAP.get(asset, 0.02)

    # Ensure symbol is subscribed in Market Watch (silent fail otherwise)
    mt5.symbol_select(symbol, True)

    df = _mt5_df(symbol, tf, 160)
    if df is None:
        print(
            f"[{asset}] SKIP: no candles from MT5 ({symbol} {acfg['timeframe']}) — "
            f"check symbol name & Market Watch"
        )
        return None

    st = detect_bos_choch(df, left=2, right=2)
    if not (st["bos"] or st["choch"]) or not st["direction"]:
        print(f"[{asset}] SKIP: no BOS/CHoCH on {acfg['timeframe']}")
        return None
    direction = st["direction"]

    # ── Higher-timeframe TREND FILTER (only trade with the bigger trend) ──
    up = _htf_trend_up(symbol, acfg["trend_tf"])
    if up is not None and ((direction == "LONG" and not up) or (direction == "SHORT" and up)):
        print(
            f"[{asset}] SKIP: {direction} blocked by {acfg['trend_tf']} trend "
            f"(EMA50 trend={'UP' if up else 'DOWN'})"
        )
        return None

    ob = detect_order_block(df, direction)
    if not ob["valid"]:
        print(f"[{asset}] SKIP: no unmitigated OB for {direction} on {acfg['timeframe']}")
        return None

    fvg = detect_fvg(df, direction)
    swept, _lvl = detect_liquidity_sweep(df, direction)
    if not (fvg["valid"] or swept):
        print(f"[{asset}] SKIP: no FVG or liquidity sweep for {direction}")
        return None

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"[{asset}] SKIP: no tick data for {symbol}")
        return None
    price = tick.ask if direction == "LONG" else tick.bid
    # Minimum stop distance: at least 3x the live spread (stops placed
    # inside/near a widened spread get rejected by the broker — this could
    # silently kill GOLD entries at night) and never under 0.05% of price.
    spread = max(tick.ask - tick.bid, 0.0)
    min_dist = max(3.0 * spread, price * 0.0005)

    DYN_LB = 50
    if direction == "LONG":
        sl = min(ob["low"] * 0.999, price - min_dist)  # structure stop
        if (price - sl) / price > cap:
            sl = price * (1 - cap)
        sl = min(sl, price - min_dist)
        risk = price - sl
        struct = float(df["high"].iloc[-DYN_LB:].max())
        target = struct if (struct - price) / risk >= 1.5 else price + 3 * risk
    else:
        sl = max(ob["high"] * 1.001, price + min_dist)  # structure stop
        if (sl - price) / price > cap:
            sl = price * (1 + cap)
        sl = max(sl, price + min_dist)
        risk = sl - price
        struct = float(df["low"].iloc[-DYN_LB:].min())
        target = struct if (price - struct) / risk >= 1.5 else price - 3 * risk

    if risk <= 0:
        return None

    return {
        "asset": asset,
        "direction": direction,
        "entry": round(price, 2),
        "sl": round(sl, 2),
        "target": round(target, 2),
        "id": f"{asset}-{acfg['timeframe']}",
        "score": acfg["timeframe"],
        "trade_params": {},
    }


def close_expired_positions(symbol: str, max_hours: float):
    """Force-close our positions older than max_hours (time-based exit)."""
    pos = mt5.positions_get(symbol=symbol)
    if not pos:
        return
    tick = mt5.symbol_info_tick(symbol)
    now = tick.time if tick else int(time.time())
    for p in pos:
        if p.magic != MAGIC:
            continue
        age_h = (now - p.time) / 3600.0
        if age_h < max_hours:
            continue
        otype = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
        price = tick.bid if p.type == 0 else tick.ask
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": p.volume,
            "type": otype,
            "position": p.ticket,
            "price": price,
            "deviation": 30,
            "magic": MAGIC,
            "comment": "time-exit",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"[TIME-EXIT] closed {symbol} after {age_h:.1f}h  P&L={p.profit:.2f}")
            tg(f"⏱ Time-exit: closed {symbol} after {max_hours}h\nP&L: {p.profit:+.2f} USD")


# ═══════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════


class _Tee:
    """Mirror stdout to mt5_trader.log so the live loop is always inspectable."""

    def __init__(self, stream, path="mt5_trader.log"):
        self._s = stream
        self._f = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, text):
        self._s.write(text)
        with contextlib.suppress(Exception):
            self._f.write(text)

    def flush(self):
        self._s.flush()
        with contextlib.suppress(Exception):
            self._f.flush()


def recent_loss_cooldown(symbol: str, cooldown_min: float) -> float:
    """Minutes remaining in cooldown after the most recent losing close on
    symbol (our magic only). 0 = free to trade. Stops rapid-fire re-entry
    after a stop-out (29-Jun style bleed)."""
    if cooldown_min <= 0:
        return 0.0
    now = datetime.now(UTC)
    deals = mt5.history_deals_get(now - timedelta(minutes=cooldown_min + 5), now)
    if not deals:
        return 0.0
    last_loss = None
    for d in deals:
        if (
            d.magic == MAGIC
            and d.symbol == symbol
            and d.entry == mt5.DEAL_ENTRY_OUT
            and (d.profit + d.swap + d.commission) < 0
        ):
            last_loss = max(last_loss or 0, d.time)
    if not last_loss:
        return 0.0
    elapsed_min = (now.timestamp() - last_loss) / 60.0
    return max(0.0, cooldown_min - elapsed_min)


def main():
    sys.stdout = _Tee(sys.stdout)
    print("=" * 60)
    print("  MT5 Auto-Trader — Gold + Bitcoin")
    print("  Press Ctrl+C to stop")
    print("=" * 60)

    if not connect():
        print("[MT5] Could not connect. Is MT5 terminal open and logged in?")
        sys.exit(1)

    traded_ids: set = set()  # signal IDs already traded this session (github mode)
    assets = CFG.get("assets", ["GOLD", "BTC"])
    max_pos = CFG.get("max_positions_per_asset", 1)
    mode = CFG.get("strategy_mode", "github")  # "local_15m" or "github"
    max_hold = float(CFG.get("max_hold_hours", 4))  # time-based exit (hours)

    print(f"\n[BOT] Watching assets: {assets}")
    print(f"[BOT] Strategy mode: {mode}  |  Max hold: {max_hold}h")
    print(
        f"[BOT] Risk per trade: {CFG.get('risk_pct', 1.0)}%  |  TP: {CFG.get('tp_r_multiple', 2.0)}R"
    )
    print(f"[BOT] Max positions per asset: {max_pos}  |  Polling every {POLL_SEC}s\n")

    while True:
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        print(f"[{now.strftime('%H:%M:%S IST')}] Polling ({mode})...")

        for asset in assets:
            try:
                symbol = SYMBOL_MAP.get(asset, asset)

                # Check if MT5 is still connected
                if not mt5.terminal_info():
                    print("[MT5] Lost connection — reconnecting...")
                    if not connect():
                        time.sleep(30)
                        continue

                # Time-based exit: close anything held longer than max_hold hours
                if max_hold > 0:
                    close_expired_positions(symbol, max_hold)

                # One position per asset
                if count_open_positions(symbol) >= max_pos:
                    print(f"[{asset}] position already open — skip")
                    continue

                # Cooldown after a stop-loss: block immediate re-entry
                cd = recent_loss_cooldown(symbol, float(CFG.get("loss_cooldown_min", 45)))
                if cd > 0:
                    print(f"[{asset}] loss cooldown — {cd:.0f} min left")
                    continue

                # ── Signal selection ─────────────────────────────────────
                if mode == "local_15m":
                    sig = generate_local_signal(symbol, asset)
                    if sig is None:
                        print(f"[{asset}] no 15m setup")
                        continue
                else:
                    signals = fetch_signals(asset)
                    new_signals = [
                        s
                        for s in (signals or [])
                        if s.get("status") == "OPEN" and s.get("id") not in traded_ids
                    ]
                    if not new_signals:
                        print(f"[{asset}] no new signals")
                        continue
                    new_signals.sort(key=lambda x: x.get("score", 0), reverse=True)
                    sig = None
                    for cand in new_signals:
                        ok, why = signal_tradeable(cand, symbol)
                        if ok:
                            sig = cand
                            break
                        traded_ids.add(cand.get("id"))
                        print(f"[{asset}] skip #{cand.get('id')}: {why}")
                    if sig is None:
                        print(f"[{asset}] no fresh tradeable signal")
                        continue
                    traded_ids.add(sig.get("id"))

                print(
                    f"[{asset}] SETUP {sig['direction']}  entry={sig.get('entry')}  sl={sig.get('sl')}"
                )
                if place_order(sig):
                    print(f"[{asset}] trade placed")
                else:
                    print(f"[{asset}] trade failed")
            except Exception as e:
                # One asset's error must never silently kill the other's trading
                print(f"[{asset}] LOOP ERROR: {e}")

        report_closed_trades()
        time.sleep(POLL_SEC)


# ═══════════════════════════════════════════════════════════════════
# CONFIG FILE GENERATOR
# ═══════════════════════════════════════════════════════════════════


def generate_config():
    """Run this once to create your mt5_config.json."""
    sample = {
        "_instructions": "Fill in your MT5 demo account details below",
        "login": 12345678,
        "password": "YourDemoPassword",
        "server": "XMGlobal-Demo",
        "path": "",
        "risk_pct": 1.0,
        "telegram_token": "your_bot_token_here",
        "telegram_chat_id": "your_chat_id_here",
        "github_user": "lavakus",
        "github_repo": "nse-intraday-bot",
        "assets": ["GOLD", "BTC"],
        "max_positions_per_asset": 1,
        "symbol_gold": "XAUUSD",
        "symbol_btc": "BTCUSD",
        "_broker_notes": {
            "XM": "symbol_gold=XAUUSD, symbol_btc=BTCUSD, server=XMGlobal-Demo",
            "ICMarkets": "symbol_gold=XAUUSD, symbol_btc=BTCUSD, server=ICMarketsSC-Demo",
            "Exness": "symbol_gold=XAUUSDm, symbol_btc=BTCUSDm, server=Exness-Trial",
            "Pepperstone": "symbol_gold=XAUUSD, symbol_btc=BTCUSD, server=Pepperstone-Demo",
        },
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=2)
    print(f"✅ Created {CONFIG_FILE} — fill in your details and run: python mt5_trader.py")


if __name__ == "__main__":
    if "--setup" in sys.argv:
        generate_config()
    else:
        main()
