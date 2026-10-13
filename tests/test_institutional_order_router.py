"""
Unit and Integration Tests for Institutional Smart Order Router (SOR).
"""

from institutional_integrations.institutional_order_router import (
    InstitutionalOrderRouter,
    InstitutionalOrderRouterAdapter,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_round_tick_005() -> None:
    assert round_tick_005(100.02) == 100.00
    assert round_tick_005(100.03) == 100.05
    assert round_tick_005(100.08) == 100.10


def test_order_slicing_twap() -> None:
    router = InstitutionalOrderRouter()
    slices = router.slice_order_twap(total_quantity=100, num_slices=4)
    assert len(slices) == 4
    assert sum(slices) == 100

    slices_uneven = router.slice_order_twap(total_quantity=10, num_slices=3)
    assert sum(slices_uneven) == 10


def test_evaluate_exchange_liquidity() -> None:
    router = InstitutionalOrderRouter()
    nse_depth = {"bid": 2850.0, "ask": 2850.5, "volume": 7000}
    bse_depth = {"bid": 2849.9, "ask": 2850.6, "volume": 3000}

    alloc = router.evaluate_exchange_liquidity("RELIANCE", nse_depth, bse_depth)
    assert alloc["NSE"] == 0.70
    assert alloc["BSE"] == 0.30
    assert alloc["primary_exchange"] == "NSE"


def test_order_router_adapter_lifecycle() -> None:
    adapter = InstitutionalOrderRouterAdapter(is_sandbox=True)
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    acc = adapter.get_account_info()
    assert acc["broker"] == "INSTITUTIONAL_ORDER_ROUTER"

    req = SEBIOrderRequest(
        symbol="INFY", order_type="BUY", quantity=150, price=1800.12, product="MIS", exchange="NSE"
    )
    res = adapter.execute_order(req)
    assert res.success is True
    assert res.price == 1800.10
    assert res.ticket.startswith("SOR_")

    close_res = adapter.close_order(res.ticket, "INFY")
    assert close_res.success is True


def test_broker_registry_integration() -> None:
    assert IndianBrokerPluginRegistry.is_enabled("INSTITUTIONAL_ORDER_ROUTER") is True
    adapter_cls = IndianBrokerPluginRegistry.get_adapter_class("INSTITUTIONAL_ORDER_ROUTER")
    assert adapter_cls is InstitutionalOrderRouterAdapter
