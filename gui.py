import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading
import time
import datetime
import os
import config
import database
import main

class ScalperGui:
    """
    Stunning Dark-Themed Desktop GUI for the Autonomous Forex Scalper.
    Enables users to monitor balances, check scanner results, view indicator matrices,
    track running positions, toggle modes, and start/stop the autonomous bot smoothly.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Scalper Brain - Autonomous Trading System")
        self.root.geometry("1100x700")
        self.root.minsize(1000, 600)

        # Style configurations
        self.bg_dark = "#0f172a"
        self.bg_card = "#1e293b"
        self.fg_light = "#f1f5f9"
        self.fg_accent = "#38bdf8"
        self.fg_green = "#22c55e"
        self.fg_red = "#f43f5e"

        self.root.configure(bg=self.bg_dark)

        # Configure Tkinter Treeview/Widget Styles
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(".", background=self.bg_dark, foreground=self.fg_light, fieldbackground=self.bg_dark)
        self.style.configure("Treeview", background=self.bg_card, foreground=self.fg_light, fieldbackground=self.bg_card, bordercolor="#334155", borderwidth=1, rowheight=25)
        self.style.map("Treeview", background=[("selected", "#38bdf8")], foreground=[("selected", "#0f172a")])
        self.style.configure("Treeview.Heading", background="#0f172a", foreground=self.fg_accent, font=("Segoe UI", 10, "bold"), borderwidth=1)

        # Background Thread state
        self.scalper = None
        self.bot_thread = None
        self.running = False

        # Build UI layout
        self._build_header()
        self._build_stats_ribbon()
        self._build_main_split()
        self._build_controls_bar()

        # Initialize background visual update loop
        self.update_gui_loop()

    def _build_header(self):
        """Header Banner"""
        header_frame = tk.Frame(self.root, bg=self.bg_dark, pady=10, padx=20)
        header_frame.pack(fill=tk.X)

        title_label = tk.Label(
            header_frame,
            text="🤖 SCALPER BRAIN AUTONOMOUS SYSTEM",
            font=("Segoe UI Semibold", 18),
            bg=self.bg_dark,
            fg=self.fg_accent
        )
        title_label.pack(side=tk.LEFT)

        # Dynamic connection badge
        self.badge_text = tk.StringVar(value="SIMULATION ACTIVE" if config.SIMULATION_MODE else "MT5 CONNECTED")
        self.badge_label = tk.Label(
            header_frame,
            textvariable=self.badge_text,
            font=("Segoe UI", 9, "bold"),
            bg="#eab308" if config.SIMULATION_MODE else "#15803d",
            fg="#ffffff",
            padx=10,
            pady=3,
            relief=tk.FLAT
        )
        self.badge_label.pack(side=tk.RIGHT, pady=5)

    def _build_stats_ribbon(self):
        """Card grid displaying account statistics"""
        ribbon_frame = tk.Frame(self.root, bg=self.bg_dark, padx=20, pady=5)
        ribbon_frame.pack(fill=tk.X)

        # 1. Balance Card
        self.card_balance = self._create_card(ribbon_frame, "Account Balance", "$10,000.00 USD", 0)
        # 2. Equity Card
        self.card_equity = self._create_card(ribbon_frame, "Account Equity", "$10,000.00 USD", 1, value_color=self.fg_accent)
        # 3. Active Positions
        self.card_active = self._create_card(ribbon_frame, "Running Positions", "0 / 3", 2)
        # 4. Settings Card
        self.card_settings = self._create_card(ribbon_frame, "Risk Limit Settings", f"{config.RISK_PER_TRADE_PERCENT}% Risk / {config.MAX_DAILY_DRAWDOWN_PERCENT}% Stop", 3)

    def _create_card(self, parent, label_text, val_text, column, value_color=None):
        card = tk.Frame(parent, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#334155", highlightcolor="#334155")
        card.grid(row=0, column=column, padx=10, pady=5, sticky="ew")
        parent.columnconfigure(column, weight=1)

        lbl = tk.Label(card, text=label_text.upper(), font=("Segoe UI", 8, "bold"), bg=self.bg_card, fg="#94a3b8")
        lbl.pack(anchor="w", padx=15, pady=(10, 2))

        val_color = value_color if value_color else self.fg_light
        val = tk.Label(card, text=val_text, font=("Segoe UI Semibold", 16), bg=self.bg_card, fg=val_color)
        val.pack(anchor="w", padx=15, pady=(0, 10))
        return val

    def _build_main_split(self):
        """Middle container containing the scanning matrix list and status details"""
        split_frame = tk.Frame(self.root, bg=self.bg_dark, padx=20, pady=10)
        split_frame.pack(fill=tk.BOTH, expand=True)

        # Left Column: Symbols Grid Table
        left_pane = tk.Frame(split_frame, bg=self.bg_dark)
        left_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        lbl = tk.Label(left_pane, text="🔎 MULTI-ASSET COGNITIVE SCANS MATRIX", font=("Segoe UI", 10, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl.pack(anchor="w", pady=(0, 5))

        # Setup Scans Treeview Table
        cols = ("Symbol", "Price", "EMA-200", "Trend", "RSI", "ATR", "Status")
        self.tree = ttk.Treeview(left_pane, columns=cols, show="headings", style="Treeview")
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor=tk.W, width=110)
        # Give Status column extra space
        self.tree.column("Status", width=340)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbar for table
        sb = ttk.Scrollbar(left_pane, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

    def _build_controls_bar(self):
        """Action Buttons Controls Banner"""
        ctrl_frame = tk.Frame(self.root, bg=self.bg_card, height=60, bd=1, relief=tk.SOLID, highlightbackground="#334155")
        ctrl_frame.pack(fill=tk.X, side=tk.BOTTOM, ipady=10)

        # Start Bot Button
        self.btn_start = tk.Button(
            ctrl_frame,
            text="▶ START AUTONOMOUS TRADER",
            font=("Segoe UI", 10, "bold"),
            bg="#16a34a",
            fg="#ffffff",
            activebackground="#15803d",
            activeforeground="#ffffff",
            padx=15,
            pady=8,
            relief=tk.FLAT,
            command=self.start_bot
        )
        self.btn_start.pack(side=tk.LEFT, padx=(20, 10), pady=10)

        # Stop Bot Button (Initially disabled)
        self.btn_stop = tk.Button(
            ctrl_frame,
            text="🛑 STOP BOT",
            font=("Segoe UI", 10, "bold"),
            bg="#dc2626",
            fg="#ffffff",
            activebackground="#b91c1c",
            activeforeground="#ffffff",
            padx=15,
            pady=8,
            relief=tk.FLAT,
            state=tk.DISABLED,
            command=self.stop_bot
        )
        self.btn_stop.pack(side=tk.LEFT, padx=10, pady=10)

        # Strategy Selector label and dropdown list
        strat_lbl = tk.Label(ctrl_frame, text="STRATEGY:", font=("Segoe UI", 9, "bold"), bg=self.bg_card, fg="#94a3b8")
        strat_lbl.pack(side=tk.LEFT, padx=(20, 5), pady=15)

        self.strat_var = tk.StringVar(value=config.ACTIVE_STRATEGY)
        self.strat_menu = tk.OptionMenu(
            ctrl_frame,
            self.strat_var,
            "TREND_FOLLOWING",
            "MEAN_REVERSION",
            "MACD_MOMENTUM",
            "VOTING_ENSEMBLE",
            command=self.on_strategy_change
        )
        self.strat_menu.config(font=("Segoe UI", 9, "bold"), bg="#1e293b", fg=self.fg_accent, activebackground="#334155", relief=tk.FLAT, borderwidth=1, highlightthickness=0)
        self.strat_menu["menu"].config(bg="#1e293b", fg=self.fg_accent)
        self.strat_menu.pack(side=tk.LEFT, padx=5, pady=15)

        # Simulation Mode Toggle Button
        self.mode_text = tk.StringVar(value="SWITCH TO MT5 WINDOWS" if config.SIMULATION_MODE else "SWITCH TO SIMULATOR")
        self.btn_toggle_mode = tk.Button(
            ctrl_frame,
            textvariable=self.mode_text,
            font=("Segoe UI", 9, "bold"),
            bg="#475569",
            fg="#ffffff",
            activebackground="#334155",
            activeforeground="#ffffff",
            padx=15,
            pady=8,
            relief=tk.FLAT,
            command=self.toggle_mode
        )
        self.btn_toggle_mode.pack(side=tk.RIGHT, padx=20, pady=10)

        # Live clock / status label
        self.lbl_clock = tk.Label(
            ctrl_frame,
            text="Last update: Never",
            font=("Segoe UI", 9),
            bg=self.bg_card,
            fg="#64748b"
        )
        self.lbl_clock.pack(side=tk.RIGHT, padx=10, pady=15)

    def start_bot(self):
        """Spawns background threading to run the Autonomous Bot coordinator"""
        if self.running:
            return

        self.running = True
        self.btn_start.config(state=tk.DISABLED, bg="#1e293b")
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_toggle_mode.config(state=tk.DISABLED)

        # Create autonomous bot instance
        self.scalper = main.AutonomousScalper()

        # Thread function
        def thread_loop():
            if not self.scalper.start():
                self.running = False
                self.root.after(0, self.reset_buttons)
                return

            while self.running:
                try:
                    self.scalper.tick_and_execute()
                except Exception as e:
                    print(f"Error in execution tick: {e}")

                # Sleep interval
                for _ in range(config.CHECK_INTERVAL_SECONDS):
                    if not self.running:
                        break
                    time.sleep(1)

            self.scalper.stop()
            self.root.after(0, self.reset_buttons)

        self.bot_thread = threading.Thread(target=thread_loop, daemon=True)
        self.bot_thread.start()

    def stop_bot(self):
        """Stops the autonomous bot safely"""
        if not self.running:
            return
        self.running = False
        self.lbl_clock.config(text="Stopping bot...")
        self.btn_stop.config(state=tk.DISABLED)

    def reset_buttons(self):
        """Puts UI buttons back to normal"""
        self.btn_start.config(state=tk.NORMAL, bg="#16a34a")
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_toggle_mode.config(state=tk.NORMAL)
        self.lbl_clock.config(text="Bot stopped safely.")

    def on_strategy_change(self, selected_strat):
        """Fires when the user updates the strategy dropdown choice"""
        config.ACTIVE_STRATEGY = selected_strat
        print(f"🔄 GUI STRATEGY SWITCH: Active Trading Strategy updated to: {selected_strat}")

    def toggle_mode(self):
        """Switches between MT5 Windows live and paper trading simulation"""
        config.SIMULATION_MODE = not config.SIMULATION_MODE
        self.badge_text.set("SIMULATION ACTIVE" if config.SIMULATION_MODE else "MT5 CONNECTED")
        self.badge_label.config(bg="#eab308" if config.SIMULATION_MODE else "#15803d")
        self.mode_text.set("SWITCH TO MT5 WINDOWS" if config.SIMULATION_MODE else "SWITCH TO SIMULATOR")

        # Update settings display card
        self.card_settings.config(text=f"{config.RISK_PER_TRADE_PERCENT}% Risk / {config.MAX_DAILY_DRAWDOWN_PERCENT}% Stop")
        messagebox.showinfo("Mode Toggled", f"Successfully switched trading backend to: {'Simulation Paper Trading' if config.SIMULATION_MODE else 'MT5 Windows Native'}")

    def update_gui_loop(self):
        """Runs on main thread every 2 seconds to refresh cards and tree table values"""
        try:
            # Update metrics from chosen connector if initialized
            if self.scalper and self.scalper.conn:
                info = self.scalper.conn.get_account_info()
                self.card_balance.config(text=f"${info['balance']:,.2f} USD")
                self.card_equity.config(text=f"${info['equity']:,.2f} USD")

                active_positions = self.scalper.conn.get_open_orders()
                self.card_active.config(text=f"{len(active_positions)} / {config.MAX_CONCURRENT_TRADES}")

                # Fetch latest DB scan assessments to show in table
                self.tree.delete(*self.tree.get_children())

                # Query assessments logged recently
                conn = database.get_connection()
                cursor = conn.cursor()
                # Get the most recent assessment for each symbol
                cursor.execute("""
                    SELECT a1.symbol, a1.trend_direction, a1.rsi_val, a1.atr_val, a1.decision, a1.explanation, a1.timestamp
                    FROM assessments a1
                    INNER JOIN (
                        SELECT symbol, MAX(timestamp) as max_ts
                        FROM assessments
                        GROUP BY symbol
                    ) a2 ON a1.symbol = a2.symbol AND a1.timestamp = a2.max_ts
                    ORDER BY a1.symbol ASC
                """)
                rows = cursor.fetchall()
                conn.close()

                # Get active open positions symbols
                active_symbols = {p['symbol'].upper(): p for p in active_positions}

                for row in rows:
                    sym = row['symbol']
                    trend = row['trend_direction']
                    rsi = f"{row['rsi_val']:.2f}" if row['rsi_val'] is not None else "-"
                    atr = f"{row['atr_val']:.5f}" if row['atr_val'] is not None else "-"
                    status = row['explanation']

                    # Override status text if position is actively open
                    if sym in active_symbols:
                        pos = active_symbols[sym]
                        status = f"ACTIVE ({pos['direction']} - Ticket {pos['ticket']})"

                    # Lookup actual live tick price if available
                    price_info = self.scalper.conn.get_current_price(sym)
                    price = f"{price_info['ask']:.5f}" if price_info['ask'] > 0 else "-"

                    # Insert row
                    self.tree.insert("", tk.END, values=(sym, price, "-", trend, rsi, atr, status))

                self.lbl_clock.config(text=f"Last updated: {datetime.datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"Error updating GUI fields: {e}")

        # Cycle every 2 seconds
        self.root.after(2000, self.update_gui_loop)


def launch_gui():
    root = tk.Tk()
    app = ScalperGui(root)
    root.mainloop()

if __name__ == "__main__":
    launch_gui()
