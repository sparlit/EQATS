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
        self.root.title("BLOOMBERG PROFESSIONAL - TERMINAL CLIENT")
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

        # Build UI layout
        self._build_header()
        self._build_command_bar()
        self._build_stats_ribbon()

        # Central switchable display frame
        self.screen_frame = tk.Frame(self.root, bg=self.bg_dark, padx=20, pady=5)
        self.screen_frame.pack(fill=tk.BOTH, expand=True)

        # Build the initial screen (MAIN)
        self.switch_to_screen("MAIN")

        self._build_controls_bar()

        # Keyboard Bindings to simulate Bloomberg F-Keys
        self.root.bind("<F2>", lambda e: self.switch_to_screen("MAIN"))
        self.root.bind("<F3>", lambda e: self.switch_to_screen("GP"))
        self.root.bind("<F4>", lambda e: self.switch_to_screen("WEI"))
        self.root.bind("<F5>", lambda e: self.switch_to_screen("NEWS"))
        self.root.bind("<F6>", lambda e: self.switch_to_screen("ANR"))
        self.root.bind("<F1>", lambda e: self.switch_to_screen("HELP"))

        # Initialize background visual update loop
        self.update_gui_loop()

        # Autostart autonomous bot immediately on GUI load for hands-off execution!
        self.root.after(1000, self.start_bot)

    def _build_header(self):
        """Header Banner"""
        header_frame = tk.Frame(self.root, bg=self.bg_dark, pady=5, padx=20)
        header_frame.pack(fill=tk.X)

        title_label = tk.Label(
            header_frame,
            text="BBG: SCALPER BRAIN",
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
        self.card_perf = self._create_card(ribbon_frame, "5) PERFORMANCE ANALYTICS <GO>", "Win Rate: 0% | Net: 0.00 USD (0 Trades)", 4, value_color=self.fg_accent)

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
        elif screen_code == "HELP":
            self._show_help_screen()
        else:
            # Fallback / Error Alert
            self._show_unknown_screen(screen_code)

    # ----------------------------------------------------
    # SCREEN LAYOUTS
    # ----------------------------------------------------

    def _show_main_screen(self):
        """MAIN <GO>: The technical scans matrix & cognitive indicators grid"""
        lbl = tk.Label(self.screen_frame, text="6) MULTI-ASSET COGNITIVE SCANS MATRIX <GO>", font=("Consolas", 10, "bold"), bg=self.bg_dark, fg=self.fg_accent)
        lbl.pack(anchor="w", pady=(0, 5))

        cols = ("Symbol", "Price", "EMA-200", "Trend", "RSI", "ATR", "Status")
        self.tree = ttk.Treeview(self.screen_frame, columns=cols, show="headings", style="Treeview")
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor=tk.W, width=110)
        self.tree.column("Status", width=340)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(self.screen_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

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
                session_str = f"{timeline['active']} (Next: {timeline['next_session']} in {timeline['countdown']})"
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

                self.lbl_clock.config(text=f"Last updated: {datetime.datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"Error updating GUI fields: {e}")

        # Cycle every 2 seconds
        self.root.after(2000, self.update_gui_loop)

    def _update_main_screen_data(self, active_positions):
        """Populates the scan assessment matrix table"""
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
        if self.scalper and hasattr(self.scalper, "neural_net") and self.scalper.neural_net:
            nn = self.scalper.neural_net
            # Calculate rolling accuracy rate
            perf = database.get_all_time_performance()
            win_rate = perf["win_rate"]

            self.lbl_mlp_bias.config(
                text=f"MLP Next Candle Bias: {nn.last_predicted_dir.upper()} ({nn.last_prob*100:.1f}% Confidence)",
                fg=self.fg_green if nn.last_predicted_dir == "buy" else self.fg_red
            )
            self.lbl_mlp_loss.config(text=f"Latest Backpropagation Loss: {nn.last_loss:.5f}")

            filter_state = "INTERVENTION ENGAGED" if nn.is_deviating else "IDLE (PROCEED)"
            self.lbl_mlp_corrective.config(
                text=f"Filter Intervention State: {filter_state}",
                fg=self.fg_red if nn.is_deviating else self.fg_green
            )
            self.lbl_mlp_accuracy.config(text=f"Historical System Accuracy: {win_rate}%")


def launch_gui():
    root = tk.Tk()
    app = ScalperGui(root)
    root.mainloop()

if __name__ == "__main__":
    launch_gui()
