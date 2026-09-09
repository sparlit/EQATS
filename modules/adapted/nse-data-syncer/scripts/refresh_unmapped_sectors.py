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
Refreshes sector/industry classification for currently-unmapped stocks by
scraping Screener.in's per-company "Peer comparison" breadcrumb (see
scripts/screener_service.py's _extract_sector_info(), rewritten to use the
real DOM structure - a[title=...] tags, not hardcoded keyword matching).

Universe: active stocks whose `industry` either has no value at all, or
has a value that doesn't map to any NSE sector index in
app/sector_mapping.py's SECTOR_INDEX_MAP (i.e. exactly the set excluded
from the swing-setup/swing-score sector-dependent features).

Column mapping matches scripts/update_sectors_from_bse.py exactly, so the
two sources are interchangeable:
    Screener "Broad Sector" -> sector
    Screener "Sector"       -> subsector1
    Screener "Broad Industry" -> subsector2
    Screener "Industry" (finest) -> subsector3 (also -> subsector, "most specific")
                                     -> industry (the SECTOR_INDEX_MAP join key)

A long-running headless Chrome session can crash mid-batch (observed:
"invalid session id" after ~450 sequential page loads, likely memory
buildup). If that happens, this script closes the dead session, opens a
fresh one (re-login), and resumes - since load_unmapped_stocks() re-queries
"still unmapped" fresh each time, already-classified stocks simply won't
reappear, so resumption is automatic rather than needing an explicit
checkpoint/offset.

Usage:
    python scripts/refresh_unmapped_sectors.py
"""
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from selenium.common.exceptions import WebDriverException
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))
sys.path.append(base_dir)
sys.path.append(os.path.join(base_dir, "scripts"))

from app.database import DatabaseManager
from app.sector_mapping import SECTOR_INDEX_MAP
from screener_service import ScreenerService

MAX_SESSION_RESTARTS = 8


def load_unmapped_stocks(session):
    rows = session.execute(
        text("""
        SELECT id, nse_symbol, industry FROM stocks
        WHERE is_active = true
    """)
    ).fetchall()
    unmapped = [r for r in rows if r.industry not in SECTOR_INDEX_MAP]
    print(f"{len(rows)} active stocks, {len(unmapped)} currently unmapped to an NSE sector index.")
    return unmapped


def write_sector_info(session, stock_id, sector_info):
    subsector = sector_info["subsector3"] or sector_info["subsector2"]
    session.execute(
        text("""
        UPDATE stocks SET
            sector = :sector,
            subsector = :subsector,
            subsector1 = :subsector1,
            subsector2 = :subsector2,
            subsector3 = :subsector3,
            industry = :industry
        WHERE id = :stock_id
    """),
        {
            "sector": sector_info["sector"] or None,
            "subsector": subsector or None,
            "subsector1": sector_info["subsector1"] or None,
            "subsector2": sector_info["subsector2"] or None,
            "subsector3": sector_info["subsector3"] or None,
            "industry": sector_info["subsector3"] or None,  # finest level = BSE's "Industry" column equivalent
            "stock_id": stock_id,
        },
    )


def process_batch(service, session, unmapped, stats):
    """Process one batch with the given (live) service session. Returns
    True if the session died mid-batch (caller should restart), False if
    it ran to completion normally."""
    for i, row in enumerate(unmapped, start=1):
        symbol = row.nse_symbol
        if not symbol:
            continue

        url = f"{service.base_url}/company/{symbol}/consolidated/"
        try:
            service.driver.get(url)
            time.sleep(2)

            if "company" not in service.driver.current_url.lower():
                stats["failed"].append((symbol, "page did not load"))
                continue

            sector_info = service._extract_sector_info()
            if not any(sector_info.values()):
                stats["failed"].append((symbol, "no classification found"))
                continue

            write_sector_info(session, row.id, sector_info)
            stats["found"] += 1

            new_industry = sector_info["subsector3"]
            if new_industry not in SECTOR_INDEX_MAP:
                stats["still_unmapped_industries"][new_industry] = (
                    stats["still_unmapped_industries"].get(new_industry, 0) + 1
                )

        except WebDriverException as e:
            # Session/browser died (e.g. "invalid session id") - every
            # subsequent call would fail instantly too, so stop this batch
            # and let main() restart with a fresh session instead of
            # racing through the rest as instant failures.
            print(f"  Session appears dead at {i}/{len(unmapped)} ({symbol}): {type(e).__name__}")
            return True
        except Exception as e:
            stats["failed"].append((symbol, str(e)))
            continue

        if i % 25 == 0:
            session.commit()
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Processed {i}/{len(unmapped)} "
                f"({stats['found']} classified, {len(stats['failed'])} failed)"
            )

    session.commit()
    return False


def main():
    username = os.getenv("SCREENER_USERNAME")
    password = os.getenv("SCREENER_PASSWORD")
    if not username or not password:
        print("SCREENER_USERNAME / SCREENER_PASSWORD not set in web/.env")
        sys.exit(1)

    db = DatabaseManager()
    session = db.Session()

    stats = {"found": 0, "failed": [], "still_unmapped_industries": {}}

    try:
        restarts = 0
        while True:
            unmapped = load_unmapped_stocks(session)
            if not unmapped:
                break

            with ScreenerService(headless=True) as service:
                if not service.login(username, password):
                    print("Login failed.")
                    sys.exit(1)
                session_died = process_batch(service, session, unmapped, stats)

            if not session_died:
                break

            restarts += 1
            if restarts > MAX_SESSION_RESTARTS:
                print(f"Hit max session restarts ({MAX_SESSION_RESTARTS}), stopping.")
                break
            print(f"Restarting with a fresh session (attempt {restarts}/{MAX_SESSION_RESTARTS})...")

        print(f"\n=== Done: {datetime.now().strftime('%H:%M:%S')} ===")
        print(f"Classified (sector data written): {stats['found']}")
        print(f"Failed: {len(stats['failed'])}")
        if stats["failed"]:
            print("Failed symbols (first 30):")
            for sym, reason in stats["failed"][:30]:
                print(f"  {sym}: {reason}")

        still_unmapped = stats["still_unmapped_industries"]
        newly_mapped = stats["found"] - sum(still_unmapped.values())
        print(
            f"\nOf the {stats['found']} classified, {newly_mapped} now map to an NSE sector index "
            f"(via app/sector_mapping.py's SECTOR_INDEX_MAP)."
        )
        print(
            f"{sum(still_unmapped.values())} still don't map to any NSE sector index "
            f"(real classification, just no matching index) - top industries:"
        )
        for industry, cnt in sorted(still_unmapped.items(), key=lambda x: -x[1])[:20]:
            print(f"  {industry}: {cnt}")

    finally:
        session.close()


if __name__ == "__main__":
    main()
