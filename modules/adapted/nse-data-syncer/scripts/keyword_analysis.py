from __future__ import annotations

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
Investor Presentation Keyword & Sentiment Analysis

Steps:
  1. For every company in pead_announcements this season, look up investor
     presentations from nse_documents (sync_nse_documents.py keeps it current).
     Falls back to live NSE scraping if not found in DB.
  2. Download each PDF and:
       - count theme keyword occurrences (data centre, AI, defence, ...)
       - run a positive/negative sentiment phrase scan with negation handling
       - normalize hits per 1000 words and compute a sentiment delta
  3. Save results to DB table `presentation_keyword_analysis` and a CSV.

Usage:
  python scripts/keyword_analysis.py [--season-start 2026-04-08] [--out results/keyword_analysis.csv]
  python scripts/keyword_analysis.py --symbol TCS   # single-symbol test mode
  python scripts/keyword_analysis.py --force        # re-process even if already analysed
"""


import argparse
import contextlib
import csv
import io
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import requests

logging.getLogger("pdfminer").setLevel(logging.ERROR)

try:
    import pdfplumber
except ImportError:
    msg = "Install pdfplumber: pip3 install pdfplumber"
    raise SystemExit(msg)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:6XC3bmwDse3Bu6f@database-1.cziuywsuc132.ap-south-1.rds.amazonaws.com:5432/nifty_data?sslmode=require",
)

NSE_API = "https://www.nseindia.com/api/corporate-announcements"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
NSE_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}
PDF_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/pdf,*/*",
    "Referer": "https://www.nseindia.com/",
}

# ── Theme keywords (regex, case-insensitive on lowered text) ──────────────
# \s* matches zero or more spaces so "datacentre" and "data centre" both count,
# and "orderbook" and "order book" both count.
THEME_KEYWORDS = {
    # ── AI / compute ──────────────────────────────────────────────────────────
    "data_centre": [r"data[\s\-]*cent(?:re|er)s?", r"\bdc\b"],
    "liquid_cooling": [
        r"liquid[\s-]?cooling",
        r"immersion[\s-]?cooling",
        r"cold[\s-]?plate",
        r"direct[\s-]?liquid[\s-]?cooling",
        r"\bdlc\b",
    ],
    "ai": [
        r"\bai\b",
        r"artificial\s+intelligence",
        r"machine\s+learning",
        r"generative\s+ai",
        r"\bgenai\b",
        r"\bllm\b",
        r"\bllms\b",
    ],
    "sovereign_ai": [r"sovereign\s+ai", r"sovereign\s+cloud", r"national\s+ai"],
    "agentic_ai": [r"agentic\s+ai", r"agentic", r"\bai[\s-]?agents?\b", r"autonomous\s+ai"],
    "gpu_inference": [
        r"gpu[\s-]?as[\s-]?a[\s-]?service",
        r"\bgpuaas\b",
        r"\bgpu\s+cloud\b",
        r"\binferenc(?:e|ing)\b",
        r"ai\s+inferenc(?:e|ing)",
        r"model\s+serving",
    ],
    "slm": [r"small\s+language\s+model", r"\bslm\b", r"foundation\s+model", r"\bfm\b"],
    "cloud": [r"\bcloud\b"],
    "quantum": [r"quantum\s+comput(?:ing|er)", r"quantum\s+commun", r"quantum\s+technolog"],
    # ── Power / energy infra ─────────────────────────────────────────────────
    "bess": [
        r"\bbess\b",
        r"battery\s+energy\s+storage",
        r"energy\s+storage\s+system",
        r"energy\s+storage",
        r"battery\s+storage",
        r"pumped\s+(?:hydro|storage)",
    ],
    "transmission": [
        r"\btransmission\b",
        r"\bhvdc\b",
        r"high[\s-]voltage\s+direct\s+current",
        r"power\s+transmission",
        r"\bt\s*&\s*d\b",
        r"transmission\s+line",
    ],
    "transformer": [
        r"power\s+transformer",
        r"distribution\s+transformer",
        r"grid\s+transformer",
        r"\btransformer\s+manufactur",
        r"traction\s+transformer",
        r"\bauto[\s-]?transformer\b",
    ],
    "switchgear": [r"switchgear", r"circuit\s+breaker", r"\bgis\b", r"\bais\b", r"gas[\s-]insulated\s+switchgear"],
    "renewable": [r"renewable", r"solar", r"wind\s+energy"],
    "nuclear": [r"nuclear", r"\bsmr\b", r"small\s+modular\s+reactor", r"nuclear\s+power"],
    # ── Semiconductor / electronics ──────────────────────────────────────────
    "semiconductor": [r"semiconductor"],
    "osat": [
        r"\bosat\b",
        r"\batmp\b",
        r"outsourced\s+semiconductor\s+assembly",
        r"chip\s+(?:packaging|assembly)",
        r"advanced\s+packaging",
    ],
    "sic_gan": [
        r"\bsic\b",
        r"silicon\s+carbide",
        r"\bgan\b",
        r"gallium\s+nitride",
        r"wide[\s-]?bandgap",
        r"compound\s+semiconductor",
    ],
    "pcb": [r"\bpcb\b", r"printed\s+circuit\s+board", r"\bhdi\b", r"hdi\s+pcb", r"high[\s-]density\s+interconnect"],
    "optical_fibre": [
        r"optical\s+fib(?:re|er)",
        r"fib(?:re|er)\s+optic",
        r"\bopgw\b",
        r"optic(?:al)?\s+cable",
        r"\bftth\b",
        r"fib(?:re|er)\s+to\s+the",
    ],
    "ems": [
        r"\bems\b",
        r"electronics\s+manufacturing\s+services?",
        r"\bedsm\b",
        r"\besdm\b",
        r"electronics\s+design\s+(?:and\s+)?manufacturing\s+services?",
    ],
    "odm": [r"\bodm\b", r"original\s+design\s+manufactur(?:er|ing)?"],
    "cdmo": [r"\bcdmo\b", r"contract\s+(?:development\s+(?:and\s+)?)?manufacturing\s+organi[sz]ation"],
    # ── Defence / aerospace ───────────────────────────────────────────────────
    "aerospace": [r"aerospace"],
    "defence": [
        r"defenc(?:e|es)",
        r"defens(?:e|es)",
        r"defense",
        r"\bdrdo\b",
        r"defence\s+export",
        r"defense\s+export",
    ],
    "electronic_warfare": [
        r"electronic\s+warfare",
        r"\bew\b",
        r"\baesa\b",
        r"active\s+electronically\s+scanned",
        r"\bradar\b",
        r"electronic\s+counter",
    ],
    "drone": [r"\bdrones?\b", r"\buavs?\b"],
    "anti_drone": [
        r"\banti[\s-]?drones?\b",
        r"\bcounter[\s-]?drones?\b",
        r"\banti[\s-]?uav\b",
        r"\bc[\s-]?uas\b",
        r"\bcounter[\s-]?uas\b",
    ],
    "space": [
        r"\bspace\b",
        r"\bsatcom\b",
        r"satellite\s+commun",
        r"\bleo\b",
        r"\bmeo\b",
        r"\bgeo\b",
        r"launch\s+vehicle",
        r"satellite\s+launch",
    ],
    "kavach": [r"\bkavach\b", r"train\s+collision\s+avoidance", r"\btcas\b", r"automatic\s+train\s+protection"],
    # ── Robotics / automation ────────────────────────────────────────────────
    "robotics": [
        r"robotic(?:s|ally)?",
        r"\brobots?\b",
        r"humanoid",
        r"\bcobots?\b",
        r"industrial\s+automation",
        r"warehouse\s+automation",
        r"factory\s+automation",
    ],
    # ── Geographies ───────────────────────────────────────────────────────────
    "us": [r"\busa\b", r"united\s+states", r"u\.s\.a?"],
    "europe": [
        r"\beurope\b",
        r"\beuropean\b",
        r"european\s+union",
        r"\beu\b",
        r"\buk\b",
        r"united\s+kingdom",
        r"great\s+britain",
    ],
    "china": [r"\bchina\b", r"\bchinese\b", r"\bprc\b"],
    "export": [r"\bexport"],
    # ── Health / pharma ───────────────────────────────────────────────────────
    "glp1": [
        r"\bglp[\s-]?1\b",
        r"semaglutide",
        r"tirzepatide",
        r"obesity\s+drug",
        r"weight[\s-]loss\s+drug",
        r"anti[\s-]?obesity",
    ],
    "rare_earth": [
        r"rare[\s-]earth",
        r"critical\s+mineral",
        r"lithium\s+(?:ion|mining|processing)",
        r"\bcobalt\b",
        r"\btungsten\b",
        r"\bneodymium\b",
    ],
    # ── EV / mobility ─────────────────────────────────────────────────────────
    "ev": [r"\bev\b", r"electric\s+vehicle"],
    # ── Business metrics ─────────────────────────────────────────────────────
    "capex": [r"\bcapex\b", r"capital\s+expenditure"],
    "order_book": [r"order\s*book", r"order\s*inflow", r"\bbacklog\b"],
    "cctv": [r"\bcctv\b", r"\bcameras?\b"],
    "precision_engineering": [r"precision\s*engineering"],
    "best": [r"\bbest\b"],
    "top": [r"\btop\b"],
    "leader": [r"\bleader[s]?\b", r"\bleading\b", r"\bleadership\b"],
    "highest": [r"\bhighest\b"],
}

# ── Sentiment phrase library ───────────────────────────────────────────────
# Each entry is a tuple of tokens (1-3 words). Tokens are lowercase, hyphens
# treated as spaces during tokenization (so "all-time" -> "all", "time").
# Bigrams/trigrams are preferred over noisy unigrams to reduce false positives.

POSITIVE_PHRASES: list[tuple[str, ...]] = [
    # Performance superlatives
    ("highest",),
    ("record",),
    ("all", "time", "high"),
    ("record", "high"),
    ("record", "revenue"),
    ("record", "profit"),
    ("record", "quarter"),
    ("record", "order", "book"),
    ("record", "orderbook"),
    ("record", "ebitda"),
    ("strongest",),
    ("unprecedented",),
    ("exceptional",),
    ("outstanding",),
    ("robust",),
    ("stellar",),
    ("milestone",),
    # Growth language
    ("growth",),
    ("accelerating",),
    ("surge",),
    ("momentum",),
    ("expansion",),
    ("scaling",),
    ("ramp", "up"),
    ("double", "digit"),
    ("multi", "fold"),
    ("exponential",),
    ("traction",),
    ("uptick",),
    ("strong", "growth"),
    ("healthy", "growth"),
    ("growth", "momentum"),
    ("strong", "traction"),
    # Market position
    ("leader",),
    ("leading",),
    ("market", "leader"),
    ("dominant",),
    ("pioneer",),
    ("first", "mover"),
    ("flagship",),
    ("top", "selling"),
    ("fastest", "growing"),
    ("preferred",),
    ("trusted",),
    ("best",),
    ("number", "one"),
    ("no", "1"),
    # Demand / order book
    ("strong", "demand"),
    ("robust", "order", "book"),
    ("healthy", "order", "book"),
    ("robust", "orderbook"),
    ("healthy", "orderbook"),
    ("strong", "orderbook"),
    ("record", "order", "inflow"),
    ("strong", "order", "inflow"),
    ("healthy", "pipeline"),
    ("sold", "out"),
    ("fully", "booked"),
    ("order", "inflow"),
    ("backlog",),
    ("repeat", "orders"),
    ("capacity", "utilization"),
    # Profitability / margins
    ("margin", "expansion"),
    ("improved", "margins"),
    ("operating", "leverage"),
    ("healthy", "margins"),
    ("profitability",),
    ("ebitda", "growth"),
    ("return", "ratios"),
    ("roe", "improvement"),
    # Forward-looking / guidance
    ("confident",),
    ("well", "positioned"),
    ("poised",),
    ("optimistic",),
    ("on", "track"),
    ("ahead", "of", "guidance"),
    ("raised", "guidance"),
    ("upgraded", "outlook"),
    ("visibility",),
    ("structural", "tailwinds"),
    # Strategic / competitive
    ("moat",),
    ("differentiated",),
    ("proprietary",),
    ("breakthrough",),
    ("transformational",),
    ("value", "accretive"),
    ("synergies",),
    ("debottlenecking",),
    ("foray",),
    ("scale", "up"),
    # Capacity / capex
    ("greenfield",),
    ("brownfield",),
    ("commissioned",),
    ("debt", "reduction"),
    ("deleveraging",),
    ("free", "cash", "flow"),
    ("strong", "balance", "sheet"),
    ("capex", "completion"),
    # Custom requested
    ("precision", "engineering"),
]

NEGATIVE_PHRASES: list[tuple[str, ...]] = [
    ("weak",),
    ("weak", "demand"),
    ("decline",),
    ("declining",),
    ("declined",),
    ("decrease",),
    ("decreased",),
    ("below", "expectations"),
    ("challenging",),
    ("headwinds",),
    ("subdued",),
    ("muted",),
    ("underperformance",),
    ("delayed",),
    ("postponed",),
    ("postpone",),
    ("slowdown",),
    ("sluggish",),
    ("loss",),
    ("losses",),
    ("write", "off"),
    ("impairment",),
    ("contraction",),
    ("degrowth",),
    ("de", "growth"),
    ("margin", "pressure"),
    ("cost", "pressure"),
    ("working", "capital", "pressure"),
    ("increased", "debt"),
    ("disappointing",),
    ("lower", "margins"),
    ("missed", "guidance"),
    ("downgrade",),
    ("downgraded",),
    ("cautious",),
    ("uncertain",),
    ("uncertainty",),
    ("volatile",),
    ("volatility",),
    ("weak", "orderbook"),
    ("weak", "order", "book"),
    ("declining", "orderbook"),
]

# Negation / downplaying tokens — if any appear within NEGATION_WINDOW tokens
# before a phrase match, the match is dropped (treated as neutral).
NEGATION_WORDS = {
    "not",
    "no",
    "never",
    "without",
    "lack",
    "lacking",
    "despite",
    "neither",
    "nor",
    "cannot",
    "unable",
}
NEGATION_WINDOW = 3


def clean_db_url(url: str) -> str:
    return re.sub(r'sslmode=["\']?(\w+)["\']?', r"sslmode=\1", url.strip())


class DB:
    """Thin psycopg2 wrapper that transparently reconnects on dropped
    connections (RDS closes idle connections during long PDF-fetch gaps)."""

    def __init__(self, url: str):
        self.url = url
        self._connect()

    def _connect(self):
        self.conn = psycopg2.connect(self.url)
        self.cur = self.conn.cursor()

    def execute(self, sql: str, params=None):
        attempts = 5
        for attempt in range(attempts):
            try:
                self.cur.execute(sql, params)
                return
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                with contextlib.suppress(Exception):
                    self.conn.close()
                if attempt == attempts - 1:
                    raise
                time.sleep(5)
                try:
                    self._connect()
                except psycopg2.OperationalError:
                    pass  # still down; will retry connect on next loop iteration

    def commit(self):
        try:
            self.conn.commit()
        except psycopg2.OperationalError:
            self._connect()

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()

    def close(self):
        self.cur.close()
        self.conn.close()


def fetch_nse_day(date_str: str) -> list[dict]:
    """date_str in DD-MM-YYYY."""
    try:
        resp = requests.get(
            NSE_API,
            params={"index": "equities", "from_date": date_str, "to_date": date_str},
            headers=NSE_HEADERS,
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"    NSE fetch error {date_str}: {e}")
        return []


def find_investor_presentations(symbol: str, result_date: date, season_end: date | None = None) -> list[str]:
    """
    Collect ALL investor-presentation NSE filings within 60 days of result_date.
    Returns every candidate URL so the caller can score each and pick the best.
    60-day window catches late addendums (e.g. SETL's AI-datacenter briefing
    filed 46 days after results).
    """
    end = min(season_end or date.today(), result_date + timedelta(days=60))
    d = result_date
    seen: set[str] = set()
    urls: list[str] = []
    while d <= end:
        if d.weekday() != 6:  # skip Sundays only
            nse_date = d.strftime("%d-%m-%Y")
            anns = fetch_nse_day(nse_date)
            time.sleep(0.4)
            for ann in anns:
                if ann.get("symbol", "").upper() != symbol.upper():
                    continue
                url = ann.get("attchmntFile", "")
                if not url or url in seen:
                    continue
                # Normalize underscores in filename so "Lodha_Investor_Presentation"
                # matches 'investor presentation' the same as plain text does.
                url_text = url.replace("_", " ").replace("-", " ")
                combined = (ann.get("desc", "") + " " + ann.get("attchmntText", "") + " " + url_text).lower()
                # NSE filings use varied labels: "Investor Presentation",
                # "Investor Update", "Investor/Analyst Meet", "Institutional
                # Investor Meet" (Analysts/Institutional Investor Meet/Con. Call
                # Updates), and addendums to earlier presentations.
                if (
                    "investor presentation" in combined
                    or "investors presentation" in combined
                    or "investor update" in combined
                    or "investor meet" in combined
                    or "investor/analyst" in combined
                    or "analyst meet" in combined
                    or "investorpresentation" in combined
                    or "investorupdate" in combined
                    or ("addendum" in combined and "presentation" in combined)
                ):
                    seen.add(url)
                    urls.append(url)
        d += timedelta(days=1)
    return urls


def download_pdf(url: str) -> bytes | None:
    try:
        resp = requests.get(url, headers=PDF_HEADERS, timeout=60)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception as e:
        print(f"    PDF download error: {e}")
    return None


def extract_text(pdf_bytes: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n".join(pages)
    except Exception as e:
        print(f"    PDF parse error: {e}")
        return ""


def count_theme_keywords(text: str) -> dict[str, int]:
    lower = text.lower()
    counts = {}
    for key, patterns in THEME_KEYWORDS.items():
        total = 0
        for pattern in patterns:
            total += len(re.findall(pattern, lower))
        counts[key] = total
    return counts


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics (hyphens become word breaks too,
    so 'all-time' -> ['all', 'time'], 'first-mover' -> ['first', 'mover'])."""
    return re.findall(r"[a-z0-9]+", text.lower())


