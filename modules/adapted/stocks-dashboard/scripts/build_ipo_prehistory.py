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
"""Backfill PRE-IPO ANNUAL financials (revenue + net profit) for recently-listed names, for a
DISPLAY-ONLY context card on the stock page ("Pre-IPO financials, from the prospectus").

WHY THIS EXISTS / WHAT IT IS NOT
--------------------------------
A freshly-listed company's multi-year history lives in its DRHP as *annual* accounts. Private
companies do not file *quarterly* results before listing, so pre-IPO quarters simply do not exist
(DATA_RUNBOOK §2: "co's listed too recently whose earlier quarters are pre-IPO ... never
re-attempt"). MoneyControl's ANNUAL feed carries those DRHP-era years (INDOMIM 14 FYs, MANIPALHOS
9, measured 2026-09-03); its quarterly feed is as shallow as the exchange's for fresh names.

This file, docs/ipo_prehistory.json, is READ ONLY BY THE STOCK PAGE. It is NEVER read by the
backtest engine and is NEVER merged into sf_fundamentals/sf_revop. The backtest's point-in-time
fundamentals stay BSE-PDF+vision sourced and owners-attributable (runbook §2). Keeping aggregator
annual history in a separate, clearly-labelled artifact is the whole point.

SELF-CLEARING DAILY LEDGER (the user's ask: "check all IPOs daily till they get their old data")
------------------------------------------------------------------------------------------------
Each recently-listed name carries a status. A name is retried each run until 'filled'; a name the
feed can't serve yet (brand-new, MC has no annual, or we can't anchor it) stays 'pending' and is
retried; a name that stays empty for a long time drops to 'dormant' (retried occasionally, not
every run) so we don't ping dead symbols forever. Filled names are skipped.

ANCHOR (display-grade, still never-unanchored)
----------------------------------------------
We show MoneyControl's annual series ONLY once we've proved it is the right company at the right
scale: at least one quarter MC reports must reproduce a quarter WE already hold from the exchange
(sf_fundamentals standalone net profit), within tolerance. No overlap we can check yet -> stay
'pending', show nothing. This keeps unverified aggregator numbers off the page.

Run:  python -X utf8 scripts/build_ipo_prehistory.py            # one pass over the pending backlog
      python -X utf8 scripts/build_ipo_prehistory.py --limit 40 # cap names touched this run
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import agg_sources as AG  # mc_id / mc_quarters / mc_annuals (disk-cached, paced 1s)
import fetch_ipos as FI  # reuse the NSE public-issues session + iso()

OUT = os.path.join(DOCS, "ipo_prehistory.json")
SF_FUND = os.path.join(DOCS, "sf_fundamentals.json")  # [[qe, npStd, annStd, npCon, annCon]]
LOOKBACK_DAYS = 1095  # seed the backlog from IPOs of the last ~3 years (older names already covered)
PER_RUN = 120  # cap names attempted per run so the daily job stays well under CI timeout
DORMANT_AFTER = 45  # pending attempts with no annual data -> check occasionally, not daily
DORMANT_EVERY = 7  # ...retry a dormant name only every Nth day (by tries count)
PAT_TOL_ABS = 0.5  # ₹cr: overlap-quarter net-profit match tolerance (or 2% of |value|)


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def _norm(s):
    s = re.sub(r"\b(limited|ltd|private|pvt|the|india|indian)\b", " ", (s or "").lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def name_ok(a, b):
    """Belt-and-suspenders identity guard on top of mc_id's exact-symbol autosuggest match:
    the aggregator's company name must clearly be the same company we listed."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ta, tb = set(a.split()), set(b.split())
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5


