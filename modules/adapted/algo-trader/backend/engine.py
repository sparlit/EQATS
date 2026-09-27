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


from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")


# ── Data ─────────────────────────────────────────────────────────────────────


def _to_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise columns from either yf.download (MultiIndex) or Ticker.history (simple)."""
    df = df.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    # history() includes 'dividends' / 'stock splits' — drop anything extra
    keep = [c for c in ["open", "close", "high", "low", "volume"] if c in df.columns]
    return df[keep].dropna()


def fetch(
    ticker: str, days: int | None = None, start: str | None = None, end: str | None = None, interval: str | None = None
) -> tuple:
    """
    Fetch OHLCV data. Auto-selects interval based on range:
      ≤ 7 days  → 1-minute bars  (intraday)
      ≤ 60 days → 5-minute bars  (short-term)
      > 60 days → daily bars

    Returns (df, interval) tuple.
    """
    t = yf.Ticker(ticker)

    if start and end:
        end_buf = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        delta_days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    else:
        end_dt = datetime.today() + timedelta(days=1)
        start_dt = end_dt - timedelta(days=int(days or 730) + 1)
        start = start_dt.strftime("%Y-%m-%d")
        end_buf = end_dt.strftime("%Y-%m-%d")
        delta_days = int(days or 730)

    # yfinance hard limits: 1m→7d, intraday (2m/5m/15m/30m)→60d, daily→unlimited
    _MAX_DAYS = {"1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60}
    if interval is None:
        if delta_days <= 7:
            interval = "1m"
        elif delta_days <= 60:
            interval = "5m"
        else:
            interval = "1d"
    elif interval in _MAX_DAYS and delta_days > _MAX_DAYS[interval]:
        # Requested interval can't cover the range — fall back automatically
        interval = "5m" if delta_days <= 60 else "1d"

    df = t.history(start=start, end=end_buf, interval=interval, auto_adjust=True)
    if df.empty:
        msg = f"No data found for {ticker!r}. Check the ticker symbol."
        raise ValueError(msg)

    df = _to_ohlcv(df)

    # For intraday, convert index to IST so times are readable
    if interval in ("1m", "5m"):
        if df.index.tzinfo is not None:
            df.index = df.index.tz_convert(IST)
        else:
            df.index = df.index.tz_localize("UTC").tz_convert(IST)

    return df, interval


def fetch_intraday(ticker: str, interval: str = "1m") -> pd.DataFrame:
    """Fetch the most recent trading day's intraday data, converted to IST."""
    df = yf.Ticker(ticker).history(period="2d", interval=interval, auto_adjust=True)
    if df.empty:
        msg = f"No intraday data for {ticker!r}."
        raise ValueError(msg)
    df = _to_ohlcv(df)
    # Convert index to IST
    if df.index.tzinfo is not None:
        df.index = df.index.tz_convert(IST)
    else:
        df.index = df.index.tz_localize("UTC").tz_convert(IST)
    # Keep only the latest trading day
    last_date = df.index[-1].date()
    return df[df.index.date == last_date]


