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


import setuptools

with open("README.md") as fh:
    long_description = fh.read()

setuptools.setup(
    name="TickerStore",
    version="0.0.8",
    author="Apoorva Singh",
    author_email="apoorva.singh157@gmail.com",
    description="Historical data of financial instruments from NSE",
    long_description=long_description,
    url="https://github.com/meticulousCraftman/tickerstore",
    license="MIT",
    install_requires=[
        "upstox",
        "python-dotenv",
        "Flask",
        "influxdb",
        "crayons",
        "nsepy",
        "pandas",
        "requests",
        "lxml",
        "loguru",
    ],
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
