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


"""Turn the three price panels (daily spot, monthly WPI, monthly HS trade unit prices) into commodity SIGNALS mapped to
listed Indian beneficiaries and sufferers, via docs/ideas/commodity_map.json. This is the file the daily research run reads
first and the Commodity Watch page shows at the top. Usage: python3 scripts/ideas/signals.py -> docs/ideas/signals.json
"""
import csv
import datetime
import gzip
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ist

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs", "ideas")
TON_UNITS = {"TON", "TNE", "MTS"}


def load(fn):
    p = os.path.join(DOCS, fn)
    if os.path.exists(p + ".gz"):
        return json.load(gzip.open(p + ".gz", "rt"))
    return json.load(open(p)) if os.path.exists(p) else None


def pct(a, b):
    return round((a / b - 1) * 100, 1) if a is not None and b else None


_CH = {}


def chapter(ch):
    if ch not in _CH:
        p = os.path.join(DOCS, "trade", "ch", f"{ch}.json")
        _CH[ch] = json.load(gzip.open(p + ".gz", "rt")) if os.path.exists(p + ".gz") else None
    return _CH[ch]


def trade_group(prefixes, side):
    """Aggregate monthly unit price for a set of HS prefixes: sum(value) / sum(quantity in KGS) across every code under the
    prefixes that is quoted in a mass unit (KGS, or TON x 1000). Summing before dividing makes one lumpy code harmless."""
    vf, qf = ("i", "p") if side == "imp" else ("e", "q")
    months = None
    picked = []
    for pre in prefixes:
        obj = chapter(pre[:2])
        if not obj:
            continue
        if months is None:
            months = obj["months"]
        for hs, r in obj["codes"].items():
            if not hs.startswith(pre) or r["u"] not in ("KGS", "TON", "TNE", "MTS"):
                continue
            mult = 1000.0 if r["u"] in TON_UNITS else 1.0
            ups = [
                v * 1e6 / (q * mult)
                for v, q in list(zip(r[vf], r[qf], strict=False))[-12:]
                if v is not None and q and v >= 0.05
            ]
            lv = sum(v for v in r[vf][-12:] if v)
            if ups and lv > 0:
                picked.append((hs, r, mult, statistics.median(ups), lv))
    if not picked or not months:
        return None
    # mix guard: the group price is meaningful only across codes of one price class. Reference = value-weighted median of the
    # codes' trailing-12-month median unit prices; codes more than 3x above or below it (powder vs bars, jewellery vs metal,
    # a quantity recorded in the wrong unit) are left out of the aggregate.
    srt = sorted(picked, key=lambda t: t[3])
    tot = sum(t[4] for t in srt)
    acc = 0
    ref = srt[-1][3]
    for t in srt:
        acc += t[4]
        if acc >= tot / 2:
            ref = t[3]
            break
    keep = [t for t in picked if ref / 3 <= t[3] <= ref * 3]
    V = [0.0] * len(months)
    Q = [0.0] * len(months)
    codes = 0
    top = None
    for hs, r, mult, _med, lv in keep:
        for i, (v, q) in enumerate(zip(r[vf], r[qf], strict=False)):
            if v is not None and q:
                V[i] += v
                Q[i] += q * mult
        codes += 1
        if top is None or (r[vf][-1] or 0) > top[1]:
            top = (hs, r[vf][-1] or 0, r["d"], r["u"])
    dropped = [t[0] for t in picked if t not in keep]
    P = [round(V[i] * 1e6 / Q[i], 4) if Q[i] > 0 and V[i] >= 0.05 else None for i in range(len(months))]
    last = len(months) - 1

    def at(n):
        j = last - n
        return P[j] if j >= 0 else None

    def block(a, b):  # smoothed: sum over months last-a..last-b
        vs = sum(V[j] for j in range(last - a, last - b + 1) if j >= 0)
        qs = sum(Q[j] for j in range(last - a, last - b + 1) if j >= 0)
        return vs * 1e6 / qs if qs > 0 and vs >= 0.05 else None

    val3 = sum(V[j] for j in range(last - 2, last + 1) if j >= 0) / 3
    return {
        "codes": codes,
        "month": months[last],
        "value_usd_mn": round(V[last], 1),
        "value_3m_avg": round(val3, 1),
        "unit": "US$/kg",
        "price": P[last],
        "chg_1m": pct(P[last], at(1)),
        "chg_3m": pct(P[last], at(3)),
        "chg_12m": pct(P[last], at(12)),
        "chg_sy": pct(block(2, 0), block(14, 12)),
        "qty_12m": pct(Q[last], Q[last - 12] if last >= 12 else None),
        "top": {"hs": top[0], "d": top[2], "u": top[3], "v": round(top[1], 2)},
        "dropped": dropped,
        "series": {"months": months, "price": P, "value": [round(x, 2) for x in V]},
    }


