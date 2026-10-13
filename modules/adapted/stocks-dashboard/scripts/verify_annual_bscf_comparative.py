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
"""SECOND READER for scripts/annual_bscf.json fill years (runbook §148).

The holdout gate proves a filer's FORMAT on one XBRL-held year; the fill years it lands are read
from other PDFs and were never checked against anything. Every audited annual result prints the
PRIOR year-end beside the current one, so the FY(t+1) filing is an independent second read of
FY(t): different document, different page, different day. This script reads that comparative
column (nums[1]) for Total Assets and PP&E and compares it with each landed cell.

Verdicts per cell:  agree (both anchors within 2%)                              → `x2: 1`
                    disagree = MISREAD (~10^k or >20x gap on assets or PP&E)     → RETRACT the cell
                    grey (any other gap: restated comparative after a merger /
                          reclass / ROU convention — as-filed is the PIT value)  → keep, `x2: -1`
                    unknown (no next-year filing / page / column / unit)         → keep, `x2: 0`

Run: python3 -X utf8 scripts/verify_annual_bscf_comparative.py [--only SYM,SYM] [--apply]
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_annual_bscf as F

LEDGER = os.path.join(HERE, "annual_bscf.json")


def prior_col(pdf, pages):
    """(assets, ppe, rou) from the SECOND value column of the BS page(s), raw."""
    import fitz

    doc = fitz.open(stream=pdf, filetype="pdf")
    out = {}
    for pi in F._as_list(pages):
        rows = F.rows_of(doc[pi])
        for field, rx in (
            ("assets", r"^\s*total\s+assets\b"),
            ("ppe", F.BS_ONE[3][1]),
            ("rou", r"right[\s\-]*of[\s\-]*use\s+assets?\b"),
        ):
            if field in out:
                continue
            for label, nums in rows:
                if re.search(rx, label, re.I) and len(nums) >= 2 and nums[1] is not None:
                    out[field] = nums[1]
                    break
        if "assets" not in out:
            for label, nums in rows:
                if (
                    re.search(r"total[\s\-–:.]{0,6}equity\s+and\s+liabilit", label, re.I)
                    and len(nums) >= 2
                ):
                    out["assets"] = nums[1]
                    break
    doc.close()
    return out


import gzip

_X = None


def xbrl_ref(sym, b):
    global _X
    if _X is None:
        _X = json.loads(
            gzip.decompress(open(os.path.join(HERE, "xbrl_extra.json.gz"), "rb").read())
        )
    for fy in ("20230331", "20240331", "20250331", "20260331"):
        c = _X.get(sym, {}).get(fy, {}).get(b)
        if isinstance(c, dict) and c.get("assets"):
            return c
    return None


def near(v, r):
    return v is not None and bool(r) and 1 / 3 <= v / r <= 3


def misread(a, b):
    """True when two reads of one quantity differ by ~10^k (k != 0) or by more than 20x."""
    if not a or not b:
        return False
    r = abs(a / b)
    if r > 20 or r < 1 / 20:
        return True
    return any(abs(r / k - 1) <= 0.05 or abs(r * k - 1) <= 0.05 for k in (10, 100, 1000))


def main():
    a = sys.argv[1:]
    apply = "--apply" in a
    only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
    led = json.load(open(LEDGER))
    byid = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
    o = F.session()
    stats = {"agree": 0, "disagree": 0, "grey": 0, "unknown": 0, "keep-cmp-misread": 0}
    report = []
    for sym in sorted(led):
        if only and sym not in only:
            continue
        code = byid.get(sym)
        for q, c in sorted(led[sym].items()):
            if c.get("m") != "text" or c.get("x2") is not None or c.get("v") or not code:
                continue  # v=1: a validate-year cash-flow-only cell — no BS to compare
            fy = int(q[:4])
            nxt = fy + 1
            verdict, got = "unknown", None
            try:
                fl = F.result_filings(o, code, "%d0401" % nxt, "%d0901" % nxt)
            except F.BseBlocked:
                raise  # a block must abort the run, never read as 'unknown' (§148)
            except Exception:
                fl = []
            for _ann, att in fl[:8]:
                pdf = F.download(o, att)
                if not pdf:
                    continue
                loc = F.locate(pdf, nxt, c["b"])
                if not loc or loc[0] != c["b"]:
                    continue
                raw = prior_col(pdf, loc[1])
                if not raw.get("assets"):
                    continue
                unit = F.detect_unit(
                    "\n".join(
                        __import__("fitz").open(stream=pdf, filetype="pdf")[p].get_text()
                        for p in F._as_list(loc[1])
                    )
                )
                ks = [unit] if unit else [1.0, 10.0, 100.0, 1e4, 1e7]
                ks = [
                    k
                    for k in ks
                    if c.get("assets")
                    and abs(raw["assets"] / k - c["assets"]) / c["assets"] <= 0.10
                ]
                if not ks:
                    if not unit:
                        verdict = "unknown"
                        break  # no stated unit and no candidate within 10%
                    got = {kk: v / unit for kk, v in raw.items()}
                    verdict = (
                        "disagree"
                        if (
                            misread(c.get("assets"), got.get("assets"))
                            or misread(c.get("ppe"), got.get("ppe"))
                        )
                        else "grey"
                    )
                    break
                k = ks[0]
                got = {kk: v / k for kk, v in raw.items()}
                da = abs(got["assets"] - c["assets"]) / c["assets"]
                pp = got.get("ppe")
                if pp is not None and c.get("ppe"):
                    alt = pp + (got.get("rou") or 0)
                    dp = min(abs(pp - c["ppe"]), abs(alt - c["ppe"])) / c["ppe"]
                else:
                    dp = None
                if da <= 0.02 and dp is None and c.get("ppe") is not None:
                    verdict = "unknown"  # assets agree but PP&E (the field that matters) unchecked
                elif da <= 0.02 and (dp is None or dp <= 0.02):
                    verdict = "agree"
                elif misread(c.get("assets"), got.get("assets")) or misread(
                    c.get("ppe"), got.get("ppe")
                ):
                    verdict = (
                        "disagree"  # a power-of-ten / >20x gap is a MISREAD, never a restatement
                    )
                else:
                    verdict = "grey"  # moderate gap: a restated comparative (merger, reclass,
                    # ROU convention) is legitimate — the as-filed value is the
                    # point-in-time one, so keep it and flag x2=-1
                break
            report.append(
                (
                    sym,
                    q,
                    verdict,
                    c.get("assets"),
                    c.get("ppe"),
                    got and round(got.get("assets") or 0, 2),
                    got and got.get("ppe") and round(got["ppe"], 2),
                )
            )
            if apply:
                if verdict == "disagree":
                    # a disagreement names NO side (the comparative read mis-takes note numbers too:
                    # GRANULES FY22 ppe 1,583 vs a comparative '4.5'). A third reference decides —
                    # the symbol's own XBRL-held year: the side within 3x of it is the plausible one.
                    r = xbrl_ref(sym, c["b"])
                    st_ok = near(c.get("assets"), r and r.get("assets")) and (
                        c.get("ppe") is None
                        or not (r or {}).get("ppe")
                        or near(c.get("ppe"), r["ppe"])
                    )
                    cp_ok = (
                        got is not None
                        and near(got.get("assets"), r and r.get("assets"))
                        and (
                            got.get("ppe") is None
                            or not (r or {}).get("ppe")
                            or near(got.get("ppe"), r["ppe"])
                        )
                    )
                    if st_ok and not cp_ok:
                        verdict = "keep-cmp-misread"
                if verdict == "agree":
                    c["x2"] = 1
                elif verdict == "keep-cmp-misread":
                    c["x2"] = -2
                elif verdict == "disagree":
                    del led[sym][q]
                elif verdict == "grey":
                    c["x2"] = -1
                else:
                    c["x2"] = 0
            stats[verdict] = stats.get(verdict, 0) + 1
            time.sleep(0.2)
    if apply:
        for s in [s for s in led if not led[s]]:
            del led[s]
        json.dump(led, open(LEDGER, "w"), separators=(",", ":"), sort_keys=True)
    for r in report:
        print("%-11s %s %-8s stored a=%s ppe=%s | next-year comparative a=%s ppe=%s" % r)
    print(stats)


if __name__ == "__main__":
    main()