def count_phrases(words: list[str], phrases: list[tuple[str, ...]], check_negation: bool = True) -> int:
    """
    Count occurrences of any phrase (1-3 token tuples) in `words`.
    If check_negation, a match preceded within NEGATION_WINDOW tokens by a
    negation word ("not strong", "no growth") is dropped.
    """
    by_len: dict[int, set[tuple[str, ...]]] = {}
    for p in phrases:
        by_len.setdefault(len(p), set()).add(p)

    n = len(words)
    total = 0
    for i in range(n):
        for plen, pset in by_len.items():
            if i + plen > n:
                continue
            if tuple(words[i : i + plen]) in pset:
                if check_negation:
                    start = max(0, i - NEGATION_WINDOW)
                    if any(w in NEGATION_WORDS for w in words[start:i]):
                        continue
                total += 1
    return total


def analyse_sentiment(text: str) -> dict:
    words = tokenize(text)
    word_count = len(words)
    pos_hits = count_phrases(words, POSITIVE_PHRASES)
    neg_hits = count_phrases(words, NEGATIVE_PHRASES)

    pos_density = (pos_hits / word_count * 1000) if word_count else 0.0
    neg_density = (neg_hits / word_count * 1000) if word_count else 0.0

    return {
        "word_count": word_count,
        "positive_hits": pos_hits,
        "negative_hits": neg_hits,
        "positive_density": round(pos_density, 2),
        "negative_density": round(neg_density, 2),
        "sentiment_score": round(pos_density - neg_density, 2),
    }


