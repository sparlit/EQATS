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


import datetime
import glob
import gzip
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import pandas as pd
import requests

EMA_LEN, RSI_LEN, VOL_LEN = 50, 14, 20
RSI_LO, RSI_HI = 45, 50
VOL_MULT, LOOKBACK, NEAR_PCT = 1.5, 3, 1.5
MIN_AVG_VOL = 100000
PAGE = "https://johnebe2020-trade.github.io/Nse-scanner/"
TG_HOURS = (10, 13, 15)

TOKEN = os.environ.get("UPSTOX_TOKEN", "")
HDR = {"Accept": "application/json"}
if TOKEN:
    HDR["Authorization"] = f"Bearer {TOKEN}"
BASE = "https://api.upstox.com/v3/historical-candle"
INSTR_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
KEYS = {}


class TokenError(Exception):
    pass


_lock = threading.Lock()
_last = [0.0]


def throttle():
    with _lock:
        wait = 0.17 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def get_candles(url):
    for _ in range(4):
        throttle()
        try:
            r = requests.get(url, headers=HDR, timeout=25)
        except Exception:
            time.sleep(2)
            continue
        if r.status_code == 401:
            raise TokenError()
        if r.status_code == 429:
            time.sleep(30)
            continue
        if r.status_code >= 500:
            time.sleep(2)
            continue
        if r.status_code != 200:
            return None
        try:
            rows = r.json().get("data", {}).get("candles", [])
        except Exception:
            return None
        if not rows:
            return None
        df = pd.DataFrame(rows).iloc[:, :6]
        df.columns = ["ts", "open", "high", "low", "close", "volume"]
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Kolkata")
        return df.set_index("ts").sort_index().astype(float)
    return None


def hist(key, unit, interval, days):
    to = datetime.datetime.now(IST).date()
    frm = to - datetime.timedelta(days=days)
    return get_candles(f"{BASE}/{quote(key, safe='')}/{unit}/{interval}/{to}/{frm}")


def today_candles(key, unit, interval):
    return get_candles(f"{BASE}/intraday/{quote(key, safe='')}/{unit}/{interval}")


def merge(a, b):
    if a is None:
        return b
    if b is None:
        return a
    m = pd.concat([a, b])
    return m[~m.index.duplicated(keep="last")].sort_index()


def to_4h(df):
    d = df.copy()
    d["day"] = d.index.date
    d["blk"] = d.groupby("day").cumcount() // 4
    g = d.groupby(["day", "blk"])
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        }
    )
    ts = d.index.to_series().groupby([d["day"], d["blk"]]).first()
    out.index = pd.DatetimeIndex(ts)
    return out


def check(df):
    if df is None or len(df) < EMA_LEN + 5:
        return None
    c = df["close"]
    ema = c.ewm(span=EMA_LEN, adjust=False).mean()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / RSI_LEN, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / RSI_LEN, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn)
    vr = df["volume"] / df["volume"].rolling(VOL_LEN).mean()
    cx = ((c.shift(1) <= ema.shift(1)) & (c > ema)).tail(LOOKBACK)
    cross = bool(cx.any()) and c.iloc[-1] > ema.iloc[-1]
    cross_ts = cx[cx].index[-1] if cx.any() else None
    vol_ok = vr.tail(LOOKBACK).max() >= VOL_MULT
    r, rp = rsi.iloc[-1], rsi.iloc[-2]
    rsi_ok = RSI_LO <= r <= RSI_HI
    gap = (c.iloc[-1] - ema.iloc[-1]) / ema.iloc[-1] * 100
    near = c.iloc[-1] < ema.iloc[-1] and gap >= -NEAR_PCT and rsi_ok and r > rp
    if cross and vol_ok and rsi_ok:
        return "CROSS", r, gap, cross_ts
    if near:
        return "NEAR", r, gap, None
    return None


def fmt_ts(ts, tf):
    if ts is None:
        return "", 0
    s = ts.strftime("%d %b") if tf == "D" else ts.strftime("%d %b %H:%M")
    return s, int(ts.timestamp())


