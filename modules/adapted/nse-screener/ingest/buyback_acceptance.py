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


"""Buyback ACCEPTANCE RATIOS — the number the whole tender trade rests on.

Why this matters (from v40): buyback stocks do NOT run up into the
record date — they drift ~1-2pp behind the market — and they stay ~2pp
weak for a month after it. So the entry price isn't inflated, but any
shares the company DOESN'T accept are held into reliable weakness.
The trade therefore lives or dies on the acceptance ratio, and for
small shareholders (<=Rs 2L holdings, who get a reserved 15% of every
tender offer) that ratio has historically run far above entitlement.

Our announcement store has 504 post-offer filings but EMPTY snippets —
the numbers are only in PDF attachments. Same shape as the v22.1
ratings pipeline, so same 3-phase design:

    python -m ingest.buyback_acceptance scan    # announcements + PDF urls
    python -m ingest.buyback_acceptance pdfs    # download (restartable)
    python -m ingest.buyback_acceptance parse   # extract (after review)
"""
import contextlib
import re
import sys
import time
from datetime import date

import pandas as pd
from ingest import nse, renames

import config

DIR = config.DATA_DIR / "buybacks"
PDF_DIR = DIR / "pdfs"
ANN_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={frm}&to_date={to}"
WARMUP = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
# post-offer filings carry the acceptance numbers; the others give context
POST = re.compile(r"post[\s-]?(buyback|offer)", re.IGNORECASE)
ANY_BB = re.compile(r"buy[\s-]?back|post[\s-]?offer", re.IGNORECASE)


def scan() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    s = nse.session()
    s.get(WARMUP, timeout=15)
    frames = []
    for yr in range(2016, 2027):
        for frm, to in ((f"01-01-{yr}", f"30-06-{yr}"), (f"01-07-{yr}", f"31-12-{yr}")):
            try:
                r = nse.get(ANN_URL.format(frm=frm, to=to), timeout=180)
                d = r.json()
                d = d if isinstance(d, list) else d.get("data", [])
                if not d:
                    continue
                df = pd.DataFrame(d)
                df = df[df["desc"].astype(str).str.contains(ANY_BB, na=False)]
                if len(df):
                    frames.append(df)
                print(f"  {frm[-4:]} {frm[3:5]}-{to[3:5]}: {len(df)} buyback rows", flush=True)
            except Exception as e:
                print(f"  {frm}: {type(e).__name__} {e}"[:110], flush=True)
            time.sleep(1.5)
    ann = pd.concat(frames, ignore_index=True)
    ann["symbol"] = renames.canonical(ann["symbol"].astype(str).str.strip())
    ann["an_dt"] = pd.to_datetime(ann["an_dt"], errors="coerce")
    ann["is_post"] = ann["desc"].astype(str).str.contains(POST, na=False)
    ann = ann.drop_duplicates(["symbol", "an_dt", "desc"])
    keep = ["symbol", "an_dt", "desc", "attchmntFile", "is_post", "sm_name"]
    ann[[c for c in keep if c in ann.columns]].to_parquet(DIR / "announcements.parquet", index=False)
    print(f"\nbuyback announcements: {len(ann)} ({ann['is_post'].sum()} post-offer with the acceptance numbers)")
    print(ann.groupby(ann["an_dt"].dt.year)["is_post"].sum().to_string())


def pdfs(limit: int | None = None) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    ann = pd.read_parquet(DIR / "announcements.parquet")
    todo = ann[ann["is_post"] & ann["attchmntFile"].astype(str).str.endswith((".pdf", ".PDF"))]
    if limit:
        todo = todo.head(limit)
    got = 0
    for _, r in todo.iterrows():
        url = str(r["attchmntFile"])
        name = f"{r['symbol']}_{r['an_dt'].date()}_{url.rsplit('/', 1)[-1]}"
        out = PDF_DIR / name[:120]
        if out.exists():
            continue
        try:
            resp = nse.get(url, timeout=120)
            if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                out.write_bytes(resp.content)
                got += 1
            else:
                print(f"  skip {name[:50]}: {resp.status_code}", flush=True)
        except Exception as e:
            print(f"  {name[:50]}: {type(e).__name__}", flush=True)
        time.sleep(0.6)
        if got and got % 50 == 0:
            print(f"  {got} PDFs downloaded", flush=True)
    print(f"pdf fetch done: {got} new, {len(list(PDF_DIR.glob('*.pdf')))} total on disk")


