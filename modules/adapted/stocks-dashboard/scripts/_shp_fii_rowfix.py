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
"""Row-level FII heal for the 2015-2022 old-format XBRL era (DATA_RUNBOOK §159) — the FII twin of §158.
FII = Institutions(Foreign) B2 (minus depository receipts, §151) in every format. The old form kept strategic /
PE foreign holders under Non-institutions -> "Any Other" rows ("Foreign Companies", "Bodies Corporate", "Overseas
Corporate Bodies"); the filer's own 2022-form filing lists many of them under B2 (Foreign Direct Investment / FPI),
so the Sep-2022 seam showed +71.8 pp (PAYTM), +47.9 (ETERNAL), +30.0 (ITC) ... on the FII side.
Rule R2-FII, one old-format filing at a time (Non-institutions -> Any Other rows only; Institutions rows were
adjudicated by §158 R1):
  * a >=1% holder that the filer's FIRST 2022-form filing places under Institutions(Foreign) (FDI / FPI / FVCI /
    foreign SWF / other foreign institution) -> fii;  placed under Foreign Companies / Bodies Corporate / NRI /
    other non-institutions -> stays public;
  * a holder absent from that filing: fii only when its own name carries an institution tag ((FPI)/(FII)/foreign
    portfolio/foreign institutional/FVCI/foreign venture/foreign bank/sovereign) or (§164r batch 7, 'Documents only') another
    company's filing lists the same legal name under Institutions (Foreign) (shp_foreign_holder_evidence.json inst=true; the SW-2 curated verdict alone no longer counts);
    every other name is decided by its row LABEL — and every non-institution label is public;
  * a whole row whose LABEL is FII-type (Foreign Portfolio Investors / FII / QFI / foreign institution ...) is fii,
    less any domestic-classified holder inside it.
Nothing else moves: dii, mf, ins untouched; the change is a pure public -> fii move, so fii+dii+prom can only grow
by what the filer itself reports in the row. Materiality 0.05 pp.
Stages: classify -> <work>/fii_proposals.json ; one SYM,.. ; verify ; revfix -> <work>/fii_revfix.json ; write
(merges into scripts/shp_cell_fix.json with `superseded`, evidence in scripts/_shp_fii_rowfix_audit.json, re-filing
rows in scripts/shp_revisions.json). Reuses scripts/_shp_dii_rowfix.py (rows_of/groups/SymCtx/match_filing) and the
same DII_ROWFIX_* inputs; FII_ROWFIX_WORK = output dir (default: the DII work dir).
"""
import collections
import copy
import json
import os
import re
import sys
import time

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import contextlib

import _shp_dii_rowfix as D
import fetch_shareholding as F

WORK = os.environ.get("FII_ROWFIX_WORK") or D.HERE
MARK = "§159 row-level FII heal"
INST_TAG = re.compile(
    r"\((fpi|fii|fdi)\)|\bfpi\b|\bfii\b|\bfdi\b|foreign direct|foreign portfolio|foreign institutional|\bfvci\b|foreign venture|foreign bank|sovereign",
    re.I,
)

DII_AUDIT = os.path.join(SCRIPTS, "_shp_dii_rowfix_audit.json")
_dii_files = None


def pick_filing(sym, qe, cur, fl, led):
    """The old-format filing behind the stored row: (a) the file §158 recorded for this cell, (b) the parse that
    matches the stored row, (c) the parse that matches an earlier `was` in the cell's ledger chain (a §158 heal
    moved dii/fii sums, so the raw parse no longer matches the healed store)."""
    global _dii_files
    if _dii_files is None:
        _dii_files = (
            {k: v.get("file") for k, v in (json.load(open(DII_AUDIT)).get("cells") or {}).items()}
            if os.path.exists(DII_AUDIT)
            else {}
        )
    f = _dii_files.get(f"{sym}|{qe}")
    if f and D.find_file(f):
        txt = open(D.find_file(f), "rb").read()
        try:
            bd = D.breakdown(txt)
            res = F.parse_shp(txt, qe)
        except Exception:
            res = None
        if res and "InstitutionsMember" in bd and "InstitutionsDomesticMember" not in bd:
            return f, txt, bd, res, "dii-audit"
    ch = D.match_filing(fl, qe, cur)
    if ch:
        return ch + ("match",)
    e = (led.get(sym) or {}).get(qe)
    depth = 0
    while isinstance(e, dict) and depth < 8:
        was = e.get("was")
        if was:
            ch = D.match_filing(fl, qe, was)
            if ch:
                return ch + ("ledger-was@%d" % depth,)
        e = e.get("superseded")
        depth += 1
    return None


