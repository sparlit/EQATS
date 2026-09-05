"""
report.py — HTML/PDF Report Generator
=======================================

Builds a self-contained HTML report with all charts embedded as base64 PNGs
and optionally converts it to PDF using weasyprint.

Report sections
---------------
1. Executive Summary      — current level, key risk metrics, model recommendation
2. Methodology            — plain-language explanation of each model
3. GBM Parameter Audit    — explicitly logged assumptions
4. All 8 Charts           — embedded inline
5. Risk Metrics Table     — full numeric output per model
6. Model Comparison Table — GBM vs. Bootstrap vs. Jump vs. GARCH
7. Backtest Results       — walk-forward coverage
8. Assumptions & Limits   — explicit statement of what each model does NOT capture
9. Disclaimer             — research/educational use only
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)


def generate_report(
    params: Dict,
    all_metrics: Dict[str, Dict],
    backtest_results: Dict[str, Dict],
    comparison_table: pd.DataFrame,
    png_paths: List[str],
    cfg: dict,
    run_timestamp: str,
) -> Dict[str, str]:
    """
    Generate HTML and (optionally) PDF reports.

    Parameters
    ----------
    params : dict
        GBM parameter audit dictionary.
    all_metrics : dict
        model_name → metrics dict.
    backtest_results : dict
        model_name → backtest result dict.
    comparison_table : pd.DataFrame
        Model comparison table.
    png_paths : list of str
        Absolute paths to saved chart PNGs.
    cfg : dict
        Full configuration.
    run_timestamp : str
        ISO-format timestamp for this run.

    Returns
    -------
    dict
        Keys ``html`` and (if successful) ``pdf``, mapping to output paths.
    """
    report_dir = Path(cfg["reporting"]["report_dir"])
    report_dir.mkdir(parents=True, exist_ok=True)

    # ── Embed charts as base64 ───────────────────────────────────────────────
    charts_b64: Dict[str, str] = {}
    chart_names = [
        "Historical Price & Returns",
        "Simulated Path Fan Chart",
        "Terminal Price Distribution",
        "Return Distribution & Q-Q",
        "Rolling Volatility",
        "Drawdown Distribution",
        "Model Comparison",
        "Probability Heatmap",
    ]
    for i, png_path in enumerate(png_paths[:8]):
        try:
            with open(png_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
            charts_b64[chart_names[i]] = img_data
        except FileNotFoundError:
            logger.warning("Chart PNG not found: %s", png_path)
            charts_b64[chart_names[i]] = ""

    # ── Prepare template context ─────────────────────────────────────────────
    primary_model = list(all_metrics.keys())[0]
    primary = all_metrics[primary_model]

    def fmt_pct(v: float, decimals: int = 2) -> str:
        return f"{v * 100:.{decimals}f}%"

    def fmt_num(v: float, decimals: int = 0) -> str:
        return f"{v:,.{decimals}f}"

    context = {
        "title": "Nifty Bank Index — Monte Carlo Risk Report",
        "timestamp": run_timestamp,
        "ticker": cfg["data"]["ticker"],
        "S0": params["S0"],
        "date_start": params["date_start"],
        "date_end": params["date_end"],
        "n_historical_days": params["n_historical_days"],
        "mu_annual_pct": params["mu_annual"] * 100,
        "sigma_annual_pct": params["sigma_annual"] * 100,
        "skewness": params["skewness"],
        "excess_kurtosis": params["excess_kurtosis"],
        "n_paths": params["n_paths"],
        "params": params,
        "all_metrics": all_metrics,
        "primary_model": primary_model,
        "primary": primary,
        "comparison_table_html": comparison_table.round(4).to_html(
            classes="metrics-table", border=0, float_format=lambda x: f"{x:.4f}"
        ),
        "backtest_results": backtest_results,
        "charts": charts_b64,
        "risk_free_rate_pct": cfg["risk"]["risk_free_rate"] * 100,
        "target_return_pct": cfg["risk"]["target_return"] * 100,
        "fmt_pct": fmt_pct,
        "fmt_num": fmt_num,
        "models": list(all_metrics.keys()),
        "cfg": cfg,
    }

    # ── Render HTML ──────────────────────────────────────────────────────────
    template_dir = Path(__file__).parent.parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report_template.html")
    html_content = template.render(**context)

    html_path = report_dir / f"report_{run_timestamp[:10]}.html"
    html_path.write_text(html_content, encoding="utf-8")
    logger.info("HTML report saved → %s", html_path)

    output_paths = {"html": str(html_path)}

    # ── Save versioned config alongside report ───────────────────────────────
    import yaml
    config_copy = report_dir / f"config_{run_timestamp[:10]}.yaml"
    with open(config_copy, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
    logger.info("Config copy saved → %s", config_copy)

    # ── PDF via weasyprint ───────────────────────────────────────────────────
    if "pdf" in cfg["reporting"].get("output_formats", []):
        pdf_path = report_dir / f"report_{run_timestamp[:10]}.pdf"
        try:
            from weasyprint import HTML
            HTML(string=html_content, base_url=str(report_dir)).write_pdf(str(pdf_path))
            logger.info("PDF report saved → %s", pdf_path)
            output_paths["pdf"] = str(pdf_path)
        except Exception as exc:
            logger.warning("weasyprint PDF generation failed (%s) — HTML report only.", exc)

    return output_paths
