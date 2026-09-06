import sys
import db

def ema(vals, period):
    out = []
    k = 2 / (period + 1)
    e = vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def compute(closes, highs, lows, vols):
    c = closes
    e9 = ema(c, 9)
    e21 = ema(c, 21)
    e50 = ema(c, 50)
    e12 = ema(c, 12)
    e26 = ema(c, 26)
    macd = [a - b for a, b in zip(e12, e26)]
    sig = ema(macd, 9)
    hist = [m - s for m, s in zip(macd, sig)]
    trs = []
    for i in range(1, len(c)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - c[i - 1]), abs(lows[i] - c[i - 1]))
        trs.append(tr)
    atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else None
    gains = losses = 0.0
    for i in range(len(c) - 14, len(c)):
        ch = c[i] - c[i - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    rsi = 100.0 if losses == 0 else 100 - (100 / (1 + gains / losses))
    vol20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else 0
    vol_ratio = vols[-1] / vol20 if vol20 else 0
    return dict(e9=e9[-1], e21=e21[-1], e50=e50[-1],
                hist=hist[-1], hist_prev=hist[-2], atr=atr, rsi=rsi,
                vol_ratio=vol_ratio,
                high20=max(highs[-20:]), low20=min(lows[-20:]))

def swing(symbol):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT close, high, low, volume FROM prices_daily "
        "WHERE symbol=? ORDER BY date DESC LIMIT 120",
        (symbol,)).fetchall()
    conn.close()
    rows = [r for r in rows if r[0] is not None]
    if len(rows) < 60:
        return None
    rows = list(reversed(rows))
    closes = [r[0] for r in rows]
    highs = [r[1] if r[1] else r[0] for r in rows]
    lows = [r[2] if r[2] else r[0] for r in rows]
    vols = [r[3] or 0 for r in rows]
    ind = compute(closes, highs, lows, vols)
    price = closes[-1]
    score = 0
    notes = []
    if ind["e9"] > ind["e21"] > ind["e50"] and price > ind["e9"]:
        score += 30
        notes.append("perfect EMA stack")
    elif ind["e9"] > ind["e21"] and price > ind["e21"]:
        score += 20
        notes.append("short uptrend")
    elif price < ind["e50"]:
        notes.append("below EMA50")
    else:
        score += 10
    if ind["hist"] > 0 and ind["hist"] > ind["hist_prev"]:
        score += 25
        notes.append("MACD rising")
    elif ind["hist"] > 0:
        score += 15
    elif ind["hist"] > ind["hist_prev"]:
        score += 10
        notes.append("MACD turning")
    if 55 <= ind["rsi"] <= 70:
        score += 20
    elif 50 <= ind["rsi"] < 55 or 70 < ind["rsi"] <= 75:
        score += 12
    elif ind["rsi"] > 75:
        score += 4
        notes.append("overbought")
    else:
        score += 6
    if price >= ind["high20"] * 0.98:
        score += 15
        notes.append("at 20-day high")
    elif price >= ind["high20"] * 0.95:
        score += 8
    if ind["vol_ratio"] >= 1.5:
        score += 10
        notes.append("volume confirmed")
    stop = ind["low20"]
    if ind["atr"]:
        stop = min(ind["low20"], price - 2 * ind["atr"])
    entry_low = ind["e21"] * 0.99
    entry_high = price
    risk = entry_high - stop
    target = price + 2 * risk if risk > 0 else price * 1.1
    rr = (target - price) / risk if risk > 0 else 0
    return dict(symbol=symbol, price=round(price, 1), score=score,
                notes=notes, entry=(round(entry_low, 1),
                round(entry_high, 1)), stop=round(stop, 1),
                target=round(target, 1), rr=round(rr, 1),
                rsi=round(ind["rsi"], 1),
                atr_pct=round(100 * ind["atr"] / price, 1)
                if ind["atr"] else None)

def scan_top(limit=15):
    conn = db.get_conn()
    syms = [r[0] for r in conn.execute(
        "SELECT symbol FROM stocks WHERE active=1")]
    conn.close()
    out = []
    for s in syms:
        r = swing(s)
        if r:
            out.append(r)
    out.sort(key=lambda x: -x["score"])
    return out[:limit]

if len(sys.argv) > 2 and sys.argv[1] == "run":
    for s in sys.argv[2:]:
        print(swing(s.upper()))
elif len(sys.argv) > 1 and sys.argv[1] == "scan":
    for r in scan_top():
        print(f"{r['symbol']:<12} {r['score']:>3}  "
              f"entry {r['entry']}  stop {r['stop']}  "
              f"tgt {r['target']}  R:R {r['rr']}  "
              f"{' ; '.join(r['notes'])}")