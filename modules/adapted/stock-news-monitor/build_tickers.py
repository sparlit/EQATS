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


"""Regenerate tickers.csv from the trading bot's universe.

Why this exists: the monitor watched 56 NIFTY-50 names while the trading bot
picks momentum leaders from 147 (NATIONALUM, ADANIPOWER, BHEL, NMDC...). Measured
2026-07-30: ZERO of the ₹1k news bot's holdings were in the news universe, so the
news overlay was a no-op on the exact stocks it was supposed to inform.

Company names come from yfinance (longName), so the alias list doesn't depend on
anyone typing 147 company names from memory. Curated aliases in CURATED win —
they encode brand names and abbreviations no API returns ("HUL", "L&T",
"Royal Enfield").

Aliases too generic to match safely on their own are listed in BLOCKLIST: "Titan",
"Apollo", "Century", "Sun", "Trent", "Page" are ordinary English words and would
fire on unrelated news. Those tickers keep only their unambiguous long forms.

A curated alias may also be a raw regex, written `re:<pattern>` (see
newslib.RE_ALIAS). That exists for one situation: an abbreviation headlines
actually use, whose prefix belongs to a DIFFERENT listed company. Only SBIN needs
it today. Prefer a longer literal alias over a regex whenever one works.

Run this, eyeball the diff, then `python migrate.py` to re-scan history against
the new aliases.

Usage: python build_tickers.py [--out tickers.csv]
"""
import csv
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
BOT_UNIVERSE = BASE.parent / "trading-bot" / "src" / "universe.py"

# Single words that are ordinary English or shared across many companies. An
# alias equal to one of these is dropped; longer aliases containing them are fine
# ("Titan Company" stays, "Titan" goes).
BLOCKLIST = {
    "titan",
    "apollo",
    "century",
    "sun",
    "trent",
    "page",
    "power",
    "grid",
    "india",
    "indian",
    "national",
    "bharat",
    "united",
    "new",
    "max",
    "one",
    "gail",
    "canara",
    "union",
    "central",
    "federal",
    "city",
    "prestige",
    "oil",
    "steel",
    "motors",
    "bank",
    "finance",
    "cement",
    "pharma",
    "tech",
    "life",
    "auto",
    "petroleum",
    "chemicals",
    "industries",
    "enterprises",
    # Added 2026-07-31 (see meta['alias_rev'] and LESSONS.md L21). Tail-word
    # peeling manufactured all four of these and they were the worst false
    # positives in the corpus. Measured over 12 132 articles:
    #   "adani"      95 title hits, only 27 name Adani Ent — the other 68 are
    #                ADANIGREEN / ADANIPORTS / ADANIENSOL / ADANIPOWER, i.e.
    #                other LISTED companies, so this was not noise, it was
    #                systematic mis-attribution to a sibling.
    #   "coal"       70 hits vs 53 for "Coal India" — the rest are sector and
    #                macro stories ("India's coal production up 5.35%").
    #   "reliance"   24 hits, ~12 false: Reliance Power / Reliance Infra (both
    #                separate listings) and the ordinary English noun
    #                ("flag reliance on unsecured lending", "self-reliance in
    #                defence" — \b fires after the hyphen).
    #   "persistent" 6 hits, correct today, but "persistent inflation" is one
    #                headline away and there is no upside: "Persistent Systems"
    #                is how headlines write it.
    # Each ticker keeps its unambiguous long form. Bare "ACC" (7 hits, 2 of them
    # Advanced Chemistry Cell battery stories) was left in place deliberately:
    # ACC Ltd has no longer form that headlines use, so blocking it would kill
    # the symbol outright for a 2-in-7 error rate.
    "adani",
    "coal",
    "reliance",
    "persistent",
}

