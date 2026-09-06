# -*- coding: utf-8 -*-
"""STEP E — re-gate cells STEP D refused ONLY because it could not READ the EPS.

WHY THIS EXISTS
STEP D's refusal ledger carries 1,957 cells whose reason is
`E: EPS-recon inputs missing (eps=None eqcap=<num> fv=<num>)` — equity capital and face value
parsed fine, so the ONLY blocker was an unmatched EPS label. BSE detres always prints an EPS; it
just uses six different labels:

    Basic & Diluted EPS {after,before} Extraordinary items
    Basic EPS          {after,before} Extraordinary items
    Diluted EPS        {after,before} Extraordinary items

Sampled live 2026-08-07: 16 of 16 detres quarters had one. So these are not missing data, they
are an unread field — the same class as the two revenue-label bugs fixed in STEP W on 08-06.

THE PROOF (GATE E, unchanged in spirit from STEP D/W)
    shares  = equity capital / face value
    implied = PAT / shares
    land only if |implied - printed EPS| <= max(2% of EPS, 0.05)
This is a genuine independent check: PAT, equity capital, face value and EPS are four separately
printed fields, and a misparse of any one of them breaks the identity. It proves the PAT.

WHAT IT DOES *NOT* PROVE: revenue. Gate E says nothing about the revenue row, which merely rides
along from the same document. So, following STEP W's own rule, NON-POSITIVE revenue is stored as
None rather than landed — real-estate filers legitimately print negative revenue on
percentage-of-completion reversals (verified on DBREALTY and ORBITCORP Mar-2014, whose filings
really do read -0.67 and -239.48 rs-million), and a negative "revenue" is not something this
dataset should serve.

PERIOD DISCIPLINE: the qid->quarter mapping is derived but NEVER trusted. Every response's own
`Date End` is read and must equal the quarter we asked for, else the response is discarded. A
fetched quarter is never re-labelled to fit the cell being filled.

Run:  python -X utf8 -u scripts/_stepe_eps_regate.py [--years 2014] [--limit N]
Writes: scripts/pre2015_reads_e.json  (+ scripts/pre2015_attempted_e.json)
Applied by _apply_reads.py --pre2015 (gate "E").
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_fundamentals as BF  # noqa: E402

OUTP = os.path.join(HERE, "pre2015_reads_e.json")
ATTP = os.path.join(HERE, "pre2015_attempted_e.json")
CACHE = os.path.join(HERE, "_stepe_cache")
os.makedirs(CACHE, exist_ok=True)

MON = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

# The reconciliation partner for the NET PROFIT row is an "after extraordinary items" EPS.
# Basic before Diluted: diluted counts potential shares the PAT was never earned on.
EPS_PREF = ["basic & diluted eps after extraordinary", "basic eps after extraordinary",
            "diluted eps after extraordinary", "basic & diluted eps before extraordinary",
            "basic eps before extraordinary", "diluted eps before extraordinary"]
REV_PREF = ["net sales/revenue from operations", "net sales / income from operations",
            "total income from operations", "income from operations", "interest earned"]


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def detres(scrip, qid):
    """Cached detres fetch. Re-runs are free, which keeps a retry cheap."""
    cp = os.path.join(CACHE, "d_%s_%d.json" % (scrip, qid))
    if os.path.exists(cp):
        try:
            return json.load(open(cp, encoding="utf8"))
        except Exception:
            os.remove(cp)
    u = ("https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w"
         "?scrip_cd=%s&qtr=%d.00" % (scrip, qid))
    d = BF._get(u, headers={"User-Agent": BF.UA, "Accept": "application/json",
                            "Referer": "https://www.bseindia.com/"})
    if isinstance(d, bytes):
        d = d.decode("utf8", "replace")
    rows = json.loads(d).get("table1", []) or []
    json.dump(rows, open(cp, "w", encoding="utf8"))
    return rows


def fields(rows):
    out = {}
    for r in rows:
        k = (r.get("fld_desc") or "").strip()
        if k and k not in out:
            out[k] = (r.get("Value") or "").strip()
    return out


def pick(f, prefs, exact=False):
    for want in prefs:
        for k, v in f.items():
            kl = k.lower()
            if (kl == want) if exact else kl.startswith(want):
                n = _num(v)
                if n is not None:
                    return n
    return None


def qend_of(f):
    m = re.match(r"(\d{2})-(\w{3})-(\d{2,4})", f.get("Date End", ""))
    if not m:
        return None
    y = int(m.group(3))
    y += 2000 if y < 100 else 0
    return y * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))


def qid_for(qe):
    """Calendar-sequential: qid 81 == Jan-Mar 2014 (verified live). Always re-verified
    against the response's own Date End before anything is trusted."""
    y, md = qe // 10000, qe % 10000
    return 81 + (y - 2014) * 4 + {331: 0, 630: 1, 930: 2, 1231: 3}[md]


