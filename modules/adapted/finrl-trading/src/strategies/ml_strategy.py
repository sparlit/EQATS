import datetime
import logging
import os
import sys
import warnings
from datetime import datetime as dt_class
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

try:
    import numpy as np
    import pandas as pd
    from scipy.optimize import minimize
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Lasso, LinearRegression, Ridge
    from sklearn.metrics import mean_squared_error, r2_score
    from sklearn.model_selection import TimeSeriesSplit, train_test_split
    from sklearn.preprocessing import StandardScaler
except ImportError as e:
    warnings.warn(f"Optional ML dependencies not available: {e}", stacklevel=2)
    np = pd = minimize = GradientBoostingRegressor = RandomForestRegressor = None
    Lasso = LinearRegression = Ridge = mean_squared_error = r2_score = None
    TimeSeriesSplit = train_test_split = StandardScaler = None

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

try:
    from src.data.data_fetcher import fetch_fundamental_data, fetch_sp500_tickers
    from src.strategies.base_strategy import BaseStrategy, StrategyConfig, StrategyResult
except ImportError:
    fetch_fundamental_data = fetch_sp500_tickers = None
    BaseStrategy = StrategyConfig = StrategyResult = None


def is_ist_market_session_active(dt: dt_class | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = dt_class.now(ist)
    else:
        if dt.tzinfo is None:
            dt = ist.localize(dt)
        now = dt.astimezone(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    rounded = round(price / tick_size) * tick_size
    return round(rounded + 1e-10, 2)


"""
Machine Learning Strategy Module
===============================

Implements ML-based stock selection strategies:
- Supervised learning for stock selection
- Feature engineering
- Model training and prediction
- Sector-neutral portfolio construction
- Multiple weight allocation methods:
  * Equal weight: 等权重分配（默认）
  * Min variance: 最小方差权重分配（自动使用基本面数据中的 adj_close_q）

  Usage:
      # 使用等权重
      result = strategy.generate_weights(
          data_dict,
          prediction_mode='single',
          weight_method='equal'
      )

      # 使用最小方差权重（自动使用基本面数据中的 adj_close_q 列计算）
      data_dict = {
          'fundamentals': fundamentals_df  # 必须包含 adj_close_q 列
      }
      result = strategy.generate_weights(
          data_dict,
          prediction_mode='single',
          weight_method='min_variance',
          lookback_periods=8  # 回溯季度数（默认8，即2年）
      )

      # 也可以使用日度价格数据
      data_dict = {
          'fundamentals': fundamentals_df,
          'prices': prices_df  # 包含 ['date', 'tic', 'close']
      }
      result = strategy.generate_weights(
          data_dict,
          prediction_mode='single',
          weight_method='min_variance',
          lookback_periods=252  # 回溯交易日数
      )
"""
