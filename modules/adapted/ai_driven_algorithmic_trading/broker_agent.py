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


# =====================================================================
# BROKER AGENT: QUANTITATIVE PORTFOLIO EXECUTION & ACCUMULATION ENGINE
# =====================================================================
import json
import os


class InstitutionalBrokerAgent:
    def __init__(self, ledger_path: str = "data/output/live_portfolio_ledger.json"):
        self.ledger_path = ledger_path
        self.signals_path = "data/output/latest_market_signals.json"
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        self.portfolio = self._load_or_initialize_ledger()

    def _load_or_initialize_ledger(self) -> dict:
        """Loads the permanent trading ledger or sets up initial account variables."""
        if os.path.exists(self.ledger_path):
            try:
                with open(self.ledger_path) as f:
                    return json.load(f)
            except Exception:
                pass

        # Default structural seed configuration mapping
        return {
            "account_telemetry": {
                "initial_seed_capital": 100000.0,
                "available_cash": 100000.0,
                "total_portfolio_value": 100000.0,
                "total_closed_roi_pct": 0.0,
            },
            "active_positions": {},  # Format: {TICKER: {qty, entry_avg, tp1, tp2, trailing_floor, peak_close}}
            "closed_trades_history": [],
        }

    def generate_next_day_order_ticket(self):
        """
        Parses daily quantitative alerts and designs exact morning limit order tickets,
        volatility take-profit matrices, and capital protective stop floors.
        """
        print("\n=== STEP 1: INITIALIZING MORNING LIMIT ORDER TICKETS (9:05 AM IST) ===")
        if not os.path.exists(self.signals_path):
            print(" ✕ Aborted. Central signals cache file 'latest_market_signals.json' is missing.")
            return

        with open(self.signals_path) as f:
            scan_data = json.load(f)

        signals_list = scan_data.get("signals", [])
        buy_triggers = [s for s in signals_list if s.get("action_status") == "BUY"]

        if not buy_triggers:
            print(" ✓ No fresh BUY signal entries identified for this session.")
            return

        print(
            f" ✓ Identified {len(buy_triggers)} strategy candidates. Compiling bracket thresholds:"
        )

        for idx, asset in enumerate(buy_triggers, 1):
            ticker = asset.get("ticker", "N/A")
            close_price = asset.get("close_price", 0.0)
            shares_to_buy = asset.get("recommended_shares_to_buy", 0)

            # Extract target price structures from the signal variables
            tp1 = asset.get("take_profit_target_1", 0.0)
            tp2 = asset.get("take_profit_target_2", 0.0)
            initial_stop = asset.get("active_trailing_stop_floor", 0.0)

            # 🧮 APPLY 1% NEXT-DAY PULLBACK LIMIT ENTRY STRATEGY RULE
            calculated_limit_entry = close_price * 0.99

            print(f"\n   [Ticket #{idx}] ---- Asset Target: #{ticker} ----")
            print("   • Execution Type  : Buy Limit Order (Deploy at 9:15 AM)")
            print(f"   • Targeted Entry  : ₹{calculated_limit_entry:,.2f} (1% Pullback Anchor)")
            print(f"   • Position Sizing : Allocation of {shares_to_buy} shares")
            print(f"   • Take Profit 1   : ₹{tp1:,.2f} (50% Scalp Matrix Landmark)")
            print(f"   • Take Profit 2   : ₹{tp2:,.2f} (50% Runner Milestone Target)")
            print(f"   • Trailing Floor  : ₹{initial_stop:,.2f} (5% Fixed Peak Stop)")

    def update_portfolio_matrix_states(self, simulated_current_prices: dict = None):
        """
        Simulates execution updates by adjusting open positions, tracking price extensions,
        raising trailing stops, processing target exits, and updating the ledger.
        """
        print("\n=== STEP 2: PARSING PORTFOLIO MATRIX STATES & EXIT MARGINS ===")
        simulated_prices = simulated_current_prices or {}

        active_positions = self.portfolio["active_positions"]
        cash = self.portfolio["account_telemetry"]["available_cash"]

        # 1. Evaluate open active holdings against stop-loss and take-profit milestones
        tickers_to_liquidate = []

        for ticker, data in list(active_positions.items()):
            # Fallback to entry price if no fresh simulation tick is supplied
            current_tick = float(simulated_prices.get(ticker, data["entry_avg"]))

            # Update tracked peak close values dynamically
            if current_tick > data["peak_close"]:
                data["peak_close"] = current_tick
                # Automatically trail your defensive floor upward by 5% from the new peak close
                data["trailing_floor"] = current_tick * 0.95
                print(
                    f" 📈 #{ticker} reached a new peak high of ₹{current_tick:,.2f}. Trailing stop floor raised to ₹{data['trailing_floor']:,.2f}."
                )

            # Check if the trailing stop floor was violated
            if current_tick <= data["trailing_floor"]:
                print(
                    f" 🚨 #{ticker} breached trailing stop floor of ₹{data['trailing_floor']:,.2f} at current price ₹{current_tick:,.2f}. Forcing liquidation..."
                )
                cash += data["qty"] * current_tick
                tickers_to_liquidate.append(ticker)
                self.portfolio["closed_trades_history"].append(
                    {
                        "ticker": ticker,
                        "status": "STOP_LOSS_HIT",
                        "roi_pct": ((current_tick - data["entry_avg"]) / data["entry_avg"]) * 100,
                    }
                )

            # Check if Take-Profit targets were reached
            elif current_tick >= data["tp2"]:
                print(
                    f" 🎯 #{ticker} achieved max Take Profit 2 target of ₹{data['tp2']:,.2f}. Closing out remaining shares..."
                )
                cash += data["qty"] * current_tick
                tickers_to_liquidate.append(ticker)
                self.portfolio["closed_trades_history"].append(
                    {
                        "ticker": ticker,
                        "status": "TP2_RUNNER_HIT",
                        "roi_pct": ((data["tp2"] - data["entry_avg"]) / data["entry_avg"]) * 100,
                    }
                )

        for ticker in tickers_to_liquidate:
            del active_positions[ticker]

        # 2. Simulate new entries from the latest signals JSON
        if os.path.exists(self.signals_path):
            with open(self.signals_path) as f:
                scan_data = json.load(f)

            for asset in scan_data.get("signals", []):
                ticker = asset.get("ticker", "N/A")
                if asset.get("action_status") == "BUY" and ticker not in active_positions:
                    close_price = asset.get("close_price", 0.0)
                    limit_entry = close_price * 0.99
                    shares_to_buy = asset.get("recommended_shares_to_buy", 0)
                    capital_required = shares_to_buy * limit_entry

                    if cash >= capital_required and shares_to_buy > 0:
                        cash -= capital_required
                        active_positions[ticker] = {
                            "qty": shares_to_buy,
                            "entry_avg": limit_entry,
                            "tp1": asset.get("take_profit_target_1", 0.0),
                            "tp2": asset.get("take_profit_target_2", 0.0),
                            "trailing_floor": asset.get("active_trailing_stop_floor", 0.0),
                            "peak_close": limit_entry,
                            "sector": asset.get("sector", "Other Diversified"),
                        }
                        print(
                            f" 🛒 Simulated Buy Execution filled for #{ticker}: {shares_to_buy} shares at entry cost ₹{limit_entry:,.2f}."
                        )

        # 3. Synchronize account balances and cache updates
        self.portfolio["account_telemetry"]["available_cash"] = cash
        self._calculate_total_net_worth(simulated_prices)
        self._save_ledger()

    def _calculate_total_net_worth(self, simulated_prices: dict):
        """Calculates total account equity value across cash and liquid asset values."""
        cash = self.portfolio["account_telemetry"]["available_cash"]
        holdings_value = 0.0

        for ticker, data in self.portfolio["active_positions"].items():
            current_tick = float(simulated_prices.get(ticker, data["entry_avg"]))
            holdings_value += data["qty"] * current_tick

        total_value = cash + holdings_value
        self.portfolio["account_telemetry"]["total_portfolio_value"] = total_value

        initial = self.portfolio["account_telemetry"]["initial_seed_capital"]
        self.portfolio["account_telemetry"]["total_closed_roi_pct"] = (
            (total_value - initial) / initial
        ) * 100

    def generate_institutional_summary_report(self):
        print("=================================================================")
        print("⚡ INSTITUTIONAL PORTFOLIO PERFORMANCE SUMMARY LEAF")
        print("=================================================================")
        telemetry = self.portfolio["account_telemetry"]
        print(f" • Account Initial Capital Base : ₹{telemetry['initial_seed_capital']:,.2f}")
        print(f" • Current Liquid Idle Cash Foot: ₹{telemetry['available_cash']:,.2f}")
        print(f" • Total Portfolio Net Worth    : ₹{telemetry['total_portfolio_value']:,.2f}")
        print(f" • Strategy Performance Net ROI : {telemetry['total_closed_roi_pct']:+.2f}%")
        print("-----------------------------------------------------------------")

        active_positions = self.portfolio["active_positions"]
        print(f" 📋 ACTIVE HOLDINGS MONITOR MATRIX ({len(active_positions)} Assets Live):")
        if not active_positions:
            print("   [Empty Ledger - No current active stock positions held]")
        else:
            for ticker, details in active_positions.items():
                print(
                    f"   📈 Ticker: #{ticker.ljust(10)} | Qty: {str(details['qty']).ljust(5)} | Avg Entry: ₹{details['entry_avg']:,.2f} | Current Stop Floor: ₹{details['trailing_floor']:,.2f}"
                )

        print("=================================================================\n")

    # 🟢 FIXED: Aligned perfectly to the class tier margin level
    def _save_ledger(self):
        with open(self.ledger_path, "w") as f:
            json.dump(self.portfolio, f, indent=4)


# =====================================================================ENGINE DRIVER TERMINAL EXECUTION FRAME=====================================================================

# 🟢 To this exact syntax block structure:
if __name__ == "__main__":
    agent = InstitutionalBrokerAgent()

    # 1. Design morning limit order tickets from scanning signals
    agent.generate_next_day_order_ticket()

    # 2. Process portfolio adjustments and updates
    agent.update_portfolio_matrix_states(simulated_current_prices=None)

    # 3. Print the comprehensive account metrics report
    agent.generate_institutional_summary_report()
