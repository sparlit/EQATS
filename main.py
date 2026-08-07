import os
import time
import datetime
import config
import database
import connector
import brain
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
            f"🚀 *Autonomous Forex Scalper Started!*\n"
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
        self.conn.disconnect()
        stop_msg = "🛑 *Autonomous Forex Scalper Stopped Safely.*"
        print(stop_msg.replace("*", ""))
        telegram_bot.send_telegram_message(stop_msg)

    def _generate_html_dashboard(self, current_time, equity, balance, active_positions, scans):
        """Generates a responsive and beautiful HTML dashboard file."""
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
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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
            <div style="text-align: right;">
                <span class="status-badge active" style="background-color: #15803d;">AUTONOMOUS EXECUTION RUNNING</span>
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
                <div class="card-label">Risk Settings</div>
                <div class="card-val" style="font-size: 16px;">{config.RISK_PER_TRADE_PERCENT}% Risk | {config.MAX_DAILY_DRAWDOWN_PERCENT}% Daily Limit</div>
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
            with open("dashboard.html", "w") as f:
                f.write(html_content)
        except Exception as e:
            print(f"Warning: Failed to write dashboard.html: {e}")

    def tick_and_execute(self):
        """
        Runs one iteration of checking market state, assessing trades,
        updating open positions, and enforcing limits.
        """
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

        # C. Check Daily Drawdown Limit
        daily_loss = database.get_daily_profit(current_date)
        max_allowed_loss = self.daily_start_balance * (config.MAX_DAILY_DRAWDOWN_PERCENT / 100.0)

        if daily_loss < 0 and abs(daily_loss) >= max_allowed_loss:
            warn_msg = (
                f"⚠️ *Daily Drawdown Reached!* Today's loss of {abs(daily_loss):.2f} "
                f"exceeded maximum allowed of {max_allowed_loss:.2f} ({config.MAX_DAILY_DRAWDOWN_PERCENT}%). "
                f"Stopping new trades for today."
            )
            print(warn_msg.replace("*", ""))
            telegram_bot.send_telegram_message(warn_msg)
            return

        # D. Retrieve open positions from connection and synchronize with SQLite
        active_positions = self.conn.get_open_orders()
        open_db_trades = database.get_open_trades()

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
        print(f"\n⚡ [{timestamp_str}] --- COGNITIVE SCAN CYCLE ---")
        print(f"Equity: {current_equity:.2f} USD | Active Trades: {len(active_positions)}/{config.MAX_CONCURRENT_TRADES}")
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

        for symbol in config.SYMBOLS:
            # Fetch 210 candles of historical data (plenty for 200 EMA calculation)
            history = self.conn.get_history(symbol, 220)
            if not history:
                print(f"{symbol:<9} | No History Data Found. Please wait for terminal to synchronize.")
                # Draw status on chart
                scans_list.append({
                    "symbol": symbol,
                    "price": "-",
                    "ema200": "-",
                    "trend": "-",
                    "rsi": "-",
                    "atr": "-",
                    "status": "Syncing history..."
                })
                continue

            current_price = history[-1]['close']

            # Check if we already have an open trade on this exact symbol
            has_active_symbol = any(p['symbol'].upper() == symbol.upper() for p in active_positions)
            if has_active_symbol:
                trade_info = [p for p in active_positions if p['symbol'].upper() == symbol.upper()][0]
                print(f"{symbol:<9} | {current_price:<10.5f} | {'-':<10} | {'-':<5} | {'-':<6} | {'-':<8} | ACTIVE ({trade_info['direction']} ticket {trade_info['ticket']})")
                scans_list.append({
                    "symbol": symbol,
                    "price": f"{current_price:.5f}",
                    "ema200": "-",
                    "trend": "-",
                    "rsi": "-",
                    "atr": "-",
                    "status": f"ACTIVE ({trade_info['direction']} Ticket {trade_info['ticket']})"
                })
                continue

            # Get technical analysis and trading decision from the Brain
            analysis = self.brain.evaluate(symbol, history, current_equity)
            decision = analysis['decision']
            indicators_info = analysis.get('indicators', {})
            ema200 = indicators_info.get('ema_long', 0.0)
            rsi_val = indicators_info.get('rsi', 0.0)
            atr_val = indicators_info.get('atr', 0.0)
            trend_str = "UP" if current_price > ema200 else "DOWN"

            status_text = analysis['explanation']
            if not trading_available:
                status_text = "HOLD (MAX LIMIT OF ACTIVE TRADES REACHED)"
            elif decision in ['BUY', 'SELL']:
                status_text = f"Executing {decision}!"

            print(f"{symbol:<9} | {current_price:<10.5f} | {ema200:<10.5f} | {trend_str:<5} | {rsi_val:<6.2f} | {atr_val:<8.5f} | {status_text}")

            scans_list.append({
                "symbol": symbol,
                "price": f"{current_price:.5f}",
                "ema200": f"{ema200:.5f}",
                "trend": trend_str,
                "rsi": f"{rsi_val:.1f}",
                "atr": f"{atr_val:.5f}",
                "status": status_text
            })

            if decision in ['BUY', 'SELL'] and trading_available:
                # Execute order
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

                    # Update active positions list to prevent duplicate trades in the same tick loop
                    active_positions.append({
                        'ticket': res['ticket'],
                        'symbol': symbol,
                        'direction': decision,
                        'open_price': res['price'],
                        'sl': analysis['sl'],
                        'tp': analysis['tp'],
                        'lot_size': analysis['lot_size']
                    })
                    # Recheck available limit
                    trading_available = len(active_positions) < config.MAX_CONCURRENT_TRADES

        # Generate HTML Dashboard file with real and live data & indicators
        self._generate_html_dashboard(
            current_time=timestamp_str,
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
