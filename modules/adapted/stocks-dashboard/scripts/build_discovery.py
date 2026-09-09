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
"""Build docs/discovery.json — the auto-computed "Discovery" trigger buckets (Sovrenn-style
concept, our own automated implementation). No hand curation: every bucket is derived from
data the site already maintains:

  docs/announcements.json        -> event/trigger buckets (order wins, fund raising, M&A, ...)
  docs/sf_revop.json             -> "Excellent Results (<qtr>)" per quarter since Mar-2019 + weak results + P/E
  docs/dash_slim.bin             -> names/mcap/52w stats -> breakout / deep-correction / P/E buckets
  docs/sector_classification.json-> sector theme buckets (defence, railways, green energy, ...)

Output schema (compact):
{updated, groups:[{g, buckets:[{k,t,d,type,n,rows}]}]}
  type 'ann': rows [sym, name, count, lastDate, lastCaption, lastFile]
  type 'res': rows [sym, name, patNow, patAgo, patYoY%, revYoY%]
  type 'px' : rows [sym, name, mcapCr, lastPx, d52pct, pe|null]
  type 'sec': rows [sym, name, mcapCr, d52pct, subgroup]

Run: python -X utf8 scripts/build_discovery.py   (CI: refresh-announcements.yml, after the fetch)
"""
import datetime
import gzip
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")


def dp(f):
    return os.path.join(DOCS, f)


MCAP_FLOOR = 50.0  # cr — keep shell/illiquid names out of price & sector buckets
RES_MIN_PAT = 2.0  # cr — min current-quarter PAT for Excellent Results
FIRST_RES_QE = 20190331  # earliest results bucket

# ---------------------------------------------------------------- inputs
ann = json.load(open(dp("announcements.json"), encoding="utf-8"))
# order-value strings extracted from the order-win PDFs (enrich_order_values.py), keyed by attachment file
try:
    ORDVALS = json.load(open(dp("order_values.json"), encoding="utf-8")).get("vals", {})
except Exception:
    ORDVALS = {}
# shares outstanding for order-win names missing a market cap (enrich_order_shares.py) — mcap is
# recomputed here as shares × latest price so it stays fresh without re-fetching the XBRL
try:
    ORDSHARES = json.load(open(dp("order_shares.json"), encoding="utf-8")).get("shares", {})
except Exception:
    ORDSHARES = {}
revop = json.load(open(dp("sf_revop.json"), encoding="utf-8"))
# ★ HTML-ESCAPED PHANTOM KEYS ARE NOT INERT — THEY WERE RENDERING (2026-08-26, runbook §114).
# sf_revop still carries 13 keys an ingestion path HTML-escaped (`M&M` -> `M&AMP;M`); this page read
# them as ordinary symbols and shipped 46 rows across 21 result buckets labelled `M&AMP;M`,
# `J&AMP;KBANK`, `GVT&AMP;D` — duplicates of names already in the same bucket, with a ticker that
# links nowhere. Two memories had recorded these keys as "invisible to the site"; measuring the
# SERVED payload is what showed they were not. Dropped here rather than folded into the real symbol:
# every one of the 13 resolves to a key sf_revop already holds, so folding could only double-count.
# The keys themselves are retracted store by store (fundamentals: done; sf_revop: open).
for _s in [_k for _k in revop if html.unescape(_k) != _k]:
    revop.pop(_s)
# OWNERS-attributable PAT lives in sf_revop's mirror slots too, but the two files DISAGREE on 1,372
# of 43,731 populated con-PAT cells (measured 2026-08-09, runbook §70) and sf_fundamentals is the
# authoritative one -- stock.html: "never swap in sf_revop's PAT mirror slots". ttm_pat() below was
# reading the mirror, so the TTM P/E on this page was computed off a copy that differs from the PAT
# the site displays, on 298 cells in the 2025-26 window alone.
FUNDPAT = {}
for _s, _rows in json.load(open(dp("sf_fundamentals.json"), encoding="utf-8")).items():
    for _r in _rows:
        if len(_r) > 3:
            _v = _r[3] if _r[3] not in (None, 0) else _r[1]
            if _v is not None:
                FUNDPAT[(_s, _r[0])] = _v
slim = json.loads(gzip.decompress(open(dp("dash_slim.bin"), "rb").read()))
classif = json.load(open(dp("sector_classification.json"), encoding="utf-8"))

