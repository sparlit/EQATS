from __future__ import annotations

import pandas as pd

from screener.screener import run_screener


def test_run_screener_filters_low_price() -> None:
    data = pd.DataFrame({"close": [25.0, 55.0], "volume": [600_000, 700_000]})
    result = run_screener(data)
    assert len(result) == 1
    assert result.iloc[0]["close"] == 55.0