NEWFII = {
    "InstitutionsForeign",
    "ForeignDirectInvestment",
    "ForeignVentureCapitalInvestors",
    "SovereignWealthFunds",
    "OtherInstitutionsForeign",
}
NEWPUB = {
    "ForeignCompanies",
    "ForeignNationals",
    "OtherForeignShareholders",
    "BodiesCorporate",
    "OtherNonInstitutions",
    "NonResidentIndians",
    "NonResidentIndividualsOrForeignIndividuals",
    "OtherIndianShareholders",
    "IndividualsOrHUF",
}


def newmap_multi(sym, bse_rows):
    """Holder -> [(cls, axis, pct), ...] from the filer's FIRST 2022-form filing — EVERY row the name appears on
    (ASTERDM lists Olympus Capital 20.36 under Foreign Companies AND 2.60 under FVCI; a name->one-axis map kept the
    last row). Same file choice as _shp_dii_rowfix.newmap_for."""
    cands = sorted(
        [
            (D.qe_of(r.get("qtr")), (r.get("XbrlFile") or "").strip())
            for r in bse_rows
            if D.qe_of(r.get("qtr")) and D.qe_of(r.get("qtr")) >= "2022-09-30" and r.get("XbrlFile")
        ]
    )
    for _qe, f in cands[:3]:
        p = D.find_file(f)
        if not p:
            continue
        txt = open(p, "rb").read()
        bd = D.breakdown(txt)
        if "InstitutionsDomesticMember" not in bd and "InstitutionsForeignMember" not in bd:
            continue
        M = {}
        for ax, _seq, pct, kind, _cat, name in D.rows_of(txt):
            if kind.lower().startswith("categ") or not name:
                continue
            cls = (
                "fii"
                if (
                    ax.startswith("ForeignPortfolioInvestor")
                    or ax.startswith("InstitutionsForeignPortfolioInvestor")
                    or ax in NEWFII
                )
                else "public"
                if ax in NEWPUB
                else "domestic"
            )
            M.setdefault(D.norm(name), []).append((cls, ax, pct))
        return M, f
    return {}, None


class FiiCtx(D.SymCtx):
    """SymCtx whose 2022-form lookup is size-aware: when the filer lists the holder on several rows, the row whose
    size is closest to the old-form holding decides (tie/none close -> the largest row)."""

    def __init__(self, sym, bse_rows, verdicts):
        super().__init__(sym, bse_rows, verdicts)
        self.multi = None

    def _pick(self, ents, hp):
        if len(ents) == 1:
            return ents[0]
        best = min(ents, key=lambda e: abs(e[2] - hp))
        return best if abs(best[2] - hp) <= max(1.0, 0.25 * hp) else max(ents, key=lambda e: e[2])

    def hclass_p(self, hn, hp):
        if D.fdi_line(self.sym, hn):
            return (
                "foreign",
                "fii",
                "new-format:ForeignDirectInvestment(any filing)",
            )  # §164r batch 14 (user 2026-10-04 'yes go with A')
        if self.multi is None:
            self.multi, self.newfile = newmap_multi(self.sym, self.bse_rows)
            self.newmap = {
                k: (self._pick(v, 0)[0], self._pick(v, 0)[1]) for k, v in self.multi.items()
            }  # keeps the parent class usable
        n = D.norm(hn)
        ents = self.multi.get(n)
        how = None
        if ents:
            cls, ax, pct = self._pick(ents, hp)
            how = "new-format:" + ax
        else:
            best = None
            for k, v in self.multi.items():
                if len(n) >= 10 and len(k) >= 10 and abs(len(n) - len(k)) <= 8:
                    r = D.difflib.SequenceMatcher(None, n, k).ratio()
                    if r >= 0.85 and (best is None or r > best[0]):
                        best = (r, v)
            if best:
                cls, ax, pct = self._pick(best[1], hp)
                how = "new-format~:" + ax
        if how:
            c = "foreign" if cls in ("fii", "public") else "domestic"
            dest = cls if cls in ("fii", "public") else None
            self.memory[n] = (c, dest, how)
            return c, dest, how
        c, dest, src = D.holder_class(hn, self.verdicts, {})
        if (
            src == "curated"
        ):  # §164r batch 7: a curated foreign verdict carries FII into later quarters only with an institution document
            if c == "foreign":
                dest = "fii" if D.inst_documented(hn) else "public"
            self.memory[n] = (c, dest, src)
            return c, dest, src
        if n in self.memory:
            c, dest, src = self.memory[n]
            return c, dest, "memory"
        for k, v in self.memory.items():
            if len(n) >= 8 and D.difflib.SequenceMatcher(None, n, k).ratio() >= 0.85:
                c, dest, src = v
                return c, dest, "memory~"
        return c, dest, src


