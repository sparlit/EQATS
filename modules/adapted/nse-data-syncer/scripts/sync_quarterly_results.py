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


#!/usr/bin/env python3
"""
Scrape quarterly results for a stock from Screener.in and store in DB.

Usage:
    python sync_quarterly_results.py --symbol RELIANCE

Requires env vars (in web/.env or environment):
    DATABASE_URL        PostgreSQL connection string
    SCREENER_USERNAME   Screener.in username/email
    SCREENER_PASSWORD   Screener.in password
"""

import argparse
import json
import logging
import os
import re
import sys
from urllib.parse import urlparse

import psycopg2
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Load env from web/.env (works when running from repo root or scripts/)
_script_dir = os.path.dirname(os.path.abspath(__file__))
for _candidate in [
    os.path.join(_script_dir, "..", "web", ".env"),
    os.path.join(_script_dir, "..", ".env"),
]:
    if os.path.exists(_candidate):
        load_dotenv(_candidate)
        break

BASE_URL = "https://www.screener.in"


def login_to_screener() -> requests.Session:
    username = os.environ.get("SCREENER_USERNAME")
    password = os.environ.get("SCREENER_PASSWORD")
    if not username or not password:
        msg = "SCREENER_USERNAME and SCREENER_PASSWORD must be set in web/.env"
        raise RuntimeError(msg)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
    )

    resp = session.get(f"{BASE_URL}/login/", timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if not csrf_input:
        msg = "Could not find CSRF token on Screener.in login page"
        raise RuntimeError(msg)

    resp = session.post(
        f"{BASE_URL}/login/",
        data={
            "csrfmiddlewaretoken": csrf_input["value"],
            "username": username,
            "password": password,
            "next": "/",
        },
        headers={"Referer": f"{BASE_URL}/login/"},
        timeout=15,
        allow_redirects=True,
    )
    resp.raise_for_status()

    if "/login/" in resp.url:
        msg = "Login failed — check SCREENER_USERNAME / SCREENER_PASSWORD"
        raise RuntimeError(msg)

    logger.info("Logged into Screener.in successfully")
    return session


def _parse_number(text: str):
    """Parse '1,234.56' or '12.5%' → float, or None."""
    if not text:
        return None
    cleaned = text.strip().replace(",", "").replace("%", "").replace("\xa0", "")
    # Handle negative in parentheses: (123) → -123
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


def _quarter_info(col_header: str):
    """
    'Jun 2024' → (quarter='Jun 2024', fy_year=2025, quarter_number=1)

    Indian fiscal year quarters:
        Q1 Apr–Jun  Q2 Jul–Sep  Q3 Oct–Dec  Q4 Jan–Mar
    FY year is the year in which March falls.
    e.g. 'Mar 2024' → FY2024 Q4; 'Jun 2024' → FY2025 Q1
    """
    MONTH_MAP = {
        "jan": (4, 0),
        "feb": (4, 0),
        "mar": (4, 0),  # Q4, same calendar year
        "apr": (1, 1),
        "may": (1, 1),
        "jun": (1, 1),  # Q1, +1 year
        "jul": (2, 1),
        "aug": (2, 1),
        "sep": (2, 1),  # Q2, +1 year
        "oct": (3, 1),
        "nov": (3, 1),
        "dec": (3, 1),  # Q3, +1 year
    }
    parts = col_header.strip().split()
    if len(parts) != 2:
        return col_header, 0, 0
    month_str, year_str = parts
    try:
        cal_year = int(year_str)
    except ValueError:
        return col_header, 0, 0
    key = month_str[:3].lower()
    if key not in MONTH_MAP:
        return col_header, 0, 0
    qnum, yr_offset = MONTH_MAP[key]
    fy_year = cal_year + yr_offset
    return col_header, fy_year, qnum


# Map Screener.in row labels to DB column names
_ROW_MAP = [
    (["sales", "revenue", "net sales"], "revenue"),
    (["operating profit"], "operating_profit"),
    (["opm %", "opm%", "operating profit margin"], "opm_percent"),
    (["other income"], "other_income"),
    (["interest"], "interest"),
    (["depreciation"], "depreciation"),
    (["profit before tax", "pbt"], "pbt"),
    (["tax %", "tax%"], "tax_percent"),
    (["net profit", "profit after tax", "pat"], "net_profit"),
    (["eps in rs", "eps (rs)", "eps"], "eps"),
    (["expenditure", "expenses", "total expenses"], "expenditure"),
]


def _match_row(label: str):
    norm = label.lower().strip().replace("+", "").replace("\xa0", " ").strip()
    for keywords, field in _ROW_MAP:
        for kw in keywords:
            if kw in norm:
                return field
    return None


def _latest_quarter_month(soup: BeautifulSoup) -> tuple:
    """Return (year, month_num) of the most recent quarter column, or (0, 0)."""
    MONTH_NUM = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    section = soup.find("section", {"id": "quarters"})
    if not section:
        return (0, 0)
    table = section.find("table")
    if not table:
        return (0, 0)
    thead = table.find("thead")
    cells = (thead or table.find("tr") or BeautifulSoup("", "html.parser")).find_all(["th", "td"])
    headers = [c.get_text(strip=True) for c in cells][1:]
    if not headers:
        return (0, 0)
    parts = headers[-1].strip().split()
    if len(parts) != 2:
        return (0, 0)
    try:
        return (int(parts[1]), MONTH_NUM.get(parts[0][:3].lower(), 0))
    except ValueError:
        return (0, 0)


def fetch_company_page(session: requests.Session, symbol: str) -> BeautifulSoup:
    """Fetch both Screener pages and prefer consolidated (for correct group numbers),
    falling back to standalone only if standalone has more recent data."""
    default_url = f"{BASE_URL}/company/{symbol}/"
    consolidated_url = f"{BASE_URL}/company/{symbol}/consolidated/"

    default_soup = consolidated_soup = None

    r = session.get(consolidated_url, timeout=20)
    if r.status_code == 200:
        consolidated_soup = BeautifulSoup(r.text, "html.parser")

    r = session.get(default_url, timeout=20)
    if r.status_code == 200:
        default_soup = BeautifulSoup(r.text, "html.parser")

    if consolidated_soup is None and default_soup is None:
        msg = f"Could not fetch page for {symbol}"
        raise RuntimeError(msg)

    if consolidated_soup is None:
        logger.info(f"Fetched page: {default_url} (no consolidated available)")
        return default_soup  # type: ignore

    if default_soup is None:
        logger.info(f"Fetched page: {consolidated_url}")
        return consolidated_soup

    # Prefer consolidated unless standalone has strictly newer quarterly data
    cons_date = _latest_quarter_month(consolidated_soup)
    dflt_date = _latest_quarter_month(default_soup)

    if dflt_date > cons_date:
        logger.info(f"Fetched page: {default_url} (standalone is more recent: {dflt_date} vs {cons_date})")
        return default_soup

    logger.info(f"Fetched page: {consolidated_url} (consolidated preferred)")
    return consolidated_soup


def scrape_quarterly_results(session: requests.Session, symbol: str):
    """Returns list of dicts, one per quarter (newest first from Screener)."""
    soup = fetch_company_page(session, symbol)
    return scrape_quarterly_results_from_soup(soup, symbol)


def scrape_quarterly_results_from_soup(soup: BeautifulSoup, symbol: str):

    section = soup.find("section", {"id": "quarters"})
    if not section:
        msg = f"No #quarters section found for {symbol}"
        raise RuntimeError(msg)

    table = section.find("table")
    if not table:
        msg = f"No table in #quarters section for {symbol}"
        raise RuntimeError(msg)

    # Parse column headers — try thead>th, then thead>td, then first tbody row
    quarter_cols = []
    thead = table.find("thead")
    if thead:
        cells = thead.find_all(["th", "td"])
        if cells:
            quarter_cols = [c.get_text(strip=True) for c in cells][1:]

    if not quarter_cols:
        # Fallback: first <tr> anywhere in the table
        first_row = table.find("tr")
        if first_row:
            cells = first_row.find_all(["th", "td"])
            quarter_cols = [c.get_text(strip=True) for c in cells][1:]

    if not quarter_cols:
        # Last resort: dump raw HTML to help debug future failures
        logger.debug("Table HTML: %s", table.prettify()[:2000])
        msg = "No quarter columns found in table"
        raise RuntimeError(msg)

    # Parse body rows into {field: [val_q0, val_q1, ...]}
    field_values: dict[str, list] = {}
    tbody = table.find("tbody")
    if tbody:
        all_rows = tbody.find_all("tr")
        # If we fell back to reading headers from the first tbody row, skip it
        first_row_is_header = bool(tbody.find("tr") and tbody.find("tr").find("th"))
        data_rows = all_rows[1:] if first_row_is_header else all_rows
        for tr in data_rows:
            cells = tr.find_all("td")
            if not cells:
                continue
            label = cells[0].get_text(strip=True)
            field = _match_row(label)
            if field:
                vals = [
                    cells[i].get_text(strip=True) if i < len(cells) else "" for i in range(1, len(quarter_cols) + 1)
                ]
                field_values[field] = vals

    # Build one record per quarter column
    results = []
    for idx, col in enumerate(quarter_cols):
        if not col:
            continue
        quarter_str, fy_year, qnum = _quarter_info(col)
        rec: dict = {
            "quarter": quarter_str,
            "year": fy_year,
            "quarter_number": qnum,
            "is_consolidated": True,
            "source": "screener",
        }
        for field, vals in field_values.items():
            if idx < len(vals):
                rec[field] = _parse_number(vals[idx])

        # EBITDA = Operating Profit + Depreciation
        op = rec.get("operating_profit")
        dep = rec.get("depreciation")
        if op is not None:
            rec["ebitda"] = (op + dep) if dep is not None else op

        # Derived margins (if not already set by OPM% row)
        rev = rec.get("revenue")
        if rev and rev != 0:
            if "opm_percent" not in rec or rec["opm_percent"] is None:
                if op is not None:
                    rec["opm_percent"] = round((op / rev) * 100, 2)
            np_ = rec.get("net_profit")
            if np_ is not None:
                rec["net_margin"] = round((np_ / rev) * 100, 2)
            if op is not None:
                rec["operating_margin"] = round((op / rev) * 100, 2)

        results.append(rec)

    return results


# ── Shareholding ─────────────────────────────────────────────────────────────

_SHAREHOLDING_MAP = {
    "promoter": "promoter_holding",
    "fii": "fii_holding",
    "dii": "dii_holding",
    "public": "public_holding",
    "government": "government_holding",
}


def _match_shareholding_row(label: str):
    norm = label.lower().strip().rstrip("+").strip()
    for key, field in _SHAREHOLDING_MAP.items():
        if key in norm:
            return field
    return None


def scrape_shareholding(soup: BeautifulSoup) -> list:
    """Parse #shareholding section from an already-fetched Screener page."""
    section = soup.find("section", {"id": "shareholding"})
    if not section:
        return []

    table = section.find("table")
    if not table:
        return []

    # Headers (quarter strings)
    thead = table.find("thead")
    if not thead:
        return []
    header_cells = thead.find_all(["th", "td"])
    quarter_cols = [c.get_text(strip=True) for c in header_cells][1:]
    if not quarter_cols:
        return []

    # Parse rows
    field_values: dict[str, list] = {}
    num_shareholders: list = []
    tbody = table.find("tbody")
    if tbody:
        for tr in tbody.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            label = cells[0].get_text(strip=True)
            vals = [cells[i].get_text(strip=True) if i < len(cells) else "" for i in range(1, len(quarter_cols) + 1)]
            if "no. of shareholders" in label.lower():
                num_shareholders = vals
            else:
                field = _match_shareholding_row(label)
                if field:
                    field_values[field] = vals

    results = []
    for idx, col in enumerate(quarter_cols):
        if not col:
            continue
        quarter_str, fy_year, qnum = _quarter_info(col)
        rec: dict = {
            "quarter": quarter_str,
            "year": fy_year,
            "quarter_number": qnum,
        }
        for field, vals in field_values.items():
            if idx < len(vals):
                rec[field] = _parse_number(vals[idx])
        if idx < len(num_shareholders):
            ns = _parse_number(num_shareholders[idx])
            if ns is not None:
                rec["num_shareholders"] = int(ns)
        results.append(rec)

    return results


def save_shareholding_to_db(stock_id: int, results: list, conn) -> int:
    cur = conn.cursor()
    cur.execute("DELETE FROM shareholding_patterns WHERE stock_id = %s AND quarter ~ '^Q[1-4] [0-9]{4}$'", (stock_id,))
    upserted = 0
    for rec in results:
        try:
            cur.execute(
                """
                INSERT INTO shareholding_patterns
                    (stock_id, quarter, year, quarter_number,
                     promoter_holding, fii_holding, dii_holding,
                     public_holding, government_holding, num_shareholders)
                VALUES (%s,%s,%s,%s, %s,%s,%s,%s,%s,%s)
                ON CONFLICT (stock_id, quarter, year) DO UPDATE SET
                    promoter_holding   = EXCLUDED.promoter_holding,
                    fii_holding        = EXCLUDED.fii_holding,
                    dii_holding        = EXCLUDED.dii_holding,
                    public_holding     = EXCLUDED.public_holding,
                    government_holding = EXCLUDED.government_holding,
                    num_shareholders   = EXCLUDED.num_shareholders
                """,
                (
                    stock_id,
                    rec.get("quarter"),
                    rec.get("year"),
                    rec.get("quarter_number"),
                    rec.get("promoter_holding"),
                    rec.get("fii_holding"),
                    rec.get("dii_holding"),
                    rec.get("public_holding"),
                    rec.get("government_holding"),
                    rec.get("num_shareholders"),
                ),
            )
            upserted += 1
        except Exception as e:
            logger.warning(f"  Skipped shareholding {rec.get('quarter')}: {e}")
            conn.rollback()
            continue
    return upserted


def _open_db_conn():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        msg = "DATABASE_URL not set"
        raise RuntimeError(msg)
    parsed = urlparse(db_url)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
        user=parsed.username,
        password=parsed.password,
        sslmode="require",
    )


