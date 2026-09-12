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
"""
SAFETY NET for the Season Trends tab of docs/quarterly-results.html (the merged results-season
chart) — guarantees the chart never silently undercounts.

For the LIVE quarter it compares, per universe on that page (the liquid set + every NSE index, using the
SAME point-in-time membership build_results_season.py uses):
  declared = index members that have FILED results for the quarter (present in results_feed.json)
  parsed   = index members whose PAT we've actually captured (in sf_fundamentals.json)  -> what the
             chart's "reported" count shows
  missing  = declared but not parsed  -> exactly the gap that made Nifty 500 read 22 vs 25.

Writes docs/_season_coverage.json (per-index declared/parsed/missing) and PRINTS any gap so it is visible
in the nightly CI log the moment it appears — for Nifty 500 and every other index — instead of being
discovered later by eyeballing a reference site. It does NOT fail the pipeline (exit 0 always); it is a
monitor. Most gaps here are insurers awaiting the free Gemini-vision / std-only fill; a gap that persists
> ~1 day is the flag to fill by hand (INSURER_EXTRACTION_PLAYBOOK.md).

Run standalone or as a CI step after build_results_season.py.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FUND = os.path.join(HERE, "..", "docs", "sf_fundamentals.json")
FEED = os.path.join(HERE, "..", "docs", "results_feed.json")
INDICES = os.path.join(HERE, "indices_history.json")
RENAME = os.path.join(HERE, "_rename_map.json")
OUT = os.path.join(HERE, "..", "docs", "_season_coverage.json")


def iso(qe):
    s = str(qe)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def snap_as_of(snaps, ymd, rename):
    """Point-in-time index members effective on/before ymd (survivorship-free) — mirrors
    build_results_season.snap_as_of exactly."""
    chosen = None
    for snp in snaps:
        if snp.get("effectiveDate", "9") <= ymd:
            chosen = snp
    return {rename.get(s, s) for s in chosen["symbols"]} if chosen else set()


def main():
    fund = json.load(open(FUND, encoding="utf-8"))
    feed = json.load(open(FEED, encoding="utf-8"))
    indices = json.load(open(INDICES, encoding="utf-8"))
    try:
        rename = json.load(open(RENAME, encoding="utf-8"))
    except Exception:
        rename = {}

    rows = feed.get("rows", [])
    if not rows:
        print("[season-coverage] empty feed — nothing to check.")
        return
    # live quarter = the newest quarter anyone has filed for
    live_qe = max(r[3] for r in rows if isinstance(r[3], int))

    # who has FILED for the live quarter (declared) and who we've PARSED (PAT present)
    declared_all = {r[0] for r in rows if r[3] == live_qe}
    parsed_all = set()
    for s, frows in fund.items():
        for r in frows:
            if r[0] == live_qe and (r[1] is not None or r[3] is not None):
                parsed_all.add(s)
                break

    report = {}
    total_missing = set()
    for index, snaps in indices.items():
        if not isinstance(snaps, list) or not snaps:
            continue
        members = snap_as_of(snaps, iso(live_qe), rename)
        if not members:
            continue
        declared = members & declared_all
        parsed = members & parsed_all
        missing = sorted(declared - parsed)
        report[index] = {"declared": len(declared), "parsed": len(parsed), "missing": missing}
        total_missing |= set(missing)

    json.dump(
        {"generated": int(time.time()), "qe": live_qe, "indexes": report},
        open(OUT, "w", encoding="utf-8"),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    # ---- CI-visible report ----
    print(f"[season-coverage] live quarter {iso(live_qe)}")
    gaps = {k: v for k, v in report.items() if v["missing"]}
    if not gaps:
        print("[season-coverage] OK — every index's declared filings are parsed into the chart.")
    else:
        print("[season-coverage] GAP — declared-but-unparsed members (chart undercounts until filled):")
        for k in sorted(gaps, key=lambda k: -len(gaps[k]["missing"])):
            v = gaps[k]
            print(
                "   %-24s %d declared / %d parsed  MISSING: %s"
                % (k, v["declared"], v["parsed"], ", ".join(v["missing"]))
            )
        print(
            "[season-coverage] union of missing names (%d): %s" % (len(total_missing), ", ".join(sorted(total_missing)))
        )
    print(f"[season-coverage] wrote {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
