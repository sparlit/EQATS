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


"""
train_breakout_model.py
=======================
Trains a LightGBM AI model to predict next-week price breakouts
using historical NSE delivery data organized in Year/Month sub-folders.
"""

import glob
import os
import re

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split


def extract_date_from_filename(filename):
    """
    Fallback date parser that extracts DDMMYYYY from filenames like:
    'sec_bhavdata_full_15052023.csv' if the 'DATE' column has formatting issues.
    """
    match = re.search(r"sec_bhavdata_full_(\d{8})\.csv", filename)
    if match:
        return pd.to_datetime(match.group(1), format="%d%m%Y")
    return None


def load_and_clean_data(folder_path):
    """Gathers all nested daily full bhav files across Year/Month sub-folders."""
    print("Scanning nested folder structures for 2023 CSV files...")
    all_files = glob.glob(os.path.join(folder_path, "**/*.csv"), recursive=True)

    if not all_files:
        msg = f"No CSV files found in the path: {os.path.abspath(folder_path)}"
        raise ValueError(msg)

    print(f"Discovered {len(all_files)} data files. Compiling master history...")

    data_frames = []
    for file in all_files:
        try:
            df = pd.read_csv(file)
            df.columns = df.columns.str.strip()  # Clear trailing whitespaces from headers

            # Ensure the DATE column exists and is well-formatted
            if "DATE" in df.columns:
                df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
            else:
                file_date = extract_date_from_filename(os.path.basename(file))
                if file_date:
                    df["DATE"] = file_date
                else:
                    continue

            data_frames.append(df)
        except Exception:
            continue

    if not data_frames:
        msg = "Could not parse any valid text or date structures from files."
        raise ValueError(msg)

    df_merged = pd.concat(data_frames, ignore_index=True)
    df_merged = df_merged.dropna(subset=["DATE"])

    # ── THE CORE FIX: Force string objects into actual numeric types ──
    print("Converting text columns to numeric datatypes...")
    numeric_cols = ["DELIV_QTY", "DELIV_PER", "CLOSE_PRICE", "TURNOVER_LACS", "TTL_TRD_QTY"]
    for col in numeric_cols:
        if col in df_merged.columns:
            # errors='coerce' turns text artifacts like '-' or ' ' into NaN automatically
            df_merged[col] = pd.to_numeric(df_merged[col], errors="coerce")

    # Fill any broken rows or missing records cleanly
    df_merged["DELIV_QTY"] = df_merged["DELIV_QTY"].fillna(0)
    df_merged["DELIV_PER"] = df_merged["DELIV_PER"].fillna(0)

    # CRITICAL: Sort chronologically by Symbol and Date so rolling math applies correctly
    return df_merged.sort_values(by=["SYMBOL", "DATE"]).reset_index(drop=True)


def engineer_features_and_targets(df):
    """Engineers quant features and creates the 5-day breakout prediction target."""
    print("Engineering AI features and forward-looking targets...")

    # 1. Delivery Volume Dynamics
    df["DELIV_QTY_20MA"] = df.groupby("SYMBOL")["DELIV_QTY"].transform(lambda x: x.rolling(20).mean())
    df["DELIV_SPIKE_RATIO"] = df["DELIV_QTY"] / (df["DELIV_QTY_20MA"] + 1e-5)
    df["DELIV_PER_5MA"] = df.groupby("SYMBOL")["DELIV_PER"].transform(lambda x: x.rolling(5).mean())

    # 2. Price/Returns Momentum
    df["PRICE_RETURN_1D"] = df.groupby("SYMBOL")["CLOSE_PRICE"].pct_change(1) * 100
    df["PRICE_RETURN_5D"] = df.groupby("SYMBOL")["CLOSE_PRICE"].pct_change(5) * 100
    df["PRICE_VOLATILITY_20D"] = df.groupby("SYMBOL")["PRICE_RETURN_1D"].transform(lambda x: x.rolling(20).std())

    # 3. Total Traded Volume vs Delivery Volume interaction
    df["TOTAL_TURNOVER_5MA"] = df.groupby("SYMBOL")["TURNOVER_LACS"].transform(lambda x: x.rolling(5).mean())
    df["TURNOVER_SPIKE"] = df["TURNOVER_LACS"] / (df["TOTAL_TURNOVER_5MA"] + 1e-5)

    # CREATE TARGET (Look-forward 5 days)
    df["FUTURE_MAX_CLOSE_5D"] = df.groupby("SYMBOL")["CLOSE_PRICE"].transform(lambda x: x.shift(-5).rolling(5).max())

    # Target = 1 if stock achieves a >= 5% breakout over today's close price within next week
    df["BREAKOUT_TARGET"] = (df["FUTURE_MAX_CLOSE_5D"] >= df["CLOSE_PRICE"] * 1.05).astype(int)

    # Drop rows where window lookbacks or lookforwards cannot be computed mathematically
    return df.dropna(subset=["DELIV_QTY_20MA", "FUTURE_MAX_CLOSE_5D"]).copy()


def train_breakout_model(df):
    """Splits data sequentially to avoid data leaks and trains the LightGBM classifier."""
    feature_cols = [
        "DELIV_PER",
        "DELIV_SPIKE_RATIO",
        "DELIV_PER_5MA",
        "PRICE_RETURN_1D",
        "PRICE_RETURN_5D",
        "PRICE_VOLATILITY_20D",
        "TURNOVER_SPIKE",
    ]

    X = df[feature_cols]
    y = df["BREAKOUT_TARGET"]

    # Chronological split (No random shuffle) to mirror live production trading models
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    print(f"\nTraining set size: {X_train.shape[0]} rows")
    print(f"Testing set size: {X_test.shape[0]} rows")
    print(f"Base Breakout Rate in Test Set: {y_test.mean() * 100:.2f}%")

    params = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 6,
        "scale_pos_weight": (len(y_train) - sum(y_train)) / sum(y_train),  # Balances rare breakout events
        "verbose": -1,
        "random_state": 42,
    }

    train_data = lgb.Dataset(X_train, label=y_train)
    test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    print("\nTraining LightGBM Model...")
    model = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[test_data],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )

    preds_proba = model.predict(X_test)
    preds_binary = (preds_proba >= 0.5).astype(int)

    print("\n" + "=" * 40 + " EVALUATION METRICS " + "=" * 40)
    print(f"ROC-AUC Score: {roc_auc_score(y_test, preds_proba):.4f}")
    print("\nClassification Matrix:")
    print(classification_report(y_test, preds_binary))

    importance = pd.DataFrame(
        {"Feature": feature_cols, "Gain_Importance": model.feature_importance(importance_type="gain")}
    ).sort_values(by="Gain_Importance", ascending=False)

    print("\nFeature Importance Profile:")
    print(importance.to_string(index=False))

    return model


if __name__ == "__main__":
    DATA_PATH = "./HistoricalBhavCopy/NSE"

    try:
        raw_data = load_and_clean_data(DATA_PATH)
        processed_data = engineer_features_and_targets(raw_data)
        trained_model = train_breakout_model(processed_data)
        print("\nModel pipeline executed successfully!")
    except Exception as e:
        print(f"\nExecution failed: {e}")
