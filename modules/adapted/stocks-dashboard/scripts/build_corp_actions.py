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
"""Fetch NSE's OFFICIAL split/bonus ratios and write scripts/corp_actions.json
({SYMBOL: [[exYmd, factor], ...]}). The price builds (build_sf_data / update_sf_data)
apply these EXACT factors on each ex-date instead of inferring the factor from the
overnight price drop — which silently breaks whenever a stock moves on the ex-date
(e.g. Adani Power's 1:5 split read as 1:4 after a +20% ex-date pop) or when a small
bonus (1:4 / 1:5 / 1:10) only dips the price <25% and gets ignored entirely.

Cheap (≈9 API calls) — safe to run daily before update_sf_data.py.
Run: python -X utf8 build_corp_actions.py
"""
import datetime
import json
import os
import re

import build_fundamentals as F

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "corp_actions.json")


# A demerger / scheme of arrangement is NOT a split: real value leaves the stock (it goes to the
# spun-off entity), so the ex-date price drop must NOT be divided out. We only need its ex-date to
# tell the price build "do not treat this drop as a split". (Vedanta 2026-04-30, Raymond, Siemens.)
DEMERGER_KW = (
    "demerger",
    "de-merger",
    "scheme of arrangement",
    "scheme of amalgamation",
    "spin off",
    "spin-off",
    "composite scheme",
    "reduction of capital",
    "capital reduction",
)


def is_demerger(subj):
    s = (subj or "").lower()
    return any(k in s for k in DEMERGER_KW)


# Hardcoded FALSE corporate-action detections that are NOT in NSE's corporate-actions feed: a market
# crash whose overnight drop ca_factor mis-reads as a split/bonus, so the build divides it out and
# (after re-anchoring) mis-scales the pre-crash history. NSE never lists these (they aren't real
# actions), so without this they'd be lost on every daily regeneration. Merged into `noadjust` =
# "keep the drop as a genuine move, do NOT divide it out".
#   ADANIENT  2023-02-01/02 — Hindenburg crash + FPO withdrawal (2/3 x 3/4 = 1/2 false halving)
#   ADANIPOWER 2020-03-12   — COVID crash mis-read as 3:4
# Market crashes / corrections whose overnight drop the build mis-reads as a split/bonus. Per the rule
# "a big fall with NO corporate announcement is a crash, not a CA": each below was verified to have no
# split/bonus/rights announcement on the date (NSE corporate-actions). Found via scripts/_audit_fullscan.py
# (full-universe scan) + scripts/_anncheck.py (announcement check). Real splits/rights are NOT listed here
# (they stay adjusted). 2026-06-23.
MANUAL_NOADJUST = {
    "ADANIENT": [20230201, 20230202],  # Hindenburg + FPO withdrawal
    "ADANIPOWER": [20200312],  # COVID crash
    # --- COVID-19 crash, Mar-2020 (market-wide, no corporate action) ---
    "IDEA": [20200318],
    "ASHOKLEY": [20200319],
    "AXISBANK": [20200323],
    "BAJAJFINSV": [20200323],
    "BANDHANBNK": [20200323],
    "CHOLAFIN": [20200323],
    "EQUITAS": [20200323],
    "M&MFIN": [20200323],
    "MFSL": [20200323],
    # --- news-driven crashes (no corporate action) ---
    "ZEEL": [20240123],  # Sony merger called off
    "RECLTD": [20240604],  # 4-Jun-2024 election-result crash
    "INDUSINDBK": [20250311],  # derivatives-accounting disclosure
    "PAYTM": [20211118, 20211119],  # IPO listing-day crash
    "IEX": [20250724],  # CERC market-coupling order
    # 2026-08-03 full-series audit: crashes mis-baked as splits (see update_sf_data LEGACY_FALSE_CA)
    "SAMMAANCAP": [20190930, 20200319],
    "YESBANK": [20190430],
    "ZEEL": [20190125],
    "DISHTV": [20190125],
    "RELINFRA": [20190206, 20190207],
    # --- IPO listing-day pops mis-read as reverse-splits (keep the real move) ---
    "ROUTE": [20200921],
    "INDIGOPNTS": [20210202],
    "MTARTECH": [20210315],
    "GRINFRA": [20210719],
    "NYKAA": [20211110],
    "IREDA": [20231129],
    "PREMIERENE": [20240903],
}
# Auto-discovered crashes appended weekly by scripts/audit_phantom_ca.py (same rule: a big fall with no
# corporate announcement = a crash -> noadjust). Merged additively; a missing/empty file is safe.
try:
    _pc = json.load(open(os.path.join(HERE, "phantom_crashes.json")))
    for _s, _ds in _pc.items():
        MANUAL_NOADJUST.setdefault(_s, [])
        for _d in _ds:
            if int(_d) not in MANUAL_NOADJUST[_s]:
                MANUAL_NOADJUST[_s].append(int(_d))
