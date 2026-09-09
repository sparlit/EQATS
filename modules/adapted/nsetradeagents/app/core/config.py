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


from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All tunable parameters, with the values the backtest was measured on.

    Any field can be overridden from .env. Defaults here are the source of
    truth — .env.example deliberately does not repeat them.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    # LLM — unused while the pipeline is fully deterministic; the veto agent
    # will need these again. Optional so the app starts without them.
    anthropic_api_key: str | None = None
    tavily_api_key: str | None = None
    llm_model_veto: str = "claude-opus-5"

    # Portfolio
    starting_capital: float = 200000
    simulation_mode: bool = True

    # Database
    database_url: str = "sqlite:///swing_bot.db"

    # Risk
    max_positions: int = 5
    max_position_pct: float = 0.20
    # Flat fallbacks, used only when a stock's ATR is unknown. Every level is
    # otherwise scaled to volatility — see the exit ladder below.
    stop_loss_pct: float = 0.07
    take_profit_pct: float = 0.18
    max_hold_days: int = 21
    rules_confidence_threshold: float = 65

    # Regime gate: breadth of the traded universe, not an index. Nifty 50 rose
    # 9.2% in 2025 while the median mid/smallcap fell 5.3%.
    breadth_floor_pct: float = 50.0

    # Screener
    min_volume_ratio: float = 2.0
    min_volume_shares: int = 50000
    min_avg_daily_value: float = 2_00_00_000
    max_day_change_pct: float = 8.0
    min_price: float = 100.0
    min_atr_pct: float = 1.5
    rsi_min: float = 55.0
    rsi_max: float = 70.0
    regime_sma_period: int = 50

    # Fundamental filters
    min_market_cap: float = 5_00_00_00_000  # ₹500 Crore
    max_debt_to_equity: float = 200.0  # yfinance returns as %, 200 = 2.0x
    min_roe: float = 0.05
    max_revenue_decline_pct: float = -0.10
    max_pe_ratio: float = 100.0

    # Scoring adjustments
    vix_high_fear_level: float = 22.0
    vix_medium_fear_level: float = 18.0
    vix_high_fear_penalty: int = 20
    vix_medium_fear_penalty: int = 10
    nifty_20d_decline_threshold: float = -3.0
    nifty_10d_decline_threshold: float = -2.0
    round_number_levels: list[float] = Field(default=[500.0, 1000.0, 2000.0, 5000.0])
    resistance_proximity_pct: float = 0.02

    # Trailing stop
    trail_activation_pct: float = 0.12  # flat fallback when ATR is unknown
    trail_min_pct: float = 0.05  # floor for ATR-based trail
    trail_max_pct: float = 0.08  # cap for ATR-based trail

    # Exit ladder, in ATR multiples.
    # The target sits at the median favourable excursion over a 21-day hold, so
    # roughly half of trades reach it; the flat 18% was ~5.4x ATR and reached by
    # 19%. The trail must arm below the target or it never arms at all.
    stop_atr_mult: float = 2.5
    target_atr_mult: float = 4.0
    trail_arm_atr_mult: float = 2.0
    # Bounded for the same reason the stop is: a 1.5% ATR stock would otherwise
    # get a target tighter than its own stop.
    target_min_pct: float = 0.06
    target_max_pct: float = 0.20
    trail_arm_min_pct: float = 0.04
    trail_arm_max_pct: float = 0.12

    # Veto config
    veto_mode: str = "shadow"  # off | shadow | acting


settings: Settings = Settings()
