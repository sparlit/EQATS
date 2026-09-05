import requests
import pytz
import structlog
from datetime import datetime
from functools import lru_cache
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging import setup_logging
from app.portfolio.exits import Bar, PositionView, evaluate_exit, update_trail
from app.portfolio.postmortem import fill_outcomes
from app.portfolio.simulator import simulator
from app.utils.market_data import safe_yf_download, extract_ticker_df

setup_logging()
logger = structlog.get_logger()

IST = pytz.timezone("Asia/Kolkata")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com",
}


@lru_cache(maxsize=1)
def _load_nse_holidays(year: int) -> set[str]:
    """Trading holidays for a year, from NSE's official list. Cached per year."""
    resp = requests.get(
        "https://www.nseindia.com/api/holiday-master?type=trading",
        headers=NSE_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    holidays = {entry["tradingDate"] for entry in resp.json().get("CM", [])}
    logger.info("nse_holidays_loaded", count=len(holidays), year=year)
    return holidays


def _is_market_open() -> bool:
    """True during NSE trading hours on a working day.

    If the holiday list can't be fetched, assumes the market is open rather
    than skipping the day.
    """
    now = datetime.now(IST)

    if now.weekday() >= 5:
        return False

    try:
        holidays = _load_nse_holidays(now.year)
        if now.strftime("%d-%b-%Y") in holidays:
            logger.info(
                "market_closed", reason="NSE holiday", date=now.strftime("%d-%b-%Y")
            )
            return False
    except Exception as e:
        logger.warning("holiday_check_failed", error=str(e))

    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def review_positions() -> None:
    """Check open positions against their exit rules using live prices.

    Runs through the market day. Prices are single observations rather than
    full bars, so intraday moves between checks are not seen.
    """
    if not _is_market_open():
        logger.info("position_review_skipped", reason="market closed")
        return

    portfolio = simulator.get_portfolio_state()
    positions = portfolio["positions"]

    if not positions:
        logger.info("position_review_no_open_positions")
        return

    tickers = [position["ticker"] for position in positions]
    logger.info("position_review_start", tickers=tickers)

    try:
        raw = safe_yf_download(tickers, period="1d", interval="5m", group_by="ticker")
    except Exception as e:
        logger.error("position_review_fetch_failed", error=str(e))
        return

    if raw is None or raw.empty:
        logger.warning("position_review_no_data")
        return

    live_prices: dict[str, float] = {}

    for position in positions:
        ticker = position["ticker"]
        try:
            df = extract_ticker_df(raw, ticker)
            if df is None:
                logger.error(
                    "position_review_fetch_failed",
                    ticker=ticker,
                    error="ticker not in batch download",
                )
                continue
            current_price = float(df["Close"].dropna().iloc[-1])
            live_prices[ticker] = current_price
        except Exception as e:
            logger.error("position_review_fetch_failed", ticker=ticker, error=str(e))
            continue

        result = evaluate_exit(
            PositionView(
                entry_date=position["opened_at"].date(),
                stop_price=position["stop_loss"],
                target_price=position["take_profit"],
                trail_stop=position.get("trail_stop") or 0.0,
            ),
            Bar.flat(current_price),
            datetime.now(IST).date(),
        )

        if result is None:
            logger.info("position_review_hold", ticker=ticker, price=current_price)
            continue

        exit_price, reason = result
        logger.info(
            "position_review_exit", ticker=ticker, price=exit_price, reason=reason
        )
        simulator.close_trade(ticker, exit_price, reason=reason)

    simulator.save_snapshot(open_prices=live_prices if live_prices else None)


def review_trail_eod() -> None:
    """Advance trailing stops on the day's closing prices.

    Closes any position whose close has fallen through its trail.
    """
    portfolio = simulator.get_portfolio_state()
    positions = portfolio["positions"]

    if not positions:
        logger.info("trail_eod_no_positions")
        return

    tickers = [position["ticker"] for position in positions]
    logger.info("trail_eod_start", tickers=tickers)

    try:
        raw = safe_yf_download(tickers, period="2d", group_by="ticker")
    except Exception as e:
        logger.error("trail_eod_fetch_failed", error=str(e))
        return

    if raw is None or raw.empty:
        logger.warning("trail_eod_no_data")
        return

    for position in positions:
        ticker = position["ticker"]
        try:
            df = extract_ticker_df(raw, ticker)
            if df is None:
                logger.error(
                    "trail_eod_fetch_failed",
                    ticker=ticker,
                    error="ticker not in batch download",
                )
                continue
            close_price = float(df["Close"].dropna().iloc[-1])
        except Exception as e:
            logger.error("trail_eod_fetch_failed", ticker=ticker, error=str(e))
            continue

        entry_price = position["entry_price"]
        peak_price = position.get("peak_price") or 0
        trail_stop_val = position.get("trail_stop") or 0
        atr_pct = position.get("atr_pct") or 0

        new_peak, new_trail_stop, active = update_trail(
            close=close_price,
            entry_price=entry_price,
            atr_pct=atr_pct,
            peak_price=peak_price,
            trail_stop=trail_stop_val,
            stop_price=position["stop_loss"],
        )

        is_already_trail = peak_price > 0

        if not active and not is_already_trail:
            continue

        if not is_already_trail:
            simulator.update_trail(ticker, new_peak, new_trail_stop)
            logger.info(
                "trail_activated",
                ticker=ticker,
                close=close_price,
                peak=new_peak,
                trail_stop=new_trail_stop,
            )
        elif new_peak != peak_price or new_trail_stop != trail_stop_val:
            simulator.update_trail(ticker, new_peak, new_trail_stop)
            logger.info(
                "trail_updated",
                ticker=ticker,
                close=close_price,
                peak=new_peak,
                trail_stop=new_trail_stop,
            )

        if close_price <= new_trail_stop:
            logger.info(
                "trail_eod_hit",
                ticker=ticker,
                close=close_price,
                peak=new_peak,
                trail_stop=new_trail_stop,
            )
            simulator.close_trade(ticker, close_price, reason="trail")


def create_scheduler() -> BackgroundScheduler:
    """Build the job schedule: the afternoon scan, intraday position checks,
    the end-of-day trail update, and the post-mortem.

    The scan runs late in the session rather than at the open because the
    signal is a claim about today's action — the setup is evaluated and bought
    on the same day. Buying at the next open instead forfeits the night after
    the signal, which is worth 1.5x a typical held night.
    """
    from main import run_scan

    sched = BackgroundScheduler(timezone=IST)

    # 15:00, not later: the scan downloads 400 tickers and then runs the
    # LangGraph pipeline — including a veto call — per candidate, so it needs
    # roughly ten minutes. Orders have to be in before the 15:30 close, and a
    # missed close is a missed trade rather than a late one.
    sched.add_job(
        run_scan,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=0, timezone=IST),
        name="afternoon_scan",
    )

    sched.add_job(review_positions, IntervalTrigger(minutes=15), name="position_review")

    sched.add_job(
        review_trail_eod,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=35, timezone=IST),
        name="trail_eod_review",
    )

    sched.add_job(
        fill_outcomes,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=IST),
        name="postmortem",
    )

    logger.info(
        "scheduler_ready",
        jobs=[
            f"{j.name}: {j.trigger}" for j in sched.get_jobs()
        ],
    )

    return sched
