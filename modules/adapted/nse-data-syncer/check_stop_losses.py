"""
Daily stop-loss monitor for active strategy holdings.

Uses strategy_picks.json for current month's stocks and DB open price on the
first trading day of the month as entry price — same as the backtest.

Walks every trading day from entry to today (same loop as the backtest) so a
close-stop that triggered on a prior day (e.g. Jul 8) is correctly detected
even when this script runs the next day (Jul 9).

Stop rules (checked in order each day):
  1. GTT gap-down:  day's open <= entry * 0.85 → exited at open that day
  2. GTT intraday:  day's low  <= entry * 0.85 → exited at ~entry * 0.85
  3. Close stop:    day's close <= entry * 0.90 → exit at next morning's open
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
import pandas as pd
from sqlalchemy import text
from dotenv import load_dotenv

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, 'web', '.env'))
sys.path.append(base_dir)
from app.database import DatabaseManager

CLOSE_STOP_PCT = -0.10
GTT_STOP_PCT   = -0.15


def next_weekday(d: date) -> date:
    candidate = d + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def date_str(d) -> str:
    return str(d)[:10]


def find_stop_event(rows, entry_price):
    """
    Walk daily rows (sorted ascending by date) and return the first stop event.
    Returns dict with stop_type, stop_date, exit_date, ret, exit_open — or None.
    exit_open is the open price on exit_date (available when rows contain it).
    """
    gtt_price     = entry_price * (1 + GTT_STOP_PCT)
    close_trigger = entry_price * (1 + CLOSE_STOP_PCT)

    for i, row in enumerate(rows):
        d, open_p, low_p, close_p = row

        # GTT gap-down: open already below trigger
        if open_p is not None and open_p <= gtt_price:
            return {
                'stop_type': 'gtt_gap_down',
                'stop_date': date_str(d),
                'exit_date': date_str(d),
                'ret':       (open_p - entry_price) / entry_price,
                'exit_open': open_p,
            }
        # GTT intraday: low touched trigger during the day
        if low_p is not None and low_p <= gtt_price:
            return {
                'stop_type': 'gtt_intraday',
                'stop_date': date_str(d),
                'exit_date': date_str(d),
                'ret':       GTT_STOP_PCT,
                'exit_open': None,
            }
        # Close-price stop: exit next morning at open
        if close_p is not None and close_p <= close_trigger:
            exit_date = next_weekday(pd.Timestamp(d).date())
            # If we have the next row (exit day) grab its open for actual return
            exit_open = None
            exit_ret  = (close_p - entry_price) / entry_price
            if i + 1 < len(rows):
                next_row = rows[i + 1]
                if date_str(next_row[0]) == str(exit_date):
                    exit_open = next_row[1]  # open of next day
                    if exit_open is not None:
                        exit_ret = (exit_open - entry_price) / entry_price
            return {
                'stop_type': 'close_stop',
                'stop_date': date_str(d),
                'exit_date': str(exit_date),
                'ret':       exit_ret,
                'exit_open': exit_open,
            }

    return None


def main():
    today = date.today()
    current_month = today.strftime('%Y-%m')

    # Prefer monthly snapshot (frozen on first run of the month) so stocks that
    # drop out of the daily top-15 mid-month are still monitored for stops.
    snapshot_path = os.path.join(base_dir, 'web', 'src', 'data', 'monthly_picks_snapshot.json')
    picks_path    = os.path.join(base_dir, 'web', 'src', 'data', 'strategy_picks.json')

    picks_data = None
    if os.path.exists(snapshot_path):
        with open(snapshot_path) as f:
            snapshot = json.load(f)
        if current_month in snapshot:
            picks_data = {'picks': snapshot[current_month]['picks']}
            print(f"Using monthly snapshot for {current_month}")

    if picks_data is None:
        if not os.path.exists(picks_path):
            print("strategy_picks.json not found.")
            return
        with open(picks_path) as f:
            picks_data = json.load(f)
        print(f"No snapshot for {current_month} — using strategy_picks.json")

    db = DatabaseManager()
    session = db.Session()

    latest_date = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    print(f"Latest price date: {latest_date}")

    month_start = today.replace(day=1)
    entry_date = session.execute(
        text("SELECT MIN(date) FROM daily_prices WHERE date >= :ms"),
        {'ms': month_start.isoformat()}
    ).scalar()

    if not entry_date:
        print("No price data for current month.")
        session.close()
        return

    print(f"Entry date (first trading day): {entry_date}")

    alerts = {}

    for strategy_key, strategy in picks_data['picks'].items():
        stocks = strategy['stocks']
        symbols = [s['symbol'] for s in stocks]
        if not symbols:
            continue

        id_rows = session.execute(
            text("SELECT id, nse_symbol FROM stocks WHERE nse_symbol IN :syms AND is_active = true"),
            {'syms': tuple(symbols)}
        ).fetchall()
        sym_to_id = {r[1]: r[0] for r in id_rows}
        ids = list(sym_to_id.values())
        if not ids:
            continue

        # Entry prices = open on first trading day of month
        entry_rows = session.execute(
            text("SELECT stock_id, open_price FROM daily_prices WHERE stock_id IN :ids AND date = :dt"),
            {'ids': tuple(ids), 'dt': entry_date}
        ).fetchall()
        entry_map = {r[0]: float(r[1]) for r in entry_rows}

        # All daily OHLC from entry_date to latest_date — one query per strategy batch
        all_price_rows = session.execute(
            text("""
                SELECT stock_id, date, open_price, low_price, close_price
                FROM daily_prices
                WHERE stock_id IN :ids AND date >= :from_dt AND date <= :to_dt
                ORDER BY stock_id, date ASC
            """),
            {'ids': tuple(ids), 'from_dt': entry_date, 'to_dt': latest_date}
        ).fetchall()

        # Group by stock_id
        from collections import defaultdict
        price_history = defaultdict(list)
        for r in all_price_rows:
            sid2, d, open_p, low_p, close_p = r
            price_history[sid2].append((
                d,
                float(open_p)  if open_p  is not None else None,
                float(low_p)   if low_p   is not None else None,
                float(close_p) if close_p is not None else None,
            ))

        # Latest close for display
        latest_close_map = {}
        for sid2, rows in price_history.items():
            if rows:
                latest_close_map[sid2] = rows[-1][3]  # close of last row

        strategy_alerts = []
        for pick in stocks:
            sym = pick['symbol']
            sid = sym_to_id.get(sym)
            if not sid:
                continue
            entry_price = entry_map.get(sid)
            rows = price_history.get(sid, [])
            if not entry_price or not rows:
                continue

            event = find_stop_event(rows, entry_price)
            current_close = latest_close_map.get(sid)

            if event:
                stop_hit  = True
                stop_type = event['stop_type']
                stop_date = event['stop_date']
                exit_date = event['exit_date']
                ret       = event['ret']
                # overdue: close_stop exit was due today or earlier (already have that day's data)
                overdue   = (stop_type == 'close_stop' and
                             exit_date <= date_str(latest_date))
            else:
                stop_hit  = False
                stop_type = None
                stop_date = None
                exit_date = None
                overdue   = False
                ret = ((current_close - entry_price) / entry_price) if current_close else 0.0

            strategy_alerts.append({
                'rank':          pick['rank'],
                'symbol':        sym,
                'name':          pick.get('name', sym),
                'entry_date':    str(entry_date),
                'entry_price':   round(entry_price, 2),
                'current_close': round(current_close, 2) if current_close else None,
                'current_date':  str(latest_date),
                'return_pct':    round(ret * 100, 2),
                'stop_hit':      stop_hit,
                'stop_type':     stop_type,
                'stop_date':     stop_date,
                'exit_date':     exit_date,
                'overdue':       overdue,
            })

        strategy_alerts.sort(key=lambda x: x['return_pct'])
        alerts[strategy_key] = strategy_alerts

    session.close()

    hits = sum(sum(1 for a in v if a['stop_hit']) for v in alerts.values())
    next_trading_day = next_weekday(pd.Timestamp(latest_date).date()).isoformat()

    output = {
        'generated_at':    datetime.now().isoformat(timespec='seconds'),
        'current_month':   current_month,
        'entry_date':      str(entry_date),
        'latest_date':     str(latest_date),
        'next_trading_day': next_trading_day,
        'close_stop_pct':  CLOSE_STOP_PCT * 100,
        'gtt_stop_pct':    GTT_STOP_PCT * 100,
        'total_stop_hits': hits,
        'alerts':          alerts,
    }

    out_path = os.path.join(base_dir, 'web', 'src', 'data', 'stop_alerts.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {out_path}")
    print(f"Total stop hits: {hits}")
    for key, lst in alerts.items():
        for a in lst:
            if a['stop_hit']:
                overdue_tag = ' [OVERDUE]' if a.get('overdue') else ''
                print(f"  {key}: {a['symbol']} → {a['stop_type']} on {a['stop_date']}, exit {a['exit_date']}{overdue_tag} ({a['return_pct']:.1f}%)")


if __name__ == '__main__':
    main()
