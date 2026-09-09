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
"""Adjudicate stored fii==0.0 cells (Jun-2016+) against BSE's own XBRL copy of each filing.

Per cell verdicts, all evidence-carrying, never a default:
  HEAL_REPARSE  — today's parse_shp on BSE's copy yields fii > 0.05 (properly itemised filing;
                  the stored zero came from an older builder or a defective sibling document).
  ZERO_EXPLICIT — filing carries a foreign member fact and it sums ~0: as-filed zero, keep.
  ZERO_ARITH    — institutions block itemises domestic-only, no OtherInstitutions, block closes:
                  fii=0 proven arithmetically, keep.
  DERIVE_CAND   — no foreign member anywhere; OtherInstitutionsMember swallowed the block
                  (ASIANPAINT Jun-16 class). fii_cand = o_other − x_sym, where x_sym = the
                  symbol's own measured domestic-other (median o_other of its properly-itemised
                  anchor filings). Written ONLY if the chain gate corroborates (pass 2).
  NOCLOSE / NOPARSE / ABSENT / NOROW — journalled, never written.

Pass 2 (no network): chain-gate DERIVE candidates from trusted values (verified stored anchors,
HEAL_REPARSE values, ZERO_* cells) across adjacent quarters, step <= GATE_PP. |fii_cand| <= 0.35
after x_sym subtraction -> ZERO_LEARNED (the o_other is the symbol's own domestic residue).
"""
import collections
import json
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

SP = os.path.dirname(os.path.abspath(__file__))
HERE = os.environ.get("ZFII_WORKDIR") or SP  # caches + json outputs land here
sys.path.insert(0, SP)
import fetch_shareholding as FS
from curl_cffi import requests as cr

QCACHE = os.path.join(HERE, "qcache")
os.makedirs(QCACHE, exist_ok=True)
XCACHE = os.path.join(HERE, "xcache")
os.makedirs(XCACHE, exist_ok=True)
THREADS = 6
GATE_PP = 3.0  # seam per-cell corroboration precedent (runbook 22f round 4)
ZERO_BAND = 0.35  # |fii_cand| below this after x_sym subtraction = learned zero
CLOSE_TOL = 0.35  # institutions block closing tolerance (parse_shp's own recon number)

FOREIGN = {
    "InstitutionsForeignMember",
    "InstitutionsForeignPortfolioInvestorMember",
    "ForeignVentureCapitalInvestorsMember",
    "QualifiedForeignInvestorMember",
    "ForeignPortfolioInvestorsMember",
    "ForeignInstitutionalInvestorsMember",
    "ForeignDirectInvestmentMember",
    "ForeignNationalsMember",
}
DOM = {
    "MutualFundsOrUtiMember",
    "MutualFundsOrUTIMember",
    "AlternativeInvestmentFundsMember",
    "VentureCapitalFundsMember",
    "FinancialInstitutionOrBanksMember",
    "InsuranceCompaniesMember",
    "ProvidentFundsOrPensionFundsMember",
    "NbfcsRegisteredWithRbiMember",
    "NbfCsRegisteredWithRbiMember",
}
GOVT = {
    "CentralGovernmentOrStateGovernmentSOrPresidentOfIndiaMember",
    "GovermentsMember",
    "GovernmentsMember",
    "CentralGovernmentOrStateGovernmentSMember",
}
_lk = threading.Lock()


def get(url, tries=4, timeout=45):
    last = None
    for i in range(tries):
        try:
            r = cr.get(url, headers={"Referer": "https://www.bseindia.com/"}, impersonate="chrome", timeout=timeout)
            if r.status_code == 200:
                return r.content
            last = Exception("HTTP %d" % r.status_code)
            if r.status_code == 404 and i >= 1:
                raise last
        except Exception as e:
            last = e
        time.sleep(1.2 * (i + 1))
    raise last


_qlocks = collections.defaultdict(threading.Lock)


def quarter_list(code):
    cf = os.path.join(QCACHE, "q_%d.json" % code)
    with _qlocks[code]:
        if os.path.exists(cf) and os.path.getsize(cf) > 120:
            try:
                return json.load(open(cf))["Table"]
            except Exception:
                pass
        raw = get("https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode=%d" % code)
        open(cf, "wb").write(raw)
        return json.loads(raw).get("Table", [])


QMON = {"March": "-03-31", "June": "-06-30", "September": "-09-30", "December": "-12-31"}