# --- parse phase (written AFTER a format review of 167 downloaded PDFs) ---
# Layout, stable across 2018-2026 with one variant:
#   "Reserved category for Small Shareholders <RESERVED> <BIDS> <TENDERED> <RESPONSE>"
# and an older variant (e.g. COCHINSHIP 2018) that puts the numbers BEFORE
# the label. Numbers are Indian-comma format and PDF extraction sprinkles
# stray spaces inside them ("1,84,7 6,817"), so the number regex tolerates
# internal whitespace.
#
# CRITICAL DESIGN CHOICE: the stated "Response" column is sometimes a
# MULTIPLE (10.67) and sometimes a PERCENTAGE (433.37%) — the header text
# differs by filing. So acceptance is DERIVED as reserved/tendered, and the
# stated response is used only as a CROSS-CHECK. A row is kept only if the
# stated figure matches the derived ratio (as-is or x100) within 5%.
SMALL = re.compile(r"Reserved\s+category\s+for\s+Small\s+Shareholders", re.IGNORECASE)
GENERAL = re.compile(r"General\s+[Cc]ategory", re.IGNORECASE)
# NOTE: whitespace must NOT be allowed inside this pattern — an earlier
# version permitted it and greedily merged four table columns into one
# number. Filings whose PDF text splits a figure ("1,84,7 6,817") now
# simply fail the cross-check below and are rejected rather than guessed.
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _nums(text):
    out = []
    for m in NUM.finditer(text):
        t = re.sub(r"[,\s]", "", m.group(0))
        with contextlib.suppress(ValueError):
            out.append(float(t))
    return out


def _row_after(flat, marker_match, n=4):
    """the first n numbers following the label (main layout)"""
    return _nums(flat[marker_match.end() : marker_match.end() + 220])[:n]


def parse() -> None:
    from pypdf import PdfReader

    rows, unread, no_table, rejected = [], 0, 0, 0
    for f in sorted(PDF_DIR.glob("*.pdf")):
        try:
            txt = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(f)).pages)
        except Exception:
            unread += 1
            continue
        flat = re.sub(r"\s+", " ", txt)
        m = SMALL.search(flat)
        if not m:
            no_table += 1
            continue
        vals = _row_after(flat, m)
        if len(vals) < 3:
            no_table += 1
            continue
        reserved, bids, tendered = vals[0], vals[1], vals[2]
        stated = vals[3] if len(vals) > 3 else None
        # PLAUSIBILITY BOUNDS (added after ASHIANA-2023 slipped through):
        # some post-offer PAs are SCANS, and OCR drops digits. There the
        # cross-check below is useless, because the reserved figure and the
        # stated response are mangled by the SAME corrupted text, so their
        # ratio survives and they agree. Correlated errors defeat a
        # consistency check — only absolute plausibility catches them.
        # A real reserved category is never a few hundred shares, and even
        # the most extreme genuine oversubscription is tens of times, not
        # thousands.
        if reserved < 1000 or tendered <= 0 or tendered / reserved > 200:
            rejected += 1
            continue
        derived = tendered / reserved  # "times oversubscribed"
        ok = stated is not None and (
            abs(stated - derived) / derived < 0.05 or abs(stated - derived * 100) / (derived * 100) < 0.05
        )
        if not ok:
            rejected += 1  # parse not trustworthy
            continue
        gm = GENERAL.search(flat, m.end())
        gvals = _row_after(flat, gm) if gm else []
        sym, dt = f.name.split("_")[0], f.name.split("_")[1]
        rows.append(
            {
                "symbol": sym,
                "an_dt": dt,
                "pdf": f.name,
                "small_reserved": reserved,
                "small_bids": bids,
                "small_tendered": tendered,
                "small_oversub_x": derived,
                "small_acceptance": min(1.0, reserved / tendered),
                "gen_reserved": gvals[0] if len(gvals) > 2 else None,
                "gen_tendered": gvals[2] if len(gvals) > 2 else None,
            }
        )
    out = pd.DataFrame(rows)
    out.to_parquet(DIR / "acceptance.parquet", index=False)
    print(
        f"parsed: {len(out)} filings with a validated small-shareholder "
        f"table  (no table: {no_table}, failed cross-check: {rejected}, "
        f"unreadable: {unread})"
    )
    if len(out):
        a = out["small_acceptance"]
        print("\nSMALL-SHAREHOLDER ACCEPTANCE RATIO")
        print(f"  median {100 * a.median():.1f}%   mean {100 * a.mean():.1f}%")
        print(f"  p25 {100 * a.quantile(0.25):.1f}%   p75 {100 * a.quantile(0.75):.1f}%")
        print(f"  share of events accepting >50%: {100 * (a > 0.5).mean():.0f}%")
        print(f"  share accepting 100% (undersubscribed): {100 * (a >= 1).mean():.0f}%")
        ent = out.dropna(subset=["gen_tendered"])
        if len(ent):
            gen = (ent["gen_reserved"] / ent["gen_tendered"]).clip(upper=1)
            print(
                f"\n  general-category acceptance median: {100 * gen.median():.1f}%"
                f"  → small-shareholder advantage: "
                f"{100 * (ent['small_acceptance'].median() - gen.median()):+.1f}pp"
            )


