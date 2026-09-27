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


"""Build docs/ideas/universe.json: every active BSE equity with market cap between 200 and 2,000 crore.

Usage: python3 scripts/ideas/universe.py [--min 200] [--max 2000]
Market cap comes from BSE's scrip master (Rs crore, updated daily by BSE). Suspended groups (Z, ZP) are
dropped. NSE symbols are joined by ISIN from the two NSE lists when present next to this script
(nse_equity_l.csv, nse_sme.csv) so the routine can quote both tickers.
"""
import argparse
import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# scripts/, for bse_names (runbook §204). Appended, so this folder's bse.py / ist.py still resolve first.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bse
import bse_names
import ist

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs", "ideas")


def nse_by_isin():
    out = {}
    for fn, sym, isin, seg in (
        ("nse_equity_l.csv", "SYMBOL", " ISIN NUMBER", "NSE"),
        ("nse_sme.csv", "SYMBOL", "ISIN_NUMBER", "NSE-SME"),
    ):
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p)):
            k = (r.get(isin) or r.get(isin.strip()) or "").strip()
            if k:
                out[k] = (r[sym].strip(), seg)
    return out


def build(lo, hi):
    master = bse.scrip_master()
    nse = nse_by_isin()
    uni = []
    for x in master:
        try:
            mcap = float(x.get("Mktcap") or 0)
        except Exception:
            continue
        grp = (x.get("GROUP") or "").strip()
        if not (lo <= mcap <= hi) or grp in ("Z", "ZP"):
            continue
        isin = (x.get("ISIN_NUMBER") or "").strip()
        n = nse.get(isin, ("", ""))
        uni.append(
            {
                "scrip": str(x["SCRIP_CD"]).strip(),
                "id": (x.get("scrip_id") or "").strip(),
                "name": bse_names.clean_scrip_name(x.get("Scrip_Name")),
                "issuer": (x.get("Issuer_Name") or "").strip(),
                "isin": isin,
                "group": grp,
                "mcap": round(mcap, 1),
                "face_value": x.get("FACE_VALUE"),
                "nse": n[0],
                "nse_seg": n[1],
                "sme": grp in ("M", "MT", "MS"),
            }
        )
    uni.sort(key=lambda r: -r["mcap"])
    return uni


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=200)
    ap.add_argument("--max", type=float, default=2000)
    a = ap.parse_args()
    out_fn = os.path.join(DOCS, "universe.json")
    try:
        uni = build(a.min, a.max)
    except Exception as e:
        # The scrip master lives on api.bseindia.com, which BSE's edge can refuse for a whole network
        # (2026-09-24). Crashing here used to take the whole routine down before the scan ran, even
        # though the scan only needs the committed universe plus bhavcopies from the other host.
        # Behave like the commodity builders: keep what is on file, say so, and do not fail the run.
        if os.path.exists(out_fn):
            try:
                old = json.load(open(out_fn))
                print(
                    f"universe: BSE scrip master unreachable ({str(e)[:110]}); "
                    f"universe.json LEFT UNCHANGED at its {old.get('asof', '?')} build, {old.get('count', '?')} names. "
                    "Market caps are that day's, not today's."
                )
                sys.exit(0)
            except Exception:
                pass
        msg = f"universe: BSE scrip master unreachable and no committed universe.json to fall back on: {e}"
        raise SystemExit(msg)
    os.makedirs(DOCS, exist_ok=True)
    out = {"asof": ist.today().isoformat(), "mcap_min": a.min, "mcap_max": a.max, "count": len(uni), "rows": uni}
    json.dump(out, open(out_fn, "w"), separators=(",", ":"))
    import collections

    print(
        "universe",
        len(uni),
        "names |",
        collections.Counter(r["group"] for r in uni).most_common(),
        "| with NSE symbol:",
        sum(1 for r in uni if r["nse"]),
        "| SME:",
        sum(1 for r in uni if r["sme"]),
    )
