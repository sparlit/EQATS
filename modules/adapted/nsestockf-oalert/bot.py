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


# bot.py - FINAL BOX B - WITH YOUR 5 SETTINGS
import contextlib
import os
import time
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf
from stocks import ALL_STOCKS

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TIMEFRAME = os.getenv("TIMEFRAME", "5m")
CHANNEL_WIDTH = int(os.getenv("CHANNEL_WIDTH", "5"))
PERIOD = os.getenv("PERIOD", "5d")

PIVOT_LEN = 20
VOLUME_MULT = 1.0
MOVEMENT_MIN = 0.3
NEAR_PCT = 1.0

print(
    f"SETTINGS -> TF:{TIMEFRAME} Period:{PERIOD} Width:{CHANNEL_WIDTH}% | PIVOT:{PIVOT_LEN} VOLx{VOLUME_MULT} MOV>{MOVEMENT_MIN}% NEAR:{NEAR_PCT}%",
    flush=True,
)


def is_market_open():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    if now.weekday() >= 5:
        return False
    return now.replace(hour=9, minute=15) <= now <= now.replace(hour=15, minute=35)


def send(msg):
    with contextlib.suppress(BaseException):
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )


def get_box_b(df):
    pivots = []
    for i in range(PIVOT_LEN, len(df) - PIVOT_LEN):
        if df["High"].iloc[i] == df["High"].iloc[i - PIVOT_LEN : i + PIVOT_LEN + 1].max():
            pivots.append(df["High"].iloc[i])
        if df["Low"].iloc[i] == df["Low"].iloc[i - PIVOT_LEN : i + PIVOT_LEN + 1].min():
            pivots.append(df["Low"].iloc[i])
    pivots = pivots[-50:]
    if len(pivots) < 6:
        return None
    cwidth = (df["High"].tail(300).max() - df["Low"].tail(300).min()) * CHANNEL_WIDTH / 100
    boxes = []
    temp = pivots.copy()
    for _ in range(10):
        if not temp:
            break
        hi = temp[0]
        cluster = [p for p in temp if abs(p - hi) <= cwidth]
        if cluster:
            boxes.append((min(cluster), max(cluster)))
            temp = [p for p in temp if p not in cluster]
    boxes = sorted(boxes, key=lambda x: (x[0] + x[1]) / 2)[:6]
    if len(boxes) < 4:
        return None
    return boxes[1][0], boxes[1][1], boxes[-2][0], boxes[-2][1]


if not is_market_open():
    exit(0)

for sym in ALL_STOCKS:
    try:
        df = yf.Ticker(sym).history(period=PERIOD, interval=TIMEFRAME, auto_adjust=True)
        if df.empty or len(df) < 150:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        res = get_box_b(df)
        if not res:
            continue
        b_lo, b_hi, s_lo, s_hi = res
        last = df["Close"].iloc[-1]
        prev = df["Close"].iloc[-2]

        # Aapki 5 settings ka filter
        avg_vol = df["Volume"].tail(20).mean()
        vol_ratio = df["Volume"].iloc[-1] / avg_vol if avg_vol > 0 else 0
        mov = abs(last - prev) / prev * 100 if prev > 0 else 0
        if mov < MOVEMENT_MIN:
            continue
        if vol_ratio < VOLUME_MULT:
            continue

        # Near check
        dist_to_box = abs(last - b_hi) / last * 100

        if prev <= b_hi and last > b_hi:
            send(
                f"🔥 *BREAKOUT* [{TIMEFRAME}]\n`{sym}` LTP: {last:.2f} ({mov:.1f}%)\nBox: {b_lo:.2f}-{b_hi:.2f} Vol:{vol_ratio:.1f}x"
            )
        elif prev >= s_lo and last < s_lo:
            send(
                f"💣 *BREAKDOWN* [{TIMEFRAME}]\n`{sym}` LTP: {last:.2f}\nBox: {s_lo:.2f}-{s_hi:.2f}"
            )
        elif dist_to_box <= NEAR_PCT and last < b_hi:
            send(
                f"⚠️ *NEAR BOX* [{TIMEFRAME}]\n`{sym}` LTP: {last:.2f} Box: {b_hi:.2f} ({dist_to_box:.2f}% away) Vol:{vol_ratio:.1f}x"
            )

        time.sleep(0.3)
    except:
        continue