except Exception:
    pass


def official_factor(subj):
    """Return (price_factor, label) for a split/bonus subject, else (None, None).
    Split: face value Rs X -> Rs Y  => factor Y/X.   Bonus B:A (B new per A held) => A/(A+B)."""
    s = (subj or "").lower()
    # A bonus/split of a DIFFERENT instrument class is not an equity price factor: preference
    # shares (TVSHLTD "Bonus Ncrps 1:116"), DVRs ("Bonus 1 Dvr : 10 Eq"), debentures. Never
    # multiply these in (2026-08-11 campaign; previously only the numeric gate excluded them).
    # "Sch Of Agmt- Bonus Deb1:1" (BRITANNIA 2010-03-08, ASTRAZEN 2008-01-04) is a bonus DEBENTURE
    # issue, not an equity bonus — the tape's open proves no basis change (open-gap 1.84-1.92).
    # ncd/ccps added 2026-08-30 (StockView R5 F-07 hardening): zero live instances today
    # (42,612 feed rows swept, 14 class-bonus rows — all ncrps/dvr/debenture/preference,
    # every one factor-free in our store), but a future "Bonus NCD 1:1" / CCPS bonus must
    # be excluded by the same class rule, not by luck.
    if re.search(r"\bncrps\b|\bdvr\b|preference|debenture|\bdeb\s*\d+\s*:|\bncd\b|ccps", s):
        return (None, None)
    factor = 1.0
    parts = []
    # A single NSE subject can carry a bonus AND a split together ("Bonus 1:1/Face Value Split - From
    # Rs 10 To Re 1") -> the price factor is their PRODUCT. The old code returned on the FIRST match and
    # dropped the other leg, so combined bonus+split lines were under-recorded (SUNILHITEC 0.1 not 0.05,
    # HINDCOMPOS 0.5 not 0.333), which then disagreed with the correctly-combined price data and got
    # reverted by self_heal. Also: NSE writes the currency as "Rs" for >Re.1 but "Re" for exactly Re.1,
    # so accept BOTH (the rs-only regex silently dropped every split down to Re.1, e.g. GAEL Rs2->Re1).
    # NSE also files abbreviated subjects ("Fv Splt Frm Rs 10 To Rs 2") — accept frm/splt variants
    # era abbreviations run the words together: "Rs10tors2" / "Rs10tore1" / "Rs.5tors.2".
    sx = re.sub(r"tor([se])", r" to r\1", s)
    m = re.search(r"f(?:ro|r)m\s*(?:r[se]\.?\s*)?([\d.]+).*?to\s*(?:r[se]\.?\s*)?([\d.]+)", sx)
    # pre-2016 era format has NO "From" word at all: "Fv Split Rs.10/- To Rs.2/" (66x in the
    # 2006-2015 feed), even "Split-Rs.10toRs.2". Fall back to a bare Rs-to-Rs pattern
    # (second "Rs" optional — ALLCARGO files "Fv Spl-Rs10to2").
    if not m:
        m = re.search(r"r[se]\.?\s*([\d.]+)\s*/?-?\s*to\s*(?:r[se]\.?\s*)?([\d.]+)", sx)
    # ...and the currency can be missing entirely — CYIENT 2006 "Fv Spl-10 To 5 / Bon 1:2".
    # Anchored on the split keyword itself so a bare "X to Y" elsewhere in the subject
    # (a dividend clause) can never be read as a face-value change.
    if not m:
        m = re.search(r"spl[t]?[\s\-.]*(?:r[se]\.?\s*)?([\d.]+)\s*/?-?\s*to\s*(?:r[se]\.?\s*)?([\d.]+)", sx)
    # ...and a THIRD spelling of the keyword: "Spl" (23 events 2005-2010 — UNITECH 2006-06-23
    # "Fv Spl-Rs10tors2/Bon-12:1", VEDL/RAMCOCEM/ENGINERSIN/STLTECH...). Accept it ONLY in the
    # face-value sense — "spl" adjacent to an Rs amount — never the SPECIAL-DIVIDEND sense
    # ("Spl Dividend @120%", "Div Fin-30% + Spl-50%"), which is 77 of the 100 "spl" subjects.
    spl_fv = bool(re.search(r"spl[\s\-.]*(?:r[se]\.?\s*)?[\d.]+\s*/?-?\s*to", sx)) and not re.search(
        r"spl[\s\-.]*div", sx
    )
    if m and (
        "split" in s or "splt" in s or spl_fv or "sub-division" in s or "sub division" in s or "subdivision" in s
    ):
        x, y = float(m.group(1)), float(m.group(2))
        if x and 0 < y < x:
            factor *= y / x
            parts.append(f"split FV {m.group(1)}->{m.group(2)}")
    m = re.search(r"bonus[^0-9]*(\d+)\s*:\s*(\d+)", s)
    # "Bon-12:1" / "Bon 1:2" — the same era abbreviation (21 events; UNITECH, VEDL, RAMCOCEM,
    # NIITLTD, CYIENT...). \bbon\b never matches "bond" (8 subjects, none carrying a ratio),
    # and the DVR guard above already rejects "Bon 1dvr:10eq".
    if not m:
        m = re.search(r"\bbon\b[^0-9]{0,3}(\d+)\s*:\s*(\d+)", s)
    if m:
        b, a = int(m.group(1)), int(m.group(2))
        if a + b and b <= 50 and a <= 250:  # ignore absurd parses (stray digits)
            factor *= a / (a + b)
            parts.append("bonus %d:%d" % (b, a))
    return (factor, " + ".join(parts)) if parts else (None, None)


