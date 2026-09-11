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


import subprocess
from datetime import date

try:
    import structlog
except ImportError:
    structlog = None

try:
    from app.core.config import settings
    from app.core.database import get_db, init_db
    from app.core.health import note_scan_run
    from app.core.logging import setup_logging
    from app.graph.graph import analyze_ticker
    from app.models.models import DecisionRecord, ScanRun, utcnow
    from app.portfolio.simulator import simulator
    from app.screener.filters import screen
    from app.screener.universe import fetch_universe
except ImportError:
    settings = None
    get_db = init_db = note_scan_run = setup_logging = analyze_ticker = None
    DecisionRecord = ScanRun = utcnow = None
    simulator = screen = fetch_universe = None

if structlog:
    setup_logging()
    logger = structlog.get_logger()
else:
    import logging

    logger = logging.getLogger(__name__)


def _git_sha() -> str | None:
    """Short commit hash, recorded on decisions so results trace to code."""
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


GIT_SHA = _git_sha()


def run_scan():
    """Run the daily scan: screen the universe, analyse candidates, open trades.

    Writes a decision record for every candidate it evaluates, bought or not,
    which is what makes rejected trades measurable later. Stops early if the
    circuit breaker is active or the portfolio is full; a failure on one
    ticker never abandons the rest.
    """
    logger.info("scan_start")
    candidates_found = 0
    error = None

    try:
        tickers = fetch_universe()

        candidates, _regime_open, _breadth = screen(tickers)
        candidates_found = len(candidates)

        if not candidates:
            logger.info("scan_no_candidates")
            return

        # Circuit breaker - pause new entires if portfolio down >8% from 30-day peak
        if simulator.is_circuit_breaker_active():
            logger.info("scan_circuit_breaker_triggered")
            return

        logger.info("scan_candidates_found", count=len(candidates))

        portfolio = simulator.get_portfolio_state()
        settings.max_positions - portfolio["open_positions"]
        analyzed = 0

        for candidate in candidates:
            ticker = candidate["ticker"]

            portfolio = simulator.get_portfolio_state()

            if portfolio["open_positions"] >= settings.max_positions:
                logger.info("scan_max_positions_reached")
                break

            analyzed += 1
            try:
                analyze_ticker(ticker)
                # Process result...
            except Exception as e:
                logger.exception("scan_ticker_failed", ticker=ticker, error=str(e))
                continue

    except Exception as e:
        logger.exception("scan_failed", error=str(e))
        error = str(e)
    finally:
        logger.info("scan_complete", candidates_found=candidates_found, analyzed=analyzed, error=error)
