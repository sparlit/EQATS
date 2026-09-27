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


"""Scrape NSE ASM/GSM surveillance data using SeleniumBase anti-detection.

Outputs:
    /tmp/nse_asm_current.json  - Current ASM stocks (LT + ST)
    /tmp/nse_gsm_current.json  - Current GSM stocks

Usage:
    python scripts/scrape_nse_surveillance.py [--save-json] [--ingest-pg]
"""


import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def scrape_asm(sb) -> list[dict]:
    """Scrape NSE ASM page for Long-Term and Short-Term ASM stocks."""
    log.info("Fetching ASM page...")
    sb.uc_open_with_reconnect("https://www.nseindia.com/reports/asm", reconnect_time=4)
    time.sleep(5)

    raw = sb.execute_script("""
        var tables = document.querySelectorAll('table');
        var results = [];
        tables.forEach(function(table) {
            var headers = [];
            table.querySelectorAll('th').forEach(th => headers.push(th.textContent.trim()));
            if (headers.includes('SYMBOL')) {
                table.querySelectorAll('tr').forEach(function(row) {
                    var cells = row.querySelectorAll('td');
                    if (cells.length >= 4) {
                        var data = [];
                        cells.forEach(c => data.push(c.textContent.trim()));
                        if (data[1] && data[1] !== 'SYMBOL') {
                            results.push(data);
                        }
                    }
                });
            }
        });
        return results;
    """)

    stocks = []
    for row in raw:
        symbol = row[1] if len(row) > 1 else ""
        company = row[2] if len(row) > 2 else ""
        isin = row[3] if len(row) > 3 else ""
        stage_raw = row[4] if len(row) > 4 else ""

        # Parse stage: "LTASM - I (13)" -> framework=LTASM, stage=I, code=13
        framework = "ASM"
        stage = ""
        stage_code = ""
        if "LTASM" in stage_raw:
            framework = "LTASM"
        elif "STASM" in stage_raw:
            framework = "STASM"

        # Extract罗马数字 stage
        for s in ["I", "II", "III", "IV", "V", "VI"]:
            if f"- {s}" in stage_raw or f"-{s}" in stage_raw:
                stage = s
                break

        # Extract code number
        if "(" in stage_raw and ")" in stage_raw:
            stage_code = stage_raw.split("(")[-1].rstrip(")")

        stocks.append(
            {
                "symbol": symbol,
                "company_name": company,
                "isin": isin,
                "framework": framework,
                "stage": stage,
                "stage_code": stage_code,
                "stage_raw": stage_raw,
            }
        )

    log.info(
        f"ASM scraped: {len(stocks)} stocks (LTASM: {sum(1 for s in stocks if s['framework'] == 'LTASM')}, STASM: {sum(1 for s in stocks if s['framework'] == 'STASM')})"
    )
    return stocks


def scrape_gsm(sb) -> list[dict]:
    """Scrape NSE GSM page for Graded Surveillance Measure stocks."""
    log.info("Fetching GSM page...")
    sb.uc_open_with_reconnect("https://www.nseindia.com/reports/gsm", reconnect_time=4)
    time.sleep(5)

    raw = sb.execute_script("""
        var tables = document.querySelectorAll('table');
        var results = [];
        tables.forEach(function(table) {
            var headers = [];
            table.querySelectorAll('th').forEach(th => headers.push(th.textContent.trim()));
            if (headers.includes('SYMBOL')) {
                table.querySelectorAll('tr').forEach(function(row) {
                    var cells = row.querySelectorAll('td');
                    if (cells.length >= 3) {
                        var data = [];
                        cells.forEach(c => data.push(c.textContent.trim()));
                        if (data[1] && data[1] !== 'SYMBOL') {
                            results.push(data);
                        }
                    }
                });
            }
        });
        return results;
    """)

    stocks = []
    for row in raw:
        symbol = row[1] if len(row) > 1 else ""
        company = row[2] if len(row) > 2 else ""
        isin = row[3] if len(row) > 3 else ""
        stage_raw = row[4] if len(row) > 4 else ""

        # Parse GSM stage: "GSM - 0 (99)", "GSM - VI (6)", "IBC - Receipt & GSM 0 (62)"
        stage = ""
        has_ibc = "IBC" in stage_raw
        for s in ["0", "I", "II", "III", "IV", "V", "VI"]:
            if s in stage_raw:
                stage = s
                break

        stocks.append(
            {
                "symbol": symbol,
                "company_name": company,
                "isin": isin,
                "framework": "GSM",
                "stage": stage,
                "stage_raw": stage_raw,
                "has_ibc": has_ibc,
            }
        )

    log.info(f"GSM scraped: {len(stocks)} stocks")
    return stocks


