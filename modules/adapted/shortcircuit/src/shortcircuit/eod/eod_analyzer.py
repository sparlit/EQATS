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


import asyncio
import inspect
import logging
import os
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from shortcircuit import config
from shortcircuit.state.database import DatabaseManager
from shortcircuit.strategy.features import compute_rsi_wilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
EOD_SQUAREOFF_TIME = datetime.strptime("15:10", "%H:%M").time()

REPORT_DIR = "logs/eod_reports"


class EODAnalyzer:
    """
    End-of-day analyzer that supports both:
    - in-process async execution (runtime scheduler path), and
    - standalone script execution (sync query() fallback).
    """

    def __init__(self, fyers=None, db_manager=None, *, fyers_client=None, db=None):
        self.fyers = fyers_client if fyers_client is not None else fyers
        self.db = db if db is not None else db_manager
        os.makedirs(REPORT_DIR, exist_ok=True)

    async def run_daily_analysis(self, date=None):
        """
        Main async entrypoint for EOD analysis.
        """
        if self.db is None:
            raise RuntimeError("EODAnalyzer: db is None — DatabaseManager was not injected.")

        if not hasattr(self.db, "fetch") and not hasattr(self.db, "query"):
            raise RuntimeError("EODAnalyzer: injected db is missing .query or .fetch method.")

        if isinstance(date, str):
            import datetime as _dt

            target_date = _dt.date.fromisoformat(date)
        else:
            target_date = date if date is not None else datetime.now().date()

        logger.info("Starting EOD analysis for %s", target_date)

        # 1. Fetch live trades for performance/audit
        trades = await self._fetch_trades(target_date)
        audit_results = (
            self.perform_safety_audit(trades)
            if trades
            else {"status": "PASSED", "issues": [], "orphans": 0, "processed": 0}
        )
        soft_stop_results = await self.analyze_soft_stops(target_date)
        stats = self.calculate_performance(trades)

        # Ghost audit: label signals that passed validation but were never traded.
        ghost_stats = {"processed": 0, "wins": 0, "losses": 0, "tp_hits": 0, "eod_wins": 0}
        try:
            # Force target_date passed to audit
            ghost_stats = await self.audit_missed_signals(target_date)
            stats["ghost_trades"] = ghost_stats
        except Exception as e:
            logger.error(f"Ghost Signal Audit failed: {e}")

        # 3. Report generation
        report_text = self.generate_report(
            target_date, stats, audit_results, soft_stop_results, ghost_stats
        )

        # 4. Persistence
        await self._save_summary_db(target_date, stats, audit_results)

        return report_text

    async def audit_missed_signals(self, target_date: date):
        """
        Finds signals that passed validation but weren't traded.
        Simulates their path (SL/TP) to provide labeled data for the ML Trainer.
        """
        from shortcircuit.observability.ml_logger import MLDataLogger, get_ml_logger

        target_date_str = target_date.isoformat()
        active_logger = get_ml_logger()
        ml_logger = (
            active_logger
            if getattr(active_logger, "today", None) == target_date_str
            else MLDataLogger(session_date=target_date_str)
        )

        unlabeled_df = ml_logger.get_unlabeled_observations(target_date_str)
        unlabeled = unlabeled_df.to_dict("records") if not unlabeled_df.empty else []
        if not unlabeled:
            logger.info("No unlabeled observations to audit.")
            return {"processed": 0, "wins": 0, "losses": 0}

        logger.info(f"Auditing {len(unlabeled)} missed signals for {target_date}...")
        results = {
            "processed": 0,
            "wins": 0,
            "losses": 0,
            "tp_hits": 0,
            "eod_wins": 0,
            "not_triggered": 0,
        }

        # Global audit timeout to prevent EOD hang
        audit_start_ts = time.monotonic()
        MAX_AUDIT_SECONDS = 60

        for obs in unlabeled:
            # Check for global timeout
            if time.monotonic() - audit_start_ts > MAX_AUDIT_SECONDS:
                logger.warning(
                    f"[GHOST AUDIT] Reached {MAX_AUDIT_SECONDS}s limit. Skipping remaining {len(unlabeled) - results['processed']} signals."
                )
                break

            symbol = obs.get("symbol")
            if not symbol:
                continue

            try:
                sig_dt = self._observation_timestamp(obs, target_date)
                if sig_dt is None:
                    logger.warning("[GHOST AUDIT] Missing/invalid signal timestamp for %s", symbol)
                    continue

                # We need historical data to simulate the path
                # Fyers history API: resolution 1
                data = {
                    "symbol": symbol,
                    "resolution": "1",
                    "date_format": "1",
                    "range_from": target_date.strftime("%Y-%m-%d"),
                    "range_to": target_date.strftime("%Y-%m-%d"),
                    "cont_flag": "1",
                }

                # Fetch history with timeout
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(self.fyers.history, data=data), timeout=15.0
                    )
                except TimeoutError:
                    logger.warning(f"[GHOST AUDIT] History API timeout for {symbol}")
                    continue

                if (
                    not response
                    or response.get("s") != "ok"
                    or "candles" not in response
                    or not response["candles"]
                ):
                    continue

                cols = ["epoch", "open", "high", "low", "close", "volume"]
                df = pd.DataFrame(response["candles"], columns=cols)
                df["dt"] = pd.to_datetime(df["epoch"], unit="s", utc=True).dt.tz_convert(
                    "Asia/Kolkata"
                )

                # Use candles strictly after the signal timestamp. The signal
                # minute candle can contain price action from before the signal.
                relevant_candles = df[df["dt"] > sig_dt]
                if relevant_candles.empty:
                    continue

                # 2. Simulate Path — with the exit the signal was actually going
                # to use. A top-coil setup has no take-profit and only exists if
                # its trigger breaks, so grading it on the VWAP-target path counted
                # setups that never triggered as trades and exited real ones early.
                if str(obs.get("exit_profile") or "").upper() == "EOD_HOLD":
                    outcome_data = self._simulate_eod_hold(obs, relevant_candles, session=df)
                else:
                    outcome_data = self._simulate_path(obs, relevant_candles)

                # 3. Update ML Logger
                if outcome_data:
                    ml_logger.update_outcome(
                        obs_id=obs["obs_id"],
                        outcome=outcome_data["outcome"],
                        exit_price=outcome_data["exit_price"],
                        max_favorable=outcome_data["max_favorable"],
                        max_adverse=outcome_data["max_adverse"],
                        hold_time_mins=outcome_data["hold_time_mins"],
                        pnl_pct=outcome_data["pnl_pct"],
                        label_source="GHOST",
                        exit_reason=outcome_data["exit_reason"],
                    )
                    results["processed"] += 1
                    if outcome_data["outcome"] == "NOT_TRIGGERED":
                        results["not_triggered"] += 1
                    elif outcome_data["outcome"] == "WIN":
                        results["wins"] += 1
                        if outcome_data.get("exit_reason") == "TP_HIT":
                            results["tp_hits"] += 1
                        elif outcome_data.get("exit_reason") == "EOD_SQUAREOFF":
                            results["eod_wins"] += 1
                    elif outcome_data["outcome"] == "LOSS":
                        results["losses"] += 1

            except Exception as e:
                logger.warning(f"Failed to audit {symbol}: {e}")

            # Rate limit safety: 5 calls per second max
            await asyncio.sleep(0.2)

        logger.info(f"Ghost Audit Complete: {results}")
        return results

    def _observation_timestamp(self, obs, target_date: date):
        """Return a timezone-aware IST timestamp for an ML observation."""
        timestamp_ist = obs.get("timestamp_ist")
        if timestamp_ist and not pd.isna(timestamp_ist):
            ts = pd.Timestamp(timestamp_ist)
            ts = ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST)
            return ts.to_pydatetime()

        signal_time_str = obs.get("time")
        if not signal_time_str or pd.isna(signal_time_str):
            return None

        obs_date = obs.get("date") or target_date.isoformat()
        sig_dt = datetime.strptime(f"{obs_date} {signal_time_str}", "%Y-%m-%d %H:%M:%S")
        return sig_dt.replace(tzinfo=IST)

    # The validation gate's fixed expiry, refreshed on every re-arm.
    TOPCOIL_PENDING_MINUTES = 15

    def _simulate_eod_hold(self, obs, df, session=None):
        """
        Grade a top-coil (EOD_HOLD) setup the way the engine trades it.

        From the last re-arm: the trigger has 15 minutes to break, and a push
        through coil_high * 1.002 cancels it first. Once in, the only exits are
        the stop and the 15:10 square-off. A setup that never triggers is labelled
        NOT_TRIGGERED, not WIN or LOSS — it was never a trade.

        With TOPCOIL_RSI_TP_ENABLED and the full session passed as `session`, the
        operator's RSI take-profit applies too, exactly as the live loop runs it:
        on a completed bar at least TOPCOIL_RSI_TP_SKIP_MINUTES after the entry
        bar, in profit, 1-minute RSI below the threshold -> covered at that close.

        Within one 1-minute bar the order of events is unknown; a bar that touches
        both the trigger and the invalidation is counted as entered, because the
        engine tests the trigger first on each tick.
        """
        try:
            trig = float(obs.get("trigger_price"))
            coil_high = float(obs.get("coil_high"))
            sl_price = float(obs.get("sl_price"))
        except (TypeError, ValueError):
            return None
        if not (trig > 0 and coil_high > 0 and sl_price > trig):
            return None

        armed_at = obs.get("armed_at")
        if armed_at and not pd.isna(armed_at):
            ts = pd.Timestamp(armed_at)
            armed = ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST)
            df = df[df["dt"] > armed]
        else:
            armed = df.iloc[0]["dt"] if not df.empty else None
        if df.empty or armed is None:
            return None

        not_triggered = {
            "outcome": "NOT_TRIGGERED",
            "exit_price": 0.0,
            "max_favorable": 0.0,
            "max_adverse": 0.0,
            "pnl_pct": 0.0,
            "hold_time_mins": 0,
        }
        inval = coil_high * 1.002
        entry_pos = None
        for k, row in enumerate(df.itertuples(index=False)):
            if (row.dt - armed).total_seconds() > self.TOPCOIL_PENDING_MINUTES * 60:
                return {**not_triggered, "exit_reason": "EXPIRED"}
            if row.low <= trig:
                entry_pos = k
                break
            if row.high >= inval:
                return {**not_triggered, "exit_reason": "INVALIDATED"}
        if entry_pos is None:
            return {**not_triggered, "exit_reason": "EXPIRED"}

        held = df.iloc[entry_pos:]
        held = held[held["dt"].dt.time < EOD_SQUAREOFF_TIME]
        if held.empty:
            return None
        entry_time = held.iloc[0]["dt"]

        rsi_by_dt = {}
        if session is not None and getattr(config, "TOPCOIL_RSI_TP_ENABLED", False):
            sess = session.sort_values("dt")
            if len(sess) >= int(getattr(config, "TOPCOIL_RSI_TP_MIN_CANDLES", 30)):
                period = int(getattr(config, "TOPCOIL_RSI_TP_PERIOD", 14))
                closes = sess["close"].astype(float).tolist()
                for k, ts in enumerate(sess["dt"]):
                    if k + 1 >= int(getattr(config, "TOPCOIL_RSI_TP_MIN_CANDLES", 30)):
                        rsi_by_dt[ts] = compute_rsi_wilder(closes[: k + 1], period)
        rsi_thr = float(getattr(config, "TOPCOIL_RSI_TP_THRESHOLD", 40.0))
        rsi_skip = int(getattr(config, "TOPCOIL_RSI_TP_SKIP_MINUTES", 5))

        mfe = mae = 0.0
        exit_price, exit_reason, exit_time = None, None, None
        for bars_after, row in enumerate(held.itertuples(index=False)):
            mae = max(mae, (row.high - trig) / trig * 100)
            if row.high >= sl_price:
                exit_price, exit_reason, exit_time = sl_price, "SL_HIT", row.dt
                break
            mfe = max(mfe, (trig - row.low) / trig * 100)
            r = rsi_by_dt.get(row.dt)
            if (
                r is not None
                and r == r
                and bars_after >= rsi_skip
                and row.close < trig
                and r < rsi_thr
            ):
                exit_price, exit_reason, exit_time = float(row.close), "RSI_TP", row.dt
                break
        if exit_price is None:
            last = held.iloc[-1]
            exit_price, exit_reason, exit_time = float(last["close"]), "EOD_SQUAREOFF", last["dt"]

        pnl_pct = (trig - exit_price) / trig * 100
        return {
            "exit_reason": exit_reason,
            "outcome": "WIN" if pnl_pct > 0 else "LOSS",
            "exit_price": exit_price,
            "max_favorable": mfe,
            "max_adverse": max(0.0, mae),
            "pnl_pct": pnl_pct,
            "hold_time_mins": (exit_time - entry_time).total_seconds() / 60,
        }

    def _simulate_path(self, obs, df):
        """
        Core path simulation engine for ShortCircuit strategy.
        Checks for SL, TP1, TP2, TP3 hits in order.
        """
        try:
            entry_price = float(obs.get("ltp"))
            sl_price = float(obs.get("sl_price"))
            tp_price = float(obs.get("tp_price") or obs.get("tp1_price"))
        except (TypeError, ValueError):
            return None

        if not all([entry_price, sl_price, tp_price]):
            return None

        # Position State
        state = "ACTIVE"
        current_sl = sl_price
        max_favorable = 0.0
        max_adverse = 0.0
        start_time = df.iloc[0]["dt"]
        exit_time = None
        exit_price = None
        outcome = "LOSS"  # Default
        exit_reason = None

        direction = str(obs.get("direction") or "").upper()
        is_short = (
            direction == "SHORT" if direction in {"SHORT", "LONG"} else sl_price > entry_price
        )

        for _, row in df.iterrows():
            high = row["high"]
            low = row["low"]
            row["close"]

            if is_short:
                # SHORT: AE (Price going AGAINST = UP), FE (Price going WITH = DOWN)
                adv = max(0.0, ((high - entry_price) / entry_price) * 100)
                fav = max(0.0, ((entry_price - low) / entry_price) * 100)
            else:
                # LONG: AE (Price going AGAINST = DOWN), FE (Price going WITH = UP)
                adv = max(0.0, ((entry_price - low) / entry_price) * 100)
                fav = max(0.0, ((high - entry_price) / entry_price) * 100)

            max_adverse = max(max_adverse, adv)
            max_favorable = max(max_favorable, fav)

            # Check Stop Loss
            sl_hit = (high >= current_sl) if is_short else (low <= current_sl)
            if sl_hit:
                state = "CLOSED"
                exit_price = current_sl
                exit_time = row["dt"]
                exit_reason = "SL_HIT"
                if is_short:
                    outcome = (
                        "BREAKEVEN"
                        if abs(current_sl - entry_price) < 0.1
                        else ("LOSS" if current_sl > entry_price else "WIN")
                    )
                else:
                    outcome = (
                        "BREAKEVEN"
                        if abs(current_sl - entry_price) < 0.1
                        else ("LOSS" if current_sl < entry_price else "WIN")
                    )
                break

            # Check Take Profits
            if state == "ACTIVE":
                tp_hit = (low <= tp_price) if is_short else (high >= tp_price)
                if tp_hit and tp_price > 0:
                    exit_price = tp_price
                    exit_reason = "TP_HIT"
                    state = "CLOSED"
                    outcome = "WIN"
                    exit_time = row["dt"]
                    break

        # EOD Square-off if still active
        if state == "ACTIVE":
            exit_price = df.iloc[-1]["close"]
            exit_time = df.iloc[-1]["dt"]
            exit_reason = "EOD_SQUAREOFF"
            if is_short:
                outcome = "WIN" if exit_price < entry_price else "LOSS"
            else:
                outcome = "WIN" if exit_price > entry_price else "LOSS"

        hold_time = (exit_time - start_time).total_seconds() / 60
        if is_short:
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100
        else:
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        return {
            "exit_reason": exit_reason,
            "outcome": outcome,
            "exit_price": exit_price,
            "max_favorable": max_favorable,
            "max_adverse": max_adverse,
            "pnl_pct": pnl_pct,
            "hold_time_mins": hold_time,
        }

    async def _fetch_trades(self, session_date: str):
        """
        Fetch trades for a given session date.
        Prefers async fetch() when available, falls back to sync query().
        """
        if hasattr(self.db, "fetch") and asyncio.iscoroutinefunction(self.db.fetch):
            rows = await self.db.fetch(
                """
                SELECT
                    symbol,
                    entry_price,
                    COALESCE(current_price, entry_price) AS exit_price,
                    COALESCE(realized_pnl, 0) AS pnl,
                    CASE
                        WHEN entry_price > 0 AND qty > 0
                        THEN ROUND((COALESCE(realized_pnl, 0) / (entry_price * qty)) * 100, 2)
                        ELSE NULL
                    END AS pnl_pct,
                    state AS status
                FROM positions
                WHERE session_date = $1
                """,
                session_date,
            )
            return [dict(r) for r in rows]

        rows = self.db.query(
            """
            SELECT
                symbol,
                entry_price,
                COALESCE(current_price, entry_price) AS exit_price,
                COALESCE(realized_pnl, 0) AS pnl,
                CASE
                    WHEN entry_price > 0 AND qty > 0
                    THEN ROUND((COALESCE(realized_pnl, 0) / (entry_price * qty)) * 100, 2)
                    ELSE NULL
                END AS pnl_pct,
                state AS status
            FROM positions
            WHERE session_date = %s
            """,
            (session_date,),
        )
        return rows or []

    def perform_safety_audit(self, trades):
        issues = []
        orphans = 0

        for trade in trades:
            if trade.get("status") == "OPEN":
                orphans += 1
                issues.append(f"ORPHAN: {trade.get('symbol', 'UNKNOWN')} still OPEN at EOD.")

            entry_price = trade.get("entry_price")
            if not entry_price or entry_price <= 0:
                issues.append(f"DATA: {trade.get('symbol', 'UNKNOWN')} has invalid Entry Price.")

            pnl_pct = trade.get("pnl_pct")
            if pnl_pct is None and trade.get("status") == "CLOSED":
                issues.append(
                    f"DATA: {trade.get('symbol', 'UNKNOWN')} CLOSED but missing PnL percent."
                )
            elif pnl_pct is not None and abs(pnl_pct) > 50:
                issues.append(f"ANOMALY: {trade.get('symbol', 'UNKNOWN')} pnl_pct={pnl_pct}.")

        return {
            "status": "PASSED" if not issues else "WARNING",
            "issues": issues,
            "orphans": orphans,
            "processed": len(trades),
        }

    async def analyze_soft_stops(self, session_date: str):
        """
        Soft-stop table is optional in current schema.
        Return zeroed stats if unavailable.
        """
        results = {
            "total_decisions": 0,
            "correct_decisions": 0,
            "incorrect_decisions": 0,
            "saved_loss": 0.0,
            "missed_profit": 0.0,
            "details": [],
        }

        try:
            if hasattr(self.db, "fetch") and asyncio.iscoroutinefunction(self.db.fetch):
                rows = await self.db.fetch(
                    "SELECT * FROM soft_stop_events WHERE DATE(timestamp) = $1",
                    session_date,
                )
                results["total_decisions"] = len(rows)
                return results

            rows = self.db.query(
                "SELECT * FROM soft_stop_events WHERE DATE(timestamp) = %s",
                (session_date,),
            )
            results["total_decisions"] = len(rows or [])
            return results
        except Exception:
            return results

    def calculate_performance(self, trades):
        total_pnl = 0.0
        winners = 0
        losers = 0

        for trade in trades:
            pnl = float(trade.get("pnl", 0) or 0)
            total_pnl += pnl
            if pnl > 0:
                winners += 1
            elif pnl < 0:
                losers += 1

        total_trades = len(trades)
        win_rate = (winners / total_trades * 100) if total_trades else 0.0
        return {
            "total_pnl": total_pnl,
            "winners": winners,
            "losers": losers,
            "win_rate": round(win_rate, 1),
            "total_trades": total_trades,
        }

    def generate_report(self, date, stats, audit, soft_stop_stats, ghost_stats=None):
        pnl_emoji = "🟢" if stats["total_pnl"] > 0 else "🔴"
        audit_icon = "✅" if audit["status"] == "PASSED" else "⚠️"

        lines = [
            f"# 📊 EOD Report: {date}",
            "",
            "## 💰 Performance",
            f"- **Net P&L**: {pnl_emoji} ₹{stats['total_pnl']:.2f}",
            f"- Win Rate: {stats['win_rate']}% ({stats['winners']}W / {stats['losers']}L)",
            f"- Total Trades: {stats['total_trades']}",
            "",
        ]

        if ghost_stats and ghost_stats.get("processed", 0) > 0:
            # A setup whose trigger never broke was never a trade, so it is counted
            # apart and kept out of the win rate.
            _traded = ghost_stats["wins"] + ghost_stats["losses"]
            lines.extend(
                [
                    "## 👻 Ghost Signal Audit (Missed Trades)",
                    f"- **Processed**: {ghost_stats['processed']}",
                    f"- **Trigger never broke**: {ghost_stats.get('not_triggered', 0)}",
                    f"- **TP Hits**: {ghost_stats.get('tp_hits', 0)} 🎯",
                    f"- **EOD Profit Closures**: {ghost_stats.get('eod_wins', 0)} ⏰",
                    f"- **Losses**: {ghost_stats['losses']}",
                    f"- **Win Rate**: {round(ghost_stats['wins'] / _traded * 100, 1) if _traded else 0}%",
                    "> Setups the analyzer passed that the bot did not trade "
                    "(cooldown, capital slot busy, or it would have triggered while another "
                    "position was open), graded with the exit each one would have used.",
                    "",
                ]
            )

        lines.extend(
            [
                f"## 🛡️ Safety Audit {audit_icon}",
                f"- Status: {audit['status']}",
                f"- Orphaned Trades: {audit['orphans']}",
            ]
        )

        if audit["issues"]:
            lines.append("### Issues")
            for issue in audit["issues"]:
                lines.append(f"- {issue}")
        else:
            lines.append("- System Integrity: 100%")

        lines.extend(
            [
                "",
                "## Discretionary Analysis",
                f"- Decisions Made: {soft_stop_stats['total_decisions']}",
            ]
        )

        report_text = "\n".join(lines)
        file_path = os.path.join(REPORT_DIR, f"eod_report_{date}.md")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_text)
            logger.info("Report saved to %s", file_path)
        except Exception as exc:
            logger.error("Failed to save report: %s", exc)

        return report_text

    async def _save_summary_db(self, date, stats, audit):
        summary_data = {
            "date": date,
            "phase": "SingleStrategy",
            "total_trades": stats["total_trades"],
            "winners": stats["winners"],
            "losers": stats["losers"],
            "win_rate": stats["win_rate"],
            "total_pnl": stats["total_pnl"],
            "safety_status": audit["status"],
        }
        if not hasattr(self.db, "log_event"):
            return

        try:
            maybe_awaitable = self.db.log_event("daily_summaries", summary_data)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        except Exception:
            pass


if __name__ == "__main__":
    db = DatabaseManager()
    analyzer = EODAnalyzer(db_manager=db)
    report = asyncio.run(analyzer.run_daily_analysis())
    print(report)
