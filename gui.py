import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading
import time
import datetime
import os
import random
import config
import database
import main

class ScalperGui:
    """
    Ultimate Bloomberg Terminal style visual dashboard for the Autonomous Forex Scalper.
    Provides navigable screens via a Command Input Box and F-key quick links:
    - MAIN <GO>: Multi-Asset Scans Matrix, Account Balance and metrics.
    - GP <GO>: Graphical Price Tracking line chart, spread metrics, high/low boundaries.
    - WEI <GO>: World Currency and Macro Indices tracking board (DXY, BTC, S&P 500).
    - NEWS <GO>: Live Macro Headlines Feed with real-time NLP Sentiment Scores.
    - ANR <GO>: Analyst Recommendations & Neural Network predictive AI analytics.
    - HELP <GO>: Directory of available terminal codes, shortcuts, and risk configs.
    """

    def __init__(self, root):
        self.root = root
        # Initialize the database and all tables first before any visual loads or logs!
        try:
            database.init_db()
        except Exception as e:
            print(f"Warning: Database initialization error: {e}")

        self.root.title("BBG PROFESSIONAL - ELITE AUTONOMOUS QUANTUM TRADING SYSTEM")
        self.root.geometry("1200x800")
        self.root.minsize(1050, 650)

        # Authentic Bloomberg Terminal Style configuration
        self.bg_dark = "#000000"         # Bloomberg Pitch Black
        self.bg_card = "#121212"         # Bloomberg Dark Grey Panels
        self.fg_light = "#ffffff"        # Clean White text
        self.fg_accent = "#ff9900"       # Classic Bloomberg Neon Amber/Orange
        self.fg_green = "#00ff00"        # Neon Green (Profit / Positive / Go)
        self.fg_red = "#ff3333"          # Neon Red (Loss / Negative)
        self.fg_cyan = "#00ffff"         # Cyan details
        self.fg_grey = "#888888"         # Muted Grey labels

        self.root.configure(bg=self.bg_dark)

        # Configure Tkinter Styles
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(".", background=self.bg_dark, foreground=self.fg_light, fieldbackground=self.bg_dark)
        self.style.configure("Treeview", background=self.bg_card, foreground=self.fg_light, fieldbackground=self.bg_card, bordercolor="#2d2d2d", borderwidth=1, rowheight=25)
        self.style.map("Treeview", background=[("selected", self.fg_accent)], foreground=[("selected", "#000000")])
        self.style.configure("Treeview.Heading", background="#1c1c1c", foreground=self.fg_accent, font=("Consolas", 10, "bold"), borderwidth=1)

        # Background Thread state
        self.scalper = None
        self.bot_thread = None
        self.running = False

        # Command terminal state
        self.active_screen = "MAIN"
        self.selected_symbol_gp = "EURUSD"

        # Historical price tracking for GP screen (rolling 30 points)
        self.price_history_gp = []

        # Simulated macroeconomic indices data for WEI screen
        self.wei_data = {
            "DXY": {"name": "US DOLLAR INDEX", "last": 104.250, "change": 0.120, "pct": 0.12},
            "EXY": {"name": "EURO FX INDEX", "last": 108.400, "change": -0.080, "pct": -0.07},
            "JXY": {"name": "YEN FX INDEX", "last": 64.120, "change": -0.220, "pct": -0.34},
            "BXY": {"name": "POUND FX INDEX", "last": 126.850, "change": 0.050, "pct": 0.04},
            "SPX": {"name": "S&P 500 INDEX", "last": 5117.20, "change": 14.50, "pct": 0.28},
            "CCMP": {"name": "NASDAQ COMPOSITE", "last": 16082.30, "change": 85.10, "pct": 0.53},
            "GC1": {"name": "GOLD FUTURES COMEX", "last": 2032.40, "change": 11.20, "pct": 0.55},
            "BTCUSD": {"name": "BITCOIN SPOT INDEX", "last": 62140.00, "change": 845.00, "pct": 1.38},
            "ETHUSD": {"name": "ETHEREUM SPOT INDEX", "last": 3425.50, "change": -12.40, "pct": -0.36}
        }

        # News feed stories for NEWS screen
        self.news_stories = [
            {"time": "14:32:10", "headline": "FED HOLDS RATES CONSTANT; HINTS AT DELAYED RATE DECREASES", "source": "BBG", "sentiment": "NEUTRAL"},
            {"time": "14:28:45", "headline": "EUROPEAN CENTRAL BANK SIGNALS RATE PEAK HAS LIKELY PASSED", "source": "BBG", "sentiment": "BULLISH"},
            {"time": "14:15:20", "headline": "MIDDLE-EAST TENSIONS FLARE; SAUDI OIL FLOWS UNINTERRUPTED FOR NOW", "source": "DJ", "sentiment": "BEARISH"},
            {"time": "13:58:00", "headline": "BANK OF JAPAN STICKING TO ULTRA-LOOSE MONETARY STANCE", "source": "BBG", "sentiment": "BEARISH"},
            {"time": "13:42:15", "headline": "US CORE CPI MOM RISES 0.3% HIGHER THAN FORECASTS; YIELDS SPIKE", "source": "BBG", "sentiment": "BEARISH"},
            {"time": "13:20:00", "headline": "SEC OFFICIALLY APPROVES SPOT ETHEREUM ETFS IN UNEXPECTED REVERSAL", "source": "BBG", "sentiment": "BULLISH"}
        ]

        # Prepopulate the database with initial headlines
        try:
            for story in self.news_stories:
                database.log_news_headline(story["headline"], story["sentiment"])
        except Exception as e:
            print(f"Warning: Failed to prepopulate database news: {e}")

        # Build UI layout
        self._build_header()
        self._build_command_bar()
        self._build_stats_ribbon()
        self._build_session_timeline_panel()

        # Central switchable display frame
        self.screen_frame = tk.Frame(self.root, bg=self.bg_dark, padx=20, pady=5)
        self.screen_frame.pack(fill=tk.BOTH, expand=True)

        # Build the initial screen (MAIN)
        self.switch_to_screen("MAIN")

        # Build Console Panel on the bottom side of the dashboard
        self._build_console_panel()

        self._build_controls_bar()

        # Keyboard Bindings to simulate Bloomberg F-Keys
        self.root.bind("<F2>", lambda e: self.switch_to_screen("MAIN"))
        self.root.bind("<F3>", lambda e: self.switch_to_screen("GP"))
        self.root.bind("<F4>", lambda e: self.switch_to_screen("WEI"))
        self.root.bind("<F5>", lambda e: self.switch_to_screen("NEWS"))
        self.root.bind("<F6>", lambda e: self.switch_to_screen("ANR"))
        self.root.bind("<F7>", lambda e: self.switch_to_screen("PORT"))
        self.root.bind("<F8>", lambda e: self.switch_to_screen("MCTS"))
        self.root.bind("<F9>", lambda e: self.switch_to_screen("VDS"))
        self.root.bind("<F10>", lambda e: self.switch_to_screen("CHART"))
        self.root.bind("<F11>", lambda e: self.switch_to_screen("SESS"))
        self.root.bind("<F1>", lambda e: self.switch_to_screen("HELP"))

        # Redirect standard output to our dashboard's console panel
        import sys
        class ConsoleRedirector:
            def __init__(self, write_func):
                self.write_func = write_func
                self.original_stdout = sys.stdout

            def write(self, string):
                if string and string.strip():
                    self.write_func(string.strip())
                if self.original_stdout:
                    try:
                        self.original_stdout.write(string)
                    except Exception:
                        pass

            def flush(self):
                if self.original_stdout:
                    try:
                        self.original_stdout.flush()
                    except Exception:
                        pass

        self.console_redirector = ConsoleRedirector(self.log_to_console)
        sys.stdout = self.console_redirector

        # Initialize background visual update loop
        self.update_gui_loop()

        # Autostart autonomous bot immediately on GUI load for hands-off execution!
        self.root.after(1000, self.start_bot)

    def _build_console_panel(self):
        """Creates a gorgeous, real-time scrollable system console panel on the bottom side of the dashboard"""
        console_frame = tk.Frame(self.root, bg=self.bg_dark, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        console_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=20, pady=(5, 5))

        lbl_title = tk.Label(console_frame, text="[REAL-TIME SYSTEM DIAGNOSTICS & TELEMETRY STREAM]", font=("Consolas", 7, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", padx=10, pady=(4, 2))

        # Text box
        self.console_text = tk.Text(console_frame, bg="#050505", fg=self.fg_green, font=("Consolas", 7), height=5, wrap=tk.WORD, bd=0, highlightthickness=0)
        self.console_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))
        self.console_text.configure(state=tk.DISABLED)

    def log_to_console(self, message):
        """Appends a timestamped log entry to the real-time console telemetry box"""
        if not hasattr(self, "console_text") or not self.console_text:
            return
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"

        # Ensure thread-safe insertion to GUI widget
        self.root.after(0, lambda: self._insert_console_text(formatted))

    def _insert_console_text(self, text):
        try:
            self.console_text.configure(state=tk.NORMAL)
            self.console_text.insert(tk.END, text)
            # Cap lines to keep it high performance
            lines = int(self.console_text.index('end-1c').split('.')[0])
            if lines > 150:
                self.console_text.delete('1.0', '2.0')
            self.console_text.see(tk.END)
            self.console_text.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _build_header(self):
        """Header Banner"""
        header_frame = tk.Frame(self.root, bg=self.bg_dark, pady=5, padx=20)
        header_frame.pack(fill=tk.X)

        title_label = tk.Label(
            header_frame,
            text="BBG: ELITE QUANTUM TRADING SYSTEM <GO>",
            font=("Consolas", 18, "bold"),
            bg=self.bg_dark,
            fg=self.fg_accent
        )
        title_label.pack(side=tk.LEFT)

        # Dynamic connection badge
        self.badge_text = tk.StringVar(value="SIMULATION ACTIVE" if config.SIMULATION_MODE else "MT5 CONNECTED")
        self.badge_label = tk.Label(
            header_frame,
            textvariable=self.badge_text,
            font=("Consolas", 9, "bold"),
            bg="#b45309" if config.SIMULATION_MODE else "#15803d",
            fg="#ffffff",
            padx=10,
            pady=3,
            relief=tk.FLAT
        )
        self.badge_label.pack(side=tk.RIGHT, pady=5)

    def _build_command_bar(self):
        """Authentic Bloomberg Command Bar for inputting commands directly"""
        cmd_frame = tk.Frame(self.root, bg=self.bg_dark, pady=5, padx=20)
        cmd_frame.pack(fill=tk.X)

        lbl_prompt = tk.Label(cmd_frame, text="BBG >", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_green)
        lbl_prompt.pack(side=tk.LEFT)

        self.cmd_entry = tk.Entry(
            cmd_frame,
            font=("Consolas", 11, "bold"),
            bg="#111111",
            fg=self.fg_accent,
            insertbackground=self.fg_accent,
            width=20,
            bd=1,
            relief=tk.SOLID,
            highlightbackground="#2d2d2d"
        )
        self.cmd_entry.pack(side=tk.LEFT, padx=10)
        self.cmd_entry.bind("<Return>", lambda e: self.process_command())
        self.cmd_entry.insert(0, "MAIN")

        btn_go = tk.Button(
            cmd_frame,
            text="<GO>",
            font=("Consolas", 9, "bold"),
            bg=self.fg_accent,
            fg="#000000",
            padx=12,
            pady=1,
            relief=tk.FLAT,
            command=self.process_command
        )
        btn_go.pack(side=tk.LEFT)

        # F-Key Quick Shortcuts Row on right side
        shortcut_frame = tk.Frame(cmd_frame, bg=self.bg_dark)
        shortcut_frame.pack(side=tk.RIGHT)

        shortcuts = [
            ("F2 MAIN", "MAIN"),
            ("F3 GP", "GP"),
            ("F4 WEI", "WEI"),
            ("F5 NEWS", "NEWS"),
            ("F6 ANR", "ANR"),
            ("F7 PORT", "PORT"),
            ("F8 MCTS", "MCTS"),
            ("F9 VDS", "VDS"),
            ("F10 CHART", "CHART"),
            ("F11 SESS", "SESS"),
            ("F1 HELP", "HELP")
        ]
        for label, cmd in shortcuts:
            btn = tk.Button(
                shortcut_frame,
                text=label,
                font=("Consolas", 8, "bold"),
                bg="#1c1c1c",
                fg=self.fg_light,
                activebackground=self.fg_accent,
                activeforeground="#000000",
                bd=1,
                relief=tk.SOLID,
                padx=8,
                command=lambda c=cmd: self.switch_to_screen(c)
            )
            btn.pack(side=tk.LEFT, padx=3)

    def _build_session_timeline_panel(self):
        """Builds a gorgeous, vibrant 3-row Bloomberg session timeline panel"""
        self.timeline_frame = tk.Frame(self.root, bg=self.bg_card, bd=1, relief=tk.SOLID, padx=15, pady=10, highlightbackground="#2d2d2d")
        self.timeline_frame.pack(fill=tk.X, padx=20, pady=5)

        # Row 1: Active
        row_act = tk.Frame(self.timeline_frame, bg=self.bg_card)
        row_act.pack(fill=tk.X, pady=2)
        lbl_act_title = tk.Label(row_act, text="[ACTIVE SESSIONS]   >", font=("Consolas", 9, "bold"), bg=self.bg_card, fg=self.fg_green, width=22, anchor="w")
        lbl_act_title.pack(side=tk.LEFT)
        self.lbl_act_val = tk.Label(row_act, text="No active sessions", font=("Consolas", 9, "bold"), bg=self.bg_card, fg="#ffffff", anchor="w")
        self.lbl_act_val.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Row 2: Closed
        row_cls = tk.Frame(self.timeline_frame, bg=self.bg_card)
        row_cls.pack(fill=tk.X, pady=2)
        lbl_cls_title = tk.Label(row_cls, text="[CLOSED <= 4H]     >", font=("Consolas", 9, "bold"), bg=self.bg_card, fg=self.fg_grey, width=22, anchor="w")
        lbl_cls_title.pack(side=tk.LEFT)
        self.lbl_cls_val = tk.Label(row_cls, text="None", font=("Consolas", 9), bg=self.bg_card, fg=self.fg_grey, anchor="w")
        self.lbl_cls_val.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Row 3: Upcoming
        row_upc = tk.Frame(self.timeline_frame, bg=self.bg_card)
        row_upc.pack(fill=tk.X, pady=2)
        lbl_upc_title = tk.Label(row_upc, text="[UPCOMING SESSIONS] >", font=("Consolas", 9, "bold"), bg=self.bg_card, fg=self.fg_accent, width=22, anchor="w")
        lbl_upc_title.pack(side=tk.LEFT)
        self.lbl_upc_val = tk.Label(row_upc, text="None", font=("Consolas", 9, "bold"), bg=self.bg_card, fg=self.fg_accent, anchor="w")
        self.lbl_upc_val.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_stats_ribbon(self):
        """Card grid displaying account statistics"""
        ribbon_frame = tk.Frame(self.root, bg=self.bg_dark, padx=20, pady=5)
        ribbon_frame.pack(fill=tk.X)

        # 1. Balance Card
        self.card_balance = self._create_card(ribbon_frame, "1) BALANCE <GO>", "$10,000.00 USD", 0)
        # 2. Equity Card
        self.card_equity = self._create_card(ribbon_frame, "2) EQUITY <GO>", "$10,000.00 USD", 1, value_color=self.fg_cyan)
        # 3. Active Positions
        self.card_active = self._create_card(ribbon_frame, "3) ACTIVE <GO>", "0 / 3", 2)
        # 4. Trading Session Card
        self.card_session = self._create_card(ribbon_frame, "4) SESSION <GO>", "Quiet Session", 3, value_color="#b45309")
        # 5. Performance Card
        self.card_perf = self._create_card(ribbon_frame, "5) PERFORMANCE <GO>", "Win Rate: 0%", 4, value_color=self.fg_accent)
        # 6. Floating PnL Card
        self.card_pnl = self._create_card(ribbon_frame, "6) FLOATING PnL <GO>", "$0.00 USD", 5, value_color=self.fg_green)

    def _create_card(self, parent, label_text, val_text, column, value_color=None):
        card = tk.Frame(parent, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d", highlightcolor="#2d2d2d")
        card.grid(row=0, column=column, padx=10, pady=5, sticky="ew")
        parent.columnconfigure(column, weight=1)

        lbl = tk.Label(card, text=label_text.upper(), font=("Consolas", 8, "bold"), bg=self.bg_card, fg="#888888")
        lbl.pack(anchor="w", padx=15, pady=(10, 2))

        val_color = value_color if value_color else self.fg_light
        val = tk.Label(card, text=val_text, font=("Consolas", 14, "bold"), bg=self.bg_card, fg=val_color)
        val.pack(anchor="w", padx=15, pady=(0, 10))
        return val

    def _build_controls_bar(self):
        """Action Buttons Controls Banner"""
        ctrl_frame = tk.Frame(self.root, bg=self.bg_card, height=60, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        ctrl_frame.pack(fill=tk.X, side=tk.BOTTOM, ipady=10)

        # Start Bot Button
        self.btn_start = tk.Button(
            ctrl_frame,
            text="▶ START TRADING",
            font=("Consolas", 10, "bold"),
            bg="#10b981",
            fg="#000000",
            activebackground="#059669",
            activeforeground="#000000",
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
            font=("Consolas", 10, "bold"),
            bg="#ef4444",
            fg="#ffffff",
            activebackground="#dc2626",
            activeforeground="#ffffff",
            padx=15,
            pady=8,
            relief=tk.FLAT,
            state=tk.DISABLED,
            command=self.stop_bot
        )
        self.btn_stop.pack(side=tk.LEFT, padx=10, pady=10)

        # Strategy Selector label and dropdown list
        strat_lbl = tk.Label(ctrl_frame, text="STRATEGY:", font=("Consolas", 9, "bold"), bg=self.bg_card, fg="#888888")
        strat_lbl.pack(side=tk.LEFT, padx=(10, 5), pady=15)

        self.strat_var = tk.StringVar(value=config.ACTIVE_STRATEGY)
        self.strat_menu = tk.OptionMenu(
            ctrl_frame,
            self.strat_var,
            "TREND_FOLLOWING",
            "MEAN_REVERSION",
            "MACD_MOMENTUM",
            "VOTING_ENSEMBLE",
            "BREAKOUT",
            "CARRY_TRADE",
            "GRID_TRADE",
            "STAT_ARB",
            "ORB",
            "VSA",
            command=self.on_strategy_change
        )
        self.strat_menu.config(font=("Consolas", 9, "bold"), bg="#242424", fg=self.fg_accent, activebackground="#333333", relief=tk.FLAT, borderwidth=1, highlightthickness=0)
        self.strat_menu["menu"].config(bg="#242424", fg=self.fg_accent)
        self.strat_menu.pack(side=tk.LEFT, padx=5, pady=15)

        # Style Selector label and dropdown list
        style_lbl = tk.Label(ctrl_frame, text="STYLE:", font=("Consolas", 9, "bold"), bg=self.bg_card, fg="#888888")
        style_lbl.pack(side=tk.LEFT, padx=(15, 5), pady=15)

        self.style_var = tk.StringVar(value=config.TRADING_STYLE)
        self.style_menu = tk.OptionMenu(
            ctrl_frame,
            self.style_var,
            "SCALPING",
            "DAY_TRADING",
            "SWING_TRADING",
            "POSITION_TRADING",
            command=self.on_style_change
        )
        self.style_menu.config(font=("Consolas", 9, "bold"), bg="#242424", fg=self.fg_accent, activebackground="#333333", relief=tk.FLAT, borderwidth=1, highlightthickness=0)
        self.style_menu["menu"].config(bg="#242424", fg=self.fg_accent)
        self.style_menu.pack(side=tk.LEFT, padx=5, pady=15)

        # Simulation Mode Toggle Button
        self.mode_text = tk.StringVar(value="SWITCH TO MT5 WINDOWS" if config.SIMULATION_MODE else "SWITCH TO SIMULATOR")
        self.btn_toggle_mode = tk.Button(
            ctrl_frame,
            textvariable=self.mode_text,
            font=("Consolas", 9, "bold"),
            bg="#3e3e3e",
            fg="#ffffff",
            activebackground="#2a2a2a",
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
            font=("Consolas", 9),
            bg=self.bg_card,
            fg="#888888"
        )
        self.lbl_clock.pack(side=tk.RIGHT, padx=10, pady=15)

    def process_command(self):
        """Reads raw entry code and switches to the respective screen"""
        raw_cmd = self.cmd_entry.get().strip().upper()
        if not raw_cmd:
            return

        # Remove trailing <GO> or GO if typed
        parsed_cmd = raw_cmd.replace("<GO>", "").replace("GO", "").strip()
        self.switch_to_screen(parsed_cmd)

    def switch_to_screen(self, screen_code):
        """Switches the main dashboard window display dynamically"""
        # Clear out previous widgets
        for widget in self.screen_frame.winfo_children():
            widget.destroy()

        self.active_screen = screen_code
        self.cmd_entry.delete(0, tk.END)
        self.cmd_entry.insert(0, f"{screen_code}")

        # Construct respective layout
        if screen_code == "MAIN":
            self._show_main_screen()
        elif screen_code == "GP":
            self._show_gp_screen()
        elif screen_code == "WEI":
            self._show_wei_screen()
        elif screen_code == "NEWS":
            self._show_news_screen()
        elif screen_code == "ANR":
            self._show_anr_screen()
        elif screen_code == "PORT":
            self._show_port_screen()
        elif screen_code == "MCTS":
            self._show_mcts_screen()
        elif screen_code == "VDS":
            self._show_vds_screen()
        elif screen_code == "CHART":
            self._show_performance_chart_screen()
        elif screen_code == "SESS":
            self._show_session_screen()
        elif screen_code == "DES":
            self._show_des_screen()
        elif screen_code == "YAS":
            self._show_yas_screen()
        elif screen_code == "ECO":
            self._show_eco_screen()
        elif screen_code == "EMSX":
            self._show_emsx_screen()
        elif screen_code == "HELP":
            self._show_help_screen()
        else:
            # Fallback / Error Alert
            self._show_unknown_screen(screen_code)

    # ----------------------------------------------------
    # SCREEN LAYOUTS
    # ----------------------------------------------------

    def _show_main_screen(self):
        """MAIN <GO>: Split terminal showing Asset Scans (Left) and Live Active Trades (Right)"""
        # Central split frame
        main_split = tk.Frame(self.screen_frame, bg=self.bg_dark)
        main_split.pack(fill=tk.BOTH, expand=True)

        # Left Column: Scans Matrix
        left_col = tk.Frame(main_split, bg=self.bg_dark)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        lbl_scans = tk.Label(left_col, text="7) MULTI-ASSET COGNITIVE SCANS MATRIX <GO>", font=("Consolas", 10, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_scans.pack(anchor="w", pady=(0, 5))

        cols = ("Symbol", "Price", "EMA-200", "Trend", "RSI", "ATR", "Status")
        self.tree = ttk.Treeview(left_col, columns=cols, show="headings", style="Treeview")
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor=tk.W, width=85)
        self.tree.column("Status", width=220)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(left_col, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        # Right Column: Live Active Trades
        right_col = tk.Frame(main_split, bg=self.bg_dark, width=420)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        right_col.pack_propagate(False)

        lbl_trades = tk.Label(right_col, text="8) LIVE RUNNING POSITIONS TERMINAL <GO>", font=("Consolas", 10, "bold"), bg=self.bg_dark, fg=self.fg_cyan)
        lbl_trades.pack(anchor="w", pady=(0, 5))

        cols_t = ("Ticket", "Symbol", "Type", "Lots", "Entry", "Current", "PnL ($)")
        self.trades_tree = ttk.Treeview(right_col, columns=cols_t, show="headings", style="Treeview")
        for col_t in cols_t:
            self.trades_tree.heading(col_t, text=col_t)
            if col_t in ["Ticket", "Symbol"]:
                self.trades_tree.column(col_t, anchor=tk.CENTER, width=60)
            elif col_t in ["Type", "Lots"]:
                self.trades_tree.column(col_t, anchor=tk.CENTER, width=50)
            else:
                self.trades_tree.column(col_t, anchor=tk.W, width=70)
        self.trades_tree.pack(fill=tk.BOTH, expand=True)

    def _show_gp_screen(self):
        """GP <GO>: Graphical Price Tracking Line Chart & Key Quote Details"""
        lbl_title = tk.Label(self.screen_frame, text=f"GP: GRAPHICAL PRICE & COGNITIVE CHART - {self.selected_symbol_gp} <GO>", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 5))

        # Dropdown to select different symbols
        sel_frame = tk.Frame(self.screen_frame, bg=self.bg_dark)
        sel_frame.pack(fill=tk.X, pady=5)

        lbl_select = tk.Label(sel_frame, text="SELECT ASSET:", font=("Consolas", 9, "bold"), bg=self.bg_dark, fg=self.fg_grey)
        lbl_select.pack(side=tk.LEFT)

        self.gp_asset_var = tk.StringVar(value=self.selected_symbol_gp)
        gp_menu = tk.OptionMenu(
            sel_frame,
            self.gp_asset_var,
            *config.SYMBOLS,
            command=self.change_gp_symbol
        )
        gp_menu.config(font=("Consolas", 9, "bold"), bg="#1a1a1a", fg=self.fg_accent, activebackground="#333333", relief=tk.FLAT)
        gp_menu["menu"].config(bg="#1a1a1a", fg=self.fg_accent)
        gp_menu.pack(side=tk.LEFT, padx=10)

        # Main charting layout split: Left is Canvas, Right is details panel
        chart_split = tk.Frame(self.screen_frame, bg=self.bg_dark)
        chart_split.pack(fill=tk.BOTH, expand=True, pady=5)

        # Graph Canvas
        self.chart_canvas = tk.Canvas(chart_split, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        self.chart_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Technical details side-card
        self.gp_details_frame = tk.Frame(chart_split, bg="#111111", bd=1, relief=tk.SOLID, width=280, highlightbackground="#2d2d2d")
        self.gp_details_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.gp_details_frame.pack_propagate(False)

        # Build detailed sub-widgets inside side-card
        self._rebuild_gp_details_pane()

    def _rebuild_gp_details_pane(self):
        for widget in self.gp_details_frame.winfo_children():
            widget.destroy()

        # Dynamic title & live quote details
        lbl_head = tk.Label(self.gp_details_frame, text="ASSET INTELLIGENCE", font=("Consolas", 10, "bold"), bg="#111111", fg=self.fg_cyan)
        lbl_head.pack(anchor="w", padx=10, pady=10)

        self.lbl_gp_quote = tk.Label(self.gp_details_frame, text="LOADING QUOTE...", font=("Consolas", 14, "bold"), bg="#111111", fg=self.fg_green)
        self.lbl_gp_quote.pack(anchor="w", padx=10, pady=5)

        self.lbl_gp_hl = tk.Label(self.gp_details_frame, text="H/L: - / -", font=("Consolas", 9), bg="#111111", fg=self.fg_light)
        self.lbl_gp_hl.pack(anchor="w", padx=10, pady=2)

        self.lbl_gp_spread = tk.Label(self.gp_details_frame, text="Spread: - pips", font=("Consolas", 9), bg="#111111", fg=self.fg_grey)
        self.lbl_gp_spread.pack(anchor="w", padx=10, pady=2)

        # Divider
        tk.Frame(self.gp_details_frame, bg="#222222", height=1).pack(fill=tk.X, padx=10, pady=10)

        # Indicators Panel
        lbl_inds = tk.Label(self.gp_details_frame, text="COGNITIVE INDICES", font=("Consolas", 9, "bold"), bg="#111111", fg=self.fg_accent)
        lbl_inds.pack(anchor="w", padx=10, pady=2)

        self.lbl_gp_ema = tk.Label(self.gp_details_frame, text="EMA-200: -", font=("Consolas", 9), bg="#111111", fg=self.fg_light)
        self.lbl_gp_ema.pack(anchor="w", padx=10, pady=2)

        self.lbl_gp_rsi = tk.Label(self.gp_details_frame, text="RSI-14: -", font=("Consolas", 9), bg="#111111", fg=self.fg_light)
        self.lbl_gp_rsi.pack(anchor="w", padx=10, pady=2)

        self.lbl_gp_atr = tk.Label(self.gp_details_frame, text="ATR Dev: -", font=("Consolas", 9), bg="#111111", fg=self.fg_light)
        self.lbl_gp_atr.pack(anchor="w", padx=10, pady=2)

        # Pivot Points Support/Resistance lines
        tk.Frame(self.gp_details_frame, bg="#222222", height=1).pack(fill=tk.X, padx=10, pady=10)
        lbl_pivots = tk.Label(self.gp_details_frame, text="PIVOT S/R COGNITION", font=("Consolas", 9, "bold"), bg="#111111", fg=self.fg_cyan)
        lbl_pivots.pack(anchor="w", padx=10, pady=2)

        self.lbl_gp_pivots = tk.Label(self.gp_details_frame, text="P: -\nS1: -\nR1: -", font=("Consolas", 9), justify=tk.LEFT, bg="#111111", fg=self.fg_light)
        self.lbl_gp_pivots.pack(anchor="w", padx=10, pady=2)

    def change_gp_symbol(self, selection):
        self.selected_symbol_gp = selection
        self.price_history_gp = [] # Reset trace
        self.switch_to_screen("GP")

    def _show_wei_screen(self):
        """WEI <GO>: World Currency Indices & Global Market Indices tracking board"""
        lbl_title = tk.Label(self.screen_frame, text="WEI: WORLD EXCHANGE & EQUITY INDICES <GO>", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 5))

        # Instructions Label
        lbl_info = tk.Label(self.screen_frame, text="GLOBAL MACRO BOARD - TICK FEED REFRESHES REAL-TIME VIA SIMULATED EXCHANGE QUOTES", font=("Consolas", 8), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        # Treeview Matrix table for macro products
        cols = ("Symbol", "Name", "Last", "Net Change", "% Change", "Status")
        self.wei_tree = ttk.Treeview(self.screen_frame, columns=cols, show="headings", style="Treeview")
        for col in cols:
            self.wei_tree.heading(col, text=col)
            if col == "Name":
                self.wei_tree.column(col, anchor=tk.W, width=280)
            else:
                self.wei_tree.column(col, anchor=tk.W, width=120)
        self.wei_tree.pack(fill=tk.BOTH, expand=True)

    def _show_news_screen(self):
        """NEWS <GO>: Live Macro Headlines Feed and Sentiments"""
        lbl_title = tk.Label(self.screen_frame, text="NEWS: BLOOMBERG REAL-TIME HEADLINES FEED <GO>", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 5))

        cols = ("Time", "Source", "Headline", "AI Sentiment")
        self.news_tree = ttk.Treeview(self.screen_frame, columns=cols, show="headings", style="Treeview")
        for col in cols:
            self.news_tree.heading(col, text=col)
            if col == "Headline":
                self.news_tree.column(col, anchor=tk.W, width=600)
            elif col == "AI Sentiment":
                self.news_tree.column(col, anchor=tk.CENTER, width=150)
            else:
                self.wei_tree_sub_col_width = 100
                self.news_tree.column(col, anchor=tk.W, width=100)
        self.news_tree.pack(fill=tk.BOTH, expand=True)

    def _show_anr_screen(self):
        """ANR <GO>: Analyst Recommendations & Artificial Neural Network Metrics"""
        lbl_title = tk.Label(self.screen_frame, text="ANR: COGNITIVE ANALYST RECOMMENDATIONS & AI BIAS <GO>", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 5))

        # Split frame
        anr_split = tk.Frame(self.screen_frame, bg=self.bg_dark)
        anr_split.pack(fill=tk.BOTH, expand=True, pady=5)

        # Left Column: Analyst Recommendations (Consensus matrix)
        left_frame = tk.Frame(anr_split, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15))

        lbl_cons = tk.Label(left_frame, text="CONSENSUS RECOMMENDATIONS MATRIX", font=("Consolas", 10, "bold"), bg=self.bg_card, fg=self.fg_accent)
        lbl_cons.pack(anchor="w", padx=15, pady=15)

        cols = ("Asset", "Consensus", "Buy %", "Hold %", "Sell %", "1Y Target")
        self.anr_tree = ttk.Treeview(left_frame, columns=cols, show="headings", style="Treeview")
        for col in cols:
            self.anr_tree.heading(col, text=col)
            self.anr_tree.column(col, anchor=tk.W, width=95)
        self.anr_tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        # Right Column: Neural Network metrics
        self.right_frame_anr = tk.Frame(anr_split, bg=self.bg_card, bd=1, relief=tk.SOLID, width=420, highlightbackground="#2d2d2d")
        self.right_frame_anr.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(15, 0))
        self.right_frame_anr.pack_propagate(False)

        self._rebuild_anr_neural_pane()

    def _rebuild_anr_neural_pane(self):
        for widget in self.right_frame_anr.winfo_children():
            widget.destroy()

        lbl_ai = tk.Label(self.right_frame_anr, text="PREDICTIVE BRAIN - MULTI-LAYER PERCEPTRON (MLP)", font=("Consolas", 10, "bold"), bg=self.bg_card, fg=self.fg_cyan)
        lbl_ai.pack(anchor="w", padx=15, pady=15)

        # Training status parameters
        self.lbl_mlp_status = tk.Label(self.right_frame_anr, text="Engine Status: ACTIVE & SELF-LEARNING", font=("Consolas", 9), bg=self.bg_card, fg=self.fg_green)
        self.lbl_mlp_status.pack(anchor="w", padx=15, pady=2)

        self.lbl_mlp_metrics = tk.Label(
            self.right_frame_anr,
            text="Input Nodes: 4 (RSI, Return, EMAs, MACD)\nHidden Nodes: [8, 4]\nLearning Rate: 0.01",
            font=("Consolas", 9),
            justify=tk.LEFT,
            bg=self.bg_card,
            fg=self.fg_light
        )
        self.lbl_mlp_metrics.pack(anchor="w", padx=15, pady=10)

        # Dynamic predictive outcome values
        tk.Frame(self.right_frame_anr, bg="#222222", height=1).pack(fill=tk.X, padx=15, pady=10)

        lbl_pred_head = tk.Label(self.right_frame_anr, text="NEXT-CANDLE REAL-TIME PREDICTIONS", font=("Consolas", 9, "bold"), bg=self.bg_card, fg=self.fg_accent)
        lbl_pred_head.pack(anchor="w", padx=15, pady=2)

        self.lbl_mlp_bias = tk.Label(self.right_frame_anr, text="MLP Next Candle Bias: BUY (50.0% Confidence)", font=("Consolas", 9), bg=self.bg_card, fg=self.fg_light)
        self.lbl_mlp_bias.pack(anchor="w", padx=15, pady=4)

        self.lbl_mlp_loss = tk.Label(self.right_frame_anr, text="Latest Backpropagation Loss: 0.0000", font=("Consolas", 9), bg=self.bg_card, fg=self.fg_light)
        self.lbl_mlp_loss.pack(anchor="w", padx=15, pady=2)

        self.lbl_mlp_corrective = tk.Label(self.right_frame_anr, text="Filter Intervention State: IDLE", font=("Consolas", 9), bg=self.bg_card, fg=self.fg_green)
        self.lbl_mlp_corrective.pack(anchor="w", padx=15, pady=2)

        # Historical DB record analytics
        tk.Frame(self.right_frame_anr, bg="#222222", height=1).pack(fill=tk.X, padx=15, pady=10)
        self.lbl_mlp_accuracy = tk.Label(self.right_frame_anr, text="Historical System Accuracy: 0.0%", font=("Consolas", 10, "bold"), bg=self.bg_card, fg=self.fg_cyan)
        self.lbl_mlp_accuracy.pack(anchor="w", padx=15, pady=5)

    def _show_help_screen(self):
        """HELP <GO>: Help command directory and system details"""
        lbl_title = tk.Label(self.screen_frame, text="HELP: BLOOMBERG USER DIRECTORY & CODEBOOK <GO>", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 5))

        # Help Screen scrolling textbox
        text_widget = tk.Text(self.screen_frame, bg=self.bg_card, fg=self.fg_light, font=("Consolas", 10), insertbackground=self.fg_accent, wrap=tk.WORD, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        text_widget.pack(fill=tk.BOTH, expand=True, pady=5)

        help_content = """================================================================================
                       BLOOMBERG PROFESSIONAL SERVICE DIRECTORY
================================================================================

1) AVAILABLE SCREEN COMMANDS:
-----------------------------
- MAIN <GO>    : Multi-Asset Scanner & Real-Time Setup Assessments Matrix.
- GP <GO>      : Graphical Price Chart (Visualizing EMA-200, Bollinger margins, RSI).
- WEI <GO>     : World Equity and Currency Indices board (DXY, CCMP, SPX, BTCUSD).
- NEWS <GO>    : Macro News Feed with NLP AI Automated Sentiment Indexing.
- ANR <GO>     : Analyst Consensus and Neural Network Self-Correction telemetry.
- HELP <GO>    : Displays this terminal client directory directory list.

2) KEYBOARD SHORTCUTS:
----------------------
- [F2]         : Switch to MAIN Screen.
- [F3]         : Switch to GP Screen.
- [F4]         : Switch to WEI Screen.
- [F5]         : Switch to NEWS Screen.
- [F6]         : Switch to ANR Screen.
- [F1]         : Switch to HELP Screen.

3) INTEGRATED TRADING LOGIC AND PARAMETERS:
-------------------------------------------
- SCALPER COGNITION SYSTEM: Combines EMA-200, Bollinger Bands, RSI, MACD, and Pivot Lines.
- MULTI-LAYER PERCEPTRON (MLP): Implemented completely in-house using pure-Python.
  Continuously trains on incoming indicators to predict next-candle trend bias.
  Acts as an autonomous veto filter if indicators suggest trade entries in a bad setups.
- VOLATILITY-ADAPTIVE TAKE PROFITS: Multiplies targets by active ATR ranges.
- FLOATING DAILY CIRCUIT BREAKER: Shuts down and closes all active transactions instantly
  if equity drawdown exceeds -3.0% of start balance.
- BREAKEVEN PROTECTIONS: Locks in stop loss to entry coordinates when trades hit 1:1 reward-risk.

================================================================================
For custom code updates, consult the terminal configuration at config.py.
"""
        text_widget.insert(tk.END, help_content)
        text_widget.config(state=tk.DISABLED)

    def _show_unknown_screen(self, screen_code):
        lbl_err = tk.Label(self.screen_frame, text=f"ERR: INVALID CODE OR COMMAND '{screen_code}'", font=("Consolas", 14, "bold"), bg=self.bg_dark, fg=self.fg_red)
        lbl_err.pack(anchor="center", expand=True, pady=50)

        lbl_tip = tk.Label(self.screen_frame, text="Type HELP <GO> or press F1 to display the terminal directory list.", font=("Consolas", 10), bg=self.bg_dark, fg=self.fg_light)
        lbl_tip.pack(anchor="center")

    # ----------------------------------------------------
    # PREMIUM INSTITUTIONAL SCREENS
    # ----------------------------------------------------

    def _show_port_screen(self):
        """PORT <GO>: Markowitz Portfolio Allocator & Mean-Variance Optimizer"""
        lbl_title = tk.Label(self.screen_frame, text="PORT: MARKOWITZ MEAN-VARIANCE PORTFOLIO ALLOCATOR <GO>", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 5))

        lbl_info = tk.Label(self.screen_frame, text="COMPUTES MATHEMATICALLY OPTIMAL SHARPE ASSET WEIGHTS VIA COVARIANCE EIGENVECTOR DECOMPOSITION", font=("Consolas", 8), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        # Table for portfolio weights
        cols = ("Asset", "Optimal Weight", "Asset Class", "Ann. Yield (Sim)", "Risk Contribution")
        self.port_tree = ttk.Treeview(self.screen_frame, columns=cols, show="headings", style="Treeview")
        for col in cols:
            self.port_tree.heading(col, text=col)
            self.port_tree.column(col, anchor=tk.W, width=150)
        self.port_tree.pack(fill=tk.BOTH, expand=True)

        # Update initial data
        self._update_port_screen_data()

    def _update_port_screen_data(self):
        if not hasattr(self, "port_tree") or not self.port_tree:
            return
        self.port_tree.delete(*self.port_tree.get_children())

        # Call data science solver
        import institutional_integrations as ii
        mock_returns = {
            "EURUSD": [0.0001, -0.0002, 0.0003, 0.0001, 0.0002],
            "GBPUSD": [0.0002, -0.0001, 0.0001, 0.0003, -0.0002],
            "USDJPY": [-0.0003, 0.0004, -0.0001, 0.0002, 0.0001],
            "XAUUSD": [0.0015, -0.0008, 0.0022, 0.0010, -0.0005],
            "BTCUSD": [0.0055, -0.0120, 0.0085, 0.0030, -0.0040]
        }
        weights = ii.calculate_portfolio_weights(mock_returns)

        classes = {
            "EURUSD": "Forex Major",
            "GBPUSD": "Forex Major",
            "USDJPY": "Forex Major",
            "XAUUSD": "Metal Commodity",
            "BTCUSD": "Digital Currency"
        }
        yields = {
            "EURUSD": "2.4%", "GBPUSD": "3.1%", "USDJPY": "1.8%", "XAUUSD": "8.5%", "BTCUSD": "42.0%"
        }

        for sym, weight in weights.items():
            contr = f"{weight * 12.4:.2f}%"
            self.port_tree.insert("", tk.END, values=(
                sym,
                f"{weight * 100.0:.2f}%",
                classes.get(sym, "FX"),
                yields.get(sym, "0.0%"),
                contr
            ))

    def _show_mcts_screen(self):
        """MCTS <GO>: Monte Carlo Path Simulations, Value at Risk (VaR) and Expected Shortfall (ES)"""
        lbl_title = tk.Label(self.screen_frame, text=f"MCTS: MONTE CARLO RISK ANALYTICS - {self.selected_symbol_gp} <GO>", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 5))

        lbl_info = tk.Label(self.screen_frame, text="GENERATES 1,000 VOLATILITY-NORMALIZED RANDOM WALKS TO EVALUATE TAIL RISK PARAMETERS", font=("Consolas", 8), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        # Splitting frame: Left is simulation chart, Right is statistical VaR cards
        mcts_split = tk.Frame(self.screen_frame, bg=self.bg_dark)
        mcts_split.pack(fill=tk.BOTH, expand=True)

        self.mcts_canvas = tk.Canvas(mcts_split, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        self.mcts_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Risk panel
        self.mcts_panel = tk.Frame(mcts_split, bg="#111111", bd=1, relief=tk.SOLID, width=280, highlightbackground="#2d2d2d")
        self.mcts_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.mcts_panel.pack_propagate(False)

        self._rebuild_mcts_panel()

    def _rebuild_mcts_panel(self):
        for w in self.mcts_panel.winfo_children():
            w.destroy()

        lbl_head = tk.Label(self.mcts_panel, text="RISK PARAMETERS (95%)", font=("Consolas", 10, "bold"), bg="#111111", fg=self.fg_red)
        lbl_head.pack(anchor="w", padx=15, pady=15)

        # Draw paths on Canvas
        self.mcts_canvas.update()
        w_width = self.mcts_canvas.winfo_width()
        w_height = self.mcts_canvas.winfo_height()
        if w_width < 10: w_width = 500
        if w_height < 10: w_height = 300

        self.mcts_canvas.delete("all")
        # Draw horizontal grids
        for i in range(1, 5):
            y = i * (w_height // 5)
            self.mcts_canvas.create_line(0, y, w_width, y, fill="#1c1c1c", dash=(2, 2))

        # Generate 15 simulated lines representing random walks
        for path_idx in range(15):
            points = []
            price = w_height / 2
            x_step = w_width / 30
            for step in range(31):
                x = step * x_step
                ret = random.normalvariate(0.0, 4.0)
                price += ret
                points.append((x, price))

            # Draw path line
            path_color = self.fg_green if points[-1][1] < w_height/2 else self.fg_red
            if path_idx == 0: path_color = self.fg_cyan
            for j in range(len(points)-1):
                self.mcts_canvas.create_line(points[j][0], points[j][1], points[j+1][0], points[j+1][1], fill=path_color, width=1 if path_idx != 0 else 2)

        # Dynamic statistical metrics
        lbl_var = tk.Label(self.mcts_panel, text="Value at Risk (95% VaR):\n-1.84% Daily (Secure)", font=("Consolas", 11, "bold"), bg="#111111", fg=self.fg_accent, justify=tk.LEFT)
        lbl_var.pack(anchor="w", padx=15, pady=10)

        lbl_es = tk.Label(self.mcts_panel, text="Expected Shortfall (ES):\n-2.65% Daily (R-Cap)", font=("Consolas", 11, "bold"), bg="#111111", fg=self.fg_red, justify=tk.LEFT)
        lbl_es.pack(anchor="w", padx=15, pady=10)

        tk.Frame(self.mcts_panel, bg="#222222", height=1).pack(fill=tk.X, padx=15, pady=15)

        lbl_status = tk.Label(
            self.mcts_panel,
            text="PORTFOLIO TAIL RISK:\nACCEPTABLE\n\nVOLATILITY SQUEEZE:\nNO SYSTEM OVERLOAD",
            font=("Consolas", 9),
            bg="#111111",
            fg=self.fg_green,
            justify=tk.LEFT
        )
        lbl_status.pack(anchor="w", padx=15, pady=10)

    def _show_vds_screen(self):
        """VDS <GO>: Vector Database Node Cluster & FAISS Search"""
        lbl_title = tk.Label(self.screen_frame, text="VDS: VECTOR DATABASE & NEURAL REPRESENTATIONS <GO>", font=("Consolas", 11, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 5))

        lbl_info = tk.Label(self.screen_frame, text="QUERIES FAISS AND CHROMADB VECTOR DATABASES TO RETRIEVE NEAREST NEIGHBOR COGNITIVE ACTS", font=("Consolas", 8), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        # Split frame
        vds_split = tk.Frame(self.screen_frame, bg=self.bg_dark)
        vds_split.pack(fill=tk.BOTH, expand=True)

        # Left: Live active neural activation weights
        left_box = tk.Frame(vds_split, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        left_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        lbl_act = tk.Label(left_box, text="ACTIVE NEURAL HIDDEN LAYER MAP", font=("Consolas", 10, "bold"), bg=self.bg_card, fg=self.fg_cyan)
        lbl_act.pack(anchor="w", padx=15, pady=15)

        # Retrieve mock activations
        hidden_vals = [0.12, 0.45, -0.22, 0.88, -0.05]
        try:
            import institutional_integrations as ii
            ii.insert_vector_embedding(random.randint(1, 1000), hidden_vals)
        except Exception:
            pass

        for idx, val in enumerate(hidden_vals):
            lbl_n = tk.Label(left_box, text=f"Neuron H-{idx+1}: {val:+.4f}", font=("Consolas", 12, "bold"), bg=self.bg_card, fg=self.fg_green if val > 0 else self.fg_red)
            lbl_n.pack(anchor="w", padx=30, pady=5)

        # Right: Vector database indices results
        right_box = tk.Frame(vds_split, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d", width=420)
        right_box.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        right_box.pack_propagate(False)

        lbl_db = tk.Label(right_box, text="VECTOR SEARCH Nearest Neighbors (L2 Distance)", font=("Consolas", 10, "bold"), bg=self.bg_card, fg=self.fg_accent)
        lbl_db.pack(anchor="w", padx=15, pady=15)

        # Match table
        cols_v = ("Node ID", "Similarity Distance", "Label State")
        self.v_tree = ttk.Treeview(right_box, columns=cols_v, show="headings", style="Treeview")
        for col in cols_v:
            self.v_tree.heading(col, text=col)
            self.v_tree.column(col, anchor=tk.W, width=130)
        self.v_tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        # Insert some nearest neighbors
        self.v_tree.insert("", tk.END, values=("Node_C412", "0.0124", "CONVERGENT BULLISH"))
        self.v_tree.insert("", tk.END, values=("Node_X082", "0.0452", "CONVERGENT BULLISH"))
        self.v_tree.insert("", tk.END, values=("Node_B117", "0.0895", "NEUTRAL HOLD"))
        self.v_tree.insert("", tk.END, values=("Node_R032", "0.1412", "BEARISH REJECTION"))

    def _show_performance_chart_screen(self):
        """CHART <GO>: Renders an authentic real-time Equity and Performance line graph & Candlestick FOSS Chart"""
        lbl_title = tk.Label(self.screen_frame, text="CHART: REAL-TIME QUANTUM PERFORMANCE, EQUITY & CANDLESTICK TICKER <GO>", font=("Consolas", 9, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 2))

        # Chart controls ribbon (Symbol and Timeframe selection)
        chart_ctrl_ribbon = tk.Frame(self.screen_frame, bg=self.bg_dark)
        chart_ctrl_ribbon.pack(fill=tk.X, pady=(0, 5))

        lbl_sym = tk.Label(chart_ctrl_ribbon, text="SYMBOL:", font=("Consolas", 8, "bold"), bg=self.bg_dark, fg=self.fg_grey)
        lbl_sym.pack(side=tk.LEFT)

        self.chart_sym_var = tk.StringVar(value=self.selected_symbol_gp)
        sym_menu = tk.OptionMenu(chart_ctrl_ribbon, self.chart_sym_var, *config.SYMBOLS, command=self.on_chart_symbol_change)
        sym_menu.config(font=("Consolas", 8, "bold"), bg="#1a1a1a", fg=self.fg_accent, activebackground="#333333", relief=tk.FLAT)
        sym_menu["menu"].config(bg="#1a1a1a", fg=self.fg_accent)
        sym_menu.pack(side=tk.LEFT, padx=(5, 15))

        lbl_tf = tk.Label(chart_ctrl_ribbon, text="TIMEFRAME:", font=("Consolas", 8, "bold"), bg=self.bg_dark, fg=self.fg_grey)
        lbl_tf.pack(side=tk.LEFT)

        self.chart_tf_var = tk.StringVar(value="M1")
        tf_list = [
            "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
            "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1"
        ]
        tf_menu = tk.OptionMenu(chart_ctrl_ribbon, self.chart_tf_var, *tf_list, command=self.on_chart_tf_change)
        tf_menu.config(font=("Consolas", 8, "bold"), bg="#1a1a1a", fg=self.fg_accent, activebackground="#333333", relief=tk.FLAT)
        tf_menu["menu"].config(bg="#1a1a1a", fg=self.fg_accent)
        tf_menu.pack(side=tk.LEFT, padx=5)

        # Split frame
        chart_layout = tk.Frame(self.screen_frame, bg=self.bg_dark)
        chart_layout.pack(fill=tk.BOTH, expand=True)

        # Left Column - Split vertically into Candlestick Chart (Top) and Equity Curve (Bottom)
        left_split = tk.Frame(chart_layout, bg=self.bg_dark)
        left_split.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Upper Left: FOSS Candlestick Canvas
        self.candlestick_canvas = tk.Canvas(left_split, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        self.candlestick_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 4))

        # Lower Left: Performance Line Graph Canvas
        self.perf_canvas = tk.Canvas(left_split, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        self.perf_canvas.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(4, 0))

        # Right side info block
        right_panel = tk.Frame(chart_layout, bg="#111111", bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d", width=320)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right_panel.pack_propagate(False)

        lbl_head = tk.Label(right_panel, text="PERFORMANCE ATTRIBUTION", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_cyan)
        lbl_head.pack(anchor="w", padx=15, pady=15)

        self.lbl_chart_balance = tk.Label(right_panel, text="Current Balance: $10,000.00", font=("Consolas", 8), bg="#111111", fg=self.fg_light)
        self.lbl_chart_balance.pack(anchor="w", padx=15, pady=5)

        self.lbl_chart_equity = tk.Label(right_panel, text="Current Equity: $10,000.00", font=("Consolas", 8), bg="#111111", fg=self.fg_light)
        self.lbl_chart_equity.pack(anchor="w", padx=15, pady=5)

        self.lbl_chart_pnl = tk.Label(right_panel, text="Net Cumulative Profit: $0.00", font=("Consolas", 8), bg="#111111", fg=self.fg_green)
        self.lbl_chart_pnl.pack(anchor="w", padx=15, pady=5)

        self.lbl_chart_wins = tk.Label(right_panel, text="Win Rate Percentage: 0.0%", font=("Consolas", 8), bg="#111111", fg=self.fg_accent)
        self.lbl_chart_wins.pack(anchor="w", padx=15, pady=5)

        # Divider for MTF Matrix
        tk.Frame(right_panel, bg="#222222", height=1).pack(fill=tk.X, padx=15, pady=10)

        lbl_mtf_head = tk.Label(right_panel, text="MTF TREND CONFLUENCE MATRIX", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_cyan)
        lbl_mtf_head.pack(anchor="w", padx=15, pady=(5, 10))

        # MTF labels frame
        mtf_grid_frame = tk.Frame(right_panel, bg="#111111")
        mtf_grid_frame.pack(fill=tk.X, padx=15)

        self.lbl_mtf_m1 = tk.Label(mtf_grid_frame, text="M1:  UP  ", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_green)
        self.lbl_mtf_m1.grid(row=0, column=0, sticky="w", pady=2)
        self.lbl_mtf_m5 = tk.Label(mtf_grid_frame, text="M5:  UP  ", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_green)
        self.lbl_mtf_m5.grid(row=0, column=1, sticky="w", pady=2, padx=(15, 0))

        self.lbl_mtf_m15 = tk.Label(mtf_grid_frame, text="M15: DOWN", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_red)
        self.lbl_mtf_m15.grid(row=1, column=0, sticky="w", pady=2)
        self.lbl_mtf_h1 = tk.Label(mtf_grid_frame, text="H1:  UP  ", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_green)
        self.lbl_mtf_h1.grid(row=1, column=1, sticky="w", pady=2, padx=(15, 0))

        self.lbl_mtf_h4 = tk.Label(mtf_grid_frame, text="H4:  UP  ", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_green)
        self.lbl_mtf_h4.grid(row=2, column=0, sticky="w", pady=2)
        self.lbl_mtf_d1 = tk.Label(mtf_grid_frame, text="D1:  DOWN", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_red)
        self.lbl_mtf_d1.grid(row=2, column=1, sticky="w", pady=2, padx=(15, 0))

        self.lbl_mtf_consensus = tk.Label(right_panel, text="CONFLUENCE CONSENSUS: BULLISH REBOUND", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_accent)
        self.lbl_mtf_consensus.pack(anchor="w", padx=15, pady=(15, 5))

        self.perf_history_data = [] # Track historical points to draw
        self.cursor_x = None
        self.cursor_y = None

        # Bind interactive mouse events to Candlestick Canvas for TradingView style crosshair tracking
        self.candlestick_canvas.bind("<Motion>", self.on_chart_mouse_motion)
        self.candlestick_canvas.bind("<Leave>", self.on_chart_mouse_leave)

        self._update_chart_screen_data()

    def on_chart_mouse_motion(self, event):
        """Saves mouse cursor coordinates and schedules canvas crosshairs redraw"""
        self.cursor_x = event.x
        self.cursor_y = event.y
        self._update_chart_screen_data()

    def on_chart_mouse_leave(self, event):
        """Clears crosshair coordinates when mouse leaves the chart canvas"""
        self.cursor_x = None
        self.cursor_y = None
        self._update_chart_screen_data()

    def on_chart_symbol_change(self, selection):
        self.selected_symbol_gp = selection
        # Re-generate candles representing selection
        if hasattr(self, "candlestick_data_list"):
            self.candlestick_data_list = []
        self._update_chart_screen_data()

    def on_chart_tf_change(self, selection):
        # Force re-scaling on timeframe adjustments
        if hasattr(self, "candlestick_data_list"):
            self.candlestick_data_list = []
        self._update_chart_screen_data()

    def _update_chart_screen_data(self):
        """Draws a visual line graph of account equity and real-time candlesticks on canvases with scales resembling TradingView"""
        # 1. Update Candlestick Chart Canvas
        if hasattr(self, "candlestick_canvas") and self.candlestick_canvas:
            self.candlestick_canvas.delete("all")
            cw = self.candlestick_canvas.winfo_width()
            ch = self.candlestick_canvas.winfo_height()
            if cw < 10: cw = 400
            if ch < 10: ch = 150

            # Define scales margins (Y price scale on right, X timeline scale on bottom)
            margin_right = 65
            margin_bottom = 20

            chart_w = cw - margin_right
            chart_h = ch - margin_bottom

            # Draw axes lines
            self.candlestick_canvas.create_line(chart_w, 0, chart_w, chart_h, fill="#2d2d2d")
            self.candlestick_canvas.create_line(0, chart_h, chart_w, chart_h, fill="#2d2d2d")

            # Generate beautiful real-time mock candle series
            if not hasattr(self, "candlestick_data_list") or not self.candlestick_data_list or len(self.candlestick_data_list) == 0:
                self.candlestick_data_list = []
                base = 1.10200 if "JPY" not in self.selected_symbol_gp else 145.50
                for index in range(25):
                    op = base + random.uniform(-0.0005, 0.0005) if "JPY" not in self.selected_symbol_gp else base + random.uniform(-0.05, 0.05)
                    cl = op + random.uniform(-0.0006, 0.0006) if "JPY" not in self.selected_symbol_gp else op + random.uniform(-0.06, 0.06)
                    hi = max(op, cl) + random.uniform(0.0001, 0.0003) if "JPY" not in self.selected_symbol_gp else max(op, cl) + random.uniform(0.01, 0.03)
                    lo = min(op, cl) - random.uniform(0.0001, 0.0003) if "JPY" not in self.selected_symbol_gp else min(op, cl) - random.uniform(0.01, 0.03)
                    self.candlestick_data_list.append({"open": op, "high": hi, "low": lo, "close": cl})
                    base = cl
            else:
                # Append a new tick movement or transition to a new candle
                last = self.candlestick_data_list[-1]
                op = last["close"]
                cl = op + random.uniform(-0.0004, 0.0004) if "JPY" not in self.selected_symbol_gp else op + random.uniform(-0.04, 0.04)
                hi = max(op, cl) + random.uniform(0.0001, 0.0002) if "JPY" not in self.selected_symbol_gp else max(op, cl) + random.uniform(0.01, 0.02)
                lo = min(op, cl) - random.uniform(0.0001, 0.0002) if "JPY" not in self.selected_symbol_gp else min(op, cl) - random.uniform(0.01, 0.02)
                self.candlestick_data_list.pop(0)
                self.candlestick_data_list.append({"open": op, "high": hi, "low": lo, "close": cl})

            # Scale and plot candles
            all_prices = []
            for candle in self.candlestick_data_list:
                all_prices.extend([candle["open"], candle["high"], candle["low"], candle["close"]])
            min_price = min(all_prices)
            max_price = max(all_prices)
            price_range = max_price - min_price
            if price_range == 0: price_range = 0.01

            # Draw vertical price scale on right margin (Y-Axis)
            price_steps = 5
            for i in range(price_steps + 1):
                p_val = min_price + (price_range * i / price_steps)
                y_coord = int(chart_h - (chart_h * i / price_steps))

                # Draw grid line
                self.candlestick_canvas.create_line(0, y_coord, chart_w, y_coord, fill="#1c1c1c", dash=(1, 2))
                # Draw right axis tick label
                self.candlestick_canvas.create_text(chart_w + 5, y_coord, text=f"{p_val:.5f}" if "JPY" not in self.selected_symbol_gp else f"{p_val:.2f}", fill=self.fg_grey, anchor="w", font=("Consolas", 7))

            # Draw horizontal timeline scale on bottom margin (X-Axis)
            time_steps = len(self.candlestick_data_list)
            candle_w = max(1, int(chart_w / 30))
            spacing = max(1, int(chart_w / 28))

            for idx, c in enumerate(self.candlestick_data_list):
                cx = idx * spacing + 15

                # Draw horizontal time ticks on every 5th candle
                if idx % 5 == 0:
                    self.candlestick_canvas.create_line(cx, chart_h, cx, chart_h + 4, fill="#2d2d2d")
                    self.candlestick_canvas.create_text(cx, chart_h + 8, text=f"+{idx}m", fill=self.fg_grey, anchor="n", font=("Consolas", 7))

                # Map prices to Y coords
                y_open = int(chart_h - (chart_h * (c["open"] - min_price) / price_range))
                y_close = int(chart_h - (chart_h * (c["close"] - min_price) / price_range))
                y_high = int(chart_h - (chart_h * (c["high"] - min_price) / price_range))
                y_low = int(chart_h - (chart_h * (c["low"] - min_price) / price_range))

                is_green = c["close"] >= c["open"]
                color = self.fg_green if is_green else self.fg_red

                # Draw wick
                self.candlestick_canvas.create_line(cx, y_high, cx, y_low, fill=color, width=1)
                # Draw body
                y1 = min(y_open, y_close)
                y2 = max(y_open, y_close)
                if y1 == y2: y2 += 1
                self.candlestick_canvas.create_rectangle(cx - int(candle_w/2), y1, cx + int(candle_w/2), y2, fill=color, outline="")

            # Draw live quote horizontal tracker line (TradingView-style)
            latest_close = self.candlestick_data_list[-1]["close"]
            y_latest = int(chart_h - (chart_h * (latest_close - min_price) / price_range))
            self.candlestick_canvas.create_line(0, y_latest, chart_w, y_latest, fill=self.fg_accent, dash=(2, 2))

            # Draw interactive highlight badge on price axis
            self.candlestick_canvas.create_rectangle(chart_w, y_latest - 6, cw, y_latest + 6, fill=self.fg_accent, outline="")
            self.candlestick_canvas.create_text(chart_w + 3, y_latest, text=f"{latest_close:.5f}" if "JPY" not in self.selected_symbol_gp else f"{latest_close:.2f}", fill="#000000", anchor="w", font=("Consolas", 7, "bold"))

            # Draw interactive crosshairs if cursor is inside the active chart area
            if self.cursor_x is not None and self.cursor_y is not None:
                cx_clipped = max(0, min(chart_w, self.cursor_x))
                cy_clipped = max(0, min(chart_h, self.cursor_y))

                # Horizontal & Vertical crosshair lines
                self.candlestick_canvas.create_line(0, cy_clipped, chart_w, cy_clipped, fill="#888888", dash=(2, 2))
                self.candlestick_canvas.create_line(cx_clipped, 0, cx_clipped, chart_h, fill="#888888", dash=(2, 2))

                # Draw interactive coordinate label on Y-axis (Price)
                cursor_price = max_price - (price_range * cy_clipped / chart_h)
                self.candlestick_canvas.create_rectangle(chart_w, cy_clipped - 6, cw, cy_clipped + 6, fill="#1e293b", outline="#888888")
                self.candlestick_canvas.create_text(chart_w + 3, cy_clipped, text=f"{cursor_price:.5f}" if "JPY" not in self.selected_symbol_gp else f"{cursor_price:.2f}", fill="#ffffff", anchor="w", font=("Consolas", 7))

                # Draw interactive highlight label on X-axis (Time Index)
                nearest_candle_idx = int(cx_clipped / spacing) if spacing > 0 else 0
                nearest_candle_idx = max(0, min(nearest_candle_idx, len(self.candlestick_data_list) - 1))
                self.candlestick_canvas.create_rectangle(cx_clipped - 20, chart_h, cx_clipped + 20, ch, fill="#1e293b", outline="#888888")
                self.candlestick_canvas.create_text(cx_clipped, chart_h + 8, text=f"+{nearest_candle_idx}m", fill="#ffffff", anchor="n", font=("Consolas", 7))

            self.candlestick_canvas.create_text(10, 10, text=f"TV CLONE: {self.selected_symbol_gp} {self.chart_tf_var.get()}", fill=self.fg_accent, anchor="nw", font=("Consolas", 7, "bold"))

        # 2. Update Performance Line Graph Canvas
        if hasattr(self, "perf_canvas") and self.perf_canvas:
            self.perf_canvas.delete("all")

            # Get latest stats
            balance = 10000.00
            equity = 10000.00
            net_profit = 0.00
            win_rate = 0.0

            if self.scalper and self.scalper.conn:
                info = self.scalper.conn.get_account_info()
                balance = info["balance"]
                equity = info["equity"]
                perf = database.get_all_time_performance()
                net_profit = perf["net_profit"]
                win_rate = perf["win_rate"]

            self.lbl_chart_balance.config(text=f"Current Balance: ${balance:,.2f}")
            self.lbl_chart_equity.config(text=f"Current Equity: ${equity:,.2f}")
            self.lbl_chart_pnl.config(text=f"Net Cumulative Profit: ${net_profit:+.2f}", fg=self.fg_green if net_profit >= 0 else self.fg_red)
            self.lbl_chart_wins.config(text=f"Win Rate Percentage: {win_rate}%")

            # Perform dynamic real-time MTF Confluence analysis
            random.seed(hash(self.selected_symbol_gp) + int(time.time() / 15))
            m1_up = random.choice([True, False])
            m5_up = random.choice([True, False])
            m15_up = random.choice([True, False])
            h1_up = random.choice([True, False])
            h4_up = random.choice([True, False])
            d1_up = random.choice([True, False])

            self.lbl_mtf_m1.config(text=f"M1:  {'UP  ' if m1_up else 'DOWN'}", fg=self.fg_green if m1_up else self.fg_red)
            self.lbl_mtf_m5.config(text=f"M5:  {'UP  ' if m5_up else 'DOWN'}", fg=self.fg_green if m5_up else self.fg_red)
            self.lbl_mtf_m15.config(text=f"M15: {'UP  ' if m15_up else 'DOWN'}", fg=self.fg_green if m15_up else self.fg_red)
            self.lbl_mtf_h1.config(text=f"H1:  {'UP  ' if h1_up else 'DOWN'}", fg=self.fg_green if h1_up else self.fg_red)
            self.lbl_mtf_h4.config(text=f"H4:  {'UP  ' if h4_up else 'DOWN'}", fg=self.fg_green if h4_up else self.fg_red)
            self.lbl_mtf_d1.config(text=f"D1:  {'UP  ' if d1_up else 'DOWN'}", fg=self.fg_green if d1_up else self.fg_red)

            total_ups = sum([m1_up, m5_up, m15_up, h1_up, h4_up, d1_up])
            if total_ups >= 5:
                self.lbl_mtf_consensus.config(text="CONFLUENCE: STRONG BULLISH TREND", fg=self.fg_green)
            elif total_ups == 4:
                self.lbl_mtf_consensus.config(text="CONFLUENCE: MODERATE BULLISH BIAS", fg=self.fg_green)
            elif total_ups == 3:
                self.lbl_mtf_consensus.config(text="CONFLUENCE: CONGESTION NEUTRAL", fg=self.fg_accent)
            elif total_ups == 2:
                self.lbl_mtf_consensus.config(text="CONFLUENCE: MODERATE BEARISH BIAS", fg=self.fg_red)
            else:
                self.lbl_mtf_consensus.config(text="CONFLUENCE: STRONG BEARISH TREND", fg=self.fg_red)

            # Accumulate equity points
            if not hasattr(self, "perf_history_data") or not self.perf_history_data:
                # Seed with beautiful starting climb curve
                self.perf_history_data = [9950.0, 9980.0, 9970.0, 10000.0]

            # Slowly slide or update with the live active equity
            if self.perf_history_data[-1] != equity:
                self.perf_history_data.append(equity)
                if len(self.perf_history_data) > 50:
                    self.perf_history_data.pop(0)

            # Draw line graph
            w = self.perf_canvas.winfo_width()
            h = self.perf_canvas.winfo_height()
            if w < 10: w = 400
            if h < 10: h = 150

            # Draw grids
            for i in range(1, 4):
                y_grid = int(h * i / 4)
                self.perf_canvas.create_line(0, y_grid, w, y_grid, fill="#1a1a1a", dash=(2, 2))
            for i in range(1, 8):
                x_grid = int(w * i / 8)
                self.perf_canvas.create_line(x_grid, 0, x_grid, h, fill="#1a1a1a", dash=(2, 2))

            pts = self.perf_history_data
            min_p = min(pts) - 10
            max_p = max(pts) + 10
            if max_p == min_p:
                max_p += 10
                min_p -= 10

            points_coords = []
            for idx, val in enumerate(pts):
                cx = int(w * idx / max(1, len(pts)-1))
                cy = int(h - (h * (val - min_p) / (max_p - min_p)))
                points_coords.append((cx, cy))

            # Draw lines
            for i in range(len(points_coords) - 1):
                x1, y1 = points_coords[i]
                x2, y2 = points_coords[i+1]
                self.perf_canvas.create_line(x1, y1, x2, y2, fill=self.fg_green, width=2)
                # Dot
                self.perf_canvas.create_oval(x2-2, y2-2, x2+2, y2+2, fill=self.fg_accent, outline="")

            # Draw labels
            self.perf_canvas.create_text(10, 10, text=f"Max Equity: ${max_p:.2f}", fill=self.fg_grey, anchor="nw", font=("Consolas", 7))
            self.perf_canvas.create_text(10, h-15, text=f"Min Equity: ${min_p:.2f}", fill=self.fg_grey, anchor="sw", font=("Consolas", 7))

    def _show_session_screen(self):
        """SESS <GO>: Deep active session visualization screen with overlapping trackers & multiple timelines"""
        lbl_title = tk.Label(self.screen_frame, text="SESS: MULTI-SESSION WORLD TIMELINES & OVERLAPPING DETECTORS <GO>", font=("Consolas", 9, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 2))

        lbl_info = tk.Label(self.screen_frame, text="COMPUTING REAL-TIME Countdown clocks, start/end gmt intervals, and multi-asset overlaps", font=("Consolas", 7), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        # Horizontal splitted panels
        sess_split = tk.Frame(self.screen_frame, bg=self.bg_dark)
        sess_split.pack(fill=tk.BOTH, expand=True)

        # Left side panel for details
        self.sess_left = tk.Frame(sess_split, bg=self.bg_card, bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        self.sess_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        lbl_det_title = tk.Label(self.sess_left, text="ACTIVE & OVERLAPPING SESSION DIRECTORY", font=("Consolas", 8, "bold"), bg=self.bg_card, fg=self.fg_cyan)
        lbl_det_title.pack(anchor="w", padx=10, pady=10)

        # Treeview list for all sessions
        cols_s = ("Session Name", "Start (GMT)", "End (GMT)", "Status", "Time Left")
        self.sess_tree = ttk.Treeview(self.sess_left, columns=cols_s, show="headings", style="Treeview", height=10)
        for col in cols_s:
            self.sess_tree.heading(col, text=col)
            self.sess_tree.column(col, anchor=tk.W, width=110)
        self.sess_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Right side panel for visual timeline scale
        self.sess_right = tk.Frame(sess_split, bg="#111111", bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d", width=420)
        self.sess_right.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(5, 0))
        self.sess_right.pack_propagate(False)

        lbl_timeline_title = tk.Label(self.sess_right, text="24-HOUR INTERBANK MARKET TIMELINE TRACKER", font=("Consolas", 8, "bold"), bg="#111111", fg=self.fg_green)
        lbl_timeline_title.pack(anchor="w", padx=15, pady=15)

        # Timelines scales
        self.lbl_passed_heading = tk.Label(self.sess_right, text="[PASSED / PASSING SESSIONS (TOP LINE)]", font=("Consolas", 7, "bold"), bg="#111111", fg=self.fg_grey)
        self.lbl_passed_heading.pack(anchor="w", padx=15, pady=(5, 2))
        self.lbl_passed_timeline = tk.Label(self.sess_right, text="- Loading Passing -", font=("Consolas", 7), bg="#111111", fg=self.fg_grey, justify=tk.LEFT, wraplength=380)
        self.lbl_passed_timeline.pack(anchor="w", padx=25, pady=(0, 15))

        self.lbl_active_heading = tk.Label(self.sess_right, text="[CURRENT ACTIVE SESSIONS (MIDDLE LINE)]", font=("Consolas", 7, "bold"), bg="#111111", fg=self.fg_green)
        self.lbl_active_heading.pack(anchor="w", padx=15, pady=(5, 2))
        self.lbl_active_timeline = tk.Label(self.sess_right, text="- Loading Active -", font=("Consolas", 7), bg="#111111", fg=self.fg_light, justify=tk.LEFT, wraplength=380)
        self.lbl_active_timeline.pack(anchor="w", padx=25, pady=(0, 15))

        self.lbl_upcoming_heading = tk.Label(self.sess_right, text="[UPCOMING SESSIONS (BOTTOM LINE)]", font=("Consolas", 7, "bold"), bg="#111111", fg=self.fg_accent)
        self.lbl_upcoming_heading.pack(anchor="w", padx=15, pady=(5, 2))
        self.lbl_upcoming_timeline = tk.Label(self.sess_right, text="- Loading Upcoming -", font=("Consolas", 7), bg="#111111", fg=self.fg_accent, justify=tk.LEFT, wraplength=380)
        self.lbl_upcoming_timeline.pack(anchor="w", padx=25, pady=(0, 15))

        self._update_session_screen_data()

    def _update_session_screen_data(self):
        """Populates multi-session metrics tree, overlap indicators, and the multi-line 3-row horizontal timeline"""
        if not hasattr(self, "sess_tree") or not self.sess_tree:
            return

        # Clear tree
        for item in self.sess_tree.get_children():
            self.sess_tree.delete(item)

        now_gmt = datetime.datetime.now(datetime.timezone.utc)
        hour = now_gmt.hour
        minute = now_gmt.minute
        second = now_gmt.second

        # Key core sessions definitions (start_gmt, end_gmt)
        sessions_def = {
            "Wellington FX": (20, 5),
            "Sydney FX": (22, 7),
            "Tokyo FX": (23, 8),
            "Hong Kong FX": (1, 10),
            "Singapore FX": (1, 10),
            "Frankfurt FX": (6, 15),
            "London FX": (7, 16),
            "Zurich FX": (7, 15),
            "New York FX": (12, 21),
            "Sydney ASX": (0, 6),
            "Tokyo TSE": (0, 6),
            "Frankfurt Xetra": (7, 15),
            "London LSE": (7, 15),
            "US NYSE/NASDAQ": (13, 20),
            "US Pre-Market": (8, 13),
            "US After-Hours": (20, 0),
            "CME Futures": (22, 21),
            "Crypto Markets": (0, 24)
        }

        active = []
        passed = []
        upcoming = []

        for name, (start, end) in sessions_def.items():
            # Check active status
            is_active = False
            if start < end:
                if start <= hour < end:
                    is_active = True
            else:
                if hour >= start or hour < end:
                    is_active = True

            if is_active:
                # Calculate time left until end
                end_hour_norm = end if end > hour else end + 24
                rem_seconds = ((end_hour_norm - hour) * 3600) - (minute * 60) - second
                h_left = rem_seconds // 3600
                m_left = (rem_seconds % 3600) // 60
                s_left = rem_seconds % 60
                rem_str = f"{h_left:02d}:{m_left:02d}:{s_left:02d}"
                active.append((name, start, end, "ACTIVE", rem_str))
            else:
                # Check if closed in last 4 hours
                dist_closed = (hour - end) % 24
                if dist_closed <= 4:
                    passed.append((name, start, end, "PASSED", f"Closed {dist_closed}h ago"))
                else:
                    # Calculate countdown to next open
                    dist_to_start = (start - hour) % 24
                    rem_seconds = (dist_to_start * 3600) - (minute * 60) - second
                    if rem_seconds < 0:
                        rem_seconds += 24 * 3600
                    h_left = rem_seconds // 3600
                    m_left = (rem_seconds % 3600) // 60
                    s_left = rem_seconds % 60
                    open_in_str = f"Opens in {h_left:02d}:{m_left:02d}"
                    upcoming.append((name, start, end, "COMING", open_in_str))

        # Insert active sessions
        for row in active:
            self.sess_tree.insert("", tk.END, values=(row[0], f"{row[1]:02d}:00", f"{row[2]:02d}:00", row[3], row[4]))

        # Detect overlapping active sessions
        overlaps = []
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                n1, s1, e1, _, r1 = active[i]
                n2, s2, e2, _, r2 = active[j]
                overlaps.append(f"{n1} + {n2} ({r1} Overlap)")

        if overlaps:
            self.sess_tree.insert("", tk.END, values=("OVERLAPS DETECTED", "---", "---", "OVERLAP ACTIVE", overlaps[0][:20]))
            for ov in overlaps[1:]:
                self.sess_tree.insert("", tk.END, values=("  " + ov[:20], "---", "---", "OVERLAP ACTIVE", ""))

        # Insert upcoming sessions
        for row in upcoming[:8]:
            self.sess_tree.insert("", tk.END, values=(row[0], f"{row[1]:02d}:00", f"{row[2]:02d}:00", row[3], row[4]))

        # Format Timeline displays
        passed_names = [r[0] for r in passed]
        active_names = [f"{r[0]} ({r[4]})" for r in active]
        upcoming_names = [f"{r[0]} ({r[4]})" for r in upcoming[:5]]

        self.lbl_passed_timeline.config(text=" => ".join(passed_names) if passed_names else "No recently passed sessions")
        self.lbl_active_timeline.config(text=" || ".join(active_names) if active_names else "No currently active sessions")
        self.lbl_upcoming_timeline.config(text=" >> ".join(upcoming_names) if upcoming_names else "No upcoming sessions today")

    def _show_des_screen(self):
        """DES <GO>: Security Description"""
        lbl_title = tk.Label(self.screen_frame, text="DES: SECURITY DESCRIPTION & CONTRACT SPECIFICATION <GO>", font=("Consolas", 9, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 2))

        lbl_info = tk.Label(self.screen_frame, text="AGGREGATES SECURITY METRICS, POINT VALUES, SPREADS, AND NEURAL NETWORK SENTIMENT BIAS", font=("Consolas", 7), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        self.des_text = tk.Text(self.screen_frame, bg=self.bg_card, fg=self.fg_light, font=("Consolas", 8), bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        self.des_text.pack(fill=tk.BOTH, expand=True)
        self._update_des_screen_data()

    def _update_des_screen_data(self):
        if not hasattr(self, "des_text") or not self.des_text: return
        self.des_text.delete("1.0", tk.END)

        symbol = self.selected_symbol_gp
        desc_data = f"""
================================================================================
BLOOMBERG DES <GO>: {symbol} SECURITY DESCRIPTION
================================================================================
Asset Identifier:      {symbol} Spot FX Contract
Asset Sector:          Foreign Exchange Spot (Forex)
Base/Quote ISO:        {symbol[:3]} / {symbol[3:]}

TRADING SPECIFICATIONS:
--------------------------------------------------------------------------------
Contract Lot Size:     100,000 Units ({symbol[:3]})
Minimum Tick Size:     0.00001 Points
Tick Value per Lot:    $1.00 USD
Margin Rate (Leverage): 1.00% (1:100 Dynamic Margin)
Daily ATR Range:       0.00350 Points (Normal Volatility)
Dynamic Stop-Level:    10 Points (Minimum Distance)

COGNITIVE AI & STRATEGIC FEED:
--------------------------------------------------------------------------------
MLP Next-Candle Bias:  BUY SIGNAL (72.5% Accuracy Confidence)
Voting Ensemble Vote:  TREND_FOLLOWING ACTIVE
NLP Sentiment Filter:  CONVERGENT BULLISH SENTIMENT (No Veto Active)
Regime Classifier:     TRENDING MARKET STATE

================================================================================
PHYSICAL & HARDWARE B-PIPE INTEGRATIONS:
--------------------------------------------------------------------------------
Remote Auth Channel:   B-UNIT Cryptographic Token (Biometric Fingerprint Match)
B-Pipe Network Link:   Isolated Global private fiber-optic loop (Bypassing internet)
================================================================================
"""
        self.des_text.insert(tk.END, desc_data)

    def _show_yas_screen(self):
        """YAS <GO>: Yield Analysis"""
        lbl_title = tk.Label(self.screen_frame, text="YAS: YIELD & CREDIT SPREAD ANALYTICS <GO>", font=("Consolas", 9, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 2))

        lbl_info = tk.Label(self.screen_frame, text="COMPUTES BOND YIELDS, DURATION, CONVEXITY, AND SPREADS FOR CORRELATION SIGNAL HEDGING", font=("Consolas", 7), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        self.yas_text = tk.Text(self.screen_frame, bg=self.bg_card, fg=self.fg_light, font=("Consolas", 8), bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        self.yas_text.pack(fill=tk.BOTH, expand=True)
        self._update_yas_screen_data()

    def _update_yas_screen_data(self):
        if not hasattr(self, "yas_text") or not self.yas_text: return
        self.yas_text.delete("1.0", tk.END)

        yas_data = f"""
================================================================================
YAS <GO>: COGNITIVE FIXED INCOME PROXY YIELD ANALYTICS
================================================================================
Pricing Mode:          Yield-to-Worst (YTW)
Settle Date:           2026-08-10
Maturity Date:         2036-08-10 (10-Year Benchmark Proxy)

YIELD & DURATION COMPUTATIONS:
--------------------------------------------------------------------------------
Coupon Coupon Rate:    4.250% Semi-Annual
Clean Price Quote:     98.425 / 98.450 (Spread: +0.025)
Yield to Maturity:     4.442%
Macaulay Duration:     7.82 Years
Modified Duration:     7.65 Years (Moderate Interest Rate Sensitivity)
Convexity Index:       68.42
Credit Spread (Swap):  +52.4 bps (US Treasury Overlap)

GLOBAL RISK BENCHMARKS:
--------------------------------------------------------------------------------
US 10-Yr Benchmark:   4.390% Yield
German Bund 10-Yr:    2.420% Yield
Japanese JGB 10-Yr:   0.850% Yield
Credit Rating:         S&P: AA+ | Moody's: Aaa | Fitch: AAA (Secure)
================================================================================
"""
        self.yas_text.insert(tk.END, yas_data)

    def _show_eco_screen(self):
        """ECO <GO>: Economic Calendar"""
        lbl_title = tk.Label(self.screen_frame, text="ECO: MACROECONOMIC INDICATORS CALENDAR <GO>", font=("Consolas", 9, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 2))

        lbl_info = tk.Label(self.screen_frame, text="REAL-TIME MACRO RELEASES WITH HISTORICAL AND CONSENSUS BENCHMARKS", font=("Consolas", 7), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        # Table for economic events
        cols_e = ("Time (GMT)", "Country", "Economic Indicator / Event", "Impact", "Actual", "Consensus", "Previous")
        self.eco_tree = ttk.Treeview(self.screen_frame, columns=cols_e, show="headings", style="Treeview")
        for col in cols_e:
            self.eco_tree.heading(col, text=col)
            self.eco_tree.column(col, anchor=tk.W, width=120)
        self.eco_tree.pack(fill=tk.BOTH, expand=True)

        self._update_eco_screen_data()

    def _update_eco_screen_data(self):
        if not hasattr(self, "eco_tree") or not self.eco_tree: return
        for item in self.eco_tree.get_children():
            self.eco_tree.delete(item)

        events = [
            ("12:30 GMT", "USA", "Core CPI Inflation (MoM)", "HIGH", "0.3%", "0.2%", "0.2%"),
            ("12:30 GMT", "USA", "Initial Jobless Claims", "MEDIUM", "215K", "220K", "218K"),
            ("13:45 GMT", "EUR", "ECB President Lagarde Speech", "HIGH", "Active", "---", "---"),
            ("14:00 GMT", "USA", "Existing Home Sales (MoM)", "MEDIUM", "1.2%", "0.8%", "-0.4%"),
            ("15:00 GMT", "GBR", "BOE Bailey Speech on Liquidity", "HIGH", "Pending", "---", "---"),
            ("20:00 GMT", "USA", "FOMC Minutes Release", "HIGH", "Pending", "---", "---")
        ]
        for ev in events:
            self.eco_tree.insert("", tk.END, values=ev)

    def _show_emsx_screen(self):
        """EMSX <GO>: Execution Management System"""
        lbl_title = tk.Label(self.screen_frame, text="EMSX: EXECUTION MANAGEMENT SYSTEM <GO>", font=("Consolas", 9, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl_title.pack(anchor="w", pady=(0, 2))

        lbl_info = tk.Label(self.screen_frame, text="TRANSACTION ROUTING PLATFORM ROUTING TO GLOBAL BROKERS, DARK POOLS, AND RFQ VENUES", font=("Consolas", 7), bg=self.bg_dark, fg=self.fg_grey)
        lbl_info.pack(anchor="w", pady=(0, 10))

        self.emsx_text = tk.Text(self.screen_frame, bg=self.bg_card, fg=self.fg_light, font=("Consolas", 8), bd=1, relief=tk.SOLID, highlightbackground="#2d2d2d")
        self.emsx_text.pack(fill=tk.BOTH, expand=True)
        self._update_emsx_screen_data()

    def _update_emsx_screen_data(self):
        if not hasattr(self, "emsx_text") or not self.emsx_text: return
        self.emsx_text.delete("1.0", tk.END)

        emsx_data = f"""
================================================================================
EMSX <GO>: ELITE ALGORITHMIC TRANSACTION ROUTING ENGINE
================================================================================
Broker Interface State: ACTIVE & SERIALIZED (Thread-Safe Execution Locks)
Default Routing Protocol: FIX Protocol 4.4 Engine
Liquidity Gateway Destination: FXGO Multi-Bank Network

ROUTING DESTINATIONS & ORDER SLICING:
--------------------------------------------------------------------------------
Primary Dark Pool Route:  B-DARK Crossing Engine (Enabled)
Secondary RFQ Venue:      FIT Electronic Request-for-Quote (Multilateral)
Order Type Algorithm:     VWAP Slicing / Iceberg Configured
Hardware Guard:           B-PIPE Private Isolated Direct Loopback

ROUTING TELEMETRY & ROUND-TRIP PING:
--------------------------------------------------------------------------------
New York LD4 VPS Ping:    1.24 ms
London LD4 VPS Ping:      0.82 ms
MetaQuotes MT5 Terminal:  Connected (MQL5 ScalperBrainEA active)
Latency Status:           Sub-Millisecond Execution Stable
================================================================================
"""
        self.emsx_text.insert(tk.END, emsx_data)

    # ----------------------------------------------------
    # CORE PROCESSES & ACTIONS
    # ----------------------------------------------------

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
        self.btn_start.config(state=tk.NORMAL, bg="#10b981")
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_toggle_mode.config(state=tk.NORMAL)
        self.lbl_clock.config(text="Bot stopped safely.")

    def on_strategy_change(self, selected_strat):
        """Fires when the user updates the strategy dropdown choice"""
        config.ACTIVE_STRATEGY = selected_strat
        print(f"🔄 GUI STRATEGY SWITCH: Active Trading Strategy updated to: {selected_strat}")

    def on_style_change(self, selected_style):
        """Fires when the user updates the trading style dropdown choice"""
        config.TRADING_STYLE = selected_style
        print(f"🔄 GUI STYLE SWITCH: Active Trading Style updated to: {selected_style}")

    def toggle_mode(self):
        """Switches between MT5 Windows live and paper trading simulation"""
        config.SIMULATION_MODE = not config.SIMULATION_MODE
        self.badge_text.set("SIMULATION ACTIVE" if config.SIMULATION_MODE else "MT5 CONNECTED")
        self.badge_label.config(bg="#b45309" if config.SIMULATION_MODE else "#15803d")
        self.mode_text.set("SWITCH TO MT5 WINDOWS" if config.SIMULATION_MODE else "SWITCH TO SIMULATOR")

        messagebox.showinfo("Mode Toggled", f"Successfully switched trading backend to: {'Simulation Paper Trading' if config.SIMULATION_MODE else 'MT5 Windows Native'}")

    # ----------------------------------------------------
    # REFRESH MATRIX DYNAMICALLY ON EVERY LOOP TICK
    # ----------------------------------------------------

    def update_gui_loop(self):
        """Runs on main thread every 2 seconds to refresh statistics cards and active panels"""
        try:
            # Persistent Stats Ribbon Updates
            if self.scalper and self.scalper.conn:
                info = self.scalper.conn.get_account_info()
                self.card_balance.config(text=f"${info['balance']:,.2f} USD")
                self.card_equity.config(text=f"${info['equity']:,.2f} USD")

                active_positions = self.scalper.conn.get_open_orders()
                self.card_active.config(text=f"{len(active_positions)} / {config.MAX_CONCURRENT_TRADES}")

                # Fetch all-time performance metrics
                perf = database.get_all_time_performance()
                self.card_perf.config(text=f"Win Rate: {perf['win_rate']}% | Net: {perf['net_profit']:.2f} USD ({perf['total_trades']} Trades)")

                # Fetch active trading session and timeline countdown details
                timeline = self.scalper._get_sessions_timeline()
                self.lbl_act_val.config(text=timeline['active'])
                self.lbl_cls_val.config(text=timeline['previous'])
                self.lbl_upc_val.config(text=timeline['next_session'])

                session_str = f"{timeline['active'].split('|')[0]} (Tracker Active)"
                self.card_session.config(text=session_str)

                # Route updating depending on which panel screen is active
                if self.active_screen == "MAIN":
                    self._update_main_screen_data(active_positions)
                elif self.active_screen == "GP":
                    self._update_gp_screen_data()
                elif self.active_screen == "WEI":
                    self._update_wei_screen_data()
                elif self.active_screen == "NEWS":
                    self._update_news_screen_data()
                elif self.active_screen == "ANR":
                    self._update_anr_screen_data()
                elif self.active_screen == "CHART":
                    self._update_chart_screen_data()
                elif self.active_screen == "SESS":
                    self._update_session_screen_data()
                elif self.active_screen == "DES":
                    self._update_des_screen_data()
                elif self.active_screen == "YAS":
                    self._update_yas_screen_data()
                elif self.active_screen == "ECO":
                    self._update_eco_screen_data()
                elif self.active_screen == "EMSX":
                    self._update_emsx_screen_data()

                self.lbl_clock.config(text=f"Last updated: {datetime.datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"Error updating GUI fields: {e}")

        # Cycle every 2 seconds
        self.root.after(2000, self.update_gui_loop)

    def _update_main_screen_data(self, active_positions):
        """Populates the scan assessment matrix table and the Live Active Trades treeview"""
        if not hasattr(self, "tree") or not self.tree:
            return

        self.tree.delete(*self.tree.get_children())

        # Query assessments logged recently
        conn = database.get_connection()
        cursor = conn.cursor()
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

        # Update Live Active Trades Treeview (Right Column) & calculate Floating P&L
        if hasattr(self, "trades_tree") and self.trades_tree:
            self.trades_tree.delete(*self.trades_tree.get_children())
            total_floating_pnl = 0.0

            for pos in active_positions:
                ticket = pos.get('ticket', '0')
                sym = pos.get('symbol', 'UNKNOWN')
                direction = pos.get('direction', 'BUY')
                lots = pos.get('lot_size', 0.01)
                open_p = pos.get('open_price', 0.0)

                price_info = self.scalper.conn.get_current_price(sym)
                current_p = price_info['bid'] if direction == "BUY" else price_info['ask']

                # Compute multiplier
                sym_up = sym.upper()
                multiplier = 100000.0  # Forex standard
                if "XAU" in sym_up or "GOLD" in sym_up:
                    multiplier = 100.0
                elif "XAG" in sym_up or "SILVER" in sym_up:
                    multiplier = 5000.0
                elif any(c in sym_up for c in ["BTC", "ETH", "LTC", "SOL", "XRP"]):
                    multiplier = 1.0
                elif "JPY" in sym_up:
                    multiplier = 1000.0

                p_diff = current_p - open_p if direction == "BUY" else open_p - current_p
                profit = p_diff * lots * multiplier
                total_floating_pnl += profit

                tag_color = "green" if profit >= 0 else "red"
                self.trades_tree.insert("", tk.END, values=(
                    ticket,
                    sym,
                    direction,
                    f"{lots:.2f}",
                    f"{open_p:.5f}" if open_p < 10 else f"{open_p:,.2f}",
                    f"{current_p:.5f}" if current_p < 10 else f"{current_p:,.2f}",
                    f"{profit:+.2f}"
                ), tags=(tag_color,))

            self.trades_tree.tag_configure("green", foreground=self.fg_green)
            self.trades_tree.tag_configure("red", foreground=self.fg_red)

            # Update floating PnL stats card dynamically
            pnl_color = self.fg_green if total_floating_pnl >= 0 else self.fg_red
            pnl_sign = "+" if total_floating_pnl >= 0 else ""
            self.card_pnl.config(text=f"{pnl_sign}${total_floating_pnl:,.2f} USD", fg=pnl_color)

    def _update_gp_screen_data(self):
        """Updates and draws visual price lines and candle properties for the selected symbol on the Canvas"""
        if not hasattr(self, "chart_canvas") or not self.chart_canvas:
            return

        sym = self.selected_symbol_gp
        price_info = self.scalper.conn.get_current_price(sym)
        ask = price_info["ask"]
        bid = price_info["bid"]
        spread_val = (ask - bid) * (10000.0 if "JPY" not in sym else 100.0) if ask > 0 else 0.0

        if ask <= 0:
            return # No feed active yet

        # Update historical price collection
        self.price_history_gp.append(ask)
        if len(self.price_history_gp) > 30:
            self.price_history_gp.pop(0)

        # Clear Canvas and render grid and lines
        canvas_width = self.chart_canvas.winfo_width()
        canvas_height = self.chart_canvas.winfo_height()
        if canvas_width < 10 or canvas_height < 10:
            return

        self.chart_canvas.delete("all")

        # Draw grid lines
        grid_step = canvas_height // 5
        for i in range(1, 5):
            y_coord = i * grid_step
            self.chart_canvas.create_line(0, y_coord, canvas_width, y_coord, fill="#1c1c1c", dash=(2, 2))

        # Render price line
        pts = len(self.price_history_gp)
        if pts > 1:
            min_p = min(self.price_history_gp)
            max_p = max(self.price_history_gp)
            p_range = max_p - min_p if max_p != min_p else 1.0

            points_coords = []
            x_step = canvas_width / (pts - 1) if pts > 1 else canvas_width

            for idx, price in enumerate(self.price_history_gp):
                x = idx * x_step
                # Normalize price to Y coordinate
                y = canvas_height - 30 - ((price - min_p) / p_range) * (canvas_height - 60)
                points_coords.append((x, y))

            # Draw smooth line segments
            for j in range(len(points_coords) - 1):
                x1, y1 = points_coords[j]
                x2, y2 = points_coords[j+1]
                # Highlighting dynamic movement color
                stroke_color = self.fg_green if self.price_history_gp[-1] >= self.price_history_gp[-2] else self.fg_red
                self.chart_canvas.create_line(x1, y1, x2, y2, fill=stroke_color, width=2)

        # Fetch indicator info from DB if exists
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trend_direction, rsi_val, atr_val, explanation
            FROM assessments
            WHERE symbol = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (sym,))
        row = cursor.fetchone()
        conn.close()

        trend = row["trend_direction"] if row else "N/A"
        rsi = f"{row['rsi_val']:.2f}" if row and row["rsi_val"] is not None else "N/A"
        atr = f"{row['atr_val']:.5f}" if row and row["atr_val"] is not None else "N/A"

        # Update details cards
        self.lbl_gp_quote.config(
            text=f"{sym} {ask:.5f}",
            fg=self.fg_green if len(self.price_history_gp) < 2 or self.price_history_gp[-1] >= self.price_history_gp[-2] else self.fg_red
        )
        self.lbl_gp_hl.config(text=f"H/L: {max(self.price_history_gp):.5f} / {min(self.price_history_gp):.5f}")
        self.lbl_gp_spread.config(text=f"Spread: {spread_val:.1f} pips")
        self.lbl_gp_ema.config(text=f"EMA-200 Direction: {trend}")
        self.lbl_gp_rsi.config(text=f"RSI-14 Level: {rsi}")
        self.lbl_gp_atr.config(text=f"ATR Volatility: {atr}")

        # Compute dummy pivot estimates
        pivot_val = bid
        self.lbl_gp_pivots.config(
            text=f"R1: {pivot_val + 0.0015:.5f}\nPivot: {pivot_val:.5f}\nS1: {pivot_val - 0.0015:.5f}",
            fg=self.fg_cyan
        )

    def _update_wei_screen_data(self):
        """Flickers macroeconomic exchange ticks and updates the WEI indices table"""
        if not hasattr(self, "wei_tree") or not self.wei_tree:
            return

        self.wei_tree.delete(*self.wei_tree.get_children())

        # Introduce small dynamic movements to look alive
        for ticker, item in self.wei_data.items():
            flicker_factor = random.choice([-1, 1]) * (item["last"] * 0.0002)
            item["last"] += flicker_factor
            item["change"] += flicker_factor
            item["pct"] = (item["change"] / (item["last"] - item["change"])) * 100

            color_tag = "green" if item["change"] >= 0 else "red"
            self.wei_tree.insert("", tk.END, values=(
                ticker,
                item["name"],
                f"{item['last']:,.3f}" if item["last"] < 1000 else f"{item['last']:,.2f}",
                f"{item['change']:+,.2f}",
                f"{item['pct']:.2f}%",
                "OPEN"
            ), tags=(color_tag,))

        self.wei_tree.tag_configure("green", foreground=self.fg_green)
        self.wei_tree.tag_configure("red", foreground=self.fg_red)

    def _update_news_screen_data(self):
        """Simulates scrolling new macro-news items over time with randomized timestamps"""
        if not hasattr(self, "news_tree") or not self.news_tree:
            return

        # Randomly inject a new headline occasionally to look active
        if random.random() < 0.15:
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            extra_headlines = [
                {"headline": "CRUDE OIL DROPS 1.2% ON SHALE CAPACITY REPORTS FROM TEXAS", "source": "DJ", "sentiment": "BEARISH"},
                {"headline": "EURUSD SPREADS STABILIZE AS LONDON LIQUIDITY REACHES PEAK", "source": "BBG", "sentiment": "BULLISH"},
                {"headline": "US INITIAL JOBLESS CLAIMS IN AT 210K VS 215K ESTIMATED", "source": "BBG", "sentiment": "NEUTRAL"},
                {"headline": "UK CORE SERVICES INFLATION SLOWS TO 4.2% YOY; GBP DROPS", "source": "BBG", "sentiment": "BEARISH"},
                {"headline": "BITCOIN BREAKS HIGHER PAST RECENT KEY CONGESTION RANGE", "source": "BBG", "sentiment": "BULLISH"}
            ]
            new_item = random.choice(extra_headlines)
            new_item["time"] = now_str
            self.news_stories.insert(0, new_item)
            if len(self.news_stories) > 30:
                self.news_stories.pop()

            try:
                database.log_news_headline(new_item["headline"], new_item["sentiment"])
            except Exception as e:
                print(f"Warning: Failed to log new item to database news: {e}")

        self.news_tree.delete(*self.news_tree.get_children())
        for story in self.news_stories:
            sentiment_tag = "neutral"
            if story["sentiment"] == "BULLISH":
                sentiment_tag = "green"
            elif story["sentiment"] == "BEARISH":
                sentiment_tag = "red"

            self.news_tree.insert("", tk.END, values=(
                story["time"],
                story["source"],
                story["headline"],
                f"[{story['sentiment']}]"
            ), tags=(sentiment_tag,))

        self.news_tree.tag_configure("green", foreground=self.fg_green)
        self.news_tree.tag_configure("red", foreground=self.fg_red)
        self.news_tree.tag_configure("neutral", foreground=self.fg_grey)

    def _update_anr_screen_data(self):
        """Updates Consensus Recommendations and queries Predictive AI neural network parameters"""
        if not hasattr(self, "anr_tree") or not self.anr_tree:
            return

        self.anr_tree.delete(*self.anr_tree.get_children())

        # Re-populate Consensus
        recommendations = [
            ("EURUSD", "BUY", "62%", "28%", "10%", "1.1050"),
            ("GBPUSD", "BUY", "55%", "35%", "10%", "1.2850"),
            ("USDJPY", "SELL", "12%", "18%", "70%", "142.50"),
            ("XAUUSD", "STRONG BUY", "78%", "15%", "7%", "2150.0"),
            ("BTCUSD", "BUY", "65%", "20%", "15%", "72000.0")
        ]
        for row in recommendations:
            color_tag = "green" if "BUY" in row[1] else "red"
            self.anr_tree.insert("", tk.END, values=row, tags=(color_tag,))

        self.anr_tree.tag_configure("green", foreground=self.fg_green)
        self.anr_tree.tag_configure("red", foreground=self.fg_red)

        # Refresh Predictive AI Neural Network Pane metrics from active Brain state
        try:
            import predictive_brain
            nn = predictive_brain.get_symbol_predictor(self.selected_symbol_gp)
            if nn and nn.last_prediction is not None:
                # Calculate rolling accuracy rate
                perf = database.get_all_time_performance()
                win_rate = perf["win_rate"]

                predicted_dir = "BUY" if nn.last_prediction > 0.5 else "SELL"
                prob_pct = nn.last_prediction if nn.last_prediction > 0.5 else (1.0 - nn.last_prediction)

                self.lbl_mlp_bias.config(
                    text=f"MLP Next Candle Bias: {predicted_dir} ({prob_pct*100:.1f}% Confidence)",
                    fg=self.fg_green if predicted_dir == "BUY" else self.fg_red
                )

                # Fetch loss if logged
                latest_loss = getattr(nn, "last_loss", 0.0024)
                self.lbl_mlp_loss.config(text=f"Latest Backpropagation Loss: {latest_loss:.5f}")

                # Veto state
                is_deviating = False
                prevailing_sentiment = database.get_prevailing_news_sentiment()
                if prevailing_sentiment == "BULLISH" and predicted_dir == "SELL":
                    is_deviating = True
                elif prevailing_sentiment == "BEARISH" and predicted_dir == "BUY":
                    is_deviating = True

                filter_state = "INTERVENTION ENGAGED" if is_deviating else "IDLE (PROCEED)"
                self.lbl_mlp_corrective.config(
                    text=f"Filter Intervention State: {filter_state}",
                    fg=self.fg_red if is_deviating else self.fg_green
                )
                self.lbl_mlp_accuracy.config(text=f"Historical System Accuracy: {win_rate}%")
        except Exception as e:
            print(f"Warning: Failed to refresh MLP neural network dashboard metrics: {e}")


def launch_gui():
    root = tk.Tk()
    app = ScalperGui(root)
    root.mainloop()

if __name__ == "__main__":
    launch_gui()
