"""
data_pipeline.py
================
Fetches, cleans, quality-checks, and persists historical Bank Nifty OHLC data.

Pipeline steps
--------------
1. Attempt yfinance download for ticker (^NSEBANK).
2. On API failure, fall back to the local CSV cache.
3. Compute log returns and rolling volatilities.
4. Run data-quality checks: missing dates, split artifacts, stationarity (ADF).
5. Log all GBM parameters explicitly for auditability.
6. Save raw → data/raw/, processed → data/processed/.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.stattools import adfuller

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────
TRADING_DAYS_PER_YEAR: int = 252
MIN_HISTORY_DAYS: int = 252 * 3          # at least 3 years for reliable estimates
SPLIT_ARTIFACT_THRESHOLD: float = 0.25  # flag if |log-return| > 25 % in a single day


# ─── Public API ───────────────────────────────────────────────────────────────

def run_pipeline(cfg: dict) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    """
    Execute the full data pipeline and return processed data plus GBM parameters.

    Parameters
    ----------
    cfg : dict
        Full configuration dictionary loaded from YAML.

    Returns
    -------
    raw_df : pd.DataFrame
        Raw OHLC data saved to disk.
    processed_df : pd.DataFrame
        Cleaned data with log returns and rolling vols.
    params : dict
        Auditable GBM parameters: S0, mu, sigma, dt, etc.
    """
    data_cfg = cfg["data"]
    raw_dir = Path(data_cfg["raw_dir"])
    processed_dir = Path(data_cfg["processed_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Acquire raw data ─────────────────────────────────────────────
    raw_df = _fetch_data(
        ticker=data_cfg["ticker"],
        period=data_cfg["period"],
        local_csv=data_cfg["local_csv"],
    )
    raw_path = raw_dir / "niftybank_raw.csv"
    raw_df.to_csv(raw_path)
    logger.info("Raw data saved → %s  (%d rows)", raw_path, len(raw_df))

    # ── Step 2: Quality checks ───────────────────────────────────────────────
    raw_df = _quality_check(raw_df)

    # ── Step 3: Compute features ─────────────────────────────────────────────
    processed_df = _compute_features(raw_df)

    processed_path = processed_dir / "niftybank_processed.csv"
    processed_df.to_csv(processed_path)
    logger.info("Processed data saved → %s  (%d rows)", processed_path, len(processed_df))

    # ── Step 4: GBM parameter extraction ─────────────────────────────────────
    params = _extract_gbm_params(processed_df, cfg)
    _log_gbm_params(params)

    return raw_df, processed_df, params


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _fetch_data(ticker: str, period: str, local_csv: str) -> pd.DataFrame:
    """
    Download OHLC data from yfinance; fall back to local CSV on failure.

    Parameters
    ----------
    ticker : str
        Yahoo Finance ticker symbol, e.g. ``"^NSEBANK"``.
    period : str
        yfinance period string, e.g. ``"max"``.
    local_csv : str
        Path to the local CSV fallback file.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: Open, High, Low, Close, Volume.
        Index is a DatetimeIndex named ``Date``.
    """
    logger.info("Attempting yfinance download: ticker=%s, period=%s", ticker, period)
    try:
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if df is None or df.empty:
            raise ValueError("yfinance returned empty DataFrame")
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        logger.info(
            "yfinance: downloaded %d rows  (%s → %s)",
            len(df),
            df.index[0].date(),
            df.index[-1].date(),
        )
        if len(df) < MIN_HISTORY_DAYS:
            logger.warning(
                "Only %d rows fetched — falling back to local CSV for supplemental data.",
                len(df),
            )
            raise ValueError("Insufficient history from API")
        return df[["Open", "High", "Low", "Close", "Volume"]].copy()

    except Exception as exc:
        logger.warning("yfinance failed (%s) — loading local CSV: %s", exc, local_csv)
        return _load_local_csv(local_csv)


def _load_local_csv(path: str) -> pd.DataFrame:
    """
    Load and normalise the local CSV cache.

    Parameters
    ----------
    path : str
        Path to the CSV file (Investing.com or NSE export format).

    Returns
    -------
    pd.DataFrame
        Normalised OHLC DataFrame.

    Raises
    ------
    FileNotFoundError
        If the CSV does not exist.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Local CSV not found: {csv_path}")

    df = pd.read_csv(csv_path, thousands=",")
    df.columns = df.columns.str.strip()

    # Normalise column names from Investing.com / NSE export formats
    rename_map: Dict[str, str] = {
        "Date": "Date",
        "Price": "Close",
        "Open": "Open",
        "High": "High",
        "Low": "Low",
        "Vol.": "Volume",
        "Change %": "Change_pct",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Parse date
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            df["Date"] = pd.to_datetime(df["Date"], format=fmt)
            break
        except (ValueError, TypeError):
            continue
    else:
        df["Date"] = pd.to_datetime(df["Date"], infer_datetime_format=True)

    df = df.set_index("Date").sort_index()

    # Ensure numeric
    for col in ["Close", "Open", "High", "Low"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")

    # Volume may contain 'M' / 'B' suffixes
    if "Volume" in df.columns:
        df["Volume"] = _parse_volume(df["Volume"])

    needed = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[needed].copy()
    logger.info("Local CSV loaded: %d rows  (%s → %s)", len(df), df.index[0].date(), df.index[-1].date())
    return df


def _parse_volume(series: pd.Series) -> pd.Series:
    """Convert volume strings like '165.02M' or '1.2B' to floats."""
    def _parse_one(val: str) -> float:
        if pd.isna(val):
            return np.nan
        s = str(val).strip().upper().replace(",", "")
        if s.endswith("B"):
            return float(s[:-1]) * 1e9
        if s.endswith("M"):
            return float(s[:-1]) * 1e6
        if s.endswith("K"):
            return float(s[:-1]) * 1e3
        try:
            return float(s)
        except ValueError:
            return np.nan

    return series.apply(_parse_one)


def _quality_check(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run data-quality checks and log findings.

    Checks
    ------
    - Missing / NaN values → forward-fill then drop.
    - Duplicate dates → keep last.
    - Extreme single-day log returns (potential split/rebalancing artifacts).
    - Stationarity test (ADF) on log returns (informational).

    Parameters
    ----------
    df : pd.DataFrame
        Raw OHLC data.

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame.
    """
    logger.info("Running data quality checks on %d rows …", len(df))

    # Duplicate dates
    n_dup = df.index.duplicated().sum()
    if n_dup:
        logger.warning("Found %d duplicate dates — keeping last occurrence.", n_dup)
        df = df[~df.index.duplicated(keep="last")]

    # Missing values
    n_missing = df["Close"].isna().sum()
    if n_missing:
        logger.warning("Found %d missing Close values — forward-filling.", n_missing)
        df["Close"] = df["Close"].ffill().bfill()

    # Check for zero / negative prices
    bad_prices = (df["Close"] <= 0).sum()
    if bad_prices:
        logger.warning("Found %d non-positive Close values — dropping.", bad_prices)
        df = df[df["Close"] > 0]

    # Compute log returns for artifact detection
    log_ret = np.log(df["Close"] / df["Close"].shift(1)).dropna()

    # Split / rebalancing artifacts: |ret| > threshold
    artifacts = log_ret[log_ret.abs() > SPLIT_ARTIFACT_THRESHOLD]
    if not artifacts.empty:
        logger.warning(
            "Potential split/rebalancing artifacts detected on %d dates:\n%s",
            len(artifacts),
            artifacts,
        )

    # ADF stationarity test on log returns
    _run_adf(log_ret)

    # Missing trading-day gaps (more than 5 business days between records)
    biz_gaps = pd.bdate_range(df.index.min(), df.index.max())
    missing_biz = biz_gaps.difference(df.index)
    if len(missing_biz) > 0:
        logger.info(
            "Found %d business-day gaps (holidays / trading halts) — expected for Indian markets.",
            len(missing_biz),
        )

    logger.info("Quality check complete. Rows after cleaning: %d", len(df))
    return df


def _run_adf(returns: pd.Series) -> None:
    """
    Run Augmented Dickey-Fuller test on log returns and log results.

    Parameters
    ----------
    returns : pd.Series
        Daily log returns.
    """
    try:
        result = adfuller(returns.dropna(), autolag="AIC")
        p_value = result[1]
        is_stationary = p_value < 0.05
        logger.info(
            "ADF stationarity test on log returns: ADF=%.4f, p=%.6f → %s",
            result[0],
            p_value,
            "STATIONARY (as expected)" if is_stationary else "NON-STATIONARY (unexpected)",
        )
    except Exception as e:
        logger.warning("ADF test failed: %s", e)


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute log returns, rolling volatilities, and normalised features.

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned OHLC DataFrame.

    Returns
    -------
    pd.DataFrame
        Extended DataFrame with additional columns:
        ``log_return``, ``rolling_vol_30``, ``rolling_vol_60``,
        ``rolling_vol_90``, ``cum_return``.
    """
    out = df.copy()
    out["log_return"] = np.log(out["Close"] / out["Close"].shift(1))
    out["rolling_vol_30"] = out["log_return"].rolling(30).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    out["rolling_vol_60"] = out["log_return"].rolling(60).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    out["rolling_vol_90"] = out["log_return"].rolling(90).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    out["cum_return"] = (1 + out["log_return"]).cumprod() - 1
    out = out.dropna(subset=["log_return"])
    return out


def _extract_gbm_params(df: pd.DataFrame, cfg: dict) -> Dict[str, float]:
    """
    Compute and return auditable GBM parameters from historical data.

    Parameters
    ----------
    df : pd.DataFrame
        Processed DataFrame containing ``log_return`` and ``Close``.
    cfg : dict
        Full config (used for horizons and n_paths).

    Returns
    -------
    dict
        Keys: S0, mean_daily_return, sigma_daily, mu_annual, sigma_annual,
              dt, n_steps_1m, n_steps_3m, n_steps_1y, n_paths, skewness, kurtosis.
    """
    log_ret = df["log_return"].dropna()
    S0 = float(df["Close"].iloc[-1])
    mean_daily = float(log_ret.mean())
    sigma_daily = float(log_ret.std())
    mu_annual = mean_daily * TRADING_DAYS_PER_YEAR
    sigma_annual = sigma_daily * np.sqrt(TRADING_DAYS_PER_YEAR)
    dt = 1.0 / TRADING_DAYS_PER_YEAR
    horizons = cfg["simulation"]["horizons"]

    return {
        "S0": S0,
        "mean_daily_return": mean_daily,
        "sigma_daily": sigma_daily,
        "mu_annual": mu_annual,
        "sigma_annual": sigma_annual,
        "dt": dt,
        "n_steps_1m": horizons[0],
        "n_steps_3m": horizons[1],
        "n_steps_1y": horizons[2],
        "n_paths": cfg["simulation"]["n_paths"],
        "skewness": float(log_ret.skew()),
        "excess_kurtosis": float(log_ret.kurt()),
        "n_historical_days": len(log_ret),
        "date_start": str(df.index[0].date()),
        "date_end": str(df.index[-1].date()),
    }


def _log_gbm_params(params: Dict[str, float]) -> None:
    """Log all GBM parameters for run auditability."""
    logger.info("=" * 60)
    logger.info("  GBM PARAMETER AUDIT LOG")
    logger.info("=" * 60)
    logger.info("  Data range         : %s → %s  (%d trading days)",
                params["date_start"], params["date_end"], params["n_historical_days"])
    logger.info("  S0 (latest close)  : %.2f", params["S0"])
    logger.info("  Mean daily return  : %.6f", params["mean_daily_return"])
    logger.info("  Daily volatility σ : %.6f", params["sigma_daily"])
    logger.info("  Annual drift  μ    : %.4f  (%.2f%%/yr)", params["mu_annual"], params["mu_annual"] * 100)
    logger.info("  Annual vol    σ    : %.4f  (%.2f%%/yr)", params["sigma_annual"], params["sigma_annual"] * 100)
    logger.info("  Time step Δt       : %.6f  (1/252 trading year)", params["dt"])
    logger.info("  Horizons (days)    : 1m=%d  3m=%d  1y=%d",
                params["n_steps_1m"], params["n_steps_3m"], params["n_steps_1y"])
    logger.info("  Simulated paths N  : %d", params["n_paths"])
    logger.info("  Historical skewness: %.4f", params["skewness"])
    logger.info("  Excess kurtosis    : %.4f", params["excess_kurtosis"])
    logger.info("=" * 60)
