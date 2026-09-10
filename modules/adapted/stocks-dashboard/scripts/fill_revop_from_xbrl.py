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
"""Targeted rev/op/ebit re-extraction from NSE result XBRLs — the FILL-2020 method, made a tool.

Campaign: PLAN_XBRL_FILER_FORMAT.md Phase D + the same-filing finding (94% of revCon gaps have a
dated con PAT for the very quarter — the filing was already read for PAT; sf_revop never got the
revenue columns).

METHOD (mirrors the 7e2711cc ledger fields exactly):
  For each (sym, qe, basis) with a null sf_revop slot: locate the filing's XBRL via the NSE
  list-sweep caches (scripts/_nse_list_cache/), download to the SHARED main-checkout
  scripts/_xbrl_cache (validated: XML magic, >2KB), parse with build_revop.metrics_for — the same
  branches that built the file (bank rev = InterestEarned, insurer premium formulas, NBFC ORFO
  netting, industrial PBET formula) — and ANCHOR before writing: the XBRL's PAT for that basis
  must match the stored sf_fundamentals PAT within 2% (owners first for con, total as fallback,
  same as the con PAT convention). No anchor -> no write, logged to the refusals file.

WRITES (fill-only, guarded, idempotent):
  docs/sf_revop.json + scripts/revop_fundamentals.json slots [rev,op,ebit] per basis;
  strip_lender_ebit applied (the 2026-08-16 alignment must not regress);
  provenance per cell into scripts/nse_xbrl_rev_fills.json (anchor, anchor_tag, filed, src).

USAGE
  python3 scripts/fill_revop_from_xbrl.py --worklist <path> [--limit N] [--dry]
"""
import argparse
import gzip
import io
import json
import os
import re
import socket
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
MAIN_CACHE = "/Users/dhruvan/stocks-dashboard/scripts/_xbrl_cache"  # shared, untracked
# Where NEW downloads go: this tree's own scripts/_xbrl_cache (== MAIN_CACHE when run from the main
# checkout, so nothing changes there; a worktree keeps its downloads to itself and never writes into
# the shared cache -- WP1 revCon 2026-09-02). Lookups try MAIN_CACHE first, then here.
LOCAL_CACHE = os.path.join(HERE, "_xbrl_cache")
LIST_CACHE = os.path.join(HERE, "_nse_list_cache")
socket.setdefaulttimeout(45)
sys.path.insert(0, HERE)
import build_revop as B  # metrics_for + strip_lender_ebit + the format branches

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
SLOT = {"rev": (0, 1), "op": (2, 3), "ebit": (7, 8)}  # (std, con) indices in the 9-slot row


def list_rows(sym):
    p = os.path.join(LIST_CACHE, "{}.json".format(re.sub(r"[^A-Z0-9]", "_", sym.upper())))
    if not os.path.exists(p):
        return []
    return json.load(open(p)).get("rows") or []


def iso_qe(s):
    M = {
        m: i
        for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
    }
    mm = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    return "%04d%02d%02d" % (int(mm.group(3)), M[mm.group(2).title()], int(mm.group(1))) if mm else None


def urls_for(sym, qe):
    """[(basis, url, filed)] for this quarter, exact-basis rows first."""
    out = []
    for r in list_rows(sym):
        if iso_qe(r.get("toDate")) != qe:
            continue
        u = (r.get("xbrl") or "").strip()
        # NSE's xbrl placeholder has TWO spellings and the second masquerades as a transient
        # failure: the bare '-' AND a full URL whose BASENAME is '-' (the placeholder pasted onto
        # the archive prefix). Checking only `u == '-'` lets the second through, the fetch 404s,
        # the one-shot retry refetches the same dead URL, and the cell lands in fetch_fail where
        # it survives every "retry the transients" pass intact (measured 2026-08-16: 76/76
        # identical across two runs). Gate on the basename and count it separately.
        if not u or u == "-" or u.rsplit("/", 1)[-1] in ("-", ""):
            continue
        basis = "con" if str(r.get("consolidated", "")).strip().lower() == "consolidated" else "std"
        out.append((basis, u, r.get("filingDate") or r.get("broadCastDate")))
    return out