def our_std_pat(sym):
    """{qe:int -> standalone net profit ₹cr} we already hold for this symbol (the anchor set)."""
    try:
        d = json.load(open(SF_FUND, encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for row in d.get(sym) or []:
        if len(row) >= 2 and row[0] and row[1] is not None:
            out[int(row[0])] = float(row[1])
    return out


def anchored(mc_q, ours):
    """True + the matched (qe, mc, ours) when >=1 quarter MC reports reproduces a quarter WE hold.
    Proves identity + scale on real filed data before we trust MC's deep annual history."""
    for qe, mine in ours.items():
        v = (mc_q.get(qe) or {}).get("pat_total")
        if v is None:
            continue
        if abs(v - mine) <= max(PAT_TOL_ABS, 0.02 * abs(mine)):
            return True, (qe, v, mine)
    return False, None


def fy_rows(mc_a):
    """MC annual dict {qe:{fields}} -> sorted [[fyYear, revenue, netProfit], ...] (Mar-end FYs).
    Revenue = operating revenue (Net Sales), falling back to Total Income; PAT = standalone net
    profit. Rows with neither number are dropped."""
    rows = []
    for qe in sorted(mc_a):
        if qe % 10000 != 331:  # annual = March year-end only
            continue
        v = mc_a[qe]
        rev = v.get("rev_ops")
        rev = rev if rev is not None else v.get("rev_total")
        pat = v.get("pat_total")
        if rev is None and pat is None:
            continue
        rows.append([qe // 10000, rev, pat])
    return rows


SCR_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
_SCR_LAST = [0.0]


def screener_annuals(sym):
    """FALLBACK annual source: revenue (Sales) + net profit from Screener's P&L section, keyed by
    our NSE ticker in the URL (no id map — reaches the SME names MoneyControl has no page for).
    -> ([[fyYear, rev, pat], ...] Mar-year-end, company_name, note). Screener occasionally prints an
    implausible pre-IPO figure, so a net profit whose |value| >> sales is dropped (screener_prefund's
    guard). Paced ~3s; a 429/blk leaves the name pending for the next run. Display-only, same as MC."""
    wait = 4.0 - (time.time() - _SCR_LAST[0])
    if wait > 0:
        time.sleep(wait)
    _SCR_LAST[0] = time.time()
    url = "https://www.screener.in/company/{}/".format(urllib.parse.quote(sym, safe=""))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": SCR_UA})
        t = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        return [], "", f"screener: HTTP {ex.code}"  # 404 = no page; 429 = rate-limited (retry next run)
    except Exception as ex:
        return [], "", f"screener: {ex}"
    m = re.search(r'id="profit-loss".*?</section>', t, re.DOTALL)
    if not m:
        return [], "", "screener: no P&L section"
    sec = m.group(0)
    yrs = re.findall(
        r"<th[^>]*>\s*([A-Za-z]{3} \d{4})\s*</th>", sec
    )  # year columns (TTM has no 'Mon YYYY' -> excluded)

    def row(lbl):
        mm = re.search(
            r'<td[^>]*class="text"[^>]*>\s*(?:<button[^>]*>)?\s*' + re.escape(lbl) + r".*?</td>(.*?)</tr>",
            sec,
            re.DOTALL,
        )
        if not mm:
            return []
        return [
            html.unescape(re.sub(r"<[^>]+>", "", c)).strip().replace(",", "")
            for c in re.findall(r"<td[^>]*>(.*?)</td>", mm.group(1), re.DOTALL)
        ]

    sales, nps = row("Sales"), row("Net Profit")
    nm = re.search(r"<h1[^>]*>\s*([^<]+?)\s*</h1>", t)
    name = nm.group(1).strip() if nm else ""
    rows = []
    for i, y in enumerate(yrs):
        mon, yr = y.split()
        if mon != "Mar":  # keep the March fiscal-year columns
            continue
        rev = _num(sales[i]) if i < len(sales) else None
        pat = _num(nps[i]) if i < len(nps) else None
        if rev is None and pat is None:
            continue
        if rev is not None and pat is not None and abs(pat) > max(3 * abs(rev), 50):  # outlier guard
            pat = None
        rows.append([int(yr), rev, pat])
    return (
        rows,
        name,
        "screener: %d FYs %s..%s" % (len(rows), rows[0][0] if rows else "-", rows[-1][0] if rows else "-"),
    )


def seed_universe():
    """Recently-listed names from NSE public-past-issues, listed within LOOKBACK_DAYS.
    -> {sym: {"name","listed","board"}}. Empty on fetch failure (we then just work the ledger)."""
    jar = FI.B.nse_jar()
    try:
        past = (
            FI.get(jar, "public-past-issues", "https://www.nseindia.com/market-data/new-stock-exchange-listings-recent")
            or []
        )
    except Exception as e:
        print(f"past-issues fetch failed ({e}) — working the existing ledger only", flush=True)
        return {}
    lo = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    uni = {}
    for r in past:
        st = str(r.get("securityType") or "").strip().upper()
        if st not in ("EQ", "BE", "SME"):
            continue
        ld = FI.iso(r.get("listingDate"))
        sym = str(r.get("symbol") or "").strip().upper()
        if not (ld and sym) or ld < lo:
            continue
        uni.setdefault(
            sym, {"name": str(r.get("company") or "").strip(), "listed": ld, "board": "SME" if "SME" in st else "Main"}
        )
    return uni


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=PER_RUN)
    args = ap.parse_args()

    led = {}
    if os.path.exists(OUT):
        try:
            led = json.load(open(OUT, encoding="utf-8")).get("data") or {}
        except Exception:
            led = {}

    uni = seed_universe()
    for sym, meta in uni.items():
        e = led.setdefault(sym, {})
        e.setdefault("name", meta["name"])
        e.setdefault("listed", meta["listed"])
        e.setdefault("board", meta["board"])
        e.setdefault("status", "pending")
        e.setdefault("tries", 0)

    # work order: never-filled first, least-recently-tried first; skip dormant names off their cadence
    def due(e):
        if e.get("status") == "filled":
            return False
        if e.get("status") == "dormant" and (e.get("tries", 0) % DORMANT_EVERY):
            return False
        return True

    todo = [s for s, e in led.items() if due(e)]
    todo.sort(key=lambda s: led[s].get("last") or "")  # oldest attempt first
    todo = todo[: max(1, args.limit)]

    filled = pending = 0
    today = datetime.date.today().isoformat()
    for sym in todo:
        e = led[sym]
        e["tries"] = e.get("tries", 0) + 1
        e["last"] = today
        try:
            rows = source = disp_name = None
            note = ""
            ok = False
            hit = None
            # 1) MoneyControl — deep annual, id-gated (identity via exact-symbol autosuggest + name).
            ident = AG.mc_id(sym)
            if ident and name_ok(ident.get("name"), e.get("name")):
                mc_a, na = AG.mc_annuals(sym, False)
                r = fy_rows(mc_a)
                if r:
                    rows, source, disp_name, note = r, "mc", ident.get("name"), na
                    # Upgrade to a "matches filed results" badge when a quarter MC reports reproduces
                    # one we already hold (proves scale on real filed data); not required to show.
                    mc_q, _ = AG.mc_quarters(sym, False)
                    ok, hit = anchored(mc_q, our_std_pat(sym))
                else:
                    note = na
            else:
                note = "MC id name mismatch ({})".format(ident.get("name")) if ident else "no MoneyControl page"
            # 2) Screener FALLBACK — keyed by ticker, reaches the SME names MoneyControl lacks.
            if rows is None:
                sr, sname, sn = screener_annuals(sym)
                if sr and name_ok(sname, e.get("name")):
                    rows, source, disp_name, note = sr, "screener", sname, sn
                elif sr:
                    note = f"screener id name mismatch ({sname})"
                else:
                    note = f"{note}; {sn}"
            if rows is None:
                if e["tries"] >= DORMANT_AFTER:
                    e["status"] = "dormant"
                e["note"] = note
                pending += 1
                continue
            e.update(
                status="filled",
                basis=("std" if source == "mc" else "reported"),
                source=source,
                asof=today,
                rows=rows,
                verified=bool(ok),
                mc_name=disp_name,
            )
            e["anchor"] = {"qe": hit[0], "mc": hit[1], "ours": hit[2]} if ok else None
            e["note"] = ("✓ matches filed %d; " % hit[0] if ok else "") + note
            e.pop("tries", None)
            filled += 1
        except Exception as ex:
            e["note"] = f"error: {ex}"
            pending += 1

    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    total_filled = sum(1 for e in led.values() if e.get("status") == "filled")
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M"), "data": led}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(
        "attempted %d: +%d filled, %d still pending | ledger %d names, %d filled -> %s"
        % (len(todo), filled, pending, len(led), total_filled, OUT),
        flush=True,
    )
    for sym in todo[:6]:
        e = led[sym]
        print("  %-12s %-8s %s" % (sym, e.get("status"), e.get("note", "")[:80]), flush=True)


if __name__ == "__main__":
    main()
