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


"""Government announcements that are big enough to move an order book, and who they land on.

The Press Information Bureau publishes 40-80 releases a day and almost all of it is noise: awards, greetings,
inaugurations, observances. The 2026-09-22 study (runbook 144c) measured what actually paid: Cabinet
approvals, Budget allocations and procurement mandates with outlays in the tens of thousands of crores, in
sectors where the money becomes somebody's order book.

  programme (date)                        basket median   market median   share that made 5x
  defence indigenisation list (Aug-2020)      17.4x           4.3x            76% vs 44%
  smart meters / RDSS (Jun-2021)              12.0x           3.2x           100% vs 28%
  Jal Jeevan Mission (Feb-2021)                6.7x           3.7x            50% vs 35%
  railways + Vande Bharat (Feb-2022)           4.4x           3.0x            44% vs 24%
  PM Surya Ghar rooftop solar (Feb-2024)       1.8x           2.0x             0% vs  6%   <- a household
                                                                                              subsidy is not
                                                                                              an order book
So the gate here is deliberately narrow. A release must look like a DECISION (approved, sanctioned, launched,
allocated, awarded, notified) and carry either a large rupee outlay or a procurement mandate, in a sector we
have a beneficiary map for. Everything else is dropped and counted, never published.

Usage: python3 scripts/ideas/govt.py [--days 1] [--min-cr 1000]
Writes docs/ideas/govt.json  {built, scanned, kept, releases:[...]}
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contextlib

import ist  # IST stamps: a naive now() on a UTC runner was labelled IST (runbook 144e)

DOCS = os.path.join(HERE, "..", "..", "docs", "ideas")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
LIST = "https://www.pib.gov.in/allRel.aspx?reg=3&lang=1"
BODY = "https://pib.gov.in/PressReleaseIframePage.aspx?PRID=%s"

# a release must look like a decision, not an event
DECISION = re.compile(
    r"\b(cabinet (?:committee )?(?:approve|clears|nod)|ccea approve|approves?|approved|sanction(?:s|ed|ing)?|"
    r"launch(?:es|ed)?|allocat(?:es|ed|ion)|notifie[sd]|award(?:s|ed)|signs? (?:an? )?(?:contract|agreement|mou)|"
    r"clears?|tender|invites bids|policy|scheme|mission|outlay|budget|procurement|indigenis|"
    r"production linked incentive|\bpli\b|viability gap|capital outlay|contract worth)\b",
    re.IGNORECASE,
)
# and must not be one of the daily rituals
NOISE = re.compile(
    r"\b(congratulat|condol|greet|felicitat|celebrat|observ(?:es|ance)|diwas|divas|awards? ceremony|"
    r"film award|exhibition|webinar|workshop|seminar|swachhata|cleanliness|yoga day|walkathon|"
    r"photo caption|clarification|fact check|rashtrapati|visits|meets|inaugurat(?:es|ed) an? (?:exhibition|event)|"
    r"address(?:es|ed) (?:the )?(?:gathering|students)|quiz|essay|poster|pledge|anniversar)\b",
    re.IGNORECASE,
)
# Retrospectives quote big numbers about decisions taken years ago. 2026-09-24: "Coal Distribution Over
# the Years: From Allocation to Auction" (Rs 7,500 cr in the body) was kept because "Allocation" is a
# decision verb. A backgrounder is a story about the past, not an order book.
BACKGROUNDER = re.compile(
    r"\b(over the (?:years|decades)|explainer|backgrounder|fact ?sheet|year[- ]?ender|"
    r"(?:a )?look (?:back )?at|journey (?:of|from)|story of|(?:a )?decade of|\d+ years of|"
    r"milestones?|achievements? (?:of|in|under)|background note|from \w+ to \w+:|"
    r"transforming|transformation of|then and now|retrospect)\b",
    re.IGNORECASE,
)

# NOTE: 'lakh cr' and 'lakh crore' must be tried BEFORE plain 'cr' or 'Rs 1.39 lakh cr' reads as Rs 1.39 cr
AMT = re.compile(
    r"(?:rs\.?|inr|₹|rupees)\s*([\d,]+(?:\.\d+)?)\s*(lakh\s+crores?|lakh\s+cr\b|crores?|cr\b|lakhs?|billion|bn\b|trillion)",
    re.IGNORECASE,
)
MULT = {
    "lakh crore": 100000,
    "lakh crores": 100000,
    "lakh cr": 100000,
    "crore": 1,
    "crores": 1,
    "cr": 1,
    "lakh": 0.01,
    "lakhs": 0.01,
    "billion": 100,
    "bn": 100,
    "trillion": 100000,
}

# procurement mandates carry no rupee figure but reshape an order book all the same
MANDATE = re.compile(
    r"\b(indigenisation list|positive list|negative import list|import embargo|local content|"
    r"make in india (?:category|procurement)|emergency procurement|domestic content requirement|"
    r"\balmm\b|approved list of models|quality control order|anti-dumping|safeguard duty|"
    r"minimum import price|production linked incentive|\bpli\b)\b",
    re.IGNORECASE,
)


def get(url, timeout=60, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return f.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    msg = f"GET failed {url}: {last}"
    raise RuntimeError(msg)


def amount_hit(text):
    """Largest rupee outlay in the text -> (Rs crore, the matched text), or (None, None)."""
    best, hit = None, None
    for m in AMT.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", "")) * MULT.get(re.sub(r"\s+", " ", m.group(2).lower().strip()), 0)
        except Exception:
            continue
        if v and (best is None or v > best):
            best, hit = v, m.group(0).strip()
    return (round(best, 1), hit) if best else (None, None)


def amount_cr(text):
    """Largest rupee outlay in the text, in Rs crore."""
    return amount_hit(text)[0]


def listing():
    """Today's English releases: [(prid, ministry, title)] — the page groups titles under ministry headings."""
    page = get(LIST)
    out = []
    # split on the ministry headings so each link inherits the ministry above it
    parts = re.split(r"<h3[^>]*>(.*?)</h3>", page, flags=re.DOTALL)
    cur = ""
    for i, chunk in enumerate(parts):
        if i % 2 == 1:
            cur = html.unescape(re.sub(r"<[^>]+>", "", chunk)).strip()
            continue
        for m in re.finditer(r"<a[^>]*PRID=(\d+)[^>]*>(.*?)</a>", chunk, re.DOTALL):
            title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            if title:
                out.append((m.group(1), cur, re.sub(r"\s+", " ", title)))
    return out


