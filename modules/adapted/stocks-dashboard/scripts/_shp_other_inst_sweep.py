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
"""SW-2 (quantmac round 5) — the OTHER-INSTITUTIONS DII-INFLATION sweep  (2026-08-30).

THE DEFECT CLASS (§22i's dii-side sibling, confirmed against BSE's own filed XBRLs):
in the 2016..Sep-2022 SHP format, the institutions block carries an "Any Other (specify)"
row (`OtherInstitutionsMember`). `parse_shp`'s old-format branch routes that whole row into
**dii** (`OLD_OTHER_TO_DII = True`, calibrated on the 2022 format seam) — but for a filer
whose Any-Other row holds a FOREIGN strategic holder, that inflates dii by the block:
  JSWSTEEL Jun-2016: dii stored 17.00, filing = MF 1.50 + Banks 0.49 (dom ≈ 1.99) +
    "JFE STEEL INTERNATIONAL EUROPE B V" 15.00 under OtherInstitutions (typed member,
    NameOfTheShareholder fact — document-level proof).
  PETRONET Jun-2016: dii stored 16.48 = dom 6.48 + a single 10.00 OtherInstitutions holder
    (GDF International / Engie) — the exact 10.00 offset quantmac flagged.
No reconciliation gate ever fired: fii+dii == institutions sub-total either way (§22i).

WHAT THIS TOOL DOES (stages, each resumable):
  targets      build the candidate list: shp_history cells 2016-06-30..2022-06-30 with
               dii − mf >= 0.25 (a material Any-Other block is impossible below that),
               N500-ever symbols first.
  fetch        BSE's own copy of each filing (SHPQNewFormat -> XbrlFile), raw-cached to
               scripts/_shp_oth_cache/ (local), census rows appended to
               scripts/_shp_oth_census.jsonl (local): per-category %s + share counts +
               every NAMED holder under OtherInstitutions.
  adjudicate   offline: defect test = stored dii reproduces dom+o_other (not dom); block
               classification by the named holders (curated name-verdict map inside the
               audit ledger; UNRESOLVED names are listed for eyeball, never guessed).
               Writes scripts/_shp_other_inst_audit.json (tracked evidence ledger).
  apply        dry-run by default; --write journals heals into scripts/shp_cell_fix.json
               (dii -> domestic-only 4dp, fii += the foreign block, both from share counts;
               provenance per cell). Applied to history by fetch_shareholding.apply_cell_fix.

Never edits shp_history.json / docs/shp_engine.json directly (CLAUDE.md rule 5)."""
import argparse
import gzip
import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contextlib

import fetch_shareholding as FS  # parse_shares (whole-company share count)
import fetch_shp_bse_hist as H  # get / quarter_list / row_for / xbrl_url / codemap

CENSUS = os.path.join(HERE, "_shp_oth_census.jsonl")  # local (gitignored)
ABSENT = os.path.join(HERE, "_shp_oth_absent.jsonl")  # local (gitignored)
TARGETS = os.path.join(HERE, "_shp_oth_targets.json")  # local (gitignored)
AUDIT = os.path.join(HERE, "_shp_other_inst_audit.json")  # tracked evidence ledger
CACHE = os.path.join(HERE, "_shp_oth_cache")  # raw XBRLs (local)
CELL_FIX = os.path.join(HERE, "shp_cell_fix.json")
ERA_LO, ERA_HI = "2016-06-30", "2022-06-30"
MIN_GAP = 0.25  # dii − mf floor for a cell to possibly hold a material block
MIN_OTH = 0.25  # materiality of the Any-Other block itself
TOL2 = 0.06  # match tolerance when working from 2dp percentage sums
TOL4 = 0.011  # match tolerance when working from share-count 4dp recomputes
NAME_COVER_SLACK = 1.0  # named holders must cover o_other to within this many pp

DOM_MEMBERS = [
    "MutualFundsOrUtiMember",
    "AlternativeInvestmentFundsMember",
    "VentureCapitalFundsMember",
    "FinancialInstitutionOrBanksMember",
    "InsuranceCompaniesMember",
    "ProvidentFundsOrPensionFundsMember",
]
OTH = "OtherInstitutionsMember"
_lk = threading.Lock()


def strip(t):
    return t.split("}", 1)[-1]


def load_hist():
    return json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8"))


def n500_ever():
    ih = json.load(open(os.path.join(HERE, "indices_history.json"), encoding="utf-8"))
    out = set()
    for s in ih.get("Nifty 500", []):
        if "2015-06" <= s["effectiveDate"] <= "2022-12-31":
            out.update(H.norm(x) for x in s["symbols"])
    return out


