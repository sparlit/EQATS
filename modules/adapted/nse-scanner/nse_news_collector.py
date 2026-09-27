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


"""
nse_news_collector.py — Market Intelligence Collector
=======================================================
Fetches news and corporate data for shortlisted stocks from 3 sources:

    Source 1 — NSE Corporate Announcements API (official, real-time)
               Deals, orders, results, board meetings, fundraising

    Source 2 — NSE Bulk/Block Deal Data (official, same day)
               Who bought/sold, quantity, price — institutional activity

    Source 3 — Google News RSS (free, no API key)
               Headlines from ET, Moneycontrol, Business Standard

Output:
    Dict per symbol with all news combined
    Saved to output/news_DDMMYYYY.json
    Optionally printed as summary per stock

Usage:
    python nse_news_collector.py                    # today's shortlist
    python nse_news_collector.py --symbols DIXON,KAYNES,JYOTHY
    python nse_news_collector.py --date 05-03-2026
    python nse_news_collector.py --days 7           # last 7 days of news

    from nse_news_collector import get_news_for_stocks
    news = get_news_for_stocks(['DIXON', 'KAYNES'], days=30)
"""

import argparse
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import quote

import pandas as pd
import requests

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")
    sys.exit(1)

# ── Settings ──────────────────────────────────────────────────
NEWS_DAYS_DEFAULT = 30  # days of news to fetch per stock
MAX_HEADLINES = 5  # max headlines per stock from Google RSS
REQUEST_DELAY = 1.0  # seconds between requests (be polite)
REQUEST_TIMEOUT = 10  # seconds per request
OUTPUT_DIR = config.OUTPUT_DIR
LOG_DIR = config.LOG_DIR

# ── NSE API Headers (required — NSE blocks without these) ────
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.nseindia.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# ── Logging ───────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "news_collector.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# NSE SESSION — Cookie-based (NSE requires a session cookie)
# ─────────────────────────────────────────────────────────────


def get_nse_session() -> requests.Session:
    """
    Create a requests session with NSE cookies.
    NSE requires visiting the homepage first to get session cookies
    before any API calls will work.
    """
    session = requests.Session()
    session.headers.update(NSE_HEADERS)

    try:
        # Visit homepage to get session cookie
        session.get("https://www.nseindia.com", timeout=REQUEST_TIMEOUT)
        time.sleep(0.5)
        log.info("NSE session established")
    except Exception as e:
        log.warning(f"NSE session setup failed: {e} — API calls may fail")

    return session


# ─────────────────────────────────────────────────────────────
# SOURCE 1 — NSE CORPORATE ANNOUNCEMENTS
# ─────────────────────────────────────────────────────────────


def fetch_nse_announcements(session: requests.Session, symbol: str, days: int = NEWS_DAYS_DEFAULT) -> list:
    """
    Fetch corporate announcements for one stock from NSE API.

    URL: https://www.nseindia.com/api/corporate-announcements
         ?index=equities&symbol={SYMBOL}&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY

    Returns list of dicts:
        symbol, date, subject, description, attachment_url
    """
    results = []

    to_date = date.today()
    from_date = to_date - timedelta(days=days)

    url = (
        f"https://www.nseindia.com/api/corporate-announcements"
        f"?index=equities"
        f"&symbol={symbol}"
        f"&from_date={from_date.strftime('%d-%m-%Y')}"
        f"&to_date={to_date.strftime('%d-%m-%Y')}"
    )

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)

        if resp.status_code != 200:
            log.debug(f"NSE announcements {symbol}: HTTP {resp.status_code}")
            return results

        data = resp.json()

        # NSE returns a list directly or wrapped in 'data' key
        items = data if isinstance(data, list) else data.get("data", [])

        for item in items:
            subject = item.get("subject", "") or item.get("desc", "")
            ann_date = item.get("an_dt", "") or item.get("bm_dt", "")

            if not subject:
                continue

            # Classify announcement type
            ann_type = classify_announcement(subject)

            results.append(
                {
                    "source": "NSE_ANNOUNCEMENT",
                    "symbol": symbol,
                    "date": ann_date,
                    "subject": subject.strip(),
                    "type": ann_type,
                    "attachment": item.get("attchmntFile", ""),
                }
            )

        log.info(f"NSE announcements {symbol}: {len(results)} found")

    except Exception as e:
        log.debug(f"NSE announcements {symbol}: {e}")

    return results


