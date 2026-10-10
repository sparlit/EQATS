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
Screeni-py Agent Package
Provides AI-native workflow with LLM-powered stock screening.
Lazy-imports to avoid circular imports with the openai-agents 'agents' package.
"""


def _get_screeni_agent():
    """Lazy import ScreeniAgent to avoid circular import with openai-agents package."""
    from .screeni_agent import ScreeniAgent

    return ScreeniAgent


def _get_agent_loader():
    """Lazy import AgentLoader."""
    from .agent_loader import AgentLoader

    return AgentLoader


# Only expose classes, not triggering imports at module load
__all__ = ["ScreeniAgent", "AgentLoader"]


def __getattr__(name):
    """Lazy attribute access to avoid import-time circular imports."""
    if name == "ScreeniAgent":
        return _get_screeni_agent()
    if name == "AgentLoader":
        return _get_agent_loader()
    raise AttributeError(f"module 'agents' (screenipy) has no attribute {name!r}")
