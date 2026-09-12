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


"""
ui/widgets/risk_meter.py
────────────────────────
Textual widget: risk meter panel.
Shows % capital deployed, free cash, unrealised P&L, and risk rating.
"""


from typing import TYPE_CHECKING

from textual.widgets import Label, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult


class RiskMeterWidget(Static):
    """
    Compact risk meter: bar + key metrics showing capital deployment.
    """

    DEFAULT_CSS = """
    RiskMeterWidget {
        height: auto;
        border: round $warning;
        padding: 0 1;
    }
    RiskMeterWidget Label {
        color: $warning;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Risk Meter")
        yield Static(id="risk-body")

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from engine.portfolio import risk_meter

            r = risk_meter()
            self._render(r)
        except Exception:
            self.query_one("#risk-body", Static).update("[dim]Unavailable[/dim]")

    def _render(self, r) -> None:
        rating_color = {
            "LOW": "green",
            "MEDIUM": "yellow",
            "HIGH": "dark_orange",
            "DANGER": "bold red",
        }.get(r.risk_rating, "white")

        bar_len = 20
        filled = int(r.deployment_pct / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        pnl_color = "green" if r.unrealised_pnl >= 0 else "red"
        pnl_sign = "+" if r.unrealised_pnl >= 0 else ""

        lines = [
            f"[{rating_color}]{r.risk_rating:<8}[/{rating_color}]  [{rating_color}]{bar}[/{rating_color}]  {r.deployment_pct:.1f}%",
            f"Free cash  : [green]₹{r.free_cash:>12,.0f}[/green]",
            f"Used margin: [yellow]₹{r.used_margin:>11,.0f}[/yellow]",
            f"Unrealised : [{pnl_color}]{pnl_sign}₹{r.unrealised_pnl:>10,.0f}[/{pnl_color}]",
            f"Max loss est: [red]₹{r.max_loss_estimate:>10,.0f}[/red]",
        ]
        self.query_one("#risk-body", Static).update("\n".join(lines))
