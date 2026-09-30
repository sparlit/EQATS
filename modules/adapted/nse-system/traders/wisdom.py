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


"""
Market Wisdom — structured reference data.

Cross-book principles, not a scanner. Consumed by:
  - terminal/static/wisdom.html (inlines its own copy)
  - future terminal UI panels via /api/wisdom
  - future AI sessions reading the codebase

Content mirrors MARKET_WISDOM.md exactly.

Rule R45: every book extraction contributes to this file. Singhal
(#14) is the first book under the rule.
"""

AXIOMS = [
    {
        "id": "trend",
        "principle": "Trade with the primary trend, never against it.",
        "detail": "The trend is the frame; patterns inside it are just timing.",
    },
    {
        "id": "risk_first",
        "principle": "Risk first, reward second.",
        "detail": "A 50% loss needs a 100% gain to recover. Small losses preserve optionality.",
    },
    {
        "id": "volume_confirms",
        "principle": "Volume confirms price.",
        "detail": "A move without volume is a move without conviction.",
    },
    {
        "id": "buy_support_sell_resistance",
        "principle": "Buy near support, sell near resistance. Never chase.",
        "detail": "The middle of a move is the worst place to enter.",
    },
    {
        "id": "consistency",
        "principle": "Consistency beats brilliance.",
        "detail": "Half the edge is execution discipline, not signal generation.",
    },
]


