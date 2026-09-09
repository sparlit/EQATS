import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    else:
        if dt.tzinfo is None:
            dt = ist.localize(dt)
        now = dt.astimezone(ist)
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
FinRL Trading Platform Setup
===========================

Setup script for the FinRL quantitative trading platform.
"""

from pathlib import Path

from setuptools import find_packages, setup

# Read README
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()


# Read core requirements
def read_requirements():
    requirements = []
    with open("requirements.txt") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("tensorflow") and not line.startswith("torch"):
                requirements.append(line)
    return requirements


setup(
    name="finrl_trading",
    version="2.0.2",
    author="FinRL LLC",
    author_email="contact@finrl.ai",
    description="A modern quantitative trading platform with ML strategies and live trading capabilities",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/AI4Finance-Foundation/FinRL-Trading",
    project_urls={
        "Bug Reports": "https://github.com/AI4Finance-Foundation/FinRL-Trading/issues",
        "Source": "https://github.com/AI4Finance-Foundation/FinRL-Trading",
        "Documentation": "https://finrl.readthedocs.io/",
    },
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Office/Business :: Financial :: Investment",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Framework :: AsyncIO",
        "Typing :: Typed",
    ],
    keywords="quantitative trading machine learning reinforcement learning alpaca finance",
    python_requires=">=3.11",
    install_requires=read_requirements(),
    extras_require={},
)
