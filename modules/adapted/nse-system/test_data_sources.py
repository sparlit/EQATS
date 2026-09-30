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

import pytest
from data_sources.core import (
    BaseSourceAdapter,
    ProviderFetchError,
    SourceRegistry,
)


class _FakeAdapter(BaseSourceAdapter):
    datasets = ("test.value",)

    def __init__(self, name, result=None, error=None, max_calls=60):
        self.name = name
        self.result = result
        self.error = error
        super().__init__(max_calls=max_calls, window_seconds=60)

    def fetch(self):
        def run():
            if self.error:
                raise self.error
            return self.result

        return self._execute(run)


class SourceRegistryTests(unittest.TestCase):
    def test_falls_back_after_provider_error_and_reports_health(self):
        registry = SourceRegistry()
        registry.register(_FakeAdapter("first", error=OSError("offline")))
        registry.register(_FakeAdapter("second", result=["accepted"]))

        result = registry.fetch("test.value", ("first", "second"), accept=bool)

        assert result.data == ["accepted"]
        assert result.provider == "second"
        health = {item["provider"]: item for item in registry.health()}
        assert health["first"]["state"] == "unavailable"
        assert health["first"]["failures"] == 1
        assert health["second"]["state"] == "healthy"

    def test_rejected_results_do_not_masquerade_as_success(self):
        registry = SourceRegistry()
        registry.register(_FakeAdapter("empty", result=[]))

        with pytest.raises(ProviderFetchError) as error:
            registry.fetch("test.value", ("empty",), accept=bool)

        assert error.value.errors["empty"] == "provider result rejected"
        health = {item["provider"]: item for item in registry.health()}
        assert health["empty"]["state"] == "unavailable"

    def test_exhausted_fallback_raises_explicit_error(self):
        registry = SourceRegistry()
        registry.register(_FakeAdapter("broken", error=OSError("offline")))

        with pytest.raises(ProviderFetchError) as error:
            registry.fetch("test.value", ("broken",))

        assert "offline" in str(error.value)

    def test_rate_limit_blocks_calls_after_the_configured_budget(self):
        registry = SourceRegistry()
        adapter = _FakeAdapter("limited", result="ok", max_calls=1)
        registry.register(adapter)

        assert registry.fetch("test.value", ("limited",)).data == "ok"
        with pytest.raises(ProviderFetchError) as error:
            registry.fetch("test.value", ("limited",))

        assert error.value.errors["limited"] == "provider rate limit exceeded"
        assert adapter.health().calls == 1

    def test_builtins_are_discoverable_without_network_calls(self):
        registry = SourceRegistry()
        sources = {item["provider"]: item for item in registry.health()}

        assert {
            "tradingview",
            "yahoo_finance",
            "nse_constituents_local_csv",
            "nse_constituents_api",
            "nse_constituents_archive_csv",
            "chartink",
        }.issubset(sources)
        assert sources["tradingview"]["state"] == "not_checked"


if __name__ == "__main__":
    unittest.main()
