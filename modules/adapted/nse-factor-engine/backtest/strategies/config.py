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
Backtest Strategy Engine — Configuration

Single source of truth for gate/score definitions, N, tiebreaker, RF.
"""

# ── Portfolio ─────────────────────────────────────────────────────────────────
N = 25
RF = 0.07
TIEBREAKER = "proximity_52w_high"
TIEBREAKER_ASCENDING = False

# ── Gate Variants ─────────────────────────────────────────────────────────────
# Precondition for ALL gates: in_universe == True
# Operators: 'eq', 'gt', 'gte', 'lt', 'lte', 'not_in'

GATE_DEFINITIONS = {
    "G2": [
        ("weinstein_stage2", "eq", True),
    ],
    "G3": [
        ("stpb_ret_21d", "gt", -0.05),
        ("proximity_52w_high", "gte", 0.80),
    ],
    "G4": [
        ("lottery_class", "not_in", {"LOTTERY", "BORDER_LOTTERY", "EXTREME LOTTERY"}),
    ],
    "G5": [
        ("weinstein_stage2", "eq", True),
        ("stpb_ret_21d", "gt", -0.05),
        ("proximity_52w_high", "gte", 0.80),
        ("lottery_class", "not_in", {"LOTTERY", "BORDER_LOTTERY", "EXTREME LOTTERY"}),
    ],
    "G6": [
        ("weinstein_stage2", "eq", True),
        ("lottery_class", "not_in", {"LOTTERY", "BORDER_LOTTERY", "EXTREME LOTTERY"}),
        ("rs_excess_ret_mkt", "gt", 0),
    ],
    "G7": [
        ("weinstein_stage2", "eq", True),
        ("lottery_class", "not_in", {"LOTTERY", "BORDER_LOTTERY", "EXTREME LOTTERY"}),
        ("rs_excess_ret_mkt", "gt", 0),
        ("vol_weinstein_asymmetry", "eq", True),
    ],
}

# ── Score Variants ────────────────────────────────────────────────────────────

SCORE_DEFINITIONS = {
    "C1": {
        "type": "single",
        "column": "rank_ret_12m1m",
        "ascending": True,
    },
    "C3": {
        "type": "average_ranks",
        "columns": ["rank_sharpe_style_momentum", "rank_sortino_style_momentum"],
        "ascending": True,
    },
    "C6": {
        # (rank_ret_12m1m + rank_alpha_12m1m_ew) with 1.2x multiplier on incumbents
        "type": "average_ranks",
        "columns": ["rank_ret_12m1m", "rank_alpha_12m1m_ew"],
        "ascending": True,
        "incumbent_multiplier": 1.2,
    },
    "C6RSI": {
        # C6 + RSI as third scoring component
        "type": "average_ranks",
        "columns": ["rank_ret_12m1m", "rank_alpha_12m1m_ew", "rank_rsi_14"],
        "ascending": True,
        "incumbent_multiplier": 1.2,
    },
    "C7_old": {
        # former C7 — no incumbent boost, kept for reference
        "type": "average_ranks",
        "columns": ["rank_ret_12m1m", "rank_alpha_12m1m_ew"],
        "ascending": True,
    },
    "C7": {
        # equal weight: rank_ret_12m1m + rank_ret_6m1m + rank_alpha_12m1m_ew
        "type": "average_ranks",
        "columns": ["rank_ret_12m1m", "rank_ret_6m1m", "rank_alpha_12m1m_ew"],
        "ascending": True,
        "incumbent_multiplier": 1.2,
    },
    "C7v2": {
        # double-weight rank_alpha_12m1m_ew: rank_ret_12m1m + rank_ret_6m1m + 2*rank_alpha_12m1m_ew
        # alpha component restored to ~50% effective weight
        "type": "weighted_composite",
        "components": [
            ("rank_ret_12m1m", 1, True),
            ("rank_ret_6m1m", 1, True),
            ("rank_alpha_12m1m_ew", 2, True),
        ],
        "ascending": True,
        "incumbent_multiplier": 1.2,
    },
    "C8": {
        # equal weight: rank_ret_12m1m + rank_ret_6m1m + rank_ret_3m1m + rank_alpha_12m1m_ew
        "type": "average_ranks",
        "columns": ["rank_ret_12m1m", "rank_ret_6m1m", "rank_ret_3m1m", "rank_alpha_12m1m_ew"],
        "ascending": True,
        "incumbent_multiplier": 1.2,
    },
}

# ── Momentum average input columns ────────────────────────────────────────────
MOMENTUM_RANK_COLS = [
    "rank_ret_12m1m",
    "rank_simple_vol_adj_momentum",
    "rank_sharpe_style_momentum",
]

# ── Full grid ─────────────────────────────────────────────────────────────────
GATE_IDS = ["G2", "G3", "G4", "G5", "G6", "G7"]
SCORE_IDS = ["C1", "C3", "C6", "C6RSI", "C7_old", "C7", "C8"]
CELLS = [
    ("G2", "C3"),
    ("G2", "C6"),
    ("G4", "C3"),
    ("G4", "C6"),
    ("G4", "C7_old"),
    ("G5", "C1"),
    ("G6", "C1"),
    ("G6", "C6"),
    ("G6", "C6RSI"),
    ("G6", "C7_old"),
    ("G6", "C7"),
    ("G6", "C8"),
    ("G7", "C6"),
]
