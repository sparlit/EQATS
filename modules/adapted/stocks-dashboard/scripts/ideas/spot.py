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


"""Daily spot/futures price panel for the commodity watch.

Sources (public pages, no login, no bot-challenge as of 2026-09-22):
  - Westmetall (LME cash settlements with ~190 days of history): copper, aluminium, zinc, lead, nickel, tin; gold, silver (London)
  - Markets Insider commodities page (latest price + day change): ~40 global commodities (energy, metals, agri)
Usage: python3 scripts/ideas/spot.py
Writes docs/ideas/spot.json (latest + stats) and appends today's snapshot to docs/ideas/spot_history.csv (one row per
commodity per day, so weekly/monthly changes accumulate for the Markets Insider names that have no history feed).
"""
import csv
import datetime
import html as htmlmod
import json
import os
import re
import statistics
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextlib

import ist

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs", "ideas")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
WM = {
    "copper": "LME_Cu_cash",
    "aluminium": "LME_Al_cash",
    "zinc": "LME_Zn_cash",
    "lead": "LME_Pb_cash",
    "nickel": "LME_Ni_cash",
    "tin": "LME_Sn_cash",
    "gold": "Au",
    "silver": "Ag",
}
WM_UNIT = {
    "copper": "USD/t",
    "aluminium": "USD/t",
    "zinc": "USD/t",
    "lead": "USD/t",
    "nickel": "USD/t",
    "tin": "USD/t",
    "gold": "EUR/kg",
    "silver": "EUR/kg",
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=60) as f:
        return f.read().decode("utf-8", "ignore")


def westmetall(field):
    h = get(f"https://www.westmetall.com/en/markdaten.php?action=table&field={field}")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.DOTALL)
    out = []
    for r in rows:
        c = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.DOTALL)]
        if len(c) < 2:
            continue
        m = re.match(r"(\d{1,2})\.\s*(\w+)\s+(\d{4})", c[0])
        if not m:
            continue
        try:
            d = datetime.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date()
            v = float(c[1].replace(",", ""))
        except Exception:
            continue
        out.append((d, v))
    out.sort()
    return out


def insider():
    h = get("https://markets.businessinsider.com/commodities")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.DOTALL)
    out = {}
    for r in rows:
        c = [
            htmlmod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x))).strip()
            for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.DOTALL)
        ]
        if len(c) >= 5 and re.match(r"^-?[\d,]+(\.\d+)?$", c[1] or "") and "%" in (c[2] or ""):
            with contextlib.suppress(Exception):
                out[c[0]] = {
                    "price": float(c[1].replace(",", "")),
                    "chg_pct": float(c[2].replace("%", "").replace(",", "")),
                    "unit": c[4],
                    "stamp": c[5] if len(c) > 5 else "",
                }
    return out


def stats(series):
    """series: [(date, value)] ascending -> latest + % changes over 1w/1m/3m/6m + 52w position."""
    if not series:
        return {}
    d0, v0 = series[-1]

    def back(days):
        d = d0 - datetime.timedelta(days=days)
        prior = [v for dd, v in series if dd <= d]
        return prior[-1] if prior else None

    def pct(b):
        return round((v0 / b - 1) * 100, 1) if b else None

    yr = [v for dd, v in series if dd >= d0 - datetime.timedelta(days=365)]
    return {
        "date": d0.isoformat(),
        "last": v0,
        "chg_1w": pct(back(7)),
        "chg_1m": pct(back(30)),
        "chg_3m": pct(back(91)),
        "chg_6m": pct(back(182)),
        "hi": max(yr),
        "lo": min(yr),
        "pos": round((v0 - min(yr)) / (max(yr) - min(yr)) * 100) if max(yr) > min(yr) else None,
        "n": len(series),
    }


def main():
    today = ist.today()
    hist_fn = os.path.join(DOCS, "spot_history.csv")
    hist = {}
    if os.path.exists(hist_fn):
        for r in csv.DictReader(open(hist_fn)):
            with contextlib.suppress(Exception):
                hist.setdefault(r["name"], []).append((datetime.date.fromisoformat(r["date"]), float(r["price"])))
    panel = {}
    series_out = {}
    for name, field in WM.items():
        try:
            s = westmetall(field)
        except Exception as e:
            print("westmetall fail", name, e)
            continue
        panel[name] = dict(
            source="LME cash via Westmetall" if name not in ("gold", "silver") else "London fix via Westmetall",
            unit=WM_UNIT[name],
            **stats(s),
        )
        series_out[name] = sorted(set(hist.get(name, [])) | set(s))
    try:
        bi = insider()
    except Exception as e:
        bi = {}
        print("insider fail", e)
    for name, r in bi.items():
        key = name.lower()
        if key in panel:  # LME names already covered with history
            continue
        series = sorted(set(hist.get(key, [])))
        if not series or series[-1][0] != today:
            series.append((today, r["price"]))
        st = stats(series)
        st["chg_1d"] = r["chg_pct"]
        series_out[key] = series
        panel[key] = dict(source="Markets Insider", unit=r["unit"], **st)
    # Never overwrite a good panel with a failed fetch. Both sources are remote, so a blocked or
    # rate-limited run used to write {"count": 0, "rows": {}} over yesterday's file and take the
    # whole commodity page down with it (2026-09-22: the cloud VM's egress blocked both hosts and
    # spot.json went from 34 rows to 0). A run that fetched nothing leaves every file untouched.
    if not panel:
        print(
            "spot: 0 commodities fetched - every source failed, so spot.json and spot_series.json "
            "were LEFT UNCHANGED. Check network access to westmetall.com and markets.businessinsider.com."
        )
        return 2
    prev_n = 0
    with contextlib.suppress(Exception):
        prev_n = json.load(open(os.path.join(DOCS, "spot.json")))["count"]
    if prev_n and len(panel) < prev_n:
        print(
            f"spot: WARNING only {len(panel)} of {prev_n} commodities fetched - some source failed; "
            "the panel is being written with fewer rows than the committed one."
        )
    # append today's snapshot for everything to the history file (idempotent per day)
    seen = {(k, d) for k, v in hist.items() for d, _ in v}
    with open(hist_fn, "a", newline="") as f:
        w = csv.writer(f)
        if os.path.getsize(hist_fn) == 0:
            w.writerow(["date", "name", "price", "unit", "source"])
        for k, v in panel.items():
            if v.get("last") is not None and (k, today) not in seen and v.get("date") == today.isoformat():
                w.writerow([today.isoformat(), k, v["last"], v["unit"], v["source"]])
    out = {"updated": ist.stamp(), "count": len(panel), "rows": panel}
    json.dump(out, open(os.path.join(DOCS, "spot.json"), "w"), indent=1)
    json.dump(
        {k: [[d.isoformat(), v] for d, v in sorted(set(ser))] for k, ser in series_out.items()},
        open(os.path.join(DOCS, "spot_series.json"), "w"),
        separators=(",", ":"),
    )
    print("spot:", len(panel), "commodities")
    for k, v in sorted(panel.items(), key=lambda kv: -(kv[1].get("chg_1m") or 0)):
        print(
            f"  {k:24s} {v.get('last')} {v.get('unit'):14s} 1w {v.get('chg_1w')} 1m {v.get('chg_1m')} 3m {v.get('chg_3m')} 52w-pos {v.get('pos')} n={v.get('n')} [{v['source']}]"
        )
    return None


if __name__ == "__main__":
    sys.exit(main() or 0)