WISDOM = [
    # ---------------- TREND ----------------
    {
        "theme": "trend",
        "id": "trend_primary",
        "principle": "Trade with the primary trend, never against it.",
        "quant": "No fixed rule. Trend = higher highs + higher lows, or price above the 200 DMA.",
        "sources": ["McAllen", "O'Neil", "Patel & Kiri", "Ishaan", "Turtle", "Singhal"],
        "why": "Fighting the primary trend is the most expensive error in trading.",
        "violated_when": "Buying 'cheap' stocks; shorting strong uptrends; ignoring the index.",
    },
    {
        "theme": "trend",
        "id": "dma200_heartbeat",
        "principle": "The 200 DMA is the long-term heartbeat.",
        "quant": "Price above 200 DMA = offence. Below = defence. Rising slope > flat.",
        "sources": ["McAllen", "O'Neil", "Chande", "Singhal"],
        "why": "Cross above = new regime. Cross below = regime change.",
        "violated_when": "Buying below 200 DMA in a bull regime; ignoring slope.",
    },
    {
        "theme": "trend",
        "id": "secondary_pullbacks",
        "principle": "Secondary pullbacks inside a primary uptrend are noise.",
        "quant": "3-10 sessions, 6-25% deep, within an uptrend.",
        "sources": ["McAllen", "Ishaan", "Patel & Kiri", "Singhal"],
        "why": "Buying pullback gets tighter stop than buying breakout.",
        "violated_when": "Panicking on normal pullbacks; averaging down.",
    },
    {
        "theme": "trend",
        "id": "hh_hl_structure",
        "principle": "Higher highs + higher lows = intact uptrend.",
        "quant": "Last 3 swing highs rising AND last 3 swing lows rising.",
        "sources": ["McAllen", "O'Neil", "Chande", "Turtle", "Singhal"],
        "why": "Simple, structural. No indicators needed.",
        "violated_when": "Ignoring a lower high because news sounds good.",
    },
    {
        "theme": "trend",
        "id": "ma_stacking",
        "principle": "MA stacking: 10 > 20 > 50 > 200.",
        "quant": "Full stack aligned = strong trend. Any inversion = weakening.",
        "sources": ["Patel & Kiri", "Ishaan", "O'Neil", "Singhal"],
        "why": "Shows alignment across time horizons.",
        "violated_when": "Buying reversals while MAs are bearishly stacked.",
    },
    {
        "theme": "trend",
        "id": "golden_cross",
        "principle": "Golden cross = regime change to bullish.",
        "quant": "50 DMA crosses above 200 DMA. Fresh > old.",
        "sources": [
            "McAllen (implicit)",
            "Patel & Kiri",
            "Nison (13/26 EMA)",
            "Chande (100/350)",
            "Singhal (9/21 EMA)",
        ],
        "why": "Long-term regime change.",
        "violated_when": "Chasing a cross that already happened.",
    },
    {
        "theme": "trend",
        "id": "death_cross",
        "principle": "Death cross = regime change to bearish.",
        "quant": "50 DMA crosses below 200 DMA.",
        "sources": ["McAllen", "O'Neil (M gate)", "Patel & Kiri"],
        "why": "Internal strength has flipped.",
        "violated_when": "Continuing to buy 'dips' through the cross.",
    },
    {
        "theme": "trend",
        "id": "market_sideways_70pct",
        "principle": "70% of the time the market is sideways.",
        "quant": "Range-bound != trending. Trend-following works 30% of the time; range-trading works 70%.",
        "sources": ["Singhal"],
        "why": "Most losing trades come from applying trending tools in a range-bound market.",
        "violated_when": "Trend-following during confirmed sideways regimes.",
    },
    # ---------------- RISK & SIZING ----------------
    {
        "theme": "risk",
        "id": "cut_losses_fixed",
        "principle": "Cut every loss at a fixed percentage. No exception.",
        "quant": "7-8% below entry (O'Neil). 2x ATR (Chande, Patel, Singhal).",
        "sources": ["O'Neil", "Chande", "Patel & Kiri", "McAllen", "Singhal"],
        "why": "The insurance-premium rule. The single most important defensive rule.",
        "violated_when": "Averaging down; 'waiting for it to come back'; overriding the stop.",
    },
    {
        "theme": "risk",
        "id": "no_winner_to_loser",
        "principle": "Never let a 15-20% gain become a loss.",
        "quant": "At +15-20%, move stop to breakeven or above.",
        "sources": ["O'Neil"],
        "why": "Watching a winner turn red is the worst regret.",
        "violated_when": "'It'll come back' — it won't necessarily.",
    },
    {
        "theme": "risk",
        "id": "two_percent_rule",
        "principle": "Risk <= 2% of capital per trade.",
        "quant": "Size = (capital x 0.02) / (entry - stop).",
        "sources": ["Patel & Kiri", "O'Neil", "Chande", "Turtle", "Singhal"],
        "why": "20 losses at 2% ~ 33% DD. Survivable. At 5% = ~64%. Fatal.",
        "violated_when": "Sizing up because 'this one feels certain'.",
    },
    {
        "theme": "risk",
        "id": "loss_recovery_math",
        "principle": "A 50% loss needs a 100% gain to recover.",
        "quant": "10%->11%. 25%->33%. 50%->100%. 75%->300%. 90%->900%.",
        "sources": ["Patel & Kiri", "Singhal"],
        "why": "Compounding is asymmetric.",
        "violated_when": "'It's only a paper loss' — while it's still small.",
    },
    {
        "theme": "risk",
        "id": "small_losses_cost",
        "principle": "Small losses are the cost of doing business.",
        "quant": "Winning trades need only be ~40% if avg win is 3x avg loss.",
        "sources": ["O'Neil", "Turtle", "Chande"],
        "why": "A positive-expectancy system expects most trades to lose.",
        "violated_when": "Trying to avoid all losses.",
    },
    {
        "theme": "risk",
        "id": "size_by_volatility",
        "principle": "Position size by volatility, not conviction.",
        "quant": "Volatile stocks get smaller positions.",
        "sources": ["Turtle (1N rule)", "Chande"],
        "why": "Same dollar risk across all trades.",
        "violated_when": "Sizing up on 'the best setup of the year'.",
    },
    {
        "theme": "risk",
        "id": "half_kelly",
        "principle": "Half-Kelly with caps beats full Kelly.",
        "quant": "Half of Kelly fraction. Cap at 25% of capital. Fallback WR = 0.35.",
        "sources": ["O'Neil (pragmatic)", "Gray & Carlisle"],
        "why": "75% of growth with 50% of variance.",
        "violated_when": "Going all-in because 'math says so'.",
    },
    # ---------------- ENTRY TIMING ----------------
    {
        "theme": "entry",
        "id": "buy_on_close",
        "principle": "Buy on the breakout close, not intraday.",
        "quant": "Signal on daily close above pivot + 0.05%. Enter next open.",
        "sources": ["O'Neil", "Ishaan", "Patel & Kiri", "Nison", "Singhal"],
        "why": "Intraday breakouts frequently reverse by close.",
        "violated_when": "Anticipating the breakout.",
    },
    {
        "theme": "entry",
        "id": "wait_confirmation",
        "principle": "Wait for confirmation. Do not pre-empt.",
        "quant": "Breakout requires volume >= 1.4-1.5x average.",
        "sources": ["Ishaan", "O'Neil", "Patel & Kiri", "McAllen", "Singhal"],
        "why": "Unconfirmed breakouts have high false-positive rates.",
        "violated_when": "FOMO into a breakout you 'know' will work.",
    },
    {
        "theme": "entry",
        "id": "buy_new_highs",
        "principle": "Buy near new highs, not lows. (O'Neil Paradox.)",
        "quant": "Within 5% of 52-week high.",
        "sources": ["O'Neil", "O'Shaughnessy (RS)", "Turtle"],
        "why": "New highs attract institutional attention.",
        "violated_when": "Bottom-fishing 'because it can't go lower'.",
    },
    {
        "theme": "entry",
        "id": "pivot_buffer",
        "principle": "Entry at pivot + 0.05%. Never more than 5% extended.",
        "quant": "Buy zone = pivot to pivot x 1.05.",
        "sources": ["O'Neil", "Singhal"],
        "why": "Extended buys have wider stops, worse R/R.",
        "violated_when": "Chasing a stock that ran 15% above pivot.",
    },
    {
        "theme": "entry",
        "id": "volume_breakout",
        "principle": "Volume >= 1.4x average on breakout.",
        "quant": "140% of 20-day average. Ideal 2x+.",
        "sources": ["O'Neil", "Ishaan", "Patel & Kiri", "McAllen", "Singhal"],
        "why": "Volume = institutional participation.",
        "violated_when": "Ignoring volume because 'pattern is perfect'.",
    },
    {
        "theme": "entry",
        "id": "wait_gap_fill",
        "principle": "Wait for gap fill before entering.",
        "quant": "Breakaway gap -> wait for fill -> enter on confirmation (higher high).",
        "sources": ["McAllen", "Nison (windows)", ("Singhal (institutional gap retracement)")],
        "why": "Gaps are vacuums. Fills shake loose weak hands.",
        "violated_when": "Buying the gap on day 1.",
    },
    {
        "theme": "entry",
        "id": "reversal_candle_context",
        "principle": "Reversal candles need context: support + volume.",
        "quant": "Hammer/engulfing at validated support (>=2 prior touches) + volume >= 1.2x average.",
        "sources": ["Nison", "Ishaan", "McAllen", "Patel & Kiri"],
        "why": "A candle alone is a shape. Context makes it a signal.",
        "violated_when": "Trading candle patterns in isolation.",
    },
    {
        "theme": "entry",
        "id": "first_retracement_only",
        "principle": "First retracement only.",
        "quant": "When trading gap retracements, take the first retrace only. Second or third is a trap.",
        "sources": ["Singhal"],
        "why": "When the market touches the gap zone the second or "
        "third time, it can block funds and lead to sideways "
        "markets.",
        "violated_when": "Re-entering a gap zone after the first failed bounce.",
    },
    {
        "theme": "entry",
        "id": "longer_consolidation_stronger",
        "principle": "Longer consolidation = more reliable breakout.",
        "quant": "Base length correlates with breakout reliability. Minimum 5-7 weeks for swing bases.",
        "sources": ["Singhal", "O'Neil (flat base)", "Chande"],
        "why": "Longer consolidation = more significant buildup of buying/selling pressure.",
        "violated_when": "Trading breakouts from 3-day ranges as if they were real bases.",
    },
    {
        "theme": "entry",
        "id": "confluence_2_3_indicators",
        "principle": "At least two or three indicators must agree.",
        "quant": "Confluence of 2-3 signals. Never trade on a single indicator.",
        "sources": ["Singhal"],
        "why": "Single indicators have high false-positive rates. Confluence filters noise.",
        "violated_when": "Acting on RSI alone, MACD alone, or any single signal.",
    },
    # ---------------- EXIT DISCIPLINE ----------------
    {
        "theme": "exit",
        "id": "take_profits",
        "principle": "Take profits at 20-25% into strength.",
        "quant": "Target = entry x 1.225 (midpoint).",
        "sources": ["O'Neil"],
        "why": "Most winners give back 30-50% on reversal.",
        "violated_when": "'It's still going up — let it run'.",
    },
    {
        "theme": "exit",
        "id": "big_leaders_hold",
        "principle": "Big leaders: hold >=8 weeks after 20% in <3 weeks.",
        "quant": "Gain of 20% in under 15 sessions -> hold 40 sessions.",
        "sources": ["O'Neil"],
        "why": "Speed is the signal that this is not a normal trade.",
        "violated_when": "Applying usual profit-taking to a big leader.",
    },
    {
        "theme": "exit",
        "id": "65sma_3cc_exit",
        "principle": "Three consecutive closes below 65-SMA = exit.",
        "quant": "3 below 65-SMA. Faster variant: 3 below 50-SMA.",
        "sources": ["Chande"],
        "why": "Three consecutive closes = real trend change.",
        "violated_when": "Holding a clearly-broken position because fundamentals look fine.",
    },
    {
        "theme": "exit",
        "id": "trailing_stop_2r",
        "principle": "Trailing stop after +2R. Trail at the 5-day low.",
        "quant": "Once +2x initial risk in profit, trail at lowest low of last 5 sessions.",
        "sources": ["Chande", "Turtle (10-day variant)", "Singhal"],
        "why": "Locks in gains without giving back the whole move.",
        "violated_when": "Fixed stops hit on normal pullbacks.",
    },
    {
        "theme": "exit",
        "id": "climax_top",
        "principle": "Climax top signals = tighten stops.",
        "quant": "Largest daily run-up, heaviest volume, exhaustion gap, stock split.",
        "sources": ["O'Neil", "McAllen"],
        "why": "Climax means everyone who wanted in is already in.",
        "violated_when": "Buying into the climax because 'it's on the news'.",
    },
    {
        "theme": "exit",
        "id": "distribution_days",
        "principle": "Distribution day count >= 4-5 in 4-5 weeks = correction.",
        "quant": "Index down >0.2% on higher volume. Count. Threshold: 4-5 days.",
        "sources": ["O'Neil"],
        "why": "Distribution days are institutions selling.",
        "violated_when": "Buying breakouts into a distribution cluster.",
    },
    {
        "theme": "exit",
        "id": "sell_worst_first",
        "principle": "Sell your worst performer first; keep your best longest.",
        "quant": "When raising cash, cut the weakest setup first.",
        "sources": ["O'Neil", "Greenberg (Chieftain)"],
        "why": "Your best performers earned their hold. Dead money has not.",
        "violated_when": "Selling winners to 'lock in gains' while holding losers.",
    },
    {
        "theme": "exit",
        "id": "exit_on_opposite_signal",
        "principle": "Exit on opposite signal.",
        "quant": "When the entry's confirming signal flips (Supertrend, MACD, EMA cross), exit.",
        "sources": ["Singhal", "Nison", "Chande"],
        "why": "The setup's reason for existing has disappeared.",
        "violated_when": "Holding through a confirmed reversal.",
    },
    {
        "theme": "exit",
        "id": "time_based_exit_intraday",
        "principle": "Time-based exits for intraday setups.",
        "quant": "Exit at 3:15 PM (or 3:29 PM) for intraday positions. Options exits at 9:55 AM on expiry day.",
        "sources": ["Singhal"],
        "why": "Intraday positions held past close become overnight positions with different risk.",
        "violated_when": "Carrying an intraday setup into the next session.",
    },
    {
        "theme": "exit",
        "id": "structural_stop_pattern_low",
        "principle": "Structural stop at pattern's low.",
        "quant": "Stop below the pattern's structural low (swing low, candle low, cloud bottom).",
        "sources": ["Singhal", "Nison", "McAllen"],
        "why": "The setup is invalidated if the structural low is breached.",
        "violated_when": "Using a fixed % stop that gets hit before the pattern is actually invalid.",
    },
    # ---------------- VOLUME ----------------
    {
        "theme": "volume",
        "id": "vol_confirms",
        "principle": "Volume confirms price.",
        "quant": "Heavier on advances in uptrends; heavier on declines in downtrends.",
        "sources": ["McAllen", "O'Neil", "Nison", "Ishaan", "Singhal"],
        "why": "Volume = participation. Conviction or not.",
        "violated_when": "Trading a move with below-average volume.",
    },
    {
        "theme": "volume",
        "id": "vol_dryup_flag",
        "principle": "Volume dry-up in a flag or base = coiled spring.",
        "quant": "Flag volume <= 70% of 20-day average.",
        "sources": ["O'Neil", "Chande", "McAllen", "Singhal (VCP)"],
        "why": "Supply is exhausted. Breakout is inevitable (in context).",
        "violated_when": "Buying a base with rising volume — that's distribution.",
    },
    {
        "theme": "volume",
        "id": "low_vol_breakout_fails",
        "principle": "Low-volume breakouts fail more.",
        "quant": "<1.2x average has ~2x failure rate of high-volume breakouts.",
        "sources": ["O'Neil", "Ishaan", "Patel & Kiri", "Singhal"],
        "why": "No follow-through without volume.",
        "violated_when": "'It looks like it broke out' — volume was mediocre.",
    },
    {
        "theme": "volume",
        "id": "vol_climax",
        "principle": "Volume climax at extension = exhaustion.",
        "quant": "Heaviest daily volume of the move at the top of an advance.",
        "sources": ["O'Neil", "McAllen"],
        "why": "Last buyers capitulate to the price. Supply is about to overwhelm.",
        "violated_when": "Reading a top-tick volume spike as confirmation.",
    },
    {
        "theme": "volume",
        "id": "delivery_pct",
        "principle": "Delivery% (NSE) = institutional conviction proxy.",
        "quant": "Delivery >= 40-50% of traded quantity. Sustained high = accumulation.",
        "sources": ["India adaptation", "Singhal"],
        "why": "High delivery = shares moved into stronger hands.",
        "violated_when": "Reading traded quantity as accumulation.",
    },
    # ---------------- VALUE ----------------
    {
        "theme": "value",
        "id": "dollar_for_fifty",
        "principle": "Buy a dollar for 50 cents.",
        "quant": "Price <= 50% of intrinsic value.",
        "sources": ["Graham", "Lowe", "Greenwald", "O'Shaughnessy"],
        "why": "Margin of safety protects against error.",
        "violated_when": "'Close enough' at 20% discount.",
    },
    {
        "theme": "value",
        "id": "margin_cornerstone",
        "principle": "Margin of safety is the cornerstone of investment success.",
        "quant": "Value: 33-50% below intrinsic. Swing: R/R >= 2:1.",
        "sources": ["Graham", "Buffett (via Greenwald)", "Lowe", "Singhal (1:2 minimum)"],
        "why": "The single most important principle in value investing.",
        "violated_when": "Trading on 'opportunity' without a safety margin.",
    },
    {
        "theme": "value",
        "id": "price_dominant",
        "principle": "Price is dominant. Never let quality override price.",
        "quant": "EBIT/TEV decile 1 (cheapest 10%) beats any quality overlay.",
        "sources": ["Gray & Carlisle", "O'Shaughnessy"],
        "why": "Even wonderful companies are bad investments at the wrong price.",
        "violated_when": "Paying up for 'quality' — Magic Formula's structural flaw.",
    },
    {
        "theme": "value",
        "id": "low_psr_king",
        "principle": "Low PSR (P/S) is the king of value factors.",
        "quant": "PSR < 1.0. Beats low PE/PB/P/CF on risk-adjusted returns over 50 years.",
        "sources": ["O'Shaughnessy"],
        "why": "Sales are the hardest number to manipulate.",
        "violated_when": "Using PE alone and ignoring revenue.",
    },
    {
        "theme": "value",
        "id": "value_plus_rs",
        "principle": "Combine value with relative strength.",
        "quant": "Low PE + top-decile 1-yr RS = Sharpe 61 vs 46.",
        "sources": ["O'Shaughnessy", "Singhal (sector RS)"],
        "why": "Value + momentum = best risk-adjusted combo.",
        "violated_when": "Using value alone and buying falling knives.",
    },
    {
        "theme": "value",
        "id": "avoid_permanent_loss",
        "principle": "Avoid permanent loss first. Cleanse the universe.",
        "quant": "Eliminate top 5% on PROBM, PFD, STA, SNOA.",
        "sources": ["Gray & Carlisle"],
        "why": "Best picker in the world can't recover from a bankruptcy.",
        "violated_when": "Chasing yield in distressed names.",
    },
    {
        "theme": "value",
        "id": "growth_needs_franchise",
        "principle": "Growth outside the franchise destroys value.",
        "quant": "Only ROC > cost of capital creates value. Typically ROCE >= 15%.",
        "sources": ["Greenwald", "Buffett (via Greenwald)"],
        "why": "Growth requires capital. Low return on that capital = value tax.",
        "violated_when": "Buying growth in commodity industries.",
    },
    # ---------------- QUALITY ----------------
    {
        "theme": "quality",
        "id": "roce_floor",
        "principle": "ROCE >= 15-20% sustained = franchise proxy.",
        "quant": "ROCE >= 15% sustained 5-10 years. Prefer >= 20%.",
        "sources": ["Greenwald", "Lowe", "Parikh", "O'Shaughnessy"],
        "why": "Consistent high ROCE means competitive advantage.",
        "violated_when": "One-year high ROCE without checking consistency.",
    },
    {
        "theme": "quality",
        "id": "roe_rising",
        "principle": "ROE >= 17% and rising = compounder candidate.",
        "quant": "ROE >= 17% (prefer 25-50%). Rising trend over 3-5 years.",
        "sources": ["O'Neil", "Lowe", "Parikh"],
        "why": "Rising ROE = improving business quality.",
        "violated_when": "Flat-ROE businesses and expecting compounding.",
    },
    {
        "theme": "quality",
        "id": "geometric_quality",
        "principle": "8-year geometric ROA/ROC = volatility-adjusted quality.",
        "quant": "8-year geometric mean (not arithmetic) of ROA and ROC.",
        "sources": ["Gray & Carlisle"],
        "why": "Geometric means reveal volatility hidden by arithmetic.",
        "violated_when": "Using last year's ROE as a quality proxy.",
    },
    {
        "theme": "quality",
        "id": "franchise_gap",
        "principle": "Franchise = EPV - reproduction cost.",
        "quant": "Earnings Power Value minus reproduction cost of assets.",
        "sources": ["Greenwald"],
        "why": "The gap IS the franchise.",
        "violated_when": "Paying for 'quality' without checking franchise.",
    },
    {
        "theme": "quality",
        "id": "promoter_skin",
        "principle": "Promoter holding >= 51% = skin in the game (India).",
        "quant": "Promoter >= 51%. Pledge <= 20%.",
        "sources": ["Parikh"],
        "why": "Founders who own the business make owner decisions.",
        "violated_when": "Ignoring promoter holding because 'business looks good'.",
    },
    # ---------------- MARKET REGIME ----------------
    {
        "theme": "regime",
        "id": "three_of_four",
        "principle": "Three out of four stocks move with the market.",
        "quant": "Never fight the primary index trend. Filter gates all setups.",
        "sources": ["O'Neil", "McAllen"],
        "why": "Individual stocks are corralled by the market.",
        "violated_when": "Buying 'obvious' breakouts in a correction.",
    },
    {
        "theme": "regime",
        "id": "ema10_regime",
        "principle": "Index above EMA10 = bullish regime.",
        "quant": "Close > EMA10 with rising slope = x1.0 size. Below = x0.5 to x0.25.",
        "sources": ["Internal (regime.py)", "Turtle"],
        "why": "Fastest regime signal available.",
        "violated_when": "Ignoring regime and trading full size.",
    },
    {
        "theme": "regime",
        "id": "distribution_correction",
        "principle": "Distribution day count >= 4-5 in 4-5 weeks = correction.",
        "quant": "Index down >0.2% on higher volume. Threshold: 4-5 days.",
        "sources": ["O'Neil"],
        "why": "Distribution days are institutions selling.",
        "violated_when": "Staying long through a distribution cluster.",
    },
    {
        "theme": "regime",
        "id": "follow_through",
        "principle": "Follow-through day = new uptrend confirmation.",
        "quant": "Day 4-7 of rally: index up >=1.5% on higher volume than prior day.",
        "sources": ["O'Neil"],
        "why": "One up-day after decline isn't a trend change.",
        "violated_when": "Buying the first up-day and getting whipsawed.",
    },
    {
        "theme": "regime",
        "id": "breadth_healthy",
        "principle": "Breadth > 50% = healthy market.",
        "quant": "% above 50-EMA >= 50% AND advances >= declines.",
        "sources": ["Internal (breadth.py)", "O'Neil (implied)"],
        "why": "Breadth measures participation. Narrow rallies are fragile.",
        "violated_when": "Buying breakouts when 70% of stocks are below 50-EMA.",
    },
    {
        "theme": "regime",
        "id": "never_fight_index",
        "principle": "Never fight the index's primary trend.",
        "quant": "No new entries in confirmed correction.",
        "sources": ["O'Neil", "McAllen", "Turtle"],
        "why": "Market direction dominates stock direction.",
        "violated_when": "Conviction about a stock overrides market context.",
    },
    {
        "theme": "regime",
        "id": "high_vix_skip_trades",
        "principle": "High VIX = skip trades.",
        "quant": "India VIX > 40 is extreme. Adjust or skip.",
        "sources": ["Singhal"],
        "why": "High VIX increases drawdowns and whipsaws.",
        "violated_when": "Taking full-size positions during volatility spikes.",
    },
    {
        "theme": "regime",
        "id": "sector_rotation",
        "principle": "Sector rotation: buy the leading sector.",
        "quant": "Sector index RS above Nifty 50 -> buy highest-weight stock in that sector.",
        "sources": ["Singhal"],
        "why": "Money rotates between sectors. The leader gets the flow.",
        "violated_when": "Buying a stock in a lagging sector just because the chart looks good.",
    },
    # ---------------- PSYCHOLOGY ----------------
    {
        "theme": "psychology",
        "id": "circle_competence",
        "principle": "Know your circle of competence.",
        "quant": "Only trade setups you can explain in 60 seconds.",
        "sources": ["Buffett (via Greenwald)", "Lowe", "Turtle"],
        "why": "Edge comes from understanding.",
        "violated_when": "Trading a 'hot' theme you don't understand.",
    },
    {
        "theme": "psychology",
        "id": "consistency_wins",
        "principle": "Be consistent. Half the edge is execution.",
        "quant": "Execute every signal. Missing one big winner can wipe out a year.",
        "sources": ["Turtle", "Chande", "Singhal"],
        "why": "Good system executed poorly < mediocre system executed well.",
        "violated_when": "Skipping signals based on 'feel'.",
    },
    {
        "theme": "psychology",
        "id": "no_override",
        "principle": "No overriding the model.",
        "quant": "System says buy -> buy. System says sell -> sell.",
        "sources": ["Chande", "Gray & Carlisle", "O'Shaughnessy"],
        "why": "Discretion is where systematic edges die.",
        "violated_when": "'I know this one better'.",
    },
    {
        "theme": "psychology",
        "id": "when_in_doubt",
        "principle": "When in doubt, stay out.",
        "quant": "If setup requires interpretation beyond rules, skip it.",
        "sources": ["McAllen", "Turtle"],
        "why": "Missing a trade costs zero. A bad trade costs real money.",
        "violated_when": "Forcing trades because you're bored.",
    },
    {
        "theme": "psychology",
        "id": "no_fomo",
        "principle": "No FOMO. There is always another setup.",
        "quant": "Wait for the entry criteria. Not before.",
        "sources": ["McAllen", "Turtle", "O'Neil"],
        "why": "Missing a move costs nothing. Chasing costs real money.",
        "violated_when": "Buying extended because 'it keeps going up'.",
    },
    {
        "theme": "psychology",
        "id": "learn_from_losses",
        "principle": "Learning from losses is the fastest path.",
        "quant": "Review every loss. Log the failure condition.",
        "sources": ["Turtle", "Chande", "O'Neil"],
        "why": "Losses are the tuition. Ignoring wastes it.",
        "violated_when": "Blaming the market, news, or broker.",
    },
    {
        "theme": "psychology",
        "id": "never_trade_without_plan",
        "principle": "Never trade without a plan.",
        "quant": "No plan = guaranteed capital erosion.",
        "sources": ["Singhal"],
        "why": "An intraday trader with no plan has a high probability of eroding capital.",
        "violated_when": "Discretionary trades without predefined entry, stop, target.",
    },
    {
        "theme": "psychology",
        "id": "avoid_overtrading",
        "principle": "Avoid overtrading.",
        "quant": "Limit trades per session. Book caps at 3 per session for scalping/options.",
        "sources": ["Singhal"],
        "why": "Most losses come from too many trades, not bad ones.",
        "violated_when": "Taking multiple correlated signals in one session.",
    },
    {
        "theme": "psychology",
        "id": "avoid_analysis_paralysis",
        "principle": "Avoid analysis paralysis.",
        "quant": "Keep systems simple. Use <=3-5 indicators per strategy.",
        "sources": ["Singhal", "Chande", "Turtle"],
        "why": "Simple systems survive. Complex systems confuse.",
        "violated_when": "Adding indicators to 'improve' a working system.",
    },
    {
        "theme": "psychology",
        "id": "trading_journal",
        "principle": "Keep a trading journal.",
        "quant": "Record every trade - setup, entry, exit, reasoning, outcome.",
        "sources": ["Singhal"],
        "why": "Pattern recognition improves when you review your own history.",
        "violated_when": "Relying on memory for past trades.",
    },
    {
        "theme": "psychology",
        "id": "start_small",
        "principle": "Start small.",
        "quant": "Paper or demo first. Small capital before scaling.",
        "sources": ["Singhal"],
        "why": "Losses on small capital are cheaper tuition.",
        "violated_when": "Deploying full capital on a new strategy before backtesting.",
    },
    # ---------------- PROCESS ----------------
    {
        "theme": "process",
        "id": "positive_expectation",
        "principle": "Positive expectation required.",
        "quant": "Expectancy = (WR x avg_win) - ((1-WR) x avg_loss). Must be > 0.",
        "sources": ["Chande", "Turtle", "Patel & Kiri"],
        "why": "Negative-expectancy systems lose no matter how pretty the entries.",
        "violated_when": "Trading because 'entries look great' without expectancy check.",
    },
    {
        "theme": "process",
        "id": "simple_rulesets",
        "principle": "Small rulesets beat complex systems.",
        "quant": "<=5 rules per strategy.",
        "sources": ["Chande", "Turtle", "O'Shaughnessy"],
        "why": "Simple systems survive parameter shifts.",
        "violated_when": "Adding rules to 'improve' a system.",
    },
    {
        "theme": "process",
        "id": "robust_params",
        "principle": "Robust parameters, no curve-fitting.",
        "quant": "Performance must not collapse on +/-20% parameter changes.",
        "sources": ["Chande", "Turtle"],
        "why": "Parameter that only works at 20.0 is noise.",
        "violated_when": "Optimising to the last decimal.",
    },
    {
        "theme": "process",
        "id": "backtest_realistic",
        "principle": "Backtest with slippage, commission, survivorship bias.",
        "quant": "Slippage 0.1%, commission 0.05%, delisted included.",
        "sources": ["Chande", "Gray & Carlisle", "O'Shaughnessy", "Singhal"],
        "why": "A backtest without these is a fairy tale.",
        "violated_when": "Claiming '20% CAGR' from clean-data backtest.",
    },
    {
        "theme": "process",
        "id": "log_everything",
        "principle": "Log every run. Evidence over opinion.",
        "quant": "strategy_runs table: date, params, PF, DD, verdict.",
        "sources": ["Internal", "Chande"],
        "why": "Memory is unreliable. Logs are the audit trail.",
        "violated_when": "Relying on 'I remember the PF was ~1.4'.",
    },
]


