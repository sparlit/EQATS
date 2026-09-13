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


"""Pytest configuration for the test suite."""

"""Copyright (C) 2023 Edward West. All rights reserved.

This code is licensed under Apache 2.0 with Commons Clause license
(see LICENSE for details).
"""

import os
import tempfile

import numpy as np
import pytest


def _patch_numpy_seed_for_randomly() -> None:
    """Wrap ``numpy.random.seed`` for pytest-randomly + thinc entrypoints.

    pytest-randomly passes session seeds with per-test offsets that can exceed
    NumPy's legacy ``2**32 - 1`` limit to third-party reseed hooks (e.g. thinc).
    """
    _original_seed = np.random.seed

    def _seed(seed=None):
        if seed is not None and isinstance(seed, (int, np.integer)):
            seed = int(seed) % (2**32)
        return _original_seed(seed)

    np.random.seed = _seed  # type: ignore[method-assign]


_patch_numpy_seed_for_randomly()


def _configure_numba_cache_dir() -> None:
    """Give each pytest worker its own Numba cache before numba is imported."""
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    cache_dir = tempfile.mkdtemp(prefix=f"numba_cache_{worker}_")
    os.environ["NUMBA_CACHE_DIR"] = cache_dir


_configure_numba_cache_dir()


@pytest.fixture(scope="session", autouse=True)
def _isolated_numba_cache():
    """Ensures the Numba cache directory from :func:`_configure_numba_cache_dir`."""
    cache_dir = os.environ.get("NUMBA_CACHE_DIR", "")
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)


@pytest.fixture(autouse=True)
def _sequential_parallel_config():
    """Pins the parallel config to sequential for every test.

    The library default is ``n_jobs=-1``; letting tests inherit it would fan
    optimize trials out to loky workers, where in-process assertions
    (closure counters, ``mock.patch``) cannot see them — and under
    ``pytest -n auto`` would oversubscribe every core. Tests that exercise
    parallel behavior call ``set_parallel`` themselves.
    """
    import pybroker.parallel as parallel_mod

    saved = parallel_mod._config
    parallel_mod._config = parallel_mod.ParallelConfig(n_jobs=1)
    yield
    parallel_mod._config = saved