def eval_fii(ctx, qe, txt, bd, res, cur):
    """R2-FII on one old-format filing -> dict(mv, ev) ; mv = pp to add to the stored fii."""
    rows = D.rows_of(txt)
    gn = D.groups(rows, "OtherNonInstitutions")
    mv = 0.0
    ev = []
    for g in gn:
        lab = g["label"]
        lab_fii = (
            bool(D.LAB_FII.search(lab)) and not D.DOMLAB.search(lab) and not D.LAB_PUB.search(lab)
        )
        hs = [(hp, hn) + ctx.hclass_p(hn, hp) for hp, hn in g["holders"]]
        (sum(h[0] for h in hs) <= g["pct"] + 0.02)
        take = 0.0
        desc = []
        if lab_fii:
            # the filer's own FII/FPI-labelled block moves whole, less any holder classified domestic and less any holder
            # the filer's OWN 2022 form places outside Institutions(Foreign) (KIMS: General Atlantic 17.24 sat in a row
            # labelled "Foreign Portfolio Investor (Category - III)" but the 2022 form lists it under Foreign Companies)
            stay = [
                h
                for h in hs
                if h[2] == "domestic"
                or (
                    h[3] == "public"
                    and (h[4].startswith("new-format") or h[4] in ("memory", "memory~"))
                )
            ]
            out = sum(h[0] for h in stay)
            take = max(0.0, g["pct"] - out)
            desc.append(
                "FII-labelled row {:.2f} -> fii{}".format(
                    g["pct"], (f" less holders placed elsewhere {out:.2f}") if out else ""
                )
            )
            for hp, hn, c, dest, src in hs:
                desc.append(
                    "{} {:.2f} {}({})".format(
                        hn, hp, "stay" if (hp, hn, c, dest, src) in stay else "in-row", src or "-"
                    )
                )
        else:
            for hp, hn, c, dest, src in hs:
                if src.startswith("new-format") or src in ("memory", "memory~"):
                    go = dest == "fii"
                    how = src
                elif c == "foreign" and D.inst_documented(hn):
                    go = True
                    how = "documented-institution"  # §164r batch 7 'Documents only': not the curated list alone
                elif c != "domestic" and INST_TAG.search(hn):
                    go = True
                    how = "inst-tag"  # §164r batch 8: the company's own tag is itself the mark (Blackstone Capital Partners (Singapore) VI FDI Two at SHK had no residency document)
                else:
                    go = False
                    how = src or "label"
                if go:
                    take += hp
                desc.append("{} {:.2f} {}({})".format(hn, hp, "fii" if go else "stay", how))
        if take > 0.0049:
            mv += take
            ev.append(
                (
                    "R2FII-label" if lab_fii else "R2FII-holders",
                    lab,
                    round(g["pct"], 4),
                    round(take, 4),
                    "; ".join(desc),
                )
            )
    block = bd.get("OtherNonInstitutionsMember") or 0.0
    if mv > block + 0.05:
        ev.append(("R2FII-overflow", round(mv, 4), round(block, 4)))
        mv = 0.0  # the rows claim more than the block: leave the cell
    return {"mv": round(mv, 4), "ev": ev}


