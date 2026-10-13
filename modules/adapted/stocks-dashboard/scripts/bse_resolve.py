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
"""ISIN-GUARDED NSE-symbol -> BSE-scrip resolution.  (2026-08-10, after the KALYANI trap; §76)

★ THE RULE: a BSE `scrip_id` that equals our NSE ticker is a COINCIDENCE TO BE DISPROVED, never
a match to be trusted. Gate on ISIN — the only identifier both exchanges agree on.

WHY THIS EXISTS. `bse_scrips.json` "by_id" is BSE's `scrip_id` -> `SCRIP_CD`, but every consumer in
this repo uses it as "NSE symbol -> BSE scrip code". Those are different namespaces that happen to
collide. KALYANI is the 4th instance of the class (after TRU/CCL/SHK, §72):

    our KALYANI = Kalyani Commercials Ltd  INE610E01010  (NSE-only, NOT listed on BSE at all)
    by_id[KALYANI] -> 544023 = Kalyani Cast-Tech Ltd  INE0N6U01018  (a different company)

Three of its quarters were filled with Cast-Tech's profits, its con slots invented from Cast-Tech's
consolidated filings, and one announce date taken from Cast-Tech's calendar, before the std-PAT
adjudication (§73) caught it. A full scan of the 2,225 checkable symbols found exactly TWO live
conflicts — KALYANI and FOCUS — both recorded in `bse_scrip_isin_conflicts.json`.

Note the asymmetry that makes this dangerous: a WRONG code fails no magnitude check, no anchor, no
identity guard that only reads the document the wrong code pointed at. The document is internally
perfect; it just belongs to somebody else. Only ISIN catches it.

USE:
    import bse_resolve
    by_id = bse_resolve.by_id()          # bse_scrips by_id with conflicting symbols REMOVED
    code  = bse_resolve.guard(sym, code) # -> code, or None when sym is a known conflict
    bse_resolve.guard_map(m)             # filter any {SYM: code} map in place-safe fashion

Refresh the conflict list with:  python3 scripts/scan_scrip_isin_conflicts.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFLICTS_PATH = os.path.join(HERE, "bse_scrip_isin_conflicts.json")
SCRIPS_PATH = os.path.join(HERE, "bse_scrips.json")

_cache = None


def conflicts():
    """{SYMBOL: {nse_isin, bse_code, bse_isin, bse_name, note}} — symbols whose by_id/scrip_id
    match points at a DIFFERENT company. Missing/unreadable file -> {} (never crash a caller);
    the guard then degrades to a no-op, which is the pre-2026-08-10 behaviour."""
    global _cache
    if _cache is None:
        try:
            d = json.load(open(CONFLICTS_PATH, encoding="utf-8"))
            _cache = {k.upper(): v for k, v in (d.get("conflicts") or {}).items()}
        except Exception:
            _cache = {}
    return _cache


def blocked(sym):
    """Reason string when `sym` must NOT be resolved to a BSE scrip, else None."""
    e = conflicts().get(str(sym).upper())
    if not e:
        return None
    return "{} -> BSE {} is {} (ISIN {}), but {} is ISIN {}".format(
        sym, e.get("bse_code"), e.get("bse_name"), e.get("bse_isin"), sym, e.get("nse_isin")
    )


def guard(sym, code):
    """Return `code` unless `sym` is a known wrong-company mapping, in which case None."""
    return None if (code is not None and blocked(sym)) else code


def guard_map(m):
    """Copy of a {SYM: code} map with every known-conflicting symbol dropped."""
    bad = conflicts()
    return {k: v for k, v in m.items() if str(k).upper() not in bad}


def bse_key(tkr):
    """The key a BSE-only company is filed under in the results feed / payloads. Normally its BSE
    ticker; but when that ticker is ALSO an unrelated NSE company's symbol (a known conflict), the
    ticker would put one company's filing on the other's row (GSTL, MAL, SEL, RAJPUTANA, ZEAL,
    2026-09-27) — so the BSE company gets its own key, '<TICKER>-BSE'."""
    t = str(tkr or "").upper()
    return t + "-BSE" if t in conflicts() else t


# ---- §203: ONE TICKER STRING, TWO COMPANIES -----------------------------------------------------------------------
# The site lists an NSE company under its NSE symbol and a BSE-only company under its BSE scrip_id, and the two
# namespaces collide: ZEAL is Zeal Global Services on NSE (SME, INE0PPS01018) and Zeal Aqua on BSE (539963,
# INE819S01025). The conflict ledger above only ever held the pairs somebody had scanned for, and the build's own
# proof (the committed tape's ISIN) covers the main board only — no SME symbol — so a BSE scrip folded straight into
# an SME company's page (ZEAL, GSTL, MAL, SEL, RAJPUTANA) and its detail was filed under the SME company's key.
# The reverse happens too: KEL's page is Kotia Enterprises (BSE 539599) since its NSE twin Kundan Edifice stopped
# trading, but Kundan's filings were still keyed KEL. WHOSE PAGE A TICKER IS comes from the dashboard's own universe,
# docs/stock_data.bin meta: "SYM.NS" -> the NSE company; only "SYM.BO" -> the BSE company. A writer may file a
# company's data under the ticker only when ISIN proves it IS the page's company.
ROOT = os.path.dirname(HERE)
NSE_ISIN_PATHS = (
    os.path.join(HERE, "_nse_sym_isin_2020.json"),  # NSE symbol -> every ISIN since 2020 (+SME)
    os.path.join(HERE, "ideas", "nse_sme.csv"),
)  # NSE's SME_EQUITY_L (committed copy)
_ident = None


def issuer(isin):
    """The issuer part of an ISIN (first 7 chars) — a face-value change re-issues the security, not the company."""
    i = str(isin or "").strip().upper()
    return i[:7] if len(i) >= 7 else None


def identities(tape_isin=None):
    """Loaded once: {"site": {"SYM.NS"|"SYM.BO": meta}, "nse": {SYM: {ISIN}}, "bse": {TICKER: [(code, isin, name)]},
    "code_isin": {code: isin}}. tape_isin: {SYM: ISIN} from the committed tape meta when the caller already decoded
    it (build_stock_fin, fetch_bse_results_xbrl); else read here. A missing source degrades to fewer ISINs, and an
    NSE page with no ISIN on record then refuses every BSE scrip — never the reverse."""
    global _ident
    if _ident is not None:
        return _ident
    import csv
    import gzip

    site, nse, bse, code_isin = {}, {}, {}, {}
    try:
        raw = open(os.path.join(ROOT, "docs", "stock_data.bin"), "rb").read()
        site = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).get("meta") or {}
    except Exception as e:
        print(
            f"bse_resolve: docs/stock_data.bin meta unreadable ({e}) — page owners unknown, §203 guard idle"
        )
    if tape_isin is None:
        try:
            b = gzip.decompress(open(os.path.join(ROOT, "docs", "sf_stock_data.bin"), "rb").read())
            m, _ = json.JSONDecoder().raw_decode(b[b.rfind(b'"meta":') + 7 :].decode("utf-8"))
            tape_isin = {
                k: v["isin"] for k, v in m.items() if isinstance(v, dict) and v.get("isin")
            }
        except Exception:
            tape_isin = {}
    for s, i in (tape_isin or {}).items():
        nse.setdefault(s.upper(), set()).add(str(i).upper())
    try:
        for s, lst in json.load(open(NSE_ISIN_PATHS[0], encoding="utf-8")).items():
            nse.setdefault(s.upper(), set()).update(str(i).upper() for i in lst)
    except Exception:
        pass
    try:
        for r in csv.DictReader(open(NSE_ISIN_PATHS[1], encoding="utf-8", errors="replace")):
            s, i = (
                (r.get("SYMBOL") or "").strip().upper(),
                (r.get("ISIN_NUMBER") or r.get("ISIN NUMBER") or "").strip(),
            )
            if s and i:
                nse.setdefault(s, set()).add(i.upper())
    except Exception:
        pass
    for s, e in conflicts().items():
        if e.get("nse_isin"):
            nse.setdefault(s, set()).add(str(e["nse_isin"]).upper())
    try:
        d = json.load(open(SCRIPS_PATH, encoding="utf-8"))
        code_isin = {str(c): str(i).upper() for i, c in (d.get("by_isin") or {}).items()}
    except Exception:
        pass
    try:
        for r in (
            json.load(open(os.path.join(ROOT, "docs", "bse_universe.json"), encoding="utf-8")).get(
                "rows"
            )
            or []
        ):
            if len(r) > 3 and r[1]:
                bse.setdefault(str(r[1]).upper(), []).append(
                    (str(r[0]), str(r[3] or "").upper(), r[2])
                )
                if r[3]:
                    code_isin.setdefault(str(r[0]), str(r[3]).upper())
    except Exception:
        pass
    _ident = {"site": site, "nse": nse, "bse": bse, "code_isin": code_isin}
    return _ident


def page_company(sym):
    """Whose page the site's ticker `sym` is: ("nse", {issuers}) when the dashboard lists SYM.NS; ("bse", {issuers})
    when it lists only SYM.BO (the BSE scrip whose ticker is SYM); (None, set()) when it lists neither."""
    I = identities()
    s = str(sym or "").upper()
    if s + ".NS" in I["site"]:
        return "nse", {issuer(i) for i in I["nse"].get(s, ()) if issuer(i)}
    if s + ".BO" in I["site"]:
        return "bse", {issuer(i) for _, i, _ in I["bse"].get(s, ()) if issuer(i)}
    return None, set()


def bse_blocked_under(sym, isin=None, code=None):
    """Reason string when BSE scrip `code` (ISIN `isin`) must NOT be filed under the site ticker `sym`, else None:
    a recorded conflict, or `sym`'s page is an NSE company that ISIN does not prove to be this scrip (no NSE ISIN on
    record proves nothing, so it refuses too)."""
    s = str(sym or "").upper()
    bi = issuer(isin) or issuer(identities()["code_isin"].get(str(code)))
    e = conflicts().get(s)
    if e and (str(code) == str(e.get("bse_code")) or bi != issuer(e.get("nse_isin"))):
        return blocked(s)
    own, iss = page_company(s)
    if own == "nse" and (not bi or bi not in iss):
        return "{} on this site is the NSE company (ISIN issuer {}); BSE {} is {}".format(
            s, "/".join(sorted(iss)) or "none on record", code or "?", bi or "an unknown ISIN"
        )
    return None


def nse_blocked_under(sym, isin):
    """Reason string when an NSE filing of ISIN `isin` must NOT be filed under `sym` because the site's `sym` page is
    a BSE company of another issuer (its NSE twin stopped trading: KEL, DRL, INNOVATIVE, BRIGHT), else None. An
    unknown filing ISIN is never blocked here (the page owner cannot be contradicted by nothing)."""
    own, iss = page_company(sym)
    ni = issuer(isin)
    if own == "bse" and iss and ni and ni not in iss:
        return "{} on this site is the BSE company (ISIN issuer {}); this NSE filing is ISIN {}".format(
            str(sym).upper(), "/".join(sorted(iss)), isin
        )
    return None


def by_id(path=None):
    """bse_scrips.json['by_id'], ISIN-guarded. This is the call every fundamentals-feeding
    consumer should use instead of json.load(...)['by_id']."""
    d = json.load(open(path or SCRIPS_PATH, encoding="utf-8"))
    return guard_map(d.get("by_id") or {})


def by_isin(path=None):
    """bse_scrips.json['by_isin'] — ISIN -> scrip code. Always safe: ISIN is unambiguous."""
    d = json.load(open(path or SCRIPS_PATH, encoding="utf-8"))
    return dict(d.get("by_isin") or {})


if __name__ == "__main__":
    c = conflicts()
    print("known scrip_id/ISIN conflicts: %d" % len(c))
    for k in sorted(c):
        print(f"  {blocked(k)}")
    raw = json.load(open(SCRIPS_PATH, encoding="utf-8")).get("by_id") or {}
    print("by_id raw=%d  guarded=%d" % (len(raw), len(by_id())))
