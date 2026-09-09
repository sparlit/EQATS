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
"""Net the PDF-only Excise Duty line off refiner revenue in sf_revop (Trendlyne parity; runbook §11).

Post-GST, only petroleum (and liquor) companies still route excise through the P&L. Their XBRL
carries NO excise tag — MRPL Q1FY27 verified: the expense lines sum exactly to Total expenses with
excise inside OtherExpenses — while the results PDF prints an explicit "Excise Duty" row. Trendlyne
nets it: MRPL 41,608.96 − 3,354.77 = 38,254.19, matched to the paisa (2026-07-17). Our op formula is
unaffected (excise is already inside PBET), so ONLY the rev slots (0=std, 1=con) change.

ONLY VERIFIED SYMBOLS go in REFINERS — the ORFO lesson: never generalize a presentation rule beyond
companies checked against Trendlyne's per-stock "Operating Revenue Qtr" (liquor cos pay state excise
too, but TL's treatment of them is UNVERIFIED — do not add without checking).

Anchored parsing (never guesses):
  For each REFINERS × quarter in sf_revop with QE >= MIN_NET_QE and no ledger entry: pull the results
  PDF (integrated-filing pdf_attach when real, else the corporate-announcements attachment), find a
  page holding BOTH a "Revenue from operations" row and an "Excise" row, and map columns by matching
  revenue cells against STORED gross values (±0.5%, unit scales tried) — the excise cell in the same
  column position belongs to that same quarter. One PDF therefore usually nets cur + preceding + yago.
  Identity guard: the company name must appear in the page text.

Ledger scripts/excise_duty.json = {SYM: {QE: {"gross": cr, "excise": cr, "src": url}}}. The apply step
subtracts ONLY where the stored slot still equals the ledger gross (±0.02) — idempotent, safe to re-run
after a full build_revop rebuild (which resurrects gross values; re-run this script to re-net).

Netting HORIZON: MIN_NET_QE = 20220630 — one year before the quarterly-results page window, so every
YoY/QoQ pair it displays is net/net. Older quarters stay gross/gross (self-consistent growth). The one
straddle pair per symbol at the horizon (net cur vs gross base) is immaterial at index level (<0.02pp).

Run:  python -X utf8 fetch_excise.py [--dry-run] [--only MRPL,IOC] [--apply-only]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(HERE, "excise_duty.json")
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCRIPTS = os.path.join(HERE, "revop_fundamentals.json")

# symbol -> identity token that must appear in the PDF page text (guard against wrong attachments)
REFINERS = {
    "MRPL": "Mangalore Refinery",  # VERIFIED vs TL 2026-07-17 (38,254.19 paisa-exact)
    # "IOC": "Indian Oil",                 # add ONLY after verifying TL nets excise for it
    # "BPCL": "Bharat Petroleum",
    # "HPCL": "Hindustan Petroleum",
    # "CPCL": "Chennai Petroleum",
}
MIN_NET_QE = 20220630
SCALES = (1.0, 0.01, 10.0, 0.1)  # PDF-unit -> crore candidates (cr, lakh, 10-cr?, million*10)

RE_NUM = re.compile(r"\(?-?[\d,]+\.\d{1,2}\)?")


def _nums(cells):
    out = []
    for t in cells:
        t2 = t.replace(",", "").rstrip(".")
        neg = t2.startswith("(") and t2.endswith(")")
        t2 = t2.strip("()")
        try:
            v = float(t2)
            out.append(-v if neg else v)
        except ValueError:
            pass
    return out


def row_numbers(page, want, reject=None):
    """Numeric cells of the first row whose label matches `want` (label = words left of the first
    number). Returns (values, label). OCR junk in labels is tolerated by regex matching."""
    rows = {}
    for w in page.get_text("words"):
        rows.setdefault(round(w[1] / 3.0), []).append(w)
    for k in sorted(rows):
        ws = sorted(rows[k], key=lambda w: w[0])
        toks = [w[4] for w in ws]
        first_num = next((i for i, t in enumerate(toks) if RE_NUM.fullmatch(t.replace("|", ""))), len(toks))
        label = " ".join(toks[:first_num])
        if re.search(want, label, re.IGNORECASE) and not (reject and re.search(reject, label, re.IGNORECASE)):
            vals = _nums([t.replace("|", "") for t in toks[first_num:]])
            if vals:
                return vals, label
    return None, None


def stored_gross(revop, sym, qe):
    r = (revop.get(sym) or {}).get(str(qe))
    if not r:
        return None
    r = (list(r) + [None] * 9)[:9]
    return r[1] if r[1] is not None else r[0]  # con-pref, matches how the PDF prints one figure


def match_columns(rev_cells, excise_cells, revop, sym, scale, fetch_qe):
    """Pair revenue cells to quarters by matching stored gross; same index in the excise row.

    Candidates are limited to quarters a results PDF can actually print — cur/preceding/year-ago,
    i.e. [fetch_qe − 1y, fetch_qe]. Without this, a company whose revenue revisits an old level
    anchors ambiguously and the strict unique-hit rule skips it (MRPL was ~28.4k cr in Mar-2026,
    Dec-2023 AND Sep-2022 — all within tolerance of each other; exactly those three kept missing)."""
    if len(rev_cells) != len(excise_cells):
        return {}
    qs = [q for q in sorted((revop.get(sym) or {}), reverse=True) if fetch_qe - 10000 <= int(q) <= fetch_qe]
    out = {}
    for i, rv in enumerate(rev_cells):
        cr = rv * scale
        hit = [q for q in qs if (g := stored_gross(revop, sym, int(q))) and abs(g - cr) <= max(0.005 * abs(g), 0.02)]
        if len(hit) == 1 and int(hit[0]) not in out:
            out[int(hit[0])] = (round(cr, 2), round(excise_cells[i] * scale, 2))
    return out


def main():
    dry = "--dry-run" in sys.argv
    apply_only = "--apply-only" in sys.argv
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only"):
            only = set((a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1]).split(","))
    led = json.load(open(LEDGER, encoding="utf-8")) if os.path.exists(LEDGER) else {}

    revop = json.load(open(REVOP_DOCS, encoding="utf-8"))

    if not apply_only:
        import backfill_ipo_bases as K
        import build_fundamentals as B
        import fitz

        jar = B.nse_jar()
        for sym, ident in REFINERS.items():
            if only and sym not in only:
                continue
            need = [
                int(q) for q in (revop.get(sym) or {}) if int(q) >= MIN_NET_QE and str(q) not in (led.get(sym) or {})
            ]
            if not need:
                continue
            print("%s: %d quarters need excise" % (sym, len(need)))
            for qe in sorted(need, reverse=True):
                if str(qe) in (led.get(sym) or {}):
                    continue  # an earlier PDF's comparative column already filled it
                try:
                    pdfs = K.announcement_pdfs(sym, qe, jar)
                except Exception as e:
                    print(f"   {qe} ann-index FAIL {e}")
                    continue
                if not pdfs:
                    print(f"   {qe} no result PDF found")
                    continue
                try:
                    doc = fitz.open(stream=K.fetch_pdf(pdfs[0][0]), filetype="pdf")
                except Exception as e:
                    print(f"   {qe} pdf fetch FAIL {e}")
                    continue
                got = {}
                for p in range(doc.page_count):
                    tl = doc[p].get_text().lower()  # statements often print headers/name in UPPERCASE
                    if ident.lower() not in tl or "excise" not in tl or "evenue from" not in tl:
                        continue
                    rev_c, _ = row_numbers(doc[p], r"Revenue from Operations", reject=r"Total|Other")
                    exc_c, _ = row_numbers(doc[p], r"Excise")
                    if not rev_c or not exc_c:
                        continue
                    for sc in SCALES:
                        m = match_columns(rev_c, exc_c, revop, sym, sc, qe)
                        if m:
                            got.update(m)
                            break
                if got:
                    for q2, (g, e) in got.items():
                        led.setdefault(sym, {})[str(q2)] = {"gross": g, "excise": e, "src": pdfs[0][0]}
                    print("   {} -> netted {} from {}".format(qe, sorted(got), pdfs[0][0].rsplit("/", 1)[-1][:60]))
                else:
                    print(f"   {qe} ANCHOR MISS (scanned or unrecognized layout) — left gross")

    # ---- apply (idempotent, both copies) ----
    changed = 0
    for path in (REVOP_DOCS, REVOP_SCRIPTS):
        R = json.load(open(path, encoding="utf-8"))
        ch = 0
        for sym, qs in led.items():
            for q, rec in qs.items():
                row = (R.get(sym) or {}).get(q)
                if not row:
                    continue
                row = (list(row) + [None] * 9)[:9]
                net_exp = rec["gross"] - rec["excise"]
                for slot in (0, 1):
                    v = row[slot]
                    if v is None:
                        continue
                    if abs(v - net_exp) <= max(0.005 * abs(net_exp), 0.02):
                        continue  # already netted (idempotency)
                    # PDF comparative and stored XBRL can differ by paise-level revisions
                    # (MRPL Jun-25: 20,988.53 vs 20,988.03) — anchor tolerance, subtract from STORED.
                    if abs(v - rec["gross"]) <= max(0.005 * rec["gross"], 0.02):
                        row[slot] = round(v - rec["excise"], 2)
                        ch += 1
                R[sym][q] = row
        if not dry and ch:
            json.dump(R, open(path, "w", encoding="utf-8"), separators=(",", ":"))
        print("%-44s slots netted: %d%s" % (os.path.basename(path), ch, " (dry-run)" if dry else ""))
        changed += ch
    if not dry:
        json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1)
    print("ledger entries:", sum(len(v) for v in led.values()))


if __name__ == "__main__":
    main()
