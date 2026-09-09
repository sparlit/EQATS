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
Chart snapshot images for Telegram alerts.
Pure matplotlib candlestick (no mplfinance): last 120 sessions +
EMA10/20/200 + trigger/stop/target lines. Saves PNG, returns path.
"""
import datetime as dt
import os

import matplotlib as mpl

mpl.use("Agg")
import db
import matplotlib.pyplot as plt
import pandas as pd

OUT_DIR = os.path.join("data", "charts")


def render(sym, setup=None, n=120):
    """setup = dict(trigger, stop, target) or None. Returns png path or None."""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, open, high, low, close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT ?", (sym, n)
    ).fetchall()
    if not rows or len(rows) < 30:
        conn.close()
        return None
    rows = list(reversed(rows))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["date"])
    allc = conn.execute("SELECT date, close FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)).fetchall()
    conn.close()
    closes = pd.Series([r[1] for r in allc], index=pd.to_datetime([r[0] for r in allc]))
    e10 = closes.ewm(span=10, adjust=False).mean()
    e20 = closes.ewm(span=20, adjust=False).mean()
    e200 = closes.ewm(span=200, adjust=False).mean()
    df = df.set_index("date")
    e10 = e10.reindex(df.index)
    e20 = e20.reindex(df.index)
    e200 = e200.reindex(df.index)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{sym}_{dt.date.today().isoformat()}.png")

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=110)
    fig.patch.set_facecolor("#0b1020")
    ax.set_facecolor("#0b1020")
    width = 0.6
    for i, (_d, r) in enumerate(df.iterrows()):
        color = "#22c55e" if r["close"] >= r["open"] else "#ef4444"
        ax.vlines(i, r["low"], r["high"], color=color, linewidth=0.8)
        ax.add_patch(
            plt.Rectangle(
                (i - width / 2, min(r["open"], r["close"])),
                width,
                max(1e-9, abs(r["close"] - r["open"])),
                facecolor=color,
                edgecolor="none",
            )
        )
    xs = range(len(df))
    ax.plot(xs, e10.values, color="#60a5fa", linewidth=1.1, label="EMA10")
    ax.plot(xs, e20.values, color="#f59e0b", linewidth=1.1, label="EMA20")
    ax.plot(xs, e200.values, color="#a78bfa", linewidth=1.1, label="EMA200")
    if setup:
        ax.axhline(setup["trigger"], color="#22c55e", linestyle="--", linewidth=1.2)
        ax.axhline(setup["stop"], color="#ef4444", linestyle="--", linewidth=1.2)
        ax.axhline(setup["target"], color="#60a5fa", linestyle=":", linewidth=1.2)
        ax.text(len(df) - 1, setup["trigger"], " trigger", color="#22c55e", fontsize=8, va="bottom")
        ax.text(len(df) - 1, setup["stop"], " stop", color="#ef4444", fontsize=8, va="top")
        ax.text(len(df) - 1, setup["target"], " target", color="#60a5fa", fontsize=8, va="bottom")
    step = max(1, len(df) // 6)
    ticks = list(range(0, len(df), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([df.index[i].strftime("%d-%b") for i in ticks], color="#9fb0cc", fontsize=8)
    ax.tick_params(colors="#9fb0cc", labelsize=8)
    for s in ax.spines.values():
        s.set_color("#2a3550")
    ax.set_title(f"{sym} · {df.index[-1].strftime('%d %b %Y')}", color="#edf3ff", fontsize=12, fontweight="bold")
    ax.legend(loc="upper left", fontsize=7, facecolor="#0b1020", edgecolor="#2a3550", labelcolor="#9fb0cc")
    ax.grid(color="#1c2440", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


if __name__ == "__main__":
    import sys

    s = sys.argv[1].upper() if len(sys.argv) > 1 else "RELIANCE"
    print(render(s))
