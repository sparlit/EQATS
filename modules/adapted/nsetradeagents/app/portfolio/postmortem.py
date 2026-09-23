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


from dataclasses import replace
from datetime import date, datetime, timedelta

import structlog
from app.core.config import settings
from app.core.database import get_db
from app.models.models import DecisionRecord
from app.portfolio.exits import (
    Bar,
    PositionView,
    evaluate_exit,
    stop_pct,
    target_pct,
    update_trail,
)
from app.utils.market_data import extract_ticker_df, safe_yf_download

logger = structlog.get_logger()

# Half the traded universe, so a decision is judged against the kind of stock
# it actually is. Nifty 50 would flatter every smallcap year and punish every
# large-cap one.
BENCHMARK = "NIFTYSMLCAP250.NS"


def _simulate(record, bars) -> tuple[float, str, date] | None:
    """Replay what a decision would have returned, had it been traded.

    Buys at the close of the decision day — the same bar the signal came from,
    matching live — and runs the shared exit rules. Returns
    (pnl_pct, reason, exit_date), or None when the trade hasn't resolved yet
    and should be retried later.
    """

    on_signal_day = bars.loc[bars.index.date <= record.as_of]
    after = bars.loc[bars.index.date > record.as_of]
    if on_signal_day.empty or after.empty:
        return None

    entry_price = float(on_signal_day.iloc[-1]["Close"])
    if entry_price <= 0:
        return None

    atr = record.atr_pct or 0

    pos = PositionView(
        entry_date=record.as_of,
        stop_price=entry_price * (1 - stop_pct(atr)),
        target_price=entry_price * (1 + target_pct(atr)),
    )
    peak = entry_price

    for ts, row in after.iterrows():
        bar = Bar(
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
        )
        result = evaluate_exit(pos, bar, ts.date())
        peak, new_trail, active = update_trail(
            close=bar.close,
            entry_price=entry_price,
            atr_pct=atr,
            peak_price=peak,
            trail_stop=pos.trail_stop,
            stop_price=pos.stop_price,
        )
        if active:
            pos = replace(pos, trail_stop=new_trail)

        if result:
            exit_price, reason = result
            pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2)
            return pnl_pct, reason, ts.date()

    return None


def _benchmark_return(bench_close, start: date, end: date) -> float | None:
    """Smallcap index return over the same window, for judging alpha.

    None when the index data doesn't cover the window, so the caller can
    record a raw outcome without an alpha rather than dropping the record.
    """
    if bench_close is None or bench_close.empty:
        return None
    try:
        at_start = bench_close.loc[bench_close.index.date <= start]
        at_end = bench_close.loc[bench_close.index.date <= end]
        if at_start.empty or at_end.empty:
            return None
        return round((float(at_end.iloc[-1]) / float(at_start.iloc[-1]) - 1) * 100, 2)
    except Exception:
        return None


def fill_outcomes() -> int:
    """Work out what happened to decisions that are old enough to judge.

    Covers stocks that were bought and stocks that were passed over, so both
    are measured the same way. Records that haven't resolved stay pending.

    Returns how many were filled in.
    """
    cutoff = date.today() - timedelta(days=settings.max_hold_days + 5)

    with get_db() as db:
        pending = (
            db.query(DecisionRecord)
            .filter(DecisionRecord.outcome_pnl_pct.is_(None), DecisionRecord.as_of <= cutoff)
            .all()
        )

        if not pending:
            logger.info("postmortem_nothing_pending")
            return 0

        tickers = sorted({r.ticker for r in pending})
        logger.info("postmortem_start", records=len(pending), tickers=len(tickers))

        raw = safe_yf_download(tickers, period="6mo", group_by="ticker")

        # One extra download for the whole batch, so every outcome is judged
        # against the same index over its own holding window.
        try:
            bench = safe_yf_download(BENCHMARK, period="6mo")
            bench_close = None if bench is None or bench.empty else bench["Close"].squeeze()
        except Exception as e:
            logger.warning("postmortem_benchmark_failed", error=str(e))
            bench_close = None

        filled = 0
        for record in pending:
            try:
                bars = extract_ticker_df(raw, record.ticker)
                if bars is None:
                    continue
                result = _simulate(record, bars.dropna(subset=["Close"]))
                if result is None:
                    continue
                pnl_pct, reason, exit_date = result
                record.outcome_pnl_pct = pnl_pct
                record.outcome_reason = reason
                record.outcome_exit_date = exit_date

                bench_ret = _benchmark_return(bench_close, record.as_of, exit_date)
                if bench_ret is not None:
                    record.outcome_alpha_pct = round(pnl_pct - bench_ret, 2)

                record.outcome_filled_at = datetime.now()
                filled += 1
            except Exception as e:
                logger.warning("postmortem_failed", ticker=record.ticker, error=str(e))

        logger.info("postmortem_done", filled=filled, pending=len(pending))
        return filled
