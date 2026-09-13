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
"""Phase 4: reconcile ALL post-2016 SHP submission dates against BSE's filing_date_time, to
remove the §104 NSE-LAG class from the 63,567 cells that already hold a "real" date.

THE RULE, and why it is asymmetric.
A quarter's shareholding becomes public at the FIRST exchange disclosure. BSE's SHPQNewFormat
`filing_date_time` is one genuine such event; our stored date is another (usually NSE-sourced).
So the truth is the EARLIER of the two — but only one direction is safe to act on:

  * BSE EARLIER than stored  -> stored is stale; the screen was blind to data the market had.
    Correcting it moves the date EARLIER. Measured cause (pilot + §104): NSE's broadcastDate lags,
    sometimes by months (BBTC's four 2022 quarters all carry NSE 28-DEC-2023, a bulk re-broadcast,
    against BSE's real 2022 filings). WE CORRECT THESE.
  * BSE LATER than stored, SAME filing (stored == BSE's raw broadcast date, filed after 15:30)
    -> not a disagreement at all: both name the same event, and the store marks it visible the
    session it was filed. That is a 1-day look-ahead. WE GATE THESE (user decision 2026-08-23).
  * BSE LATER than stored, DIFFERENT dates -> could mean (a) the company genuinely filed NSE
    first, or (b) our stored date is too early. We CANNOT tell which from these two sources, and
    moving a date later on a guess would discard a possibly-genuine earlier disclosure. WE LEAVE
    THESE, and report the count so the class stays visible instead of silently absorbed.

Moving a date earlier is the direction that can create look-ahead if wrong, so every correction
must clear all of:
  * the BSE row is a real 'new' filing (never a revised-only fallback — that is a restatement)
  * lag 0..120d from quarter end (rejects years-later RE-UPLOADS: TALWALKARS Sep-2021 carries
    filing_date_time 2026-06-29; real lags over 748 measured filings: median 17d, max 47d)
  * the resulting date is > quarter end, <= today, and strictly earlier than the stored date
  * a materiality floor (--min-days, default 2) so 1-day differences that are really just the
    15:30-gate convention gap between our ledgers are NOT churned here

15:30 gate applied (user decision 2026-08-23), same as the convention campaign.

Writes scripts/shp_lag_fix.json (ledger) and, with --apply, patches scripts/shp_history.json's
sub slot — the durable store build_engine_feed() reads. NEVER writes docs/shp_engine.json
directly (regenerated ~2x/day). Keeps shp_cell_fix.json in lockstep (measured regression: _cell_eq
compares the sub string EXACTLY, so advancing it silently skips those corrections).

Usage: reconcile_all.py [--min-days N]        # dry run
       reconcile_all.py [--min-days N] --apply
"""
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import shp_dates as SD

HIST = os.path.join(SCRIPTS, "shp_history.json")
CELLFIX = os.path.join(SCRIPTS, "shp_cell_fix.json")
LEDGER = os.path.join(SCRIPTS, "shp_lag_fix.json")
MAX_LAG = 120


def iso(d):
    return f"{d // 10000:04d}-{(d // 100) % 100:02d}-{d % 100:02d}"