def _india_history():
    """Every dated Indian print we hold - recorded daily plus recovered from archives - keyed (source, series)
    the way india_spot.py writes them. Read from india_history.json.gz (what the page charts) so the stats
    here and on the page come from the same points; the raw CSV is the fallback."""
    out = {}
    p = os.path.join(DOCS, "india_history.json.gz")
    if os.path.exists(p):
        try:
            for v in json.load(gzip.open(p, "rt"))["series"].values():
                out[(v["src"], v["key"])] = [tuple(x) for x in v["p"]]
            return out
        except Exception:
            out = {}
    p = os.path.join(DOCS, "india_spot_history.csv")
    if not os.path.exists(p):
        return out
    import india_spot  # the one definition of which recorded rows are in force

    for r in india_spot.in_force(p, os.path.join(DOCS, "india_retracted.csv")):
        try:
            out.setdefault((r["source"], r["series"]), []).append((r["date"], float(r["price"])))
        except (ValueError, KeyError):
            continue
    for v in out.values():
        v.sort()
    return out


def hist_stats(series, step=False):
    """Changes and a HIGHEST-SINCE date from a dated series of [date, price] or [date, price, basis].

    'Highest since' is the plain reading of the question 'is this at a four-month high?': the most recent
    earlier date whose price was at or above today's. No earlier date reaching it means today is the highest
    in everything we hold, which is a statement about OUR history, not about all time - so the span we hold
    is reported beside it and the page says so.

    `step`: an ADMINISTERED price (NMDC) holds until the next letter, so "the price a year ago" is the one in force
    then, however long before it was set. Every other series is a set of OBSERVATIONS: a window counts only when
    a reading sits within 10% of the window (at least 4 days) of its start - otherwise a monthly series reports
    its previous month-end as "1 week ago" (it did: HRC "1 week -1.2%" on 2026-09-23).

    A third field, when present, is the basis the price was stated on (NMDC's letters say whether royalty,
    DMF and NMET are included, and that flipped in Jul-2023 and again in Jan-2026). A change measured
    between two different bases is a definition change, not a price move, so every window that compares
    across one is named in `basis_break` and the page flags it instead of presenting it as a move.
    """
    # sorted here, never trusted from the caller: NMDC's history once arrived in FILING order with one letter
    # misdated to 2020, and the 'a year ago' lookup took the last list entry before the cut - the misdated
    # one - turning a -11.5% year into +17.4%.
    v = sorted(
        ((it[0], it[1], it[2] if len(it) > 2 else None) for it in series if it[1] is not None), key=lambda t: t[0]
    )
    if len(v) < 2:
        return None
    last_d, last, last_b = v[-1]

    def back(days):
        cut_d = datetime.date.fromisoformat(last_d) - datetime.timedelta(days=days)
        if step:  # the price in force at the cut
            older = [t for t in v if t[0] <= cut_d.isoformat()]
            return older[-1] if older else None
        # an observation series: the reading nearest the window's start, either side, if one is close enough
        # (six months back from 30 Jun is 31 Dec, 181 days; a 182-day cut lands on 30 Dec)
        near = [t for t in v[:-1] if abs((datetime.date.fromisoformat(t[0]) - cut_d).days) <= max(4, days * 0.1)]
        return min(near, key=lambda t: abs((datetime.date.fromisoformat(t[0]) - cut_d).days)) if near else None

    out, breaks = {}, {}
    for name, days in (("chg_1w", 7), ("chg_1m", 30), ("chg_3m", 91), ("chg_6m", 182), ("chg_1y", 365)):
        o = back(days)
        out[name] = pct(last, o[1]) if o else None
        if o and last_b and o[2] and o[2] != last_b:
            breaks[name] = o[2]
    hi = next((t for t in reversed(v[:-1]) if t[1] >= last), None)
    lo = next((t for t in reversed(v[:-1]) if t[1] <= last), None)
    if hi and last_b and hi[2] and hi[2] != last_b:
        breaks["high_since"] = hi[2]
    vals = [t[1] for t in v]
    span = (datetime.date.fromisoformat(last_d) - datetime.date.fromisoformat(v[0][0])).days
    # A two-day series can say "highest since yesterday" and be literally true while telling the reader
    # nothing. Below a real span the changes still stand - they are measured - but the high/low-since
    # verdict is withheld rather than dressed up.
    deep = span >= 60 and len(v) >= 6
    return dict(
        n=len(v),
        first=v[0][0],
        last_date=last_d,
        span_days=span,
        deep=deep,
        **out,
        hi=max(vals),
        lo=min(vals),
        high_since=(hi[0] if hi else None) if deep else None,
        low_since=(lo[0] if lo else None) if deep else None,
        at_series_high=(hi is None) if deep else None,
        at_series_low=(lo is None) if deep else None,
        basis=last_b,
        bases=len({t[2] for t in v if t[2]}),
        basis_break=breaks,
    )