def classify(only=None, verbose=False):
    syms = json.load(open(os.path.join(D.HERE, "n500_syms.json")))
    if only:
        syms = [x for x in syms if x in only]
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    led = json.load(open(os.path.join(REPO, "scripts", "shp_cell_fix.json"))).get("fix", {})
    verdicts = D.load_verdicts()
    P = {}
    stats = collections.Counter()
    t0 = time.time()
    for si, sym in enumerate(syms):
        lp = os.path.join(D.LISTS, sym + ".json")
        if not os.path.exists(lp):
            stats["no_bse_list"] += 1
            continue
        d = json.load(open(lp))
        bse_rows = d.get("Table") if isinstance(d, dict) else d
        byq = D.quarter_files(bse_rows)
        ctx = FiiCtx(sym, bse_rows, verdicts)
        # two passes like §158: newest first warms the holder memory, the chronological pass is final
        order = [(q, f, False) for q, f in sorted(byq.items(), reverse=True)] + [
            (q, f, True) for q, f in sorted(byq.items())
        ]
        for qe, fl, final in order:
            if final:
                stats["rows"] += 1
            cur = (hist.get(sym) or {}).get(qe)
            if not cur:
                if final:
                    stats["no_store_row"] += 1
                continue
            chosen = pick_filing(sym, qe, cur, fl, led)
            if not chosen:
                if final:
                    if not any(D.find_file(f) for fd, f in fl):
                        stats["not_cached"] += 1
                    else:
                        stats["no_matching_filing"] += 1
                        verbose and print(
                            f"  {qe} NO MATCHING FILING stored={cur[:3]} files={[x[1] for x in fl]}"
                        )
                continue
            f, txt, bd, res, how = chosen
            r = eval_fii(ctx, qe, txt, bd, res, cur)
            if not final:
                continue
            stats["matched"] += 1
            stats["pick_" + how.split("@")[0]] += 1
            if any(e[0] == "R2FII-overflow" for e in r["ev"]):
                stats["overflow"] += 1
            if verbose:
                print(
                    "  {} {} stored fii {:.2f} -> +{:.2f} | {}".format(
                        qe, f, cur[1] or 0, r["mv"], "; ".join(str(e)[:200] for e in r["ev"])
                    )
                )
            if r["mv"] < 0.05:
                stats["unchanged"] += 1
                continue
            new = list(cur)
            new[1] = round((cur[1] or 0) + r["mv"], 4)
            prior = (led.get(sym) or {}).get(qe)
            P[f"{sym}|{qe}"] = {
                "file": f,
                "was": cur,
                "cell": new,
                "d_fii": r["mv"],
                "ev": r["ev"],
                "prior_entry": bool(prior),
                "prior_applied": bool(prior and F._cell_eq(cur, prior.get("cell"))),
                "newmap_file": ctx.newfile,
            }
            stats["proposed"] += 1
        if si % 50 == 0:
            print(
                "  %d/%d %s %s %.0fs" % (si, len(syms), sym, dict(stats), time.time() - t0),
                file=sys.stderr,
            )
    outp = "fii_proposals_one.json" if only else "fii_proposals.json"
    json.dump(P, open(os.path.join(WORK, outp), "w"), indent=0)
    print("classify done", dict(stats))
    return P


