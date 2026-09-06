import argparse
from datetime import date


def main():
    """Command-line entry point: ingest if needed, run the backtest, print the report."""
    parser = argparse.ArgumentParser(description="Run NSE swing-trade backtest")
    parser.add_argument("--db", default="backtest_data.db")
    parser.add_argument(
        "--force-ingest",
        action="store_true",
        help="Re-download data even if DB already exists",
    )
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--csv", default="backtest_trades.csv")
    args = parser.parse_args()

    from app.backtest.ingest import run_ingest

    run_ingest(db_path=args.db, force=args.force_ingest)

    from app.backtest.engine import run_backtest
    from app.backtest.report import print_report

    trades, equity_curve, all_scores = run_backtest(
        db_path=args.db,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
    )
    print_report(trades, equity_curve, all_scores=all_scores, csv_path=args.csv)



if __name__ == "__main__":
    main()
