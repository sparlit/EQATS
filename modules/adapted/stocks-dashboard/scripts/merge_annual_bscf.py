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
"""Land a Claude reader's annual BS/CF reads into scripts/annual_bscf.json, GATE-ENFORCED.

The no-key vision loop is: fetch_annual_bscf.py --prep renders each vision-needed filer's
balance-sheet + cash-flow pages and writes a manifest -> a Claude routine READS the PNGs with
native vision (no API key, the repo's proven pattern) and writes back the numbers per manifest
entry -> this script lands them.

The holdout gate is enforced HERE, not on trust: each symbol's manifest carries a 'validate'
entry for a year we DO hold from XBRL, with that year's XBRL 'key' (Total Assets + PP&E). A
symbol's FILL years are landed ONLY if the reader's numbers for the validate year match the key
to <=1%. A symbol whose read is wrong (or whose reader hallucinated) fails and lands NOTHING.

Input (arg1): the reader's output — a JSON list of the manifest entries with the read fields added:
  [{"sym","fy","role":"validate"|"fill"|"supplement","basis":"c|s","key":{...}(validate only),
    "assets","sc","oeq","borr","blt","bst","ppe","rou","cwip","iuad","gw","intg","invst","rec","pay","invnt",
    "cfo","cfi","cff","capex","cf_tax","cf_net","cf_fx","asat"}]   — ₹ crore, null a field the statement doesn't print.
  cf_net / cf_fx (net change in cash, FX effect) only feed the cash identity cfo + cfi + cff (+ fx) =
  cf_net; a read that FAILS it keeps its balance sheet but lands no cfo/cfi/cff. The validate year's
  own cash flow lands as a CF-only cell (v=1) when the slice has no CFO for that year (PFIZER FY25).
  'supplement' = a re-read of an ALREADY-LANDED cell's own document (iuad, a continued cash flow): it
  only fills null fields, and only when it re-anchors on the stored cell (see supplement()).
Run: python -X utf8 scripts/merge_annual_bscf.py <reader_output.json>
"""
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "annual_bscf.json")
FIN_DIR = os.path.join(HERE, "..", "docs", "fin")  # the per-stock slices (what the site serves)
FIELDS = {
    "assets",
    "sc",
    "oeq",
    "borr",
    "blt",
    "bst",
    "ppe",
    "cwip",
    "iuad",
    "gw",
    "intg",
    "invst",
    "invprop",
    "rec",
    "pay",
    "invnt",
    "cfo",
    "cfi",
    "cff",
    "capex",
    "cf_tax",
}
CF_FIELDS = ("cfo", "cfi", "cff", "capex", "cf_tax")


def slice_x(sym):
    """The symbol's slice 'x' map {qEnd: {s:{..}, c:{..}}} — the XBRL-held values the gate and the
    validate-year CF check read. {} when the slice is missing."""
    p = os.path.join(FIN_DIR, "{}.json".format(re.sub(r"[^A-Za-z0-9._-]", "_", sym)))
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p)).get("x") or {}
    except Exception:
        return {}


def cf_identity(cfo, cfi, cff, net, fx=None):
    """The statement's own cash identity cfo + cfi + cff (+ the FX effect, when printed) = net change
    in cash. True / False when checkable, None when a term is missing. Tolerance: 1 printed unit +
    0.2% of the largest term — rounding of printed figures, far below a wrong-line pick."""
    if cfo is None or cfi is None or cff is None or net is None:
        return None
    tol = 1.0 + 0.002 * max(abs(cfo), abs(cfi), abs(cff), abs(net))
    s = cfo + cfi + cff
    return abs(s - net) <= tol or (fx is not None and abs(s + fx - net) <= tol)


def validate_cf_cell(read, held, basis, method, src):
    """The validate year's own cash flow for a year whose balance sheet XBRL holds but whose cash flow
    it does not (PFIZER FY25: BS 4,911 cr from XBRL, no CF). A CF-only ledger cell marked v=1, or None.
    Never the BS fields of a held year; never when the slice already has a CFO for the year on this
    basis (the build only gap-fills, so a CF-only cell there would be dead weight); never when the
    read's own cash identity fails."""
    if (held or {}).get("cfo") is not None or read.get("cfo") is None:
        return None
    if cf_identity(read.get("cfo"), read.get("cfi"), read.get("cff"), read.get("cf_net"), read.get("cf_fx")) is False:
        return None
    cell = {"b": basis, "m": method, "src": src, "v": 1}
    cell.update({f: read[f] for f in CF_FIELDS if read.get(f) is not None})
    return cell