def classify_announcement(subject: str) -> str:
    """
    Classify an announcement subject line into a category.
    Helps prioritise which announcements are market-moving.
    """
    s = subject.lower()

    if any(w in s for w in ["order", "contract", "award", "win", "bagged", "secured"]):
        return "ORDER_WIN"
    if any(w in s for w in ["result", "quarterly", "annual", "q1", "q2", "q3", "q4", "profit", "revenue", "earnings"]):
        return "RESULTS"
    if any(w in s for w in ["dividend", "bonus", "split", "buyback", "rights"]):
        return "CORPORATE_ACTION"
    if any(
        w in s for w in ["acquisition", "merger", "amalgamation", "takeover", "joint venture", "partnership", "mou"]
    ):
        return "DEAL"
    if any(w in s for w in ["fundrais", "qip", "fpo", "ncd", "debenture", "preferential", "allotment"]):
        return "FUNDRAISING"
    if any(w in s for w in ["board meeting", "agm", "egm", "postal ballot"]):
        return "MEETING"
    if any(w in s for w in ["regulatory", "sebi", "penalty", "show cause", "litigation", "court", "arbitration"]):
        return "REGULATORY"
    if any(w in s for w in ["insider", "promoter", "pledge", "encumber"]):
        return "PROMOTER"
    if any(w in s for w in ["expansion", "capex", "plant", "capacity", "commissioning", "production"]):
        return "EXPANSION"

    return "GENERAL"


# ─────────────────────────────────────────────────────────────
# SOURCE 2 — NSE BULK / BLOCK DEALS
# ─────────────────────────────────────────────────────────────


def fetch_bulk_block_deals(session: requests.Session, symbol: str, days: int = 5) -> list:
    """
    Fetch bulk and block deal data for one stock.

    Bulk deals  : > 0.5% of total shares in one transaction
    Block deals : negotiated trades, usually institutional

    Why this matters:
        Fund buying  = confirms your scanner signal
        Promoter sell = red flag even with perfect technicals

    Returns list of dicts:
        date, client, buy_sell, quantity, price, deal_type
    """
    results = []

    # Try bulk deals first
    for deal_type, url in [
        ("BULK", "https://www.nseindia.com/api/bulk-deal-archives?number=10&type=bulk_deals&category=bulk_deals"),
        ("BLOCK", "https://www.nseindia.com/api/block-deal-archives?number=10&type=block_deals&category=block_deals"),
    ]:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue

            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])

            cutoff = date.today() - timedelta(days=days)

            for item in items:
                sym = str(item.get("symbol", "")).upper().strip()
                if sym != symbol.upper():
                    continue

                # Parse date
                deal_date_str = item.get("trade_date", "") or item.get("BD_DT_DATE", "")
                try:
                    deal_date = datetime.strptime(deal_date_str, "%d-%b-%Y").date()
                    if deal_date < cutoff:
                        continue
                except Exception:
                    pass

                qty = item.get("BD_QTY", 0) or item.get("quantity", 0)
                price = item.get("BD_TP_WATP", 0) or item.get("price", 0)
                client = item.get("BD_CLIENT_NAME", "") or item.get("client_name", "")
                buy_sell = item.get("BD_BUY_SELL", "") or item.get("buy_sell", "")

                results.append(
                    {
                        "source": f"NSE_{deal_type}_DEAL",
                        "symbol": symbol,
                        "date": deal_date_str,
                        "client": client.strip(),
                        "buy_sell": buy_sell.strip(),
                        "quantity": qty,
                        "price": price,
                        "deal_type": deal_type,
                        "flag": assess_deal_flag(client, buy_sell),
                    }
                )

        except Exception as e:
            log.debug(f"Bulk/block deal {symbol} {deal_type}: {e}")

    if results:
        log.info(f"Bulk/block deals {symbol}: {len(results)} found in last {days} days")

    return results