def monthly_stats(dd, cur):
    m = dd["close"].resample("ME").last().dropna()
    if len(m) < 6:
        return None
    ret = m.pct_change().dropna()
    ups, downs = ret[ret > 0], ret[ret < 0]
    if len(ups) < 2 or len(downs) < 2:
        return None
    up_med, up_p75 = ups.median(), ups.quantile(0.75)
    dn_med = downs.median()
    return {
        "tp1": round(cur * (1 + up_med), 1),
        "tp2": round(cur * (1 + up_p75), 1),
        "sl": round(cur * (1 + dn_med * 0.5), 1),
        "avgup": round(up_med * 100, 1),
        "avgdn": round(dn_med * 100, 1),
        "months": len(ret),
    }


def scan(item):
    sym, sec = item
    key = KEYS.get(sym)
    if not key:
        return []
    dd = hist(key, "days", 1, 400)
    if dd is None or dd["volume"].tail(20).mean() < MIN_AVG_VOL:
        return []
    hh = merge(hist(key, "hours", 1, 60), today_candles(key, "hours", 1))
    if hh is not None:
        t = hh[hh.index.date == datetime.datetime.now(IST).date()]
        if len(t) and dd.index[-1].date() < t.index[-1].date():
            row = pd.DataFrame(
                {
                    "open": [t["open"].iloc[0]],
                    "high": [t["high"].max()],
                    "low": [t["low"].min()],
                    "close": [t["close"].iloc[-1]],
                    "volume": [t["volume"].sum()],
                },
                index=[t.index[0].normalize()],
            )
            dd = pd.concat([dd, row])
    h52 = float(dd["high"].tail(252).max())
    cur = float(dd["close"].iloc[-1])
    p52 = (cur / h52 - 1) * 100
    ms = monthly_stats(dd, cur) or {}
    out = []
    for tf, frame in (("D", dd), ("4H", to_4h(hh) if hh is not None else None)):
        res = check(frame)
        if res:
            kind, r, gap, cts = res
            cs, cn = fmt_ts(cts, tf)
            row = {
                "sector": sec,
                "symbol": sym,
                "tf": tf,
                "kind": kind,
                "rsi": round(r, 1),
                "gap": round(gap, 2),
                "cross": cs,
                "cx": cn,
                "h52": round(h52, 1),
                "p52": round(p52, 1),
                "cur": round(cur, 1),
            }
            row.update(ms)
            out.append(row)
    return out


def load_keys():
    r = requests.get(INSTR_URL, timeout=90)
    try:
        data = json.loads(gzip.decompress(r.content))
    except Exception:
        data = r.json()
    return {
        d["trading_symbol"]: d["instrument_key"]
        for d in data
        if d.get("segment") == "NSE_EQ" and d.get("instrument_type") == "EQ"
    }


def load_universe():
    files = glob.glob("universe/*.csv") + glob.glob("ind_*.csv")
    if not files:
        df = pd.read_csv("stocks.csv")
        return list(zip(df["symbol"], df["sector"], strict=False))
    frames = []
    for f in files:
        d = pd.read_csv(f)
        d.columns = [c.strip() for c in d.columns]
        frames.append(
            d[["Symbol", "Industry"]].rename(columns={"Symbol": "symbol", "Industry": "sector"})
        )
    df = pd.concat(frames).dropna().drop_duplicates("symbol")
    return list(zip(df["symbol"].str.strip(), df["sector"].str.strip(), strict=False))


def send(text):
    tok = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    for i in range(0, len(text), 3800):
        requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            data={"chat_id": chat, "text": text[i : i + 3800]},
            timeout=20,
        )


def write_html(hits, total):
    os.makedirs("docs", exist_ok=True)
    meta = datetime.datetime.now(IST).strftime("%d %b %Y %H:%M IST") + f" | scanned {total} stocks"
    html = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>EMA50 RSI Scan</title>