def market_status() -> dict:
    now = datetime.now(IST)
    mo = now.replace(hour=9, minute=15, second=0, microsecond=0)
    mc = now.replace(hour=15, minute=30, second=0, microsecond=0)

    if now.weekday() >= 5:
        return {
            "open": False,
            "label": "CLOSED",
            "detail": "Weekend  ·  Opens Monday 9:15 AM IST",
            "color": "#f85149",
            "time": now.strftime("%H:%M IST"),
        }
    if now < mo:
        mins = int((mo - now).total_seconds() // 60)
        h, m = divmod(mins, 60)
        return {
            "open": False,
            "label": "PRE-MARKET",
            "detail": f"Opens in {h}h {m}m  ·  9:15 AM IST",
            "color": "#d29922",
            "time": now.strftime("%H:%M IST"),
        }
    if now > mc:
        return {
            "open": False,
            "label": "CLOSED",
            "detail": "Closed  ·  Opens tomorrow 9:15 AM IST",
            "color": "#f85149",
            "time": now.strftime("%H:%M IST"),
        }

    secs = int((mc - now).total_seconds())
    h, m = divmod(secs // 60, 60)
    return {
        "open": True,
        "label": "OPEN",
        "detail": f"Closes in {h}h {m}m  ·  3:30 PM IST",
        "color": "#3fb950",
        "time": now.strftime("%H:%M IST"),
    }


# ── Indicators ────────────────────────────────────────────────────────────────


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ── Strategies ────────────────────────────────────────────────────────────────


def apply_crossover(df: pd.DataFrame, fast=12, slow=26) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = ema(df["close"], fast)
    df["ema_slow"] = ema(df["close"], slow)
    prev_fast = df["ema_fast"].shift(1)
    prev_slow = df["ema_slow"].shift(1)
    df["signal"] = 0
    df.loc[(df["ema_fast"] > df["ema_slow"]) & (prev_fast <= prev_slow), "signal"] = 1
    df.loc[(df["ema_fast"] < df["ema_slow"]) & (prev_fast >= prev_slow), "signal"] = -1
    return df.dropna()


def apply_price_vs_ema(df: pd.DataFrame, period=20) -> pd.DataFrame:
    df = df.copy()
    df["ema"] = ema(df["close"], period)
    prev_close = df["close"].shift(1)
    prev_ema = df["ema"].shift(1)
    df["signal"] = 0
    df.loc[(df["close"] > df["ema"]) & (prev_close <= prev_ema), "signal"] = 1
    df.loc[(df["close"] < df["ema"]) & (prev_close >= prev_ema), "signal"] = -1
    return df.dropna()


def apply_rsi(df: pd.DataFrame, period=14, oversold=30, overbought=70) -> pd.DataFrame:
    """Buy when RSI crosses UP through oversold level; sell when crosses DOWN through overbought."""
    df = df.copy()
    df["rsi"] = rsi(df["close"], period)
    prev_rsi = df["rsi"].shift(1)
    df["signal"] = 0
    df.loc[(df["rsi"] > oversold) & (prev_rsi <= oversold), "signal"] = 1
    df.loc[(df["rsi"] < overbought) & (prev_rsi >= overbought), "signal"] = -1
    return df.dropna()


def apply_macd_rsi(df: pd.DataFrame, fast=12, slow=26, signal_p=9, rsi_p=14) -> pd.DataFrame:
    """MACD crossover filtered by RSI — buy only when RSI < 60, sell only when RSI > 40."""
    df = df.copy()
    macd_line = ema(df["close"], fast) - ema(df["close"], slow)
    signal_line = macd_line.ewm(span=signal_p, adjust=False).mean()
    df["rsi"] = rsi(df["close"], rsi_p)
    prev_macd = macd_line.shift(1)
    prev_sig = signal_line.shift(1)
    df["signal"] = 0
    df.loc[(macd_line > signal_line) & (prev_macd <= prev_sig) & (df["rsi"] < 60), "signal"] = 1
    df.loc[(macd_line < signal_line) & (prev_macd >= prev_sig) & (df["rsi"] > 40), "signal"] = -1
    return df.dropna()


def apply_supertrend(df: pd.DataFrame, period=10, multiplier=3.0) -> pd.DataFrame:
    """ATR-based dynamic trend line. Buy when price crosses above, sell when crosses below."""
    df = df.copy()
    mid = (df["high"] + df["low"]) / 2
    band = atr(df, period) * multiplier
    upper_basic = mid + band
    lower_basic = mid - band

    upper = upper_basic.copy()
    lower = lower_basic.copy()
    for i in range(1, len(df)):
        upper.iloc[i] = (
            upper_basic.iloc[i]
            if (upper_basic.iloc[i] < upper.iloc[i - 1] or df["close"].iloc[i - 1] > upper.iloc[i - 1])
            else upper.iloc[i - 1]
        )
        lower.iloc[i] = (
            lower_basic.iloc[i]
            if (lower_basic.iloc[i] > lower.iloc[i - 1] or df["close"].iloc[i - 1] < lower.iloc[i - 1])
            else lower.iloc[i - 1]
        )

    supertrend = pd.Series(np.nan, index=df.index)
    in_uptrend = True
    for i in range(1, len(df)):
        if df["close"].iloc[i] > upper.iloc[i - 1]:
            in_uptrend = True
        elif df["close"].iloc[i] < lower.iloc[i - 1]:
            in_uptrend = False
        supertrend.iloc[i] = lower.iloc[i] if in_uptrend else upper.iloc[i]

    df["supertrend"] = supertrend
    prev_close = df["close"].shift(1)
    prev_st = supertrend.shift(1)
    df["signal"] = 0
    df.loc[(df["close"] > df["supertrend"]) & (prev_close <= prev_st), "signal"] = 1
    df.loc[(df["close"] < df["supertrend"]) & (prev_close >= prev_st), "signal"] = -1
    return df.dropna()


# ── Backtest ──────────────────────────────────────────────────────────────────


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    exit_reason: str = "signal"  # "signal" | "stop_loss" | "take_profit"


def _fmt_dt(dt) -> str:
    """Show date+time for intraday bars, just date for daily bars."""
    if hasattr(dt, "strftime"):
        if hasattr(dt, "hour") and (dt.hour != 0 or dt.minute != 0):
            return dt.strftime("%d %b %H:%M")
        return dt.strftime("%Y-%m-%d")
    return str(dt)


def run_backtest(df: pd.DataFrame, capital: float, stop_loss_pct: float = 0.0, take_profit_pct: float = 0.0) -> dict:
    cash = capital
    position = 0
    entry_price = 0.0
    entry_date = None
    trades: list[Trade] = []
    equity: list[float] = []

    sl_mult = (1 - stop_loss_pct / 100) if stop_loss_pct > 0 else None
    tp_mult = (1 + take_profit_pct / 100) if take_profit_pct > 0 else None

    for date, row in df.iterrows():
        price = float(row["close"])
        signal = int(row["signal"])

        exit_reason: str | None = None

        if position > 0:
            if sl_mult and price <= entry_price * sl_mult:
                exit_reason = "stop_loss"
            elif tp_mult and price >= entry_price * tp_mult:
                exit_reason = "take_profit"
            elif signal == -1:
                exit_reason = "signal"

        if exit_reason:
            pnl = (price - entry_price) * position
            entry_str = _fmt_dt(entry_date)
            exit_str = _fmt_dt(date)
            trades.append(
                Trade(
                    entry_date=entry_str,
                    exit_date=exit_str,
                    entry_price=round(entry_price, 2),
                    exit_price=round(price, 2),
                    shares=position,
                    pnl=round(pnl, 2),
                    pnl_pct=round((price - entry_price) / entry_price * 100, 2),
                    exit_reason=exit_reason,
                )
            )
            cash += position * price
            position = 0

        # Enter only if not just exited on this bar
        if signal == 1 and position == 0 and exit_reason is None:
            shares = int(cash // price)
            if shares > 0:
                position = shares
                entry_price = price
                entry_date = date
                cash -= shares * price

        equity.append(cash + position * price)

    equity_curve = pd.Series(equity, index=df.index)
    final = equity_curve.iloc[-1]
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    dd = (equity_curve - equity_curve.cummax()) / equity_curve.cummax() * 100
    ret = equity_curve.pct_change().dropna()
    sharpe = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0

    win_sum = sum(t.pnl for t in wins)
    loss_sum = abs(sum(t.pnl for t in losses))
    profit_factor = round(win_sum / loss_sum, 2) if loss_sum > 0 else 99.99

    # Max consecutive losses
    max_cl = cl = 0
    for t in trades:
        cl = cl + 1 if t.pnl <= 0 else 0
        max_cl = max(max_cl, cl)

    return {
        "trades": trades,
        "equity": equity_curve,
        "initial": capital,
        "final": final,
        "pnl": final - capital,
        "return_pct": (final - capital) / capital * 100,
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "avg_win": np.mean([t.pnl for t in wins]) if wins else 0,
        "avg_loss": np.mean([t.pnl for t in losses]) if losses else 0,
        "max_drawdown": dd.min(),
        "sharpe": sharpe,
        "profit_factor": profit_factor,
        "max_consec_losses": max_cl,
    }


# ── Terminal report (used by main.py) ────────────────────────────────────────


def print_report(result: dict, ticker: str, strategy: str) -> None:
    r = result
    print(f"\n{'=' * 54}")
    print(f"  {ticker}  |  {strategy}")
    print(f"{'=' * 54}")
    sign = "+" if r["pnl"] >= 0 else ""
    print(f"  Starting Money  : ₹{r['initial']:>12,.2f}")
    print(f"  Ending Money    : ₹{r['final']:>12,.2f}")
    print(f"  Profit / Loss   : ₹{sign}{r['pnl']:>11,.2f}  ({sign}{r['return_pct']:.2f}%)")
    print(f"{'=' * 54}")
    print(f"  Trades {r['total_trades']}  |  Win Rate {r['win_rate']:.1f}%  |  Sharpe {r['sharpe']:.2f}")
    print(f"  Max Drawdown    : {r['max_drawdown']:.2f}%")
    print()


def build_chart(df: pd.DataFrame, result: dict, ticker: str, strategy: str):
    """Used by main.py (terminal mode)."""
    # Imported here so the API server never has to load matplotlib.
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
    fig.suptitle(f"{ticker}  —  {strategy}", fontsize=13, fontweight="bold")
    ax = axes[0]
    ax.plot(df.index, df["close"], color="#222", linewidth=1, label="Price")
    for col in df.columns:
        if col.startswith("ema"):
            lbl = "EMA (fast)" if col == "ema_fast" else "EMA (slow)" if col == "ema_slow" else "EMA"
            ax.plot(df.index, df[col], linewidth=1, linestyle="--", label=lbl)
    ax.scatter(
        df[df["signal"] == 1].index,
        df[df["signal"] == 1]["close"],
        marker="^",
        color="green",
        s=70,
        zorder=5,
        label="Buy",
    )
    ax.scatter(
        df[df["signal"] == -1].index,
        df[df["signal"] == -1]["close"],
        marker="v",
        color="red",
        s=70,
        zorder=5,
        label="Sell",
    )
    ax.set_ylabel("Price (₹)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)
    axes[1].plot(result["equity"].index, result["equity"], color="steelblue", linewidth=1.5)
    axes[1].axhline(result["initial"], color="gray", linestyle="--", linewidth=0.8)
    axes[1].set_ylabel("Portfolio (₹)")
    axes[1].grid(True, alpha=0.25)
    eq = result["equity"]
    dd = (eq - eq.cummax()) / eq.cummax() * 100
    axes[2].fill_between(dd.index, dd, 0, color="crimson", alpha=0.35)
    axes[2].set_ylabel("Drawdown (%)")
    axes[2].grid(True, alpha=0.25)
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate()
    plt.tight_layout()
    return fig