def fseam(h, syms, qa="2022-06-30", qb="2022-09-30"):
    ds = []
    for s in syms:
        a = (h.get(s) or {}).get(qa)
        b = (h.get(s) or {}).get(qb)
        if a and b and a[1] is not None and b[1] is not None:
            ds.append((b[1] - a[1], s, a[1], b[1]))
    v = sorted(x[0] for x in ds)
    import statistics as st

    def q(p):
        return v[int(p * (len(v) - 1))]

    return {
        "n": len(v),
        "median": round(st.median(v), 2),
        "p5": round(q(0.05), 2),
        "p95": round(q(0.95), 2),
        "ge3": sum(1 for x in v if abs(x) >= 3),
        "ge5": sum(1 for x in v if abs(x) >= 5),
    }, sorted(ds, key=lambda x: -abs(x[0]))[:20]


def verify():
    P = json.load(open(os.path.join(WORK, "fii_proposals.json")))
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    syms = json.load(open(os.path.join(D.HERE, "n500_syms.json")))
    H = copy.deepcopy(hist)
    n = bad = 0
    for k, v in P.items():
        sym, qe = k.split("|")
        cur = H[sym][qe]
        if not F._cell_eq(cur, v["was"]):
            bad += 1
            continue
        H[sym][qe] = list(v["cell"])
        n += 1
        c = v["cell"]
        if c[1] + c[2] > 100 - c[0] + 0.5 or c[1] < 0 or c[1] > 100:
            print("SANITY", k, c)
    print("applied %d (was-mismatch %d)" % (n, bad))
    for qa, qb in (
        ("2022-06-30", "2022-09-30"),
        ("2015-03-31", "2015-06-30"),
        ("2016-03-31", "2016-06-30"),
        ("2016-06-30", "2016-09-30"),
        ("2021-12-31", "2022-03-31"),
    ):
        b0, _ = fseam(hist, syms, qa, qb)
        a0, t0 = fseam(H, syms, qa, qb)
        print(f"fii seam {qa}->{qb} before {b0} after {a0}")
        if qb == "2022-09-30":
            for d, s, a, b in t0:
                print("   %-12s %7.2f -> %7.2f (%+.2f)" % (s, a, b, d))
    json.dump(
        H, open(os.path.join(WORK, "shp_history_fii_healed.json"), "w"), separators=(",", ":")
    )


def revfix():
    P = json.load(open(os.path.join(WORK, "fii_proposals.json")))
    revs = json.load(open(os.path.join(REPO, "scripts", "shp_revisions.json")))
    verdicts = D.load_verdicts()
    out = {}
    stats = collections.Counter()
    for k, v in sorted(P.items()):
        sym, qe = k.split("|")
        rc = (revs.get(sym) or {}).get(qe)
        if not rc:
            continue
        stats["rev_rows"] += 1
        if (
            abs(float(rc[1]) - float(v["was"][1])) <= 0.0100001
            and abs(float(rc[2]) - float(v["was"][2])) <= 0.0100001
        ):
            new = list(rc)
            new[1] = v["cell"][1]
            out[k] = {
                "was": rc,
                "cell": new,
                "how": "same raw fii/dii as the original -> original's healed fii",
            }
            stats["same_raw"] += 1
            continue
        d = json.load(open(os.path.join(D.LISTS, sym + ".json")))
        bse_rows = d.get("Table") if isinstance(d, dict) else d
        fl = D.quarter_files(bse_rows).get(qe, [])
        ctx = FiiCtx(sym, bse_rows, verdicts)
        chosen = D.match_filing([x for x in fl if x[1] != v["file"]], qe, rc) or D.match_filing(
            fl, qe, rc
        )
        if not chosen:
            out[k] = {"was": rc, "how": "NO MATCHING DOCUMENT for the re-filing row (left as is)"}
            stats["no_doc"] += 1
            continue
        f, txt, bd, res = chosen
        r = eval_fii(ctx, qe, txt, bd, res, rc)
        if any(e[0] == "R2FII-overflow" for e in r["ev"]):
            out[k] = {"was": rc, "how": "overflow (left as is)"}
            stats["overflow"] += 1
            continue
        if r["mv"] < 0.05:
            stats["rev_unchanged"] += 1
            continue
        new = list(rc)
        new[1] = round(float(rc[1]) + r["mv"], 4)
        out[k] = {
            "was": rc,
            "cell": new,
            "how": "re-filing document {} re-read: {}".format(
                f, "; ".join(" ".join(str(x) for x in e) for e in r["ev"])[:600]
            ),
        }
        stats["re_read"] += 1
    json.dump(out, open(os.path.join(WORK, "fii_revfix.json"), "w"), indent=0)
    print("revfix", dict(stats))
    return out