<style>body{font-family:Arial;background:#111;color:#eee;margin:8px;font-size:13px}
select,input{background:#222;color:#eee;border:1px solid #444;padding:6px;margin:2px}
.w{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:980px}
th,td{border-bottom:1px solid #333;padding:6px;text-align:left;white-space:nowrap}
th{cursor:pointer;background:#1c1c1c;position:sticky;top:0}
.CROSS{color:#4caf50;font-weight:bold}.NEAR{color:#ff9800;font-weight:bold}
.hi{color:#4caf50}.lo{color:#f44336}a{color:#6cf;text-decoration:none}.n{color:#888;font-size:11px}</style></head><body>
<h3>EMA50 + RSI(45-50) Scan</h3><div>__META__</div>
<div class="n">Cross time = candle open time (IST). TP1/TP2/SL are underlying price targets from historical monthly moves (not option premium).</div>
<select id="k"><option value="">All</option><option>CROSS</option><option>NEAR</option></select>
<select id="t"><option value="">D + 4H</option><option>D</option><option>4H</option></select>
<select id="s"><option value="">All sectors</option></select>
<select id="h"><option value="">52W high: any</option><option value="5">within 5%</option><option value="10">within 10%</option><option value="20">within 20%</option></select>
<input id="q" placeholder="search stock">
<div class="w"><table><thead><tr><th data-k="kind">Signal</th><th data-k="symbol">Stock</th><th data-k="tf">TF</th>
<th data-k="cx">Cross time</th><th data-k="sector">Sector</th><th data-k="rsi">RSI</th><th data-k="gap">Gap%</th>
<th data-k="cur">Price</th><th data-k="tp1">TP1</th><th data-k="tp2">TP2</th><th data-k="sl">SL</th>
<th data-k="avgup">Avg Up%</th><th data-k="avgdn">Avg Dn%</th><th data-k="months">Months</th>
<th data-k="h52">52W High</th><th data-k="p52">From 52W H%</th></tr></thead><tbody id="b"></tbody></table></div>
<script>
const D=__DATA__;let sk="kind",asc=true;const $=id=>document.getElementById(id);
[...new Set(D.map(x=>x.sector))].sort().forEach(v=>$("s").add(new Option(v,v)));
function draw(){
 let r=D.filter(x=>(!$("k").value||x.kind==$("k").value)&&(!$("t").value||x.tf==$("t").value)&&(!$("s").value||x.sector==$("s").value)&&(!$("h").value||x.p52>=-Number($("h").value))&&x.symbol.includes($("q").value.toUpperCase()));
 r.sort((a,b)=>(a[sk]>b[sk]?1:-1)*(asc?1:-1));
 $("b").innerHTML=r.map(x=>`<tr><td class="${x.kind}">${x.kind}</td><td><a href="https://in.tradingview.com/chart/?symbol=NSE:${x.symbol}" target="_blank">${x.symbol}</a></td><td>${x.tf}</td><td>${x.cross||"-"}</td><td>${x.sector}</td><td>${x.rsi}</td><td>${x.gap}</td><td>${x.cur??"-"}</td><td class="hi">${x.tp1??"-"}</td><td class="hi">${x.tp2??"-"}</td><td class="lo">${x.sl??"-"}</td><td>${x.avgup??"-"}</td><td>${x.avgdn??"-"}</td><td>${x.months??"-"}</td><td>${x.h52}</td><td class="${x.p52>=-5?"hi":""}">${x.p52}</td></tr>`).join("");}
["k","t","s","h","q"].forEach(i=>$(i).oninput=draw);
document.querySelectorAll("th").forEach(h=>h.onclick=()=>{const k=h.dataset.k;asc=(sk==k)?!asc:true;sk=k;draw()});
draw();
setTimeout(()=>location.reload(),600000);
</script></body></html>"""
    html = html.replace("__DATA__", json.dumps(hits)).replace("__META__", meta)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)


def main():
    global KEYS
    KEYS = load_keys()
    universe = load_universe()
    rows = [r for r in universe if r[0] in KEYS]
    skipped = len(universe) - len(rows)
    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            hits = [h for r in ex.map(scan, rows) for h in r]
    except TokenError:
        send("Upstox token expire ho gaya. GitHub secret UPSTOX_TOKEN update karo.")
        raise SystemExit(1)
    write_html(hits, len(rows))
    json.dump(hits, open("docs/hits.json", "w"))
    now = datetime.datetime.now(IST)
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if manual or (now.hour in TG_HOURS and now.minute < 30):
        n = sum(1 for h in hits if h["kind"] == "CROSS")
        send(
            f"EMA50+RSI scan: {n} CROSS, {len(hits) - n} NEAR "
            f"({len(rows)} stocks, {skipped} skipped)\n{PAGE}"
        )


main()