def assess_deal_flag(client: str, buy_sell: str) -> str:
    """
    Flag a bulk/block deal as POSITIVE, NEGATIVE, or NEUTRAL.

    POSITIVE: Known institutions, MFs, FIIs buying
    NEGATIVE: Promoter selling, pledged shares being sold
    NEUTRAL:  Unknown client or small transaction
    """
    c = client.lower()
    bs = buy_sell.upper()

    # Promoter selling = red flag
    if bs == "S" and any(w in c for w in ["promoter", "director", "founder", "managing", "chairman"]):
        return "NEGATIVE_PROMOTER_SELL"

    # Institution buying = confirmation
    if bs == "B" and any(
        w in c
        for w in [
            "mutual fund",
            "mf ",
            "aif",
            "fpi",
            "fii",
            "insurance",
            "pension",
            "lic ",
            "sbi ",
            "hdfc",
            "icici",
            "kotak",
            "axis",
            "nippon",
            "mirae",
            "dsp ",
        ]
    ):
        return "POSITIVE_INSTITUTION_BUY"

    # Institution selling = mild negative
    if bs == "S" and any(w in c for w in ["mutual fund", "mf ", "fpi", "fii"]):
        return "NEGATIVE_INSTITUTION_SELL"

    return "NEUTRAL"


# ─────────────────────────────────────────────────────────────
# SOURCE 3 — GOOGLE NEWS RSS
# ─────────────────────────────────────────────────────────────


def fetch_google_news(symbol: str, days: int = 7) -> list:
    """
    Fetch recent news headlines from Google News RSS.
    No API key required. Free and unlimited for personal use.

    URL: https://news.google.com/rss/search?q={SYMBOL}+NSE+stock

    Returns list of dicts:
        title, source, published, url
    """
    results = []

    query = f"{symbol} stock news Moneycontrol Economic Times Business Standard"
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"

    try:
        headers = {"User-Agent": NSE_HEADERS["User-Agent"]}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        if resp.status_code != 200:
            log.debug(f"Google RSS {symbol}: HTTP {resp.status_code}")
            return results

        root = ET.fromstring(resp.content)
        items = root.findall(".//item")

        cutoff = datetime.now() - timedelta(days=days)
        count = 0

        for item in items:
            if count >= MAX_HEADLINES:
                break

            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            source = item.findtext("source", "").strip()

            if not title:
                continue

            # Parse publish date
            try:
                pub_dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                if pub_dt < cutoff:
                    continue
                pub_str = pub_dt.strftime("%d-%b-%Y")
            except Exception:
                pub_str = pub_date[:16]

            # Skip generic market news not about this stock
            if symbol.upper() not in title.upper() and symbol.upper() not in link.upper():
                # Still include if no better match found
                pass

            results.append(
                {
                    "source": "GOOGLE_NEWS",
                    "symbol": symbol,
                    "date": pub_str,
                    "title": title,
                    "news_source": source,
                    "url": link,
                    "sentiment": classify_headline_sentiment(title),
                }
            )
            count += 1

        log.info(f"Google RSS {symbol}: {len(results)} headlines")

    except Exception as e:
        log.debug(f"Google RSS {symbol}: {e}")

    return results


