import datetime
import logging
import os
import threading
import time
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
import brain
import config
import connector
import database
import eqats_planes
import indicators
import predictive_brain
import telegram_bot
from event_bus import Event, global_event_bus
from supervisor_agent import global_supervisor_agent

_log = logging.getLogger(__name__)


class AutonomousScalper:
    """
    The main coordinator class for the Autonomous Forex Scalper.
    It orchestrates initialization, main loops, technical scans, execution,
    trade monitoring, and risk/drawdown safeguards under the EQATS 3.0 unified control flow.
    """

    def __init__(self) -> None:
        database.init_db()
        if config.SIMULATION_MODE:
            print("--- RUNNING IN SIMULATION MODE (PAPER TRADING) ---")
            self.conn = connector.SimulatorConnector(initial_balance=10000.0)
        else:
            print("--- RUNNING IN LIVE MT5 WINDOWS MODE ---")
            self.conn = connector.MT5Connector(demo_only=config.DEMO_ACCOUNT_ONLY)
        self.engine = eqats_planes.init_core_engine(self.conn)
        self.brain = brain.ScalperBrain()
        self.running = False
        self.trade_lock = threading.Lock()
        import institutional_integrations as ii

        self.quantum_auto_engine = ii.QuantumAutoEngine()
        self.self_healer = ii.QuantumSelfHealer()
        self.self_healer.start_non_stop_loop()
        from institutional_integrations.web_api import SocketIPCBridge

        self.ipc_bridge = SocketIPCBridge(host="127.0.0.1", port=9001)
        self.ipc_bridge.start_server()
        self.supervisor = global_supervisor_agent
        from brain_agents_orchestrator import global_brain_orchestrator

        self.brain_orchestrator = global_brain_orchestrator
        self.daily_start_balance = 0.0
        self.last_day_str = ""
        global_event_bus.subscribe("SafetyInvariantViolation", self._handle_safety_violation)
        global_event_bus.subscribe("TradeAdmissionApproved", self._handle_trade_approved)
        global_event_bus.subscribe("TradeAdmissionRejected", self._handle_trade_rejected)

    def _handle_safety_violation(self, event: Event) -> None:
        print(f"🛑 [SAFETY INVARIANT VIOLATION EVENT]: {event.payload}")

    def _handle_trade_approved(self, event: Event) -> None:
        print(f"✅ [TRADE ADMISSION APPROVED EVENT]: {event.payload}")

    def _handle_trade_rejected(self, event: Event) -> None:
        print(f"❌ [TRADE ADMISSION REJECTED EVENT]: {event.payload}")

    def start(self) -> Any:
        """Connects and starts the main loop."""
        try:
            self.conn.connect()
        except Exception as e:
            print(f"CRITICAL ERROR: Failed to connect to terminal: {e}")
            return False
        account_info = self.conn.get_account_info()
        self.daily_start_balance = account_info["balance"]
        self.last_day_str = datetime.date.today().isoformat()
        persisted_state = database.load_circuit_breaker_state()
        current_date = datetime.date.today().isoformat()
        if persisted_state and persisted_state["trading_date"] == current_date:
            self.daily_start_balance = persisted_state["daily_start_balance"]
            self.last_day_str = persisted_state["trading_date"]
            if persisted_state["is_halted"]:
                self.engine.resilience.transition_state("HALTED")
                halt_msg = f"⚠️ *CIRCUIT BREAKER STATE RECOVERED FROM DATABASE*\\nTrading was halted earlier today at {persisted_state['halt_timestamp']}.\\nReason: {persisted_state['halt_reason']}\\nDaily baseline: {self.daily_start_balance:.2f}\\nCurrent balance: {account_info['balance']:.2f}\\nTrading remains HALTED until manual operator override or next trading day."
                print(halt_msg.replace("*", ""))
                telegram_bot.send_telegram_message(halt_msg)
            else:
                recovery_msg = f"📊 *Daily baseline recovered from database*\\nDate: {current_date}\\nBaseline: {self.daily_start_balance:.2f}\\nCurrent: {account_info['balance']:.2f}"
                print(recovery_msg.replace("*", ""))
        else:
            self.daily_start_balance = account_info["balance"]
            self.last_day_str = current_date
            database.save_circuit_breaker_state(
                trading_date=current_date, daily_start_balance=self.daily_start_balance, is_halted=False,
            )
            new_day_msg = f"🌅 New trading day baseline established: {self.daily_start_balance:.2f}"
            print(new_day_msg)
        start_msg = f"🚀 *Elite Quantum Autonomous Trading System Started!*\nMode: {('Simulation' if config.SIMULATION_MODE else 'MT5 Terminal')}\nBalance: {account_info['balance']:.2f} {account_info['currency']}\nDaily Baseline: {self.daily_start_balance:.2f}\\nRisk Per Trade: {config.RISK_PER_TRADE_PERCENT}%\nMax Drawdown Limit: {config.MAX_DAILY_DRAWDOWN_PERCENT}%"
        print(start_msg.replace("*", ""))
        telegram_bot.send_telegram_message(start_msg)
        global_event_bus.publish(
            Event(family="SystemFault", source="Main", payload={"message": "System starting up cleanly"}),
        )
        self.running = True
        return True

    def stop(self) -> None:
        self.running = False
        try:
            self.self_healer.stop_loop()
        except Exception:
            pass
        try:
            self.ipc_bridge.stop_server()
        except Exception:
            pass
        self.conn.disconnect()
        stop_msg = "🛑 *Elite Quantum Autonomous Trading System Stopped Safely.*"
        print(stop_msg.replace("*", ""))
        telegram_bot.send_telegram_message(stop_msg)

    def _process_trailing_stops(self, active_positions: Any) -> None:
        """
        Autonomously manages trailing stop loss levels of active open trades
        to secure running profits dynamically.
        """
        if not config.TRAILING_STOP_ENABLED:
            return
        for pos in active_positions:
            symbol = pos["symbol"]
            ticket = pos["ticket"]
            direction = pos["direction"]
            current_sl = pos["sl"]
            current_tp = pos["tp"]
            history = self.conn.get_history(symbol, 30)
            if not history:
                continue
            closes = [bar["close"] for bar in history]
            highs = [bar["high"] for bar in history]
            lows = [bar["low"] for bar in history]
            atr_val = indicators.calculate_atr(highs, lows, closes, config.ATR_PERIOD)
            if atr_val is None or atr_val <= 0:
                continue
            trail_dist = atr_val * config.TRAILING_STOP_ATR_MULT
            price_info = self.conn.get_current_price(symbol)
            bid = price_info["bid"]
            ask = price_info["ask"]
            entry_price = pos.get("open_price", 0.0)
            if entry_price <= 0:
                continue
            risk_dist = abs(entry_price - current_sl)
            spread_buffer = max(1e-05, ask - bid)
            trigger_distance = min(atr_val, risk_dist) if risk_dist > 0 else atr_val
            if direction == "BUY":
                be_sl = entry_price + spread_buffer
                if bid >= entry_price + trigger_distance and current_sl < be_sl:
                    success = self.conn.modify_order(ticket, round(be_sl, 5), current_tp)
                    if success:
                        print(
                            f"🔒 AUTONOMOUS BREAKEVEN LOCK: Moved SL to entry + spread buffer ({be_sl:.5f}) on BUY {symbol} (Ticket {ticket}) at +1.0x ATR!",
                        )
                        current_sl = be_sl
                target_sl = bid - trail_dist
                if target_sl > current_sl + 5e-05:
                    success = self.conn.modify_order(ticket, round(target_sl, 5), current_tp)
                    if success:
                        print(
                            f"🎯 AUTONOMOUS TRAILING STOP: Moved SL on BUY {symbol} (Ticket {ticket}) up to {target_sl:.5f} (Locked profits!)",
                        )
                        current_sl = target_sl
            elif direction == "SELL":
                be_sl = entry_price - spread_buffer
                if ask <= entry_price - trigger_distance and (current_sl == 0 or current_sl > be_sl):
                    success = self.conn.modify_order(ticket, round(be_sl, 5), current_tp)
                    if success:
                        print(
                            f"🔒 AUTONOMOUS BREAKEVEN LOCK: Moved SL to entry - spread buffer ({be_sl:.5f}) on SELL {symbol} (Ticket {ticket}) at +1.0x ATR!",
                        )
                        current_sl = be_sl
                target_sl = ask + trail_dist
                if current_sl == 0 or target_sl < current_sl - 5e-05:
                    success = self.conn.modify_order(ticket, round(target_sl, 5), current_tp)
                    if success:
                        print(
                            f"🎯 AUTONOMOUS TRAILING STOP: Moved SL on SELL {symbol} (Ticket {ticket}) down to {target_sl:.5f} (Locked profits!)",
                        )
                        current_sl = target_sl

    def _is_market_open_and_liquid(self, symbol: Any, price_info: Any) -> Any:
        """
        Autonomously assesses market conditions to protect capital from
        wide spreads or dangerous rollover/weekend gaps.
        Returns: (bool, str) - (is_safe, description_reason)
        """
        now_gmt = datetime.datetime.now(datetime.UTC)
        weekday = now_gmt.weekday()
        hour = now_gmt.hour
        symbol_upper = symbol.upper()
        is_crypto_asset = any(c in symbol_upper for c in ["BTC", "ETH", "LTC", "SOL", "XRP"])
        if (
            config.BLOCK_WEEKENDS
            and (not is_crypto_asset)
            and ((weekday == 4 and hour >= 21) or weekday == 5 or (weekday == 6 and hour < 21))
        ):
            return (False, "Hazardous session: Weekend market shutdown.")
        if config.BLOCK_ROLLOVER_HOUR and hour == 22:
            return (False, "Hazardous session: Daily broker rollover hour.")
        bid = price_info["bid"]
        ask = price_info["ask"]
        spread = ask - bid
        if spread < 0:
            return (False, "Negative spread / bad price data.")
        data_status = self.engine.data.validate_reasonableness(symbol, bid, ask)
        if data_status in ["INVALID", "QUARANTINED"]:
            return (False, f"Data Plane Filter: Market state is {data_status}.")
        symbol_upper = symbol.upper()
        pip_size = 0.0001
        if "JPY" in symbol_upper:
            pip_size = 0.01
        elif "XAU" in symbol_upper:
            pip_size = 0.1
        elif "XAG" in symbol_upper:
            pip_size = 0.01
        elif any(c in symbol_upper for c in ["BTC", "ETH", "LTC", "SOL", "XRP"]):
            pip_size = 1.0
        spread_pips = spread / pip_size
        if not hasattr(self, "_symbol_avg_spreads"):
            self._symbol_avg_spreads = {}
        sym_upper = symbol.upper()
        if sym_upper not in self._symbol_avg_spreads:
            self._symbol_avg_spreads[sym_upper] = [spread_pips]
        else:
            self._symbol_avg_spreads[sym_upper].append(spread_pips)
            if len(self._symbol_avg_spreads[sym_upper]) > 20:
                self._symbol_avg_spreads[sym_upper].pop(0)
        avg_spread = sum(self._symbol_avg_spreads[sym_upper]) / len(self._symbol_avg_spreads[sym_upper])
        if len(self._symbol_avg_spreads[sym_upper]) >= 5 and spread_pips > 2.5 * avg_spread and (spread_pips > 3.0):
            return (
                False,
                f"Liquidity Filter (Spread Volatility Spike Breaker): Spread ({spread_pips:.1f} pips) exceeds 2.5x 20-period avg spread ({avg_spread:.1f} pips).",
            )
        if spread_pips > config.MAX_SPREAD_PIPS:
            return (
                False,
                f"Liquidity Filter: Spread is too wide ({spread_pips:.1f} pips > {config.MAX_SPREAD_PIPS:.1f} limit).",
            )
        return (True, "Safe conditions")

    def _get_current_session(self) -> Any:
        """Autonomously determines the active global trading session based on GMT hour and weekend status."""
        now_gmt = datetime.datetime.now(datetime.UTC)
        weekday = now_gmt.weekday()
        hour = now_gmt.hour
        is_weekend = (weekday == 4 and hour >= 21) or weekday == 5 or (weekday == 6 and hour < 21)
        if is_weekend:
            return "Crypto Weekend Session (24/7)"
        tokyo = 0 <= hour < 9
        london = 8 <= hour < 17
        ny = 12 <= hour < 21
        sessions = []
        if tokyo:
            sessions.append("Tokyo")
        if london:
            sessions.append("London")
        if ny:
            sessions.append("New York")
        if not sessions:
            return "Global 24-Hour Interbank Session"
        return " + ".join(sessions) + " Overlap" if len(sessions) > 1 else sessions[0] + " Session"

    def _get_sessions_timeline(self) -> Any:
        """
        Comprehensive 24-Session Market Timeline Tracker.
        Calculates 3 rows of data: Active, Previous, and Coming sessions with precise countdown timers.
        """
        now_gmt = datetime.datetime.now(datetime.UTC)
        weekday = now_gmt.weekday()
        hour = now_gmt.hour
        minute = now_gmt.minute
        second = now_gmt.second
        self.sessions_def = {
            "Wellington FX": (20, 5, "Forex"),
            "Sydney FX": (22, 7, "Forex"),
            "Tokyo FX": (23, 8, "Forex"),
            "Hong Kong FX": (1, 10, "Forex"),
            "Singapore FX": (1, 10, "Forex"),
            "Frankfurt FX": (6, 15, "Forex"),
            "London FX": (7, 16, "Forex"),
            "Zurich FX": (7, 15, "Forex"),
            "New York FX": (12, 21, "Forex"),
            "Sydney ASX": (0, 6, "Equity"),
            "Tokyo TSE": (0, 6, "Equity"),
            "Hong Kong HKEX": (1, 8, "Equity"),
            "Shanghai SSE": (1, 7, "Equity"),
            "Dubai DFM": (6, 11, "Equity"),
            "Saudi Tadawul": (7, 12, "Equity"),
            "Frankfurt Xetra": (7, 15, "Equity"),
            "London LSE": (7, 15, "Equity"),
            "Euronext Paris": (7, 15, "Equity"),
            "Johannesburg JSE": (7, 15, "Equity"),
            "São Paulo B3": (13, 20, "Equity"),
            "Mexican BMV": (13, 20, "Equity"),
            "US NYSE/NASDAQ": (13, 20, "Equity"),
            "US Pre-Market": (8, 13, "Extended"),
            "US After-Hours": (20, 0, "Extended"),
            "CME Futures": (22, 21, "Futures"),
            "ICE Brent": (23, 22, "Futures"),
            "Crypto Markets": (0, 24, "Digital"),
        }
        active = []
        previous = []
        coming = []
        is_weekend = (weekday == 4 and hour >= 21) or weekday == 5 or (weekday == 6 and hour < 21)
        for name, (start, end, cat) in self.sessions_def.items():
            if cat != "Digital" and is_weekend:
                continue
            is_active = False
            if start < end:
                if start <= hour < end:
                    is_active = True
            elif hour >= start or hour < end:
                is_active = True
            if is_active:
                active.append(name)
            else:
                is_prev = False
                prev_close = end
                dist_closed = (hour - prev_close) % 24
                if dist_closed <= 4:
                    is_prev = True
                if is_prev:
                    previous.append(name)
                else:
                    dist_to_start = (start - hour) % 24
                    coming.append((name, dist_to_start, start))
        coming = sorted(coming, key=lambda x: x[1])
        coming_str_list = []
        for name, dist, start_h in coming[:5]:
            seconds_to_start = dist * 3600 - minute * 60 - second
            if seconds_to_start < 0:
                seconds_to_start += 24 * 3600
            h_cd = seconds_to_start // 3600
            m_cd = seconds_to_start % 3600 // 60
            s_cd = seconds_to_start % 60
            cd_timer = f"{h_cd:02d}:{m_cd:02d}:{s_cd:02d}"
            coming_str_list.append(f"{name} ({cd_timer})")
        overlapping_str = " | ".join(active) if len(active) > 1 else "None (Single Session)"
        return {
            "active": " | ".join(active) if active else "No active sessions",
            "overlapping": overlapping_str,
            "next_session": " | ".join(coming_str_list[:3]) if coming_str_list else "None",
            "previous": " | ".join(previous) if previous else "None",
            "countdown": "Active Tracker",
        }

    def _get_session_symbols(self, active_session: Any) -> Any:
        """
        Dynamically filters config.SYMBOLS to trade only the symbols active during
        the current global trading session.
        - Weekends: Only Cryptos.
        - Weekdays: All Forex and metals are always tradeable (24-hour interbank liquidity),
                    and Cryptos are always tradeable.
        """
        all_symbols = config.SYMBOLS
        active_session_upper = active_session.upper()
        if "WEEKEND" in active_session_upper:
            return [s for s in all_symbols if any(c in s.upper() for c in ["BTC", "ETH", "LTC", "SOL", "XRP"])]
        return all_symbols

    def evaluate_symbol_worker(
        self, symbol: Any, active_positions: Any, current_equity: Any, trading_available: Any,
    ) -> Any:
        """
        Parallel worker to perform indicator calculation, research scraping,
        regime selection, and strategy evaluations for a single symbol.
        """
        history = self.conn.get_history(symbol, 220)
        if not history:
            return {
                "symbol": symbol,
                "price": "-",
                "ema200": "-",
                "trend": "-",
                "rsi": "-",
                "atr": "-",
                "status": "Syncing history...",
                "decision": "HOLD",
                "analysis": None,
                "nn_state": None,
            }
        current_price = history[-1]["close"]
        self.engine.data.store_price(symbol, current_price - 0.0001, current_price + 0.0001)
        try:
            closes_hist = [b["close"] for b in history]
            highs_hist = [b["high"] for b in history]
            lows_hist = [b["low"] for b in history]
            opt_style, opt_strat = self.quantum_auto_engine.determine_optimal_style_and_strategy(
                symbol, closes_hist, highs_hist, lows_hist,
            )
        except Exception:
            pass
        price_info = self.conn.get_current_price(symbol)
        is_safe, safety_reason = self._is_market_open_and_liquid(symbol, price_info)
        analysis = self.brain.evaluate(symbol, history, current_equity)
        decision = analysis["decision"]
        indicators_info = analysis.get("indicators", {})
        ema200 = indicators_info.get("ema_long", 0.0)
        rsi_val = indicators_info.get("rsi", 0.0)
        atr_val = indicators_info.get("atr", 0.0)
        trend_str = "UP" if current_price > ema200 else "DOWN"
        status_text = analysis["explanation"]
        if not is_safe:
            decision = "HOLD"
            status_text = f"HOLD ({safety_reason})"
        elif not trading_available:
            status_text = "HOLD (MAX LIMIT OF ACTIVE TRADES REACHED)"
        elif decision in ["BUY", "SELL"]:
            status_text = f"Executing {decision}!"
        predictor_tmp = predictive_brain.get_symbol_predictor(symbol)
        nn_state = predictor_tmp.get_internal_state()
        return {
            "symbol": symbol,
            "price": f"{current_price:.5f}",
            "ema200": f"{ema200:.5f}",
            "trend": trend_str,
            "rsi": f"{rsi_val:.1f}",
            "atr": f"{atr_val:.5f}",
            "status": status_text,
            "decision": decision,
            "analysis": analysis,
            "nn_state": nn_state,
        }

    def tick_and_execute(self) -> None:
        """
        Runs one iteration of checking market state, assessing trades,
        updating open positions, and enforcing limits under EQATS 3.0 logic.
        """
        try:
            self.brain_orchestrator.run_agentic_loop(self, symbol=config.SYMBOLS[0])
        except Exception as e:
            print(f"Warning: Brain orchestrator loop exception: {e}")
        try:
            self.supervisor.run_supervisory_audit(self)
        except Exception as e:
            print(f"Warning: Supervisor agent audit exception: {e}")
        if not self.conn.is_connected():
            print("⚠️ DISCONNECTION DETECTED: Heartbeat failed. Autonomously attempting to reconnect...")
            try:
                self.conn.connect()
            except Exception as e:
                print(f"Warning: Reconnection attempt failed: {e}")
                return
        self.engine.resilience.log_heartbeat(0.12)
        if self.engine.resilience.get_state() == "HALTED":
            print("⚠️ Trading is HALTED due to circuit breaker. Skipping tick cycle.")
            return
        current_date = datetime.date.today().isoformat()
        if current_date != self.last_day_str:
            account_info = self.conn.get_account_info()
            self.daily_start_balance = account_info["balance"]
            self.last_day_str = current_date
            database.save_circuit_breaker_state(
                trading_date=current_date, daily_start_balance=self.daily_start_balance, is_halted=False,
            )
            print(f"New day detected: {current_date}. Resetting daily baseline to {self.daily_start_balance:.2f}")
        if config.SIMULATION_MODE:
            closed_tickets = self.conn.tick()
            for ticket in closed_tickets:
                pass
        account_tmp = self.conn.get_account_info()
        current_equity = account_tmp["equity"]
        daily_floating_loss = current_equity - self.daily_start_balance
        max_allowed_loss = self.daily_start_balance * (config.MAX_DAILY_DRAWDOWN_PERCENT / 100.0)
        if daily_floating_loss < 0 and abs(daily_floating_loss) >= max_allowed_loss:
            warn_msg = f"⚠️ *CRITICAL DRAWDOWN CIRCUIT BREAKER TRIGGERED!*\nDaily drawdown of {abs(daily_floating_loss):.2f} USD reached ({config.MAX_DAILY_DRAWDOWN_PERCENT}% of starting {self.daily_start_balance:.2f} USD).\nAutonomously liquidating all open positions and stopping trading for the day..."
            print(warn_msg.replace("*", ""))
            telegram_bot.send_telegram_message(warn_msg)
            self.engine.resilience.transition_state("HALTED")
            halt_reason = f"Daily drawdown limit reached: {abs(daily_floating_loss):.2f} USD ({config.MAX_DAILY_DRAWDOWN_PERCENT}%)"
            database.save_circuit_breaker_state(
                trading_date=current_date,
                daily_start_balance=self.daily_start_balance,
                is_halted=True,
                halt_reason=halt_reason,
            )
            active_positions = self.conn.get_open_orders()
            for pos in active_positions:
                self.conn.close_order(pos["ticket"], reason="DAILY_DRAWDOWN_CIRCUIT_BREAKER")
            return
        active_positions = self.conn.get_open_orders()
        open_db_trades = database.get_open_trades()
        self._process_trailing_stops(active_positions)
        account_tmp = self.conn.get_account_info()
        database.update_performance_metrics(current_date, account_tmp["balance"])
        active_tickets = {str(p["ticket"]) for p in active_positions}
        for db_trade in open_db_trades:
            ticket_str = str(db_trade["ticket"])
            if ticket_str not in active_tickets:
                current_price = self.conn.get_current_price(db_trade["symbol"])["bid"]
                p_diff = current_price - db_trade["open_price"]
                if db_trade["direction"] == "SELL":
                    p_diff = -p_diff
                is_crypto = "BTC" in db_trade["symbol"] or "ETH" in db_trade["symbol"]
                is_gold = "XAU" in db_trade["symbol"]
                mult = 1.0 if is_crypto else 100.0 if is_gold else 100000.0
                estimated_profit = p_diff * db_trade["lot_size"] * mult
                database.log_trade_close(ticket_str, current_price, estimated_profit, "EXTERNAL_MT5_CLOSE")
                print(
                    f"Trade {ticket_str} ({db_trade['symbol']}) detected as CLOSED on MT5. Synchronized local database.",
                )
        account = self.conn.get_account_info()
        current_equity = account["equity"]
        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        active_session = self._get_current_session()
        active_symbols = self._get_session_symbols(active_session)
        print(f"\n⚡ [{timestamp_str}] --- COGNITIVE SCAN CYCLE ---")
        print(
            f"Equity: {current_equity:.2f} USD | Active Trades: {len(active_positions)}/{config.MAX_CONCURRENT_TRADES} | Active Session: {active_session}",
        )
        print(f"{'Symbol':<9} | {'Price':<10} | {'EMA-200':<10} | {'Trend':<5} | {'RSI':<6} | {'ATR':<8} | {'Status'}")
        print("-" * 120)
        trading_available = len(active_positions) < config.MAX_CONCURRENT_TRADES
        scans_list = []
        pending_orders = []
        import concurrent.futures
        import multiprocessing as mp

        from institutional_integrations.system_autotune import global_tuned_config

        max_autotuned = global_tuned_config.get("process_pool_workers", os.cpu_count() or 8)
        pool_workers = max(1, min(max_autotuned, len(active_symbols)))
        parallel_success = False
        if mp.current_process().name == "MainProcess":
            try:
                ctx = mp.get_context("spawn")
                with concurrent.futures.ProcessPoolExecutor(max_workers=pool_workers, mp_context=ctx) as executor:
                    future_to_symbol = {
                        executor.submit(
                            self.evaluate_symbol_worker,
                            symbol,
                            list(active_positions),
                            current_equity,
                            trading_available,
                        ): symbol
                        for symbol in active_symbols
                    }
                    for future in concurrent.futures.as_completed(future_to_symbol):
                        symbol = future_to_symbol[future]
                        res = future.result()
                        scans_list.append(res)
                        if res["decision"] in ["BUY", "SELL"] and res["analysis"]:
                            pending_orders.append((res["symbol"], res["decision"], res["analysis"]))
                    parallel_success = True
            except Exception:
                pass
        if not parallel_success:
            scans_list = []
            pending_orders = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(active_symbols))) as executor:
                future_to_symbol = {
                    executor.submit(
                        self.evaluate_symbol_worker, symbol, list(active_positions), current_equity, trading_available,
                    ): symbol
                    for symbol in active_symbols
                }
                for future in concurrent.futures.as_completed(future_to_symbol):
                    symbol = future_to_symbol[future]
                    try:
                        res = future.result()
                        scans_list.append(res)
                        if res["decision"] in ["BUY", "SELL"] and res["analysis"]:
                            pending_orders.append((res["symbol"], res["decision"], res["analysis"]))
                    except Exception as e:
                        print(f"Error evaluating symbol {symbol} in parallel thread: {e}")
        scans_list = sorted(scans_list, key=lambda x: x["symbol"])
        for s in scans_list:
            print(
                f"{s['symbol']:<9} | {s['price']:<10} | {s['ema200']:<10} | {s['trend']:<5} | {s['rsi']:<6} | {s['atr']:<8} | {s['status']}",
            )
        raw_pending_decisions = []
        for s in scans_list:
            if s.get("analysis") and s["analysis"].get("decisions"):
                for dec_item in s["analysis"]["decisions"]:
                    raw_pending_decisions.append(dec_item)
            elif s.get("decision") in ["BUY", "SELL"] and s.get("analysis"):
                raw_pending_decisions.append(
                    {
                        "symbol": s["symbol"],
                        "decision": s["decision"],
                        "lot_size": s["analysis"].get("lot_size", 0.01),
                        "sl": s["analysis"].get("sl", 0.0),
                        "tp": s["analysis"].get("tp", 0.0),
                        "explanation": s["analysis"].get("explanation", ""),
                        "strategy": getattr(config, "ACTIVE_STRATEGY", ""),
                        "method": getattr(config, "TRADING_STYLE", ""),
                        "probability": s["analysis"].get("probability", 0.85),
                    },
                )
        dedup_dict = {}
        for dec_item in raw_pending_decisions:
            key = (dec_item["symbol"].upper(), dec_item["decision"])
            if key not in dedup_dict or dec_item.get("probability", 0.0) > dedup_dict[key].get("probability", 0.0):
                dedup_dict[key] = dec_item
        all_pending_decisions = list(dedup_dict.values())
        for dec_item in all_pending_decisions:
            if not trading_available:
                break
            symbol = dec_item["symbol"]
            decision = dec_item["decision"]
            lot_size = dec_item["lot_size"]
            sl = dec_item["sl"]
            tp = dec_item["tp"]
            explanation = dec_item["explanation"]
            strat_tag = dec_item.get("strategy", "")
            method_tag = dec_item.get("method", "")
            with self.trade_lock:
                active_positions_refresh = self.conn.get_open_orders()
                if len(active_positions_refresh) >= config.MAX_CONCURRENT_TRADES:
                    break
                if any(

                        p["symbol"].upper() == symbol.upper() and p.get("direction") == decision
                        for p in active_positions_refresh

                ):
                    continue
                if getattr(config, "ENABLE_SYMBOL_FLOATING_LOSS_GATE", True):
                    in_loss = False
                    for p in active_positions_refresh:
                        if p["symbol"].upper() == symbol.upper():
                            p_profit = p.get("profit")
                            if p_profit is not None:
                                is_losing = float(p_profit) < 0
                            else:
                                p_open = float(p.get("open_price", 0.0))
                                p_dir = p.get("direction", "BUY")
                                price_curr = self.conn.get_current_price(symbol)["bid"]
                                diff = price_curr - p_open if p_dir == "BUY" else p_open - price_curr
                                is_losing = diff < 0
                            if is_losing:
                                in_loss = True
                                break
                    if in_loss:
                        continue
                scan_item = next((sc for sc in scans_list if sc["symbol"].upper() == symbol.upper()), None)
                tech_trend = scan_item["trend"] if scan_item else "UP"
                ai_trend = "UP" if dec_item.get("probability", 0.85) >= 0.5 else "DOWN"
                component_decisions = {"technical_trend": tech_trend, "ai_trend": ai_trend}
                has_disagreement = not self.engine.safety.verify_component_agreement(component_decisions)
                open_db_trades_refresh = database.get_open_trades()
                has_reconciliation_mismatch = not self.engine.resilience.reconcile_positions(
                    open_db_trades_refresh, active_positions_refresh,
                )
                constraints = self.conn.get_symbol_volume_constraints(symbol)
                vol_min = constraints["volume_min"]
                vol_max = constraints["volume_max"]
                vol_step = constraints["volume_step"]
                normalized_lot_size = max(vol_min, min(vol_max, float(lot_size)))
                if vol_step > 0:
                    steps = round((normalized_lot_size - vol_min) / vol_step)
                    calc_lots = vol_min + steps * vol_step
                    step_str = f"{vol_step:.8f}".rstrip("0")
                    precision = len(step_str.split(".")[1]) if "." in step_str else 0
                    normalized_lot_size = round(calc_lots, precision)
                    normalized_lot_size = max(vol_min, min(vol_max, normalized_lot_size))
                if abs(normalized_lot_size - lot_size) > 0.001:
                    _log.info(
                        "Volume normalized for %s: %.4f -> %.4f (broker min=%.4f, max=%.4f, step=%.4f)",
                        symbol,
                        lot_size,
                        normalized_lot_size,
                        vol_min,
                        vol_max,
                        vol_step,
                    )
                lot_size = normalized_lot_size
                current_equity = self.conn.get_account_info()["equity"]
                aggregate_exposure_pct = 0.0
                for pos in active_positions_refresh:
                    pos_symbol = pos.get("symbol", "")
                    pos_lot = float(pos.get("volume", 0.0))
                    pos_open_price = float(pos.get("open_price", 0.0))
                    pos_sl = float(pos.get("sl", 0.0))
                    if pos_lot > 0 and pos_open_price > 0 and (pos_sl > 0):
                        from eqats_planes import calculate_stop_loss_exposure

                        pos_exposure = calculate_stop_loss_exposure(
                            pos_symbol, pos_lot, pos_open_price, pos_sl, current_equity,
                        )
                        aggregate_exposure_pct += pos_exposure
                price_info_curr = self.conn.get_current_price(symbol)
                entry_price_estimate = price_info_curr.get("ask" if decision == "BUY" else "bid", 0.0)
                proposed_exposure = 0.0
                total_exposure_with_new_order = None
                if entry_price_estimate > 0 and sl > 0 and (lot_size > 0):
                    from eqats_planes import calculate_stop_loss_exposure

                    proposed_exposure = calculate_stop_loss_exposure(
                        symbol, lot_size, entry_price_estimate, sl, current_equity,
                    )
                    total_exposure_with_new_order = aggregate_exposure_pct + proposed_exposure
                    _log.info(
                        "Aggregate stop-loss exposure: existing=%.2f%%, proposed=%.2f%%, total=%.2f%% (equity=%.2f, normalized_lot=%.4f)",
                        aggregate_exposure_pct,
                        proposed_exposure,
                        total_exposure_with_new_order,
                        current_equity,
                        lot_size,
                    )
                else:
                    _log.warning(
                        "SECURITY: Cannot calculate actual stop-loss exposure for %s (entry=%.5f, sl=%.5f, lot=%.4f). Falling back to deprecated count-based risk calculation. This may allow exposure to exceed limits.",
                        symbol,
                        entry_price_estimate,
                        sl,
                        lot_size,
                    )
                violations = self.engine.safety.evaluate_invariants(
                    current_risk=config.RISK_PER_TRADE_PERCENT * (len(active_positions_refresh) + 1),
                    active_count=len(active_positions_refresh) + 1,
                    has_reconciliation_mismatch=has_reconciliation_mismatch,
                    has_disagreement=has_disagreement,
                    actual_aggregate_exposure_pct=total_exposure_with_new_order,
                )
                signal_probability = dec_item.get("probability", 0.5)
                if decision == "BUY":
                    sl_distance = abs(entry_price_estimate - sl) if sl > 0 else 0.0
                    tp_distance = abs(tp - entry_price_estimate) if tp > 0 else 0.0
                else:
                    sl_distance = abs(sl - entry_price_estimate) if sl > 0 else 0.0
                    tp_distance = abs(entry_price_estimate - tp) if tp > 0 else 0.0
                actual_spread = price_info_curr.get("ask", 0.0) - price_info_curr.get("bid", 0.0)
                estimated_commission_per_lot = 7e-05
                estimated_commission = estimated_commission_per_lot * lot_size
                estimated_slippage = actual_spread * 0.5
                loss_probability = 1.0 - signal_probability
                gross_edge = signal_probability * tp_distance - loss_probability * sl_distance
                env = self.engine.risk.calculate_expected_net_value(
                    gross_edge=gross_edge,
                    spread=actual_spread,
                    commission=estimated_commission,
                    slippage=estimated_slippage,
                )
                _log.info(
                    "Expected Net Value calculation for %s: probability=%.3f, SL_dist=%.5f, TP_dist=%.5f, gross_edge=%.5f, spread=%.5f, commission=%.5f, slippage=%.5f, ENV=%.5f",
                    symbol,
                    signal_probability,
                    sl_distance,
                    tp_distance,
                    gross_edge,
                    actual_spread,
                    estimated_commission,
                    estimated_slippage,
                    env,
                )
                is_market_open, _ = self._is_market_open_and_liquid(symbol, price_info_curr)
                is_symbol_tradable = symbol in config.SYMBOLS
                global_risk_cap = getattr(config, "GLOBAL_RISK_LIMIT_CAP_PERCENT", 100.0)
                if total_exposure_with_new_order is not None:
                    curr_portfolio_risk = total_exposure_with_new_order
                    if curr_portfolio_risk > global_risk_cap:
                        _log.warning(
                            "BLOCKED: Aggregate stop-loss exposure %.2f%% exceeds GLOBAL_RISK_LIMIT_CAP_PERCENT %.2f%%",
                            curr_portfolio_risk,
                            global_risk_cap,
                        )
                        print(
                            f"🛡️ [GLOBAL RISK CAP BLOCKED]: Aggregate stop-loss exposure {curr_portfolio_risk:.1f}% exceeds Global Risk Cap {global_risk_cap:.1f}%.",
                        )
                        continue
                else:
                    sub_alloc_mod = 0.5 if getattr(config, "DEDICATED_RISK_SUB_ALLOCATION_ENABLED", True) else 1.0
                    curr_portfolio_risk = (
                        config.RISK_PER_TRADE_PERCENT * sub_alloc_mod * (len(active_positions_refresh) + 1)
                    )
                    if curr_portfolio_risk > global_risk_cap:
                        _log.warning(
                            "BLOCKED (count-based fallback): Estimated risk %.2f%% exceeds GLOBAL_RISK_LIMIT_CAP_PERCENT %.2f%%",
                            curr_portfolio_risk,
                            global_risk_cap,
                        )
                        print(
                            f"🛡️ [GLOBAL RISK CAP BLOCKED]: Estimated risk {curr_portfolio_risk:.1f}% exceeds Global Risk Cap {global_risk_cap:.1f}% (count-based fallback).",
                        )
                        continue
                constitution_payload = {
                    "market_open": is_market_open,
                    "symbol_tradable": is_symbol_tradable,
                    "safety_violations": violations,
                    "portfolio_risk_pct": curr_portfolio_risk,
                    "drawdown_pct": 0.0,
                    "spread_pips": float(scan_item["spread"] if scan_item and "spread" in scan_item else "1.0"),
                    "rate_throttled": self.engine.execution.rate_state != "NORMAL",
                    "strategy_valid": decision in ["BUY", "SELL"],
                    "ai_probability": dec_item.get("probability", 0.85) * 100.0,
                }
                const_res = self.engine.constitution.evaluate_constitution_compliance(constitution_payload)
                if not const_res["compliant"]:
                    print(f"🛡️ [SYSTEM CONSTITUTION BLOCKED]: {const_res['reason']}")
                    continue
                feed_price = float(scan_item["price"] if scan_item and scan_item["price"] != "-" else "1.1")
                price_ok = self.engine.data.check_price_deviation(symbol, feed_price, feed_price)
                if not price_ok:
                    print(
                        f"🛑 [REFERENCE PRICE DEVIATION BLOCKED]: {symbol} feed price deviated significantly from reference source.",
                    )
                    continue
                if not self.engine.safety.authorize_trade(symbol, env, violations):
                    print(f"🛑 [TRADE ADMISSION CONTROLLER BLOCKED]: Admitting order for {symbol} failed.")
                    continue
                if not self.engine.execution.validate_fat_finger(symbol, lot_size, feed_price):
                    print(
                        f"🛑 [FAT-FINGER PROTECTION BLOCKED]: lot size {lot_size} or notional exceeds standard limits.",
                    )
                    continue
                if self.engine.execution.prevent_self_trade(symbol, decision, active_positions_refresh):
                    print(f"🛑 [SELF-TRADE PREVENTION BLOCKED]: conflicting positions open on symbol {symbol}.")
                    continue
                if not self.engine.execution.check_rate_limits():
                    print("🛑 [RATE LIMITER BLOCKED]: order transmission rate limits exceeded.")
                    if self.engine.execution.rate_state == "HALTED":
                        self.engine.resilience.transition_state("HALTED")
                    elif self.engine.execution.rate_state == "THROTTLED":
                        self.engine.resilience.transition_state("DEFENSIVE")
                    continue
                if total_exposure_with_new_order is not None and proposed_exposure > 0:
                    self.engine.risk.reserve_capital(symbol, proposed_exposure)
                else:
                    self.engine.risk.reserve_capital(symbol, config.RISK_PER_TRADE_PERCENT)
                self.engine.risk.commit_reservation(symbol)
                print(f"🧠 Brain signaled: {decision} on {symbol} [{strat_tag}/{method_tag}]! Executing order...")
                res = self.engine.execution.execute_admitted_order(
                    symbol=symbol, direction=decision, lot=lot_size, sl=sl, tp=tp,
                )
                if res["success"]:
                    db_write_success = database.log_trade_open(
                        ticket=res["ticket"],
                        symbol=symbol,
                        direction=decision,
                        open_price=res["price"],
                        sl=sl,
                        tp=tp,
                        lot_size=lot_size,
                        strategy=strat_tag,
                        method=method_tag,
                    )
                    if not db_write_success:
                        _log.error(
                            "CRITICAL: Failed to log trade %s to database. This may indicate a duplicate ticket or integrity violation. Closing broker position immediately to prevent untracked exposure.",
                            res["ticket"],
                        )
                        print(
                            f"🚨 CRITICAL ERROR: Failed to log trade {res['ticket']} to database. Closing broker position immediately to prevent untracked exposure.",
                        )
                        close_result = self.conn.close_order(res["ticket"], reason="DATABASE_WRITE_FAILURE")
                        if close_result.get("success"):
                            _log.info(
                                "Successfully closed untracked position %s after database write failure", res["ticket"],
                            )
                        else:
                            _log.error(
                                "CRITICAL: Failed to close untracked position %s after database write failure. Manual intervention required. Error: %s",
                                res["ticket"],
                                close_result.get("error", "Unknown error"),
                            )
                            telegram_bot.send_telegram_message(
                                f"🚨 *CRITICAL ALERT*\nFailed to close untracked position {res['ticket']} after database write failure.\nManual intervention required immediately.\nSymbol: {symbol}, Direction: {decision}, Price: {res['price']:.5f}",
                            )
                        self.engine.risk.release_reservation(symbol)
                        continue
                    alert_msg = f"📊 *New Trade Executed!*\nSymbol: {symbol} ({decision})\nStrategy: {strat_tag} | Method: {method_tag}\nPrice: {res['price']:.5f}\nLot Size: {lot_size}\nSL: {sl:.5f} | TP: {tp:.5f}\nReason: {explanation}"
                    print(alert_msg.replace("*", ""))
                    telegram_bot.send_telegram_message(alert_msg)
                    active_positions.append(
                        {
                            "ticket": res["ticket"],
                            "symbol": symbol,
                            "direction": decision,
                            "open_price": res["price"],
                            "sl": sl,
                            "tp": tp,
                            "lot_size": lot_size,
                            "strategy": strat_tag,
                            "method": method_tag,
                        },
                    )
                    trading_available = len(active_positions) < config.MAX_CONCURRENT_TRADES
        kronos_telemetry = {}
        try:
            import predictive_brain

            for sym in config.SYMBOLS:
                k_model = predictive_brain.get_kronos_predictor(sym)
                df_bars = self.conn.get_history(sym, getattr(config, "TIMEFRAME", "M1"), count=60)
                if df_bars is not None and (not df_bars.empty):
                    ohlcv = df_bars[["open", "high", "low", "close", "tick_volume"]].to_numpy()
                    fc = k_model.forecast_probabilistic(ohlcv, forecast_horizon=24)
                    kronos_telemetry[sym] = {
                        "upside_prob": fc["upside_probability"],
                        "vol_amp": fc["volatility_amplification"],
                        "confidence": fc["model_confidence"],
                    }
        except Exception:
            pass
        try:
            sessions_timeline = self._get_sessions_timeline()
            self.ipc_bridge.push_state(
                equity=current_equity,
                balance=account["balance"],
                active_positions=active_positions,
                scans=scans_list,
                session_info=sessions_timeline,
                kronos_telemetry=kronos_telemetry,
            )
        except Exception as e:
            print(f"Warning: Telemetry push exception: {e}")
        print("-" * 120)


if __name__ == "__main__":
    use_gui = True
    try:
        import tkinter

        if tkinter and os.name != "nt" and (not os.environ.get("DISPLAY")):
            use_gui = False
    except ImportError:
        use_gui = False
    if use_gui:
        print("Launching Scalper Brain in Desktop GUI Mode...")
        import gui

        gui.launch_gui()
    else:
        print("No GUI environment detected or supported. Launching in CLASSIC CONSOLE MODE...")
        scalper = AutonomousScalper()
        if scalper.start():
            try:
                while True:
                    scalper.tick_and_execute()
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                scalper.stop()