def main():
    argv = sys.argv
    years = [int(x) for x in argv[argv.index("--years") + 1].split(",")] if "--years" in argv else [2014]
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None

    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf8"))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"), encoding="utf8"))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    gaps = json.load(open(os.path.join(HERE, "_gaps_0214.json"), encoding="utf8"))
    code = {g["sym"]: str(g["bse_code"]) for g in gaps if g.get("bse_code")}

    sys.path.insert(0, HERE)
    import _n500_member_bin as MB

    targets = []
    for y in years:
        for md in (331, 630, 930, 1231):
            qe = y * 10000 + md
            for sym in MB.membership(qe):
                row = fmap.get(sym, {}).get(qe)
                rr = revop.get(sym, {}).get(str(qe))
                if (row and row[1] is not None) and (rr and rr[0] is not None):
                    continue
                if sym in code:
                    targets.append((sym, qe))
    if limit:
        targets = targets[:limit]

    out = json.load(open(OUTP, encoding="utf8")) if os.path.exists(OUTP) else {}
    att = json.load(open(ATTP, encoding="utf8")) if os.path.exists(ATTP) else {}
    print("STEP E targets: %d cells (years %s)" % (len(targets), years), flush=True)

    land = ref = 0
    for i, (sym, qe) in enumerate(targets, 1):
        if str(qe) in out.get(sym, {}) or "%s|%d" % (sym, qe) in att:
            continue
        try:
            rows = detres(code[sym], qid_for(qe))
        except Exception as e:
            print("  !! fetch fail %s %d :: %s" % (sym, qe, str(e)[:60]), flush=True)
            continue                      # transient -> stays retryable, never a refusal
        f = fields(rows)
        if not rows or qend_of(f) != qe:
            att["%s|%d" % (sym, qe)] = {"reason": "no-detres-row-for-that-quarter"}
            ref += 1
            continue
        pat = pick(f, ["net profit"], exact=True)
        eps = pick(f, EPS_PREF)
        eq = pick(f, ["equity capital"], exact=True)
        fv = pick(f, ["face value"])
        rev = pick(f, REV_PREF)
        if None in (pat, eps, eq, fv) or not fv or not eq:
            att["%s|%d" % (sym, qe)] = {
                "reason": "gate-E inputs still missing (pat=%s eps=%s eqcap=%s fv=%s)" % (pat, eps, eq, fv)}
            ref += 1
            continue
        shares = eq / fv
        implied = pat / shares
        tol = max(0.02 * abs(eps), 0.05)
        if abs(implied - eps) > tol:
            att["%s|%d" % (sym, qe)] = {
                "reason": "gate-E FAILS implied=%.4f seen=%.4f tol=%.4f" % (implied, eps, tol)}
            ref += 1
            continue
        # gate E proves the PAT only. Revenue rides along and must clear the
        # campaign's own positivity rule before it is stored.
        rev_cr = rev / 10.0 if (rev is not None and rev > 0) else None
        out.setdefault(sym, {})[str(qe)] = {
            "rev": None if rev_cr is None else round(rev_cr, 2),
            "op": None,
            "pat": round(pat / 10.0, 2),
            "basis": "std",
            "fin": 0,
            "gate": "E",
            "ann": 0,
            "ann_approx": True,
            "derived": None,
            "src": "bse-detres qid%d | GATE-E EPS-recon implied=%.4f seen=%.4f (eqcap=%.2f fv=%.2f)"
                   % (qid_for(qe), implied, eps, eq, fv),
        }
        land += 1
        print("%-12s %d  gate=E rev=%9s pat=%9.2f  EPS %.2f==%.2f" % (
            sym, qe, ("%.2f" % rev_cr) if rev_cr else "None", pat / 10.0, eps, implied), flush=True)
        if land % 25 == 0:
            _dump(out, att)
        time.sleep(0.35)

    _dump(out, att)
    print("DONE landed=%d refused=%d" % (land, ref), flush=True)


def _dump(out, att):
    json.dump(out, open(OUTP, "w", encoding="utf8"), indent=0, sort_keys=True)
    json.dump(att, open(ATTP, "w", encoding="utf8"), indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