def classify_headline_sentiment(title: str) -> str:
    """
    Simple keyword-based sentiment for a headline.
    Not ML — just fast pattern matching.
    """
    t = title.lower()

    positive = [
        "surge",
        "rally",
        "jump",
        "gain",
        "rise",
        "high",
        "record",
        "profit",
        "order",
        "win",
        "award",
        "deal",
        "partnership",
        "upgrade",
        "buy",
        "outperform",
        "strong",
        "growth",
        "beat",
    ]

    negative = [
        "fall",
        "drop",
        "crash",
        "plunge",
        "loss",
        "down",
        "concern",
        "risk",
        "warning",
        "fraud",
        "probe",
        "penalty",
        "sebi",
        "sell",
        "downgrade",
        "underperform",
        "weak",
        "miss",
        "cut",
    ]

    pos_count = sum(1 for w in positive if w in t)
    neg_count = sum(1 for w in negative if w in t)

    if pos_count > neg_count:
        return "POSITIVE"
    if neg_count > pos_count:
        return "NEGATIVE"
    return "NEUTRAL"


# ─────────────────────────────────────────────────────────────
# COMBINE — All sources for one stock
# ─────────────────────────────────────────────────────────────


def get_news_for_symbol(session: requests.Session, symbol: str, days: int = NEWS_DAYS_DEFAULT) -> dict:
    """
    Collect all news for one stock from all 3 sources.

    Args:
        session : NSE requests session (shared across stocks)
        symbol  : NSE stock symbol e.g. 'DIXON'
        days    : how many days back to look

    Returns:
        dict with:
            symbol, announcements, deals, headlines,
            summary, flags, has_news
    """
    log.info(f"Collecting news: {symbol}")

    # Fetch all sources
    announcements = fetch_nse_announcements(session, symbol, days)
    time.sleep(REQUEST_DELAY)

    deals = fetch_bulk_block_deals(session, symbol, min(days, 10))
    time.sleep(REQUEST_DELAY)

    headlines = fetch_google_news(symbol, min(days, 7))
    # No sleep after last call

    # ── Generate summary flags ──
    flags = []

    # Check for high-priority announcements
    priority_types = ["ORDER_WIN", "DEAL", "RESULTS", "FUNDRAISING", "EXPANSION"]
    for ann in announcements:
        if ann["type"] in priority_types:
            flags.append(f"ANN:{ann['type']} — {ann['subject'][:60]}")

    # Check for regulatory / promoter issues
    risk_types = ["REGULATORY", "PROMOTER"]
    for ann in announcements:
        if ann["type"] in risk_types:
            flags.append(f"RISK:{ann['type']} — {ann['subject'][:60]}")

    # Check deal flags
    for deal in deals:
        flag = deal.get("flag", "NEUTRAL")
        if flag != "NEUTRAL":
            direction = "BUY" if "BUY" in flag else "SELL"
            category = "INSTITUTION" if "INSTITUTION" in flag else "PROMOTER"
            flags.append(
                f"DEAL:{category}_{direction} — {deal['client'][:40]} qty={deal['quantity']:,} @ {deal['price']}"
            )

    # Overall sentiment from headlines
    sentiments = [h["sentiment"] for h in headlines]
    pos_count = sentiments.count("POSITIVE")
    neg_count = sentiments.count("NEGATIVE")
    news_tone = "POSITIVE" if pos_count > neg_count else "NEGATIVE" if neg_count > pos_count else "NEUTRAL"

    has_news = bool(announcements or deals or headlines)

    return {
        "symbol": symbol,
        "collected_at": datetime.now().isoformat(),
        "days_back": days,
        "announcements": announcements,
        "deals": deals,
        "headlines": headlines,
        "flags": flags,
        "news_tone": news_tone,
        "has_news": has_news,
        "ann_count": len(announcements),
        "deal_count": len(deals),
        "headline_count": len(headlines),
    }


# ─────────────────────────────────────────────────────────────
# MAIN — All stocks
# ─────────────────────────────────────────────────────────────


