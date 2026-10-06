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


#!/usr/bin/env python3
"""Portfolio widget feed — CLOUD edition (runs in GitHub Actions, not on the Mac).

Reads the holdings blob from the token-addressed supabase row, prices it with the
live-quote worker, and writes back a percentages-ONLY payload:
    {day, total, mtd, dayTxt, totalTxt, mtdTxt, asOf, ts}
No stock names, no portfolio names, no rupee amounts ever leave this script — the
phone widget must reveal nothing to whoever picks the phone up.

Tokens come from the environment (repo secrets); nothing sensitive is printed.

  python3 scripts/portfolio_feed.py                      # one shot
  python3 scripts/portfolio_feed.py --loop 30 --every 120  # loop 30 min, push every 120 s
"""
import base64
import datetime
import gzip
import json
import os
import sys
import time
import urllib.request

SUPA = "https://nebjnsndgrhumnkuipqy.supabase.co/rest/v1/rpc/"
ANON = "sb_publishable_MDlQwiVc5deii91__UNeDg_z9r4Fk98"
OWNER = "sw_owner_8Kq2Lm9Xp4Rt7v"  # already public in docs/sw-sync.js
WORKER = "https://stocksworld-quotes.dhruvan2510.workers.dev/?quotes="
SLIM = "https://dhruvan246.github.io/stocks-dashboard/dash_slim.bin"
EPOCH = datetime.date(1996, 1, 1)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

HOLD_TOKEN = os.environ.get("PF_HOLDINGS_TOKEN", "").strip()
FEED_TOKEN = os.environ.get("PF_FEED_TOKEN", "").strip()


def _post(fn, payload, timeout=40):
    req = urllib.request.Request(
        SUPA + fn,
        data=json.dumps(payload).encode(),
        headers={
            "apikey": ANON,
            "Authorization": "Bearer " + ANON,
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode().strip()
    return json.loads(body) if body else None


def load_holdings():
    row = _post("pf_feed_get", {"token": HOLD_TOKEN})
    if not row or "z" not in row:
        sys.exit(
            "holdings row not found — is PF_HOLDINGS_TOKEN right, and has push_holdings.py run?"
        )
    return json.loads(gzip.decompress(base64.b64decode(row["z"])))


def quotes(syms):
    req = urllib.request.Request(WORKER + ",".join(sorted(syms)), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r).get("data", {})


def load_series():
    """The site's EOD price bin, downloaded ONCE per run (~2 MB): last month's closes only change
    when the pipeline backfills, which a single run need not chase."""
    req = urllib.request.Request(SLIM, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(gzip.decompress(r.read()))["series"]


def month_end_baseline(series, hold):
    """Closing prices on the last trading session of LAST month, by symbol — for the holdings of THIS
    tick (cheap: the bin is already in memory), so a stock bought today has its month-end close too."""
    cut = (datetime.date.today().replace(day=1) - EPOCH).days
    best = None
    for h in hold:
        d = series.get(h.get("hist") or "", {}).get("d")
        if not d:
            continue
        prev = [x for x in d if x < cut]
        if prev and (best is None or prev[-1] > best):
            best = prev[-1]
    if best is None:
        return None, None
    px = {}
    for h in hold:
        s = series.get(h.get("hist") or "")
        if not s:
            continue
        hit = [(o, p) for o, p in zip(s["d"], s["p"], strict=False) if o <= best]
        if hit:
            px[h["hist"]] = hit[-1][1] / 100.0
    return px, str(EPOCH + datetime.timedelta(days=best))


def compute(doc, base_px):
    hold = doc["holdings"]
    q = quotes({h["live"] for h in hold if h.get("live")})
    value = cost = day = 0.0
    bv = nv = 0.0
    priced = 0
    today = (
        datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        .date()
        .isoformat()
    )
    for h in hold:
        if h.get("live") and h["live"] in q:
            px = q[h["live"]]["ltp"]
            prev = q[h["live"]].get("prevClose", px)
            priced += 1
        elif h.get("manualPx") is not None:
            px = h["manualPx"]
            prev = h.get("manualPrev", px)
        else:
            continue
        if h.get("date") == today:
            prev = h[
                "avg"
            ]  # bought today: you didn't own it at yesterday's close — today's move is from your buy price (the dashboard's rule)
        value += h["qty"] * px
        cost += h["qty"] * h["avg"]
        day += h["qty"] * (px - prev)
        b = (base_px or {}).get(h.get("hist"))
        if b:
            bv += h["qty"] * b
            nv += h["qty"] * px
    if not (value > 0 and cost > 0):
        raise SystemExit("refusing to publish a feed with no priced holdings")

    day_pct = day / (value - day) * 100
    tot_pct = (value - cost) / cost * 100
    mtd = round(nv / bv * 100 - 100, 2) if bv > 0 else None

    def sgn(v):
        return None if v is None else (f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%")

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    return {
        "day": round(day_pct, 2),
        "total": round(tot_pct, 2),
        "mtd": mtd,
        "dayTxt": sgn(day_pct),
        "totalTxt": sgn(tot_pct),
        "mtdTxt": sgn(mtd),
        "n": len(hold),
        "priced": priced,
        "asOf": now.strftime("%Y-%m-%d %H:%M"),
        "ts": int(time.time()),
        "src": "ci",
    }


def push(feed):
    ok = _post("pf_feed_set", {"secret": OWNER, "token": FEED_TOKEN, "payload": feed})
    if ok is not True:
        raise SystemExit(f"supabase rejected the feed write: {ok!r}")


def main():
    if not HOLD_TOKEN or not FEED_TOKEN:
        sys.exit("PF_HOLDINGS_TOKEN and PF_FEED_TOKEN must be set")
    args = sys.argv[1:]
    loop_min = int(args[args.index("--loop") + 1]) if "--loop" in args else 0
    every = int(args[args.index("--every") + 1]) if "--every" in args else 120

    series = load_series()
    doc = load_holdings()
    base_px, base_date = month_end_baseline(series, doc["holdings"])
    print(
        "loaded %d holdings; month-end baseline %s (%d symbols)"
        % (len(doc["holdings"]), base_date, len(base_px or {}))
    )

    deadline = time.time() + loop_min * 60
    n = 0
    while True:
        try:
            # Re-read the books EVERY tick (one ~3 KB row): loaded once, a loop started at 09:23 kept pricing
            # the pre-rebalance holdings all day after the 09:36 books update (1 Oct 2026). A failed re-read
            # keeps the last good copy.
            try:
                doc = load_holdings()
                base_px, base_date = month_end_baseline(series, doc["holdings"])
            except (Exception, SystemExit) as e:  # a transient bad read must not end the session
                print(f"holdings re-read failed (using the last copy): {e}", file=sys.stderr)
            feed = compute(doc, base_px)
            push(feed)
            n += 1
            # Deliberately NOT logging the percentages: this repo is public, and
            # its Actions logs are readable by anyone. Counts prove the push worked
            # without publishing how the portfolio is doing.
            print("%s  pushed ok (%d priced of %d)" % (feed["asOf"], feed["priced"], feed["n"]))
        except SystemExit:
            raise
        except Exception as e:  # one bad tick must not end the session
            print(f"tick failed (continuing): {e}", file=sys.stderr)
        if time.time() + every > deadline:
            break
        time.sleep(every)
    print("pushed %d update(s)" % n)


if __name__ == "__main__":
    main()
