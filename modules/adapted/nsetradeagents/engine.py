from dataclasses import dataclass
from datetime import date

import pandas as pd
import structlog

from app.backtest.store import BacktestStore
from app.agents.technical import _compute_signal
from app.core.config import settings
from app.portfolio.exits import (
    Bar,
    PositionView,
    evaluate_exit,
    stop_pct,
    target_pct,
    update_trail,
)
from app.screener.filters import evaluate_candidate
from app.utils.indicators import compute_indicators
from app.utils.scoring import compute_rules_confidence

logger = structlog.get_logger()


@dataclass
class Position:
    """An open position during a backtest run."""

    ticker: str
    entry_date: date
    entry_price: float
    stop_price: float
    target_price: float
    shares: int
    capital_used: float
    score: int = 0
    atr_pct: float = 0.0
    peak_price: float = 0.0
    trail_stop: float = 0.0


@dataclass
class ClosedTrade:
    """A finished trade, as written to the trade log."""

    ticker: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    exit_reason: str  # "stop" | "target" | "timeout" | "trail" | "end_of_backtest"
    score: int = 0


def _check_exit(pos: Position, bar: pd.Series, today: date) -> tuple[float, str] | None:
    """Adapt a backtest position and a pandas bar to the shared exit rules.

    Keeps pandas out of `exits.py` so the same rules can serve the live path.
    """
    return evaluate_exit(
        PositionView(
            entry_date=pos.entry_date,
            stop_price=pos.stop_price,
            target_price=pos.target_price,
            trail_stop=pos.trail_stop,
        ),
        Bar(
            open=float(bar["Open"]),
            high=float(bar["High"]),
            low=float(bar["Low"]),
            close=float(bar["Close"]),
        ),
        today,
    )


def _market_context(nifty: pd.DataFrame, vix: pd.DataFrame, ts: pd.Timestamp) -> dict:
    """Build the market context for one day from the index and VIX series.

    Sector fields are empty: the cache holds no sector data, so sector rules
    only take effect live.
    """
    try:
        n = nifty.loc[:ts]["Close"]
        vix_val = float(vix.at[ts, "Close"]) if ts in vix.index else 0.0
        nifty_day = (n.iloc[-1] - n.iloc[-2]) / n.iloc[-2] * 100 if len(n) >= 2 else 0.0
        nifty_10d = (
            (n.iloc[-1] - n.iloc[-11]) / n.iloc[-11] * 100 if len(n) >= 11 else 0.0
        )
        nifty_20d = (
            (n.iloc[-1] - n.iloc[-21]) / n.iloc[-21] * 100 if len(n) >= 21 else 0.0
        )
    except Exception:
        return {
            "nifty_day_pct": 0.0,
            "sector_day_pct": 0.0,
            "divergence_note": "",
            "india_vix": 0.0,
            "nifty_10d_pct": 0.0,
            "nifty_20d_pct": 0.0,
        }
    return {
        "nifty_day_pct": round(nifty_day, 2),
        "sector_day_pct": 0.0,
        "divergence_note": "",
        "india_vix": round(vix_val, 2),
        "nifty_10d_pct": round(nifty_10d, 2),
        "nifty_20d_pct": round(nifty_20d, 2),
    }


def _open_position(
    p: dict, price: float, day: date, cash: float
) -> tuple[Position | None, float]:
    """Build a position at a given fill price, and return the cash left.

    Shared by both entry models so the sizing and level arithmetic cannot
    drift between them.
    """
    if price <= 0:
        return None, cash
    budget = min(cash, settings.starting_capital * settings.max_position_pct)
    shares = int(budget / price)
    if shares <= 0:
        return None, cash

    capital_used = shares * price
    atr_pct = p.get("atr_pct", 0.0)
    stop = stop_pct(atr_pct)

    return (
        Position(
            ticker=p["ticker"],
            entry_date=day,
            entry_price=price,
            stop_price=price * (1 - stop),
            target_price=price * (1 + target_pct(atr_pct)),
            shares=shares,
            capital_used=capital_used,
            score=p["score"],
            atr_pct=atr_pct,
            peak_price=price,
        ),
        cash - capital_used,
    )


