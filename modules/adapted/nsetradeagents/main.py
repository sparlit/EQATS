from datetime import date

import structlog
from app.core.logging import setup_logging
from app.core.database import init_db, get_db
from app.core.health import note_scan_run
from app.models.models import DecisionRecord, ScanRun, utcnow
from app.core.config import settings
from app.screener.universe import fetch_universe
from app.screener.filters import screen
from app.graph.graph import analyze_ticker
from app.portfolio.simulator import simulator

import subprocess

setup_logging()
logger = structlog.get_logger()


def _git_sha() -> str | None:
    """Short commit hash, recorded on decisions so results trace to code."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
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

        candidates, regime_open, breadth = screen(tickers)
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
        capacity = settings.max_positions - portfolio["open_positions"]
        analyzed = 0

        for candidate in candidates:
            ticker = candidate["ticker"]

            portfolio = simulator.get_portfolio_state()

            if portfolio["open_positions"] >= settings.max_positions:
                logger.info(
                    "scan_max_positions_reached", open=portfolio["open_positions"]
                )
                break

            # On a blocked day nothing opens, so the position-count break above
            # never fires. Cap the shadow sample at what could have been traded,
            # or a quiet market costs a veto call per candidate for nothing.
            if not regime_open and analyzed >= capacity:
                logger.info("scan_shadow_cap_reached", analyzed=analyzed)
                break

            open_tickers = {position["ticker"] for position in portfolio["positions"]}
            if ticker in open_tickers:
                logger.info("scan_already_holding", ticker=ticker)
                continue

            logger.info("scan_analysing", ticker=ticker, score=candidate["score"])

            open_position_sectors = [p["sector"] for p in portfolio["positions"]]
            try:
                final_state = analyze_ticker(
                    ticker=ticker,
                    portfolio_cash=portfolio["cash"],
                    open_positions=portfolio["open_positions"],
                    open_position_sectors=open_position_sectors,
                )
                analyzed += 1
            except Exception as e:
                logger.error("scan_ticker_failed", ticker=ticker, error=str(e))
                continue

            trade_result = final_state.get("trade_result") or {}
            executed = trade_result.get("executed", False)
            entered = executed and regime_open
            rules_score = final_state.get("rules_score")

            block_reasons = trade_result.get("reasons")
            block_reason = ", ".join(block_reasons) if block_reasons else None

            if executed and not regime_open:
                block_reason = "regime: under half the universe above its 50d SMA"

            ind = (final_state.get("technical_signals") or {}).get("indicators") or {}
            bands = final_state.get("rules_bands") or {}
            ctx = final_state.get("market_context") or {}

            veto = final_state.get("veto_result") or {}

            with get_db() as db:
                db.add(
                    DecisionRecord(
                        as_of=date.today(),
                        ticker=ticker,
                        git_sha=GIT_SHA,
                        score=rules_score,
                        entry_timing=bands.get("entry_timing"),
                        momentum_quality=bands.get("momentum_quality"),
                        risk_reward_view=bands.get("risk_reward_view"),
                        market_regime=bands.get("market_regime"),
                        price=ind.get("current_price"),
                        rsi=ind.get("rsi"),
                        atr_pct=ind.get("atr_pct"),
                        volume_ratio=ind.get("volume_ratio"),
                        momentum_5d=ind.get("momentum_5d"),
                        day_change_pct=ind.get("day_change_pct"),
                        india_vix=ctx.get("india_vix"),
                        nifty_20d_pct=ctx.get("nifty_20d_pct"),
                        entered=entered,
                        block_reason=block_reason,
                        regime_open=regime_open,
                        breadth_pct=breadth,
                        veto_verdict=veto.get("verdict"),
                        veto_reason=veto.get("reason"),
                        veto_cited_fact=veto.get("cited_fact"),
                        veto_source_url=veto.get("source_url"),
                        veto_checked=veto.get("checked"),
                        veto_transcript=veto.get("transcript"),
                        veto_model=veto.get("model"),
                        veto_mode=settings.veto_mode,
                    )
                )
            if entered:
                simulator.open_trade(
                    trade_result=trade_result,
                    technical=final_state.get("technical_signals") or {},
                )

        logger.info("scan_complete")
    except Exception as e:
        error = str(e)
        raise
    finally:
        # Recorded even when the scan raised, and never allowed to raise itself:
        # an exception here would replace the real one on its way out.
        ran_at = utcnow()
        note_scan_run(ran_at)
        try:
            with get_db() as db:
                db.add(
                    ScanRun(
                        ran_at=ran_at,
                        candidates_found=candidates_found,
                        error=error,
                    )
                )
        except Exception as e:
            logger.error("scan_run_record_failed", error=str(e))

        # A portfolio snapshot every scan, whatever the outcome. This used to
        # sit after the candidate loop, so a quiet or blocked day recorded
        # nothing — leaving the equity curve with holes on exactly the days the
        # portfolio was flat, and the dashboard blank until the first trade.
        try:
            simulator.save_snapshot()
        except Exception as e:
            logger.error("snapshot_failed", error=str(e))


if __name__ == "__main__":
    init_db()
    run_scan()