# --- tender price phase -------------------------------------------------
# Format review: the price is always stated as
#   "at a price of <CUR><NUMBER>/- (<THE SAME AMOUNT IN WORDS>) per Equity Share"
# but the currency glyph is mangled differently by every PDF encoder
# (Rs. / INR / ` / f / t / nothing), so it is matched loosely.
#
# TWO INDEPENDENT CHECKS, deliberately chosen after the ASHIANA lesson
# (correlated OCR errors defeated the acceptance cross-check):
#   1. WORDS vs DIGITS — the filing states the amount twice in different
#      notations. An OCR slip that drops a digit does NOT produce a
#      matching slip in the spelled-out words, so these two are genuinely
#      independent, unlike reserved-vs-response.
#   2. MARKET SANITY — a buyback price is a premium to the market price
#      around the record date. Checked against our own panel.
# A price is accepted if the words agree, or (words unparseable) the
# market check passes. Rows failing both are dropped, not guessed.
PRICE = re.compile(
    r"price\s+o[fl]\s*(?:Rs\.?|INR|₹|`|f|t|\W){0,3}\s*([\d,]+(?:\.\d+)?)"
    r"\s*(?:/[-–])?\s*\(([^)]{0,160})\)",
    re.IGNORECASE,
)
_UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fourty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALE = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000, "crore": 10000000, "crores": 10000000}


def words_to_number(text):
    """'Two Thousand Seven Hundred and Seventy' -> 2770; None if unparseable"""
    toks = re.findall(r"[a-z]+", text.lower())
    toks = [t for t in toks if t not in ("rupees", "indian", "only", "and", "rupee", "inr", "rs")]
    if not toks or not all(t in _UNITS or t in _SCALE for t in toks):
        return None
    total = cur = 0
    for t in toks:
        if t in _UNITS:
            cur += _UNITS[t]
        elif t == "hundred":
            cur = max(cur, 1) * 100
        else:
            total += max(cur, 1) * _SCALE[t]
            cur = 0
    return total + cur or None


def prices() -> None:
    from ingest.constituents import raw_close_panel
    from pypdf import PdfReader

    acc = pd.read_parquet(DIR / "acceptance.parquet")
    # RAW closes, not the CA-adjusted panel: the tender price in a filing is
    # the actual rupee price of that day, while the adjusted panel restates
    # history for later splits/bonuses. Comparing the two made premiums look
    # like +160% (a 1:10 split inflates the ratio tenfold). Same trap the
    # v29 valuation work documented — price LEVELS need raw prices.
    close = raw_close_panel()
    rows, by_words, by_market, dropped = [], 0, 0, 0
    for _, r in acc.iterrows():
        f = PDF_DIR / r["pdf"]
        try:
            txt = re.sub(r"\s+", " ", "\n".join((pg.extract_text() or "") for pg in PdfReader(str(f)).pages))
        except Exception:
            dropped += 1
            continue
        sym, dt = r["symbol"], pd.Timestamp(r["an_dt"])
        # market reference: last close on/before the filing date
        mkt = None
        if sym in close.columns:
            hist = close.loc[:dt, sym].dropna()
            mkt = float(hist.iloc[-1]) if len(hist) else None
        best = None
        for m in PRICE.finditer(txt):
            try:
                num = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if num <= 0:
                continue
            w = words_to_number(m.group(2))
            words_ok = w is not None and abs(w - num) / max(num, 1) < 0.01
            mkt_ok = mkt is not None and 0.5 <= num / mkt <= 4.0
            if words_ok or (w is None and mkt_ok):
                best = (num, words_ok, mkt_ok)
                if words_ok:
                    break  # strongest evidence, stop
        if best is None:
            dropped += 1
            continue
        num, words_ok, mkt_ok = best
        by_words += words_ok
        by_market += (not words_ok) and mkt_ok
        rows.append(
            {
                "symbol": sym,
                "an_dt": r["an_dt"],
                "tender_price": num,
                "market_ref": mkt,
                "premium_pct": (100 * (num / mkt - 1) if mkt else None),
                "validated_by": "words" if words_ok else "market",
                "small_acceptance": r["small_acceptance"],
            }
        )
    out = pd.DataFrame(rows)
    out.to_parquet(DIR / "tender_prices.parquet", index=False)
    print(
        f"tender prices: {len(out)} of {len(acc)} filings "
        f"(words-validated {by_words}, market-validated {by_market}, "
        f"dropped {dropped})"
    )
    if len(out):
        pr = out["premium_pct"].dropna()
        print("\npremium of tender price over market at filing:")
        print(f"  median {pr.median():+.1f}%   p25 {pr.quantile(0.25):+.1f}%   p75 {pr.quantile(0.75):+.1f}%")
        print(f"  negative-premium cases: {(pr < 0).sum()} (price below market by the time of the post-offer filing)")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "pdfs":
        pdfs(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    else:
        {"scan": scan, "parse": parse, "prices": prices}[cmd]()
