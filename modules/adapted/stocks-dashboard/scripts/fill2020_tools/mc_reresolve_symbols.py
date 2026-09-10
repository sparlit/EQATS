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


# -*- coding: utf-8 -*-
"""RE-RESOLVE the symbols Moneycontrol was recorded as not having  (2026-08-11)

212 symbols sat in _mc_codes.json as `null` — "no Moneycontrol page" — and every fill route skipped
them on that basis. Three separate defects, none of them about Moneycontrol's coverage:

1. ★ THE SEARCH QUERY WAS NEVER URL-ENCODED. An ampersand ENDS a query parameter, so `?query=M&M`
   asks the endpoint for "M" and passes a stray `M` alongside. It fails SILENTLY: 13 plausible rows
   come back for "M", none of them Mahindra, and the symbol is written off. M&M encodes to sc_id MM,
   J&KBANK to JKB. Ten symbols in the store carry an ampersand.
2. HTML-DOUBLE-ESCAPED SYMBOLS IN OUR OWN STORE — `M&AMP;M`, `IL&AMP;FSENGG`, `SURANAT&AMP;P`.
   Tickers no exchange ever listed. Unescaped before searching.
3. RENAMES. Moneycontrol indexes a company under its CURRENT ticker, so a merged-away symbol is
   genuinely absent under the old name — TUBEINVEST is there as TIINDIA, AMARAJABAT as ARE&M. 50 of
   the 212 are in scripts/_rename_map.json.

And the reason all three stayed invisible: a negative was cached PERMANENTLY. One rate-limited minute
wrote a symbol off for good, breaking the rule the series fetchers already respect — an empty
response is a run-time condition, not evidence (§0, §55a).

⚠️ A RECOVERED CODE IS NOT A LICENCE TO WRITE. The code is verified against the row's own NSE symbol
(§49), but a renamed symbol resolves to the SUCCESSOR company, whose series may cover periods the old
entity never had. Every cell read through these codes still passes the ordinary gates.

Run: python -X utf8 scripts/fill2020_tools/mc_reresolve_symbols.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import mc_quarterly_fetch as MC  # noqa: E402

RENAMES = os.path.join(SCRIPTS, "_rename_map.json")
REPORT = os.path.join(HERE, "_mc_reresolved.json")


def main():
    codes = json.load(open(MC.CODES))
    renames = json.load(open(RENAMES)) if os.path.exists(RENAMES) else {}
    failed = sorted([s for s, v in codes.items() if v is None])
    print("re-resolving %d written-off symbols (url-encode + unescape + rename fallback)" % len(failed), flush=True)

    won = {}
    for i, sym in enumerate(failed, 1):
        code = MC.resolve_code(sym, codes, renames=renames, retry_negative=True)
        if code:
            via = renames.get(sym)
            won[sym] = {"sc_id": code, "via_rename": via}
            print("  RESOLVED %-14s -> %-8s %s" % (sym, code, ("via rename " + via) if via else ""), flush=True)
        MC._jitter(0.4, 0.9)
        if i % 25 == 0:
            json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
            json.dump(won, open(REPORT, "w"), indent=1, sort_keys=True)
            print("  [%d/%d] %d recovered" % (i, len(failed), len(won)), flush=True)

    json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
    json.dump(won, open(REPORT, "w"), indent=1, sort_keys=True)
    still = sum(1 for v in codes.values() if v is None)
    print("\nRECOVERED %d of %d | still unresolved %d" % (len(won), len(failed), still))


if __name__ == "__main__":
    main()