# Brand/abbreviation aliases no data source returns. Merged with generated ones.
CURATED = {
    "RELIANCE.NS": ["Reliance Industries", "RIL"],
    "TCS.NS": ["Tata Consultancy", "TCS"],
    "HDFCBANK.NS": ["HDFC Bank"],
    "ICICIBANK.NS": ["ICICI Bank"],
    "INFY.NS": ["Infosys"],
    "BHARTIARTL.NS": ["Bharti Airtel", "Airtel"],
    # "SBI" must be second, not first: llm_analyst.company_names() uses alias[0]
    # as the display name in the prompt, and a regex is not a company name.
    # Indian headlines write "SBI" and nothing else — SBIN matched ZERO headlines
    # in the whole corpus before this (NM-17) while 54 titles said "SBI". A bare
    # alias is impossible because "SBI Card(s)" -> SBICARD.NS and "SBI Life" ->
    # SBILIFE.NS are separate listings, hence the two negative lookaheads. See
    # newslib.RE_ALIAS for why the guard cannot use a `|` alternation.
    "SBIN.NS": ["State Bank of India", r"re:\bSBI\b(?!\s+Cards?\b)(?!\s+Life\b)", "SBI Bank"],
    "HINDUNILVR.NS": ["Hindustan Unilever", "HUL"],
    "LT.NS": ["Larsen & Toubro", "Larsen and Toubro", "L&T"],
    "KOTAKBANK.NS": ["Kotak Mahindra Bank", "Kotak Bank"],
    "MARUTI.NS": ["Maruti Suzuki", "Maruti"],
    "SUNPHARMA.NS": ["Sun Pharma", "Sun Pharmaceutical"],
    "TITAN.NS": ["Titan Company"],
    "ULTRACEMCO.NS": ["UltraTech Cement", "UltraTech"],
    "BAJFINANCE.NS": ["Bajaj Finance"],
    "ONGC.NS": ["ONGC", "Oil and Natural Gas Corporation"],
    # "Tata Motors" belongs to TMPV only. yfinance returns "Tata Motors Limited"
    # for BOTH post-demerger tickers, which made every Tata Motors headline
    # double-count across two symbols (LESSONS.md L14).
    "TMPV.NS": ["Tata Motors PV", "Tata Motors", "Tata Motors Passenger"],
    "TMCV.NS": ["Tata Motors CV", "Tata Motors Commercial"],
    "M&M.NS": ["Mahindra & Mahindra", "Mahindra and Mahindra", "M&M"],
    "HCLTECH.NS": ["HCL Technologies", "HCLTech", "HCL Tech"],
    "EICHERMOT.NS": ["Eicher Motors", "Royal Enfield"],
    "APOLLOHOSP.NS": ["Apollo Hospitals"],
    "DIVISLAB.NS": ["Divi's Lab", "Divis Lab", "Divi's Laboratories"],
    "HEROMOTOCO.NS": ["Hero MotoCorp", "Hero Moto"],
    "DRREDDY.NS": ["Dr Reddy", "Dr. Reddy", "Dr Reddy's"],
    "NESTLEIND.NS": ["Nestle India", "Nestle"],
    "ETERNAL.NS": ["Eternal", "Zomato", "Blinkit"],
    "NATIONALUM.NS": ["National Aluminium", "NALCO"],
    "ADANIPOWER.NS": ["Adani Power"],
    # "Adani Ent" is a separate alias, not a prefix match: \b after "Ent" cannot
    # fire inside "Enterprises". Headlines abbreviate it ("Adani Ent Q1 result:
    # Firm posts Rs 1,160 cr loss"), and those two rows were the only genuinely
    # correct ones among the 58 that bare "Adani" was carrying.
    "ADANIENT.NS": ["Adani Enterprises", "Adani Ent"],
    "ADANIPORTS.NS": ["Adani Ports", "Adani Ports SEZ"],
    "ADANIGREEN.NS": ["Adani Green"],
    "BHEL.NS": ["Bharat Heavy Electricals", "BHEL"],
    "NMDC.NS": ["NMDC"],
    "SAIL.NS": ["Steel Authority of India", "SAIL"],
    "HINDZINC.NS": ["Hindustan Zinc"],
    "VEDL.NS": ["Vedanta"],
    "FEDERALBNK.NS": ["Federal Bank"],
    "MOTHERSON.NS": ["Samvardhana Motherson", "Motherson Sumi"],
    "NYKAA.NS": ["Nykaa", "FSN E-Commerce"],
    "AUROPHARMA.NS": ["Aurobindo Pharma"],
    "HINDPETRO.NS": ["Hindustan Petroleum", "HPCL"],
    "BPCL.NS": ["Bharat Petroleum", "BPCL"],
    "IOC.NS": ["Indian Oil", "IOCL"],
    "POWERGRID.NS": ["Power Grid Corporation", "PowerGrid"],
    "COALINDIA.NS": ["Coal India"],
    "PAYTM.NS": ["Paytm", "One 97 Communications"],
    # Blocklisted words kept deliberately: in an Indian markets feed these are
    # unambiguous, and global feeds skip ticker matching entirely.
    "TRENT.NS": ["Trent", "Westside", "Zudio"],
    "PAGEIND.NS": ["Page Industries", "Jockey India"],
    "GAIL.NS": ["GAIL", "GAIL India"],
    "CANBK.NS": ["Canara Bank"],
    "UNIONBANK.NS": ["Union Bank of India"],
    # Names headlines use that no legal name yields, found by scanning 5 104
    # ticker-unmatched Indian-feed headlines for recurring company names.
    "TATAPOWER.NS": ["Tata Power"],
    "LICI.NS": ["LIC", "Life Insurance Corporation"],
    "SBICARD.NS": ["SBI Card", "SBI Cards"],
    "INDIGO.NS": ["IndiGo", "InterGlobe Aviation"],
    "BEL.NS": ["Bharat Electronics", "BEL"],
    "IRCTC.NS": ["IRCTC", "Indian Railway Catering"],
    "DIVISLAB.NS": ["Divi's Laboratories", "Divis Laboratories", "Divi's Lab", "Divis Lab"],
    "MARICO.NS": ["Marico"],
    "DABUR.NS": ["Dabur"],
    "SIEMENS.NS": ["Siemens India", "Siemens Ltd"],
    # Liquid names the momentum universe omits but the news feeds discuss often.
    # Harmless to the bot (it only looks up its own candidates) and they enrich
    # the ML dataset.
    "COFORGE.NS": ["Coforge"],
    "PERSISTENT.NS": ["Persistent Systems"],
    "JSWENERGY.NS": ["JSW Energy"],
    "VBL.NS": ["Varun Beverages"],
}

