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


import backtrader as bt
from bot import *

from utils import *


class NSEStrategy(bt.Strategy):
    params = (("symbol", ""),)

    def __init__(self):
        data = pd.DataFrame(
            {
                "High": list(self.datas[0].high),
                "Close": list(self.datas[0].close),
                "Open": list(self.datas[0].open),
                "Low": list(self.datas[0].low),
            },
            index=list(self.datas[0]),
        )
        self.data = calculate_indicators(data).fillna(0)
        self.order = None

    def next(self):
        # Get the current data and apply the strategy function
        data = strategy(self.data)

        if isinstance(data, pd.core.frame.DataFrame):
            # Check if there is a position to take
            if data["Positions"][0] == "Buy":
                self.order = self.buy(price=data["Entry"][0], exectype=bt.Order.Market)

            if data["Positions"][0] == "Sell":
                self.order = self.sell(price=data["Entry"][0], exectype=bt.Order.Market)

            if not os.path.exists(bot_dir):
                os.makedirs(bot_dir)

            excel_file_path = os.path.join(bot_dir, "backtest.xlsx")
            data.to_excel(excel_file_path, header=True, index=False, engine="openpyxl")

    def stop(self):
        print("Finished")


if __name__ == "__main__":
    cerebro = bt.Cerebro()
    # Set the initial cash value
    cerebro.broker.setcash(100000.0)

    # Configure commissions
    cerebro.broker.setcommission(commission=10.0, margin=False)

    # Specify slippage
    cerebro.broker.set_slippage(slip_open=0.50, slip_close=0.50)

    # Configure margin requirements
    cerebro.broker.set_margin(perc=10.0)

    data = bt.feeds.PandasData(dataname=get_historical_data("^NSEI"))  # ^NSEI
    cerebro.adddata(data)
    cerebro.addstrategy(NSEStrategy, symbol="^NSEI")

    print(f"Starting Portfolio Value: {cerebro.broker.getvalue():.2f}")

    cerebro.run()

    print(f"Final Portfolio Value: {cerebro.broker.getvalue():.2f}")

    cerebro.plot()