def save_to_db(symbol: str, results: list) -> int:
    conn = _open_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM stocks WHERE nse_symbol = %s", (symbol,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        msg = f"Stock '{symbol}' not found in database"
        raise RuntimeError(msg)
    stock_id = row[0]

    upserted = _save_quarterly(stock_id, results, conn)
    conn.commit()
    cur.close()
    conn.close()
    return upserted


def _save_quarterly(stock_id: int, results: list, conn) -> int:
    cur = conn.cursor()
    # Remove legacy "Q1 YYYY" / "Q2 YYYY" etc. rows — old sync used calendar-based
    # quarter labels that conflict with the "MMM YYYY" format Screener returns.
    cur.execute("DELETE FROM quarterly_results WHERE stock_id = %s AND quarter ~ '^Q[1-4] [0-9]{4}$'", (stock_id,))
    upserted = 0
    for rec in results:
        try:
            cur.execute(
                """
                INSERT INTO quarterly_results
                    (stock_id, quarter, year, quarter_number,
                     revenue, net_profit, ebitda, operating_profit,
                     operating_margin, net_margin, eps, is_consolidated,
                     other_income, interest, depreciation, pbt,
                     tax_percent, opm_percent, expenditure, source)
                VALUES
                    (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s)
                ON CONFLICT (stock_id, quarter, year) DO UPDATE SET
                    revenue          = EXCLUDED.revenue,
                    net_profit       = EXCLUDED.net_profit,
                    ebitda           = EXCLUDED.ebitda,
                    operating_profit = EXCLUDED.operating_profit,
                    operating_margin = EXCLUDED.operating_margin,
                    net_margin       = EXCLUDED.net_margin,
                    eps              = EXCLUDED.eps,
                    other_income     = EXCLUDED.other_income,
                    interest         = EXCLUDED.interest,
                    depreciation     = EXCLUDED.depreciation,
                    pbt              = EXCLUDED.pbt,
                    tax_percent      = EXCLUDED.tax_percent,
                    opm_percent      = EXCLUDED.opm_percent,
                    expenditure      = EXCLUDED.expenditure,
                    source           = EXCLUDED.source
                """,
                (
                    stock_id,
                    rec.get("quarter"),
                    rec.get("year"),
                    rec.get("quarter_number"),
                    rec.get("revenue"),
                    rec.get("net_profit"),
                    rec.get("ebitda"),
                    rec.get("operating_profit"),
                    rec.get("operating_margin"),
                    rec.get("net_margin"),
                    rec.get("eps"),
                    rec.get("is_consolidated", True),
                    rec.get("other_income"),
                    rec.get("interest"),
                    rec.get("depreciation"),
                    rec.get("pbt"),
                    rec.get("tax_percent"),
                    rec.get("opm_percent"),
                    rec.get("expenditure"),
                    rec.get("source", "screener"),
                ),
            )
            upserted += 1
        except Exception as e:
            logger.warning(f"  Skipped quarter {rec.get('quarter')}: {e}")
            conn.rollback()
            continue
    return upserted


