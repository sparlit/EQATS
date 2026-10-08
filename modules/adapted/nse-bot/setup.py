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


import sys

from cx_Freeze import Executable, setup

from utils import resource_path

icon = resource_path("logo.ico")

# List of files to be included in the package
files = [
    "run.py",
    "bot.py",
    "logo.ico",
    "backtest.py",
    "__init__.py",
    "utils.py",
    "bot_interface.py",
]

# Options for cx_Freeze
shortcut_table = [
    (
        "DesktopShortcut",
        "DesktopFolder",
        "NSE BOT",
        "TARGETDIR",
        "[TARGETDIR]run.exe",
        None,
        None,
        None,
        icon,
        None,
        None,
        "TARGETDIR",
    ),
]

options = {
    "build_exe": {
        "include_files": files,
        "packages": ["os", "sys", "site", "tkinter", "backtrader", "plyer"],
    },
    "bdist_msi": {
        "upgrade_code": "{d42722e4-b464-46d8-bb7c-89f435c7c90d}",
        "add_to_path": False,
        "initial_target_dir": "[ProgramFilesFolder]\\NSE BOT",
        "data": {
            "Shortcut": shortcut_table,
        },
    },
}

# base="Win32GUI" should be used only for Windows GUI app
base = "Win32GUI" if sys.platform == "win32" else None

# Define the executable file
executables = [Executable("run.py", base=base, icon=icon)]

# Call the setup() function
setup(
    name="NSE BOT", version="1.0", description="NSE BOT", options=options, executables=executables
)
