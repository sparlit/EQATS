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
        print(f"{'Symbol':<9} | {'Price':<10} | {'EMA-200':<10} | {'Trend':<5} | {'RSI':<6} | {'ATR':<8} | {'Status':<15}")
        print("-" * 80)

        # Draw visual dashboards inside MT5 terminal (or simulated logs)
        dashboard_data = {
            "time": timestamp_str,
            "equity": current_equity,
            "balance": current_balance,
            "active_count": len(active_positions)
        }

        # Don't place new trades if we already reached our total max limit of simultaneous positions
        trading_available = len(active_positions) < config.MAX_CONCURRENT_TRADES

        for symbol in config.SYMBOLS:
            # Fetch 210 candles of historical data (plenty for 200 EMA calculation)
            history = self.conn.get_history(symbol, 220)
            if not history:
                print(f"{symbol:<9} | No History Data Found. Please wait for terminal to synchronize.")
                # Draw status on chart
                self.conn.draw_dashboard(symbol, {**dashboard_data, "status": "Waiting for Data", "detail": "Syncing history..."})
                continue

            current_price = history[-1]['close']

            # Check if we already have an open trade on this exact symbol
            has_active_symbol = any(p['symbol'].upper() == symbol.upper() for p in active_positions)
            if has_active_symbol:
                trade_info = [p for p in active_positions if p['symbol'].upper() == symbol.upper()][0]
                print(f"{symbol:<9} | {current_price:<10.5f} | {'-':<10} | {'-':<5} | {'-':<6} | {'-':<8} | ACTIVE ({trade_info['direction']} ticket {trade_info['ticket']})")
                self.conn.draw_dashboard(symbol, {**dashboard_data, "status": f"ACTIVE {trade_info['direction']}", "detail": f"Ticket: {trade_info['ticket']} | SL: {trade_info['sl']} | TP: {trade_info['tp']}"})
                continue

            # Get technical analysis and trading decision from the Brain
            analysis = self.brain.evaluate(symbol, history, current_equity)
            decision = analysis['decision']
            indicators_info = analysis.get('indicators', {})
            ema200 = indicators_info.get('ema_long', 0.0)
            rsi_val = indicators_info.get('rsi', 0.0)
            atr_val = indicators_info.get('atr', 0.0)
            trend_str = "UP" if current_price > ema200 else "DOWN"

            status_text = "HOLD"
            if not trading_available:
                status_text = "HOLD (MAX LIMIT)"
            elif decision in ['BUY', 'SELL']:
                status_text = f"EXECUTING {decision}"

            print(f"{symbol:<9} | {current_price:<10.5f} | {ema200:<10.5f} | {trend_str:<5} | {rsi_val:<6.2f} | {atr_val:<8.5f} | {status_text}")

            # Send latest indicators to responsive MT5 chart labels
            self.conn.draw_dashboard(symbol, {
                **dashboard_data,
                "status": f"SCANNING | Trend: {trend_str}",
                "detail": f"RSI: {rsi_val:.1f} | ATR: {atr_val:.5f} | Signal: {decision}"
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

        print("-" * 80)


if __name__ == "__main__":
    scalper = AutonomousScalper()
    if scalper.start():
        try:
            while True:
                scalper.tick_and_execute()
                time.sleep(config.CHECK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            scalper.stop()