def main():
    parser = argparse.ArgumentParser(description="Scrape NSE ASM/GSM surveillance data")
    parser.add_argument("--save-json", action="store_true", help="Save to /tmp JSON files")
    parser.add_argument("--ingest-pg", action="store_true", help="Ingest into PostgreSQL")
    parser.add_argument("--json-dir", default="/tmp", help="Directory for JSON output")
    args = parser.parse_args()

    from seleniumbase import SB

    all_stocks = []

    with SB(uc=True, headless=True) as sb:
        # Establish session
        log.info("Establishing NSE session...")
        sb.uc_open_with_reconnect("https://www.nseindia.com", reconnect_time=6)
        log.info(f"Session established: {sb.get_title()}")

        # Scrape ASM
        asm_stocks = scrape_asm(sb)
        all_stocks.extend(asm_stocks)

        # Scrape GSM
        gsm_stocks = scrape_gsm(sb)
        all_stocks.extend(gsm_stocks)

    log.info(f"Total surveillance stocks scraped: {len(all_stocks)}")

    # Save to JSON
    if args.save_json:
        json_dir = Path(args.json_dir)
        asm_file = json_dir / "nse_asm_current.json"
        gsm_file = json_dir / "nse_gsm_current.json"
        all_file = json_dir / "nse_surveillance_current.json"

        with open(asm_file, "w") as f:
            json.dump(asm_stocks, f, indent=2)
        with open(gsm_file, "w") as f:
            json.dump(gsm_stocks, f, indent=2)
        with open(all_file, "w") as f:
            json.dump(all_stocks, f, indent=2)

        log.info(
            f"Saved: {asm_file} ({len(asm_stocks)}), {gsm_file} ({len(gsm_stocks)}), {all_file} ({len(all_stocks)})"
        )

    # Ingest to PostgreSQL
    if args.ingest_pg:
        from indian_quant.config.connections import get_engine

        engine = get_engine()
        ingest_to_pg(engine, asm_stocks, gsm_stocks)

    # Print summary
    print("\n=== SURVEILLANCE SUMMARY ===")
    print(f"LTASM stocks: {sum(1 for s in asm_stocks if s['framework'] == 'LTASM')}")
    print(f"STASM stocks: {sum(1 for s in asm_stocks if s['framework'] == 'STASM')}")
    print(f"GSM stocks:   {len(gsm_stocks)}")
    print(f"Total:        {len(all_stocks)}")

    # Stage breakdown
    from collections import Counter

    asm_stages = Counter(s["stage_raw"] for s in asm_stocks)
    gsm_stages = Counter(s["stage_raw"] for s in gsm_stocks)

    print("\n--- ASM Stage Breakdown ---")
    for stage, count in asm_stages.most_common():
        print(f"  {stage}: {count}")

    print("\n--- GSM Stage Breakdown ---")
    for stage, count in gsm_stages.most_common():
        print(f"  {stage}: {count}")

    return 0


