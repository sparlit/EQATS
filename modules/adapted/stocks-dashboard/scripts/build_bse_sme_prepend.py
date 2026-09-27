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
"""Build scripts/bse_sme_prepend.json.gz — the BSE-SME-era bars of companies that later listed on NSE (runbook §149).

For every scrip in scripts/bse_sme_backfill.json.gz (ever on BSE SME since 2020) that maps to an NSE symbol (by ISIN,
else scripts/bse_scrips.json by_id) whose NSE series starts LATER than its BSE series, emit a standard `prepend`
block for update_sf_data.insert_sme_history:
  bars    [d, c, t(₹ lakh), h, l, op, v, dv=0, vw=turnover/volume] for BSE days BEFORE the NSE series' first bar,
          on the RAW basis of the anchor day (only BSE splits between the bar and the anchor are applied);
  anchor  {ymd: NSE first bar, raw: BSE raw close that day} → insert_sme_history rescales by stored/raw, which
          maps the bars onto the NSE series' own adjustment level (and absorbs any NSE-era corporate action).
SAFETY: identity = the NSE symbol's ISIN issuer (isin[:7]) must equal the BSE scrip's; a BSE-era day in `unexpl` (a
>30 % one-day fall that may be an unadjusted bonus) truncates the block to the bars AFTER it; the implied rescale must
equal the product of the NSE series' own corporate actions after the anchor (within 3 %) or the block is refused;
the NSE series must start exactly on a BSE trading day (same-day anchor). Existing blocks are kept.

--mainboard (§171): the same blocks for MAIN-BOARD BSE scrips that listed on NSE later (NIRLON, TIMEX, ELANTAS … the
2026-04-20 permitted-to-trade batch; SANDUMA 2023). Their BSE series are built straight from the bhavcopy cache (any
group), matched to the NSE symbol by EXACT ISIN, else by issuer (isin[:7]) when exactly one BSE equity scrip carries
it; every gate above applies unchanged. Blocks land in the same ledger (note says "BSE main board").

RENAME GUARD (§199): an NSE symbol change is not a later listing. The NEW symbol of a scripts/symchg.csv pair whose OLD
symbol traded on NSE within 45 days of the change date starts a fresh-looking tape (HEGAM 2026-09-22), but NSE printed
the company under the OLD symbol all along — a BSE block would re-print those sessions from another exchange and put
bars in front of the new key (which also blinded detect_renames). Refused; that pair is a §30 MANUAL_MERGE.

Run: python3 -X utf8 scripts/build_bse_sme_prepend.py --tape docs/sf_stock_data.bin [--only SYM,…] [--mainboard] [--dry]
"""
import contextlib
import csv
import datetime
import gzip
import io
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.environ.get("BSE_BHAV_CACHE") or os.path.join(HERE, "_bse_bhav_cache")
OUT = os.path.join(HERE, "bse_sme_prepend.json.gz")
KS = (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 10, 20, 25, 50, 100)


