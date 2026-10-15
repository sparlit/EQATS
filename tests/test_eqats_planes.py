import pytest
from eqats_planes import calculate_stop_loss_exposure


def test_calculate_stop_loss_exposure_invalid_inputs():
    """Test that zero or negative inputs return 0.0 exposure."""
    symbol = "EURUSD"
    equity = 10000.0
    lot_size = 1.0
    entry_price = 1.1000
    stop_loss = 1.0950

    # Equity <= 0
    assert calculate_stop_loss_exposure(symbol, lot_size, entry_price, stop_loss, equity=0.0) == 0.0
    assert calculate_stop_loss_exposure(symbol, lot_size, entry_price, stop_loss, equity=-100.0) == 0.0

    # Lot size <= 0
    assert calculate_stop_loss_exposure(symbol, lot_size=0.0, entry_price=entry_price, stop_loss=stop_loss, equity=equity) == 0.0
    assert calculate_stop_loss_exposure(symbol, lot_size=-1.0, entry_price=entry_price, stop_loss=stop_loss, equity=equity) == 0.0

    # Entry price <= 0
    assert calculate_stop_loss_exposure(symbol, lot_size=lot_size, entry_price=0.0, stop_loss=stop_loss, equity=equity) == 0.0
    assert calculate_stop_loss_exposure(symbol, lot_size=lot_size, entry_price=-1.1, stop_loss=stop_loss, equity=equity) == 0.0

    # Stop loss <= 0
    assert calculate_stop_loss_exposure(symbol, lot_size=lot_size, entry_price=entry_price, stop_loss=0.0, equity=equity) == 0.0
    assert calculate_stop_loss_exposure(symbol, lot_size=lot_size, entry_price=entry_price, stop_loss=-1.0, equity=equity) == 0.0


def test_calculate_stop_loss_exposure_forex_standard():
    """
    Test standard Forex pair (e.g., EURUSD).
    pip_size = 0.0001, pip_value_per_lot = 10.0.
    Entry: 1.1000, SL: 1.0950 -> distance = 0.0050 = 50 pips.
    Monetary exposure = 1.0 lot * 50 pips * 10.0 = 500.0 USD.
    Exposure % on 10,000 USD equity = (500 / 10000) * 100 = 5.0%.
    """
    exposure = calculate_stop_loss_exposure(
        symbol="EURUSD",
        lot_size=1.0,
        entry_price=1.1000,
        stop_loss=1.0950,
        equity=10000.0,
    )
    assert pytest.approx(exposure, abs=1e-5) == 5.0


def test_calculate_stop_loss_exposure_jpy():
    """
    Test JPY pair (e.g., USDJPY).
    pip_size = 0.01, pip_value_per_lot = 6.5.
    Entry: 150.00, SL: 149.00 -> distance = 1.00 = 100 pips.
    Monetary exposure = 2.0 lots * 100 pips * 6.5 = 1300.0 USD.
    Exposure % on 20,000 USD equity = (1300 / 20000) * 100 = 6.5%.
    """
    exposure = calculate_stop_loss_exposure(
        symbol="USDJPY",
        lot_size=2.0,
        entry_price=150.00,
        stop_loss=149.00,
        equity=20000.0,
    )
    assert pytest.approx(exposure, abs=1e-5) == 6.5


def test_calculate_stop_loss_exposure_gold():
    """
    Test Gold symbols (e.g., XAUUSD / GOLD).
    pip_size = 0.1, pip_value_per_lot = 10.0.
    Entry: 2000.0, SL: 1990.0 -> distance = 10.0 = 100 pips.
    Monetary exposure = 0.5 lot * 100 pips * 10.0 = 500.0 USD.
    Exposure % on 10,000 USD equity = (500 / 10000) * 100 = 5.0%.
    """
    exposure_xau = calculate_stop_loss_exposure(
        symbol="XAUUSD",
        lot_size=0.5,
        entry_price=2000.0,
        stop_loss=1990.0,
        equity=10000.0,
    )
    assert pytest.approx(exposure_xau, abs=1e-5) == 5.0

    exposure_gold = calculate_stop_loss_exposure(
        symbol="GOLD_SPOT",
        lot_size=0.5,
        entry_price=2000.0,
        stop_loss=1990.0,
        equity=10000.0,
    )
    assert pytest.approx(exposure_gold, abs=1e-5) == 5.0


def test_calculate_stop_loss_exposure_silver():
    """
    Test Silver symbols (e.g., XAGUSD / SILVER).
    pip_size = 0.01, pip_value_per_lot = 50.0.
    Entry: 25.00, SL: 24.50 -> distance = 0.50 = 50 pips.
    Monetary exposure = 1.0 lot * 50 pips * 50.0 = 2500.0 USD.
    Exposure % on 50,000 USD equity = (2500 / 50000) * 100 = 5.0%.
    """
    exposure = calculate_stop_loss_exposure(
        symbol="XAGUSD",
        lot_size=1.0,
        entry_price=25.00,
        stop_loss=24.50,
        equity=50000.0,
    )
    assert pytest.approx(exposure, abs=1e-5) == 5.0


def test_calculate_stop_loss_exposure_crypto_and_indices():
    """
    Test Crypto & Index symbols (e.g., BTCUSD, US30, NAS100).
    pip_size = 1.0, pip_value_per_lot = 1.0.
    Entry: 60000.0, SL: 59000.0 -> distance = 1000.0 = 1000 pips.
    Monetary exposure = 0.1 lot * 1000 pips * 1.0 = 100.0 USD.
    Exposure % on 5,000 USD equity = (100 / 5000) * 100 = 2.0%.
    """
    exposure_btc = calculate_stop_loss_exposure(
        symbol="BTCUSD",
        lot_size=0.1,
        entry_price=60000.0,
        stop_loss=59000.0,
        equity=5000.0,
    )
    assert pytest.approx(exposure_btc, abs=1e-5) == 2.0

    exposure_us30 = calculate_stop_loss_exposure(
        symbol="US30",
        lot_size=1.0,
        entry_price=35000.0,
        stop_loss=34800.0,
        equity=10000.0,
    )
    # distance = 200, 1.0 lot * 200 pips * 1.0 = 200 USD -> 200/10000 = 2%
    assert pytest.approx(exposure_us30, abs=1e-5) == 2.0


def test_calculate_stop_loss_exposure_directional_short():
    """
    Test that short positions (entry < stop_loss) yield identical positive exposure percentage.
    Short entry: 1.1000, SL: 1.1050 -> distance = 0.0050 = 50 pips.
    """
    long_exposure = calculate_stop_loss_exposure(
        symbol="EURUSD", lot_size=1.0, entry_price=1.1000, stop_loss=1.0950, equity=10000.0
    )
    short_exposure = calculate_stop_loss_exposure(
        symbol="EURUSD", lot_size=1.0, entry_price=1.1000, stop_loss=1.1050, equity=10000.0
    )
    assert long_exposure > 0
    assert pytest.approx(long_exposure, abs=1e-5) == short_exposure