def body_text(prid):
    try:
        b = get(BODY % prid, timeout=45, retries=2)
    except Exception:
        return ""
    b = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", b, flags=re.DOTALL | re.IGNORECASE)
    m = re.search(r'<div[^>]*class="[^"]*innner-page-main-about-us-content-right-part[^"]*"[^>]*>(.*)', b, re.DOTALL)
    b = m.group(1) if m else b
    t = html.unescape(re.sub(r"<[^>]+>", " ", b))
    return re.sub(r"\s+", " ", t)[:6000]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cr", type=float, default=1000.0, help="rupee outlay below which a release is noise")
    ap.add_argument("--max-bodies", type=int, default=25, help="how many candidate releases to open in full")
    a = ap.parse_args()

    tm = json.load(open(os.path.join(DOCS, "theme_map.json")))
    themes = {k: (v, re.compile(v["keywords"], re.IGNORECASE)) for k, v in tm["themes"].items()}

    try:
        rels = listing()
    except Exception as e:
        # PIB is blocked outright on some networks (2026-09-23/24). Leave govt.json exactly as it is -
        # a stale file the page can detect beats a half-written one - but exit cleanly and say which,
        # so the run log can tell "nothing was announced" from "the lane could not be read".
        fn = os.path.join(DOCS, "govt.json")
        built = "?"
        if os.path.exists(fn):
            with contextlib.suppress(Exception):
                built = json.load(open(fn)).get("built", "?")
        print(
            f"govt: PIB unreachable ({str(e)[:130]}); docs/ideas/govt.json LEFT UNCHANGED at its {built} build. "
            "The government lane did NOT run - its kept count is that build's, not today's."
        )
        sys.exit(0)
    stamp = ist.stamp()
    kept, unmapped, opened = [], [], 0
    dropped = {"noise": 0, "backgrounder": 0, "no decision verb": 0, "no theme": 0, "too small": 0}
    for prid, ministry, title in rels:
        if NOISE.search(title):
            dropped["noise"] += 1
            continue
        if BACKGROUNDER.search(title):
            dropped["backgrounder"] += 1
            continue
        verb = DECISION.search(title)
        if not verb:
            dropped["no decision verb"] += 1
            continue
        hit = [k for k, (v, rx) in themes.items() if rx.search(title)]
        text = title
        amt, amt_text, amt_in = *amount_hit(title), "title"
        if opened < a.max_bodies and (not hit or amt is None):
            text = title + " " + body_text(prid)
            opened += 1
            hit = [k for k, (v, rx) in themes.items() if rx.search(text)] or hit
            if amt is None:
                amt, amt_text = amount_hit(text)
                amt_in = "body" if amt is not None else None
        mandate = MANDATE.search(text)
        if not mandate and (amt is None or amt < a.min_cr):
            dropped["too small"] += 1
            continue
        # Why it passed, from the file itself: the verb, the figure and where the figure was found.
        why = {
            "verb": verb.group(0),
            "amount_text": amt_text,
            "amount_in": amt_in,
            "mandate": mandate.group(0) if mandate else None,
        }
        if not hit:
            # big enough to matter but in a sector we have no beneficiary map for. Never drop this
            # silently: the run researches it from the universe and adds the names to theme_map.json.
            unmapped.append(
                {
                    "prid": prid,
                    "ministry": ministry,
                    "title": title,
                    "url": f"https://pib.gov.in/PressReleasePage.aspx?PRID={prid}",
                    "outlay_cr": amt,
                    "mandate": bool(mandate),
                    "why": why,
                }
            )
            dropped["no theme"] += 1
            continue
        names = []
        for k in hit:
            for c in tm["themes"][k]["companies"]:
                names.append(dict(c, theme=k))
        seen, uniq = set(), []
        for c in sorted(names, key=lambda c: -(c.get("n_order_filings") or 0)):
            if c["symbol"] in seen:
                continue
            seen.add(c["symbol"])
            uniq.append(c)
        kept.append(
            {
                "prid": prid,
                "ministry": ministry,
                "title": title,
                "url": f"https://pib.gov.in/PressReleasePage.aspx?PRID={prid}",
                "themes": hit,
                "theme_names": [tm["themes"][k]["name"] for k in hit],
                "history": [tm["themes"][k]["history"] for k in hit],
                "outlay_cr": amt,
                "mandate": bool(mandate),
                "why": why,
                "small_caps": [c for c in uniq if c.get("mcap_cr") and 200 <= c["mcap_cr"] <= 7500][:15],
                "companies": uniq[:30],
            }
        )
    kept.sort(key=lambda r: -(r["outlay_cr"] or 0))
    out = {
        "built": stamp,
        "source": "Press Information Bureau, English releases (pib.gov.in/allRel.aspx)",
        "gate": f"a decision verb in the title, a mapped sector, and either a procurement mandate or an outlay of at least Rs {a.min_cr:.0f} cr",
        "scanned": len(rels),
        "opened": opened,
        "kept": len(kept),
        "dropped": dropped,
        "releases": kept,
        "unmapped_releases": unmapped,
    }
    json.dump(out, open(os.path.join(DOCS, "govt.json"), "w"), indent=1, ensure_ascii=False)
    print(
        f"govt: {len(rels)} releases scanned, {opened} opened in full, {len(kept)} kept, {len(unmapped)} big but unmapped  (dropped: {dropped})"
    )
    for r in unmapped:
        print(f"  [UNMAPPED Rs {r['outlay_cr'] or 0:,.0f} cr] {r['title'][:90]}")
    for r in kept:
        amt = f"Rs {r['outlay_cr']:,.0f} cr" if r["outlay_cr"] else ("mandate" if r["mandate"] else "-")
        print(f"  [{amt}] {r['ministry'][:28]:28s} {r['title'][:80]}")
        print(f"      themes {r['themes']} | small caps: " + ", ".join(c["symbol"] for c in r["small_caps"][:10]))


if __name__ == "__main__":
    main()
