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


from setuptools import find_packages, setup

with open("README.md", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="trendmaster",
    version="0.2.3",
    author="Hemang Joshi",
    author_email="hemangjoshi37a@gmail.com",
    description="Stock Price Prediction using Transformer Deep Learning Architecture",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/hemangjoshi37a/TrendMaster",
    packages=find_packages(exclude=["Training", "Inference"]),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    python_requires=">=3.7",
    install_requires=[
        "numpy",
        "pandas",
        "torch",
        "transformers",
        "matplotlib",
        "tqdm",
        "joblib",
        "scikit-learn",
        "jugaad-trader",
    ],
    entry_points={
        "console_scripts": [
            "trendmaster=trendmaster.cli:main",
        ],
    },
)
