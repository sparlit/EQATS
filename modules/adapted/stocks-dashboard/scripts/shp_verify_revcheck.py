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
"""REVISION CHECK — re-adjudicate every "the filing confirmed us" cell against BSE's copy.

Found by the user, not by the campaign: when all three sites agreed with each other and disagreed
with us, my arbitration read the NSE document and declared us confirmed. But the arbitration used
the SAME document our pipeline had ingested — so a superseded filing confirms itself. Probing five
such cells against BSE's independently-received copy: ALL FIVE showed a `revised_date_time` on
BSE, BSE's parse agreed with the sites, and our value was the pre-revision original. The flagship
"sites unanimously wrong" example (LCCINFOTEC prom 0.0) was in fact OUR stale document — the
company revised to 45.85 five months later.

Mechanism: companies file the revision to BSE; NSE's corporate-share-holdings-master (or our read
of it) keeps serving the original. "Ours == NSE filing" is therefore necessary but NOT sufficient.

This sweeps every OURS_CONFIRMED cell: fetch BSE's row(s) for the quarter, note revised_date_time,
parse BSE's copy, and classify per field:

  REVISED_ON_BSE   BSE parses, differs from ours beyond tolerance, matches the sites  -> OUR DEFECT
  BSE_CONFIRMS     BSE parses and matches us -> genuinely confirmed, sites genuinely wrong
  BSE_DIFFERS_BOTH BSE disagrees with us AND the sites -> human
  BSE_ABSENT       no BSE file for that quarter -> NSE-only evidence stands, flagged as weaker
  BSE_REFUSED      BSE copy will not parse

  python3 -X utf8 scripts/shp_verify_revcheck.py --targets revcheck_targets.json --out revcheck.jsonl
"""
import argparse
import collections
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_shareholding as F  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MON = {"March": "03-31", "June": "06-30", "September": "09-30", "December": "12-31"}
SLOTKEY = {"prom": "prom", "fii": "fii", "dii": "dii", "mf": "mf", "ins": "ins", "nsh": "nsh"}


def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.bseindia.com/"})
    return urllib.request.urlopen(req, timeout=60).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    targets = json.load(open(a.targets))
    by = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
    try:
        ov = json.load(open(os.path.join(HERE, "_shp_scripcode_override.json")))
        by = dict(by, **{k: v for k, v in ov.items() if not k.startswith("_")})
    except Exception:
        pass

    qcache, out, tally = {}, [], collections.Counter()
    for t in targets:
        sym, qe = t["sym"], t["qe"]
        rec = {"sym": sym, "qe": qe, "fields": t["fields"]}
        code = by.get(sym)
        qlbl = None
        for m, dd in MON.items():
            if qe.endswith(dd):
                qlbl = f"{m} {qe[:4]}"
        if not code:
            rec["verdict"] = "BSE_ABSENT"
            rec["why"] = "no scripcode"
        else:
            if code not in qcache:
                try:
                    qcache[code] = json.loads(
                        get(
                            "https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w"
                            f"?scripcode={code}&qtrid=0.00&QryType=0"
                        )
                    ).get("Table", [])
                except Exception:
                    qcache[code] = []
                time.sleep(2.0)
            rows = [r for r in qcache[code] if r.get("qtr") == qlbl]
            withfile = [r for r in rows if (r.get("XbrlFile") or "").strip()]
            rec["bse_rows"] = len(rows)
            rec["revised"] = [r.get("revised_date_time") for r in rows if r.get("revised_date_time")]
            if not withfile:
                rec["verdict"] = "BSE_ABSENT"
            else:
                # BSE's list keeps original+revision; the row with a revised_date_time carries the
                # CURRENT (revised) document in XbrlFile. Prefer it; else the first row with a file.
                pick = next(
                    (r for r in rows if r.get("revised_date_time") and (r.get("XbrlFile") or "").strip()), withfile[0]
                )
                try:
                    cell = F.parse_shp(
                        get("https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + pick["XbrlFile"].strip()).decode(
                            "utf-8", "ignore"
                        ),
                        qe,
                    )
                    time.sleep(2.0)
                except Exception as e:
                    cell = None
                    rec["why"] = str(e)[:80]
                if not isinstance(cell, dict):
                    rec["verdict"] = "BSE_REFUSED"
                else:
                    rec["bse"] = cell
                    verdicts = {}
                    for fld, d in t["fields"].items():
                        ours = d.get("ours")
                        bv = cell.get(SLOTKEY.get(fld, fld))
                        if bv is None or ours is None:
                            verdicts[fld] = "BSE_NO_FIELD"
                            continue
                        tol = 0.06 if fld != "nsh" else max(500.0, 0.01 * abs(float(ours)))
                        if abs(float(bv) - float(ours)) <= tol:
                            verdicts[fld] = "BSE_CONFIRMS"
                        else:
                            svals = [v for v in (d.get("sites") or {}).values() if v is not None]
                            near_sites = any(abs(float(bv) - float(v)) <= tol for v in svals)
                            verdicts[fld] = "REVISED_ON_BSE" if near_sites else "BSE_DIFFERS_BOTH"
                    rec["field_verdicts"] = verdicts
                    worst = (
                        "REVISED_ON_BSE"
                        if "REVISED_ON_BSE" in verdicts.values()
                        else "BSE_DIFFERS_BOTH"
                        if "BSE_DIFFERS_BOTH" in verdicts.values()
                        else "BSE_CONFIRMS"
                    )
                    rec["verdict"] = worst
        tally[rec["verdict"]] += 1
        out.append(rec)
        print("  %-12s %s  %-16s rev=%s" % (sym, qe, rec["verdict"], bool(rec.get("revised"))), flush=True)

    with open(a.out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, separators=(",", ":")) + "\n" for r in out)
    print("\n%d documents re-checked -> %s" % (len(out), a.out))
    for k, v in tally.most_common():
        print("  %-18s %4d" % (k, v))


if __name__ == "__main__":
    main()