META = {}  # SYM -> {name, mcap, latest, d52}
for k, m in (slim.get("meta") or {}).items():
    sym = str(m.get("symbol") or k.split(".")[0]).upper()
    META[sym] = {"name": m.get("name") or sym, "mcap": m.get("mcap"), "latest": m.get("latest"), "d52": m.get("d52")}


def nameof(sym, fallback=""):
    return (META.get(sym) or {}).get("name") or fallback or sym


# ------------------------------------------- 1) announcement-driven buckets
# raw NSE `desc` -> bucket key (first match wins); mirrors the page's CATRULES philosophy
ANN_BUCKETS = [
    (
        "orders",
        "Order Wins",
        "Companies announcing new orders / contract wins in the last month.",
        re.compile(r"orders?/contracts|order\(s\)\/contract", re.IGNORECASE),
    ),
    (
        "capex",
        "Capacity & New Products",
        "Commercial production started, capacity added or new products launched.",
        re.compile(r"commercial production|capacity addition|product launch|new line", re.IGNORECASE),
    ),
    (
        "ma",
        "M&A, JVs & Partnerships",
        "Acquisitions, mergers, joint ventures, MOUs and strategic tie-ups.",
        re.compile(
            r"acquisition|amalgamation|merger|demerger|scheme of arrangement|memorandum of understanding|agreements|tie ?up",
            re.IGNORECASE,
        ),
    ),
    (
        "fund",
        "Fund Raising",
        "Preferential issues, QIPs, rights issues and other capital raises.",
        re.compile(
            r"preferential issue|qualified institution|rights issue|fccb|issue of securities|allotment of securities|fund raising|offer for sale",
            re.IGNORECASE,
        ),
    ),
    (
        "openoffer",
        "Open Offers",
        "Open offers triggered by takeovers / stake purchases.",
        re.compile(r"open offer", re.IGNORECASE),
    ),
    ("buyback", "Buybacks", "Share buyback announcements and updates.", re.compile(r"buy ?back", re.IGNORECASE)),
    (
        "reward",
        "Dividends, Bonus & Splits",
        "Dividends declared, bonus issues and stock splits.",
        re.compile(r"^dividend|bonus|stock split|sub-?division", re.IGNORECASE),
    ),
    (
        "rating",
        "Credit Rating Updates",
        "Rating upgrades, downgrades, reaffirmations and watch actions.",
        re.compile(r"credit rating", re.IGNORECASE),
    ),
    (
        "meet",
        "Investor Meets",
        "Analyst / institutional investor meets, con-calls and presentations.",
        re.compile(r"investor meet|analyst|investor presentation|con\.? call", re.IGNORECASE),
    ),
    (
        "spurt",
        "Volume & Price Spurts",
        "Exchange surveillance: unusual volume or price movement clarifications.",
        re.compile(r"spurt in volume|price movement", re.IGNORECASE),
    ),
    (
        "redflag",
        "Red Flags",
        "Insolvency, defaults, fraud, regulatory action, auditor exits, trading suspensions.",
        re.compile(
            r"insolvency|default|fraud|arrest|action\(s\)|statutory auditor|suspension of trading|penalt|one time settlement",
            re.IGNORECASE,
        ),
    ),
]


def build_ann_buckets():
    per = {k: {} for k, *_ in [(b[0],) for b in ANN_BUCKETS]}
    for r in ann.get("rows", []):
        sym, co, dt, desc, cap, f = r
        for key, _t, _d, rx in ANN_BUCKETS:
            if rx.search(desc):
                s = per[key].get(sym)
                if s is None:
                    per[key][sym] = {"n": 1, "dt": dt, "cap": cap, "f": f, "co": co}
                else:
                    s["n"] += 1
                    if dt > s["dt"]:
                        s.update(dt=dt, cap=cap, f=f)
                break
    out = []
    for key, t, d, _rx in ANN_BUCKETS:
        if key == "orders":
            out.append(build_orders_bucket(per["orders"], t))
            continue
        rows = [
            [
                sym,
                nameof(sym, s["co"]),
                s["n"],
                s["dt"][:10],
                (s["cap"][:179] + "…") if len(s["cap"]) > 180 else s["cap"],
                s["f"],
            ]
            for sym, s in per[key].items()
        ]
        rows.sort(key=lambda x: x[3], reverse=True)
        out.append({"k": key, "t": t, "d": d, "type": "ann", "n": len(rows), "rows": rows})
    return out


