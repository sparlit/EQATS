from __future__ import annotations

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


#!/usr/bin/env python3
"""Create PostgreSQL tables for professional quant layers.

Tables created:
  Layer 1 (Fundamentals): company_profile, key_ratios, quarterly_financials
  Layer 2 (Institutional): fii_dii_daily, shareholding_history, bulk_deals,
                           insider_trades, promoter_pledge
  Layer 3 (Sectors): sector_map, sector_daily
  Layer 4 (Risk): portfolio_risk, stock_risk

Run once to initialize schema. Safe to re-run (CREATE IF NOT EXISTS).
"""


import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sqlalchemy as sa
from indian_quant.config.connections import get_engine


def create_tables(engine: sa.engine.Engine) -> None:
    meta = sa.MetaData()

    # ── Layer 1: Fundamentals ──

    sa.Table(
        "company_profile",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(8), nullable=False, default="NSE"),
        sa.Column("company_name", sa.Text),
        sa.Column("sector", sa.String(64)),
        sa.Column("industry", sa.String(128)),
        sa.Column("description", sa.Text),
        sa.Column("website", sa.String(256)),
        sa.Column("employees", sa.Integer),
        sa.Column("shares_outstanding", sa.BigInteger),
        sa.Column("float_shares", sa.BigInteger),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", name="company_profile_pkey"),
    )

    sa.Table(
        "key_ratios",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        # Valuation
        sa.Column("pe_trailing", sa.Float),
        sa.Column("pe_forward", sa.Float),
        sa.Column("peg_ratio", sa.Float),
        sa.Column("price_to_book", sa.Float),
        sa.Column("price_to_sales", sa.Float),
        sa.Column("ev_to_ebitda", sa.Float),
        sa.Column("ev_to_revenue", sa.Float),
        sa.Column("enterprise_value", sa.BigInteger),
        sa.Column("market_cap", sa.BigInteger),
        # Profitability
        sa.Column("profit_margin", sa.Float),
        sa.Column("operating_margin", sa.Float),
        sa.Column("gross_margin", sa.Float),
        sa.Column("ebitda_margin", sa.Float),
        sa.Column("roe", sa.Float),
        sa.Column("roa", sa.Float),
        # Growth
        sa.Column("revenue_growth", sa.Float),
        sa.Column("earnings_growth", sa.Float),
        sa.Column("earnings_q_growth", sa.Float),
        # Financial Health
        sa.Column("debt_to_equity", sa.Float),
        sa.Column("current_ratio", sa.Float),
        sa.Column("quick_ratio", sa.Float),
        sa.Column("total_debt", sa.BigInteger),
        sa.Column("total_cash", sa.BigInteger),
        sa.Column("free_cash_flow", sa.BigInteger),
        # Per Share
        sa.Column("eps_trailing", sa.Float),
        sa.Column("eps_forward", sa.Float),
        sa.Column("book_value", sa.Float),
        sa.Column("revenue_per_share", sa.Float),
        # Dividend
        sa.Column("dividend_rate", sa.Float),
        sa.Column("dividend_yield", sa.Float),
        sa.Column("payout_ratio", sa.Float),
        sa.Column("ex_div_date", sa.String(16)),
        # Technical context
        sa.Column("beta", sa.Float),
        sa.Column("w52_high", sa.Float),
        sa.Column("w52_low", sa.Float),
        sa.Column("avg_volume", sa.BigInteger),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", name="key_ratios_pkey"),
    )

    sa.Table(
        "quarterly_financials",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("revenue", sa.BigInteger),
        sa.Column("net_income", sa.BigInteger),
        sa.Column("operating_income", sa.BigInteger),
        sa.Column("gross_profit", sa.BigInteger),
        sa.Column("ebitda", sa.BigInteger),
        sa.Column("eps", sa.Float),
        sa.Column("operating_cf", sa.BigInteger),
        sa.Column("investing_cf", sa.BigInteger),
        sa.Column("financing_cf", sa.BigInteger),
        sa.Column("free_cash_flow", sa.BigInteger),
        sa.Column("total_assets", sa.BigInteger),
        sa.Column("total_liabilities", sa.BigInteger),
        sa.Column("total_equity", sa.BigInteger),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", "period", name="quarterly_financials_pkey"),
    )

    # ── Layer 2: Institutional Flows ──

    sa.Table(
        "fii_dii_daily",
        meta,
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("fii_buy", sa.BigInteger),
        sa.Column("fii_sell", sa.BigInteger),
        sa.Column("fii_net", sa.BigInteger),
        sa.Column("dii_buy", sa.BigInteger),
        sa.Column("dii_sell", sa.BigInteger),
        sa.Column("dii_net", sa.BigInteger),
        sa.Column("fii_net_pct", sa.Float),
        sa.Column("dii_net_pct", sa.Float),
        sa.Column("fii_dii_ratio", sa.Float),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("trade_date", name="fii_dii_daily_pkey"),
    )

    sa.Table(
        "shareholding_history",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("quarter", sa.String(16), nullable=False),
        sa.Column("promoter_pct", sa.Float),
        sa.Column("fii_pct", sa.Float),
        sa.Column("dii_pct", sa.Float),
        sa.Column("public_pct", sa.Float),
        sa.Column("promoter_chg", sa.Float),
        sa.Column("fii_chg", sa.Float),
        sa.Column("dii_chg", sa.Float),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", "quarter", name="shareholding_history_pkey"),
    )

    sa.Table(
        "bulk_deals",
        meta,
        sa.Column("deal_date", sa.Date, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("client", sa.String(128), nullable=False),
        sa.Column("deal_type", sa.String(8)),
        sa.Column("quantity", sa.BigInteger),
        sa.Column("price", sa.Float),
        sa.Column("value", sa.BigInteger),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("deal_date", "symbol", "client", name="bulk_deals_pkey"),
    )

    sa.Table(
        "insider_trades",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("insider_name", sa.String(128), nullable=False),
        sa.Column("transaction_type", sa.String(8)),
        sa.Column("shares_traded", sa.BigInteger),
        sa.Column("shares_after", sa.BigInteger),
        sa.Column("reported_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", "trade_date", "insider_name", name="insider_trades_pkey"),
    )

    sa.Table(
        "promoter_pledge",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("pledge_pct", sa.Float),
        sa.Column("risk_signal", sa.String(16)),
        sa.Column("qoq_change", sa.Float),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", name="promoter_pledge_pkey"),
    )

    # ── Layer 3: Sectors ──

    sa.Table(
        "sector_map",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("sector", sa.String(64)),
        sa.Column("industry", sa.String(128)),
        sa.Column("nse_index", sa.String(64)),
        sa.Column("sector_mcap_rank", sa.Integer),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", name="sector_map_pkey"),
    )

    sa.Table(
        "sector_daily",
        meta,
        sa.Column("sector", sa.String(64), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("avg_return", sa.Float),
        sa.Column("avg_deliv_z", sa.Float),
        sa.Column("avg_volume_z", sa.Float),
        sa.Column("net_fii", sa.Float),
        sa.Column("net_dii", sa.Float),
        sa.Column("stock_count", sa.Integer),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("sector", "trade_date", name="sector_daily_pkey"),
    )

    # ── Layer 4: Risk ──

    sa.Table(
        "portfolio_risk",
        meta,
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("total_value", sa.BigInteger),
        sa.Column("var_95", sa.Float),
        sa.Column("var_99", sa.Float),
        sa.Column("cvar_95", sa.Float),
        sa.Column("portfolio_beta", sa.Float),
        sa.Column("max_drawdown", sa.Float),
        sa.Column("sharpe_ratio", sa.Float),
        sa.Column("concentration_hhi", sa.Float),
        sa.Column("n_positions", sa.Integer),
        sa.Column("n_sectors", sa.Integer),
        sa.Column("top_sector_pct", sa.Float),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("snapshot_date", name="portfolio_risk_pkey"),
    )

    sa.Table(
        "stock_risk",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("beta", sa.Float),
        sa.Column("vol_30d", sa.Float),
        sa.Column("vol_annual", sa.Float),
        sa.Column("var_95", sa.Float),
        sa.Column("max_drawdown_1y", sa.Float),
        sa.Column("correlation_nifty", sa.Float),
        sa.Column("avg_daily_volume", sa.BigInteger),
        sa.Column("avg_turnover", sa.Float),
        sa.Column("impact_cost", sa.Float),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", name="stock_risk_pkey"),
    )

    # Create all tables
    meta.create_all(engine)
    print("All 12 quant tables created successfully.")


def verify_tables(engine: sa.engine.Engine) -> None:
    with engine.connect() as conn:
        result = conn.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
            )
        )
        tables = [r[0] for r in result.fetchall()]
        quant_tables = [
            "company_profile",
            "key_ratios",
            "quarterly_financials",
            "fii_dii_daily",
            "shareholding_history",
            "bulk_deals",
            "insider_trades",
            "promoter_pledge",
            "sector_map",
            "sector_daily",
            "portfolio_risk",
            "stock_risk",
        ]
        print(f"\nAll public tables: {len(tables)}")
        for t in quant_tables:
            status = "✅" if t in tables else "❌"
            print(f"  {status} {t}")


if __name__ == "__main__":
    engine = get_engine()
    create_tables(engine)
    verify_tables(engine)