# ---------------------------------------------------------------- targets
def cmd_targets():
    hist = load_hist()
    n5 = n500_ever()
    names = hist.get("_names", {})
    cmap, by_name = H.build_codemap(names)
    rows, unresolved = [], []
    for sym, qs in hist.items():
        if sym.startswith("_") or not isinstance(qs, dict):
            continue
        cells = []
        for qe, c in qs.items():
            if not (ERA_LO <= qe <= ERA_HI):
                continue
            try:
                dii, mf = float(c[2]), float(c[3])
            except (TypeError, ValueError, IndexError):
                continue
            if dii - mf >= MIN_GAP:
                cells.append(qe)
        if not cells:
            continue
        code = H.resolve(sym, cmap, by_name, names)
        if code is None:
            unresolved.append(sym)
            continue
        for qe in sorted(cells):
            rows.append([sym, qe, code, H.norm(sym) in n5])
    rows.sort(key=lambda r: (not r[3], r[0], r[1]))  # N500-ever first
    json.dump({"rows": rows, "unresolved_scripcode": sorted(unresolved)}, open(TARGETS, "w"), indent=0)
    print(
        "targets: %d cells (%d N500-ever) across %d symbols; %d symbols unresolved"
        % (len(rows), sum(1 for r in rows if r[3]), len({r[0] for r in rows}), len(unresolved))
    )


# ---------------------------------------------------------------- fetch + extract
def extract(txt):
    """One filed XBRL -> {cat: {member: pct}, sh: {member: shares}, total_sh, oth_names:[[name,pct,shares]]}"""
    root = ET.fromstring(txt)
    ctx = {}  # id -> ('cat', member) | ('typed', joined-typed-values)
    for c in root.iter():
        if strip(c.tag) != "context":
            continue
        mems, typed = [], []
        for m in c.iter():
            st = strip(m.tag)
            if st == "explicitMember":
                mems.append((m.text or "").split(":")[-1].strip())
            elif st == "typedMember":
                for tm in m.iter():
                    if tm.text and tm.text.strip() and strip(tm.tag) != "typedMember":
                        typed.append(tm.text.strip())
        if typed:
            ctx[c.get("id")] = ("typed", "|".join(typed))
        elif len(mems) == 1:
            ctx[c.get("id")] = ("cat", mems[0])
    cat, sh = {}, {}
    tvals = defaultdict(dict)  # typed ctx id -> {tag: value}
    for f in root.iter():
        tag = strip(f.tag)
        cid = f.get("contextRef")
        kind = ctx.get(cid)
        if kind is None:
            continue
        if kind[0] == "cat":
            if tag == "ShareholdingAsAPercentageOfTotalNumberOfShares":
                with contextlib.suppress(TypeError, ValueError):
                    cat[kind[1]] = float(str(f.text).strip())
            elif tag == "NumberOfShares":
                with contextlib.suppress(TypeError, ValueError):
                    sh[kind[1]] = int(float(str(f.text).strip()))
        # A filer often splits one typed holder across TWO contexts (name on "X", numbers on
        # "D_X") that share the same typed VALUE — key by that value, not the context id.
        elif tag in ("NameOfTheShareholder", "ShareholdingAsAPercentageOfTotalNumberOfShares", "NumberOfShares"):
            tvals[ctx[cid][1]].setdefault(tag, str(f.text or "").strip())
    oth = []
    for marker, tv in tvals.items():
        if "OtherInstitutions" not in marker:
            continue
        nm = tv.get("NameOfTheShareholder")
        if not nm:
            continue
        try:
            pct = float(tv.get("ShareholdingAsAPercentageOfTotalNumberOfShares", ""))
        except ValueError:
            pct = None
        try:
            nsh_ = int(float(tv.get("NumberOfShares", "")))
        except ValueError:
            nsh_ = None
        oth.append([nm, pct, nsh_])
    total = FS.parse_shares(root)
    return {"cat": cat, "sh": sh, "total_sh": total, "oth_names": oth}


def done_keys():
    done = set()
    for p in (CENSUS, ABSENT):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                try:
                    r = json.loads(line)
                    done.add((r["sym"], r["qe"]))
                except Exception:
                    pass
    return done


