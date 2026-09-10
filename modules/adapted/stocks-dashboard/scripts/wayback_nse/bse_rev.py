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
"""Standalone REVENUE from BSE's ARCHIVED results page (Wayback), `bseindia.com/qresann/result.asp` —
the "STEP B candidate" PRE2015_CAMPAIGN.md scoped on 2026-08-07 and never built; built 2026-09-05 for the
rev-parity campaign as the sibling of wb_rev.py (same gates, same ledger discipline).

The URL names the company and period (`scripcd=<BSE code>&quarter=<DQ|MQ|JQ|SQ|MC|DC|SC|SH...><FY>`), and
the page DECLARES the period ("Date Begin: 01 Oct 2000  Date End: 31 Dec 2000") and the scale
("Value(Rs. million)"), then prints label/value rows:
  non-bank  Net Sales / Total Income / Expenditure / Operating Profit / Interest / Gross Profit / Net Profit
  bank      Interest Earned,Operating Income / Other Income / Total Income / ... / Net Profit
Basis is NOT declared, so the ANCHOR carries identity: the page's Net Profit (÷10 to crore) must equal the
stored sf_fundamentals npStd to the paisa, and the page's own ScripCode must equal the BSE code the repo's
master (scripts/bse_scrips.json, ISIN-merged rename map for predecessors) holds for the symbol.
Index: scripts/wayback_nse/_bse_wb_index.json  "<scripcd>|<to_qe>" -> [[ts, url, quarter_code], ...],
built from the CDX enumeration a peer cached (~/stocks-wt/pre2015-stepw-harvest/scripts/_wb_cache, 28,550
200-captures, 2001-2008) — see --build-index.

  python3 -X utf8 scripts/wayback_nse/bse_rev.py --build-index
  python3 -X utf8 scripts/wayback_nse/bse_rev.py --calib [--n 300]
  python3 -X utf8 scripts/wayback_nse/bse_rev.py --cells <gap.json> --orig <orig.json> --out <props.json> [--fetch]
  python3 -X utf8 scripts/wayback_nse/bse_rev.py --emit <props.json>   -> scripts/_bserev_reads.json + bse_rev_fills.json
"""
import collections
import glob
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import wbcache  # noqa: E402
from wb_rev import TOL, prev_qe  # noqa: E402

INDEX = os.path.join(HERE, "_bse_wb_index.json")
LEDGER = os.path.join(HERE, "bse_rev_fills.json")
READS = os.path.join(SCRIPTS, "_bserev_reads.json")
MON = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
QEND = {(3, 31), (6, 30), (9, 30), (12, 31)}


def _txt(raw):
    t = re.sub(r"<script.*?</script>", " ", raw, flags=re.DOTALL)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t)


def _date(s):
    """'01 Oct 2000' (2002+ captures) or '10/1/2000' M/D/YYYY (the 2001-02 site revision) -> yyyymmdd."""
    s = s.strip()
    m = re.match(r"(\d{1,2}) ([A-Za-z]{3}) (\d{4})", s)
    if m:
        return int(m.group(3)) * 10000 + MON[m.group(2).upper()] * 100 + int(m.group(1))
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return int(m.group(3)) * 10000 + int(m.group(1)) * 100 + int(m.group(2))
    return None


def _num(t, label):
    # values print with or without decimals ("438.98", "439", "1,368.00")
    m = re.search(r"(?<![A-Za-z,])" + re.escape(label) + r"\s+(-?[\d,]*\d(?:\.\d+)?)(?![\d.,]*%)", t)
    return float(m.group(1).replace(",", "")) if m else None