def _near(a, b, tol=0.01):
    return a is not None and b is not None and b != 0 and abs(a - b) / abs(b) <= tol


def supplement(cell, e):
    """Fields a re-read of an already-landed cell's OWN document adds (iuad; the second page of a
    continued cash flow). Returns the list of fields added. Guards: same document (src) and basis;
    NULL fields only (a stored value is never overwritten); balance-sheet fields only when the
    re-read's Total Assets is within 1% of the stored one (same page, same unit); cash-flow fields only
    when its CFO is within 1% of the stored CFO — or, if the cell has none, when the statement's own
    cash identity holds. ppe/assets are anchors, never supplemented (the ROU convention was fixed at landing)."""
    if not cell or e.get("src") != cell.get("src") or e.get("basis") != cell.get("b"):
        return []
    add = []
    bs_ok = _near(e.get("assets"), cell.get("assets"))
    if cell.get("cfo") is not None:
        cf_ok = _near(e.get("cfo"), cell.get("cfo"))
    else:
        cf_ok = cf_identity(e.get("cfo"), e.get("cfi"), e.get("cff"), e.get("cf_net"), e.get("cf_fx")) is True
    allowed = set(e.get("add") or (FIELDS - {"assets", "ppe"})) - {
        "assets",
        "ppe",
    }  # 'add' = fields this re-read may fill
    for f in sorted(allowed & FIELDS):
        if e.get(f) is None or cell.get(f) is not None:
            continue
        if (f in CF_FIELDS and cf_ok) or (f not in CF_FIELDS and bs_ok):
            cell[f] = e[f]
            add.append(f)
    if add:
        cell["sup"] = sorted(set(cell.get("sup", [])) | set(add))
    return add


def unit_slip(cell, e):
    """k when EVERY money field an independent re-read of the SAME document shares with the stored cell
    (3+ fields) is the re-read times one power of ten k != 1, within 0.1% — the stored cell landed in the
    wrong unit (ETERNAL FY22: a Rs-million page stored as crore, every field exactly 10x). Else None."""
    if not cell or e.get("src") != cell.get("src") or e.get("basis") != cell.get("b"):
        return None
    common = [
        f for f in FIELDS if isinstance(cell.get(f), (int, float)) and isinstance(e.get(f), (int, float)) and e[f]
    ]
    if len(common) < 3:
        return None
    for k in (10, 100, 1000, 1e4, 1e5, 1e7, 0.1, 0.01):
        if all(abs(cell[f] / e[f] - k) <= 0.001 * k for f in common):
            return k
    return None


def rescale(cell, k):
    """Divide every money field of a unit-slipped cell by k; the old values stay under 'fix'."""
    old = {f: cell[f] for f in FIELDS if isinstance(cell.get(f), (int, float))}
    for f, v in old.items():
        cell[f] = round(v / k, 4)
    cell["fix"] = dict(cell.get("fix", {}), unit=k, **{f"{f}_was": v for f, v in old.items() if f == "assets"})


def _same(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.011, 0.0005 * abs(b))


def correct(cell, e):
    """A re-read of a TEXT cell's own document by the fixed text reader (runbook §168c) corrects the
    old parser's cash-flow misreads — only with evidence. Returns {field: old value}.
      * the re-read triple satisfies the statement's cash identity -> its cfo/cfi/cff replace the stored
        ones that differ (VINDHYATEL FY20 cfi -0.08 -> 29.72: "(B)" had been read as "(8)");
      * otherwise, if the STORED triple contradicts the statement's own net change in cash, each stored
        value the re-read cannot reproduce is removed (HEROMOTOCO FY22 CFO 2.0 from "2 103 70";
        APLAPOLLO FY21 CFO 97,711 from "977,11") — a gap, never a guess;
      * a stored cf_tax the re-read reproduces with the OTHER sign takes the re-read's sign — the reader
        signs income tax by the statement's own arithmetic (+ paid, - net refund; §168j). The old rule
        only ever turned negatives positive, and so wrote GESHIP FY22 / MAHLOG FY21 refunds as payments.
    Never touches a vision cell; requires the same document, basis, and Total Assets within 0.5%.
    The old values stay in the cell under 'fix' (audit trail)."""
    if not cell or cell.get("m") != "text" or e.get("src") != cell.get("src") or e.get("basis") != cell.get("b"):
        return {}
    if not _near(e.get("assets"), cell.get("assets"), 0.005):
        return {}
    fix = {}
    if cf_identity(e.get("cfo"), e.get("cfi"), e.get("cff"), e.get("cf_net"), e.get("cf_fx")) is True:
        for f in ("cfo", "cfi", "cff"):
            if not _same(cell.get(f), e[f]):
                fix[f] = cell.get(f)
                cell[f] = e[f]
    elif cf_identity(cell.get("cfo"), cell.get("cfi"), cell.get("cff"), e.get("cf_net"), e.get("cf_fx")) is False:
        for f in ("cfo", "cfi", "cff"):
            if cell.get(f) is not None and not _same(cell[f], e.get(f)):
                fix[f] = cell.pop(f)
    t = cell.get("cf_tax")
    if t and e.get("cf_tax") is not None and _same(-t, e["cf_tax"]):
        fix["cf_tax"] = t
        cell["cf_tax"] = e["cf_tax"]
    if fix:
        cell["fix"] = dict(cell.get("fix", {}), **fix)
    return fix