def get_news_for_stocks(symbols: list, days: int = NEWS_DAYS_DEFAULT) -> dict:
    """
    Collect news for a list of stock symbols.

    Args:
        symbols : list of NSE symbols e.g. ['DIXON', 'KAYNES']
        days    : days of history to fetch

    Returns:
        Dict: {symbol: news_dict}
    """
    print(f"\n{'=' * 56}")
    print("  NSE News Collector")
    print(f"  Stocks  : {len(symbols)}")
    print(f"  Days    : {days}")
    print(f"{'=' * 56}")

    session = get_nse_session()
    results = {}

    for i, symbol in enumerate(symbols, 1):
        print(f"\n  [{i}/{len(symbols)}] {symbol}...")
        try:
            news = get_news_for_symbol(session, symbol, days)
            results[symbol] = news

            # Print mini summary
            print(f"    Announcements : {news['ann_count']}")
            print(f"    Bulk/Block    : {news['deal_count']}")
            print(f"    Headlines     : {news['headline_count']}")
            print(f"    News tone     : {news['news_tone']}")
            if news["flags"]:
                for flag in news["flags"][:3]:
                    print(f"    FLAG: {flag}")

        except Exception as e:
            log.exception(f"Failed to collect news for {symbol}: {e}")
            results[symbol] = {
                "symbol": symbol,
                "error": str(e),
                "has_news": False,
                "flags": [],
            }

        # Rate limiting between stocks
        if i < len(symbols):
            time.sleep(REQUEST_DELAY)

    return results


# ─────────────────────────────────────────────────────────────
# SAVE / LOAD
# ─────────────────────────────────────────────────────────────


def save_news(news_data: dict, report_date: date | None = None) -> str:
    """Save collected news to JSON file in output/ folder."""
    if report_date is None:
        report_date = date.today()

    fname = f"news_{report_date.strftime('%d%m%Y')}.json"
    fpath = os.path.join(OUTPUT_DIR, fname)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(news_data, f, indent=2, ensure_ascii=False, default=str)

    log.info(f"News saved: {fpath}")
    print(f"\n  Saved: {fpath}")
    return fpath