def write(stamp=None):
    stamp = stamp or time.strftime("%Y-%m-%d")
    P = json.load(open(os.path.join(WORK, "fii_proposals.json")))
    path = os.path.join(REPO, "scripts", "shp_cell_fix.json")
    raw = open(path, encoding="utf-8").read()
    led = json.loads(raw)
    fix = led.setdefault("fix", {})
    ascii_only = "\\u00" in raw
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    n_new = n_sup = n_skip = 0
    audit = {
        "_doc": [
            f"{MARK} ({stamp}), old-format XBRL era Jun-2015..Jun-2022, Nifty 500. FII = Institutions(Foreign) B2 (less depository receipts, §151) in every format.",
            "R2-FII Non-institutions -> Any Other rows: a >=1% holder the filer's FIRST 2022-form filing places under Institutions(Foreign) (FDI/FPI/FVCI/foreign SWF) joins fii; one it places under Foreign Companies / Bodies Corporate / NRI / other non-institutions stays public; a holder absent from that filing joins fii only on an institution tag in its own name or another company's filing listing it under Institutions (Foreign) (§164r batch 7: the curated list alone no longer counts), else its row label decides (every non-institution label is public). A row whose LABEL is FII-type (FPI/FII/QFI/foreign institution) is fii in full, less domestic-classified holders.",
            "Pure public -> fii move: dii, mf, ins untouched. Materiality 0.05 pp. Evidence per cell: file, every row hit with label, holders and the tier that decided each.",
        ],
        "cells": {},
    }
    for k, v in sorted(P.items()):
        sym, qe = k.split("|")
        cur = (hist.get(sym) or {}).get(qe)
        if cur is None or not F._cell_eq(cur, v["was"]):
            n_skip += 1
            continue
        why = (
            "{} ({}, FII = Institutions(Foreign) in every format): fii {:.2f} -> {:.2f} (+{:.2f} from Non-institutions Any-Other rows the filer's 2022 form lists under B2). ".format(
                MARK, stamp, cur[1] or 0, v["cell"][1], v["d_fii"]
            )
            + "; ".join(" ".join(str(x) for x in e) for e in v["ev"])[:900]
            + ". Evidence: _shp_fii_rowfix_audit.json"
        )
        ent = {
            "cell": list(v["cell"]),
            "was": list(cur),
            "src": "bsexbrl:{}".format(v["file"]),
            "why": why,
        }
        prior = (fix.get(sym) or {}).get(qe)
        if prior:
            if not F._cell_eq(cur, prior.get("cell")):
                n_skip += 1
                continue
            ent["superseded"] = prior
            n_sup += 1
        else:
            n_new += 1
        fix.setdefault(sym, {})[qe] = ent
        audit["cells"][k] = {x: v[x] for x in ("file", "d_fii", "ev", "newmap_file")}
    rp = os.path.join(WORK, "fii_revfix.json")
    n_rev = 0
    if os.path.exists(rp):
        R = json.load(open(rp))
        rpath = os.path.join(REPO, "scripts", "shp_revisions.json")
        revs = json.load(open(rpath, encoding="utf-8"))
        audit["revisions"] = {}
        for k, v in sorted(R.items()):
            if not v.get("cell"):
                audit["revisions"][k] = {"how": v["how"], "row": v["was"]}
                continue
            sym, qe = k.split("|")
            rc = (revs.get(sym) or {}).get(qe)
            if not rc or [round(float(x), 4) for x in rc[:5] if x is not None] != [
                round(float(x), 4) for x in v["was"][:5] if x is not None
            ]:
                audit["revisions"][k] = {
                    "how": "sidecar row moved since revfix — left as is",
                    "row": rc,
                }
                continue
            new = list(rc)
            new[1] = v["cell"][1]
            if len(new) > 7 and isinstance(new[7], str) and "§159" not in new[7]:
                new[7] = (
                    new[7]
                    + " §159 heal:"
                    + ("inherited" if v["how"].startswith("same raw") else "re-read")
                )
            revs[sym][qe] = new
            n_rev += 1
            audit["revisions"][k] = {"how": v["how"], "was": rc, "cell": new}
        json.dump(revs, open(rpath, "w", encoding="utf-8"), separators=(",", ":"), sort_keys=True)
    json.dump(led, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=ascii_only)
    json.dump(
        audit,
        open(os.path.join(REPO, "scripts", "_shp_fii_rowfix_audit.json"), "w", encoding="utf-8"),
        indent=0,
        ensure_ascii=False,
    )
    print(
        "write: %d new, %d superseding earlier entries, %d skipped (store moved), %d re-filing rows healed"
        % (n_new, n_sup, n_skip, n_rev)
    )