def qe_of(qtr):
    p = str(qtr or "").split()
    if len(p) == 2 and p[0] in QMON and p[1].isdigit():
        return p[1] + QMON[p[0]]
    return None


def row_for(rows, qe):
    cand = [r for r in rows if qe_of(r.get("qtr")) == qe and (r.get("XbrlFile") or "").strip()]
    if not cand:
        return None
    cand.sort(key=lambda r: r.get("revised_date_time") or r.get("filing_date_time") or "")
    return cand[-1]


def xbrl_url(r):
    f = (r.get("XbrlFile") or "").strip()
    u = (r.get("xbrlurl") or "").strip()
    if u.lower().endswith(".xml"):
        return "https://www.bseindia.com" + u
    return "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + f


def fetch_xbrl(row):
    fn = (row.get("XbrlFile") or "").strip().replace("/", "_")
    cf = os.path.join(XCACHE, fn)
    if os.path.exists(cf) and os.path.getsize(cf) > 500:
        return open(cf, "rb").read()
    raw = get(xbrl_url(row))
    open(cf, "wb").write(raw)
    return raw


def facts_of(root):
    """{member: pct} for single-explicit-member untyped ShareholdingAsAPercentageOfTotal... facts."""

    def strip(t):
        return t.split("}", 1)[-1]

    ctx = {}
    for c in root.iter():
        if strip(c.tag) != "context":
            continue
        mems, typed = [], False
        for m in c.iter():
            st = strip(m.tag)
            if st == "explicitMember":
                mems.append((m.text or "").split(":")[-1].strip())
            elif st == "typedMember":
                typed = True
        ctx[c.get("id")] = mems[0] if (not typed and len(mems) == 1) else None
    vals = {}
    for f in root.iter():
        if strip(f.tag) != "ShareholdingAsAPercentageOfTotalNumberOfShares":
            continue
        mem = ctx.get(f.get("contextRef"))
        if not mem:
            continue
        try:
            vals[mem] = float(str(f.text).strip())
        except (TypeError, ValueError):
            continue
    return vals


def iso_day(s):
    s = str(s or "")
    return s[:10] if len(s) >= 10 and s[4] == "-" else ""