def lag_days(qe, d):
    a = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
    b = datetime.date(d // 10000, (d // 100) % 100, d % 100)
    return (b - a).days


def main():
    apply = "--apply" in sys.argv
    min_days = 2
    if "--min-days" in sys.argv:
        min_days = int(sys.argv[sys.argv.index("--min-days") + 1])

    shp = json.load(open(os.path.join(ROOT, "docs", "shp_engine.json")))
    cal = SD.tdays()
    today = int(datetime.date.today().strftime("%Y%m%d"))

    fetched = {}
    for pat in ("full_shard{}.json", "rest_shard{}.json"):
        for i in (0, 1):
            p = os.path.join(HERE, pat.format(i))
            if os.path.exists(p):
                fetched.update(json.load(open(p)))
    print(f"fetched symbols available: {len(fetched)}")

    st = collections.Counter()
    ledger, gaps = {}, []
    for sym, rows in shp.items():
        ent = fetched.get(sym)
        if not ent or ent.get("error"):
            st["symbol_unfetched"] += 1
            continue
        res = {int(k): v for k, v in (ent.get("resolved") or {}).items()}
        for q in rows:
            if not (isinstance(q, list) and len(q) > 3):
                continue
            qe, sub = q[0], q[3]
            if qe < 20160101 or not sub or SD.is_convention(qe, sub):
                continue  # convention cells belong to the other campaign
            st["in_scope"] += 1
            r = res.get(qe)
            if not r:
                st["no_bse_row"] += 1
                continue
            if r["src"] != "new":
                st["revised_only_skipped"] += 1
                continue
            raw, _ = SD.ts_parts(r["ts"])
            if raw is None:
                st["unparseable"] += 1
                continue
            L = lag_days(qe, raw)
            if not (0 <= L <= MAX_LAG):
                st["guard_lag"] += 1
                continue
            new, gated = SD.visible_date(r["ts"], cal)
            if new is None or new <= qe or new > today:
                st["guard_bounds"] += 1
                continue
            if new == sub:
                st["agree"] += 1
                continue
            if new > sub:
                # USER DECISION 2026-08-23 ("both"): where the stored date IS the BSE raw
                # broadcast date and the filing was after 15:30, the store marks it visible the
                # same session — a 1-day look-ahead. Gate it. Measured: 24,709 such cells; this
                # is the only case where moving a date LATER is justified, because the two dates
                # are the SAME filing and the difference is purely our own visibility rule.
                if raw == sub:
                    st["GATE_shift_later"] += 1
                    ledger[f"{sym}|{qe}"] = {
                        "sub": new,
                        "was": sub,
                        "ts": r["ts"],
                        "src": r["src"],
                        "gated_1530": gated,
                        "days_later": new - sub,
                        "prov": "bse:SHPQNewFormat 15:30 gate (same filing, visibility rule)",
                    }
                    continue
                # genuinely different dates with BSE later: cannot tell whether the company
                # filed NSE first or our date is early. Left alone, counted, never guessed.
                st["bse_later_left_alone"] += 1
                gaps.append((sym, qe, sub, new, new - sub))
                continue
            delta = (
                datetime.date(sub // 10000, (sub // 100) % 100, sub % 100)
                - datetime.date(new // 10000, (new // 100) % 100, new % 100)
            ).days
            if delta < min_days:
                st["below_materiality"] += 1
                continue
            st["CORRECT_earlier"] += 1
            ledger[f"{sym}|{qe}"] = {
                "sub": new,
                "was": sub,
                "ts": r["ts"],
                "src": r["src"],
                "gated_1530": gated,
                "days_earlier": delta,
                "prov": "bse:SHPQNewFormat filing_date_time (NSE-lag heal)",
            }

    print("=== reconciliation ===")
    for k in sorted(st):
        print(f"  {k:24s} {st[k]}")
    heals = {k: v for k, v in ledger.items() if "days_earlier" in v}
    gatesh = {k: v for k, v in ledger.items() if "days_later" in v}
    print(f"\n  ledger = {len(heals)} staleness heals + {len(gatesh)} gate shifts = {len(ledger)}")
    if heals:
        d = sorted(v["days_earlier"] for v in heals.values())
        b = collections.Counter("2-6" if x <= 6 else "7-30" if x <= 30 else "31-90" if x <= 90 else "90+" for x in d)
        print(
            f"\n  corrections {len(ledger)}: median {d[len(d) // 2]}d earlier, p95 {d[int(0.95 * len(d))]}d, max {d[-1]}d"
        )
        print(f"  buckets {dict(b)}")
        worst = sorted(heals.items(), key=lambda kv: -kv[1]["days_earlier"])[:8]
        for k, v in worst:
            print(f"    {k:24s} {v['was']} -> {v['sub']}  ({v['days_earlier']}d earlier)  ts {v['ts'][:19]}")
    json.dump(ledger, open(LEDGER, "w"), indent=0, sort_keys=True)
    print(f"\nledger -> {os.path.relpath(LEDGER, ROOT)} ({len(ledger)})")

    if not apply:
        print("\n(dry run — pass --apply to patch shp_history.json)")
        return

    hist = json.load(open(HIST))
    cf = json.load(open(CELLFIX))
    fix = cf.get("fix") or {}
    n = ncf = 0
    for key, e in ledger.items():
        sym, qe = key.split("|")
        qk = iso(int(qe))
        cell = (hist.get(sym) or {}).get(qk)
        if not (isinstance(cell, list) and len(cell) > 5):
            continue
        if str(cell[5]).replace("-", "") != str(e["was"]):
            continue  # someone else moved it since the dry run
        cell[5] = iso(e["sub"])
        n += 1
        ent = (fix.get(sym) or {}).get(qk)  # lockstep, see module docstring
        if (
            ent
            and isinstance(ent.get("cell"), list)
            and len(ent["cell"]) > 5
            and str(ent["cell"][5]).replace("-", "") == str(e["was"])
        ):
            ent["cell"][5] = iso(e["sub"])
            ncf += 1
    for path, obj, kw in ((HIST, hist, {"separators": (",", ":")}), (CELLFIX, cf, {"indent": 1})):
        tmp = path + ".tmp"
        json.dump(obj, open(tmp, "w", encoding="utf-8"), **kw)
        os.replace(tmp, path)
    print(f"patched {n} cells in shp_history.json; {ncf} shp_cell_fix entries advanced in lockstep")
    print("DONE. Regenerate the feed with fetch_shareholding.build_engine_feed().")


if __name__ == "__main__":
    main()