# The Order Wins bucket gets its own richer layout (like the reference sites): market cap, TTM P/E,
# date, and a remark stating the order value and how many times the company's trailing-12-month
# sales it represents. type 'ord' rows: [sym, name, mcap|null, pe|null, date, remark, file]
def _ordval(f):
    v = ORDVALS.get(f)
    if isinstance(v, dict):
        return v.get("t"), v.get("cr")  # {"t":display,"cr":₹crore}
    return (v, None) if v else (None, None)  # legacy string / "" / missing


def build_orders_bucket(per, t):
    rows = []
    for sym, s in per.items():
        m = META.get(sym) or {}
        mc = round(m["mcap"], 1) if m.get("mcap") else None
        if mc is None and ORDSHARES.get(sym):  # computed fallback mcap = shares × price
            sh = ORDSHARES[sym]
            shares, cpx = (sh.get("sh"), sh.get("px")) if isinstance(sh, dict) else (sh, None)
            px = m.get("latest") or cpx  # our price, else the cached (Yahoo) one
            if shares and px:
                cand = round(shares * px / 1e7, 1)
                if cand >= 5:
                    mc = cand  # guard bad share-count parses (< ₹5 cr is implausible)
        tp = ttm_pat(sym)
        pe = round(mc / tp, 1) if (mc and tp and tp > 0) else None
        disp, cr = _ordval(s["f"])
        rev = ttm_rev(sym)
        if disp:
            remark = disp + " order"
            if cr and rev:
                ratio = cr / rev
                remark += " · " + (
                    f"{ratio:.1f}× annual sales"
                    if ratio >= 1
                    else ("%d%% of annual sales" % round(ratio * 100) if ratio >= 0.01 else "<1% of annual sales")
                )
        else:
            cap = s["cap"] or ""
            remark = (
                "Order received"
                if ("informed the exchange" in cap.lower() or not cap)
                else ((cap[:179] + "…") if len(cap) > 180 else cap)
            )
        rows.append([sym, nameof(sym, s["co"]), mc, pe, s["dt"][:10], remark, s["f"], cr])
    rows.sort(key=lambda x: x[4], reverse=True)
    return {
        "k": "orders",
        "t": t,
        "type": "ord",
        "n": len(rows),
        "rows": rows,
        "d": "New order wins in the last month — order value and how many times the company's "
        "trailing-12-month sales it represents (with market cap & TTM P/E).",
    }


