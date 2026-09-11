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


"""Starter PyBroker model training script.

Copy this file into a project and adapt the symbols, dates, features,
training function, and execution rules to the user's model.
"""

import pybroker

# Not PyBroker dependencies: pip install yfinance scikit-learn
from pybroker import ExecContext, Strategy, StrategyConfig, YFinance
from pybroker.indicator import close_minus_ma
from sklearn.linear_model import LinearRegression

SYMBOLS = ["AAPL", "MSFT"]
START_DATE = "1/1/2020"
END_DATE = "1/1/2024"
LOOKBACK = 20
MODEL_NAME = "next_return"

# Cache downloaded data, indicators, and trained models across runs.
pybroker.enable_caches("model_training_template")
# Progress bars flood AI token context and add nothing to a log file.
pybroker.disable_progress_bar()

cmma_20 = close_minus_ma("cmma_20", lookback=LOOKBACK, atr_length=14)


def train_fn(symbol: str, train_data, test_data):
    # train_fn is the sanctioned pandas boundary: PyBroker hands it
    # DataFrames. Copy so the input frame is never widened or mutated.
    df = train_data.copy()
    # Target is the NEXT bar's return, matching walkforward lookahead=1.
    df["target"] = df["close"].shift(-1) / df["close"] - 1
    df = df.dropna()
    model = LinearRegression()
    model.fit(df[["cmma_20"]], df["target"])
    # Pin the columns used as prediction input.
    return model, ["cmma_20"]


model_source = pybroker.model(MODEL_NAME, train_fn, indicators=[cmma_20])


# Execution logic reads ctx.* NumPy arrays — never pandas. The arrays hold
# completed bars only, so ctx.close[-1] is the current bar, never the future.
def exec_fn(ctx: ExecContext):
    pred = ctx.preds(MODEL_NAME)[-1]
    if not ctx.long_pos():
        if pred > 0:
            # Fills on the NEXT bar (buy_delay=1) at PriceType.MIDDLE, that
            # bar's low/high midpoint, unless ctx.buy_fill_price is set.
            ctx.buy_shares = ctx.calc_target_shares(0.5)
    elif pred < 0:
        ctx.sell_all_shares()


def build_strategy() -> Strategy:
    config = StrategyConfig(
        initial_cash=100_000,
        # Defaults to False, which leaves the final position open: it never
        # becomes a Trade, so trade_count, win_rate and total_pnl exclude it
        # and its P&L sits in unrealized_pnl. Exits fill at
        # exit_sell_fill_price / exit_cover_fill_price, both PriceType.MIDDLE.
        exit_on_last_bar=True,
    )
    strategy = Strategy(YFinance(), START_DATE, END_DATE, config)
    strategy.add_execution(exec_fn, SYMBOLS, models=model_source)
    return strategy


if __name__ == "__main__":
    result = build_strategy().walkforward(
        windows=3,
        train_size=0.5,
        lookahead=1,  # bars ahead of the prediction target
        warmup=LOOKBACK,
        # calc_bootstrap is a walkforward/backtest parameter, not a
        # StrategyConfig field. True adds result.bootstrap: BCa confidence
        # intervals for profit factor and Sharpe, plus percentile bounds on
        # max drawdown — error bars around the model's out-of-sample edge.
        # A profit factor interval whose lower bound sits below 1 means the
        # edge is not distinguishable from noise at that confidence.
        # calc_bootstrap=True,
    )
    print(result.metrics_df)
    # Structured output for agents/reports: result.to_json_str() serializes
    # metrics, trades, orders, and bootstrap; cap tables with max_rows=.