# §164r batch 14 (user 2026-10-04 'yes go with A'): the 2022-form rows (quarters and mid-quarter event rows). A holder the company files on
# its FDI line in another of its filings (D.FDI_REG) but lists here on a PUBLIC line joins fii - the same holder counted the same way
# in every quarter (JSWSTEEL Sep-2022: JFE Steel 15.00 under Foreign Companies, FDI line from Dec-2022; PPLPHARMA Jun-2026: CA Alchemy
# 17.93 back under Foreign Companies after ten quarters on the FDI line). Public lines only (B4: Foreign Companies, Bodies Corporate,
# NRIs, Foreign Nationals, Other Non-Institutions); the promoter lines (A2 'Any other' = OtherForeignShareholders, A2 individuals,
# A1 rows) are never read. Pure public -> fii move from the holder's own share count; dii, mf, ins untouched. Materiality 0.05 pp.
PUB22 = {
    "ForeignCompanies",
    "BodiesCorporate",
    "OtherNonInstitutions",
    "NonResidentIndians",
    "ForeignNationals",
}


def _key_of(lab):
    q = D.qe_of(lab)
    if q:
        return q
    try:
        return time.strftime("%Y-%m-%d", time.strptime((lab or "").strip(), "%d %b %Y"))
    except ValueError:
        return None


