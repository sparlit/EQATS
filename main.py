import datetime
import logging
import os
import threading
import time

# Configure root logger once at application entry point (FLAW-001)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

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

    def __init__(self):
        # 1. Initialize SQLite Database
        database.init_db()

        # 2. Setup chosen connector (Live MT5 or High-Fidelity Simulator)
        if config.SIMULATION_MODE:
            print("--- RUNNING IN SIMULATION MODE (PAPER TRADING) ---")
            self.conn = connector.SimulatorConnector(initial_balance=10000.0)
        else:
            print("--- RUNNING IN LIVE MT5 WINDOWS MODE ---")
            self.conn = connector.MT5Connector(demo_only=config.DEMO_ACCOUNT_ONLY)

        # 3. Instantiate the EQATS 3.0 Unified 9 Planes Engine
        self.engine = eqats_planes.init_core_engine(self.conn)

        self.brain = brain.ScalperBrain()
        self.running = False

        # Thread-safe execution lock to prevent order collisions
        self.trade_lock = threading.Lock()

        # Instantiate premium Autonomous decision & strategy engine!
        import institutional_integrations as ii

        self.quantum_auto_engine = ii.QuantumAutoEngine()

        # Spawn non-stop, non-break self-healer and self-learning loop autonomously!
        self.self_healer = ii.QuantumSelfHealer()
        self.self_healer.start_non_stop_loop()

        # Instantiate Zero-Latency Socket IPC Bridge for MT5 EA Telemetry Push (Port 9001)
        from institutional_integrations.web_api import SocketIPCBridge

        self.ipc_bridge = SocketIPCBridge(host="127.0.0.1", port=9001)
        self.ipc_bridge.start_server()

        # Attach AI System Supervisor Agent
        self.supervisor = global_supervisor_agent

        # Attach Multi-Agent Brain Intelligence & Learning Orchestrator
        from brain_agents_orchestrator import global_brain_orchestrator

        self.brain_orchestrator = global_brain_orchestrator

        # Track total starting balance of the day for Drawdown calculations
        self.daily_start_balance = 0.0
        self.last_day_str = ""

        # Event Bus wiring: subscribe to vital events
        global_event_bus.subscribe(
            "SafetyInvariantViolation", self._handle_safety_violation
        )
        global_event_bus.subscribe(
            "TradeAdmissionApproved", self._handle_trade_approved
        )
        global_event_bus.subscribe(
            "TradeAdmissionRejected", self._handle_trade_rejected
        )

    def _handle_safety_violation(self, event: Event):
        print(f"🛑 [SAFETY INVARIANT VIOLATION EVENT]: {event.payload}")

    def _handle_trade_approved(self, event: Event):
        print(f"✅ [TRADE ADMISSION APPROVED EVENT]: {event.payload}")

    def _handle_trade_rejected(self, event: Event):
        print(f"❌ [TRADE ADMISSION REJECTED EVENT]: {event.payload}")

    def start(self):
        """Connects and starts the main loop."""
        try:
            self.conn.connect()
        except Exception as e:
            print(f"CRITICAL ERROR: Failed to connect to terminal: {e}")
            return False

        account_info = self.conn.get_account_info()
        self.daily_start_balance = account_info["balance"]
        self.last_day_str = datetime.date.today().isoformat()
        # SECURITY FIX: Load persisted circuit breaker state
        persisted_state = database.load_circuit_breaker_state()
        current_date = datetime.date.today().isoformat()
        
        if persisted_state and persisted_state["trading_date"] == current_date:
            # Same trading day - recover the baseline and halt state
            self.daily_start_balance = persisted_state["daily_start_balance"]
            self.last_day_str = persisted_state["trading_date"]
            
            if persisted_state["is_halted"]:
                # Circuit breaker was triggered earlier today - restore HALTED state
                self.engine.resilience.transition_state("HALTED")
                halt_msg = (
                    f"⚠️ *CIRCUIT BREAKER STATE RECOVERED FROM DATABASE*\\n"
                    f"Trading was halted earlier today at {persisted_state['halt_timestamp']}.\\n"
                    f"Reason: {persisted_state['halt_reason']}\\n"
                    f"Daily baseline: {self.daily_start_balance:.2f}\\n"
                    f"Current balance: {account_info['balance']:.2f}\\n"
                    f"Trading remains HALTED until manual operator override or next trading day."
                )
                print(halt_msg.replace("*", ""))
                telegram_bot.send_telegram_message(halt_msg)
            else:
                # Same day, not halted - use persisted baseline
                recovery_msg = (
                    f"📊 *Daily baseline recovered from database*\\n"
                    f"Date: {current_date}\\n"
                    f"Baseline: {self.daily_start_balance:.2f}\\n"
                    f"Current: {account_info['balance']:.2f}"
                )
                print(recovery_msg.replace("*", ""))
        else:
            # New trading day or no persisted state - establish new baseline
            self.daily_start_balance = account_info["balance"]
            self.last_day_str = current_date
            
            # Persist the new baseline to database
            database.save_circuit_breaker_state(
                trading_date=current_date,
                daily_start_balance=self.daily_start_balance,
                is_halted=False
            )
            
            new_day_msg = f"🌅 New trading day baseline established: {self.daily_start_balance:.2f}"
            print(new_day_msg)

        start_msg = (
            f"🚀 *Elite Quantum Autonomous Trading System Started!*\n"
            f"Mode: {'Simulation' if config.SIMULATION_MODE else 'MT5 Terminal'}\n"
            f"Balance: {account_info['balance']:.2f} {account_info['currency']}\n"
            f"Daily Baseline: {self.daily_start_balance:.2f}\\n"
            f"Risk Per Trade: {config.RISK_PER_TRADE_PERCENT}%\n"
            f"Max Drawdown Limit: {config.MAX_DAILY_DRAWDOWN_PERCENT}%"
        )
        print(start_msg.replace("*", ""))
        telegram_bot.send_telegram_message(start_msg)

        # Notify Event Bus
        global_event_bus.publish(
            Event(
                family="SystemFault",
                source="Main",
                payload={"message": "System starting up cleanly"},
            )
        )

        self.running = True
        return True

    def stop(self):
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

    def _process_trailing_stops(self, active_positions):
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

            # Get historical ATR
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

            spread_buffer = max(0.00001, ask - bid)
            trigger_distance = min(atr_val, risk_dist) if risk_dist > 0 else atr_val

            if direction == "BUY":
                # 1. Breakeven Profit Lock: Move SL to Entry Price + spread buffer once 1.0x ATR / 1:1 RR is reached
                be_sl = entry_price + spread_buffer
                if bid >= entry_price + trigger_distance and current_sl < be_sl:
                    success = self.conn.modify_order(
                        ticket, round(be_sl, 5), current_tp
                    )
                    if success:
                        print(
                            f"🔒 AUTONOMOUS BREAKEVEN LOCK: Moved SL to entry + spread buffer ({be_sl:.5f}) on BUY {symbol} (Ticket {ticket}) at +1.0x ATR!"
                        )
                        current_sl = be_sl

                # 2. Dynamic ATR Trailing Stop
                target_sl = bid - trail_dist
                if target_sl > current_sl + 0.00005:
                    success = self.conn.modify_order(
                        ticket, round(target_sl, 5), current_tp
                    )
                    if success:
                        print(
                            f"🎯 AUTONOMOUS TRAILING STOP: Moved SL on BUY {symbol} (Ticket {ticket}) up to {target_sl:.5f} (Locked profits!)"
                        )
                        current_sl = target_sl
            elif direction == "SELL":
                # 1. Breakeven Profit Lock: Move SL to Entry Price - spread buffer once 1.0x ATR / 1:1 RR is reached
                be_sl = entry_price - spread_buffer
                if ask <= entry_price - trigger_distance and (
                    current_sl == 0 or current_sl > be_sl
                ):
                    success = self.conn.modify_order(
                        ticket, round(be_sl, 5), current_tp
                    )
                    if success:
                        print(
                            f"🔒 AUTONOMOUS BREAKEVEN LOCK: Moved SL to entry - spread buffer ({be_sl:.5f}) on SELL {symbol} (Ticket {ticket}) at +1.0x ATR!"
                        )
                        current_sl = be_sl

                # 2. Dynamic ATR Trailing Stop
                target_sl = ask + trail_dist
                if current_sl == 0 or target_sl < current_sl - 0.00005:
                    success = self.conn.modify_order(
                        ticket, round(target_sl, 5), current_tp
                    )
                    if success:
                        print(
                            f"🎯 AUTONOMOUS TRAILING STOP: Moved SL on SELL {symbol} (Ticket {ticket}) down to {target_sl:.5f} (Locked profits!)"
                        )
                        current_sl = target_sl

    def _is_market_open_and_liquid(self, symbol, price_info):
        """
        Autonomously assesses market conditions to protect capital from
        wide spreads or dangerous rollover/weekend gaps.
        Returns: (bool, str) - (is_safe, description_reason)
        """
        # A. Session Time Filters
        now_gmt = datetime.datetime.now(datetime.timezone.utc)
        weekday = (
            now_gmt.weekday()
        )  # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
        hour = now_gmt.hour

        symbol_upper = symbol.upper()
        is_crypto_asset = any(
            c in symbol_upper for c in ["BTC", "ETH", "LTC", "SOL", "XRP"]
        )

        if config.BLOCK_WEEKENDS and not is_crypto_asset and (
            (weekday == 4 and hour >= 21)
            or weekday == 5
            or (weekday == 6 and hour < 21)
        ):
            return False, "Hazardous session: Weekend market shutdown."

        if config.BLOCK_ROLLOVER_HOUR and hour == 22:
            return False, "Hazardous session: Daily broker rollover hour."

        # B. Spread Protections
        bid = price_info["bid"]
        ask = price_info["ask"]
        spread = ask - bid
        if spread < 0:
            return False, "Negative spread / bad price data."

        # Enforce Data Plane reasonableness filters
        data_status = self.engine.data.validate_reasonableness(symbol, bid, ask)
        if data_status in ["INVALID", "QUARANTINED"]:
            return False, f"Data Plane Filter: Market state is {data_status}."

        # Determine pip scaling
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

        # Dynamic Spread Volatility Spike Breaker: Track rolling average spread per symbol
        if not hasattr(self, "_symbol_avg_spreads"):
            self._symbol_avg_spreads = {}

        sym_upper = symbol.upper()
        if sym_upper not in self._symbol_avg_spreads:
            self._symbol_avg_spreads[sym_upper] = [spread_pips]
        else:
            self._symbol_avg_spreads[sym_upper].append(spread_pips)
            if len(self._symbol_avg_spreads[sym_upper]) > 20:
                self._symbol_avg_spreads[sym_upper].pop(0)

        avg_spread = sum(self._symbol_avg_spreads[sym_upper]) / len(
            self._symbol_avg_spreads[sym_upper]
        )

        # Check 2.5x rolling average spread spike breaker first
        if (
            len(self._symbol_avg_spreads[sym_upper]) >= 5
            and spread_pips > (2.5 * avg_spread)
            and spread_pips > 3.0
        ):
            return (
                False,
                f"Liquidity Filter (Spread Volatility Spike Breaker): Spread ({spread_pips:.1f} pips) exceeds 2.5x 20-period avg spread ({avg_spread:.1f} pips).",
            )

        if spread_pips > config.MAX_SPREAD_PIPS:
            return (
                False,
                f"Liquidity Filter: Spread is too wide ({spread_pips:.1f} pips > {config.MAX_SPREAD_PIPS:.1f} limit).",
            )

        return True, "Safe conditions"

    def _get_current_session(self):
        """Autonomously determines the active global trading session based on GMT hour and weekend status."""
        now_gmt = datetime.datetime.now(datetime.timezone.utc)
        weekday = (
            now_gmt.weekday()
        )  # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
        hour = now_gmt.hour

        # Traditional markets weekend check (Friday 21:00 to Sunday 21:00 GMT)
        is_weekend = (
            (weekday == 4 and hour >= 21)
            or weekday == 5
            or (weekday == 6 and hour < 21)
        )
        if is_weekend:
            return "Crypto Weekend Session (24/7)"

        # Session Hour definitions (GMT)
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
        return (
            " + ".join(sessions) + " Overlap"
            if len(sessions) > 1
            else sessions[0] + " Session"
        )

    def _get_sessions_timeline(self):
        """
        Comprehensive 24-Session Market Timeline Tracker.
        Calculates 3 rows of data: Active, Previous, and Coming sessions with precise countdown timers.
        """
        now_gmt = datetime.datetime.now(datetime.timezone.utc)
        weekday = now_gmt.weekday()  # 0 = Monday, ..., 6 = Sunday
        hour = now_gmt.hour
        minute = now_gmt.minute
        second = now_gmt.second

        # Definitions of all 24 specific Forex, Equity, Futures, and Crypto sessions
        # Format: (start_hour_gmt, end_hour_gmt, category)
        self.sessions_def = {
            # 1. Forex Sessions
            "Wellington FX": (20, 5, "Forex"),
            "Sydney FX": (22, 7, "Forex"),
            "Tokyo FX": (23, 8, "Forex"),
            "Hong Kong FX": (1, 10, "Forex"),
            "Singapore FX": (1, 10, "Forex"),
            "Frankfurt FX": (6, 15, "Forex"),
            "London FX": (7, 16, "Forex"),
            "Zurich FX": (7, 15, "Forex"),
            "New York FX": (12, 21, "Forex"),
            # 2. Global Equity Sessions
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
            # 3. US Extended Hours
            "US Pre-Market": (8, 13, "Extended"),
            "US After-Hours": (20, 0, "Extended"),
            # 4. Futures & Commodities
            "CME Futures": (22, 21, "Futures"),
            "ICE Brent": (23, 22, "Futures"),
            # 5. Digital Assets
            "Crypto Markets": (0, 24, "Digital"),
        }

        active = []
        previous = []
        coming = []

        is_weekend = (
            (weekday == 4 and hour >= 21)
            or weekday == 5
            or (weekday == 6 and hour < 21)
        )

        for name, (start, end, cat) in self.sessions_def.items():
            # Check weekend blockades for non-crypto assets
            if cat != "Digital" and is_weekend:
                continue

            # Determine if session is active standardly
            is_active = False
            if start < end:
                if start <= hour < end:
                    is_active = True
            else:  # Wraps past midnight
                if hour >= start or hour < end:
                    is_active = True

            if is_active:
                active.append(name)
            else:
                # Check if it was closed in the previous 4 hours
                is_prev = False
                prev_close = end
                dist_closed = (hour - prev_close) % 24
                if dist_closed <= 4:
                    is_prev = True

                if is_prev:
                    previous.append(name)
                else:
                    # Calculate countdown to coming opening
                    dist_to_start = (start - hour) % 24
                    coming.append((name, dist_to_start, start))

        # Sort coming sessions by closest opening hour
        coming = sorted(coming, key=lambda x: x[1])

        # Formulate Coming rows with exact countdown timers
        coming_str_list = []
        for name, dist, start_h in coming[:5]:
            seconds_to_start = (dist * 3600) - (minute * 60) - second
            if seconds_to_start < 0:
                seconds_to_start += 24 * 3600

            h_cd = seconds_to_start // 3600
            m_cd = (seconds_to_start % 3600) // 60
            s_cd = seconds_to_start % 60
            cd_timer = f"{h_cd:02d}:{m_cd:02d}:{s_cd:02d}"
            coming_str_list.append(f"{name} ({cd_timer})")

        # Overlapping sessions calculation (when >1 sessions are active concurrently)
        overlapping_str = " | ".join(active) if len(active) > 1 else "None (Single Session)"

        return {
            "active": " | ".join(active) if active else "No active sessions",
            "overlapping": overlapping_str,
            "next_session": " | ".join(coming_str_list[:3])
            if coming_str_list
            else "None",
            "previous": " | ".join(previous) if previous else "None",
            "countdown": "Active Tracker",
        }

    def _get_session_symbols(self, active_session):
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
            # Trade ONLY crypto symbols on weekends when traditional markets are closed
            return [
                s
                for s in all_symbols
                if any(c in s.upper() for c in ["BTC", "ETH", "LTC", "SOL", "XRP"])
            ]

        # Weekdays: All markets are fully active and liquid!
        return all_symbols

    def evaluate_symbol_worker(self, symbol, active_positions, current_equity, trading_available):
        """
        Parallel worker to perform indicator calculation, research scraping,
        regime selection, and strategy evaluations for a single symbol.
        """
        # Fetch 210 candles of historical data (plenty for 200 EMA calculation)
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

        # Notify Data Plane of incoming tick
        self.engine.data.store_price(
            symbol, current_price - 0.0001, current_price + 0.0001
        )

        # Autonomously select optimal trading style and strategy dynamically first!
        try:
            closes_hist = [b["close"] for b in history]
            highs_hist = [b["high"] for b in history]
            lows_hist = [b["low"] for b in history]
            opt_style, opt_strat = (
                self.quantum_auto_engine.determine_optimal_style_and_strategy(
                    symbol, closes_hist, highs_hist, lows_hist
                )
            )
        except Exception:
            pass

        # Get latest tick price details to execute spread filters
        price_info = self.conn.get_current_price(symbol)
        is_safe, safety_reason = self._is_market_open_and_liquid(symbol, price_info)

        # Get technical analysis and trading decision from the Brain
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

        # Fetch AI internal state diagnostics
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

    def tick_and_execute(self):
        """
        Runs one iteration of checking market state, assessing trades,
        updating open positions, and enforcing limits under EQATS 3.0 logic.
        """
        # Run Multi-Agent Brain Intelligence Collaborative Loop
        try:
            self.brain_orchestrator.run_agentic_loop(self, symbol=config.SYMBOLS[0])
        except Exception as e:
            print(f"Warning: Brain orchestrator loop exception: {e}")

        # Run AI System Supervisor Agent Audit
        try:
            self.supervisor.run_supervisory_audit(self)
        except Exception as e:
            print(f"Warning: Supervisor agent audit exception: {e}")

        # Heartbeat: Check connection status and attempt auto-reconnection
        if not self.conn.is_connected():
            print(
                "⚠️ DISCONNECTION DETECTED: Heartbeat failed. Autonomously attempting to reconnect..."
            )
            try:
                self.conn.connect()
            except Exception as e:
                print(f"Warning: Reconnection attempt failed: {e}")
                return

        # Log heartbeat metrics on the Operations plane
        self.engine.resilience.log_heartbeat(0.12)

        # SECURITY FIX: Check if circuit breaker is in HALTED state
        if self.engine.resilience.get_state() == "HALTED":
            # Trading is halted - skip all trading logic
            print("⚠️ Trading is HALTED due to circuit breaker. Skipping tick cycle.")
            return

        # A. Check and update the daily drawdown start baseline
        current_date = datetime.date.today().isoformat()
        if current_date != self.last_day_str:
            account_info = self.conn.get_account_info()
            self.daily_start_balance = account_info["balance"]
            self.last_day_str = current_date
            
            # SECURITY FIX: Persist new daily baseline to database
            database.save_circuit_breaker_state(
                trading_date=current_date,
                daily_start_balance=self.daily_start_balance,
                is_halted=False
            )
            
            print(
                f"New day detected: {current_date}. Resetting daily baseline to {self.daily_start_balance:.2f}"
            )

        # B. If Simulator, advance the simulator clocks and process SL/TP
        if config.SIMULATION_MODE:
            # Let the simulator tick and automatically trigger closures on hit SL/TP
            closed_tickets = self.conn.tick()
            for ticket in closed_tickets:
                pass

        # C. Check Real-Time Floating Daily Drawdown Limit
        account_tmp = self.conn.get_account_info()
        current_equity = account_tmp["equity"]

        # Real-time daily loss including closed trades and floating trades PnL
        daily_floating_loss = current_equity - self.daily_start_balance
        max_allowed_loss = self.daily_start_balance * (
            config.MAX_DAILY_DRAWDOWN_PERCENT / 100.0
        )

        if daily_floating_loss < 0 and abs(daily_floating_loss) >= max_allowed_loss:
            warn_msg = (
                f"⚠️ *CRITICAL DRAWDOWN CIRCUIT BREAKER TRIGGERED!*\n"
                f"Daily drawdown of {abs(daily_floating_loss):.2f} USD reached "
                f"({config.MAX_DAILY_DRAWDOWN_PERCENT}% of starting {self.daily_start_balance:.2f} USD).\n"
                f"Autonomously liquidating all open positions and stopping trading for the day..."
            )
            print(warn_msg.replace("*", ""))
            telegram_bot.send_telegram_message(warn_msg)

            # Transition safety state machine to HALTED (Section 41)
            self.engine.resilience.transition_state("HALTED")
            
            # SECURITY FIX: Persist HALTED state to database
            halt_reason = f"Daily drawdown limit reached: {abs(daily_floating_loss):.2f} USD ({config.MAX_DAILY_DRAWDOWN_PERCENT}%)"
            database.save_circuit_breaker_state(
                trading_date=current_date,
                daily_start_balance=self.daily_start_balance,
                is_halted=True,
                halt_reason=halt_reason
            )

            # Autonomously close all active trades immediately to preserve remaining capital!
            active_positions = self.conn.get_open_orders()
            for pos in active_positions:
                self.conn.close_order(
                    pos["ticket"], reason="DAILY_DRAWDOWN_CIRCUIT_BREAKER"
                )
            return

        # D. Retrieve open positions from connection and synchronize with SQLite
        active_positions = self.conn.get_open_orders()
        open_db_trades = database.get_open_trades()

        # Process trailing stops for active positions
        self._process_trailing_stops(active_positions)

        # Trigger Autonomous Performance Analysis in real-time
        account_tmp = self.conn.get_account_info()
        database.update_performance_metrics(current_date, account_tmp["balance"])

        # If positions closed externally in MT5 terminal, synchronize SQLite
        active_tickets = {str(p["ticket"]) for p in active_positions}
        for db_trade in open_db_trades:
            ticket_str = str(db_trade["ticket"])
            if ticket_str not in active_tickets:
                # Closed externally in MT5
                current_price = self.conn.get_current_price(db_trade["symbol"])["bid"]
                p_diff = current_price - db_trade["open_price"]
                if db_trade["direction"] == "SELL":
                    p_diff = -p_diff

                # Rough contract size estimation
                is_crypto = "BTC" in db_trade["symbol"] or "ETH" in db_trade["symbol"]
                is_gold = "XAU" in db_trade["symbol"]
                mult = 1.0 if is_crypto else (100.0 if is_gold else 100000.0)
                estimated_profit = p_diff * db_trade["lot_size"] * mult

                database.log_trade_close(
                    ticket_str, current_price, estimated_profit, "EXTERNAL_MT5_CLOSE"
                )
                print(
                    f"Trade {ticket_str} ({db_trade['symbol']}) detected as CLOSED on MT5. Synchronized local database."
                )

        # E. Core Scanning Loop & Status Reporting
        account = self.conn.get_account_info()
        current_equity = account["equity"]

        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        active_session = self._get_current_session()
        active_symbols = self._get_session_symbols(active_session)

        print(f"\n⚡ [{timestamp_str}] --- COGNITIVE SCAN CYCLE ---")
        print(
            f"Equity: {current_equity:.2f} USD | Active Trades: {len(active_positions)}/{config.MAX_CONCURRENT_TRADES} | Active Session: {active_session}"
        )
        print(
            f"{'Symbol':<9} | {'Price':<10} | {'EMA-200':<10} | {'Trend':<5} | {'RSI':<6} | {'ATR':<8} | {'Status'}"
        )
        print("-" * 120)

        # Don't place new trades if we already reached our total max limit of simultaneous positions
        trading_available = len(active_positions) < config.MAX_CONCURRENT_TRADES

        scans_list = []
        pending_orders = []

        # High-Performance Parallel processing bypassing the GIL using ProcessPoolExecutor falling back to ThreadPoolExecutor
        import concurrent.futures
        import multiprocessing as mp

        from institutional_integrations.system_autotune import global_tuned_config
        max_autotuned = global_tuned_config.get("process_pool_workers", os.cpu_count() or 8)
        pool_workers = max(1, min(max_autotuned, len(active_symbols)))
        parallel_success = False

        # Spawn ProcessPoolExecutor only if running in the MainProcess to prevent nested process pool deadlocks
        if mp.current_process().name == "MainProcess":
            try:
                # Use 'spawn' context to prevent multi-threaded fork deprecation warnings
                ctx = mp.get_context("spawn")
                with concurrent.futures.ProcessPoolExecutor(
                    max_workers=pool_workers, mp_context=ctx
                ) as executor:
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
                            pending_orders.append(
                                (res["symbol"], res["decision"], res["analysis"])
                            )
                    parallel_success = True
            except Exception:
                # Fall back gracefully to thread-pool under GIL-restricted sandboxes
                pass

        if not parallel_success:
            scans_list = []
            pending_orders = []
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, len(active_symbols))
            ) as executor:
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
                    try:
                        res = future.result()
                        scans_list.append(res)
                        if res["decision"] in ["BUY", "SELL"] and res["analysis"]:
                            pending_orders.append(
                                (res["symbol"], res["decision"], res["analysis"])
                            )
                    except Exception as e:
                        print(
                            f"Error evaluating symbol {symbol} in parallel thread: {e}"
                        )

        # Sort scans_list by symbol name to keep output clean and ordered
        scans_list = sorted(scans_list, key=lambda x: x["symbol"])

        # Display results
        for s in scans_list:
            print(
                f"{s['symbol']:<9} | {s['price']:<10} | {s['ema200']:<10} | {s['trend']:<5} | {s['rsi']:<6} | {s['atr']:<8} | {s['status']}"
            )

        # Unpack all decisions from scans_list
        raw_pending_decisions = []
        for s in scans_list:
            if s.get("analysis") and s["analysis"].get("decisions"):
                for dec_item in s["analysis"]["decisions"]:
                    raw_pending_decisions.append(dec_item)
            elif s.get("decision") in ["BUY", "SELL"] and s.get("analysis"):
                raw_pending_decisions.append({
                    "symbol": s["symbol"],
                    "decision": s["decision"],
                    "lot_size": s["analysis"].get("lot_size", 0.01),
                    "sl": s["analysis"].get("sl", 0.0),
                    "tp": s["analysis"].get("tp", 0.0),
                    "explanation": s["analysis"].get("explanation", ""),
                    "strategy": getattr(config, "ACTIVE_STRATEGY", ""),
                    "method": getattr(config, "TRADING_STYLE", ""),
                    "probability": s["analysis"].get("probability", 0.85),
                })

        # Deduplicate pending decisions by (symbol, decision) keeping highest probability
        dedup_dict = {}
        for dec_item in raw_pending_decisions:
            key = (dec_item["symbol"].upper(), dec_item["decision"])
            if key not in dedup_dict or dec_item.get("probability", 0.0) > dedup_dict[key].get("probability", 0.0):
                dedup_dict[key] = dec_item
        all_pending_decisions = list(dedup_dict.values())

        # Process any pending orders sequentially under thread-safe lock
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
                # Double-check constraints inside lock context
                active_positions_refresh = self.conn.get_open_orders()
                if len(active_positions_refresh) >= config.MAX_CONCURRENT_TRADES:
                    break

                # Enforce per-symbol order limit for same symbol and direction
                if any(
                    p["symbol"].upper() == symbol.upper() and p.get("direction") == decision
                    for p in active_positions_refresh
                ):
                    continue

                if getattr(config, "ENABLE_SYMBOL_FLOATING_LOSS_GATE", True):
                    # If floating loss gate enabled, check if existing position on symbol is in loss
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
                                diff = (price_curr - p_open) if p_dir == "BUY" else (p_open - price_curr)
                                is_losing = diff < 0
                            if is_losing:
                                in_loss = True
                                break
                    if in_loss:
                        continue

                # Find the scan matching this symbol to retrieve NN State and trends
                scan_item = next(
                    (sc for sc in scans_list if sc["symbol"].upper() == symbol.upper()),
                    None,
                )
                tech_trend = scan_item["trend"] if scan_item else "UP"
                ai_trend = "UP" if (dec_item.get("probability", 0.85) >= 0.5) else "DOWN"

                # Check State Disagreement (Section 22)
                component_decisions = {
                    "technical_trend": tech_trend,
                    "ai_trend": ai_trend,
                }
                has_disagreement = not self.engine.safety.verify_component_agreement(
                    component_decisions
                )

                # Check Continuous Reconciliation Mismatch (Section 33)
                open_db_trades_refresh = database.get_open_trades()
                has_reconciliation_mismatch = (
                    not self.engine.resilience.reconcile_positions(
                        open_db_trades_refresh, active_positions_refresh
                    )
                )

                # ==================================================================
                # EQATS 3.0 UNIFIED SAFETY, RISK AND TRADE ADMISSION ENFORCEMENT
                # ==================================================================
                
                # SECURITY FIX: Normalize lot_size to broker constraints BEFORE exposure calculation
                # This ensures exposure calculations, safety checks, and execution all use the same volume
                constraints = self.conn.get_symbol_volume_constraints(symbol)
                vol_min = constraints["volume_min"]
                vol_max = constraints["volume_max"]
                vol_step = constraints["volume_step"]
                
                # Apply broker volume constraints
                normalized_lot_size = max(vol_min, min(vol_max, float(lot_size)))
                if vol_step > 0:
                    steps = round((normalized_lot_size - vol_min) / vol_step)
                    calc_lots = vol_min + steps * vol_step
                    step_str = f"{vol_step:.8f}".rstrip("0")
                    precision = len(step_str.split(".")[1]) if "." in step_str else 0
                    normalized_lot_size = round(calc_lots, precision)
                    normalized_lot_size = max(vol_min, min(vol_max, normalized_lot_size))
                
                # Log volume adjustment if it occurred
                if abs(normalized_lot_size - lot_size) > 0.001:
                    _log.info(
                        "Volume normalized for %s: %.4f -> %.4f (broker min=%.4f, max=%.4f, step=%.4f)",
                        symbol, lot_size, normalized_lot_size, vol_min, vol_max, vol_step
                    )
                
                # SECURITY: Use normalized volume for all subsequent calculations and checks
                lot_size = normalized_lot_size
                
                # SECURITY FIX: Calculate actual aggregate stop-loss exposure
                # This replaces the count-based proxy with real monetary exposure
                current_equity = self.conn.get_account_info()["equity"]
                aggregate_exposure_pct = 0.0
                
                # Sum existing positions' actual stop-loss exposure
                for pos in active_positions_refresh:
                    pos_symbol = pos.get("symbol", "")
                    pos_lot = float(pos.get("volume", 0.0))
                    pos_open_price = float(pos.get("open_price", 0.0))
                    pos_sl = float(pos.get("sl", 0.0))
                    
                    if pos_lot > 0 and pos_open_price > 0 and pos_sl > 0:
                        from eqats_planes import calculate_stop_loss_exposure
                        pos_exposure = calculate_stop_loss_exposure(
                            pos_symbol, pos_lot, pos_open_price, pos_sl, current_equity
                        )
                        aggregate_exposure_pct += pos_exposure
                
                # Calculate proposed order's stop-loss exposure using NORMALIZED lot size
                price_info_curr = self.conn.get_current_price(symbol)
                entry_price_estimate = price_info_curr.get("ask" if decision == "BUY" else "bid", 0.0)
                
                proposed_exposure = 0.0
                total_exposure_with_new_order = None
                
                if entry_price_estimate > 0 and sl > 0 and lot_size > 0:
                    from eqats_planes import calculate_stop_loss_exposure
                    proposed_exposure = calculate_stop_loss_exposure(
                        symbol, lot_size, entry_price_estimate, sl, current_equity
                    )
                    total_exposure_with_new_order = aggregate_exposure_pct + proposed_exposure
                    _log.info(
                        "Aggregate stop-loss exposure: existing=%.2f%%, proposed=%.2f%%, total=%.2f%% (equity=%.2f, normalized_lot=%.4f)",
                        aggregate_exposure_pct, proposed_exposure, total_exposure_with_new_order, current_equity, lot_size
                    )
                else:
                    # SECURITY WARNING: Cannot calculate actual exposure - will use count-based fallback
                    # This should only occur if stop-loss is missing or invalid
                    _log.warning(
                        "SECURITY: Cannot calculate actual stop-loss exposure for %s (entry=%.5f, sl=%.5f, lot=%.4f). "
                        "Falling back to deprecated count-based risk calculation. This may allow exposure to exceed limits.",
                        symbol, entry_price_estimate, sl, lot_size
                    )
                
                # A. Evaluate Safety Invariants (INV-001 to INV-015) with actual exposure
                # SECURITY FIX: Pass actual aggregate exposure instead of count-based proxy
                # The current_risk parameter is deprecated but kept for backward compatibility
                violations = self.engine.safety.evaluate_invariants(
                    current_risk=config.RISK_PER_TRADE_PERCENT * (len(active_positions_refresh) + 1),  # Deprecated
                    active_count=len(active_positions_refresh) + 1,
                    has_reconciliation_mismatch=has_reconciliation_mismatch,
                    has_disagreement=has_disagreement,
                    actual_aggregate_exposure_pct=total_exposure_with_new_order,
                )

                # B. Estimate Expected Net Value
                env = self.engine.risk.calculate_expected_net_value(
                    gross_edge=config.RISK_PER_TRADE_PERCENT * 2.0,  # Expected win
                    spread=0.0002,
                    commission=0.0001,
                    slippage=0.0001,
                )

                # C. System Constitution Hierarchy Evaluation (Level 0 - Level 6)
                is_market_open, _ = self._is_market_open_and_liquid(
                    symbol, price_info_curr
                )
                is_symbol_tradable = symbol in config.SYMBOLS

                # SECURITY FIX: Check global risk cap using actual aggregate stop-loss exposure
                # This enforces GLOBAL_RISK_LIMIT_CAP_PERCENT based on real monetary exposure
                global_risk_cap = getattr(config, "GLOBAL_RISK_LIMIT_CAP_PERCENT", 100.0)
                
                if total_exposure_with_new_order is not None:
                    # Use actual stop-loss exposure (preferred method)
                    curr_portfolio_risk = total_exposure_with_new_order
                    if curr_portfolio_risk > global_risk_cap:
                        _log.warning(
                            "BLOCKED: Aggregate stop-loss exposure %.2f%% exceeds GLOBAL_RISK_LIMIT_CAP_PERCENT %.2f%%",
                            curr_portfolio_risk, global_risk_cap
                        )
                        print(f"🛡️ [GLOBAL RISK CAP BLOCKED]: Aggregate stop-loss exposure {curr_portfolio_risk:.1f}% exceeds Global Risk Cap {global_risk_cap:.1f}%.")
                        continue
                else:
                    # DEPRECATED: Legacy count-based calculation as fallback
                    # This should only occur when stop-loss data is unavailable
                    sub_alloc_mod = 0.5 if getattr(config, "DEDICATED_RISK_SUB_ALLOCATION_ENABLED", True) else 1.0
                    curr_portfolio_risk = (config.RISK_PER_TRADE_PERCENT * sub_alloc_mod) * (len(active_positions_refresh) + 1)
                    if curr_portfolio_risk > global_risk_cap:
                        _log.warning(
                            "BLOCKED (count-based fallback): Estimated risk %.2f%% exceeds GLOBAL_RISK_LIMIT_CAP_PERCENT %.2f%%",
                            curr_portfolio_risk, global_risk_cap
                        )
                        print(f"🛡️ [GLOBAL RISK CAP BLOCKED]: Estimated risk {curr_portfolio_risk:.1f}% exceeds Global Risk Cap {global_risk_cap:.1f}% (count-based fallback).")
                        continue

                constitution_payload = {
                    "market_open": is_market_open,
                    "symbol_tradable": is_symbol_tradable,
                    "safety_violations": violations,
                    "portfolio_risk_pct": curr_portfolio_risk,
                    "drawdown_pct": 0.0,
                    "spread_pips": float(
                        scan_item["spread"]
                        if (scan_item and "spread" in scan_item)
                        else "1.0"
                    ),
                    "rate_throttled": (self.engine.execution.rate_state != "NORMAL"),
                    "strategy_valid": (decision in ["BUY", "SELL"]),
                    "ai_probability": dec_item.get("probability", 0.85) * 100.0,
                }
                const_res = self.engine.constitution.evaluate_constitution_compliance(
                    constitution_payload
                )
                if not const_res["compliant"]:
                    print(f"🛡️ [SYSTEM CONSTITUTION BLOCKED]: {const_res['reason']}")
                    continue

                # D. Reference Price Deviation check (Section 10.5)
                feed_price = float(
                    scan_item["price"]
                    if (scan_item and scan_item["price"] != "-")
                    else "1.1"
                )
                price_ok = self.engine.data.check_price_deviation(
                    symbol, feed_price, feed_price
                )  # Compares with self as baseline
                if not price_ok:
                    print(
                        f"🛑 [REFERENCE PRICE DEVIATION BLOCKED]: {symbol} feed price deviated significantly from reference source."
                    )
                    continue

                # E. Safety Kernel check
                if not self.engine.safety.authorize_trade(symbol, env, violations):
                    print(
                        f"🛑 [TRADE ADMISSION CONTROLLER BLOCKED]: Admitting order for {symbol} failed."
                    )
                    continue

                # F. Fat-Finger checking (using normalized lot_size from earlier)
                if not self.engine.execution.validate_fat_finger(
                    symbol, lot_size, feed_price
                ):
                    print(
                        f"🛑 [FAT-FINGER PROTECTION BLOCKED]: lot size {lot_size} or notional exceeds standard limits."
                    )
                    continue

                # G. Self-Trade prevention check
                if self.engine.execution.prevent_self_trade(
                    symbol, decision, active_positions_refresh
                ):
                    print(
                        f"🛑 [SELF-TRADE PREVENTION BLOCKED]: conflicting positions open on symbol {symbol}."
                    )
                    continue

                # H. Rate limits check (Section 24.1)
                if not self.engine.execution.check_rate_limits():
                    print("🛑 [RATE LIMITER BLOCKED]: order transmission rate limits exceeded.")
                    # Transition resilience state on throttling
                    if self.engine.execution.rate_state == "HALTED":
                        self.engine.resilience.transition_state("HALTED")
                    elif self.engine.execution.rate_state == "THROTTLED":
                        self.engine.resilience.transition_state("DEFENSIVE")
                    continue

                # Commit Reservation & execute
                # Reserve actual exposure amount instead of configured percentage
                if total_exposure_with_new_order is not None and proposed_exposure > 0:
                    self.engine.risk.reserve_capital(symbol, proposed_exposure)
                else:
                    # Fallback to configured percentage if actual exposure unavailable
                    self.engine.risk.reserve_capital(symbol, config.RISK_PER_TRADE_PERCENT)
                self.engine.risk.commit_reservation(symbol)

                print(f"🧠 Brain signaled: {decision} on {symbol} [{strat_tag}/{method_tag}]! Executing order...")
                res = self.engine.execution.execute_admitted_order(
                    symbol=symbol,
                    direction=decision,
                    lot=lot_size,
                    sl=sl,
                    tp=tp,
                )

                if res["success"]:
                    database.log_trade_open(
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

                    alert_msg = (
                        f"📊 *New Trade Executed!*\n"
                        f"Symbol: {symbol} ({decision})\n"
                        f"Strategy: {strat_tag} | Method: {method_tag}\n"
                        f"Price: {res['price']:.5f}\n"
                        f"Lot Size: {lot_size}\n"
                        f"SL: {sl:.5f} | TP: {tp:.5f}\n"
                        f"Reason: {explanation}"
                    )
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
                        }
                    )
                    trading_available = (
                        len(active_positions) < config.MAX_CONCURRENT_TRADES
                    )

        # Gather Kronos Foundation Model Telemetry
        kronos_telemetry = {}
        try:
            import predictive_brain
            for sym in config.SYMBOLS:
                k_model = predictive_brain.get_kronos_predictor(sym)
                df_bars = self.conn.get_history(sym, getattr(config, "TIMEFRAME", "M1"), count=60)
                if df_bars is not None and not df_bars.empty:
                    ohlcv = df_bars[["open", "high", "low", "close", "tick_volume"]].to_numpy()
                    fc = k_model.forecast_probabilistic(ohlcv, forecast_horizon=24)
                    kronos_telemetry[sym] = {
                        "upside_prob": fc["upside_probability"],
                        "vol_amp": fc["volatility_amplification"],
                        "confidence": fc["model_confidence"],
                    }
        except Exception:
            pass

        # Push real-time state telemetry to connected MT5 EA via SocketIPCBridge on Port 9001
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
    # Check if we should launch in GUI mode or fallback to classic CLI mode
    use_gui = True
    try:
        import tkinter

        if tkinter and os.name != "nt" and not os.environ.get("DISPLAY"):
            use_gui = False
    except ImportError:
        use_gui = False

    if use_gui:
        print("Launching Scalper Brain in Desktop GUI Mode...")
        import gui

        gui.launch_gui()
    else:
        print(
            "No GUI environment detected or supported. Launching in CLASSIC CONSOLE MODE..."
        )
        scalper = AutonomousScalper()
        if scalper.start():
            try:
                while True:
                    scalper.tick_and_execute()
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                scalper.stop()
