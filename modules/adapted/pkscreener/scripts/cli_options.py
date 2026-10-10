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
import sys

# sys.path.append('/path/to/pkscreener')  # Replace with the actual path to the pkscreener directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pkscreener.classes.MenuOptions import (
    CANDLESTICK_DICT,
    PREDEFINED_SCAN_MENU_KEYS,
    level2_X_MenuDict,
    level3_X_ChartPattern_MenuDict,
    level3_X_PopularStocks_MenuDict,
    level3_X_PotentialProfitable_MenuDict,
    level3_X_Reversal_MenuDict,
    level3_X_StockPerformance_MenuDict,
    level4_X_ChartPattern_BBands_SQZ_MenuDict,
    level4_X_ChartPattern_Confluence_MenuDict,
    level4_X_ChartPattern_MASignalMenuDict,
    level4_X_Lorenzian_MenuDict,
)


def get_all_menu_options():
    options = []

    # For X options
    indices = ["12"]  # [k for k in level1_X_MenuDict.keys() if k.isnumeric()]
    scans = [k for k in level2_X_MenuDict if k.isnumeric() and k not in ["0", "50", "M", "Z"]]

    sub_menus = {
        "6": level3_X_Reversal_MenuDict,
        "7": level3_X_ChartPattern_MenuDict,
        "30": level3_X_PotentialProfitable_MenuDict,
        "21": level3_X_PopularStocks_MenuDict,
        "3": level3_X_StockPerformance_MenuDict,
    }

    sub_sub_menus = {
        ("6", "7"): level4_X_Lorenzian_MenuDict,  # Reversal > Lorentzian
        ("7", "7"): CANDLESTICK_DICT,  # Chart Patterns > Candlestick
        ("7", "8"): level4_X_ChartPattern_MASignalMenuDict,  # Chart Patterns > VCP (Mark Minervini)
        ("7", "3"): level4_X_ChartPattern_Confluence_MenuDict,  # Chart Patterns > Confluence
        ("7", "6"): level4_X_ChartPattern_BBands_SQZ_MenuDict,  # Chart Patterns > Bollinger Bands
    }

    for index in indices:
        for scan in scans:
            if scan in sub_menus:
                for sub in sub_menus[scan]:
                    if sub == "0" or sub_menus[scan][sub] in ["Any/All", "Cancel"]:
                        continue
                    if (scan, sub) in sub_sub_menus:
                        for sub_sub in sub_sub_menus[(scan, sub)]:
                            if sub_sub == "0" or sub_sub_menus[(scan, sub)][sub_sub] in [
                                "Any/All",
                                "Cancel",
                            ]:
                                continue
                            options.append(f"X:{index}:{scan}:{sub}:{sub_sub}:D:D:D:D")
                    else:
                        options.append(f"X:{index}:{scan}:{sub}:D:D:D:D")
            else:
                options.append(f"X:{index}:{scan}:D:D:D:D")
    # For P options
    p_level1 = ["1"]  # [k for k in level1_P_MenuDict.keys() if k.isnumeric()]
    for p1 in p_level1:
        if p1 == "1":
            # Predefined piped scanners
            for p2 in PREDEFINED_SCAN_MENU_KEYS:
                options.append(f"P:{p1}:{p2}:12")
        else:
            # Other P options (2, 3, 4) - assuming no further sub-menus based on available data
            options.append(f"P:{p1}")

    return sorted(options)


def run_command(option):
    import subprocess

    env = os.environ.copy()
    env["RUNNER"] = "1"
    cmd = ["python3.12", "pkscreener/pkscreenercli.py", "-l", "-e", "-a", "Y", "-o", option]
    print(f"Running: {' '.join(cmd)}")
    output_dir = os.path.join(os.path.dirname(__file__), "run_outputs")
    os.makedirs(output_dir, exist_ok=True)
    filename = option.replace(":", "_") + ".txt"
    filepath = os.path.join(output_dir, filename)
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    with open(filepath, "w") as f:
        f.write("STDOUT:\n")
        f.write(result.stdout)
        f.write("\nSTDERR:\n")
        f.write(result.stderr)


if __name__ == "__main__":
    options = get_all_menu_options()
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(
        max_workers=4
    ) as executor:  # Limit to 4 parallel processes to avoid overloading
        executor.map(run_command, options)
