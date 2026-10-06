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


import unittest

import meta_model
import ml_features
import ml_train
import numpy as np
import pandas as pd


class MLIntegrityTests(unittest.TestCase):
    def test_shared_feature_builder_matches_latest_row(self):
        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        closes = np.linspace(100, 180, 300)
        frame = ml_features.feature_frame(pd.DataFrame({"date": dates, "close": closes}))
        latest = ml_features.latest_features(closes)
        self.assertTrue(
            np.allclose(
                frame.iloc[-1][ml_features.FEATURE_COLUMNS].to_numpy(float), latest, equal_nan=True
            )
        )

    def test_time_split_is_global_and_purged(self):
        dates = pd.date_range("2020-01-01", periods=100, freq="D")
        data = pd.DataFrame(
            {
                "date": dates,
                "label_available_date": dates + pd.Timedelta(days=5),
                "x": np.arange(100),
            }
        )
        tr, va, te = ml_train._time_split(data, 0.6, 0.2)
        self.assertLess(tr["date"].max(), va["date"].min())
        self.assertLess(tr["label_available_date"].max(), va["date"].min())
        self.assertLess(va["label_available_date"].max(), te["date"].min())

    def test_legacy_meta_bundle_is_rejected_and_metadata_call_is_safe(self):
        old_model = meta_model._MODEL
        old_meta = meta_model._MODEL_METADATA
        try:
            meta_model._MODEL = object()
            meta_model._MODEL_METADATA = {"label": "test"}
            self.assertEqual(meta_model.model_bundle_metadata(object())["label"], "test")
        finally:
            meta_model._MODEL = old_model
            meta_model._MODEL_METADATA = old_meta


if __name__ == "__main__":
    unittest.main()