def qe_of(e):
    """The ledger key of an entry's year-end: <fy> + its year-end MMDD. Default 31 March; a Dec- or June-year-end
    filer's entries carry "ye": "1231" / "0630" (stock page renderDeep() anchors those companies on that month)."""
    ye = str(e.get("ye") or "0331")
    return "%d%s" % (int(e["fy"]), ye if re.fullmatch(r"(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", ye) else "0331")


def asat_ok(e):
    """A fill's balance sheet must be the FISCAL-YEAR-END audited statement, not an interim or
    off-cycle one. Calendar-year filers (e.g. Ambuja pre-2022) print an "as at 30-Jun" interim BS
    that locate() can mistake for the March year-end. If the reader reported the statement date
    (asat), require it within a few days of the entry's year-end (<fy>-03-31 unless "ye" says
    otherwise); if it didn't, fall back to trusting it."""
    a = e.get("asat")
    if not a:
        return True
    m = re.search(r"(\d{4})\D(\d{1,2})\D(\d{1,2})", str(a)) or re.search(r"(\d{1,2})\D(\d{1,2})\D(\d{4})", str(a))
    if not m:
        return True
    g = [int(x) for x in m.groups()]
    y, mo, d = g if g[0] > 31 else [g[2], g[1], g[0]]
    try:
        q = qe_of(e)
        return abs((date(y, mo, d) - date(int(q[:4]), int(q[4:6]), int(q[6:8]))).days) <= 5
    except Exception:
        return True


def gate_ok(read, key):
    """(ok, add_rou). Anchor on Total Assets + PP&E vs the validate year's XBRL key.
    Filers split Right-of-use assets onto their own PDF line, but many tag ROU INSIDE the
    XBRL PropertyPlantAndEquipment tag (Ambuja FY25: PP&E 24656.29 + ROU 1464.76 = key 26121.05).
    So accept the ppe anchor if key matches the PP&E line alone OR PP&E+ROU, and report which,
    so the SAME convention is applied when landing that symbol's fill years."""
    key = key or {}
    ka, kp = key.get("assets"), key.get("ppe")
    ra, rp = read.get("assets"), read.get("ppe")
    if ra is None or not ka or abs(ra - ka) / abs(ka) > 0.01:
        return False, False  # Total Assets is the mandatory anchor
    if kp is not None and abs(kp) < 1e-9:
        # ZERO-PP&E holding/investment company (JSWHL): the PP&E anchor is degenerate (0 == 0
        # tells us nothing). Fall back to Total-Assets-only, but require the reader's PP&E to be
        # consistently ~0 (tiny vs assets) so a reader that hallucinated a real PP&E is still caught.
        if rp is None:
            return False, False
        return (abs(rp) <= max(1.0, 0.005 * abs(ka))), False
    if not kp or rp is None:
        return False, False
    # the key is stored to 0.01 crore, so a near-zero PP&E also matches within half that storage unit
    # (HEMIPROP FY25: key 0.01 vs printed 0.93 lakh = 0.0093 — the 1% test alone rejects a true match)
    if abs(rp - kp) / abs(kp) <= 0.01 or abs(rp - kp) <= 0.005:
        return True, False
    rou = read.get("rou") or 0
    if abs((rp + rou) - kp) / abs(kp) <= 0.01 or abs((rp + rou) - kp) <= 0.005:
        return True, True
    return False, False


