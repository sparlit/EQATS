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


import os
import time

import numpy as np
import pandas as pd
import requests
from scipy.signal import argrelextrema

STOCKS = ["RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY", "SBIN"]
RANGE = "2y"
ORDER = 5  # bars each side to confirm a pivot
TOL = 0.005  # 0.5% zone width
MIN_TOUCH = 2  # min touches to count as a level
NEAR = 0.5  # % distance to flag near a level
BUFFER = 0.3  # % close beyond level to count as breakout/breakdown
SPIKE = 2.0  # volume multiple for VOL-SPIKE

TG_TOKEN = os.environ.get("TG_TOKEN", "PASTE_BOT_TOKEN")
TG_CHAT = os.environ.get("TG_CHAT", "PASTE_CHAT_ID")


def send_tg(text):
    if "PASTE" in TG_TOKEN or "PASTE" in TG_CHAT:
        print("Telegram not set, skipping")
        return
    r = requests.post(
        "https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage", data={"chat_id": TG_CHAT, "text": text}, timeout=15
    )
    print("Telegram", r.status_code)


def get_df(sym):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + sym + ".NS"
    r = requests.get(url, params={"range": RANGE, "interval": "1d"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    if r.status_code != 200:
        return None
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    return pd.DataFrame(
        {"High": q["high"], "Low": q["low"], "Close": q["close"], "Volume": q["volume"]},
        index=pd.to_datetime(res["timestamp"], unit="s"),
    ).dropna()


def get_levels(df):
    hi = df["High"].values
    lo = df["Low"].values
    ih = argrelextrema(hi, np.greater_equal, order=ORDER)[0]
    il = argrelextrema(lo, np.less_equal, order=ORDER)[0]
    pts = sorted([hi[i] for i in ih] + [lo[i] for i in il])
    zones = []
    for p in pts:
        if zones and abs(p - np.mean(zones[-1])) / np.mean(zones[-1]) <= TOL:
            zones[-1].append(p)
        else:
            zones.append([p])
    return [(round(float(np.mean(z)), 2), len(z)) for z in zones if len(z) >= MIN_TOUCH]


alerts = []
asof = ""

for s in STOCKS:
    try:
        df = get_df(s)
        if df is None or len(df) < 100:
            print(s, "no data")
            continue
        asof = df.index[-1].strftime("%d %b")
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        vr = float(df["Volume"].iloc[-1] / df["Volume"].iloc[-21:-1].mean())
        lv = get_levels(df)
        sup = [l for l in lv if l[0] < last]
        rsn = [l for l in lv if l[0] >= last]
        tag = ""
        if sup:
            L = sup[-1][0]
            d = (last - L) / last * 100
            if prev < L and BUFFER <= d <= 1.5:
                tag += f" BREAKOUT above {L}"
            elif d <= NEAR:
                tag += f" NEAR-S {L} ({sup[-1][1]}x)"
        if rsn:
            L = rsn[0][0]
            d = (L - last) / last * 100
            if prev > L and BUFFER <= d <= 1.5:
                tag += f" BREAKDOWN below {L}"
            elif d <= NEAR:
                tag += f" NEAR-R {L} ({rsn[0][1]}x)"
        if last <= df["Low"].min() * 1.005:
            tag += " AT-2Y-LOW"
        if last >= df["High"].max() * 0.995:
            tag += " AT-2Y-HIGH"
        if tag and vr >= 1.5:
            tag += " HIGH-VOL"
        elif vr >= SPIKE:
            tag += " VOL-SPIKE"
        line = f"{s} {last:.1f} vol {vr:.1f}x{tag}"
        print(line)
        if tag:
            alerts.append(line)
    except Exception as e:
        print(s, "error", e)
    time.sleep(1)

if alerts:
    send_tg("S/R scan " + asof + "\n" + "\n".join(alerts))
else:
    print("No flags today")
