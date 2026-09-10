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
Configuration file for Indian Stock Exchange MCP Server
"""

import os
from pathlib import Path
from typing import Optional

# Load environment variables from .env file if it exists
env_file = Path(".env")
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


class Config:
    """Configuration class for ISE MCP Server"""

    # API Base URL - Replace with actual API URL
    BASE_URL: str = os.getenv("ISE_API_BASE_URL", "https://stock.indianapi.in/")

    # API Key - Must be provided via environment variable or .env file
    API_KEY: str | None = os.getenv("ISE_API_KEY")

    # Request timeout in seconds
    REQUEST_TIMEOUT: int = int(os.getenv("ISE_REQUEST_TIMEOUT", "30"))

    # Server configuration
    SERVER_NAME: str = "indian-stock-exchange"

    # HTTP Server configuration
    HTTP_HOST: str = os.getenv("ISE_HTTP_HOST", "0.0.0.0")
    HTTP_PORT: int = int(os.getenv("ISE_HTTP_PORT", "8000"))

    # Logging configuration
    LOG_LEVEL: str = os.getenv("ISE_LOG_LEVEL", "INFO")

    @classmethod
    def get_headers(cls) -> dict:
        """Get HTTP headers for API requests"""
        headers = {"Content-Type": "application/json", "User-Agent": "ISE-MCP-Server/1.0.0"}

        if cls.API_KEY:
            headers["Authorization"] = f"Bearer {cls.API_KEY}"

        return headers

    @classmethod
    def validate_config(cls) -> None:
        """Validate that required configuration is present"""
        if not cls.API_KEY:
            msg = (
                "ISE_API_KEY environment variable is required. "
                "Please set it in your .env file or environment variables."
            )
            raise ValueError(msg)
