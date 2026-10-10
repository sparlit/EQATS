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


# -*- coding: utf-8 -*-
"""
Spyder Editor

This is a temporary script file.
"""
# import atexit, os
import sys

import nseta
import setuptools  # noqa
from distutils.core import setup

__USERNAME__ = "pkjmesra"

with open("README.md") as fh:
    long_description = fh.read()
with open("common-requirements.txt") as fh:
    install_requires = fh.read().splitlines()

SYS_MAJOR_VERSION = str(sys.version_info.major)
SYS_VERSION = SYS_MAJOR_VERSION + "." + str(sys.version_info.minor)

WHEEL_NAME = "nseta-" + nseta.__version__ + "-py" + SYS_MAJOR_VERSION + "-none-any.whl"
TAR_FILE = "nseta-" + nseta.__version__ + ".tar.gz"
EGG_FILE = "nseta-" + nseta.__version__ + "-py" + SYS_VERSION + ".egg"
DIST_FILES = [WHEEL_NAME, TAR_FILE, EGG_FILE]
DIST_DIR = "dist/"

# def _post_build():
# 	if "bdist_wheel" in sys.argv:
# 		for count, filename in enumerate(os.listdir(DIST_DIR)):
# 			if filename in DIST_FILES:
# 				os.rename(DIST_DIR + filename, DIST_DIR + filename.replace('nseta-', 'nseta_'+__USERNAME__+'-'))

# atexit.register(_post_build)

(
    setup(
        name="nseta",
        packages=setuptools.find_packages(where=".", exclude=["docs", "tests"]),
        include_package_data=True,  # include everything in source control
        package_data={"nseta.resources": ["config.txt", "stocks.txt", "userstocks.txt"]},
        # ...but exclude README.txt from all packages
        exclude_package_data={"": ["*.yml"]},
        version=nseta.__version__,
        description="Library to scan, analyse and predict financial data from National Stock Exchange (NSE - India) in pandas dataframe ",
        long_description=long_description,
        long_description_content_type="text/markdown",
        author="Praveen K Jha",
        author_email=__USERNAME__ + "@gmail.com",
        license="OSI Approved (MIT)",
        url="https://github.com/" + __USERNAME__ + "/nseta",  # use the URL to the github repo
        zip_safe=False,
        entry_points="""
	[console_scripts]
	nsetacli=nseta.cli.nsetacli:nsetacli
	nseta=nseta.cli.nsetacli:nsetacli
	""",
        download_url="https://github.com/"
        + __USERNAME__
        + "/nseta/archive/v"
        + nseta.__version__
        + ".zip",
        classifiers=[
            "License :: OSI Approved :: MIT License",
            "Operating System :: OS Independent",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.6",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
        ],
        install_requires=install_requires,
        keywords=["NSE", "Technical Indicators", "Backtesting"],
        test_suite="tests",
    ),
)
python_requires = (">=3.6",)
