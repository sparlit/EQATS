#!/usr/bin/env python3
"""
EQATS Integration Progress Dashboard Generator
Parses ingestion_blueprint.json and generates an interactive standalone `dashboard.html`.
"""

import json
from pathlib import Path


def generate_dashboard():
    root_dir = Path.cwd()
    blueprint_file = root_dir / "ingestion_blueprint.json"
    dashboard_file = root_dir / "dashboard.html"

    if not blueprint_file.exists():
        print("[-] Blueprint JSON file not found.")
        return

    with blueprint_file.open("r", encoding="utf-8") as f:
        ledger = json.load(f)

    repos = ledger.get("repositories", [])
    total = len(repos)
    current_index = ledger.get("current_index", 0)

    completed = sum(1 for r in repos if r.get("status") in ("Completed", "Processed"))
    skipped = sum(1 for r in repos if "Skipped" in r.get("status", "") or "Failed" in r.get("status", ""))
    pending = total - completed - skipped
    progress_pct = round((current_index / total) * 100.0, 1) if total > 0 else 0.0

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EQATS Institutional Integration Dashboard</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #0d1117; color: #c9d1d9; margin: 0; padding: 24px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 16px; margin-bottom: 24px; }}
        .title {{ font-size: 24px; font-weight: bold; color: #58a6ff; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
        .stat-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; text-align: center; }}
        .stat-val {{ font-size: 28px; font-weight: bold; margin-top: 8px; }}
        .val-total {{ color: #58a6ff; }}
        .val-completed {{ color: #3fb950; }}
        .val-skipped {{ color: #d29922; }}
        .val-pending {{ color: #8b949e; }}
        .progress-bar-bg {{ background: #21262d; border-radius: 8px; height: 16px; width: 100%; overflow: hidden; margin-bottom: 24px; }}
        .progress-bar-fill {{ background: linear-gradient(90deg, #238636, #2ea043); height: 100%; width: {progress_pct}%; transition: width 0.3s ease; }}
        table {{ width: 100%; border-collapse: collapse; background: #161b22; border-radius: 8px; overflow: hidden; border: 1px solid #30363d; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #30363d; font-size: 14px; }}
        th {{ background: #21262d; color: #8b949e; }}
        .status-completed {{ color: #3fb950; font-weight: bold; }}
        .status-skipped {{ color: #d29922; }}
        .status-pending {{ color: #8b949e; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">🚀 EQATS Institutional Integration Dashboard</div>
            <div>Progress Pointer: <strong>{current_index} / {total}</strong></div>
        </div>

        <div class="progress-bar-bg">
            <div class="progress-bar-fill"></div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div>Total Repositories</div>
                <div class="stat-val val-total">{total}</div>
            </div>
            <div class="stat-card">
                <div>Completed Integrations</div>
                <div class="stat-val val-completed">{completed}</div>
            </div>
            <div class="stat-card">
                <div>Skipped / Non-Existent</div>
                <div class="stat-val val-skipped">{skipped}</div>
            </div>
            <div class="stat-card">
                <div>Pending Queue</div>
                <div class="stat-val val-pending">{pending}</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Target Repository</th>
                    <th>Status</th>
                    <th>PR Link</th>
                </tr>
            </thead>
            <tbody>
"""

    for idx, r in enumerate(repos, start=1):
        st = r.get("status", "pending")
        pr = r.get("pr_url", "-")
        pr_link = f'<a href="{pr}" target="_blank" style="color: #58a6ff;">PR Link</a>' if pr and pr != "-" else "-"

        cls_name = "status-completed" if "Completed" in st or "Processed" in st else ("status-skipped" if "Skipped" in st or "Failed" in st else "status-pending")

        html_content += f"""
                <tr>
                    <td>{idx}</td>
                    <td><strong>{r.get('target', '-')}</strong></td>
                    <td class="{cls_name}">{st}</td>
                    <td>{pr_link}</td>
                </tr>
"""

    html_content += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""

    with dashboard_file.open("w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[+] Interactive Dashboard HTML generated successfully: {dashboard_file}")


if __name__ == "__main__":
    generate_dashboard()
