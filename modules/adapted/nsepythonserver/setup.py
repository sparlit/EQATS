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


import os

import setuptools

version = os.environ.get("PACKAGE_VERSION", "0.0.0")  # fallback if not set

with open("README.md") as fh:
    long_description = fh.read()

setuptools.setup(
    name="nsepythonserver",
    packages=setuptools.find_packages(),
    version=version,
    license="GNU",
    include_package_data=True,
    description="Python library for NSE India APIs",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Aeron7",
    author_email="dexter@unofficed.com",
    url="https://github.com/aeron7/nsepythonserver",
    install_requires=["requests", "pandas", "scipy"],
    keywords=["nseindia", "nse", "python", "sdk", "trading", "stock markets"],
    classifiers=[
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
