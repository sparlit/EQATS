import datetime
from datetime import datetime as dt_class
from pathlib import Path
from typing import Optional, Tuple

import click
import numpy as np
import pandas as pd
import pytz
from common.generators import generate_feature_set
from common.model_store import ModelStore
from service.App import App, load_config


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else dt_class.now(ist)
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
Apply feature generators
"""


@click.command()
@click.option("--config_file", "-c", type=click.Path(), default="", help="Configuration file name")
def main(config_file: str) -> None:
    load_config(config_file)
    config = App.config

    App.model_store = ModelStore(config)
    App.model_store.load_models()

    time_column = config["time_column"]

    dt_class.now()

    symbol = config["symbol"]
    data_path = Path(config["data_folder"]) / symbol

    # Determine desired data length depending on train/predict mode
    is_train = config.get("train", False)
    window_size = config.get("train_length") if is_train else config.get("predict_length")
    features_horizon = config.get("features_horizon", 0)
    if window_size:
        window_size += features_horizon

    #
    # Load merged data with regular time series
    #
    file_path = data_path / config.get("merge_file_name", "")
    if not file_path.is_file():
        print(f"Data file does not exist: {file_path}")
        return

    print(f"Loading data from source data file {file_path}...")
    if file_path.suffix == ".parquet":
        df = pd.read_parquet(file_path)
    elif file_path.suffix == ".csv":
        df = pd.read_csv(file_path, parse_dates=[time_column], date_format="ISO8601")
    else:
        print(
            f"ERROR: Unknown extension of the input file '{file_path.suffix}'. Only 'csv' and 'parquet' are supported"
        )
        return

    print(f"Finished loading {len(df)} records with {len(df.columns)} columns from the source file {file_path}")

    # Select only the data necessary for analysis
    if window_size:
        df = df.tail(window_size)
        df = df.reset_index(drop=True)

    print(f"Input data size {len(df)} records. Range: [{df.iloc[0][time_column]}, {df.iloc[-1][time_column]}]")

    #
    # Generate derived features
    #
    feature_sets = config.get("feature_sets", [])
    if not feature_sets:
        print("ERROR: no feature sets defined in configuration")
        return

    for feature_set in feature_sets:
        print(f"Generating feature set: {feature_set}")
        df = generate_feature_set(df, feature_set, config)

    # Save processed data
    output_file = data_path / config.get("features_file_name", "features.parquet")
    df.to_parquet(output_file, index=False)
    print(f"Saved {len(df)} records with {len(df.columns)} columns to {output_file}")


if __name__ == "__main__":
    main()
