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


from os import path

from setuptools import find_packages, setup

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="mftool",
    version="3.4",
    author="SujitN",
    author_email="nayakwadi_sujit@rediffmail.com",
    description="Library for getting real time Mutual funds info",
    license="MIT",
    keywords="amfi, quote, mutual-funds, funds, bse, nse, market, stock, stocks",
    install_requires=["requests", "bs4", "httpx", "pandas", "yfinance", "matplotlib", "deprecated"],
    url="https://github.com/NayakwadiS/mftool",
    packages=find_packages(include=["mftool", "mftool.*"]),
    long_description=long_description,
    long_description_content_type="text/markdown",
    package_data={"mftool": ["*.json"]},
)
