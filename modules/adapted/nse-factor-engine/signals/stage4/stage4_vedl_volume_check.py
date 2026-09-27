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


import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine/"
prices = pd.read_parquet(BASE + "data/prices.parquet")

vedl = prices[prices["symbol"] == "VEDL"].sort_values("date")

print("=" * 60)
print("VEDL full volume series stats, pre vs post 2026-04-30")
print("=" * 60)

pre_split = vedl[vedl["date"] < "2026-04-30"]
post_split = vedl[vedl["date"] >= "2026-04-30"]

print(f"Pre-split (n={len(pre_split)}):")
print(pre_split["volume"].describe())
print()
print(f"Post-split (n={len(post_split)}):")
print(post_split["volume"].describe())
print()
print(
    "Ratio of post-split mean volume / pre-split mean volume:", post_split["volume"].mean() / pre_split["volume"].mean()
)

print()
print("=" * 60)
print("Day-by-day around the split (2026-04-23 to 2026-05-07)")
print("=" * 60)
window = vedl[(vedl["date"] >= "2026-04-23") & (vedl["date"] <= "2026-05-07")]
print(window[["date", "open", "high", "low", "close", "volume"]].to_string(index=False))

print()
print("=" * 60)
print("Close price level shift check (the actual split signature)")
print("=" * 60)
print("Last close before 2026-04-30:", pre_split["close"].iloc[-1] if len(pre_split) else "n/a")
print("First close on/after 2026-04-30:", post_split["close"].iloc[0] if len(post_split) else "n/a")