def ingest_to_pg(engine, asm_stocks: list[dict], gsm_stocks: list[dict]):
    """Ingest scraped data into PostgreSQL surveillance_history table."""
    from datetime import date

    import sqlalchemy as sa

    today = date.today()

    # Ensure tables exist
    with engine.begin() as conn:
        conn.execute(
            sa.text("""
            CREATE TABLE IF NOT EXISTS surveillance_stocks (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(32) NOT NULL,
                exchange VARCHAR(8) NOT NULL DEFAULT 'NSE',
                framework VARCHAR(16) NOT NULL,
                stage VARCHAR(8),
                stage_code VARCHAR(8),
                stage_raw VARCHAR(128),
                company_name VARCHAR(256),
                isin VARCHAR(32),
                has_ibc BOOLEAN DEFAULT FALSE,
                status VARCHAR(16) DEFAULT 'ACTIVE',
                first_seen_date DATE DEFAULT CURRENT_DATE,
                last_seen_date DATE DEFAULT CURRENT_DATE,
                scraped_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(symbol, framework, exchange)
            );
            CREATE INDEX IF NOT EXISTS idx_surv_stocks_sym ON surveillance_stocks(symbol);
            CREATE INDEX IF NOT EXISTS idx_surv_stocks_fw ON surveillance_stocks(framework);
            CREATE INDEX IF NOT EXISTS idx_surv_stocks_status ON surveillance_stocks(status);
        """)
        )

        conn.execute(
            sa.text("""
            CREATE TABLE IF NOT EXISTS surveillance_history (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(32) NOT NULL,
                exchange VARCHAR(8) NOT NULL DEFAULT 'NSE',
                framework VARCHAR(16) NOT NULL,
                stage VARCHAR(8),
                stage_code VARCHAR(8),
                stage_raw VARCHAR(128),
                has_ibc BOOLEAN DEFAULT FALSE,
                snapshot_date DATE NOT NULL,
                scraped_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(symbol, framework, exchange, snapshot_date)
            );
            CREATE INDEX IF NOT EXISTS idx_surv_hist_sym ON surveillance_history(symbol);
            CREATE INDEX IF NOT EXISTS idx_surv_hist_date ON surveillance_history(snapshot_date);
            CREATE INDEX IF NOT EXISTS idx_surv_hist_fw ON surveillance_history(framework);
        """)
        )

    # Upsert current stocks
    all_stocks = asm_stocks + gsm_stocks
    count = 0
    with engine.begin() as conn:
        for s in all_stocks:
            conn.execute(
                sa.text("""
                INSERT INTO surveillance_stocks (symbol, framework, stage, stage_code, stage_raw, company_name, isin, has_ibc, status, last_seen_date)
                VALUES (:symbol, :framework, :stage, :stage_code, :stage_raw, :company_name, :isin, :has_ibc, 'ACTIVE', :today)
                ON CONFLICT (symbol, framework, exchange) DO UPDATE SET
                    stage = EXCLUDED.stage,
                    stage_code = EXCLUDED.stage_code,
                    stage_raw = EXCLUDED.stage_raw,
                    status = 'ACTIVE',
                    last_seen_date = EXCLUDED.last_seen_date,
                    scraped_at = NOW()
            """),
                {
                    "symbol": s["symbol"],
                    "framework": s["framework"],
                    "stage": s["stage"],
                    "stage_code": s.get("stage_code", ""),
                    "stage_raw": s["stage_raw"],
                    "company_name": s.get("company_name", ""),
                    "isin": s.get("isin", ""),
                    "has_ibc": s.get("has_ibc", False),
                    "today": today,
                },
            )
            count += 1

        # Insert daily snapshot
        for s in all_stocks:
            conn.execute(
                sa.text("""
                INSERT INTO surveillance_history (symbol, framework, stage, stage_code, stage_raw, has_ibc, snapshot_date)
                VALUES (:symbol, :framework, :stage, :stage_code, :stage_raw, :has_ibc, :today)
                ON CONFLICT (symbol, framework, exchange, snapshot_date) DO UPDATE SET
                    stage = EXCLUDED.stage,
                    stage_code = EXCLUDED.stage_code,
                    stage_raw = EXCLUDED.stage_raw,
                    has_ibc = EXCLUDED.has_ibc,
                    scraped_at = NOW()
            """),
                {
                    "symbol": s["symbol"],
                    "framework": s["framework"],
                    "stage": s["stage"],
                    "stage_code": s.get("stage_code", ""),
                    "stage_raw": s["stage_raw"],
                    "has_ibc": s.get("has_ibc", False),
                    "today": today,
                },
            )

    log.info(f"Ingested {count} stocks into surveillance_stocks + surveillance_history for {today}")

    # Print DB summary
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
            SELECT framework, COUNT(*) FROM surveillance_stocks WHERE status='ACTIVE' GROUP BY framework ORDER BY framework
        """)
        ).fetchall()
        print("\n--- DB Summary ---")
        for r in rows:
            print(f"  {r[0]}: {r[1]} active stocks")

        total = conn.execute(sa.text("SELECT COUNT(*) FROM surveillance_history")).scalar()
        print(f"  History rows: {total}")


if __name__ == "__main__":
    raise SystemExit(main())