def cached_path(fn):
    """The nightly fetcher stores a filing as <basename with '.xml' -> '_xml'> (measured 2026-09-02:
    104,331 of the shared cache's files end in `_xml`, 204 in `.xml`), so a lookup by the URL basename
    alone missed the whole cache and re-downloaded every filing. Try both spellings, both dirs."""
    for d in (MAIN_CACHE, LOCAL_CACHE):
        for name in (fn, re.sub(r"\.xml$", "_xml", fn)):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return None


def fetch(url):
    fn = url.rsplit("/", 1)[-1]
    p = cached_path(fn)
    if p is None:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read()
        if len(raw) < 2048 or b"<?xml" not in raw[:300]:
            raise ValueError("not an XBRL (%d bytes)" % len(raw))
        os.makedirs(LOCAL_CACHE, exist_ok=True)
        p = os.path.join(LOCAL_CACHE, fn)
        open(p, "wb").write(raw)
        time.sleep(0.6)
    return open(p, encoding="utf-8", errors="replace").read()


NAT_RE = re.compile(r"NatureOfReportStandaloneConsolidated[^>]*>([^<]+)<")


NAT_ALL = re.compile(r'NatureOfReportStandaloneConsolidated contextRef="([^"]+)"[^>]*>([^<]+)<')


def parse(xml, basis_hint=None):
    """{basis: {'rev','op','ebit','pat','owners'}} for the CURRENT quarter of this filing.

    ⚠️ FourD IS NOT AUTOMATICALLY "THE OTHER BASIS". That assumption was this tool's own bug (found
    2026-08-16 by its anchor gate, which refused 136 writes): in a SINGLE-basis filing FourD is the
    SAME basis's YEAR-TO-DATE period — ABB's Jun-2020 standalone has OneD 90 days and FourD 181,
    so reading FourD as 'con' offered 80.92 against a stored quarter of 16.28. Mirrors
    build_revop.xbrl_revop exactly: take FourD only when it DECLARES a different basis AND its
    period is a quarter (is_quarter_ctx). Anything cumulative is skipped, not stored."""
    nat = {m.group(1): m.group(2).strip().lower() for m in NAT_ALL.finditer(xml)}
    hint = (basis_hint or "").lower()
    out = {}
    one_nat = nat.get("OneD", "") or hint
    if B.is_quarter_ctx(xml, "OneD"):
        v = B.metrics_for(xml, "OneD")
        if any(x is not None for x in v):
            out["con" if "consol" in one_nat else "std"] = dict(
                zip(("rev", "op", "ebit", "pat", "owners"), v, strict=False)
            )
            out["con" if "consol" in one_nat else "std"]["_end"] = period_end(xml, "OneD")
            out["con" if "consol" in one_nat else "std"]["_insurer"] = (
                "NetPremiumIncome" in xml or "PremiumEarned" in xml
            )
    four_nat = nat.get("FourD", "")
    if four_nat and four_nat != one_nat and B.is_quarter_ctx(xml, "FourD"):
        v = B.metrics_for(xml, "FourD")
        b = "con" if "consol" in four_nat else "std"
        if any(x is not None for x in v) and b not in out:
            out[b] = dict(zip(("rev", "op", "ebit", "pat", "owners"), v, strict=False))
            out[b]["_end"] = period_end(xml, "FourD")
            out[b]["_insurer"] = "NetPremiumIncome" in xml or "PremiumEarned" in xml
    return out


def period_end(xml, cid):
    """'YYYYMMDD' end of context cid's stated period, else None (old BANKING/NONINDAS files state none)."""
    per = B.ctx_period(xml, cid)
    return per[1].replace("-", "") if per else None


def filed_days_after(filed, qe):
    """Days from quarter-end to the list row's filing date ('25-Oct-2019 19:46'); None if unparseable."""
    import datetime

    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", (filed or "").strip())
    if not m:
        return None
    M = {
        x: i
        for i, x in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
    }
    try:
        f = datetime.date(int(m.group(3)), M[m.group(2).title()], int(m.group(1)))
        q = datetime.date(int(qe[:4]), int(qe[4:6]), int(qe[6:8]))
    except Exception:
        return None
    return (f - q).days


