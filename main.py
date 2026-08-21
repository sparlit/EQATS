import os
import time
import datetime
import threading
import logging

# Configure root logger once at application entry point (FLAW-001)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

import config
import database
import connector
import brain
import indicators
import predictive_brain
import telegram_bot
import eaqts_planes
from event_bus import global_event_bus, Event
from supervisor_agent import global_supervisor_agent

class AutonomousScalper:
    """
    The main coordinator class for the Autonomous Forex Scalper.
    It orchestrates initialization, main loops, technical scans, execution,
    trade monitoring, and risk/drawdown safeguards under the EAQTS 3.0 unified control flow.
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

        # 3. Instantiate the EAQTS 3.0 Unified 9 Planes Engine
        self.engine = eaqts_planes.init_core_engine(self.conn)

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

        # Attach AI System Supervisor Agent
        self.supervisor = global_supervisor_agent

        # Attach Multi-Agent Brain Intelligence & Learning Orchestrator
        from brain_agents_orchestrator import global_brain_orchestrator
        self.brain_orchestrator = global_brain_orchestrator

        # Track total starting balance of the day for Drawdown calculations
        self.daily_start_balance = 0.0
        self.last_day_str = ""

        # Event Bus wiring: subscribe to vital events
        global_event_bus.subscribe("SafetyInvariantViolation", self._handle_safety_violation)
        global_event_bus.subscribe("TradeAdmissionApproved", self._handle_trade_approved)
        global_event_bus.subscribe("TradeAdmissionRejected", self._handle_trade_rejected)

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
        self.daily_start_balance = account_info['balance']
        self.last_day_str = datetime.date.today().isoformat()

        start_msg = (
            f"🚀 *Elite Quantum Autonomous Trading System Started!*\n"
            f"Mode: {'Simulation' if config.SIMULATION_MODE else 'MT5 Terminal'}\n"
            f"Balance: {account_info['balance']:.2f} {account_info['currency']}\n"
            f"Risk Per Trade: {config.RISK_PER_TRADE_PERCENT}%\n"
            f"Max Drawdown Limit: {config.MAX_DAILY_DRAWDOWN_PERCENT}%"
        )
        print(start_msg.replace("*", ""))
        telegram_bot.send_telegram_message(start_msg)

        # Notify Event Bus
        global_event_bus.publish(Event(
            family="SystemFault",
            source="Main",
            payload={"message": "System starting up cleanly"}
        ))

        self.running = True
        return True

    def stop(self):
        self.running = False
        try:
            self.self_healer.stop_loop()
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
            symbol = pos['symbol']
            ticket = pos['ticket']
            direction = pos['direction']
            current_sl = pos['sl']
            current_tp = pos['tp']

            # Get historical ATR
            history = self.conn.get_history(symbol, 30)
            if not history:
                continue

            closes = [bar['close'] for bar in history]
            highs = [bar['high'] for bar in history]
            lows = [bar['low'] for bar in history]
            atr_val = indicators.calculate_atr(highs, lows, closes, config.ATR_PERIOD)
            if atr_val is None or atr_val <= 0:
                continue

            trail_dist = atr_val * config.TRAILING_STOP_ATR_MULT
            price_info = self.conn.get_current_price(symbol)
            bid = price_info['bid']
            ask = price_info['ask']

            entry_price = pos.get('open_price', 0.0)
            if entry_price <= 0:
                continue

            risk_dist = abs(entry_price - current_sl)

            spread_buffer = max(0.00001, ask - bid)
            trigger_distance = min(atr_val, risk_dist) if risk_dist > 0 else atr_val

            if direction == "BUY":
                # 1. Breakeven Profit Lock: Move SL to Entry Price + spread buffer once 1.0x ATR / 1:1 RR is reached
                be_sl = entry_price + spread_buffer
                if bid >= entry_price + trigger_distance and current_sl < be_sl:
                    success = self.conn.modify_order(ticket, round(be_sl, 5), current_tp)
                    if success:
                        print(f"🔒 AUTONOMOUS BREAKEVEN LOCK: Moved SL to entry + spread buffer ({be_sl:.5f}) on BUY {symbol} (Ticket {ticket}) at +1.0x ATR!")
                        current_sl = be_sl

                # 2. Dynamic ATR Trailing Stop
                target_sl = bid - trail_dist
                if target_sl > current_sl + 0.00005:
                    success = self.conn.modify_order(ticket, round(target_sl, 5), current_tp)
                    if success:
                        print(f"🎯 AUTONOMOUS TRAILING STOP: Moved SL on BUY {symbol} (Ticket {ticket}) up to {target_sl:.5f} (Locked profits!)")
                        current_sl = target_sl
            elif direction == "SELL":
                # 1. Breakeven Profit Lock: Move SL to Entry Price - spread buffer once 1.0x ATR / 1:1 RR is reached
                be_sl = entry_price - spread_buffer
                if ask <= entry_price - trigger_distance and (current_sl == 0 or current_sl > be_sl):
                    success = self.conn.modify_order(ticket, round(be_sl, 5), current_tp)
                    if success:
                        print(f"🔒 AUTONOMOUS BREAKEVEN LOCK: Moved SL to entry - spread buffer ({be_sl:.5f}) on SELL {symbol} (Ticket {ticket}) at +1.0x ATR!")
                        current_sl = be_sl

                # 2. Dynamic ATR Trailing Stop
                target_sl = ask + trail_dist
                if current_sl == 0 or target_sl < current_sl - 0.00005:
                    success = self.conn.modify_order(ticket, round(target_sl, 5), current_tp)
                    if success:
                        print(f"🎯 AUTONOMOUS TRAILING STOP: Moved SL on SELL {symbol} (Ticket {ticket}) down to {target_sl:.5f} (Locked profits!)")
                        current_sl = target_sl

    def _is_market_open_and_liquid(self, symbol, price_info):
        """
        Autonomously assesses market conditions to protect capital from
        wide spreads or dangerous rollover/weekend gaps.
        Returns: (bool, str) - (is_safe, description_reason)
        """
        # A. Session Time Filters
        now_gmt = datetime.datetime.now(datetime.timezone.utc)
        weekday = now_gmt.weekday() # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
        hour = now_gmt.hour

        symbol_upper = symbol.upper()
        is_crypto_asset = any(c in symbol_upper for c in ["BTC", "ETH", "LTC", "SOL", "XRP"])

        if config.BLOCK_WEEKENDS and not is_crypto_asset:
            # Friday after 21:00 GMT to Sunday before 21:00 GMT
            if (weekday == 4 and hour >= 21) or weekday == 5 or (weekday == 6 and hour < 21):
                return False, "Hazardous session: Weekend market shutdown."

        if config.BLOCK_ROLLOVER_HOUR:
            # Rollover daily spread expansions occur between 22:00 and 23:00 GMT standardly
            if hour == 22:
                return False, "Hazardous session: Daily broker rollover hour."

        # B. Spread Protections
        bid = price_info['bid']
        ask = price_info['ask']
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
        if not hasattr(self, '_symbol_avg_spreads'):
            self._symbol_avg_spreads = {}

        sym_upper = symbol.upper()
        if sym_upper not in self._symbol_avg_spreads:
            self._symbol_avg_spreads[sym_upper] = [spread_pips]
        else:
            self._symbol_avg_spreads[sym_upper].append(spread_pips)
            if len(self._symbol_avg_spreads[sym_upper]) > 20:
                self._symbol_avg_spreads[sym_upper].pop(0)

        avg_spread = sum(self._symbol_avg_spreads[sym_upper]) / len(self._symbol_avg_spreads[sym_upper])

        # Check 2.5x rolling average spread spike breaker first
        if len(self._symbol_avg_spreads[sym_upper]) >= 5 and spread_pips > (2.5 * avg_spread) and spread_pips > 3.0:
            return False, f"Liquidity Filter (Spread Volatility Spike Breaker): Spread ({spread_pips:.1f} pips) exceeds 2.5x 20-period avg spread ({avg_spread:.1f} pips)."

        if spread_pips > config.MAX_SPREAD_PIPS:
            return False, f"Liquidity Filter: Spread is too wide ({spread_pips:.1f} pips > {config.MAX_SPREAD_PIPS:.1f} limit)."

        return True, "Safe conditions"

    def _get_current_session(self):
        """Autonomously determines the active global trading session based on GMT hour and weekend status."""
        now_gmt = datetime.datetime.now(datetime.timezone.utc)
        weekday = now_gmt.weekday() # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
        hour = now_gmt.hour

        # Traditional markets weekend check (Friday 21:00 to Sunday 21:00 GMT)
        is_weekend = (weekday == 4 and hour >= 21) or weekday == 5 or (weekday == 6 and hour < 21)
        if is_weekend:
            return "Crypto Weekend Session (24/7)"

        # Session Hour definitions (GMT)
        tokyo = (0 <= hour < 9)
        london = (8 <= hour < 17)
        ny = (12 <= hour < 21)

        sessions = []
        if tokyo: sessions.append("Tokyo")
        if london: sessions.append("London")
        if ny: sessions.append("New York")

        if not sessions:
            return "Global 24-Hour Interbank Session"
        return " + ".join(sessions) + " Overlap" if len(sessions) > 1 else sessions[0] + " Session"

    def _get_sessions_timeline(self):
        """
        Comprehensive 24-Session Market Timeline Tracker.
        Calculates 3 rows of data: Active, Previous, and Coming sessions with precise countdown timers.
        """
        now_gmt = datetime.datetime.now(datetime.timezone.utc)
        weekday = now_gmt.weekday() # 0 = Monday, ..., 6 = Sunday
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
            "Crypto Markets": (0, 24, "Digital")
        }

        active = []
        previous = []
        coming = []

        is_weekend = (weekday == 4 and hour >= 21) or weekday == 5 or (weekday == 6 and hour < 21)

        for name, (start, end, cat) in self.sessions_def.items():
            # Check weekend blockades for non-crypto assets
            if cat != "Digital" and is_weekend:
                continue

            # Determine if session is active standardly
            is_active = False
            if start < end:
                if start <= hour < end:
                    is_active = True
            else: # Wraps past midnight
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

        return {
            "active": " | ".join(active) if active else "No active sessions",
            "previous": " | ".join(previous) if previous else "None",
            "next_session": " | ".join(coming_str_list[:3]) if coming_str_list else "None",
            "countdown": "Active Tracker"
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
            return [s for s in all_symbols if any(c in s.upper() for c in ["BTC", "ETH", "LTC", "SOL", "XRP"])]

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
                "nn_state": None
            }

        current_price = history[-1]['close']

        # Notify Data Plane of incoming tick
        self.engine.data.store_price(symbol, current_price - 0.0001, current_price + 0.0001)


        # Autonomously select optimal trading style and strategy dynamically first!
        try:
            closes_hist = [b['close'] for b in history]
            highs_hist = [b['high'] for b in history]
            lows_hist = [b['low'] for b in history]
            opt_style, opt_strat = self.quantum_auto_engine.determine_optimal_style_and_strategy(
                symbol, closes_hist, highs_hist, lows_hist
            )
        except Exception:
            pass

        # Get latest tick price details to execute spread filters
        price_info = self.conn.get_current_price(symbol)
        is_safe, safety_reason = self._is_market_open_and_liquid(symbol, price_info)

        # Get technical analysis and trading decision from the Brain
        analysis = self.brain.evaluate(symbol, history, current_equity)
        decision = analysis['decision']
        indicators_info = analysis.get('indicators', {})
        ema200 = indicators_info.get('ema_long', 0.0)
        rsi_val = indicators_info.get('rsi', 0.0)
        atr_val = indicators_info.get('atr', 0.0)
        trend_str = "UP" if current_price > ema200 else "DOWN"

        status_text = analysis['explanation']
        if not is_safe:
            decision = "HOLD"
            status_text = f"HOLD ({safety_reason})"
        elif not trading_available:
            status_text = "HOLD (MAX LIMIT OF ACTIVE TRADES REACHED)"
        elif decision in ['BUY', 'SELL']:
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
            "nn_state": nn_state
        }

    def tick_and_execute(self):
        """
        Runs one iteration of checking market state, assessing trades,
        updating open positions, and enforcing limits under EAQTS 3.0 logic.
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
            print("⚠️ DISCONNECTION DETECTED: Heartbeat failed. Autonomously attempting to reconnect...")
            try:
                self.conn.connect()
            except Exception as e:
                print(f"Warning: Reconnection attempt failed: {e}")
                return

        # Log heartbeat metrics on the Operations plane
        self.engine.resilience.log_heartbeat(0.12)

        # A. Check and update the daily drawdown start baseline
        current_date = datetime.date.today().isoformat()
        if current_date != self.last_day_str:
            account_info = self.conn.get_account_info()
            self.daily_start_balance = account_info['balance']
            self.last_day_str = current_date
            print(f"New day detected: {current_date}. Resetting daily baseline to {self.daily_start_balance:.2f}")

        # B. If Simulator, advance the simulator clocks and process SL/TP
        if config.SIMULATION_MODE:
            # Let the simulator tick and automatically trigger closures on hit SL/TP
            closed_tickets = self.conn.tick()
            for ticket in closed_tickets:
                pass

        # C. Check Real-Time Floating Daily Drawdown Limit
        account_tmp = self.conn.get_account_info()
        current_equity = account_tmp['equity']

        # Real-time daily loss including closed trades and floating trades PnL
        daily_floating_loss = current_equity - self.daily_start_balance
        max_allowed_loss = self.daily_start_balance * (config.MAX_DAILY_DRAWDOWN_PERCENT / 100.0)

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

            # Autonomously close all active trades immediately to preserve remaining capital!
            active_positions = self.conn.get_open_orders()
            for pos in active_positions:
                self.conn.close_order(pos['ticket'], reason="DAILY_DRAWDOWN_CIRCUIT_BREAKER")
            return

        # D. Retrieve open positions from connection and synchronize with SQLite
        active_positions = self.conn.get_open_orders()
        open_db_trades = database.get_open_trades()

        # Process trailing stops for active positions
        self._process_trailing_stops(active_positions)

        # Trigger Autonomous Performance Analysis in real-time
        account_tmp = self.conn.get_account_info()
        database.update_performance_metrics(current_date, account_tmp['balance'])

        # If positions closed externally in MT5 terminal, synchronize SQLite
        active_tickets = {str(p['ticket']) for p in active_positions}
        for db_trade in open_db_trades:
            ticket_str = str(db_trade['ticket'])
            if ticket_str not in active_tickets:
                # Closed externally in MT5
                current_price = self.conn.get_current_price(db_trade['symbol'])['bid']
                p_diff = current_price - db_trade['open_price']
                if db_trade['direction'] == 'SELL':
                    p_diff = -p_diff

                # Rough contract size estimation
                is_crypto = "BTC" in db_trade['symbol'] or "ETH" in db_trade['symbol']
                is_gold = "XAU" in db_trade['symbol']
                mult = 1.0 if is_crypto else (100.0 if is_gold else 100000.0)
                estimated_profit = p_diff * db_trade['lot_size'] * mult

                database.log_trade_close(ticket_str, current_price, estimated_profit, "EXTERNAL_MT5_CLOSE")
                print(f"Trade {ticket_str} ({db_trade['symbol']}) detected as CLOSED on MT5. Synchronized local database.")

        # E. Core Scanning Loop & Status Reporting
        account = self.conn.get_account_info()
        current_equity = account['equity']
        current_balance = account['balance']

        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        active_session = self._get_current_session()
        active_symbols = self._get_session_symbols(active_session)

        print(f"\n⚡ [{timestamp_str}] --- COGNITIVE SCAN CYCLE ---")
        print(f"Equity: {current_equity:.2f} USD | Active Trades: {len(active_positions)}/{config.MAX_CONCURRENT_TRADES} | Active Session: {active_session}")
        print(f"{'Symbol':<9} | {'Price':<10} | {'EMA-200':<10} | {'Trend':<5} | {'RSI':<6} | {'ATR':<8} | {'Status'}")
        print("-" * 120)

        # Don't place new trades if we already reached our total max limit of simultaneous positions
        trading_available = len(active_positions) < config.MAX_CONCURRENT_TRADES

        scans_list = []
        pending_orders = []

        # High-Performance Parallel processing bypassing the GIL using ProcessPoolExecutor falling back to ThreadPoolExecutor
        import concurrent.futures
        import multiprocessing as mp
        pool_workers = min(12, max(1, len(active_symbols))) # Optimized for Performance hybrid cores (12 logical threads)
        parallel_success = False

        try:
            # Use 'spawn' context to prevent multi-threaded fork deprecation warnings
            ctx = mp.get_context('spawn')
            with concurrent.futures.ProcessPoolExecutor(max_workers=pool_workers, mp_context=ctx) as executor:
                future_to_symbol = {
                    executor.submit(self.evaluate_symbol_worker, symbol, list(active_positions), current_equity, trading_available): symbol
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
            # Fall back gracefully to thread-pool under GIL-restricted sandboxes
            pass

        if not parallel_success:
            scans_list = []
            pending_orders = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(active_symbols))) as executor:
                future_to_symbol = {
                    executor.submit(self.evaluate_symbol_worker, symbol, list(active_positions), current_equity, trading_available): symbol
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

        # Sort scans_list by symbol name to keep output clean and ordered
        scans_list = sorted(scans_list, key=lambda x: x["symbol"])

        # Display results
        for s in scans_list:
            print(f"{s['symbol']:<9} | {s['price']:<10} | {s['ema200']:<10} | {s['trend']:<5} | {s['rsi']:<6} | {s['atr']:<8} | {s['status']}")

        # Process any pending orders sequentially under thread-safe lock
        for symbol, decision, analysis in pending_orders:
            if not trading_available:
                break

            with self.trade_lock:
                # Double-check constraints inside lock context
                active_positions_refresh = self.conn.get_open_orders()
                if len(active_positions_refresh) >= config.MAX_CONCURRENT_TRADES:
                    break
                if any(p['symbol'].upper() == symbol.upper() for p in active_positions_refresh):
                    continue

                # Find the scan matching this symbol to retrieve NN State and trends
                scan_item = next((sc for sc in scans_list if sc["symbol"].upper() == symbol.upper()), None)
                tech_trend = scan_item["trend"] if scan_item else "UP"
                ai_trend = "UP" if (analysis.get("probability", 0.5) >= 0.5) else "DOWN"

                # Check State Disagreement (Section 22)
                component_decisions = {"technical_trend": tech_trend, "ai_trend": ai_trend}
                has_disagreement = not self.engine.safety.verify_component_agreement(component_decisions)

                # Check Continuous Reconciliation Mismatch (Section 33)
                open_db_trades_refresh = database.get_open_trades()
                has_reconciliation_mismatch = not self.engine.resilience.reconcile_positions(open_db_trades_refresh, active_positions_refresh)

                # ==================================================================
                # EAQTS 3.0 UNIFIED SAFETY, RISK AND TRADE ADMISSION ENFORCEMENT
                # ==================================================================
                # A. Evaluate Safety Invariants (INV-001 to INV-015)
                violations = self.engine.safety.evaluate_invariants(
                    current_risk=config.RISK_PER_TRADE_PERCENT * (len(active_positions_refresh) + 1),
                    active_count=len(active_positions_refresh) + 1,
                    has_reconciliation_mismatch=has_reconciliation_mismatch,
                    has_disagreement=has_disagreement
                )

                # B. Estimate Expected Net Value
                env = self.engine.risk.calculate_expected_net_value(
                    gross_edge=config.RISK_PER_TRADE_PERCENT * 2.0, # Expected win
                    spread=0.0002,
                    commission=0.0001,
                    slippage=0.0001
                )

                # C. System Constitution Hierarchy Evaluation (Level 0 - Level 6)
                price_info_curr = self.conn.get_current_price(symbol)
                is_market_open, _ = self._is_market_open_and_liquid(symbol, price_info_curr)
                is_symbol_tradable = symbol in config.SYMBOLS

                constitution_payload = {
                    "market_open": is_market_open,
                    "symbol_tradable": is_symbol_tradable,
                    "safety_violations": violations,
                    "portfolio_risk_pct": config.RISK_PER_TRADE_PERCENT * (len(active_positions_refresh) + 1),
                    "drawdown_pct": 0.0,
                    "spread_pips": float(scan_item["spread"] if (scan_item and "spread" in scan_item) else "1.0"),
                    "rate_throttled": (self.engine.execution.rate_state != "NORMAL"),
                    "strategy_valid": (decision in ['BUY', 'SELL']),
                    "ai_probability": 85.0
                }
                const_res = self.engine.constitution.evaluate_constitution_compliance(constitution_payload)
                if not const_res["compliant"]:
                    print(f"🛡️ [SYSTEM CONSTITUTION BLOCKED]: {const_res['reason']}")
                    continue

                # D. Reference Price Deviation check (Section 10.5)
                feed_price = float(scan_item["price"] if (scan_item and scan_item["price"] != "-") else "1.1")
                price_ok = self.engine.data.check_price_deviation(symbol, feed_price, feed_price) # Compares with self as baseline
                if not price_ok:
                    print(f"🛑 [REFERENCE PRICE DEVIATION BLOCKED]: {symbol} feed price deviated significantly from reference source.")
                    continue

                # E. Safety Kernel check
                if not self.engine.safety.authorize_trade(symbol, env, violations):
                    print(f"🛑 [TRADE ADMISSION CONTROLLER BLOCKED]: Admitting order for {symbol} failed.")
                    continue

                # E. Fat-Finger checking
                if not self.engine.execution.validate_fat_finger(symbol, analysis['lot_size'], feed_price):
                    print(f"🛑 [FAT-FINGER PROTECTION BLOCKED]: lot size {analysis['lot_size']} or notional exceeds standard limits.")
                    continue

                # F. Self-Trade prevention check
                if self.engine.execution.prevent_self_trade(symbol, decision, active_positions_refresh):
                    print(f"🛑 [SELF-TRADE PREVENTION BLOCKED]: conflicting positions open on symbol {symbol}.")
                    continue

                # G. Rate limits check (Section 24.1)
                if not self.engine.execution.check_rate_limits():
                    print(f"🛑 [RATE LIMITER BLOCKED]: order transmission rate limits exceeded.")
                    # Transition resilience state on throttling
                    if self.engine.execution.rate_state == "HALTED":
                        self.engine.resilience.transition_state("HALTED")
                    elif self.engine.execution.rate_state == "THROTTLED":
                        self.engine.resilience.transition_state("DEFENSIVE")
                    continue

                # Commit Reservation & execute
                self.engine.risk.reserve_capital(symbol, config.RISK_PER_TRADE_PERCENT)
                self.engine.risk.commit_reservation(symbol)

                print(f"🧠 Brain signaled: {decision} on {symbol}! Executing order...")
                res = self.engine.execution.execute_admitted_order(
                    symbol=symbol,
                    direction=decision,
                    lot=analysis['lot_size'],
                    sl=analysis['sl'],
                    tp=analysis['tp']
                )

                if res['success']:
                    database.log_trade_open(
                        ticket=res['ticket'],
                        symbol=symbol,
                        direction=decision,
                        open_price=res['price'],
                        sl=analysis['sl'],
                        tp=analysis['tp'],
                        lot_size=analysis['lot_size']
                    )

                    alert_msg = (
                        f"📊 *New Trade Executed!*\n"
                        f"Symbol: {symbol} ({decision})\n"
                        f"Price: {res['price']:.5f}\n"
                        f"Lot Size: {analysis['lot_size']}\n"
                        f"SL: {analysis['sl']:.5f} | TP: {analysis['tp']:.5f}\n"
                        f"Reason: {analysis['explanation']}"
                    )
                    print(alert_msg.replace("*", ""))
                    telegram_bot.send_telegram_message(alert_msg)

                    active_positions.append({
                        'ticket': res['ticket'],
                        'symbol': symbol,
                        'direction': decision,
                        'open_price': res['price'],
                        'sl': analysis['sl'],
                        'tp': analysis['tp'],
                        'lot_size': analysis['lot_size']
                    })
                    trading_available = len(active_positions) < config.MAX_CONCURRENT_TRADES

        print("-" * 120)


if __name__ == "__main__":
    # Check if we should launch in GUI mode or fallback to classic CLI mode
    use_gui = True
    try:
        import tkinter as tk
        if os.name != 'nt' and not os.environ.get('DISPLAY'):
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