def ohlc_rows(codes):
    """{code: {date: (o,h,l,c,v,turnover)}} from the cache, date-checked, for the wanted scrips only."""
    out = {c: {} for c in codes}
    for f in sorted(x for x in os.listdir(CACHE) if x[:8].isdigit()):
        k = int(f[:8])
        raw = open(os.path.join(CACHE, f), "rb").read()
        if f.endswith(".zip"):
            z = zipfile.ZipFile(io.BytesIO(raw))
            raw = z.read(z.namelist()[0])
        rows = list(csv.reader(io.StringIO(raw.decode("latin1"))))
        h = [x.strip() for x in rows[0]]
        if "SC_CODE" in h:
            ix = {c: h.index(c) for c in ("SC_CODE", "OPEN", "HIGH", "LOW", "CLOSE", "NO_OF_SHRS", "NET_TURNOV")}
            td = h.index("TRADING_DATE") if "TRADING_DATE" in h else None
            for r in rows[1:]:
                if len(r) < len(h) - 3:
                    continue
                code = r[ix["SC_CODE"]].strip()
                if code not in out:
                    continue
                if td is not None and r[td].strip():
                    try:
                        if int(datetime.datetime.strptime(r[td].strip(), "%d-%b-%y").strftime("%Y%m%d")) != k:
                            break
                    except ValueError:
                        continue  # a record broken across lines (newline inside a name) — rows_of skips it too
                with contextlib.suppress(ValueError):
                    out[code][k] = tuple(
                        float(r[ix[x]] or 0) for x in ("OPEN", "HIGH", "LOW", "CLOSE", "NO_OF_SHRS", "NET_TURNOV")
                    )
        else:
            ix = {
                c: h.index(c)
                for c in (
                    "FinInstrmId",
                    "OpnPric",
                    "HghPric",
                    "LwPric",
                    "ClsPric",
                    "TtlTradgVol",
                    "TtlTrfVal",
                    "TradDt",
                )
            }
            for r in rows[1:]:
                if len(r) <= ix["TradDt"]:
                    continue
                code = r[ix["FinInstrmId"]].strip()
                if code not in out:
                    continue
                if int(r[ix["TradDt"]].replace("-", "")) != k:
                    break
                with contextlib.suppress(ValueError):
                    out[code][k] = tuple(
                        float(r[ix[x]] or 0)
                        for x in ("OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol", "TtlTrfVal")
                    )
    return out


