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


#!/usr/bin/env python
# Parse pre-2008 CNX-500 .htm constituent captures -> era-symbol lists per date.
# Table layout: repeating [Company Name, Industry Name, Symbol, Series].
import glob
import json
import os
import re


def clean(c):
    c = re.sub("<[^>]+>", "", c)
    return c.replace("&nbsp;", " ").replace("&amp;", "&").strip()


def parse_htm(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    cells = [clean(x) for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", raw, re.IGNORECASE | re.DOTALL)]
    # find the "Symbol" / "Series" header anchor
    syms = []
    # locate index of a cell that == 'Symbol' followed by 'Series'
    start = None
    for i in range(len(cells) - 1):
        if cells[i] == "Symbol" and cells[i + 1] == "Series":
            start = i + 2
            break
    if start is None:
        return []
    # from start, walk in groups of 4: company, industry, symbol, series
    i = start
    while i + 3 < len(cells) + 1 and i + 2 < len(cells):
        sym = cells[i + 2] if i + 2 < len(cells) else ""
        ser = cells[i + 3] if i + 3 < len(cells) else ""
        # symbol looks like a ticker (uppercase alnum/&-), series in EQ/BE/etc
        if re.fullmatch(r"[A-Z0-9&\-\.]{1,20}", sym) and ser in ("EQ", "BE", "BT", "BZ", "SM"):
            syms.append(sym)
            i += 4
        else:
            # try to resync: advance by 1
            i += 1
            # bail if we've clearly left the table
            if len(syms) > 20 and (i - start) > len(syms) * 4 + 40:
                break
    return syms


def main():
    per_date = {}
    for p in sorted(glob.glob("_n500_pre2008/cnx500_*.htm")):
        d = re.search(r"(\d{8})", os.path.basename(p)).group(1)
        s = parse_htm(p)
        per_date[d] = sorted(set(s))
        print(f"{d}: {len(per_date[d])} symbols  ({os.path.basename(p)})")
    json.dump(per_date, open("_n500_pre2008_lists.json", "w"), indent=0)
    uni = sorted(set().union(*[set(v) for v in per_date.values() if v]))
    json.dump(uni, open("_n500_pre2008_union.json", "w"), indent=0)
    print(f"\nDATES parsed: {sum(1 for v in per_date.values() if v)}/{len(per_date)}")
    print(f"PRE-2008 ERA-SYMBOL UNION: {len(uni)}")


if __name__ == "__main__":
    main()