def main():
    cmap = load("commodity_map.json")
    spot = load("spot.json")
    wpi = load("wpi.json")
    idx = load("trade/index.json")
    ind = load("india_spot.json") or {}
    te_rows = {r["slug"]: r for r in ((ind.get("sources") or {}).get("te") or {}).get("rows", [])}
    ind_src = {k: v.get("rows", []) for k, v in (ind.get("sources") or {}).items() if k != "te"}
    ihist = _india_history()
    out = []
    for g in cmap["groups"]:
        sig = {
            "id": g["id"],
            "name": g["name"],
            "hs": g.get("hs", []),
            "benefit": g.get("benefit", []),
            "suffer": g.get("suffer", []),
            "history": g.get("history"),
            "note": g.get("note"),
            "sources": {},
        }
        # daily spot
        sp = []
        for k in g.get("spot", []):
            r = (spot or {}).get("rows", {}).get(k)
            if r and r.get("last") is not None:
                sp.append(
                    {
                        "name": k,
                        "last": r["last"],
                        "unit": r.get("unit"),
                        "chg_1w": r.get("chg_1w"),
                        "chg_1m": r.get("chg_1m"),
                        "chg_3m": r.get("chg_3m"),
                        "chg_6m": r.get("chg_6m"),
                        "pos52": r.get("pos"),
                        "date": r.get("date"),
                        "n": r.get("n"),
                    }
                )
        if sp:
            sig["sources"]["spot"] = sp
        # Trading Economics daily proxies (futures/CFD: direction, not the Indian print)
        te = []
        for slug in g.get("te", []):
            r = te_rows.get(slug)
            if r and r.get("price") is not None:
                te.append(
                    {
                        "slug": slug,
                        "name": r["name"],
                        "last": r["price"],
                        "unit": r["unit"],
                        "date": r["date"],
                        "chg_1d": r.get("chg_1d"),
                        "chg_1m": r.get("chg_1m"),
                        "chg_1y": r.get("chg_1y"),
                        "id": "te|" + (r.get("key") or f"{r['name']} | {slug}"),
                    }
                )
        if te:
            sig["sources"]["te"] = te
        # Indian domestic prints (MetalBook city prices, IBJA, Rubber Board, sugar spot, PPAC fuel)
        india = []
        for src, rx in g.get("india", []):
            for r in ind_src.get(src, []):
                label = " ".join(str(r.get(k)) for k in ("city", "market", "name", "grade") if r.get(k))
                if (
                    not re.search(rx, str(r.get("name") or r.get("grade") or ""), re.IGNORECASE)
                    or r.get("price") is None
                ):
                    continue
                # NMDC carries its own history (its price letters are the series); the other sources publish
                # only today's print, so their history is the one we have been recording since 2026-09-22.
                key = " | ".join(str(r.get(k)) for k in ("city", "market", "name", "grade", "slug") if r.get(k))
                series = r.get("history") or ihist.get((src, key)) or []
                row = {
                    "source": src,
                    "name": label,
                    "last": r["price"],
                    "unit": r.get("unit"),
                    "chg_1d": r.get("chg_1d"),
                    "chg_prev": r.get("chg_prev"),
                    "date": r.get("date"),
                    "id": f"{src}|{key}",
                }
                for k in ("wef", "basis", "chg_rev", "filed"):
                    if r.get(k) is not None:
                        row[k] = r[k]
                st = hist_stats([tuple(x) for x in series], step=bool(r.get("step")))
                if st:
                    row["stats"] = st
                india.append(row)
        if india:
            sig["sources"]["india"] = india
        # monthly WPI items
        wp = []
        if wpi and g.get("wpi"):
            months = wpi["months"]
            for it in wpi["items"]:
                if not it["leaf"] or not any(t in it["n"].lower() for t in g["wpi"]):
                    continue
                v = it["v"]
                last_i = max((i for i, x in enumerate(v) if x is not None), default=None)
                if last_i is None:
                    continue

                def at(n):
                    j = last_i - n
                    return v[j] if j >= 0 else None

                wp.append(
                    {
                        "name": it["n"],
                        "code": it["c"],
                        "month": months[last_i],
                        "last": v[last_i],
                        "chg_1m": pct(v[last_i], at(1)),
                        "chg_3m": pct(v[last_i], at(3)),
                        "chg_12m": pct(v[last_i], at(12)),
                        "weight": it["w"],
                    }
                )
        if wp:
            sig["sources"]["wpi"] = wp
        # monthly trade unit prices: ONE aggregate per HS prefix (a prefix is one product class; a group may deliberately mix
        # an input and an output, e.g. needle coke + electrodes, sulphur + sulphuric acid, so they are never summed together)
        if g.get("hs"):
            tr = []
            for pre in g["hs"]:
                d = {"prefix": pre}
                for side in ("imp", "exp"):
                    t = trade_group([pre], side)
                    if t:
                        d[side] = t
                if "imp" in d or "exp" in d:
                    big = max((d[k] for k in ("imp", "exp") if k in d), key=lambda t: t["value_3m_avg"])
                    d["name"] = big["top"]["d"]
                    d["value_3m_avg"] = round(sum(d[k]["value_3m_avg"] for k in ("imp", "exp") if k in d), 1)
                    tr.append(d)
            tr.sort(key=lambda d: -d["value_3m_avg"])
            if tr:
                sig["sources"]["trade"] = tr
        # strength: the strongest normalised move across sources (positive = rising price)
        cands = []
        for s in sp:
            for k, thr in (("chg_1w", 5), ("chg_1m", 10), ("chg_3m", 20)):
                if s.get(k) is not None:
                    cands.append((s[k] / thr, f"spot {s['name']} {k[4:]} {s[k]:+.1f}%"))
        for t in te:
            for k, thr in (("chg_1m", 10), ("chg_1y", 30)):
                if t.get(k) is not None:
                    cands.append((max(min(t[k], 300), -100) / thr, f"{t['name']} (global) {k[4:]} {t[k]:+.1f}%"))
        for w in wp:
            for k, thr in (("chg_1m", 3), ("chg_3m", 8), ("chg_12m", 15)):
                if w.get(k) is not None:
                    cands.append((w[k] / thr, f"WPI {w['name']} {k[4:]} {w[k]:+.1f}%"))
        for d in sig["sources"].get("trade") or []:
            for side in ("imp", "exp"):
                t = d.get(side)
                if (
                    not t or (t.get("value_3m_avg") or 0) < 3
                ):  # sides averaging under US$3 mn a month have lumpy unit prices
                    continue
                for k, thr, cap in (("chg_1m", 10, 60), ("chg_3m", 15, 150), ("chg_sy", 30, 300)):
                    if t.get(k) is None:
                        continue
                    if k == "chg_1m" and (t.get("chg_3m") is None or (t["chg_3m"] > 0) != (t[k] > 0)):
                        continue  # a one-month jump counts only when the 3-month move agrees (single lumpy shipments)
                    cands.append(
                        (
                            max(min(t[k], cap), -cap) / thr,
                            f"{side}ort unit price {k[4:]} {t[k]:+.1f}% · HS {d['prefix']} {d['name'][:38].lower()} ({t['codes']} codes, US${t['value_usd_mn']}mn/month)",
                        )
                    )
        if cands:
            best = max(cands, key=lambda c: c[0])
            worst = min(cands, key=lambda c: c[0])
            pick = best if abs(best[0]) >= abs(worst[0]) else worst
            sig["strength"] = round(pick[0], 2)
            sig["headline"] = pick[1]
            sig["direction"] = "up" if pick[0] > 0 else "down"
            sig["evidence"] = [c[1] for c in sorted(cands, key=lambda c: -abs(c[0]))[:6]]
        else:
            sig["strength"] = 0
            sig["headline"] = "no price feed wired for this group yet"
            sig["direction"] = "none"
            sig["evidence"] = []
        out.append(sig)
    out.sort(key=lambda s: -abs(s.get("strength") or 0))
    res = {
        "built": ist.stamp(),
        "thresholds": "strength 1.0 = spot +5% 1w / +10% 1m / +20% 3m; WPI +3% 1m / +8% 3m / +15% 12m; trade unit price +8% 1m / +15% 3m / +30% smoothed yoy",
        "spot_date": (spot or {}).get("updated"),
        "wpi_month": (wpi or {}).get("months", [None])[-1],
        "trade_month": (idx or {}).get("latest"),
        "india_built": ind.get("built"),
        "india_status": ind.get("status"),
        "groups": out,
    }
    json.dump(res, open(os.path.join(DOCS, "signals.json"), "w"), indent=1)
    print("signals:", len(out), "groups")
    for s in out[:14]:
        print(f"  {s['strength']:+6.2f} {s['direction']:4s} {s['name'][:32]:32s} {s['headline']}")


if __name__ == "__main__":
    main()
