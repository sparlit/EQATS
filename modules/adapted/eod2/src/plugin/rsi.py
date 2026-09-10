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


from argparse import ArgumentParser

from mplfinance import make_addplot
from pandas import Series
from ta.momentum import RSIIndicator

# To be added to src/defs/user.json
# "PLOT_PLUGINS": {
#     "RSI": {
#       "name": "rsi",
#       "overbought": 80,
#       "oversold": 20,
#       "line_color": "teal"
#     }
# }


def load(parser: ArgumentParser):
    parser.add_argument("--rsi", action="store_true", help="Relative strength index")


def main(df, plot_args, args, config):
    if args.rsi:
        opts = config.PLOT_PLUGINS["RSI"]

        df["RSI"] = RSIIndicator(close=df["Close"]).rsi()

        if "addplot" not in plot_args:
            plot_args["addplot"] = []

        OB_LINE = Series(data=opts["overbought"], index=df.index)
        OS_LINE = Series(data=opts["oversold"], index=df.index)

        plot_args["addplot"].extend(
            [
                make_addplot(
                    df["RSI"],
                    label="RSI",
                    panel="lower",
                    color=opts["line_color"],
                    ylabel="RSI",
                    width=2,
                ),
                make_addplot(
                    OB_LINE,
                    panel="lower",
                    color=opts["line_color"],
                    linestyle="dashed",
                    width=1.5,
                ),
                make_addplot(
                    OS_LINE,
                    panel="lower",
                    color=opts["line_color"],
                    linestyle="dashed",
                    width=1.5,
                ),
            ]
        )