def main():
    a = sys.argv[1:]
    tape = a[a.index("--tape") + 1]
    only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
    T = json.loads(gzip.open(tape).read())
    BS = json.loads(gzip.open(os.path.join(HERE, "bse_sme_backfill.json.gz")).read())["series"]
    isin2sym = {m["isin"]: s for s, m in T["meta"].items() if m.get("isin")}
    code2sym = {str(v): k for k, v in json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"].items()}
    try:
        led = json.load(gzip.open(OUT, "rt", encoding="utf-8"))
    except (OSError, ValueError):
        led = {"prepend": {}}
    # IDENTITY GATE: the NSE symbol's own ISIN (NSE's EQUITY_L.csv, else the tape meta) must share the ISSUER part
    # (isin[:7]) with the BSE scrip's ISIN — the tail legitimately changes on a face-value split (INA 01016 -> 01024).
    # A symbol-only match can be a different company (bse_scrip_isin_conflicts.json: FOCUS, KALYANI; GSTL collides).
    nse_isin = {s: m["isin"] for s, m in T["meta"].items() if m.get("isin")}
    if "--equity-l" in a:
        import csv as _csv

        for r in _csv.DictReader(open(a[a.index("--equity-l") + 1], encoding="utf-8", errors="replace")):
            r = {k.strip(): (v or "").strip() for k, v in r.items()}
            if r.get("SYMBOL") and r.get("ISIN NUMBER"):
                nse_isin[r["SYMBOL"]] = r["ISIN NUMBER"]
    board = "BSE SME"
    if "--mainboard" in a:
        import build_bse_sme_backfill as BB

        board = "BSE main board"
        allser, _, _ = BB.build_series("ALL")
        full = {i: s_ for s_, i in nse_isin.items() if i}
        by_iss = {}
        for code, bs in allser.items():
            if (bs.get("isin") or "")[:3] in ("INE", "IN9"):
                by_iss.setdefault(bs["isin"][:7], []).append(code)
        BS = {}
        for code, bs in allser.items():
            i = bs.get("isin") or ""
            sym = full.get(i)
            if not sym and len(by_iss.get(i[:7], [])) == 1:
                sym = next((s_ for s_, i2 in nse_isin.items() if i2 and i2[:7] == i[:7]), None)
            e = T["data"].get(sym) if sym else None
            if e and e["d"] and bs["d"][0] < e["d"][0]:
                BS[code] = bs
                isin2sym.setdefault(i, sym)
        print("mainboard: %d BSE series in the cache, %d start before their NSE symbol's tape" % (len(allser), len(BS)))
    # §199 rename guard: new symbol -> [(old symbol, change date)] from NSE's symbol-change master
    ren = {}
    mon = {
        m: i + 1
        for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))
    }
    try:
        for r in csv.reader(open(os.path.join(HERE, "symchg.csv"), encoding="utf-8", errors="replace")):
            c = [x.strip() for x in r]
            if len(c) >= 4 and c[1] and c[2] and len(c[3].split("-")) == 3 and c[3].split("-")[1].upper() in mon:
                dd, mm, yy = c[3].split("-")
                ren.setdefault(c[2].upper(), []).append(
                    (c[1].upper(), int(yy) * 10000 + mon[mm.upper()] * 100 + int(dd))
                )
    except OSError as ex:
        sys.exit(f"ABORT: scripts/symchg.csv unreadable ({ex}) — the rename guard cannot run")

    def _od(y):
        return datetime.date(y // 10000, y // 100 % 100, y % 100).toordinal()

    cand = {}
    for code, bs in BS.items():
        sym = isin2sym.get(bs.get("isin")) or code2sym.get(code)
        e = T["data"].get(sym) if sym else None
        if not e or not e["d"] or bs["d"][0] >= e["d"][0]:
            continue
        if only and sym not in only:
            continue
        prev = [
            (o, dch)
            for o, dch in ren.get(sym, ())
            if (T["data"].get(o) or {}).get("d") and 0 <= _od(dch) - _od(T["data"][o]["d"][-1]) <= 45
        ]
        if prev:
            print(
                "  SKIP %-12s NSE rename %s -> %s on %d: the company traded on NSE as %s — a §30 MANUAL_MERGE, not a "
                "later listing (§199)" % (sym, prev[0][0], sym, prev[0][1], prev[0][0])
            )
            continue
        ni, bi = nse_isin.get(sym, ""), bs.get("isin", "")
        if not ni or not bi or ni[:7] != bi[:7]:
            print(
                "  SKIP %-12s identity: NSE ISIN %s vs BSE %s ISIN %s" % (sym, ni or "unknown", code, bi or "unknown")
            )
            continue
        cand[sym] = (code, bs, e)
    CA = {}
    for p_ in ("corp_actions_hist.json", "corp_actions.json"):
        try:
            for k_, lst in json.load(open(os.path.join(HERE, p_)))["factors"].items():
                for dd, ff in lst:
                    CA.setdefault(k_, {})[dd] = ff  # same ex-date in both files counts once
        except (OSError, ValueError, KeyError):
            pass
    rows = ohlc_rows({c for c, _, _ in cand.values()})
    made, refused, kept = [], [], []
    for sym, (code, bs, e) in sorted(cand.items()):
        if sym in led["prepend"]:
            kept.append(sym)
            continue
        a0 = e["d"][0]
        R = rows[code]
        if a0 not in R:
            refused.append((sym, "no BSE row on the NSE first day %d" % a0))
            continue
        raw0 = R[a0][3]
        s = e["c"][0] / raw0 if raw0 else 0
        # the rescale must be EXPLAINED by the NSE series' own corporate actions after the anchor (their product,
        # from scripts/corp_actions*.json) — 'close to a standard ratio' was too loose: NGIL 0.678 has no NSE action
        exp = 1.0
        for dd, ff in sorted(CA.get(sym, {}).items()):
            if dd > a0:
                exp *= ff
        anchor = {"ymd": a0, "raw": raw0}
        if board == "BSE main board":
            # A thin name's FIRST NSE close can sit several % off BSE's that day (73 of 81 day-1 refusals, 3-15 %) —
            # a cross-exchange spread, not a corporate action. Main-board blocks therefore (a) test identity on the
            # MEDIAN NSE-stored / BSE-raw ratio over the first <=10 common sessions and (b) scale the BSE era by the
            # NSE corporate-action product itself (BSE raw x the same factors the NSE series carries), so no spread
            # is baked into years of history; the seam keeps the real day-1 gap. anchor.raw = stored/product so the
            # consumer's stored/raw rescale equals the product; bse_raw keeps BSE's printed close for provenance.
            rat = sorted(
                c_ / R[d_][3] for d_, c_ in list(zip(e["d"], e["c"], strict=False))[:10] if d_ in R and R[d_][3] > 0
            )
            med = rat[len(rat) // 2] if rat else 0
            if not rat or abs(med / exp - 1) > 0.03:
                refused.append(
                    (
                        sym,
                        "median NSE/BSE ratio %.4f over %d common days (day-1 %.4f) not explained by NSE corporate actions after %d (product %.4f)"
                        % (med, len(rat), s, a0, exp),
                    )
                )
                continue
            anchor = {
                "ymd": a0,
                "raw": round(e["c"][0] / exp, 4),
                "bse_raw": raw0,
                "median_ratio": round(med, 4),
                "n": len(rat),
            }
            s = exp
        elif abs(s / exp - 1) > 0.03:
            refused.append(
                (sym, "rescale %.4f not explained by NSE corporate actions after %d (product %.4f)" % (s, a0, exp))
            )
            continue
        splits = [(d, f) for d, f in bs.get("splits", []) if d <= a0]
        unexpl = [d for d, _ in bs.get("unexpl", []) if d <= a0]
        start = max(unexpl) if unexpl else 0  # bars strictly after the last unconfirmed fall
        bars = []
        for d in sorted(R):
            if d >= a0 or d < start or (start and d == start):
                continue
            o, hi, lo, c, v, t = R[d]
            if c <= 0:
                continue
            m = 1.0
            for sd, f in splits:
                if d < sd:
                    m /= f  # a split between this bar and the anchor
            vw = (t / v) if v else c
            bars.append(
                [
                    d,
                    round(c * m, 2),
                    round(t / 1e5, 2),
                    round(hi * m, 2),
                    round(lo * m, 2),
                    round(o * m, 2),
                    int(v / m),
                    0,
                    round(vw * m, 2),
                ]
            )
        if board == "BSE main board" and bars:
            # RISES too (§171): the SME `unexpl` list holds only >30 % FALLS; a main-board relisting after a capital
            # reduction prints +1,000 % across the gap (DIACABS, UEL, ACL, AQYLON, MICEL in the first dry run). BSE's
            # price bands cap a normal session far below this, so any bar-to-bar move outside [0.7, 1/0.7] is treated
            # as an unconfirmed action: keep only the bars after the last one, and refuse a block whose SEAM (last
            # BSE bar on the NSE level vs the NSE first close) breaks the same band.
            cut = max((i for i in range(1, len(bars)) if not 0.7 <= bars[i][1] / bars[i - 1][1] <= 1 / 0.7), default=0)
            if cut:
                start = max(start, bars[cut - 1][0])
                bars = bars[cut:]
            seam = e["c"][0] / (bars[-1][1] * s) if bars else 1
            if not 0.7 <= seam <= 1 / 0.7:
                refused.append(
                    (
                        sym,
                        "seam %.3f (last BSE %d -> NSE first %d) outside the price band — unconfirmed action at the join"
                        % (seam, bars[-1][0], a0),
                    )
                )
                continue
        if not bars:
            refused.append((sym, "no bars left before the anchor"))
            continue
        led["prepend"][sym] = {
            "target": sym,
            "bars": bars,
            "anchor": anchor,
            "meta": {"isin": bs.get("isin")},
            "note": "%s %s: %d bars %d -> %d; splits %s; truncated after unconfirmed move %s; rescale %.4f"
            % (board, code, len(bars), bars[0][0], bars[-1][0], splits or "none", start or "none", s),
        }
        made.append((sym, code, len(bars), bars[0][0], bars[-1][0], round(s, 4), start or ""))
    for m in made:
        print(
            "  ADD  %-12s BSE %s  %4d bars %d→%d  rescale %.4f  %s"
            % (m[0], m[1], m[2], m[3], m[4], m[5], (f"after unexpl {m[6]}") if m[6] else "")
        )
    for r in refused:
        print("  SKIP %-12s %s" % r)
    print("blocks: %d new, %d already present, %d refused" % (len(made), len(kept), len(refused)))
    if "--dry" not in a and made:
        led["built"] = datetime.date.today().isoformat()
        json.dump(led, gzip.open(OUT, "wt", encoding="utf-8"))
        print("wrote", OUT)


if __name__ == "__main__":
    main()