# Sector labels drive autotrader's learned sector weights; unknown -> "other".
SECTOR_MAP = {
    "Technology": "it",
    "Financial Services": "financials",
    "Basic Materials": "metals",
    "Energy": "energy",
    "Utilities": "energy",
    "Consumer Cyclical": "consumer",
    "Consumer Defensive": "fmcg",
    "Healthcare": "pharma",
    "Industrials": "infra",
    "Communication Services": "telecom",
    "Real Estate": "infra",
}

_SUFFIXES = re.compile(
    r"\s+(limited|ltd\.?|corporation|corp\.?|company|co\.?|inc\.?|plc)$", re.IGNORECASE
)

# Generic tail words that appear in a legal name but almost never in a headline:
# "The Tata Power Company" is written "Tata Power", "Hindalco Industries" is
# "Hindalco". Stripping these produced 20% dead tickers when it was missing —
# TATAPOWER had 33 headline mentions and zero matches (LESSONS.md L14).
_TAIL_WORDS = re.compile(
    r"\s+(company|industries|enterprises?|technologies|services|systems|"
    r"laboratories|labs|holdings|ventures|international|india|"
    r"corporation|solutions|products|group)$",
    re.IGNORECASE,
)
_LEADING_THE = re.compile(r"^the\s+", re.IGNORECASE)


def short_forms(name):
    """Progressively shorter headline-style variants of a legal company name.

    Each variant is still filtered through BLOCKLIST by the caller, so this can
    propose "Titan" from "Titan Company" and have it correctly rejected, while
    "Tata Power" from "The Tata Power Company" is kept.
    """
    out = []
    # Strip the legal suffix FIRST. The tail-word regex is anchored at the end,
    # so "Havells India Limited" would otherwise never reduce to "Havells".
    base = _SUFFIXES.sub("", (name or "").strip()).strip(" .,")
    n = _LEADING_THE.sub("", base)
    if n and n.lower() != base.lower():
        out.append(n)
    for _ in range(3):  # peel at most three generic tails
        shorter = _TAIL_WORDS.sub("", n).strip()
        if shorter == n or not shorter:
            break
        out.append(shorter)
        n = shorter
    return out