def main():
    parser = argparse.ArgumentParser(description="Sync quarterly results from Screener.in")
    parser.add_argument("--symbol", required=True, help="NSE stock symbol (e.g. RELIANCE)")
    args = parser.parse_args()

    symbol = args.symbol.upper().replace(".NS", "").replace(".BO", "")

    try:
        session = login_to_screener()

        # Fetch page once, parse both sections
        soup = fetch_company_page(session, symbol)

        quarterly = scrape_quarterly_results_from_soup(soup, symbol)
        shareholding = scrape_shareholding(soup)
        logger.info(f"Scraped {len(quarterly)} quarters, {len(shareholding)} shareholding rows for {symbol}")

        conn = _open_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM stocks WHERE nse_symbol = %s", (symbol,))
        row = cur.fetchone()
        if not row:
            msg = f"Stock '{symbol}' not found in database"
            raise RuntimeError(msg)
        stock_id = row[0]

        saved_q = _save_quarterly(stock_id, quarterly, conn)
        saved_s = save_shareholding_to_db(stock_id, shareholding, conn)
        conn.commit()
        conn.close()

        logger.info(f"Saved {saved_q} quarters, {saved_s} shareholding rows")

        print(
            json.dumps(
                {
                    "success": True,
                    "symbol": symbol,
                    "quarters_scraped": len(quarterly),
                    "quarters_saved": saved_q,
                    "shareholding_saved": saved_s,
                }
            )
        )

    except Exception as exc:
        logger.exception(str(exc))
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
