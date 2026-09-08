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


"""Funnel diagnostics: counts screener passes and setup failure reasons."""
import db
import pandas as pd
from scanner import Screener
from setup import SetupDetector

from main import DEFAULT_UNIVERSE


def load(sym):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date",
        (sym.split(".")[0],),
    ).fetchall()
    conn.close()
    if not rows:
        return None
    df = pd.DataFrame(list(rows), columns=["date", "Open", "High", "Low", "Close", "Volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
    return df


screen_pass = 0
triggered = 0
reason_counts = {}

for sym in DEFAULT_UNIVERSE:
    df = load(sym)
    if df is None or len(df) < 300:
        continue
    for i in range(280, len(df), 5):
        hist = df.iloc[:i]
        sc = Screener.evaluate(hist, sym)
        if not sc.passed:
            continue
        screen_pass += 1
        st = SetupDetector.detect(hist, sym)
        if st.triggered:
            triggered += 1
            print(f"   ✅ {sym} on {hist.index[-1].date()} entry {st.entry_price} stop {st.stop_loss}")
        else:
            for r in st.reasons:
                key = r[:45]
                reason_counts[key] = reason_counts.get(key, 0) + 1

print(f"\nscreener passes: {screen_pass}")
print(f"setups triggered: {triggered}")
print("\nTOP FAILURE REASONS:")
for k, v in sorted(reason_counts.items(), key=lambda x: -x[1])[:10]:
    print(f"   {v:>5}  {k}")