def bot_universe():
    """Read TICKERS out of the trading bot without importing pandas etc."""
    src = BOT_UNIVERSE.read_text(encoding="utf-8")
    names = re.search(r"_NAMES\s*=\s*\[(.*?)\]", src, re.DOTALL)
    if not names:
        raise SystemExit(f"could not parse _NAMES from {BOT_UNIVERSE}")
    # Strip comments first: universe.py documents the Tata Motors rename with a
    # quoted "TATAMOTORS" inside a comment, which a naive scan reads as a ticker.
    body = re.sub(r"#[^\n]*", "", names.group(1))
    return [n + ".NS" for n in re.findall(r'"([^"]+)"', body)]


def clean_aliases(raw, curated=()):
    """Drop blank, too-short, duplicate and blocklisted aliases.

    The blocklist guards AUTO-GENERATED names only. A curated alias is a
    deliberate human call ("Trent", "SAIL") and is always kept.
    """
    out, seen = [], set()
    for a in curated:
        # Verbatim: a curated alias is already the intended form. Suffix-stripping
        # it turns "Titan Company" into bare "Titan" — the exact generic-word
        # false positive the blocklist exists to prevent.
        a = (a or "").strip()
        if a and a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    for a in raw:
        a = _SUFFIXES.sub("", (a or "").strip()).strip(" .,")
        key = a.lower()
        if not a or len(a) < 3 or key in BLOCKLIST or key in seen:
            continue
        # Peeling a tail word can leave a dangling connective
        # ("Life Insurance Corporation of India" -> "...Corporation of").
        if key.split()[-1] in {"of", "and", "&", "the", "for", "in", "on"}:
            continue
        seen.add(key)
        out.append(a)
    return out


def main():
    out_path = BASE / (
        sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "tickers.csv"
    )
    symbols = bot_universe()
    # keep any curated symbol the bot universe doesn't carry (e.g. PAYTM)
    for extra in CURATED:
        if extra not in symbols:
            symbols.append(extra)
    print(f"Building aliases for {len(symbols)} symbols...")

    import yfinance as yf

    rows, no_data = [], []
    for i, sym in enumerate(symbols, 1):
        long_name = sector = None
        try:
            info = yf.Ticker(sym).get_info()
            long_name = info.get("longName") or info.get("shortName")
            sector = info.get("sector")
        except Exception:
            pass
        generated = [long_name] + short_forms(long_name or "")
        aliases = clean_aliases(generated, curated=CURATED.get(sym, []))
        if not aliases:
            no_data.append(sym)
            continue
        rows.append(
            {"symbol": sym, "aliases": "|".join(aliases), "sector": SECTOR_MAP.get(sector, "other")}
        )
        if i % 25 == 0:
            print(f"  ...{i}/{len(symbols)}")

    # Resolve cross-symbol collisions: an alias claimed by two tickers is kept
    # only by the one that curated it, and dropped from the other. yfinance
    # returns "Tata Motors Limited" for BOTH post-demerger symbols, so without
    # this every Tata Motors headline double-counts (LESSONS.md L14).
    owner = {a.strip().lower(): s for s, al in CURATED.items() for a in al}
    claims = {}
    for r in rows:
        for a in r["aliases"].split("|"):
            claims.setdefault(a.strip().lower(), []).append(r["symbol"])
    contested = {a: syms for a, syms in claims.items() if len(set(syms)) > 1}
    for r in rows:
        keep = []
        for a in r["aliases"].split("|"):
            k = a.strip().lower()
            if k in contested and owner.get(k, r["symbol"]) != r["symbol"]:
                print(
                    f"  dropped contested alias '{a}' from {r['symbol']} (owned by {owner.get(k)})"
                )
                continue
            keep.append(a)
        r["aliases"] = "|".join(keep)
    rows = [r for r in rows if r["aliases"]]

    rows.sort(key=lambda r: r["symbol"])
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "aliases", "sector"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} tickers to {out_path.name}.")
    if no_data:
        print(f"  no name resolved (skipped): {', '.join(no_data)}")
    print("Next: eyeball the file, then `python migrate.py` to rescan history.")


if __name__ == "__main__":
    main()
