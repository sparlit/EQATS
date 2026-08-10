import os
import time
import datetime
import threading
import config
import database
import connector
import brain
import indicators
import predictive_brain
import telegram_bot

class AutonomousScalper:
    """
    The main coordinator class for the Autonomous Forex Scalper.
    It orchestrates initialization, main loops, technical scans, execution,
    trade monitoring, and risk/drawdown safeguards.
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

        # Track total starting balance of the day for Drawdown calculations
        self.daily_start_balance = 0.0
        self.last_day_str = ""

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
            f"🚀 *Elite Autonomous Quantum Trading System Started!*\n"
            f"Mode: {'Simulation' if config.SIMULATION_MODE else 'MT5 Terminal'}\n"
            f"Balance: {account_info['balance']:.2f} {account_info['currency']}\n"
            f"Risk Per Trade: {config.RISK_PER_TRADE_PERCENT}%\n"
            f"Max Drawdown Limit: {config.MAX_DAILY_DRAWDOWN_PERCENT}%"
        )
        print(start_msg.replace("*", ""))
        telegram_bot.send_telegram_message(start_msg)

        self.running = True
        return True

    def stop(self):
        self.running = False
        try:
            self.self_healer.stop_loop()
        except Exception:
            pass
        self.conn.disconnect()
        stop_msg = "🛑 *Elite Autonomous Quantum Trading System Stopped Safely.*"
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

            if direction == "BUY":
                # 1. Breakeven Profit Lock: Move SL to Entry Price once 1:1 RR is touched
                if bid >= entry_price + risk_dist and current_sl < entry_price + 0.00001:
                    success = self.conn.modify_order(ticket, round(entry_price, 5), current_tp)
                    if success:
                        print(f"🔒 AUTONOMOUS BREAKEVEN LOCK: Moved SL to entry price ({entry_price:.5f}) on BUY {symbol} (Ticket {ticket}) at 1:1 RR!")
                        current_sl = entry_price # update local ref for trailing step below

                # 2. Dynamic Trailing Stop
                target_sl = bid - trail_dist
                if target_sl > current_sl + 0.00005:
                    success = self.conn.modify_order(ticket, round(target_sl, 5), current_tp)
                    if success:
                        print(f"🎯 AUTONOMOUS TRAILING STOP: Moved SL on BUY {symbol} (Ticket {ticket}) up to {target_sl:.5f} (Locked profits!)")
            elif direction == "SELL":
                # 1. Breakeven Profit Lock: Move SL to Entry Price once 1:1 RR is touched
                if ask <= entry_price - risk_dist and (current_sl == 0 or current_sl > entry_price - 0.00001):
                    success = self.conn.modify_order(ticket, round(entry_price, 5), current_tp)
                    if success:
                        print(f"🔒 AUTONOMOUS BREAKEVEN LOCK: Moved SL to entry price ({entry_price:.5f}) on SELL {symbol} (Ticket {ticket}) at 1:1 RR!")
                        current_sl = entry_price # update local ref

                # 2. Dynamic Trailing Stop
                target_sl = ask + trail_dist
                # For SELL, target SL must be lower than current SL (or if current SL is 0)
                if current_sl == 0 or target_sl < current_sl - 0.00005:
                    success = self.conn.modify_order(ticket, round(target_sl, 5), current_tp)
                    if success:
                        print(f"🎯 AUTONOMOUS TRAILING STOP: Moved SL on SELL {symbol} (Ticket {ticket}) down to {target_sl:.5f} (Locked profits!)")

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

    def _write_ea_state_file(self, equity, balance, active_positions, scans):
        """
        Writes a highly structured trading state file 'scalper_state.txt' into the MT5
        Common Files directory so the native MQL5 EA can parse and show it on chart.
        """
        lines = []
        active_session = self._get_current_session()
        timeline = self._get_sessions_timeline()

        # Header line: equity|balance|active_count|active_session|overlaps|next_session|countdown
        lines.append(f"{equity:.2f}|{balance:.2f}|{len(active_positions)}|{active_session}|{timeline['previous']}|{timeline['next_session']}|{timeline['countdown']}")

        # Open Positions Section
        for pos in active_positions:
            ticket = pos.get('ticket', '0')
            symbol = pos.get('symbol', 'UNKNOWN')
            direction = pos.get('direction', 'BUY')
            open_p = pos.get('open_price', 0.0)
            sl = pos.get('sl', 0.0)
            tp = pos.get('tp', 0.0)

            # Simple floating profit estimate
            prices = self.conn.get_current_price(symbol)
            curr_p = prices['bid'] if direction == "BUY" else prices['ask']
            p_diff = curr_p - open_p if direction == "BUY" else open_p - curr_p
            is_crypto = "BTC" in symbol or "ETH" in symbol
            is_gold = "XAU" in symbol
            mult = 1.0 if is_crypto else (100.0 if is_gold else 100000.0)
            profit = p_diff * pos.get('lot_size', 0.0) * mult

            lines.append(f"TRADE|{ticket}|{symbol}|{direction}|{open_p:.5f}|{sl:.5f}|{tp:.5f}|{profit:.2f}")

        # Split marker
        lines.append("SCANS_HEADER")

        # Symbol scan lines: Symbol|Price|EMA200|Trend|RSI|ATR|Status|avg_w_ih|avg_w_ho|bias_output|hidden_activations
        for s in scans:
            lines.append(f"{s['symbol']}|{s['price']}|{s['ema200']}|{s['trend']}|{s['rsi']}|{s['atr']}|{s['status']}|{s.get('avg_w_ih', 0.0)}|{s.get('avg_w_ho', 0.0)}|{s.get('bias_output', 0.0)}|{s.get('hidden_activations', '0,0,0,0,0')}")

        file_content = "\n".join(lines)
        try:
            target_path = os.path.join(config.MT5_COMMON_FILES_PATH, "scalper_state.txt")
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(file_content)
        except Exception as e:
            print(f"Warning: Failed to write EA state file: {e}")

    def _generate_html_dashboard(self, current_time, equity, balance, active_positions, scans):
        """Generates a responsive and beautiful HTML dashboard file with live analytics."""
        perf = database.get_all_time_performance()
        timeline = self._get_sessions_timeline()
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="5">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scalper Brain Live Dashboard</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #0f172a;
            color: #f1f5f9;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #1e293b;
            padding-bottom: 20px;
            margin-bottom: 25px;
        }}
        h1 {{
            margin: 0;
            font-size: 24px;
            color: #38bdf8;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .badge {{
            background-color: #22c55e;
            color: #ffffff;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: bold;
        }}
        .badge.sim {{
            background-color: #eab308;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }}
        .card {{
            background-color: #1e293b;
            border-radius: 8px;
            padding: 15px 20px;
            border: 1px solid #334155;
        }}
        .card-label {{
            font-size: 13px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 5px;
        }}
        .card-val {{
            font-size: 24px;
            font-weight: bold;
            color: #f8fafc;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background-color: #1e293b;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #334155;
            margin-bottom: 25px;
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #334155;
        }}
        th {{
            background-color: #0f172a;
            color: #38bdf8;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        .status-badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .status-badge.hold {{
            background-color: #475569;
            color: #cbd5e1;
        }}
        .status-badge.active {{
            background-color: #1d4ed8;
            color: #ffffff;
        }}
        .status-badge.buy {{
            background-color: #15803d;
            color: #ffffff;
        }}
        .status-badge.sell {{
            background-color: #b91c1c;
            color: #ffffff;
        }}
        .time-text {{
            font-size: 12px;
            color: #64748b;
            text-align: right;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 SCALPER BRAIN <span class="badge {'sim' if config.SIMULATION_MODE else ''}">{'SIMULATION MODE' if config.SIMULATION_MODE else 'MT5 LIVE/DEMO'}</span></h1>
            <div style="text-align: right; display: flex; flex-direction: column; gap: 5px; align-items: flex-end;">
                <span class="status-badge active" style="background-color: #00ff00; color: #000000; font-family: monospace; font-weight: bold;">[ACTIVE] {timeline['active']}</span>
                <span class="status-badge hold" style="background-color: #555555; color: #ffffff; font-family: monospace; font-weight: bold;">[CLOSED <= 4H] {timeline['previous']}</span>
                <span class="status-badge active" style="background-color: #ff9900; color: #000000; font-family: monospace; font-weight: bold;">[UPCOMING] {timeline['next_session']}</span>
            </div>
        </header>

        <div class="metrics-grid">
            <div class="card">
                <div class="card-label">Account Balance</div>
                <div class="card-val">${balance:,.2f} USD</div>
            </div>
            <div class="card">
                <div class="card-label">Account Equity</div>
                <div class="card-val" style="color: #38bdf8;">${equity:,.2f} USD</div>
            </div>
            <div class="card">
                <div class="card-label">Open Positions</div>
                <div class="card-val">{len(active_positions)} / {config.MAX_CONCURRENT_TRADES}</div>
            </div>
            <div class="card">
                <div class="card-label">Active Market Session</div>
                <div class="card-val" style="color: #eab308; font-size: 20px;">{self._get_current_session()}</div>
            </div>
            <div class="card">
                <div class="card-label">Brain Performance Analytics</div>
                <div class="card-val" style="font-size: 15px; color: #38bdf8;">
                    Win Rate: {perf['win_rate']}% | Net Profit: {perf['net_profit']:.2f} USD ({perf['total_trades']} Trades)
                </div>
            </div>
        </div>

        <h2 style="font-size: 18px; color: #38bdf8; margin-bottom: 15px;">🔍 Multi-Asset Cognitive Scan Summary</h2>
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Current Price</th>
                    <th>EMA-200 (Trend)</th>
                    <th>Trend Bias</th>
                    <th>RSI Index</th>
                    <th>ATR Volatility</th>
                    <th>Input Weights (Avg)</th>
                    <th>Output Weights (Avg)</th>
                    <th>Neurons Activations</th>
                    <th>Current Status</th>
                </tr>
            </thead>
            <tbody>
        """

        for scan in scans:
            status_badge_class = "hold"
            if "ACTIVE" in scan['status']:
                status_badge_class = "active"
            elif "BUY" in scan['status'] or "Executing BUY" in scan['status']:
                status_badge_class = "buy"
            elif "SELL" in scan['status'] or "Executing SELL" in scan['status']:
                status_badge_class = "sell"

            html_content += f"""
                <tr>
                    <td style="font-weight: bold; color: #38bdf8;">{scan['symbol']}</td>
                    <td>{scan['price']}</td>
                    <td>{scan['ema200']}</td>
                    <td>{scan['trend']}</td>
                    <td>{scan['rsi']}</td>
                    <td>{scan['atr']}</td>
                    <td>{scan.get('avg_w_ih', 0.0):.4f}</td>
                    <td>{scan.get('avg_w_ho', 0.0):.4f}</td>
                    <td style="font-family: monospace; font-size: 12px; color: #eab308;">[{scan.get('hidden_activations', '0,0,0,0,0')}]</td>
                    <td><span class="status-badge {status_badge_class}">{scan['status']}</span></td>
                </tr>
            """

        html_content += f"""
            </tbody>
        </table>

        <div class="time-text">
            Last Updated: {current_time} (Dashboard auto-refreshes every 5 seconds)
        </div>
    </div>
</body>
</html>
        """

        try:
            with open("dashboard.html", "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"Warning: Failed to write dashboard.html: {e}")

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

        # Check if we already have an open trade on this exact symbol
        has_active_symbol = any(p['symbol'].upper() == symbol.upper() for p in active_positions)
        if has_active_symbol:
            trade_info = [p for p in active_positions if p['symbol'].upper() == symbol.upper()][0]

            # Dynamic Grid Trading Cost-Averaging Logic Expansion!
            if config.ACTIVE_STRATEGY == "GRID_TRADE":
                symbol_trades = [p for p in active_positions if p['symbol'].upper() == symbol.upper()]
                if len(symbol_trades) < config.GRID_MAX_LEVELS:
                    last_trade = symbol_trades[-1]
                    entry_p = last_trade['open_price']
                    direction = last_trade['direction']

                    atr_val = indicators.calculate_atr([b['high'] for b in history], [b['low'] for b in history], [b['close'] for b in history], config.ATR_PERIOD) or 0.0010
                    grid_spacing = atr_val * config.GRID_SPACING_ATR_MULT

                    price_info = self.conn.get_current_price(symbol)
                    current_p = price_info['bid'] if direction == "BUY" else price_info['ask']

                    should_add_grid = False
                    if direction == "BUY" and current_p <= entry_p - grid_spacing:
                        should_add_grid = True
                    elif direction == "SELL" and current_p >= entry_p + grid_spacing:
                        should_add_grid = True

                    if should_add_grid and len(active_positions) < config.MAX_CONCURRENT_TRADES:
                        with self.trade_lock:
                            lot = last_trade['lot_size']
                            sl_new = current_p - (grid_spacing * 2) if direction == "BUY" else current_p + (grid_spacing * 2)
                            tp_new = current_p + (grid_spacing * 3) if direction == "BUY" else current_p - (grid_spacing * 3)

                            res = self.conn.execute_order(symbol, direction, lot, sl_new, tp_new)
                            if res['success']:
                                database.log_trade_open(res['ticket'], symbol, direction, res['price'], sl_new, tp_new, lot)
                                print(f"🧱 GRID COST-AVERAGING PLACEMENT: Added layer {len(symbol_trades)+1} on {symbol} {direction} (Ticket {res['ticket']}) at {res['price']:.5f}")
                                active_positions.append({
                                    'ticket': res['ticket'],
                                    'symbol': symbol,
                                    'direction': direction,
                                    'open_price': res['price'],
                                    'sl': sl_new,
                                    'tp': tp_new,
                                    'lot_size': lot
                                })

            return {
                "symbol": symbol,
                "price": f"{current_price:.5f}",
                "ema200": "-",
                "trend": "-",
                "rsi": "-",
                "atr": "-",
                "status": f"ACTIVE ({trade_info['direction']} Ticket {trade_info['ticket']})",
                "decision": "HOLD",
                "analysis": None,
                "nn_state": None
            }

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
        updating open positions, and enforcing limits.
        """
        # Heartbeat: Check connection status and attempt auto-reconnection
        if not self.conn.is_connected():
            print("⚠️ DISCONNECTION DETECTED: Heartbeat failed. Autonomously attempting to reconnect...")
            try:
                self.conn.connect()
            except Exception as e:
                print(f"Warning: Reconnection attempt failed: {e}")
                return

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
                # Synchronize status with SQLite (if not already handled by Simulator)
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

        # Draw visual dashboards inside MT5 terminal (or simulated logs)
        dashboard_data = {
            "time": timestamp_str,
            "equity": current_equity,
            "balance": current_balance,
            "active_count": len(active_positions)
        }

        # Don't place new trades if we already reached our total max limit of simultaneous positions
        trading_available = len(active_positions) < config.MAX_CONCURRENT_TRADES

        scans_list = []
        pending_orders = []

        # Multi-threaded parallel processing using concurrent.futures
        import concurrent.futures
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

                print(f"🧠 Brain signaled: {decision} on {symbol}! Executing order...")
                res = self.conn.execute_order(
                    symbol=symbol,
                    order_type=decision,
                    lot_size=analysis['lot_size'],
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

        # Generate HTML Dashboard file with real and live data & indicators
        self._generate_html_dashboard(
            current_time=timestamp_str,
            equity=current_equity,
            balance=current_balance,
            active_positions=active_positions,
            scans=scans_list
        )

        # Write real-time trading state for native MT5 MQL5 EA visual dashboard
        self._write_ea_state_file(
            equity=current_equity,
            balance=current_balance,
            active_positions=active_positions,
            scans=scans_list
        )

        print("-" * 120)


if __name__ == "__main__":
    # Check if we should launch in GUI mode or fallback to classic CLI mode
    # Standard fallback if Tkinter is not supported/configured (e.g., in headless Linux/Docker environments)
    use_gui = True
    try:
        import tkinter as tk
        # Check for X11 display presence on Unix-like environments
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