def main():
    reads = json.load(open(sys.argv[1], encoding="utf-8"))
    bysym = {}
    for e in reads:
        bysym.setdefault(e["sym"], []).append(e)
    ledger = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    landed = 0
    trusted = 0
    vlanded = 0
    rejected = []
    offcycle = []
    basismix = []
    cfdrop = []
    supp = []
    supp_rej = []
    fixes = []
    for sym, entries in sorted(bysym.items()):
        # corrections, then supplements: re-reads of an already-landed cell's own document — no gate run,
        # they re-anchor on the stored cell instead
        for e in (x for x in entries if x.get("role") == "correct"):
            q = qe_of(e)
            fx = correct((ledger.get(sym) or {}).get(q), e)
            if fx:
                fixes.append(
                    "{} {}:{}".format(sym, q[:4], ",".join(f"{f} {fx[f]}->{ledger[sym][q].get(f)}" for f in sorted(fx)))
                )
        for e in (x for x in entries if x.get("role") == "supplement"):
            q = qe_of(e)
            k = unit_slip((ledger.get(sym) or {}).get(q), e)
            if k:
                rescale(ledger[sym][q], k)
                fixes.append(f"{sym} {q[:4]}: unit slip, every field /{k}")
            add = supplement((ledger.get(sym) or {}).get(q), e)
            (supp if add else supp_rej).append("{} {}{}".format(sym, q[:4], (":" + ",".join(add)) if add else ""))
        entries = [x for x in entries if x.get("role") not in ("supplement", "correct")]
        if not entries:
            continue
        val = next((e for e in entries if e.get("role") == "validate"), None)
        ok, add_rou = gate_ok(val, val.get("key")) if val else (False, False)
        if not ok:
            rejected.append(sym)
            continue
        trusted += 1
        vq = qe_of(val)
        if vq not in (ledger.get(sym) or {}):
            vc = validate_cf_cell(
                val, (slice_x(sym).get(vq) or {}).get(val.get("basis")), val.get("basis"), "vision", val.get("src", "")
            )
            if vc:
                ledger.setdefault(sym, {})[vq] = vc
                vlanded += 1
        for e in entries:
            if e.get("role") != "fill":
                continue
            if e.get("basis") != val.get("basis"):
                # never mix bases in one symbol's series — a standalone year among consolidated
                # ones (or vice-versa) reads as a false step-change. Skip; leave the year a gap.
                basismix.append("{} {}({})".format(sym, e.get("fy"), e.get("basis")))
                continue
            if not asat_ok(e):
                offcycle.append("{} {}".format(sym, e.get("fy")))
                continue
            if add_rou and e.get("ppe") is not None:
                e = dict(e)
                e["ppe"] = round(e["ppe"] + (e.get("rou") or 0), 4)  # round: 24396.64 not 24396.640000000003
            cell = {"b": e.get("basis", "c"), "m": "vision", "src": e.get("src", "")}
            cell.update({f: e[f] for f in FIELDS if e.get(f) is not None})
            if cell.get("assets") is None:
                continue
            if cf_identity(e.get("cfo"), e.get("cfi"), e.get("cff"), e.get("cf_net"), e.get("cf_fx")) is False:
                for f in ("cfo", "cfi", "cff"):  # the statement's own cash identity failed: keep the BS,
                    cell.pop(f, None)  # never land a cash flow that doesn't add up
                cfdrop.append("{} {}".format(sym, e.get("fy")))
            ledger.setdefault(sym, {})[qe_of(e)] = cell
            landed += 1
    json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"), sort_keys=True)
    print(
        "trusted %d symbols, landed %d fill-years + %d validate-year cash flows. gate-rejected %d: %s | "
        "off-cycle skipped %d: %s | basis-mix skipped %d: %s | cash identity failed (CF dropped) %d: %s"
        % (
            trusted,
            landed,
            vlanded,
            len(rejected),
            rejected[:12],
            len(offcycle),
            offcycle[:12],
            len(basismix),
            basismix[:12],
            len(cfdrop),
            cfdrop[:12],
        )
    )
    if supp or supp_rej:
        print(
            "supplements: %d applied %s | %d rejected (no cell / other document / anchor off / nothing new): %s"
            % (len(supp), supp[:20], len(supp_rej), supp_rej[:20])
        )
    if fixes:
        print("corrections: %d cells %s" % (len(fixes), fixes[:40]))


if __name__ == "__main__":
    main()