def main():
    targets = json.load(open(os.path.join(HERE, "targets_xbrl.json")))
    hist = json.load(open(os.path.join(SP, "shp_history.json"), encoding="utf-8"))
    hist.get("_names", {})
    scrips = json.load(open(os.path.join(SP, "bse_scrips.json")))["by_id"]
    master = json.load(open(os.path.join(SP, "_bse_master_all.json")))
    override = json.load(open(os.path.join(SP, "_shp_scripcode_override.json")))
    rmap = json.load(open(os.path.join(SP, "_rename_map.json")))

    by_id = {}
    for row in master:
        sid = str(row.get("scrip_id") or "").strip().upper()
        if sid and sid not in by_id:
            by_id[sid] = int(row["SCRIP_CD"])

    def norm(s):
        seen = set()
        while s in rmap and s not in seen and rmap[s] != s:
            seen.add(s)
            s = rmap[s]
        return s

    def code_of(sym):
        for k in (sym, norm(sym)):
            if k in override:
                v = override[k]
                return int(v["scripcode"] if isinstance(v, dict) else v)
            if k in scrips:
                return int(scrips[k])
            if k in by_id:
                return by_id[k]
        return None

    # fetch set: target cells + run-anchor quarters >= 2016-06-30 (to learn x_sym + verify anchors)
    fetch = {}
    for t in targets:
        fetch[(t["sym"], t["qe"])] = "target"
    for t in targets:
        for aqe, _afii in t["anchors"].values():
            if aqe >= "2016-06-30" and (t["sym"], aqe) not in fetch:
                fetch[(t["sym"], aqe)] = "anchor"
    items = sorted(fetch.items())
    print(
        "fetch set: %d cells (%d targets + %d anchors), %d symbols"
        % (
            len(items),
            sum(1 for _, k in items if k == "target"),
            sum(1 for _, k in items if k == "anchor"),
            len({s for (s, _), _ in items}),
        )
    )

    unresolved = sorted({s for (s, _), _ in items if code_of(s) is None})
    if unresolved:
        print("NO SCRIPCODE (%d syms): %s" % (len(unresolved), ", ".join(unresolved)))

    out = {}
    stats = collections.Counter()

    def work(item):
        (sym, qe), kind = item
        code = code_of(sym)
        if code is None:
            return sym, qe, kind, {"verdict": "NOCODE"}
        try:
            rows = quarter_list(code)
        except Exception as e:
            return sym, qe, kind, {"verdict": "ERR", "err": f"qlist {e!r}"}
        r = row_for(rows, qe)
        if r is None:
            return sym, qe, kind, {"verdict": "NOROW", "code": code}
        try:
            raw = fetch_xbrl(r)
            root = ET.fromstring(raw)
        except Exception as e:
            if "404" in repr(e):
                return sym, qe, kind, {"verdict": "ABSENT", "code": code}
            return sym, qe, kind, {"verdict": "ERR", "err": repr(e)[:120], "code": code}
        p = FS.parse_shp(root, qe)
        fx = facts_of(root)
        if isinstance(p, dict):
            p.get("nsh")
        ev = {
            "code": code,
            "file": (r.get("XbrlFile") or "")[:70],
            "sub": iso_day(r.get("revised_date_time") or r.get("filing_date_time")) or (qe[:8] + "21"),
            "revised": bool(r.get("revised_date_time")),
        }
        foreign_present = sorted(k for k in fx if k in FOREIGN)
        oo = fx.get("OtherInstitutionsMember")
        oi = fx.get("InstitutionsMember")
        dom_sum = sum(v for k, v in fx.items() if k in DOM and k != "MutualFundsOrUTIMember")
        # avoid double-count when both MF spellings carry the same fact
        if "MutualFundsOrUTIMember" in fx and "MutualFundsOrUtiMember" not in fx:
            dom_sum += fx["MutualFundsOrUTIMember"]
        govt = sum(v for k, v in fx.items() if k in GOVT) / max(1, len([k for k in fx if k in GOVT]))
        unknown = sorted(
            k
            for k in fx
            if k not in FOREIGN
            and k not in DOM
            and k not in GOVT
            and k not in ("InstitutionsMember", "OtherInstitutionsMember")
            and ("oreign" in k or "Fii" in k or "Fpi" in k or "nstitut" in k)
        )
        ev.update(
            {
                "foreign_mem": foreign_present,
                "o_other": oo,
                "o_inst": oi,
                "dom_sum": round(dom_sum, 4),
                "govt": round(govt, 4),
                "unknown_inst_mem": unknown,
                "parse": None
                if not isinstance(p, dict)
                else {k: p.get(k) for k in ("prom", "fii", "dii", "mf", "ins", "nsh")},
            }
        )
        if not isinstance(p, dict):
            ev["verdict"] = "NOPARSE"
            return sym, qe, kind, ev
        if kind == "anchor":
            ev["verdict"] = "ANCHOR"
            return sym, qe, kind, ev
        if p["fii"] > 0.05:
            ev["verdict"] = "HEAL_REPARSE"
            return sym, qe, kind, ev
        if foreign_present:
            ev["verdict"] = "ZERO_EXPLICIT"
            return sym, qe, kind, ev
        if oi is None:
            ev["verdict"] = "NOBLOCK"
            return sym, qe, kind, ev
        c1 = oi - (dom_sum + (oo or 0.0))
        c2 = c1 - govt
        closing = c1 if abs(c1) <= abs(c2) else c2
        ev["closing"] = round(closing, 4)
        if abs(closing) > CLOSE_TOL:
            ev["verdict"] = "NOCLOSE"
            return sym, qe, kind, ev
        if not oo or oo <= 0.05:
            ev["verdict"] = "ZERO_ARITH"
            return sym, qe, kind, ev
        ev["verdict"] = "DERIVE_CAND"
        return sym, qe, kind, ev

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = {ex.submit(work, it): it for it in items}
        done = 0
        for fut in as_completed(futs):
            sym, qe, _kind, ev = fut.result()
            with _lk:
                out[f"{sym}|{qe}"] = ev
                stats[ev["verdict"]] += 1
                done += 1
                if done % 100 == 0:
                    print("  ... %d/%d (%.0fs) %s" % (done, len(items), time.time() - t0, dict(stats)))
    print(f"\nfetch pass done in {time.time() - t0:.0f}s: {dict(stats)}")
    json.dump(out, open(os.path.join(HERE, "adjudication_raw.json"), "w"), indent=1)
    print("-> adjudication_raw.json (pass 2 = chain gate, separate script)")


if __name__ == "__main__":
    main()