THEME_COLUMNS = list(THEME_KEYWORDS.keys())

_THEME_COL_DEFS = ",\n    ".join(f"{c} INT DEFAULT 0" for c in THEME_COLUMNS)

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS presentation_keyword_analysis (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL,
    company_name    VARCHAR(500),
    result_date     DATE NOT NULL,
    presentation_url TEXT,
    pdf_pages       INT,
    pdf_chars       INT,
    {_THEME_COL_DEFS},
    word_count        INT DEFAULT 0,
    positive_hits     INT DEFAULT 0,
    negative_hits     INT DEFAULT 0,
    positive_density  NUMERIC(8,2) DEFAULT 0,
    negative_density  NUMERIC(8,2) DEFAULT 0,
    sentiment_score   NUMERIC(8,2) DEFAULT 0,
    has_presentation BOOLEAN DEFAULT FALSE,
    analysed_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (symbol, result_date)
);
CREATE INDEX IF NOT EXISTS ix_pka_symbol ON presentation_keyword_analysis (symbol);
"""

# ALTER statements to add new columns to a pre-existing table from prior versions.
_NEW_INT_COLS = (
    "precision_engineering",
    "best",
    "top",
    "leader",
    "order_book",
    "highest",
    "word_count",
    "positive_hits",
    "negative_hits",
    "drone",
    "anti_drone",
    "cctv",
    "bess",
    "ems",
    "odm",
    "pcb",
    "cdmo",
    "us",
    "europe",
    "china",
    # v2 additions
    "liquid_cooling",
    "sovereign_ai",
    "agentic_ai",
    "gpu_inference",
    "slm",
    "quantum",
    "transmission",
    "transformer",
    "switchgear",
    "nuclear",
    "osat",
    "sic_gan",
    "optical_fibre",
    "electronic_warfare",
    "space",
    "kavach",
    "robotics",
    "glp1",
    "rare_earth",
)
ALTER_TABLE_SQL = [
    f"ALTER TABLE presentation_keyword_analysis ADD COLUMN IF NOT EXISTS {c} INT DEFAULT 0" for c in _NEW_INT_COLS
] + [
    "ALTER TABLE presentation_keyword_analysis ADD COLUMN IF NOT EXISTS positive_density NUMERIC(8,2) DEFAULT 0",
    "ALTER TABLE presentation_keyword_analysis ADD COLUMN IF NOT EXISTS negative_density NUMERIC(8,2) DEFAULT 0",
    "ALTER TABLE presentation_keyword_analysis ADD COLUMN IF NOT EXISTS sentiment_score NUMERIC(8,2) DEFAULT 0",
]


def process_one(symbol, company_name, result_date, insert_sql, insert_cols, force, pdf_url=None):
    """Process a single company in its own thread with its own DB connection."""
    result = None
    db = None
    try:
        db = DB(clean_db_url(DB_URL))
        if not force:
            db.execute(
                "SELECT id FROM presentation_keyword_analysis WHERE symbol = %s AND result_date = %s",
                (symbol, result_date),
            )
            if db.fetchone():
                return "skip", symbol, result_date, None

        if pdf_url:
            # URL supplied directly (e.g. from Lambda dispatch) — use it, skip search
            pres_urls = [pdf_url]
        else:
            # Check nse_documents table first, fall back to live NSE scraping
            db.execute(
                """
                SELECT attachment_url FROM nse_documents
                WHERE symbol = %s AND doc_type = 'presentation'
                  AND nse_filed_at >= %s::date
                  AND nse_filed_at <  %s::date + INTERVAL '61 days'
                  AND attachment_url != ''
                ORDER BY nse_filed_at ASC
            """,
                (symbol, result_date, result_date),
            )
            db_urls = [r[0] for r in db.fetchall()]
            pres_urls = db_urls or find_investor_presentations(symbol, result_date)

        if not pres_urls:
            db.execute(
                """
                INSERT INTO presentation_keyword_analysis
                    (symbol, company_name, result_date, has_presentation)
                VALUES (%s, %s, %s, FALSE)
                ON CONFLICT (symbol, result_date) DO NOTHING
            """,
                (symbol, company_name, result_date),
            )
            db.commit()
            result = {
                "symbol": symbol,
                "company_name": company_name,
                "result_date": result_date,
                "has_presentation": False,
                "presentation_url": "",
                "pdf_pages": 0,
                "pdf_chars": 0,
                **dict.fromkeys(THEME_COLUMNS, 0),
                "word_count": 0,
                "positive_hits": 0,
                "negative_hits": 0,
                "positive_density": 0,
                "negative_density": 0,
                "sentiment_score": 0,
            }
            return "no_pres", symbol, result_date, result

        # Download + score each candidate; keep highest total theme keyword count.
        # Tiebreaker: prefer larger documents (more words) so a short mis-filed
        # doc (e.g. 230-word AMS note) doesn't win over a full presentation.
        best_url = best_pdf_bytes = best_text = None
        best_score = -1
        for url in pres_urls:
            pdf_bytes = download_pdf(url)
            if not pdf_bytes:
                continue
            text = extract_text(pdf_bytes)
            theme_score = sum(count_theme_keywords(text).values())
            word_count = len(text.split())
            score = theme_score * 100_000 + word_count
            if score > best_score:
                best_score = score
                best_url = url
                best_pdf_bytes = pdf_bytes
                best_text = text

        if not best_url:
            db.execute(
                """
                INSERT INTO presentation_keyword_analysis
                    (symbol, company_name, result_date, presentation_url, has_presentation)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (symbol, result_date) DO UPDATE
                  SET presentation_url = EXCLUDED.presentation_url
            """,
                (symbol, company_name, result_date, pres_urls[0]),
            )
            db.commit()
            return "dl_fail", symbol, result_date, None

        theme_counts = count_theme_keywords(best_text)
        sentiment = analyse_sentiment(best_text)
        try:
            with pdfplumber.open(io.BytesIO(best_pdf_bytes)) as pdf:
                n_pages = len(pdf.pages)
        except Exception:
            n_pages = 0

        values = [symbol, company_name, result_date, best_url, n_pages, len(best_text)]
        values += [theme_counts[c] for c in THEME_COLUMNS]
        values += [
            sentiment["word_count"],
            sentiment["positive_hits"],
            sentiment["negative_hits"],
            sentiment["positive_density"],
            sentiment["negative_density"],
            sentiment["sentiment_score"],
        ]
        db.execute(insert_sql, values)
        db.commit()

        result = {
            "symbol": symbol,
            "company_name": company_name,
            "result_date": str(result_date),
            "has_presentation": True,
            "presentation_url": best_url,
            "pdf_pages": n_pages,
            "pdf_chars": len(best_text),
            **theme_counts,
            **sentiment,
            "_n_pages": n_pages,
            "_n_candidates": len(pres_urls),
        }
        return "found", symbol, result_date, result
    except Exception as e:
        return "error", symbol, result_date, str(e)
    finally:
        if db:
            db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season-start", default="2026-04-08")
    parser.add_argument("--out", default="results/keyword_analysis.csv")
    parser.add_argument("--symbol", help="Run for a single symbol only (for testing)")
    parser.add_argument(
        "--pdf-url", dest="pdf_url", default=None, help="Direct presentation PDF URL — skips DB/NSE search entirely"
    )
    parser.add_argument("--force", action="store_true", help="Re-process even if already analysed")
    parser.add_argument("--resume-after", help="Skip companies alphabetically <= this symbol")
    parser.add_argument(
        "--missing-only", action="store_true", help="Only process companies without a found presentation"
    )
    parser.add_argument("--workers", type=int, default=4, help="Parallel threads (default 4)")
    args = parser.parse_args()

    season_start = date.fromisoformat(args.season_start)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    db = DB(clean_db_url(DB_URL))
    db.execute(CREATE_TABLE_SQL)
    for stmt in ALTER_TABLE_SQL:
        db.execute(stmt)
    db.commit()

    # Get all (symbol, result_date) pairs announced this season — one row per
    # announcement so both Q4 FY26 and Q1 FY27 results for the same company
    # are processed independently.
    # Source: nse_documents (not pead_announcements) so companies the Lambda
    # filtered out (e.g. not in board_meetings on that day) are still included.
    # Restrict to symbols in the stocks table to skip obscure filings not in
    # our watchlist — this keeps the nightly batch at a manageable size.
    query = """
        SELECT DISTINCT
            nd.symbol,
            COALESCE(s.name, sm.name, nd.symbol) AS company_name,
            DATE(nd.nse_filed_at AT TIME ZONE 'Asia/Kolkata') AS result_date
        FROM nse_documents nd
        LEFT JOIN stocks s    ON s.nse_symbol = nd.symbol
        LEFT JOIN sme_stocks sm ON sm.symbol   = nd.symbol
        WHERE nd.doc_type = 'result'
          AND nd.nse_filed_at >= %s
          AND (s.id IS NOT NULL OR sm.id IS NOT NULL)
        ORDER BY nd.symbol, result_date ASC
    """
    IST_start = datetime.combine(season_start, datetime.min.time()).replace(
        tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    db.execute(query, (IST_start,))
    companies = db.fetchall()

    # Pre-filter already-analysed rows before spawning any threads so we don't
    # pay a DB connection cost per worker for companies that are already done.
    # When --force is set skip this so everything re-processes.
    if not args.force and not args.symbol:
        db.execute("SELECT symbol, result_date FROM presentation_keyword_analysis")
        done = {(r[0].upper(), str(r[1])) for r in db.fetchall()}
        companies = [(s, n, d) for s, n, d in companies if (s.upper(), str(d)) not in done]

    db.close()

    if args.symbol:
        companies = [(s, n, d) for s, n, d in companies if s.upper() == args.symbol.upper()]

    if args.resume_after:
        companies = [(s, n, d) for s, n, d in companies if s.upper() > args.resume_after.upper()]

    if args.missing_only:
        # Check by (symbol, result_date) so Q1 FY27 rows are included even when
        # a company already has a Q4 FY26 presentation recorded.
        db2 = DB(clean_db_url(DB_URL))
        db2.execute("SELECT symbol, result_date FROM presentation_keyword_analysis WHERE has_presentation = TRUE")
        have = {(r[0].upper(), str(r[1])) for r in db2.fetchall()}
        db2.close()
        companies = [(s, n, d) for s, n, d in companies if (s.upper(), str(d)) not in have]
        args.force = True

    total = len(companies)
    print(f"Companies to analyse: {total}  (workers={args.workers})")
    print(f"Output CSV: {out_path}\n")

    insert_cols = [
        "symbol",
        "company_name",
        "result_date",
        "presentation_url",
        "pdf_pages",
        "pdf_chars",
        *THEME_COLUMNS,
        "word_count",
        "positive_hits",
        "negative_hits",
        "positive_density",
        "negative_density",
        "sentiment_score",
    ]
    update_cols = [c for c in insert_cols if c not in ("symbol", "result_date")]
    insert_sql = f"""
        INSERT INTO presentation_keyword_analysis
            ({", ".join(insert_cols)}, has_presentation)
        VALUES ({", ".join(["%s"] * len(insert_cols))}, TRUE)
        ON CONFLICT (symbol, result_date) DO UPDATE SET
            {", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)},
            has_presentation = TRUE,
            analysed_at = NOW()
    """

    rows = []
    counter = [0]
    lock = threading.Lock()

    def run(item):
        symbol, company_name, result_date = item
        try:
            status, sym, rd, data = process_one(
                symbol, company_name, result_date, insert_sql, insert_cols, args.force, getattr(args, "pdf_url", None)
            )
        except Exception as e:
            status, sym, rd, data = "error", symbol, result_date, str(e)
        with lock:
            counter[0] += 1
            n = counter[0]
            if status == "skip":
                print(f"[{n}/{total}] {sym} ({rd}) … already done, skipping")
            elif status == "no_pres":
                print(f"[{n}/{total}] {sym} ({rd}) … no presentation found")
            elif status == "dl_fail":
                print(f"[{n}/{total}] {sym} ({rd}) … download failed")
            elif status == "error":
                print(f"[{n}/{total}] {sym} ({rd}) … ERROR: {data}")
            else:
                r = data
                kw = (
                    ", ".join(f"{k}={v}" for k, v in r.items() if k in THEME_COLUMNS and v and v > 0)
                    or "no theme matches"
                )
                cands = f"{r['_n_candidates']} candidate PDFs" if r["_n_candidates"] > 1 else "found PDF"
                print(
                    f"[{n}/{total}] {sym} ({rd}) … {cands} … "
                    f"{r['_n_pages']}pp, {r['word_count']}w → "
                    f"sentiment={r['sentiment_score']:+.2f} "
                    f"(+{r['positive_hits']}/-{r['negative_hits']}) | {kw}"
                )
                rows.append({k: v for k, v in data.items() if not k.startswith("_")})
        return status

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, companies))

    # Write CSV
    if rows:
        fieldnames = [
            "symbol",
            "company_name",
            "result_date",
            "has_presentation",
            "presentation_url",
            "pdf_pages",
            "pdf_chars",
            *THEME_COLUMNS,
            "word_count",
            "positive_hits",
            "negative_hits",
            "positive_density",
            "negative_density",
            "sentiment_score",
        ]
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV saved: {out_path}")

    # Summary
    conn2 = psycopg2.connect(clean_db_url(DB_URL))
    cur2 = conn2.cursor()
    cur2.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE has_presentation) AS with_presentation,
            COUNT(*) AS total,
            {", ".join(f"SUM({c}) AS {c}" for c in THEME_COLUMNS)},
            AVG(sentiment_score) FILTER (WHERE has_presentation) AS avg_sentiment
        FROM presentation_keyword_analysis
    """)
    row = cur2.fetchone()
    if row:
        print("\n=== Season Summary ===")
        print(f"Companies with investor presentation: {row[0]} / {row[1]}")
        print("Total theme mentions across all presentations:")
        for label, val in zip(THEME_COLUMNS, row[2:-1], strict=False):
            print(f"  {label:24s}: {val or 0}")
        avg_sent = row[-1]
        if avg_sent is not None:
            print(f"\nAverage sentiment score (positive - negative density per 1000 words): {avg_sent:.2f}")

    cur2.close()
    conn2.close()


if __name__ == "__main__":
    main()