def fetch():
    jar = F.nse_jar()
    h = {"User-Agent": F.UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
    cmap = {}
    demap = {}
    for yr in range(2016, datetime.date.today().year + 1):
        url = (
            "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
            "&from_date=01-01-%d&to_date=31-12-%d" % (yr, yr)
        )
        try:
            d = json.loads(F._get(url, headers=h, jar=jar, timeout=40))
            rows = d if isinstance(d, list) else d.get("data", [])
        except Exception as e:
            print("  %d: fetch failed (%s)" % (yr, str(e)[:40]))
            continue
        n = dm = 0
        for r in rows:
            subj = r.get("subject") or r.get("purpose") or ""
            ex = F.iso(r.get("exDate"))
            if not ex:
                continue
            f, _ = official_factor(subj)
            # gate was 0.05 < f < 0.95: a combined "Bonus 1:1 + FV split 10->1" computes to
            # EXACTLY 0.05 and was silently dropped (SUNILHITEC 2016-12-01 — the very case the
            # combined parser was built for), and small bonuses like 1:26 (0.963, INFINITE
            # 2017-11-01) fell off the top. Real combined events go as low as 1/23 x 1/10.
            if f and 0.002 < f < 0.98:
                dd = cmap.setdefault(r.get("symbol"), {})  # combine same-day actions (e.g. BAJFINANCE
                dd[int(ex)] = round(dd.get(int(ex), 1.0) * f, 6)
                n += 1  # 1:2 split x 4:1 bonus = 0.10
            elif is_demerger(subj):
                demap.setdefault(r.get("symbol"), set()).add(int(ex))
                dm += 1
        print("  %d: %d split/bonus, %d demerger/scheme events" % (yr, n, dm))
    return cmap, demap


def main():
    cmap, demap = fetch()
    # PRE-2016 HISTORY (2026-08-11 campaign): the API loop above starts at 2016. Verified
    # split/bonus factors and demerger/scheme keep-drop dates for 1999-2015 live in the TRACKED
    # ledger scripts/corp_actions_hist.json (built once from the same NSE feed + BSE/Yahoo
    # verification — see DATA_RUNBOOK); merge it here so daily regeneration never loses them.
    try:
        _h = json.load(open(os.path.join(HERE, "corp_actions_hist.json")))
        for sym, evs in _h.get("factors", {}).items():
            dd = cmap.setdefault(sym, {})
            for ex, f in evs:
                dd.setdefault(int(ex), f)
        for sym, exs in _h.get("noadjust", {}).items():
            demap.setdefault(sym, set()).update(int(e) for e in exs)
        print(
            "Merged corp_actions_hist.json: %d factor symbols, %d noadjust symbols"
            % (len(_h.get("factors", {})), len(_h.get("noadjust", {})))
        )
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  (corp_actions_hist.json unreadable: {e})")
    # HAND-VERIFIED FEED MIS-KEYS (2026-08-11, RUNBOOK §89e): NSE's CA feed itself can file an
    # action under a sister company's symbol. "Bonus 1:2 ex 2021-08-05" is served with
    # symbol=DVL/"Dhunseri Ventures", but the ex-drop is on DTIL's tape (Dhunseri Tea,
    # 521.15->346.65 = x0.665) while DVL moved -6.5%; Yahoo records the 3:2 split on DTIL.NS and
    # none ever on DVL, and DVL's equity capital is unchanged across 2021. Refetching re-imports
    # the wrong row every run, so re-key it here. {(feed_sym, ex): true_sym} — factor moved whole.
    MISKEYED = {("DVL", 20210805): "DTIL"}
    for (ws, ex), rs in MISKEYED.items():
        f = (cmap.get(ws) or {}).pop(ex, None)
        if f is not None:
            cmap.setdefault(rs, {})[ex] = f
            if not cmap.get(ws):
                cmap.pop(ws, None)
            print("  MISKEYED feed row re-keyed: %s ex %d f=%s -> %s" % (ws, ex, f, rs))
    # Merge the hardcoded/auto-detected false-CA (crash) overrides so they survive this daily
    # regeneration (NSE's feed doesn't list market crashes, so they'd vanish otherwise). BUT a
    # crash-flag on a date that ALSO carries an official split/bonus is a FALSE POSITIVE: the big
    # single-day drop is the corporate action, not a crash. Skip those, else self_heal would reverse
    # the correct split adjustment as keep-drop (e.g. SUNILHITEC/HINDCOMPOS/DVL — bonus+split to Re.1
    # that the crash detector mis-read as ~95% falls). Genuine demergers from NSE (is_demerger, already
    # in demap) are untouched and still keep their drop even if they also carry a bonus.
    for sym, exs in MANUAL_NOADJUST.items():
        split_dates = {int(k) for k in cmap.get(sym, {})}
        demap.setdefault(sym, set()).update(e for e in exs if int(e) not in split_dates)
    out = {
        "factors": {sym: sorted([k, v] for k, v in d.items()) for sym, d in cmap.items()},
        "noadjust": {sym: sorted(s) for sym, s in demap.items()},
    }
    tmp = OUT + ".tmp"
    json.dump(out, open(tmp, "w"))
    os.replace(tmp, OUT)
    print(
        "Wrote %s: %d split/bonus symbols (%d events), %d demerger/scheme symbols (%d ex-dates)"
        % (
            OUT,
            len(out["factors"]),
            sum(len(v) for v in out["factors"].values()),
            len(out["noadjust"]),
            sum(len(v) for v in out["noadjust"].values()),
        )
    )


if __name__ == "__main__":
    main()