THEMES = {
    "trend": "Trend",
    "risk": "Risk & Position Sizing",
    "entry": "Entry Timing",
    "exit": "Exit Discipline",
    "volume": "Volume",
    "value": "Value & Fundamentals",
    "quality": "Quality & Franchise",
    "regime": "Market Regime",
    "psychology": "Psychology & Discipline",
    "process": "Process & Validation",
}


def by_theme(theme):
    return [w for w in WISDOM if w["theme"] == theme]


def by_source(source_substring):
    """Return principles whose sources include the given substring."""
    s = source_substring.lower()
    return [w for w in WISDOM if any(s in src.lower() for src in w.get("sources", []))]


def search(query):
    q = query.lower()
    out = []
    for w in WISDOM:
        blob = " ".join(
            [
                w.get("principle", ""),
                w.get("quant", ""),
                w.get("why", ""),
                w.get("violated_when", ""),
                " ".join(w.get("sources", [])),
            ]
        ).lower()
        if q in blob:
            out.append(w)
    return out


def count():
    return {
        "total": len(WISDOM),
        "axioms": len(AXIOMS),
        "themes": len(THEMES),
        "per_theme": {k: len(by_theme(k)) for k in THEMES},
    }


if __name__ == "__main__":
    import json

    print(json.dumps(count(), indent=2))