def period_ok(m, filed, qe):
    """★ PERIOD GATE (2026-09-02, WP1 revCon). The NSE index double-indexes: its row for toDate
    30-Sep-2018 can carry the Sep-2019 filing's XBRL (RATNAMANI/GHCL `_WEB_2.xml`, §45), and the PAT
    anchor cannot catch it when the stored con PAT for that quarter was itself read from the same
    mis-indexed file (RATNAMANI con PAT 76.46 stored for BOTH Sep-2018 and Sep-2019). Two wrong
    revenue cells were written and caught by the duplicate-to-the-paisa screen before any push.
    Rule: the context's stated period must END on the target quarter; when the file states no
    period (old BANKING/NONINDAS instances) the row's filing date must sit 0..150 days after the
    quarter-end (runbook §52's post-quarter stretch). -> (ok, reason)."""
    end = m.get("_end")
    if end is not None:
        return (
            end == qe
        ), None if end == qe else f"period-mismatch: XBRL context ends {end}, target {qe} (index double-indexing, §45)"
    d = filed_days_after(filed, qe)
    if d is None:
        return False, "no-period-in-xbrl and no parseable filing date"
    if 0 <= d <= 150:
        return True, None
    return False, "no-period-in-xbrl and filed %d days after quarter-end (not this quarter)" % d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worklist", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    WL = json.load(open(a.worklist))
    REVOP = json.load(open(os.path.join(DOCS, "sf_revop.json")))
    RF = json.load(open(os.path.join(HERE, "revop_fundamentals.json")))
    FUND = json.load(open(os.path.join(DOCS, "sf_fundamentals.json")))
    LED = json.load(open(os.path.join(HERE, "nse_xbrl_rev_fills.json")))
    refusals = []
    stats = {
        "filled_cells": 0,
        "pairs_done": 0,
        "anchor_fail": 0,
        "no_url": 0,
        "fetch_fail": 0,
        "already": 0,
        "basis_absent": 0,
        "field_none_by_format": 0,
    }

    def stored_pat(sym, qe, basis):
        for q in FUND.get(sym, []):
            if q[0] == int(qe):
                return q[3] if basis == "con" else q[1]
        return None

    def anchor_ok(sym, qe, basis, m):
        sp = stored_pat(sym, qe, basis)
        if sp is None:
            return None, "no-stored-pat"
        for tag in ("owners", "pat"):
            v = m.get(tag)
            if v is not None and abs(v - sp) <= max(0.02, abs(sp) * 0.02):
                return (sp, tag), None
        return None, "anchor-mismatch stored={} got pat={} owners={}".format(sp, m.get("pat"), m.get("owners"))

    done = 0
    for item in WL:
        if a.limit and done >= a.limit:
            break
        sym, qe, fields = item["sym"], item["qe"], item["fields"]
        # what does this pair still need, per basis?
        row = REVOP.setdefault(sym, {}).get(qe)
        need = set()
        for f in fields:
            if f == "revCon":
                need.add(("rev", "con"))
            elif f == "revStd":
                need.add(("rev", "std"))
            elif f in ("op", "ebit"):
                si, ci = SLOT[f]
                if row is None or (len(row) > si and row[si] is None):
                    need.add((f, "std"))
                if row is None or (len(row) > ci and row[ci] is None):
                    need.add((f, "con"))
        if row is not None:
            need = {(f, b) for (f, b) in need if len(row) <= SLOT[f][b == "con"] or row[SLOT[f][b == "con"]] is None}
        if not need:
            stats["already"] += 1
            continue
        done += 1
        cand = urls_for(sym, qe)
        if not cand:
            stats["no_url"] += 1
            refusals.append({"sym": sym, "qe": qe, "why": "not-found-via:nse-list-cache"})
            continue
        got = {}
        filed_at = {}
        for basis, url, filed in cand:
            pr = None
            for attempt in (1, 2):
                try:
                    pr = parse(fetch(url), basis_hint=("consolidated" if basis == "con" else "standalone"))
                    break
                except Exception as e:
                    if attempt == 1:
                        time.sleep(3.0)  # transient rate-limit / connection reset
                        continue
                    stats["fetch_fail"] += 1
                    refusals.append(
                        {"sym": sym, "qe": qe, "why": f"fetch/parse: {type(e).__name__} {str(e)[:60]}", "url": url}
                    )
            if pr is None:
                continue
            for b, m in pr.items():
                if b not in got or (m.get("rev") is not None and got[b].get("rev") is None):
                    got[b] = m
                    filed_at[b] = (filed, url)
        wrote_any = False
        for f, b in sorted(need):
            m = got.get(b)
            if not m:
                stats["basis_absent"] += 1
                refusals.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "basis": b,
                        "field": f,
                        "why": f"no parseable {b} context in any candidate file",
                    }
                )
                continue
            if m.get(f) is None:
                # metrics_for returned None for this field — for ebit on bank/NBFC/insurer-FORM
                # files that is BY DESIGN (build_revop refuses the formula there). Count it as its
                # own class; silence here is how a whole category vanishes from a report.
                stats["field_none_by_format"] += 1
                refusals.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "basis": b,
                        "field": f,
                        "why": f"parsed OK but {f} is None — filing format does not yield it via metrics_for",
                    }
                )
                continue
            if f == "rev" and m.get(f) is not None and round(m[f], 2) <= 0 and not m.get("_insurer"):
                # <= 0, on the ROUNDED value: HBSL Mar-2022 carried a sub-paisa revenue that `== 0` let
                # through as 0.0, and DHRUV Dec-2025 / DHARAN Sep-2023 landed NEGATIVE revenue from an
                # industrial XBRL. Only insurer formats may legitimately be negative (runbook §55, MTM).
                # §58c: a printed 0.00 is a BLANK row, not a result. KSL Mar-2024 tagged RevenueFromOperations
                # 0 (neighbours ~488), MANGALAM Sep-2023 0 (~90) -- 6 such cells landed on 2026-09-02 and were
                # retracted before the push. Refuse; never publish a zero revenue from an XBRL tag.
                stats["zero_rev"] = stats.get("zero_rev", 0) + 1
                refusals.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "basis": b,
                        "field": f,
                        "why": "rev==0 in the XBRL (blank row, §58c)",
                        "url": filed_at.get(b, ("?", "?"))[1],
                    }
                )
                continue
            pok, perr = period_ok(m, filed_at.get(b, ("?", "?"))[0], qe)
            if not pok:
                stats["period_fail"] = stats.get("period_fail", 0) + 1
                refusals.append(
                    {"sym": sym, "qe": qe, "basis": b, "field": f, "why": perr, "url": filed_at.get(b, ("?", "?"))[1]}
                )
                continue
            anc, err = anchor_ok(sym, qe, b, m)
            if anc is None:
                stats["anchor_fail"] += 1
                refusals.append({"sym": sym, "qe": qe, "basis": b, "field": f, "why": err})
                continue
            si = SLOT[f][b == "con"]
            for store in (REVOP, RF):
                d = store.setdefault(sym, {})
                rr = d.get(qe) or [None] * 6 + [0, None, None]
                if len(rr) < 9:
                    rr += [None] * (9 - len(rr))
                if rr[si] is None:
                    rr[si] = round(m[f], 2)
                    wrote_any = True
                B.strip_lender_ebit(sym, rr)
                d[qe] = rr
            if a.dry:
                stats["filled_cells"] += 1
                continue
            key = f"{sym}|{qe}|{b}"
            e = LED.setdefault(key, {})
            e.update(
                {
                    "basis": b,
                    f: round(m[f], 2),
                    "anchor": anc[0],
                    "anchor_tag": anc[1],
                    "filed": filed_at.get(b, ("?", "?"))[0],
                    "src": filed_at.get(b, ("?", "?"))[1],
                    "fill_pass": "2026-08-16 phaseD",
                }
            )
            stats["filled_cells"] += 1
        if wrote_any:
            stats["pairs_done"] += 1
        if done % 40 == 0:
            print("  %d pairs processed · %s" % (done, stats), flush=True)
            if not a.dry:
                json.dump(REVOP, open(os.path.join(DOCS, "sf_revop.json"), "w"), separators=(",", ":"))
                json.dump(RF, open(os.path.join(HERE, "revop_fundamentals.json"), "w"), separators=(",", ":"))
                json.dump(LED, open(os.path.join(HERE, "nse_xbrl_rev_fills.json"), "w"), separators=(",", ":"))

    if not a.dry:
        json.dump(REVOP, open(os.path.join(DOCS, "sf_revop.json"), "w"), separators=(",", ":"))
        json.dump(RF, open(os.path.join(HERE, "revop_fundamentals.json"), "w"), separators=(",", ":"))
        json.dump(LED, open(os.path.join(HERE, "nse_xbrl_rev_fills.json"), "w"), separators=(",", ":"))
    json.dump(refusals, open(os.path.join(HERE, "_revop_fill_refusals.json"), "w"), indent=0)
    print("FINAL:", stats)
    print("refusals:", len(refusals), "->scripts/_revop_fill_refusals.json")


if __name__ == "__main__":
    main()
