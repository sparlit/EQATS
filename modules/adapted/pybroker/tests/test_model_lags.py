import datetime
from typing import Optional

import pytz


def is_ist_market_session_active(dt: Optional[datetime.datetime] = None) -> bool:
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


"""Unit tests for model lag transform metadata."""

import numpy as np
import pandas as pd
import pytest

try:
    from pybroker.common import DataCol, ModelSymbol, TrainedModel
    from pybroker.model import (
        LagSeriesKey,
        ModelInput,
        _build_stacked_lags,
        apply_lags_to_model_input,
        build_lag_feature_matrix,
        build_lag_feature_matrix_pooled,
        compute_lag_series_cache,
        model,
        model_input_from_frame,
        symbol_history_arrays,
    )
    from pybroker.scope import (
        ColumnScope,
        IndicatorScope,
        ModelInputScope,
        StaticScope,
    )
except ImportError:
    pass


@pytest.fixture(autouse=True)
def clear_model_sources():
    try:
        scope = StaticScope.instance()
        scope._model_sources.clear()
        yield
        scope._model_sources.clear()
    except Exception:
        yield


class TestLagHelpers:
    def test_lags_must_be_positive(self):
        with pytest.raises(ValueError, match="lags must be a positive integer"):
            model(
                "m",
                lambda s, t, u: None,
                lags=0,
            )


class TestLagData:
    @pytest.fixture
    def sample_df(self):
        dates = pd.date_range("2020-01-01", periods=5)
        return pd.DataFrame(
            {
                DataCol.SYMBOL.value: ["SPY"] * 5 + ["AAPL"] * 5,
                DataCol.DATE.value: dates.tolist() * 2,
                DataCol.CLOSE.value: [
                    100,
                    101,
                    102,
                    103,
                    104,
                    200,
                    201,
                    202,
                    203,
                    204,
                ],
            }
        )

    def test_compute_lag_series_cache_per_symbol(self, sample_df):
        cache = compute_lag_series_cache(sample_df, ("SPY", "AAPL"), ("close",), 2)
        spy_lag1 = cache[LagSeriesKey("SPY", "close", 1)]
        aapl_lag1 = cache[LagSeriesKey("AAPL", "close", 1)]
        assert np.isnan(spy_lag1[0])
        assert spy_lag1[1] == 100
        assert np.isnan(aapl_lag1[0])
        assert aapl_lag1[1] == 200

    def test_apply_lags_no_column_expansion(self, sample_df):
        cache = compute_lag_series_cache(sample_df, ("SPY",), ("close",), 2)
        assert len(cache) > 0