def run_backtest(
    db_path: str = "backtest_data.db",
    start: date = date(2022, 1, 1),
    end: date = date(2025, 12, 31),
) -> tuple[list[ClosedTrade], list[tuple[date, float]], list[int]]:
    """Replay the strategy day by day over historical bars.

    Each day, in order: check exits against today's bar, update trailing stops
    on the close, then score new candidates.

    A signal is filled at the close of the same bar it came from, so the fill
    uses a price that was not knowable at decision time. Live closes that gap by
    scanning at 15:00 and buying before 15:30, when the filters are ~92%
    resolved — the backtest is optimistic by the difference.

    Returns (closed_trades, equity_curve, all_candidate_scores).
    """
    store = BacktestStore(db_path)
    trading_days = store.get_trading_days(start, end)
    warmup_start = date(start.year - 1, start.month, start.day)
    all_bars = store.preload(warmup_start, end)
    store.close()

    if not trading_days or not all_bars:
        logger.error("backtest_no_data", db=db_path)
        return [], [], []

    nifty = all_bars.get("^NSEI", pd.DataFrame())
    vix = all_bars.get("^INDIAVIX", pd.DataFrame())
    universe = sorted(t for t in all_bars if not t.startswith("^"))

    logger.info("backtest_init", trading_days=len(trading_days), universe=len(universe))

    # Breadth, precomputed once: recomputing 50-day means across the whole
    # universe on every trading day would dominate the run. Only tickers with
    # data on a given day count toward that day's percentage.
    _closes = pd.DataFrame({t: all_bars[t]["Close"] for t in universe})
    _sma = _closes.rolling(settings.regime_sma_period).mean()
    _valid = _closes.notna() & _sma.notna()
    breadth = (
        ((_closes > _sma) & _valid).sum(axis=1)
        / _valid.sum(axis=1).replace(0, pd.NA)
        * 100
    )

    cash: float = settings.starting_capital
    open_positions: list[Position] = []
    closed_trades: list[ClosedTrade] = []
    equity_curve: list[tuple[date, float]] = []
    all_scores: list[int] = []

    for idx, day in enumerate(trading_days):
        ts = pd.Timestamp(day)

        # 1. Check exits on today's bar (using EOD trail stop from yesterday)
        for pos in list(open_positions):
            bars = all_bars.get(pos.ticker)
            if bars is None or ts not in bars.index:
                continue
            result = _check_exit(pos, bars.loc[ts], day)
            if result is None:
                continue
            exit_price, reason = result
            proceeds = pos.shares * exit_price
            pnl = proceeds - pos.capital_used
            cash += proceeds
            closed_trades.append(
                ClosedTrade(
                    ticker=pos.ticker,
                    entry_date=pos.entry_date,
                    exit_date=day,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    shares=pos.shares,
                    pnl=pnl,
                    pnl_pct=pnl / pos.capital_used * 100,
                    exit_reason=reason,
                    score=pos.score,
                )
            )
            open_positions.remove(pos)

        # 2. EOD trailing stop update
        eod_exits: list[tuple[Position, float]] = []
        for pos in open_positions:
            bars = all_bars.get(pos.ticker)
            if bars is None or ts not in bars.index:
                continue
            close_p = float(bars.at[ts, "Close"])

            was_trailing = pos.trail_stop > 0

            pos.peak_price, new_trail, active = update_trail(
                close=close_p,
                entry_price=pos.entry_price,
                atr_pct=pos.atr_pct,
                peak_price=pos.peak_price,
                trail_stop=pos.trail_stop,
                stop_price=pos.stop_price,
            )
            if not active and not was_trailing:
                continue
            pos.trail_stop = new_trail

            if close_p <= pos.trail_stop:
                eod_exits.append((pos, close_p))

        for pos, close_p in eod_exits:
            if pos not in open_positions:
                continue
            proceeds = pos.shares * close_p
            pnl = proceeds - pos.capital_used
            cash += proceeds
            closed_trades.append(
                ClosedTrade(
                    ticker=pos.ticker,
                    entry_date=pos.entry_date,
                    exit_date=day,
                    entry_price=pos.entry_price,
                    exit_price=close_p,
                    shares=pos.shares,
                    pnl=pnl,
                    pnl_pct=pnl / pos.capital_used * 100,
                    exit_reason="trail",
                    score=pos.score,
                )
            )
            open_positions.remove(pos)

        # 3. Generate new signals from today's close and fill them there
        capacity = settings.max_positions - len(open_positions)
        b = breadth.get(ts)
        gate_open = b is None or pd.isna(b) or b >= settings.breadth_floor_pct
        if capacity > 0 and gate_open:
            held = {p.ticker for p in open_positions}
            mkt_ctx = _market_context(nifty, vix, ts)
            signal_candidates: list[dict] = []

            for ticker in universe:
                if ticker in held:
                    continue
                bars = all_bars.get(ticker)
                if bars is None:
                    continue
                bars_asof = bars.loc[:ts]
                if len(bars_asof) < 50:
                    continue
                try:
                    ind = compute_indicators(bars_asof)
                except Exception:
                    continue

                if _compute_signal(ind) != "BUY":
                    continue

                candidate, _ = evaluate_candidate(ind)
                if candidate is None:
                    continue

                est = ind["current_price"]
                try:
                    score = compute_rules_confidence(
                        {"signal": "BUY", "indicators": ind},
                        {
                            "stop_loss": est * (1 - stop_pct(ind.get("atr_pct", 0.0))),
                            "take_profit": est
                            * (1 + target_pct(ind.get("atr_pct", 0.0))),
                        },
                        mkt_ctx,
                    )["score"]
                except Exception as e:
                    logger.warning("score_failed", ticker=ticker, day=day, error=str(e))
                    continue
                all_scores.append(score)

                if score >= settings.rules_confidence_threshold:
                    signal_candidates.append(
                        {
                            "ticker": ticker,
                            "score": score,
                            "screener_score": candidate["screener_score"],
                            "atr_pct": ind["atr_pct"],
                        }
                    )

            signal_candidates.sort(key=lambda x: x["screener_score"], reverse=True)
            selected = signal_candidates[:capacity]

            # Filled on the same bar the signal came from. Runs after exits,
            # so a position opened here cannot exit the same day.
            for p in selected:
                if len(open_positions) >= settings.max_positions:
                    break
                bars = all_bars.get(p["ticker"])
                if bars is None or ts not in bars.index:
                    continue
                pos, cash = _open_position(p, float(bars.at[ts, "Close"]), day, cash)
                if pos:
                    open_positions.append(pos)

        # 4. Daily equity snapshot
        equity = cash
        for pos in open_positions:
            bars = all_bars.get(pos.ticker)
            price = (
                float(bars.at[ts, "Close"])
                if bars is not None and ts in bars.index
                else pos.entry_price
            )
            equity += pos.shares * price
        equity_curve.append((day, equity))

        if idx % 50 == 0:
            logger.info(
                "backtest_progress",
                day=day,
                equity=round(equity),
                open=len(open_positions),
                trades=len(closed_trades),
            )

    # Force-close any surviving positions at final day's close
    if trading_days:
        last_ts = pd.Timestamp(trading_days[-1])
        for pos in list(open_positions):
            bars = all_bars.get(pos.ticker)
            price = (
                float(bars.at[last_ts, "Close"])
                if bars is not None and last_ts in bars.index
                else pos.entry_price
            )
            proceeds = pos.shares * price
            pnl = proceeds - pos.capital_used
            cash += proceeds
            closed_trades.append(
                ClosedTrade(
                    ticker=pos.ticker,
                    entry_date=pos.entry_date,
                    exit_date=trading_days[-1],
                    entry_price=pos.entry_price,
                    exit_price=price,
                    shares=pos.shares,
                    pnl=pnl,
                    pnl_pct=pnl / pos.capital_used * 100,
                    exit_reason="end_of_backtest",
                )
            )

    final_equity = equity_curve[-1][1] if equity_curve else settings.starting_capital
    logger.info(
        "backtest_done", trades=len(closed_trades), final_equity=round(final_equity)
    )
    return closed_trades, equity_curve, all_scores