# ------------------------------------------- 2) results buckets (computed, per quarter)
def prev_qe(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return {3: (y - 1) * 10000 + 331, 6: y * 10000 + 331, 9: y * 10000 + 630, 12: y * 10000 + 930}[m]  # unused


def yoy_qe(qe):
    return qe - 10000


def pick(cell, i_con, i_std):
    if not cell:
        return None
    v = cell[i_con]
    if v is None or v == 0:
        v = cell[i_std]
    return v


QLBL = {3: "Mar", 6: "Jun", 9: "Sep", 12: "Dec"}


def qlabel(qe):
    return "%s-%02d" % (QLBL[(qe // 100) % 100], (qe // 10000) % 100)


def build_results_buckets():
    qes = set()
    for qmap in revop.values():
        for q in qmap:
            qes.add(int(q))
    qes = sorted((q for q in qes if q >= FIRST_RES_QE), reverse=True)
    buckets, weak_by_qe = [], {}
    for qe in qes:
        rows, weak = [], []
        base = str(yoy_qe(qe))
        for sym, qmap in revop.items():
            cur, ago = qmap.get(str(qe)) or qmap.get(qe), qmap.get(base) or qmap.get(yoy_qe(qe))
            if not cur or not ago:
                continue
            pat, patA = pick(cur, 5, 4), pick(ago, 5, 4)
            rev, revA = pick(cur, 1, 0), pick(ago, 1, 0)
            # NEGATIVE year-ago base is NOT an edge case — 22% of all PAT YoY cells. Use Trendlyne's
            # (and our backtest's) rule: (cur - base)/ABS(base), so a LOSS->PROFIT turnaround reads
            # POSITIVE and lands in Excellent Results instead of being skipped. The old `patA <= 0:
            # continue` dropped every one of them from the bucket they most belong in (BHEL Q1FY27:
            # -455.5 -> +376.71 = +182.7%, exactly TL's figure). Dividing straight through would
            # SIGN-FLIP it to -182.7% and file it under Weak — never do that. base == 0 skipped (÷0).
            if pat is None or patA is None or patA == 0:
                continue
            patY = (pat - patA) / abs(patA) * 100
            revY = (rev - revA) / abs(revA) * 100 if (rev is not None and revA) else None
            if pat >= RES_MIN_PAT and patY >= 25 and (revY is None or revY >= 10) and (revY is not None or patY >= 40):
                rows.append(
                    [
                        sym,
                        nameof(sym),
                        round(pat, 1),
                        round(patA, 1),
                        round(patY, 1),
                        round(revY, 1) if revY is not None else None,
                    ]
                )
            elif patY <= -30 or pat < 0:
                weak.append(
                    [
                        sym,
                        nameof(sym),
                        round(pat, 1),
                        round(patA, 1),
                        round(patY, 1),
                        round(revY, 1) if revY is not None else None,
                    ]
                )
        rows.sort(key=lambda x: -x[4])
        if len(rows) >= 5:
            buckets.append(
                {
                    "k": "res%d" % qe,
                    "t": f"Excellent Results ({qlabel(qe)})",
                    "d": "PAT up ≥25% YoY (with revenue support), incl. loss→profit turnarounds — computed from filings, not hand-picked.",
                    "type": "res",
                    "n": len(rows),
                    "rows": rows,
                }
            )
        weak_by_qe[qe] = weak
    # Weak Results: attach to the newest quarter with real coverage (early in a season the
    # latest quarter has only a handful of filings)
    for qe in qes:
        weak = weak_by_qe.get(qe) or []
        if len(weak) >= 30:
            weak.sort(key=lambda x: x[4])
            buckets.insert(
                1 if buckets else 0,
                {
                    "k": "weak%d" % qe,
                    "t": f"Weak Results ({qlabel(qe)})",
                    "d": "PAT down ≥30% YoY, or loss-making this quarter.",
                    "type": "res",
                    "n": len(weak),
                    "rows": weak,
                },
            )
            break
    return buckets


# TTM PAT for P/E (needs the 4 most recent consecutive quarters present)
def ttm_pat(sym):
    qmap = revop.get(sym)
    if not qmap:
        return None
    qes = sorted(int(q) for q in qmap)
    if len(qes) < 4:
        return None
    last4 = qes[-4:]
    today = int(datetime.date.today().strftime("%Y%m%d"))
    if last4[-1] < today - 10000 + 3000:
        return None  # latest quarter older than ~9 months -> stale
    tot = 0.0
    for q in last4:
        # authoritative first; the revop mirror only when sf_fundamentals has nothing for the cell
        v = FUNDPAT.get((sym, q))
        if v is None:
            v = pick(qmap[str(q)] if str(q) in qmap else qmap[q], 5, 4)
        if v is None:
            return None
        tot += v
    return tot


# TTM revenue (trailing 4 quarters) — denominator for the "N× annual sales" order comparison
def ttm_rev(sym):
    qmap = revop.get(sym)
    if not qmap:
        return None
    qes = sorted(int(q) for q in qmap)
    if len(qes) < 4:
        return None
    last4 = qes[-4:]
    today = int(datetime.date.today().strftime("%Y%m%d"))
    if last4[-1] < today - 10000 + 3000:
        return None  # latest quarter older than ~9 months -> stale
    tot = 0.0
    for q in last4:
        v = pick(qmap[str(q)] if str(q) in qmap else qmap[q], 1, 0)
        if v is None or v < 0:
            return None
        tot += v
    return tot if tot > 0 else None


# ------------------------------------------- 3) price buckets (from slim meta)
def build_price_buckets():
    hi, corr, cheap = [], [], []
    for sym, m in META.items():
        mc, d52, px = m.get("mcap"), m.get("d52"), m.get("latest")
        if not mc or mc < MCAP_FLOOR or d52 is None or px is None:
            continue
        if d52 >= -2:
            hi.append([sym, m["name"], round(mc, 1), px, round(d52, 1), None])
        if d52 <= -30:
            corr.append([sym, m["name"], round(mc, 1), px, round(d52, 1), None])
        t = ttm_pat(sym)
        if t and t > 0:
            pe = mc / t
            if pe < 30:
                cheap.append([sym, m["name"], round(mc, 1), px, round(d52, 1), round(pe, 1)])
    hi.sort(key=lambda x: -x[2])
    corr.sort(key=lambda x: x[4])
    cheap.sort(key=lambda x: x[5])
    hi, corr, cheap = hi[:500], corr[:500], cheap[:500]
    return [
        {
            "k": "hi52",
            "t": "Near 52-Week High",
            "d": "Trading within 2% of the 52-week high — breakout zone (mcap ≥ ₹50 cr).",
            "type": "px",
            "n": len(hi),
            "rows": hi,
        },
        {
            "k": "corr",
            "t": "30%+ Off the High",
            "d": "Corrected 30% or more from the 52-week high (mcap ≥ ₹50 cr, 500 worst shown).",
            "type": "px",
            "n": len(corr),
            "rows": corr,
        },
        {
            "k": "pe30",
            "t": "P/E Under 30",
            "d": "Market cap under 30× trailing-12-month PAT (profitable, recent filings; 500 cheapest shown).",
            "type": "px",
            "n": len(cheap),
            "rows": cheap,
        },
    ]


# ------------------------------------------- 4) sector theme buckets
# Themes cut ACROSS the exchange taxonomy (Suzlon=Heavy Electrical, RVNL=Civil Construction,
# IREDA=Finance) so pure regex misses them — each theme = taxonomy regex OR a hand-seeded
# symbol list (edit SEEDS below to grow a theme).
THEMES = [
    (
        "defence",
        "Defence & Aerospace",
        r"defence|defense|aerospace",
        "HAL BEL BDL MAZDOCK COCHINSHIP GRSE MIDHANI DATAPATTNS ASTRAMICRO PARAS ZENTEC SOLARINDS DYNAMATECH IDEAFORGE UNIMECH TANEJAERO",
    ),
    (
        "rail",
        "Railways",
        r"railway",
        "RVNL IRCON RITES IRFC IRCTC RAILTEL TITAGARH TEXRAIL JWL BEML CONCOR RKFORGE RAMKY HINDCON OSWALAGRO",
    ),
    (
        "green",
        "Green Energy",
        r"$^",  # no taxonomy bucket — seeds only
        "SUZLON INOXWIND IWEL ADANIGREEN TATAPOWER NHPC SJVN ACMESOLAR PREMIERENE WAAREEENER SWSOLAR IREDA KPIGREEN KPEL WEBSOL SOLARA ZODIACLOTH UJAAS ORIANA INSOLATION GANESHBE BORORENEW SWELECTES ADVAIT",
    ),
    (
        "ev",
        "Auto & Components",
        r"auto components|auto ancillar|2/3 wheelers|passenger cars|commercial vehicles|tyres",
        "",
    ),
    ("hosp", "Hospitals & Diagnostics", r"hospital|diagnostic|healthcare service", ""),
    ("hotel", "Hotels & Travel", r"hotel|resort|tour|travel|airline|aviation", ""),
    ("it", "IT Services & Software", r"software|it enabled|computers - |internet & catalogue", ""),
    ("realty", "Realty & Building", r"realty|residential|commercial projects|cement|building products", ""),
    ("logi", "Shipping & Logistics", r"shipping|logistics|\bport\b|marine", ""),
    (
        "pharma",
        "Pharma & Chemicals",
        r"pharmaceutical|specialty chemical|agrochemical|petrochem|commodity chemical",
        "",
    ),
    (
        "capgoods",
        "Capital Goods",
        r"industrial products|heavy electrical|industrial machinery|capital goods|engineering",
        "",
    ),
    (
        "ems",
        "Electronics & EMS",
        r"consumer electronics|electronic components",
        "DIXON KAYNES SYRMA AMBER AVALON CYIENTDLM PGEL DCX CENTUM ELIN EPACK SAHASRA MOSCHIP",
    ),
]


def build_sector_buckets():
    out = []
    for key, t, rx_s, seeds_s in THEMES:
        rx, seeds = re.compile(rx_s, re.IGNORECASE), set(seeds_s.split())
        rows = []
        for k, c in classif.items():
            sym = k.split(".")[0].upper()
            m = META.get(sym)
            if not m or not m.get("mcap") or m["mcap"] < MCAP_FLOOR:
                continue
            blob = " ".join(str(c.get(f) or "") for f in ("igroup", "industry", "subgroup"))
            if sym in seeds or rx.search(blob):
                rows.append([sym, m["name"], round(m["mcap"], 1), round(m.get("d52") or 0, 1), c.get("subgroup") or ""])
        # seeded symbols with no classification entry still belong in the theme
        for sym in seeds:
            m = META.get(sym)
            if m and m.get("mcap") and m["mcap"] >= MCAP_FLOOR and not any(r[0] == sym for r in rows):
                rows.append([sym, m["name"], round(m["mcap"], 1), round(m.get("d52") or 0, 1), ""])
        rows.sort(key=lambda x: -x[2])
        rows = rows[:80]
        out.append(
            {
                "k": key,
                "t": t,
                "d": "Listed companies in this theme (mcap ≥ ₹50 cr), largest first.",
                "type": "sec",
                "n": len(rows),
                "rows": rows,
            }
        )
    return out


def build_deal_buckets():
    """Smart-money buckets from docs/deals.json (fetch_deals.py, refresh-deals.yml).
    type 'deal' rows: [sym, name, netCr, buyCr, distinctBuyers, lastDate, topBuyer].
    The feed may not exist yet on a fresh checkout — return [] and the group is skipped."""
    try:
        deals = json.load(open(dp("deals.json"), encoding="utf-8"))
        drows, dto = deals.get("rows") or [], deals.get("to")
        end = datetime.date.fromisoformat(dto)
    except Exception:
        return []
    out = []
    for key, days, minbuy in (("deal7", 7, 5.0), ("deal30", 30, 5.0)):
        lo = (end - datetime.timedelta(days=days - 1)).isoformat()
        agg = {}
        for r in drows:
            if r[0] < lo:
                continue
            a = agg.setdefault(r[2], {"name": r[3], "buy": 0.0, "sell": 0.0, "buyers": {}, "last": ""})
            v = r[6] * r[7] / 1e7
            if r[5] == "B":
                a["buy"] += v
                c = r[4].upper()
                a["buyers"][c] = a["buyers"].get(c, 0.0) + v
            else:
                a["sell"] += v
            a["last"] = max(a["last"], r[0])
        rows = []
        for sym, a in agg.items():
            if a["buy"] < minbuy:
                continue
            m = META.get(sym)
            top = max(a["buyers"], key=a["buyers"].get) if a["buyers"] else ""
            rows.append(
                [
                    sym,
                    (m or {}).get("name") or a["name"],
                    round(a["buy"] - a["sell"], 2),
                    round(a["buy"], 2),
                    len(a["buyers"]),
                    a["last"],
                    top.title(),
                ]
            )
        rows.sort(key=lambda x: -x[2])
        rows = rows[:100]
        out.append(
            {
                "k": key,
                "t": "Bulk/block buying (last %dd)" % days,
                "d": "Stocks where big investors bought ≥₹%d cr via NSE bulk or block deals in the last %d days. Net = disclosed buys − sells; largest net buying first."
                % (int(minbuy), days),
                "type": "deal",
                "n": len(rows),
                "rows": rows,
            }
        )
    return [b for b in out if b["n"]]


def build_insider_buckets():
    """Promoter-buying bucket from docs/insider.json (fetch_insider.py, refresh-insider.yml).
    Reuses the 'deal' row type: [sym, name, netCr, buyCr, people, lastDate, topPerson].
    Market purchases/sales by Promoters only (cat P, mode MP/MS) — ESOP, gifts, off-market
    inter-se transfers etc. are excluded so the signal stays clean."""
    try:
        ins = json.load(open(dp("insider.json"), encoding="utf-8"))
        irows, ito = ins.get("rows") or [], ins.get("to")
        end = datetime.date.fromisoformat(ito)
    except Exception:
        return []
    out = []
    for key, days, minbuy in (("pit30", 30, 0.25),):
        lo = (end - datetime.timedelta(days=days - 1)).isoformat()
        agg = {}
        for r in irows:
            if r[0] < lo or r[4] != "P" or r[8] not in ("MP", "MS"):
                continue
            a = agg.setdefault(r[1], {"name": r[2], "buy": 0.0, "sell": 0.0, "ppl": {}, "last": ""})
            v = (r[7] or 0) / 1e7
            if r[8] == "MP":
                a["buy"] += v
                p = r[3].upper()
                a["ppl"][p] = a["ppl"].get(p, 0.0) + v
            else:
                a["sell"] += v
            a["last"] = max(a["last"], r[0])
        rows = []
        for sym, a in agg.items():
            if a["buy"] < minbuy:
                continue
            m = META.get(sym)
            top = max(a["ppl"], key=a["ppl"].get) if a["ppl"] else ""
            rows.append(
                [
                    sym,
                    (m or {}).get("name") or a["name"],
                    round(a["buy"] - a["sell"], 2),
                    round(a["buy"], 2),
                    len(a["ppl"]),
                    a["last"],
                    top.title(),
                ]
            )
        rows.sort(key=lambda x: -x[2])
        rows = rows[:150]
        out.append(
            {
                "k": key,
                "t": "Promoters buying (last %dd)" % days,
                "d": "Stocks whose PROMOTERS bought ≥₹25 lakh of their own shares on the market in the last %d days (SEBI PIT Reg 7(2) disclosures). Net = promoter market buys − sells. Promoter buying is one of the strongest conviction signals."
                % days,
                "type": "deal",
                "n": len(rows),
                "rows": rows,
            }
        )
    return [b for b in out if b["n"]]


def build_spike_buckets():
    """Delivery-spike bucket from docs/delivery.json (fetch_delivery.py, refresh-delivery.yml).
    type 'spike' rows: [sym, name, spikeCount, totDelivCr, bestMult, lastDate]."""
    try:
        dl = json.load(open(dp("delivery.json"), encoding="utf-8"))
        sp = dl.get("spikes") or []
    except Exception:
        return []
    sess = sorted({r[0] for r in sp}, reverse=True)[:5]
    if not sess:
        return []
    lo = sess[-1]
    agg = {}
    for r in sp:
        if r[0] < lo:
            continue
        a = agg.setdefault(r[1], {"name": r[2], "n": 0, "cr": 0.0, "best": 0.0, "last": 0})
        a["n"] += 1
        a["cr"] += r[5]
        a["best"] = max(a["best"], r[8])
        a["last"] = max(a["last"], r[0])

    def fmt(ymd):
        return "%04d-%02d-%02d" % (ymd // 10000, ymd // 100 % 100, ymd % 100)

    rows = [[s, a["name"], a["n"], round(a["cr"], 1), a["best"], fmt(a["last"])] for s, a in agg.items()]
    rows.sort(key=lambda x: (-x[2], -x[3]))
    rows = rows[:100]
    return (
        [
            {
                "k": "spike5",
                "t": "Delivery spikes (last 5 sessions)",
                "d": "Stocks whose DELIVERED quantity jumped to ≥3× their own 20-session baseline with delivery ≥30%, ≥₹1 cr delivered and price up — repeated spikes suggest steady accumulation. Full detail on the Delivery Spikes page.",
                "type": "spike",
                "n": len(rows),
                "rows": rows,
            }
        ]
        if rows
        else []
    )


# ---------------------------------------------------------------- assemble
def main():
    res = build_results_buckets()
    [b for b in res if not b["k"].startswith("res") or (res and b["k"] == res[0]["k"])]
    deal = build_insider_buckets() + build_deal_buckets() + build_spike_buckets()
    groups = (
        [
            {"g": "Triggers (last 31 days)", "buckets": build_ann_buckets()},
        ]
        + ([{"g": "Smart money", "buckets": deal}] if deal else [])
        + [
            {"g": "Price & Value", "buckets": build_price_buckets()},
            {"g": "Results — computed from filings", "buckets": res[:3]},
            {"g": "Results history", "buckets": res[3:]},
            {"g": "Sector themes", "buckets": build_sector_buckets()},
        ]
    )
    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "groups": groups}
    json.dump(out, open(dp("discovery.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    nb = sum(len(g["buckets"]) for g in groups)
    print(
        "WROTE docs/discovery.json: %d groups, %d buckets, %.2f MB"
        % (len(groups), nb, os.path.getsize(dp("discovery.json")) / 1e6)
    )
    for g in groups:
        for b in g["buckets"][:50]:
            print("  %-28s %-34s %5d" % (g["g"][:28], b["t"][:34], b["n"]))


if __name__ == "__main__":
    main()
