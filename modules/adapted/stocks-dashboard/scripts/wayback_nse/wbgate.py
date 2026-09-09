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
"""THE gate for archived-NSE std-PAT cells. ONE classifier, used by BOTH the hold-out calibration
and the landing run (memory: feedback-one-shared-classifier-for-fetch-audit-apply).

  G1  the page's own "NSE Symbol" == the symbol asked for                  identity
  G2  period spans exactly 3 months AND declares Non-Cumulative            a true quarter
  G3  IF the page prints a basis axis, it must say Non-Consolidated        standalone slot
      The 2000-2001 page revision prints only TWO axes and no basis at all; requiring the token
      there refused 44 of the first 75 true quarters for lacking something the era never emitted
      (runbook §112f). So the clause is conditional on the document revision -- and the relaxed
      form is what the hold-out measures.
  G4  declares a scale we know (lakhs / crores / million)
  G5  the page's OWN arithmetic closes: EPS == NetProfit x FaceValue / PaidUpCapital, <= 3%
      Needs nothing from us, which is the point: in 2000-2001 we usually hold nothing nearby.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wb_read import face_of, parse


def judge(sym, raw):
    """-> (value_or_None, reason, page). reason is '' on a pass."""
    if raw is None:
        return None, "fetch-failed (transport, NOT evidence about the data)", None
    p = parse(raw)
    if not p:
        return None, "unparseable/empty-shell page", None
    rt = p.get("result_type") or ""
    ntok = len([x for x in rt.split(",") if x.strip()])
    if p.get("symbol") != sym:
        return None, f"G1 page declares symbol {p.get('symbol')}, not {sym}", p
    if p["months"] != 3 or "Non-Cumulative" not in rt:
        return None, f"G2 not a true quarter: {p['months']}m, type={rt}", p
    if ntok >= 3 and "Non-Consolidated" not in rt:
        return None, f"G3 page declares a basis and it is not standalone: {rt}", p
    if p.get("div") is None:
        return None, f"G4 scale not declared/known: {p.get('scale')}", p
    if p.get("pat_cr") is None:
        return (
            None,
            ("G4b no Net Profit row (BANKING template, schema unread)" if p.get("bank") else "G4b no Net Profit row"),
            p,
        )
    fv = face_of(raw)
    np_ = p["net_profit"]
    pu = p["paidup"]
    eps = p["eps"]
    if not (fv and pu and pu > 0 and eps is not None and np_ is not None and eps != 0):
        return None, "G5 EPS identity not testable (EPS/face/paid-up missing or EPS printed 0.00)", p
    imp = np_ * fv / pu
    if abs(imp - eps) > max(0.05, 0.03 * max(abs(eps), abs(imp))):
        return None, f"G5 EPS identity fails: printed {eps}, NP*FV/PU = {imp:.2f}", p
    return round(p["pat_cr"], 2), "", p


def evidence(sym, ts, url, p, raw):
    return (
        "WAYBACK-ARCHIVED NSE results.jsp (web.archive.org/%s). Exchange-native and AS-FILED, "
        "not an aggregator rendition. The page DECLARES every gated field: Result Period %s to "
        "%s (%s) = %d month(s); Result Type '%s'; %s; scale Rs.%s. G1 the page's own NSE Symbol "
        "== %s. G5 the page's own arithmetic closes: printed Basic EPS %s == NetProfit %s x "
        "FaceValue %s / PaidUp %s. Gate + hold-out: scripts/wayback_nse/."
        % (
            ts,
            p["from"],
            p["to"],
            p["period_role"],
            p["months"],
            p.get("result_type"),
            "Non-Banking" if not p.get("bank") else "Banking",
            p.get("scale"),
            sym,
            p.get("eps"),
            p.get("net_profit"),
            face_of(raw),
            p.get("paidup"),
        )
    )