def _holder_shares(txt):
    """-> (total shares, [(axis, shares, kind, name)]) from the typed (holder) contexts of one 2022-form XBRL."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(txt)
    strip = lambda t: t.split("}", 1)[-1]
    ctx = {}
    for c in root.iter():
        if strip(c.tag) != "context":
            continue
        mems = []
        typ = None
        for m in c.iter():
            st = strip(m.tag)
            if st == "explicitMember":
                mems.append((m.text or "").split(":")[-1].strip())
            elif st == "typedMember":
                typ = (
                    (m.get("dimension") or "")
                    .split(":")[-1]
                    .replace("DetailsOfSharesHeldBy", "")
                    .replace("DetailsSharesHeldBy", "")
                    .replace("Axis", ""),
                    "".join((x.text or "") for x in m.iter() if x is not m).strip(),
                )
        ctx[c.get("id")] = (
            ("T", typ)
            if typ
            else (("W", None) if mems == ["ShareholdingPatternMember"] else (None, None))
        )
    R = {}
    tot = None
    for f in root.iter():
        t = strip(f.tag)
        k = ctx.get(f.get("contextRef"))
        if not k or not k[0]:
            continue
        if k[0] == "W":
            if t == "NumberOfShares":
                with contextlib.suppress(TypeError, ValueError):
                    tot = float(f.text)
            continue
        r = R.setdefault(k[1], {})
        if t == "NumberOfShares":
            with contextlib.suppress(TypeError, ValueError):
                r["n"] = float(f.text)
        elif t.startswith("NameOf"):
            r["name"] = (f.text or "").strip()
        elif t.startswith("WhetherACategory"):
            r["kind"] = (f.text or "").strip()
    return tot, [
        (ax, v["n"], v.get("kind") or "", v.get("name") or "")
        for (ax, val), v in R.items()
        if "n" in v
    ]


def fdi22(only=None):
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    evt = json.load(open(os.path.join(REPO, "scripts", "shp_events.json")))
    P = {}
    stats = collections.Counter()
    held = []
    for sym in sorted(D.FDI_REG):
        if only and sym not in only:
            continue
        lp = os.path.join(D.LISTS, sym + ".json")
        if not os.path.exists(lp):
            stats["no_bse_list"] += 1
            continue
        d = json.load(open(lp))
        bse_rows = d.get("Table") if isinstance(d, dict) else d
        byk = collections.defaultdict(list)
        for r in bse_rows or []:
            k = _key_of(r.get("qtr"))
            f = (r.get("XbrlFile") or "").strip()
            if k and f and k >= "2022-06-30":
                byk[k].append(((r.get("filing_date_time") or ""), f))
        for k, fl in sorted(byk.items()):
            store = hist if k[5:] in ("03-31", "06-30", "09-30", "12-31") else evt
            cur = (store.get(sym) or {}).get(k)
            if not cur:
                stats["no_store_row"] += 1
                continue
            hit = None
            for _fd, f in sorted(
                fl
            ):  # earliest first: the store row is the original filing (§142k)
                pth = D.find_file(f)
                if not pth:
                    continue
                txt = open(pth, "rb").read()
                if b"InstitutionsForeignMember" not in txt:
                    continue
                try:
                    res = F.parse_shp(txt, k)
                except Exception:
                    res = None
                if (
                    res
                    and abs((res["prom"] or 0) - (cur[0] or 0)) <= 0.06
                    and abs((res["fii"] or 0) - (cur[1] or 0)) <= 0.06
                ):
                    hit = (f, txt)
                    break
            if not hit:
                stats[
                    "no_matching_filing" if any(D.find_file(f) for fd, f in fl) else "not_cached"
                ] += 1
                if any(D.find_file(f) for fd, f in fl):
                    held.append(
                        (
                            sym,
                            k,
                            "stored row matches no 2022-form filing as filed (healed or re-filed)",
                        )
                    )
                continue
            f, txt = hit
            tot, rows = _holder_shares(txt)
            if not tot:
                stats["no_total"] += 1
                continue
            best = {}
            for ax, n, kind, nm in rows:
                if ax not in PUB22 or not nm or kind.lower().startswith("categ"):
                    continue
                h = D.fdi_line(sym, nm)
                if not h:
                    continue
                pc = 100.0 * n / tot
                if pc > best.get(h["name"], (0,))[0]:
                    best[h["name"]] = (pc, ax, nm, h["first"][0])
            mv = sum(v[0] for v in best.values())
            if mv < 0.05:
                stats["unchanged"] += 1
                continue
            new = list(cur)
            new[1] = round((cur[1] or 0) + mv, 4)
            P[f"{sym}|{k}"] = {
                "file": f,
                "was": cur,
                "cell": new,
                "d_fii": round(mv, 4),
                "ev": [
                    (
                        "FDI-holder-on-public-line",
                        v[1],
                        round(v[0], 4),
                        v[2],
                        f"FDI line first {v[3]}",
                    )
                    for v in sorted(best.values(), key=lambda x: -x[0])
                ],
            }
            stats["proposed"] += 1
    json.dump(P, open(os.path.join(WORK, "fii22_proposals.json"), "w"), indent=0)
    json.dump(held, open(os.path.join(WORK, "fii22_held.json"), "w"), indent=0)
    print("fdi22", dict(stats))
    return P


if __name__ == "__main__":
    st = sys.argv[1]
    if st == "classify":
        classify()
    elif st == "one":
        classify(only=sys.argv[2].split(","), verbose=True)
    elif st == "verify":
        verify()
    elif st == "revfix":
        revfix()
    elif st == "write":
        write()
    elif st == "fdi22":
        fdi22(only=(sys.argv[2].split(",") if len(sys.argv) > 2 else None))
