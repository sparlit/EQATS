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
fetch_tijori_fundamentals.py
============================
Fetches P&L + Balance Sheet for all tickers in ticker_to_slug.csv from
Tijori Finance using your existing Playwright session (session.json).

Runs on your Mac — same browser session the MCP uses.

Usage:
    pip install playwright pandas pyarrow
    playwright install chromium
    python fetch_tijori_fundamentals.py

Outputs:
    fundamentals_annual.parquet  — long-format, all tickers × all fiscal years
    failed_fundamentals.csv      — tickers where fetch/parse failed

Config (edit if needed):
    SESSION_PATH  — path to your Tijori session.json
    CSV_PATH      — path to ticker_to_slug.csv
    OUTPUT_DIR    — where to write outputs
    CONCURRENCY   — parallel browser pages (3 is safe; 5 if you have good RAM)
"""

import asyncio
import contextlib
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from playwright.async_api import TimeoutError as PWTimeout
from playwright.async_api import async_playwright

# ── Config ──────────────────────────────────────────────────────────────────
SESSION_PATH = Path.home() / "tijori-finance-mcp/output/session.json"
CSV_PATH = Path("ticker_to_slug.csv")  # adjust if needed
OUTPUT_DIR = Path()
CONCURRENCY = 3  # parallel pages
BASE_URL = "https://www.tijorifinance.com"
NAV_TIMEOUT = 45_000  # ms
# ────────────────────────────────────────────────────────────────────────────

CHECKPOINT_FILE = OUTPUT_DIR / "fundamentals_checkpoint.jsonl"
FAILED_FILE = OUTPUT_DIR / "failed_fundamentals.csv"
OUTPUT_PARQUET = OUTPUT_DIR / "fundamentals_annual.parquet"

# Which Tijori data-id labels map to our target columns
# Keys = Tijori metric label (data-id attribute), Values = our column name
PL_FIELD_MAP = {
    # Sales — Tijori data-id is "Sales" exactly
    "sales": "sales",
    # Raw material
    "raw_material": "raw_material",
    "operating_profit": "operating_profit",  # ← ADD (non-fin RMW)
    "ppop": "ppop",  # ← ADD (fin RMW)
    # Net profit
    "net_profit": "net_profit",
    "profit_after_tax": "net_profit",  # ← ADD THIS (insurance cos)
    # Shares in Crores — Tijori label: "Number of shares(Crs)" normalises to:
    "number_of_shares_crs": "shares_cr",
    "number_of_shares": "shares_cr",
    # EPS is not on Tijori P&L — computed post-fetch as net_profit / shares_cr
}

BS_FIELD_MAP = {
    # Book equity
    "shareholders_funds": "book_equity",
    # Total debt = Secured Loans + Unsecured Loans (handled separately below)
    # We collect both and sum them in rows_to_dict_bs
    "secured_loans": "secured_loans",
    "unsecured_loans": "unsecured_loans",
}

# ── Helpers ──────────────────────────────────────────────────────────────────


def load_tickers(csv_path: Path) -> list[dict]:
    """Load tickers that have a slug (skip FAILEDs)."""
    rows = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            if r.get("tijori_slug", "").strip():
                rows.append({"ticker": r["nse_ticker"], "slug": r["tijori_slug"]})
    return rows


def load_done() -> set[str]:
    """Tickers already fetched (from checkpoint)."""
    done = set()
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            for line in f:
                with contextlib.suppress(Exception):
                    done.add(json.loads(line)["ticker"])
    return done


def parse_value(raw: str | None) -> float | None:
    """Convert Tijori display string to float. Handles Cr, %, commas."""
    if raw is None:
        return None
    raw = str(raw).strip().replace(",", "").replace("%", "")
    # Remove trailing Cr label — values are already in Crores on Tijori
    raw = re.sub(r"\s*Cr\.?$", "", raw, flags=re.IGNORECASE).strip()
    try:
        return float(raw)
    except ValueError:
        return None


def extract_year(header: str) -> str | None:
    """
    Convert Tijori period header to fiscal year string.
    e.g. "Mar'24" → "Mar'24", "FY24" → "Mar'24", "2023-24" → "Mar'24"
    Returns as-is if already looks like Mar'YY, else tries to normalise.
    """
    h = header.strip()
    # Already Mar'YY format
    if re.match(r"Mar'?\d{2}", h, re.IGNORECASE):
        return h
    # FY24 → Mar'24
    m = re.match(r"FY(\d{2,4})", h, re.IGNORECASE)
    if m:
        yr = m.group(1)[-2:]
        return f"Mar'{yr}"
    # 2023-24 → Mar'24
    m = re.match(r"\d{4}-(\d{2,4})", h)
    if m:
        yr = m.group(1)[-2:]
        return f"Mar'{yr}"
    # Bare year 2024 → Mar'24
    m = re.match(r"(20\d{2})$", h)
    if m:
        yr = m.group(1)[-2:]
        return f"Mar'{yr}"
    return h  # return as-is if we can't parse


def normalise_metric(raw: str) -> str:
    """Normalise a Tijori metric label to a lookup key."""
    key = raw.strip().lower()
    # Replace spaces, dashes, slashes, parentheses with underscores
    key = re.sub(r"[\s\-/()+%]+", "_", key)
    # Remove any remaining non-alphanumeric except underscore
    key = re.sub(r"[^a-z0-9_]", "", key)
    # Collapse multiple underscores
    return re.sub(r"_+", "_", key).strip("_")


def rows_to_dict(tijori_rows: list[dict], field_map: dict) -> dict[str, dict]:
    """
    Convert Tijori rows list → {fiscal_year: {col: value}}.
    tijori_rows is a list of {"metric": label, "Mar'24": "1234.5", ...}
    For BS: sums secured_loans + unsecured_loans into total_debt.
    """
    year_data: dict[str, dict] = {}

    for row in tijori_rows:
        metric_key = normalise_metric(str(row.get("metric", "")))
        col = field_map.get(metric_key)
        if col is None:
            continue

        for header, raw_val in row.items():
            if header == "metric":
                continue
            fy = extract_year(header)
            if not fy or fy == "TTM":
                continue
            val = parse_value(raw_val)
            if fy not in year_data:
                year_data[fy] = {}

            if col in ("secured_loans", "unsecured_loans"):
                # Accumulate into total_debt
                existing = year_data[fy].get("total_debt") or 0.0
                year_data[fy]["total_debt"] = existing + (val or 0.0)
            # Don't overwrite already-set value (first match wins)
            elif col not in year_data[fy]:
                year_data[fy][col] = val

    return year_data


# ── Page scraper (mirrors MCP's parseFinancials) ────────────────────────────

JS_PARSE = """
(sectionId) => {
    const TYPE_TO_SECTION = {
        pl: 'profit_and_loss',
        bs: 'balance_sheet',
    };

    // Force DataTables to show all rows
    try {
        if (window.jQuery) {
            window.jQuery('table.dataTable').each(function () {
                try { window.jQuery(this).DataTable().page.len(-1).draw(false); } catch (_) {}
            });
        }
    } catch (_) {}

    function parseSection(type) {
        const section = TYPE_TO_SECTION[type];
        const wrapperId = section + '_table_wrapper';
        let wrapper = document.getElementById(wrapperId);
        if (!wrapper) {
            const tab = document.getElementById('company_table_innertab_' + section + '_content');
            wrapper = tab?.querySelector('.dt-container') ?? null;
        }
        if (!wrapper) return { type, rows: [], headers: [], error: 'not found' };

        const periodHeaders = Array.from(wrapper.querySelectorAll('thead th.headerItem'))
            .map(th => th.textContent.trim())
            .filter(Boolean);

        const rows = Array.from(wrapper.querySelectorAll('tbody tr')).flatMap(tr => {
            const label = tr.getAttribute('data-id')
                ?? tr.querySelector('td.firstcol')?.textContent.trim();
            if (!label) return [];

            const values = Array.from(tr.querySelectorAll('td.knowledge.numericvalue')).map(td => {
                const raw = td.textContent.trim().replace(/\\s+/g, ' ');
                return (raw === '—' || raw === '-' || raw === '') ? null : raw;
            });

            const row = { metric: label };
            values.forEach((val, i) => {
                if (periodHeaders[i]) row[periodHeaders[i]] = val;
            });
            return [row];
        });

        return { type, headers: ['metric', ...periodHeaders], rows };
    }

    return {
        pl: parseSection('pl'),
        bs: parseSection('bs'),
    };
}
"""


async def fetch_company(page, ticker: str, slug: str) -> list[dict] | None:
    """
    Navigate to company financials page, parse P&L + BS, return list of
    {nse_ticker, fiscal_year, sales, raw_material, net_profit, eps, shares_cr,
     book_equity, total_debt} rows. Returns None on hard failure.
    """
    url = f"{BASE_URL}/company/{slug}/financials/"
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        if resp and resp.status == 404:
            return None  # slug doesn't exist
        if resp and resp.status == 403:
            msg = "SESSION_EXPIRED"
            raise RuntimeError(msg)

        # Wait for the DataTable to render
        try:
            await page.wait_for_selector("table.dataTable", timeout=15_000)
        except PWTimeout:
            pass  # parse what we have

        # Small settle so DataTables can initialise
        await page.wait_for_timeout(500)

        # Parse both sections in one JS call
        result = await page.evaluate(JS_PARSE)

        pl_rows = result.get("pl", {}).get("rows", [])
        bs_rows = result.get("bs", {}).get("rows", [])

        if not pl_rows and not bs_rows:
            return None

        pl_by_year = rows_to_dict(pl_rows, PL_FIELD_MAP)
        bs_by_year = rows_to_dict(bs_rows, BS_FIELD_MAP)

        # Merge by fiscal year
        all_years = sorted(set(pl_by_year) | set(bs_by_year))
        out = []
        for fy in all_years:
            row = {"nse_ticker": ticker, "fiscal_year": fy}
            row.update(pl_by_year.get(fy, {}))
            row.update(bs_by_year.get(fy, {}))
            # Ensure all columns exist
            for col in [
                "sales",
                "raw_material",
                "operating_profit",
                "ppop",
                "net_profit",
                "eps",
                "shares_cr",
                "book_equity",
                "total_debt",
            ]:
                row.setdefault(col, None)
            out.append(row)

        return out or None

    except RuntimeError:
        raise
    except Exception as e:
        print(f"  [ERROR] {ticker}: {e}", flush=True)
        return None


# ── Worker ───────────────────────────────────────────────────────────────────


async def worker(semaphore, context, queue, checkpoint_lock, failed_lock, checkpoint_fh, failed_fh, counters):
    while True:
        try:
            ticker, slug = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        async with semaphore:
            page = await context.new_page()
            try:
                rows = await fetch_company(page, ticker, slug)
            except RuntimeError as e:
                if "SESSION_EXPIRED" in str(e):
                    print("\n[FATAL] Session expired. Re-run: node discover.js --reauth", flush=True)
                    sys.exit(1)
                rows = None
            finally:
                await page.close()

            if rows:
                async with checkpoint_lock:
                    checkpoint_fh.write(json.dumps({"ticker": ticker, "rows": rows}) + "\n")
                    checkpoint_fh.flush()
                counters["ok"] += 1
                print(f"  ✓ {ticker} ({len(rows)} years)", flush=True)
            else:
                async with failed_lock:
                    failed_fh.write(f"{ticker},{slug}\n")
                    failed_fh.flush()
                counters["fail"] += 1
                print(f"  ✗ {ticker}", flush=True)

            counters["done"] += 1
            total = counters["total"]
            done = counters["done"]
            pct = done / total * 100
            print(f"  Progress: {done}/{total} ({pct:.1f}%)", flush=True)


# ── Main ─────────────────────────────────────────────────────────────────────


async def main():
    # Load tickers
    if not CSV_PATH.exists():
        print(f"[ERROR] {CSV_PATH} not found. Run from the directory containing ticker_to_slug.csv")
        sys.exit(1)

    tickers = load_tickers(CSV_PATH)
    done_set = load_done()
    pending = [(t["ticker"], t["slug"]) for t in tickers if t["ticker"] not in done_set]

    print(f"Total tickers with slug: {len(tickers)}")
    print(f"Already fetched (checkpoint): {len(done_set)}")
    print(f"Remaining: {len(pending)}")
    if not pending:
        print("Nothing to fetch — building parquet from checkpoint.")
    else:
        print(f"Starting fetch with concurrency={CONCURRENCY} ...")

    # Load session
    if not SESSION_PATH.exists():
        print(f"[ERROR] Session not found at {SESSION_PATH}")
        sys.exit(1)

    session = json.loads(SESSION_PATH.read_text())

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=session,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )

        # Block images/fonts/trackers (mirrors MCP browser.js)
        async def handle_route(route):
            req = route.request
            if req.resource_type in ("image", "media", "font"):
                await route.abort()
                return
            if re.search(
                r"mixpanel|partytown|google-analytics|googletagmanager|"
                r"doubleclick|platform\.twitter|//x\.com",
                req.url,
                re.IGNORECASE,
            ):
                await route.abort()
                return
            await route.continue_()

        await context.route("**/*", handle_route)

        # Build queue
        queue: asyncio.Queue = asyncio.Queue()
        for item in pending:
            queue.put_nowait(item)

        semaphore = asyncio.Semaphore(CONCURRENCY)
        checkpoint_lock = asyncio.Lock()
        failed_lock = asyncio.Lock()
        counters = {"done": 0, "ok": 0, "fail": 0, "total": len(pending)}

        with (
            open(CHECKPOINT_FILE, "a") as chk_fh,
            open(FAILED_FILE, "a") as fail_fh,
        ):
            # Write failed header if new file
            if FAILED_FILE.stat().st_size == 0 if FAILED_FILE.exists() else True:
                fail_fh.write("nse_ticker,tijori_slug\n")

            workers = [
                asyncio.create_task(
                    worker(semaphore, context, queue, checkpoint_lock, failed_lock, chk_fh, fail_fh, counters)
                )
                for _ in range(CONCURRENCY)
            ]
            await asyncio.gather(*workers)

        await browser.close()

    # ── Build parquet from checkpoint ──
    print("\nBuilding parquet from checkpoint...")
    all_rows = []
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    all_rows.extend(entry["rows"])
                except Exception:
                    pass

    if not all_rows:
        print("[WARNING] No data collected.")
        return

    df = pd.DataFrame(all_rows)

    # Drop TTM rows — not a fiscal year
    df = df[df["fiscal_year"] != "TTM"]

    # Enforce schema
    cols = [
        "nse_ticker",
        "fiscal_year",
        "sales",
        "raw_material",
        "operating_profit",
        "ppop",
        "net_profit",
        "eps",
        "shares_cr",
        "book_equity",
        "total_debt",
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA

    df = df[cols]

    # Convert numeric columns
    for c in cols[2:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Compute EPS = net_profit (Cr) * 1e7 / (shares_cr * 1e7) = net_profit / shares_cr
    # net_profit is in Cr, shares_cr is number of shares in Cr
    # EPS in Rs = (net_profit * 1e7) / (shares_cr * 1e7) = net_profit / shares_cr
    mask = df["shares_cr"].notna() & (df["shares_cr"] > 0) & df["net_profit"].notna()
    df.loc[mask, "eps"] = df.loc[mask, "net_profit"] / df.loc[mask, "shares_cr"]

    df.to_parquet(OUTPUT_PARQUET, engine="pyarrow", index=False)

    print(f"\n{'=' * 50}")
    print("Done!")
    print(f"  Tickers fetched OK : {counters['ok']}")
    print(f"  Tickers failed     : {counters['fail']}")
    print(f"  Total rows         : {len(df)}")
    print(f"  Fiscal years       : {sorted(df['fiscal_year'].dropna().unique())}")
    print(f"  Output             : {OUTPUT_PARQUET.resolve()}")
    print(f"  Failed list        : {FAILED_FILE.resolve()}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