def load_news(report_date: date | None = None) -> dict:
    """Load previously saved news from JSON file."""
    if report_date is None:
        report_date = date.today()

    fname = f"news_{report_date.strftime('%d%m%Y')}.json"
    fpath = os.path.join(OUTPUT_DIR, fname)

    if not os.path.exists(fpath):
        return {}

    with open(fpath, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────
# PRINT SUMMARY
# ─────────────────────────────────────────────────────────────


def print_news_summary(news_data: dict):
    """Print a readable summary of collected news."""
    print(f"\n{'#' * 56}")
    print("  NEWS INTELLIGENCE SUMMARY")
    print(f"{'#' * 56}")

    for symbol, data in news_data.items():
        if "error" in data:
            print(f"\n  {symbol}: ERROR — {data['error']}")
            continue

        tone_icon = {"POSITIVE": "+", "NEGATIVE": "!", "NEUTRAL": "~"}.get(data.get("news_tone", "NEUTRAL"), "~")

        print(f"\n  {symbol}  [{tone_icon}] {data.get('news_tone', 'NEUTRAL')}")
        print(f"  {'─' * 40}")

        # Top announcements
        for ann in data.get("announcements", [])[:3]:
            print(f"  [ANN] {ann.get('date', '')[:10]}  {ann.get('type', ''):<20}  {ann.get('subject', '')[:50]}")

        # Deals
        for deal in data.get("deals", []):
            flag = deal.get("flag", "NEUTRAL")
            icon = "+" if "BUY" in flag else "-" if "SELL" in flag else "~"
            print(
                f"  [DEAL {icon}] {deal.get('date', '')[:10]}  "
                f"{deal.get('buy_sell', ''):<4}  "
                f"{deal.get('client', '')[:35]:<35}  "
                f"qty={deal.get('quantity', 0):,}"
            )

        # Top headlines
        for hl in data.get("headlines", [])[:3]:
            icon = "+" if hl["sentiment"] == "POSITIVE" else "-" if hl["sentiment"] == "NEGATIVE" else "~"
            print(f"  [NEWS {icon}] {hl.get('date', '')[:10]}  {hl.get('title', '')[:55]}")

        # Risk flags
        risk_flags = [f for f in data.get("flags", []) if "RISK" in f]
        if risk_flags:
            for rf in risk_flags:
                print(f"  *** RISK FLAG: {rf}")

    print(f"\n{'#' * 56}\n")


# ─────────────────────────────────────────────────────────────
# INTEGRATE WITH SCANNER — Add news flags to scanner output
# ─────────────────────────────────────────────────────────────


def enrich_scanner_results(scanner_df: pd.DataFrame, news_data: dict) -> pd.DataFrame:
    """
    Add news intelligence columns to scanner output DataFrame.

    Adds:
        news_tone     : POSITIVE / NEGATIVE / NEUTRAL
        news_flags    : pipe-separated key flags
        ann_count     : number of announcements in last 30 days
        deal_flag     : institution buying, promoter selling etc.
        has_risk      : True if any regulatory/promoter risk found

    Args:
        scanner_df : output from nse_scanner.scan_stocks()
        news_data  : output from get_news_for_stocks()

    Returns:
        Enriched DataFrame
    """
    df = scanner_df.copy()

    df["news_tone"] = "NEUTRAL"
    df["news_flags"] = ""
    df["ann_count"] = 0
    df["deal_flag"] = ""
    df["has_risk"] = False

    for idx, row in df.iterrows():
        sym = row["symbol"]
        data = news_data.get(sym, {})

        if not data or "error" in data:
            continue

        df.at[idx, "news_tone"] = data.get("news_tone", "NEUTRAL")
        df.at[idx, "ann_count"] = data.get("ann_count", 0)

        flags = data.get("flags", [])
        risk_flag = any("RISK" in f for f in flags)
        deal_flag = next((f for f in flags if "DEAL" in f), "")

        df.at[idx, "news_flags"] = " | ".join(flags[:2])
        df.at[idx, "deal_flag"] = deal_flag
        df.at[idx, "has_risk"] = risk_flag

    return df


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="NSE News Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python nse_news_collector.py
  python nse_news_collector.py --symbols DIXON,KAYNES,JYOTHY
  python nse_news_collector.py --date 05-03-2026
  python nse_news_collector.py --days 7
        """,
    )

    parser.add_argument("--symbols", type=str, help="Comma-separated symbols e.g. DIXON,KAYNES")
    parser.add_argument("--date", type=str, help="Scan date DD-MM-YYYY (default: today)")
    parser.add_argument(
        "--days", type=int, default=NEWS_DAYS_DEFAULT, help=f"Days of news to fetch (default: {NEWS_DAYS_DEFAULT})"
    )
    parser.add_argument("--save", action="store_true", help="Save results to output/news_DDMMYYYY.json")

    args = parser.parse_args()

    # Parse date
    report_date = date.today()
    if args.date:
        for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]:
            try:
                report_date = datetime.strptime(args.date, fmt).date()
                break
            except ValueError:
                pass

    # Get symbols
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        # Load from today's scanner output (top HC + watchlist stocks)
        try:
            from nse_scanner import scan_stocks

            print("Loading shortlist from scanner...")
            results = scan_stocks(scan_date=report_date)

            if results.empty:
                print("No scanner results. Use --symbols to specify stocks.")
                sys.exit(1)

            # Take HC + Watchlist stocks only
            if "conviction" in results.columns:
                shortlist = results[results["conviction"].isin(["HIGH CONVICTION", "Watchlist"])]["symbol"].tolist()
            else:
                shortlist = results.head(10)["symbol"].tolist()

            symbols = shortlist[:15]  # cap at 15 to avoid rate limiting
            print(f"Using scanner shortlist: {symbols}")

        except Exception as e:
            print(f"Could not load scanner results: {e}")
            print("Use --symbols SYMBOL1,SYMBOL2 to specify stocks directly")
            sys.exit(1)

    if not symbols:
        print("No symbols to process")
        sys.exit(1)

    # Collect news
    news_data = get_news_for_stocks(symbols, days=args.days)

    # Print summary
    print_news_summary(news_data)

    # Save if requested
    if args.save:
        save_news(news_data, report_date)

    print(f"  Done. {len(news_data)} stocks processed.")


if __name__ == "__main__":
    main()