def fetch_one(sym, qe, code, hist_cell):
    rows = H.quarter_list(code)
    row = H.row_for(rows, qe)
    if row is None:
        return {"sym": sym, "qe": qe, "code": code, "absent": "no-bse-xbrl-row"}
    url = H.xbrl_url(row)
    cf = os.path.join(CACHE, (row.get("XbrlFile") or "").strip() + ".gz")
    txt = None
    if os.path.exists(cf):
        txt = gzip.open(cf, "rb").read()
    else:
        try:
            txt = H.get(url)
        except Exception as e:
            return {"sym": sym, "qe": qe, "code": code, "absent": f"xbrl-fetch-fail {e!r}"}
        os.makedirs(CACHE, exist_ok=True)
        gzip.open(cf, "wb").write(txt)
    try:
        ex = extract(txt)
    except Exception as e:
        return {"sym": sym, "qe": qe, "code": code, "absent": f"xbrl-parse-fail {e!r}"}
    return {"sym": sym, "qe": qe, "code": code, "file": (row.get("XbrlFile") or "").strip(), "stored": hist_cell, **ex}


def cmd_fetch(threads, limit):
    t = json.load(open(TARGETS))
    hist = load_hist()
    done = done_keys()
    todo = [r for r in t["rows"] if (r[0], r[1]) not in done]
    if limit:
        todo = todo[:limit]
    print("fetch: %d to go (of %d), %d threads" % (len(todo), len(t["rows"]), threads))
    n_ok = n_ab = 0
    t0 = time.time()
    cen = open(CENSUS, "a", encoding="utf-8")
    ab = open(ABSENT, "a", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {
            ex.submit(fetch_one, sym, qe, code, (hist.get(sym) or {}).get(qe)): (sym, qe) for sym, qe, code, _ in todo
        }
        for i, fu in enumerate(as_completed(futs)):
            try:
                r = fu.result()
            except Exception as e:
                r = {"sym": futs[fu][0], "qe": futs[fu][1], "absent": f"worker-crash {e!r}"}
            with _lk:
                if "absent" in r:
                    ab.write(json.dumps(r) + "\n")
                    n_ab += 1
                else:
                    cen.write(json.dumps(r) + "\n")
                    n_ok += 1
                if (i + 1) % 200 == 0:
                    cen.flush()
                    ab.flush()
                    rate = (i + 1) / max(1e-9, time.time() - t0)
                    print("  %d/%d (%.1f/s, ok %d, absent %d)" % (i + 1, len(todo), rate, n_ok, n_ab), flush=True)
    cen.close()
    ab.close()
    print("fetch done: ok %d, absent %d" % (n_ok, n_ab))


# ---------------------------------------------------------------- adjudicate
FOREIGN_PAT = re.compile(
    r"\b(B\.?\s?V|N\.?V|S\.?A\.?R\.?L|GMBH|PTE|PLC|LLC|L\.?L\.?C|INC|CO\.?\s?LTD\s*\(?JAPAN|"
    r"MAURITIUS|SINGAPORE|NETHERLANDS|LUXEMBOURG|CYPRUS|DELAWARE|AMSTERDAM|EUROPE|JAPAN|KOREA|"
    r"FRANCE|GERMANY|SWEDEN|FINLAND|DENMARK|SWITZERLAND|UK|USA|U\.S\.A|HONG\s?KONG|CAYMAN|DUBAI|"
    r"ABU DHABI|QATAR|KUWAIT|SAUDI|OMAN|BAHRAIN|MALAYSIA|INDONESIA|THAILAND|TAIWAN|CHINA|"
    r"AUSTRALIA|CANADA|IRELAND|BELGIUM|ITALY|SPAIN|NORWAY|AKTIEBOLAG|KABUSHIKI|OVERSEAS?)\b",
    re.IGNORECASE,
)
DOMESTIC_PAT = re.compile(
    r"\b(LIFE INSURANCE CORPORATION|GENERAL INSURANCE CORPORATION|NEW INDIA ASSURANCE|"
    r"NATIONAL INSURANCE|ORIENTAL INSURANCE|UNITED INDIA INSURANCE|ARMY GROUP INSURANCE|"
    r"NAVAL GROUP INSURANCE|AIR FORCE GROUP INSURANCE|POSTAL LIFE|EPFO|EMPLOYEES PROVIDENT|"
    r"NPS TRUST|PENSION FUND\b.*INDIA|UTI\b|IDBI|IFCI|NABARD|SIDBI|EXIM BANK|LIC OF INDIA|"
    r"STRESSED ASSETS?|SASF|IIBI|ICICI|HDFC|SBI\b|STATE BANK|PUNJAB NATIONAL|BANK OF (INDIA|"
    r"BARODA|MAHARASHTRA)|CANARA BANK|UNION BANK|ADMINISTRATOR OF THE SPECIFIED UNDERTAKING)\b",
    re.IGNORECASE,
)


def classify_name(nm, curated):
    if nm in curated:
        return curated[nm]
    if DOMESTIC_PAT.search(nm):
        return "domestic"
    if FOREIGN_PAT.search(nm):
        return "foreign"
    return "unknown"


def load_audit():
    if os.path.exists(AUDIT):
        return json.load(open(AUDIT, encoding="utf-8"))
    return {
        "_doc": [
            (
                "SW-2 quantmac r5: Any-Other-institutions block classification + per-cell "
                "verdicts. name_verdicts holds the curated per-holder-name class "
                "(foreign/domestic) — hand-reviewed; the regexes only PROPOSE."
            )
        ],
        "name_verdicts": {},
        "cells": {},
    }


def cmd_adjudicate(write_audit=True):
    audit = load_audit()
    curated = audit.get("name_verdicts", {})
    hist = load_hist()
    stats = defaultdict(int)
    names_seen = defaultdict(float)  # name -> max pct (for eyeball ordering)
    cells = {}
    for line in open(CENSUS, encoding="utf-8"):
        r = json.loads(line)
        sym, qe = r["sym"], r["qe"]
        cur = (hist.get(sym) or {}).get(qe)
        if cur is None:
            stats["gone-from-history"] += 1
            continue
        cat, sh, total = r["cat"], r["sh"], r.get("total_sh")
        if "InstitutionsDomesticMember" in cat:
            stats["new-format-clean"] += 1
            continue
        oth2 = cat.get(OTH)
        if oth2 is None and OTH not in sh:
            stats["no-other-block"] += 1
            continue
        # block + domestic sums, share-count precision when complete
        dom2 = sum(cat.get(m) or 0.0 for m in DOM_MEMBERS)
        have_sh = total and (OTH in sh) and all((m in sh) or ((cat.get(m) or 0) == 0) for m in DOM_MEMBERS)
        if have_sh:
            oth = round(sh[OTH] / total * 100, 4)
            dom = round(sum(sh.get(m, 0) for m in DOM_MEMBERS) / total * 100, 4)
            tol = TOL4
        else:
            oth = oth2 or 0.0
            dom = dom2
            tol = TOL2
        if oth < MIN_OTH:
            stats["other-below-materiality"] += 1
            continue
        try:
            dii, fii = float(cur[2]), float(cur[1])
        except (TypeError, ValueError):
            stats["bad-stored-cell"] += 1
            continue
        if abs(dii - dom) <= max(tol, TOL2):
            stats["stored-already-domestic"] += 1
            continue
        if abs(dii - (dom + oth)) > max(tol, TOL2):
            stats["stored-matches-neither"] += 1
            cells[f"{sym}|{qe}"] = {"verdict": "mismatch-other-source", "stored_dii": dii, "dom": dom, "oth": oth}
            continue
        # stored dii == dom + block. Classify the block by its named holders.
        named = [(nm, pct or 0.0) for nm, pct, _ in r.get("oth_names", [])]
        cover = sum(p for _, p in named)
        classes = {classify_name(nm, curated) for nm, _ in named}
        for nm, p in named:
            names_seen[nm] = max(names_seen[nm], p)
        key = f"{sym}|{qe}"
        base = {"stored_dii": dii, "stored_fii": fii, "dom": dom, "oth": oth, "names": named, "file": r.get("file")}
        if not named or cover < oth - NAME_COVER_SLACK:
            stats["names-insufficient-HOLD"] += 1
            cells[key] = dict(base, verdict="names-insufficient")
        elif classes == {"foreign"}:
            stats["FOREIGN-heal"] += 1
            cells[key] = dict(base, verdict="foreign-confirmed")
        elif classes == {"domestic"}:
            stats["domestic-kept"] += 1
            cells[key] = dict(base, verdict="domestic-kept")
        elif "unknown" in classes:
            stats["name-unknown-HOLD"] += 1
            cells[key] = dict(base, verdict="name-unknown")
        else:
            stats["mixed-HOLD"] += 1
            cells[key] = dict(base, verdict="mixed-foreign-domestic")
    # SECOND PASS — same-symbol block continuity (the §22i regime idea in miniature): a HELD
    # cell whose Any-Other block is the SAME SIZE (±0.5pp) as a name-classified block in an
    # adjacent quarter (±2) of the same symbol is the same holder persisting; adopt that class.
    # Only name-verdict cells seed it (never another continuity cell — no transitive chains).
    by_sym = defaultdict(list)
    for key, v in cells.items():
        sym, qe = key.split("|")
        by_sym[sym].append((qe, key, v))

    def QSEQ(qe):
        return int(qe[:4]) * 4 + {"03": 0, "06": 1, "09": 2, "12": 3}[qe[5:7]]

    for sym, lst in by_sym.items():
        seeds = [
            (QSEQ(qe), v["oth"], v["verdict"])
            for qe, k, v in lst
            if v["verdict"] in ("foreign-confirmed", "domestic-kept")
        ]
        if not seeds:
            continue
        for qe, key, v in lst:
            if v["verdict"] not in ("names-insufficient", "name-unknown"):
                continue
            near = {vd for qs, oth, vd in seeds if abs(qs - QSEQ(qe)) <= 2 and abs(oth - v["oth"]) <= 0.5}
            if near == {"foreign-confirmed"}:
                stats[("names-insufficient-HOLD" if v["verdict"] == "names-insufficient" else "name-unknown-HOLD")] -= 1
                stats["FOREIGN-heal-continuity"] += 1
                v["verdict"] = "foreign-confirmed"
                v["basis"] = "same-symbol block continuity (adjacent quarter named-foreign, same size)"
            elif near == {"domestic-kept"}:
                stats[("names-insufficient-HOLD" if v["verdict"] == "names-insufficient" else "name-unknown-HOLD")] -= 1
                stats["domestic-kept-continuity"] += 1
                v["verdict"] = "domestic-kept"
                v["basis"] = "same-symbol block continuity"
    print("== adjudication ==")
    for k in sorted(stats):
        print("  %-28s %d" % (k, stats[k]))
    unknown = sorted(
        ((nm, p) for nm, p in names_seen.items() if classify_name(nm, curated) == "unknown"), key=lambda x: -x[1]
    )
    print("== UNRESOLVED names (max pct) — curate into name_verdicts ==")
    for nm, p in unknown[:80]:
        print(f"  {p:6.2f}  {nm}")
    if len(unknown) > 80:
        print("  ... and %d more" % (len(unknown) - 80))
    if write_audit:
        audit["cells"] = cells
        audit["_stats"] = dict(stats)
        json.dump(audit, open(AUDIT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("wrote %s (%d cells)" % (os.path.basename(AUDIT), len(cells)))


# ---------------------------------------------------------------- apply
def cmd_apply(write=False):
    audit = load_audit()
    hist = load_hist()
    led = json.load(open(CELL_FIX, encoding="utf-8"))
    fix = led.setdefault("fix", {})
    n_new = n_skip = 0
    stamp = time.strftime("%Y-%m-%d")
    for key, v in sorted(audit.get("cells", {}).items()):
        if v.get("verdict") != "foreign-confirmed":
            continue
        sym, qe = key.split("|")
        cur = (hist.get(sym) or {}).get(qe)
        if cur is None:
            continue
        new = list(cur)
        new[2] = round(v["dom"], 4)
        new[1] = round(float(cur[1]) + v["oth"], 4)
        if qe in (fix.get(sym) or {}):
            n_skip += 1
            continue
        fix.setdefault(sym, {})[qe] = {
            "cell": new,
            "was": list(cur),
            "src": "bsexbrl:%s" % (v.get("file") or ""),
            "why": (
                "SW-2 other-institutions sweep {}: filing's Any-Other institutions block "
                "({:.2f}pp, holders: {}) is FOREIGN — belongs in fii, not dii. dii -> "
                "domestic-only {:.4f} (MF+AIF+VCF+Banks+Ins+PF from the filing's own share "
                "counts), fii += the block. Evidence: _shp_other_inst_audit.json"
            ).format(stamp, v["oth"], "; ".join(nm for nm, _ in v.get("names", [])), v["dom"]),
        }
        n_new += 1
    print(
        "apply: %d new heals, %d already ledgered%s" % (n_new, n_skip, "" if write else " (DRY RUN — nothing written)")
    )
    if write:
        json.dump(led, open(CELL_FIX, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"wrote {os.path.basename(CELL_FIX)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["targets", "fetch", "adjudicate", "apply"])
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    if a.stage == "targets":
        cmd_targets()
    elif a.stage == "fetch":
        cmd_fetch(a.threads, a.limit)
    elif a.stage == "adjudicate":
        cmd_adjudicate()
    elif a.stage == "apply":
        cmd_apply(a.write)
