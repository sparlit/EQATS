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
"""§117b follow-up — audit the 114 COMPARATIVE-COLUMN VISION FILLS outside the §109 window.

The vision-PDF pass family is the remaining §108 exposure outside 20150630..20170331 (runbook
§117b boundary note): fills whose vision_rev_fills `src` cites a comparative column
(col2/col3/preceding/corresponding) of a LATER filing — the exact §108 mechanism that
contaminated BAYERCROP FY19 (§117 F-02). For each row, fetch the ORIGINAL filing of the target
quarter itself and compare.

STD route: BSE detres (Corp_detailedResult_Transpose_ng, §42 — AS-FILED by construction,
Rs million -> /10). Raw field dicts persisted so adjudication re-runs offline.

Verdicts here are DETECTION only (feedback-detect-is-not-confirm): EXACT / NEAR / FLAG buckets;
anything flagged is adjudicated by hand with EPS reconciliation + quarters-sum-to-annual before
any heal, and heals go only through fund_cell_fix.json / revop_cell_fix.json.

LEDGERS: scripts/_vintage117c_raw.json (raw detres rows), scripts/_vintage117c_scan.json
RUN: python3 scripts/vintage117c_visioncomp.py [--limit N] [--only SYM,SYM] [--sleep 2.0]
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bse_resolve  # noqa: E402

TARGETS = os.path.join(HERE, "_audit114_targets.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
SCAN = os.path.join(HERE, "_vintage117c_scan.json")
RAW = os.path.join(HERE, "_vintage117c_raw.json")

API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w?scrip_cd=%s&qtr=%s"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

EXTRA_SCRIP_FILES = [
    (os.path.join(HERE, "bse_scrips_delisted.json"), "scrips", "bse_code"),
    (os.path.join(HERE, "fill2020_tools", "_delisted_scrip_overrides.json"), None, "scrip"),
    (os.path.join(HERE, "_vintage108_scrips_extra.json"), "resolved", "scrip"),
]
SCRIP_OVERRIDE = {"ADVANTA": "532840", "DISHMAN": "532526", "CAPF": "532938"}

# field-name buckets over the detres transpose (union of spellings seen in _vintage108_raw +
# bank/NBFC formats; matching is substring/fuzzy, raw dict persisted either way)
R_REV = re.compile(
    r"net sales|revenue from operations|income from operations"
    r"|interest earned|^total income",
    re.IGNORECASE,
)
R_OP = re.compile(r"profit from operations before|operating profit before", re.IGNORECASE)
R_NP = re.compile(
    r"^net profit$|^net profit \(|net profit ?/ ?\(loss\) for the period"
    r"|from ordinary activities after tax",
    re.IGNORECASE,
)
R_EPS = re.compile(r"eps|earning[s]? per share", re.IGNORECASE)


def qid(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return "%d.00" % (85 + (y - 2015) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m])


def parse_dt(s):
    try:
        d, mo, y = (s or "").split("-")
        return (2000 + int(y)) * 10000 + MONTHS[mo] * 100 + int(d)
    except Exception:
        return None


def scrip_map():
    m = dict(bse_resolve.by_id())
    for path, key, field in EXTRA_SCRIP_FILES:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        d = d.get(key) if key else d
        for sym, e in (d or {}).items():
            if sym.startswith("_") or not isinstance(e, dict):
                continue
            code = e.get(field)
            if code and sym not in m:
                m[sym] = code
    for sym, code in SCRIP_OVERRIDE.items():
        m.setdefault(sym, code)
    for sym in list(m):
        if bse_resolve.blocked(sym):
            del m[sym]
    return {k: str(v) for k, v in m.items()}


def fetch(scrip, q, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                API % (scrip, q), headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
            if len(raw) <= 200:
                last = "stub-%db" % len(raw)
                time.sleep(8 * (i + 1))
                continue
            js = json.loads(raw.decode("utf-8", "replace"))
            out = {}
            for row in js.get("table1") or []:
                out.setdefault((row.get("fld_desc") or "").strip(), row.get("Value"))
            return out, "ok"
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as ex:
            last = f"{type(ex).__name__}:{str(ex)[:60]}"
            time.sleep(6 * (i + 1))
    raise RuntimeError(last or "unknown")


def fields_of(fdict, pat):
    out = []
    for k, v in fdict.items():
        if not pat.search(k):
            continue
        try:
            out.append((k, float(v) / 10.0))  # Rs million -> crore
        except (TypeError, ValueError):
            pass
    return out


def near(a, b, abs_tol=0.06, rel_tol=0.001):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def flag(a, b):
    """§108's detection gate: materially different."""
    if a is None or b is None:
        return False
    return abs(a - b) > max(2.0, 0.03 * max(abs(a), abs(b)))


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    sleep = float(args[args.index("--sleep") + 1]) if "--sleep" in args else 2.0

    targets = json.load(open(TARGETS, encoding="utf-8"))
    fund = json.load(open(FUND, encoding="utf-8"))
    revop = json.load(open(REVOP, encoding="utf-8"))
    codes = scrip_map()

    scan = {}
    if os.path.exists(SCAN):
        scan = json.load(open(SCAN, encoding="utf-8"))
    scan.setdefault("cells", {})
    raw = {}
    if os.path.exists(RAW):
        raw = json.load(open(RAW, encoding="utf-8"))

    todo = []
    for t in targets:
        if t["basis"] != "std":
            continue  # con adjudicated separately (detres is std-only, §42)
        if only and t["sym"] not in only:
            continue
        k = "%s|%d|std" % (t["sym"], t["qe"])
        if scan["cells"].get(k, {}).get("state") == "done":
            continue
        todo.append((k, t))
    todo = todo[:limit]
    print(
        "std cells pending: %d (ledger holds %d)"
        % (len(todo), sum(1 for v in scan["cells"].values() if v.get("state") == "done")),
        flush=True,
    )

    for _n, (k, t) in enumerate(todo, 1):
        sym, qe = t["sym"], t["qe"]
        code = codes.get(sym)
        rec = {"sym": sym, "qe": qe, "basis": "std", "fill_rev": t.get("rev"), "fill_op": t.get("op")}
        # live stored values
        rrow = (revop.get(sym) or {}).get(str(qe))
        frow = next((r for r in fund.get(sym, []) if r and r[0] == qe), None)
        rec["live_rev"] = rrow[0] if rrow else None
        rec["live_op"] = rrow[2] if rrow and len(rrow) > 2 else None
        rec["live_pat"] = frow[1] if frow and len(frow) > 1 else None
        if not code:
            rec.update(state="done", verdict="no-scrip", why=bse_resolve.blocked(sym) or "absent from ISIN-guarded map")
            scan["cells"][k] = rec
            continue
        try:
            fdict, _note = fetch(code, qid(qe))
        except RuntimeError as ex:
            rec.update(state="pending", verdict="fetch-failed", why=str(ex))
            scan["cells"][k] = rec
            json.dump(scan, open(SCAN, "w", encoding="utf-8"), indent=1)
            continue
        d0, d1 = parse_dt(fdict.get("Date Begin")), parse_dt(fdict.get("Date End"))
        raw[k] = fdict
        if d1 != qe:
            rec.update(state="done", verdict="no-detres-row", why=f"Date End {d1} != qe", date_begin=d0, date_end=d1)
            scan["cells"][k] = rec
            json.dump(scan, open(SCAN, "w", encoding="utf-8"), indent=1)
            json.dump(raw, open(RAW, "w", encoding="utf-8"), indent=0)
            time.sleep(sleep)
            continue
        revs = fields_of(fdict, R_REV)
        ops = fields_of(fdict, R_OP)
        nps = fields_of(fdict, R_NP)

        # Ind-AS detres prints NO operating-profit subtotal (§109f) — derive the two op
        # conventions this store uses: PBT−OI+FC (pre-D&A op) and +D&A (EBITDA), bank TI−TE.
        def f1(*names):
            for nm in names:
                v = fdict.get(nm)
                try:
                    return float(v) / 10.0
                except (TypeError, ValueError):
                    continue
            return None

        pbt = f1("Profit (+)/ Loss (-) from Ordinary Activities before Tax", "Profit before tax", "Profit Before Tax")
        oi = f1("Other Income") or 0.0
        fc = f1("Finance Costs", "Interest") or 0.0
        da = f1("Depreciation and amortisation expense", "Depreciation and amortization expense", "Depreciation") or 0.0
        if pbt is not None:
            ops.append(("derived:PBT-OI+FC", pbt - oi + fc))
            ops.append(("derived:PBT-OI+FC+DA", pbt - oi + fc + da))
        rec["detres_rev"] = revs
        rec["detres_op"] = ops
        rec["detres_np"] = nps
        rec["detres_eps"] = [(kk, vv * 10) for kk, vv in fields_of(fdict, R_EPS)]  # eps not scaled

        verdicts = {}
        for slot, stored in (
            ("rev", rec["live_rev"] if rec["live_rev"] is not None else t.get("rev")),
            ("op", rec["live_op"] if rec["live_op"] is not None else t.get("op")),
            ("pat", rec["live_pat"]),
        ):
            cands = {"rev": revs, "op": ops, "pat": nps}[slot]
            if stored is None:
                verdicts[slot] = "no-stored"
            elif not cands:
                verdicts[slot] = "no-detres-field"
            elif any(near(stored, v) for _, v in cands):
                verdicts[slot] = "EXACT"
            elif all(flag(stored, v) for _, v in cands):
                verdicts[slot] = "FLAG"
            else:
                verdicts[slot] = "NEAR"
        rec["verdicts"] = verdicts
        rec["state"] = "done"
        rec["verdict"] = "FLAG" if "FLAG" in verdicts.values() else "NEAR" if "NEAR" in verdicts.values() else "clean"
        scan["cells"][k] = rec
        print(
            "%-14s %d  rev:%-15s op:%-15s pat:%-8s -> %s"
            % (sym, qe, verdicts.get("rev"), verdicts.get("op"), verdicts.get("pat"), rec["verdict"]),
            flush=True,
        )
        json.dump(scan, open(SCAN, "w", encoding="utf-8"), indent=1)
        json.dump(raw, open(RAW, "w", encoding="utf-8"), indent=0)
        time.sleep(sleep)

    from collections import Counter

    print("---")
    for v, c in Counter(v.get("verdict") for v in scan["cells"].values()).most_common():
        print("  %-16s %d" % (v, c))


if __name__ == "__main__":
    main()