def read_page(raw, scripcd):
    if raw is None:
        return {"refuse": "fetch-failed (transport, not evidence)"}
    t = _txt(raw)
    if "ScripCode" not in t or "Date Begin" not in t:
        return {"refuse": "unparseable/empty-shell page"}
    m = re.search(r"ScripCode:\s*(\d+)", t)
    if not m or m.group(1) != str(scripcd):
        return {"refuse": f"G1 page declares ScripCode {m.group(1) if m else None}, not {scripcd}"}
    mb = re.search(r"Date Begin:\s*(\d{1,2} [A-Za-z]{3} \d{4}|\d{1,2}/\d{1,2}/\d{4})", t)
    me = re.search(r"Date End:\s*(\d{1,2} [A-Za-z]{3} \d{4}|\d{1,2}/\d{1,2}/\d{4})", t)
    if not (mb and me):
        return {"refuse": "period not declared"}
    frm, to = _date(mb.group(1)), _date(me.group(1))
    if not (frm and to):
        return {"refuse": "period unparseable"}
    ms = re.search(r"Value\s*\(Rs\.?\s*([A-Za-z]+)\)", t)
    div = {"million": 10.0, "millions": 10.0, "lakhs": 100.0, "lakh": 100.0, "crore": 1.0, "crores": 1.0}.get(
        ms.group(1).lower() if ms else ""
    )
    if not div:
        return {"refuse": "G4 scale not declared/known: %s" % (ms.group(1) if ms else None)}
    bank = "Interest Earned" in t
    # EVERY candidate revenue line is read; the caller picks ONE by reproduction against the symbol's own held
    # quarters (memory: feedback-aggregator-two-revenue-definitions). The store's pre-2009 std revenue follows
    # the NSE page's "Net Sales" line, which for excise-paying manufacturers is what BSE prints as "Gross Sales"
    # (ACC Dec-2003: stored 905.77 == BSE Gross Sales 9,057.70 mn; BSE Net Sales 7,599.70 mn) -- measured 2026-09-05.
    cands = (
        ["Interest Earned,Operating Income", "Interest Earned", "Total Income"]
        if bank
        else ["Net Sales", "Gross Sales", "Total Income"]
    )
    lines = {}
    for c in cands:
        v = _num(t, c)
        if v is not None:
            lines[c] = round(v / div, 4)
    if bank and "Interest Earned,Operating Income" in lines:
        lines.pop("Interest Earned", None)
    pat = _num(t, "Net Profit")
    if pat is None:
        return {"refuse": "no Net Profit row on the page"}
    if not lines:
        return {"refuse": "no revenue line on the page"}

    # printed precision -> tolerance in crore (an integer million is a 0.1-crore grid; half of that is the honest tol)
    def _dec(label):
        m = re.search(r"(?<![A-Za-z,])" + re.escape(label) + r"\s+(-?[\d,]*\d(?:\.(\d+))?)", t)
        return len(m.group(2)) if (m and m.group(2)) else 0

    prec = min([_dec("Net Profit")] + [_dec(c) for c in lines])
    tol = max(TOL, 0.5 * (10**-prec) / div + 1e-9)
    months = (to // 10000 - frm // 10000) * 12 + ((to % 10000) // 100 - (frm % 10000) // 100) + 1
    name = re.search(r"ScripName:\s*(.+?)\s+Quarter:", t)
    return {
        "from": frm,
        "to": to,
        "months": months,
        "bank": bank,
        "scale": ms.group(1).lower(),
        "div": div,
        "pat": round(pat / div, 4),
        "lines": lines,
        "tol": tol,
        "prec": prec,
        "raw_pat": pat,
        "name": name.group(1) if name else None,
        "role": re.search(r"Quarter:\s*(.+?)\s+Date Begin", t).group(1)
        if re.search(r"Quarter:\s*(.+?)\s+Date Begin", t)
        else "",
    }


def qdist(a, b):
    return abs((a // 10000 - b // 10000) * 4 + ((a % 10000) // 100 - (b % 10000) // 100) // 3)


def definition_votes(sym_keys, sc, qe, revop, std, excl, idx, fetch, window=8):
    """Per-symbol REVENUE-DEFINITION gate. Over the symbol's HELD std-revenue cells (exchange-derived, not this
    campaign's, within +-window quarters of the target) that have a 3-month BSE capture whose PAT anchors:
    which printed line reproduces the stored value? -> ({line: [exact, conflict]}, anchors_used)"""
    votes, used = collections.defaultdict(lambda: [0, 0]), 0
    for k in sym_keys:
        for q_s, row in (revop.get(k) or {}).items():
            q = int(q_s)
            if row[0] is None or q == qe or (k, q) in excl or (k, q) not in std or qdist(q, qe) > window:
                continue
            r = _read_any(idx, sc, q, fetch, want_months=3)
            if "refuse" in r or abs(r["pat"] - std[(k, q)]) > r["tol"]:
                continue
            used += 1
            for line, v in r["lines"].items():
                if abs(v - row[0]) <= r["tol"]:
                    votes[line][0] += 1
                else:
                    votes[line][1] += 1
    return dict(votes), used


def choose_line(votes, page_lines):
    """The line with >=2 exact and 0 conflicts that the target page prints. Two qualifying lines are fine only
    when the target page prints the SAME value for both (no excise that quarter); otherwise the anchors cannot
    tell the definitions apart and the cell is refused as a tie."""
    ok = [l for l, (e, c) in votes.items() if e >= 2 and c == 0 and l in page_lines]
    if not ok:
        return None, f"definition unverifiable: votes={json.dumps(votes, sort_keys=True)}"
    vals = {round(page_lines[l], 4) for l in ok}
    if len(vals) > 1:
        return (
            None,
            f"definition TIE: {ok} all reproduce the neighbours but differ on this page { ({l: page_lines[l] for l in ok}) }",
        )
    return ok[0], ""


def build_index():
    D = os.path.expanduser("~/stocks-wt/pre2015-stepw-harvest/scripts/_wb_cache")
    rows = []
    for f in os.listdir(D):
        if f.startswith("cdx_url_bseindia.com_2Fqresann"):
            rows += json.load(open(os.path.join(D, f)))
    ok = sorted(
        {
            (r["timestamp"], r["original"])
            for r in rows
            if r.get("statuscode") == "200" and "result.asp?" in r["original"]
        }
    )
    idx = collections.defaultdict(list)
    for ts, u in ok:
        q = dict(re.findall(r"([a-z_]+)=([^&]*)", u.split("?", 1)[1], re.IGNORECASE))
        sc, qu = q.get("scripcd"), q.get("quarter", "")
        m = re.match(r"([A-Z])([A-Z])(\d{4})-(\d{4})$", qu)
        if not sc or not m:
            continue
        mon = {"M": 3, "J": 6, "S": 9, "D": 12}[m.group(1)]
        fy0 = int(m.group(3))
        year = fy0 + (1 if mon == 3 else 0)  # DQ2000-2001 ends Dec-2000; MQ2000-2001 ends Mar-2001
        to = year * 10000 + mon * 100 + {3: 31, 6: 30, 9: 30, 12: 31}[mon]
        idx["%s|%d" % (sc, to)].append([ts, u, m.group(1) + m.group(2)])
    json.dump(idx, open(INDEX, "w"), separators=(",", ":"), sort_keys=True)
    print(
        "index: %d (scripcd, quarter-end) keys, %d captures -> %s"
        % (len(idx), sum(len(v) for v in idx.values()), INDEX)
    )


def codes_for(sym, fund_key, bse, inv):
    keys = {sym, fund_key} | inv.get(sym, set()) | inv.get(fund_key, set())
    return sorted({str(bse[k]) for k in keys if k in bse})


def _read_any(idx, sc, qe, fetch, want_months=None, want_from=None):
    """First capture under (sc, qe) that parses with G1 and (optionally) the wanted period."""
    last = {"refuse": "no BSE capture ends on this quarter"}
    for ts, url, qc in idx.get("%s|%d" % (sc, qe), []):
        raw = wbcache.fetch_cached(ts, url) if fetch else wbcache.cached(ts, url)
        r = read_page(raw, sc)
        if "refuse" in r:
            last = r
            continue
        if r["to"] != qe:
            last = {"refuse": "G2a page period ends %d, not %d" % (r["to"], qe)}
            continue
        if want_months is not None and r["months"] != want_months:
            last = {"refuse": "period %d..%d is %dm" % (r["from"], r["to"], r["months"])}
            continue
        if want_from is not None and r["from"] != want_from:
            last = {"refuse": "period starts %d, wanted %d" % (r["from"], want_from)}
            continue
        r["ts"], r["url"], r["qc"] = ts, url, qc
        return r
    return last


def _excl_set():
    excl = set()
    for path in (
        glob.glob(os.path.join(SCRIPTS, "agg_cell_fills.json"))
        + glob.glob(os.path.join(SCRIPTS, "mc_*_fills.json"))
        + [os.path.join(HERE, "wb_rev_fills.json"), LEDGER]
    ):
        if os.path.exists(path):
            for k in json.load(open(path)):
                if "|" in k:
                    a, b = k.split("|")[:2]
                    excl.add((a, int(b)))
    for k, v in json.load(open(os.path.join(SCRIPTS, "vision_rev_fills.json"))).items():
        if "|" in k and any(
            w in json.dumps(v).lower() for w in ("moneycontrol", "screener", "trendlyne", "tickertape", "wayback")
        ):
            a, b = k.split("|")[:2]
            excl.add((a, int(b)))
    return excl


def stage(cells, orig, idx, fund, bse, inv, fetch=False, revop=None, excl=None):
    std = {(s, r[0]): r[1] for s, rows in fund.items() for r in rows if r[1] is not None}
    revop = revop or json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    excl = excl if excl is not None else _excl_set()
    props, refs = {}, {}
    for sym, qe, _ps, _pc in cells:
        fkeys = orig.get("%s|%d" % (sym, qe)) or [sym]
        why, done = [], False
        for fk in fkeys:
            stored = std.get((fk, qe))
            if stored is None:
                why.append(f"{fk}: no stored npStd")
                continue
            codes = codes_for(sym, fk, bse, inv)
            if not codes:
                why.append(f"{fk}: no BSE code in scripts/bse_scrips.json for the symbol or its predecessors")
                continue
            for sc in codes:
                if not idx.get("%s|%d" % (sc, qe)):
                    why.append(f"{sc}: no BSE capture ends on this quarter")
                    continue
                sym_keys = {sym, fk} | inv.get(sym, set()) | inv.get(fk, set())
                votes, used = definition_votes(sym_keys, sc, qe, revop, std, excl, idx, fetch)
                # direct quarter
                r = _read_any(idx, sc, qe, fetch, want_months=3)
                if "refuse" not in r:
                    if abs(r["pat"] - stored) > r["tol"]:
                        why.append(
                            "{}: ANCHOR-FAIL page PAT {:.3f} vs stored {:.2f} (finding, not a fill)".format(
                                sc, r["pat"], stored
                            )
                        )
                        continue
                    line, dwhy = choose_line(votes, r["lines"])
                    if not line:
                        why.append("%s: %s (anchors used %d)" % (sc, dwhy, used))
                        continue
                    props["%s|%d" % (fk, qe)] = {
                        "sym": fk,
                        "qe": qe,
                        "scripcd": sc,
                        "rev": round(r["lines"][line], 2),
                        "fin": 1 if r["bank"] else 0,
                        "mode": "direct",
                        "pat_seen": stored,
                        "page_pat": r["pat"],
                        "rev_label": line,
                        "scale": r["scale"],
                        "definition_votes": votes,
                        "anchors": used,
                        "tol": r["tol"],
                        "period": "%d..%d (%s)" % (r["from"], r["to"], r["role"]),
                        "name": r["name"],
                        "wayback": [r["ts"], r["url"]],
                    }
                    done = True
                    break
                # cumulative page ending on qe: difference against a chain of legs back to its start
                c = _read_any(idx, sc, qe, fetch)
                if "refuse" in c:
                    why.append("{}: {}".format(sc, c["refuse"]))
                    continue
                if c["months"] <= 3:
                    why.append("{}: {}".format(sc, r["refuse"]))
                    continue
                chain, cur, bad = [], prev_qe(qe), None
                while True:
                    leg = _read_any(idx, sc, cur, fetch)
                    if "refuse" in leg:
                        bad = "leg ending %d: %s" % (cur, leg["refuse"])
                        break
                    if leg["from"] < c["from"] or leg["bank"] != c["bank"]:
                        bad = "leg %d..%d does not nest in %d..%d" % (leg["from"], leg["to"], c["from"], c["to"])
                        break
                    chain.append(leg)
                    if leg["from"] == c["from"]:
                        break
                    if len(chain) >= 3:
                        bad = "chain longer than 3 legs"
                        break
                    cur = prev_qe(cur)
                if bad:
                    why.append(f"{sc}: cumulative page but {bad}")
                    continue
                if sum(l["months"] for l in chain) != c["months"] - 3:
                    why.append(
                        "%s: chain covers %dm, expected %dm" % (sc, sum(l["months"] for l in chain), c["months"] - 3)
                    )
                    continue
                tol = max([c["tol"]] + [l["tol"] for l in chain])
                dpat = round(c["pat"] - sum(l["pat"] for l in chain), 4)
                if abs(dpat - stored) > tol:
                    why.append(
                        "{}: CUMDIFF PAT {:.3f}-{:.3f}={:.3f} vs stored {:.2f} (identity fails)".format(
                            sc, c["pat"], sum(l["pat"] for l in chain), dpat, stored
                        )
                    )
                    continue
                common = {l: c["lines"][l] for l in c["lines"] if all(l in leg["lines"] for leg in chain)}
                line, dwhy = choose_line(votes, common)
                if not line:
                    why.append("%s: cumdiff %s (anchors used %d)" % (sc, dwhy, used))
                    continue
                props["%s|%d" % (fk, qe)] = {
                    "sym": fk,
                    "qe": qe,
                    "scripcd": sc,
                    "rev": round(c["lines"][line] - sum(l["lines"][line] for l in chain), 2),
                    "fin": 1 if c["bank"] else 0,
                    "mode": "cumdiff",
                    "pat_seen": stored,
                    "page_pat": dpat,
                    "rev_label": line,
                    "scale": c["scale"],
                    "definition_votes": votes,
                    "anchors": used,
                    "tol": tol,
                    "period": "%d..%d (%s) MINUS %s"
                    % (c["from"], c["to"], c["role"], " + ".join("%d..%d" % (l["from"], l["to"]) for l in chain)),
                    "legs": {
                        "cum": {"rev": c["lines"][line], "pat": c["pat"]},
                        "prev": [{"rev": l["lines"][line], "pat": l["pat"], "ts": l["ts"]} for l in chain],
                    },
                    "name": c["name"],
                    "wayback": [c["ts"], c["url"]],
                    "wayback_prev": [[l["ts"], l["url"]] for l in chain],
                }
                done = True
                break
            if done:
                break
        if not done:
            refs["%s|%d" % (sym, qe)] = why
    return props, refs


def evidence(p):
    s = (
        "WAYBACK-ARCHIVED BSE results page bseindia.com/qresann/result.asp (web.archive.org/%s), exchange-native and "
        "AS-FILED. Page ScripCode %s == the repo's BSE code for %s (ScripName '%s'); period declared %s; scale Rs.%s declared. "
        "Row '%s' (%s template), CHOSEN BY REPRODUCTION: over %d held neighbour quarters of this symbol with a BSE "
        "capture, the lines reproducing the stored value were %s (>=2 exact, 0 conflicts). ANCHOR: page Net Profit %.3f cr == "
        "stored sf_fundamentals npStd %.2f (tol %.3f from printed precision). "
        % (
            p["wayback"][0],
            p["scripcd"],
            p["sym"],
            p["name"],
            p["period"],
            p["scale"],
            p["rev_label"],
            "Banking" if p["fin"] else "Non-Banking",
            p["anchors"],
            json.dumps(p["definition_votes"], sort_keys=True),
            p["page_pat"],
            p["pat_seen"],
            p["tol"],
        )
    )
    if p["mode"] == "cumdiff":
        s += (
            "CUMULATIVE DIFFERENCING: cum rev {:.3f} / pat {:.3f} minus legs {}; the PAT difference reproduces the stored "
            "quarter, so the revenue difference is the same quarter. ".format(
                p["legs"]["cum"]["rev"],
                p["legs"]["cum"]["pat"],
                ", ".join(
                    "rev {:.3f} / pat {:.3f} (web.archive.org/{})".format(l["rev"], l["pat"], l["ts"])
                    for l in p["legs"]["prev"]
                ),
            )
        )
    return s + "Reader + hold-out: scripts/wayback_nse/bse_rev.py --calib. rev-parity campaign 2026-09-05."


def emit(props, stamp):
    reads = json.load(open(READS)) if os.path.exists(READS) else {}
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    n = 0
    for key, p in sorted(props.items()):
        if key in led:
            continue
        reads.setdefault(p["sym"], {})[str(p["qe"])] = {
            "basis": "std",
            "rev": p["rev"],
            "pat_seen": p["pat_seen"],
            "fin": p["fin"],
            "src": "wayback BSE qresann/result.asp {} scripcd={} {}={} pat={} ({}) [rev-parity {}]".format(
                p["mode"], p["scripcd"], p["rev_label"], p["rev"], p["page_pat"], p["wayback"][0], stamp
            ),
        }
        led[key] = {
            "revS": p["rev"],
            "fin": p["fin"],
            "mode": p["mode"],
            "row_label": p["rev_label"],
            "scripcd": p["scripcd"],
            "anchor": {"stored_npStd": p["pat_seen"], "page_pat": p["page_pat"]},
            "wayback": p["wayback"],
            "wayback_prev": p.get("wayback_prev"),
            "period": p["period"],
            "evidence": evidence(p),
            "applied": f"{stamp} rev-parity BSE-archive route",
        }
        n += 1
    json.dump(reads, open(READS, "w"), indent=1, sort_keys=True)
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print(
        "emitted %d new cells -> %s (+ ledger %s, now %d entries)"
        % (n, os.path.basename(READS), os.path.basename(LEDGER), len(led))
    )


def _load_common():
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    bse = json.load(open(os.path.join(SCRIPTS, "bse_scrips.json")))["by_id"]
    rmap = json.load(open(os.path.join(SCRIPTS, "_rename_map.json")))
    inv = collections.defaultdict(set)
    for a, b in rmap.items():
        inv[b].add(a)
    idx = json.load(open(INDEX))
    return fund, bse, inv, idx


def calib(n, fetch):
    """HOLD-OUT on held revStd cells (exchange-derived; aggregator-derived and this campaign's own cells excluded)."""
    import random

    fund, bse, inv, idx = _load_common()
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    excl = set()
    for path in (
        glob.glob(os.path.join(SCRIPTS, "agg_cell_fills.json"))
        + glob.glob(os.path.join(SCRIPTS, "mc_*_fills.json"))
        + [os.path.join(HERE, "wb_rev_fills.json"), LEDGER]
    ):
        if os.path.exists(path):
            for k in json.load(open(path)):
                if "|" in k:
                    a, b = k.split("|")[:2]
                    excl.add((a, int(b)))
    for k, v in json.load(open(os.path.join(SCRIPTS, "vision_rev_fills.json"))).items():
        if "|" in k and any(
            w in json.dumps(v).lower() for w in ("moneycontrol", "screener", "trendlyne", "tickertape", "wayback")
        ):
            a, b = k.split("|")[:2]
            excl.add((a, int(b)))
    std = {(s, r[0]): r[1] for s, rows in fund.items() for r in rows if r[1] is not None}
    cands = []
    for s, rows in revop.items():
        for q, r in rows.items():
            q = int(q)
            if r[0] is None or (s, q) in excl or (s, q) not in std or q > 20081231:
                continue
            for sc in codes_for(s, s, bse, inv):
                if idx.get("%s|%d" % (sc, q)):
                    cands.append((s, q, sc, r[0]))
                    break
    random.Random(5).shuffle(cands)
    print("candidate held cells with a same-quarter BSE capture: %d; testing %d" % (len(cands), min(n, len(cands))))
    res, mism = collections.Counter(), []
    for s, q, sc, stored_rev in cands[:n]:
        r = _read_any(idx, sc, q, fetch, want_months=3)
        if "refuse" in r:
            res["refused:" + r["refuse"][:22]] += 1
            continue
        if abs(r["pat"] - std[(s, q)]) > r["tol"]:
            res["pat-anchor-miss"] += 1
            continue
        sym_keys = {s} | inv.get(s, set())
        votes, _used = definition_votes(
            sym_keys, sc, q, revop, std, excl, idx, fetch
        )  # excludes q itself: leave-one-out
        line, _dwhy = choose_line(votes, r["lines"])
        if not line:
            res["definition-refused"] += 1
            continue
        kind = "bank" if r["bank"] else "non-bank"
        ok = abs(r["lines"][line] - stored_rev) <= r["tol"]
        res["{}:{}".format(kind, "MATCH" if ok else "MISMATCH")] += 1
        if not ok:
            mism.append(
                (
                    s,
                    q,
                    sc,
                    line,
                    stored_rev,
                    r["lines"][line],
                    round(stored_rev / r["lines"][line], 3) if r["lines"][line] else None,
                )
            )
    for k, v in sorted(res.items()):
        print("%6d %s" % (v, k))
    print("mismatches:", mism[:40])


def main():
    av = sys.argv
    if "--build-index" in av:
        return build_index()
    if "--calib" in av:
        return calib(int(av[av.index("--n") + 1]) if "--n" in av else 300, "--fetch" in av)
    if "--emit" in av:
        import time

        return emit(
            json.load(open(av[av.index("--emit") + 1]))["proposals"],
            av[av.index("--stamp") + 1] if "--stamp" in av else time.strftime("%Y-%m-%d"),
        )
    cells = json.load(open(av[av.index("--cells") + 1]))
    orig = json.load(open(av[av.index("--orig") + 1])) if "--orig" in av else {}
    fund, bse, inv, idx = _load_common()
    props, refs = stage(cells, orig, idx, fund, bse, inv, fetch="--fetch" in av)
    modes = collections.Counter(p["mode"] + ("/bank" if p["fin"] else "") for p in props.values())
    print(
        "proposals: %d %s by year %s"
        % (len(props), dict(modes), dict(sorted(collections.Counter(p["qe"] // 10000 for p in props.values()).items())))
    )
    cls = collections.Counter(
        re.sub(r"[\d.]+", "#", re.sub(r"^[A-Z0-9&_-]+: ", "", (w[-1] if w else "?")))[:70] for w in refs.values()
    )
    print("refusals: %d" % len(refs))
    for k, v in cls.most_common(20):
        print("  %5d %s" % (v, k))
    out = av[av.index("--out") + 1] if "--out" in av else os.path.join(HERE, "_bse_rev_props.json")
    json.dump({"proposals": props, "refusals": refs}, open(out, "w"), indent=1, sort_keys=True)
    print("->", out)
    return None


if __name__ == "__main__":
    main()
