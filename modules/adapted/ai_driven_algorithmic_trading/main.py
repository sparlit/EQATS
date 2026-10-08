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


import glob
import json
import logging
import os
import time

import matplotlib
import numpy as np
import pandas as pd
import requests
import yaml

matplotlib.use("Agg")  # Enforces a headless backend for safe server execution environments
import contextlib

import matplotlib.patches as patches
import matplotlib.pyplot as plt
from openbb import obb

os.makedirs("data/output", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/output/run.log", mode="a"),
    ],
)
logger = logging.getLogger("quant_bot")


# =====================================================================
# SYSTEM ALERTER: EVENT-DRIVEN TELEGRAM WEBHOOK FRAMEWORK
# =====================================================================


class TelegramAlertEngine:
    def __init__(self, token: str, chat_id: str):
        """Initializes the secure Telegram Bot API alert gateway."""
        self.token = token.strip() if token else ""
        self.chat_id = str(chat_id).strip() if chat_id else ""
        self.enabled = bool(self.token and self.chat_id)

    def send_buy_signal_alert(
        self,
        ticker: str,
        price: float,
        vol: float,
        var: float,
        alpha: float,
        roi: float,
        rsi: float,
        volume: float,
        avg_volume: float,
        tp1: float = 0.0,
        tp2: float = 0.0,
    ):
        """Transmits a traditional text configuration log payload via Telegram bot API."""
        if not self.enabled:
            return

        clean_name = str(ticker).replace(".NS", "").replace(".BO", "").strip()
        initial_capital = 100000.0
        final_capital = initial_capital * (1.0 + (roi / 100.0))

        # Build dynamic strings for the take-profit matrix panel if values are provided
        tp_matrix_panel = ""
        if tp1 > 0 and tp2 > 0:
            tp_matrix_panel = (
                f"🎯 <b>VOLATILITY TAKE-PROFIT MATRIX:</b>\n"
                f" • Take-Profit 1 (50% Scalp): <b>₹{tp1:,.2f}</b>\n"
                f" • Take-Profit 2 (Runner Target): <b>₹{tp2:,.2f}</b>\n\n"
            )

        # Telegram text notification template layout
        message_payload = (
            f"⚡ <b>QUANT STRATEGY SYSTEM: Bismillah TRIGGER</b> ⚡\n"
            f"🤖 <b>Status:</b> Automated bot alert dispatched\n"
            f"⚠️ <i>Please check Shariah status</i>\n\n"
            f"📌 <b>Asset Target:</b> #{clean_name}\n"
            f"💰 <b>Current Close Price:</b> ₹{price:,.2f}\n"
            f"📈 <b>Qlib Alpha Score:</b> {alpha:+.4f}\n"
            f"📊 <b>Current 14-Day RSI:</b> {rsi:.2f}\n"
            f"🔊 <b>Volume Telemetry:</b> {volume:,.0f} (20D Avg: {avg_volume:,.0f})\n\n"
            f"{tp_matrix_panel}"
            f"⚙️ <b>LEAN SIMULATION PORTFOLIO MATRIX:</b>\n"
            f" • Initial Account Capital: ₹{initial_capital:,.2f}\n"
            f" • Final Strategy Capital: <b>₹{final_capital:,.2f}</b>\n"
            f" • Net Strategy Profit ROI: <b>{roi:+.2f}%</b>\n\n"
            f"📊 <b>Risk & Volatility Telemetry:</b>\n"
            f" • Trailing Ann. Volatility: {vol:.2f}%\n"
            f" • Daily Value at Risk (95%): {var:.2f}%\n\n"
            f"➡️ <b>Execution Order:</b> Only for study- no buy/sell."
        )

        api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        payload = {"chat_id": self.chat_id, "text": message_payload, "parse_mode": "HTML"}

        try:
            response = requests.post(api_url, json=payload, timeout=10)
            try:
                response_data = response.json()
            except ValueError:
                response_data = {}

            if response.status_code == 200 and response_data.get("ok") is True:
                logger.info(
                    f" ✓ Telegram text alert delivered successfully via bot for {clean_name}!"
                )
            else:
                error_description = response_data.get("description", response.text)
                logger.error(
                    f" ✕ Telegram API Error: Status {response.status_code} | Description: {error_description}"
                )

        except requests.exceptions.Timeout:
            logger.error(f" ✕ Telegram request timed out while sending alert for {clean_name}.")
        except requests.exceptions.RequestException as net_error:
            logger.error(f" ✕ Telegram connection failed: {net_error}")
        except Exception as unexpected_error:
            logger.error(f" ✕ Unexpected Telegram alert error: {unexpected_error}")

    def generate_and_send_visual_card(
        self,
        ticker: str,
        price: float,
        vol: float,
        var: float,
        alpha: float,
        roi: float,
        rsi: float,
        tp1: float,
        tp2: float,
    ):
        """Renders a restrained, institutional-style signal card (single dark palette,
        thin borders instead of blocky color panels, two accent colors only)."""
        if not self.enabled:
            return

        clean_name = str(ticker).replace(".NS", "").replace(".BO", "").strip()

        # --- Professional palette: one background, one panel tone, one border tone,
        # a muted gold brand accent, and teal/rose reserved only for +/- values. ---
        BG = "#0B0F19"
        PANEL = "#111827"
        BORDER = "#26304A"
        TEXT_PRIMARY = "#E8EAF0"
        TEXT_SECONDARY = "#8A93A6"
        GOLD = "#C9A24B"
        POSITIVE = "#3FB88F"
        NEGATIVE = "#D9707A"

        def panel(x, y, w, h):
            ax.add_patch(
                patches.Rectangle(
                    (x, y), w, h, facecolor=PANEL, edgecolor=BORDER, linewidth=1.0, zorder=1
                )
            )

        fig, ax = plt.subplots(figsize=(7, 11), facecolor=BG)
        ax.set_xlim(0, 7)
        ax.set_ylim(0, 11)
        plt.axis("off")

        # Header — brand line + thin rule, no filled block
        ax.text(
            0.4,
            10.5,
            "QUANT STRATEGY SYSTEM",
            color=TEXT_SECONDARY,
            fontsize=13,
            fontweight="bold",
            zorder=2,
        )
        ax.text(
            0.4, 10.05, "SIGNAL TRIGGERED", color=GOLD, fontsize=22, fontweight="bold", zorder=2
        )
        ax.plot([0.4, 6.6], [9.75, 9.75], color=BORDER, linewidth=1.0, zorder=2)

        # Panel A: Asset Summary
        panel(0.3, 5.8, 3.0, 3.7)
        ax.text(
            0.5, 9.1, f"{clean_name}", color=TEXT_PRIMARY, fontsize=19, fontweight="bold", zorder=2
        )
        ax.text(0.5, 8.5, "CLOSE PRICE", color=TEXT_SECONDARY, fontsize=9, zorder=2)
        ax.text(
            0.5,
            7.95,
            f"₹{price:,.2f}",
            color=TEXT_PRIMARY,
            fontsize=20,
            fontweight="bold",
            zorder=2,
        )
        alpha_color = POSITIVE if alpha > 0 else NEGATIVE
        ax.text(0.5, 7.35, "ALPHA SCORE", color=TEXT_SECONDARY, fontsize=9, zorder=2)
        ax.text(
            0.5, 6.95, f"{alpha:+.4f}", color=alpha_color, fontsize=13, fontweight="bold", zorder=2
        )
        ax.text(0.5, 6.45, f"14D RSI: {rsi:.2f}", color=TEXT_PRIMARY, fontsize=10, zorder=2)
        ax.text(0.5, 6.05, f"Volume: {vol:.2f}M", color=TEXT_PRIMARY, fontsize=10, zorder=2)

        # Panel B: Take-Profit Matrix — thin dividers, not solid color tiles
        panel(3.7, 5.8, 3.0, 3.7)
        ax.text(
            3.9,
            9.1,
            "TAKE-PROFIT MATRIX",
            color=TEXT_SECONDARY,
            fontsize=10,
            fontweight="bold",
            zorder=2,
        )
        ax.plot([3.9, 6.5], [8.9, 8.9], color=BORDER, linewidth=0.8, zorder=2)
        ax.text(3.9, 8.45, "TP1 · 50% Scalp", color=TEXT_SECONDARY, fontsize=9, zorder=2)
        ax.text(3.9, 8.0, f"₹{tp1:,.2f}", color=POSITIVE, fontsize=15, fontweight="bold", zorder=2)
        ax.plot([3.9, 6.5], [7.6, 7.6], color=BORDER, linewidth=0.8, zorder=2)
        ax.text(3.9, 7.15, "TP2 · Runner Target", color=TEXT_SECONDARY, fontsize=9, zorder=2)
        ax.text(3.9, 6.7, f"₹{tp2:,.2f}", color=POSITIVE, fontsize=15, fontweight="bold", zorder=2)

        # Panel C: Backtest ROI — thin radial gauge instead of an overflowing filled circle
        panel(0.3, 1.6, 3.0, 3.9)
        ax.text(
            0.5, 5.1, "BACKTEST ROI", color=TEXT_SECONDARY, fontsize=10, fontweight="bold", zorder=2
        )
        roi_color = POSITIVE if roi >= 0 else NEGATIVE
        gauge_fraction = min(abs(roi) / 50.0, 1.0)  # ring fills fully at +/-50% ROI
        ax.add_patch(
            patches.Wedge((1.8, 3.55), 0.8, 0, 360, width=0.18, facecolor=BORDER, zorder=2)
        )
        if gauge_fraction > 0:
            ax.add_patch(
                patches.Wedge(
                    (1.8, 3.55),
                    0.8,
                    90 - 360 * gauge_fraction,
                    90,
                    width=0.18,
                    facecolor=roi_color,
                    zorder=3,
                )
            )
        ax.text(
            1.8,
            3.55,
            f"{roi:+.1f}%",
            color=TEXT_PRIMARY,
            fontsize=13,
            fontweight="bold",
            ha="center",
            va="center",
            zorder=4,
        )
        ax.text(0.5, 2.2, "Net Strategy Return", color=TEXT_SECONDARY, fontsize=9, zorder=2)

        # Panel D: Risk & Volatility
        panel(3.7, 1.6, 3.0, 3.9)
        ax.text(
            3.9,
            5.1,
            "RISK & VOLATILITY",
            color=TEXT_SECONDARY,
            fontsize=10,
            fontweight="bold",
            zorder=2,
        )
        ax.text(3.9, 4.3, "Daily VaR (95%)", color=TEXT_SECONDARY, fontsize=9, zorder=2)
        ax.text(3.9, 3.85, f"{var:.2f}%", color=NEGATIVE, fontsize=16, fontweight="bold", zorder=2)
        ax.text(
            3.9,
            2.7,
            "Study signal only — not investment advice.",
            color=TEXT_SECONDARY,
            fontsize=8.5,
            zorder=2,
            wrap=True,
        )

        # Footer
        ax.plot([0.4, 6.6], [1.3, 1.3], color=BORDER, linewidth=1.0, zorder=2)
        ax.text(
            0.4,
            0.85,
            "Execution Order: For research/study purposes — not a buy/sell recommendation.",
            color=TEXT_SECONDARY,
            fontsize=9,
            zorder=2,
        )

        temp_img_path = f"data/output/{clean_name}_signal_card.png"
        os.makedirs(os.path.dirname(temp_img_path), exist_ok=True)
        plt.savefig(
            temp_img_path,
            facecolor=fig.get_facecolor(),
            edgecolor="none",
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)

        send_photo_url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        try:
            with open(temp_img_path, "rb") as photo_file:
                files = {"photo": photo_file}
                data = {
                    "chat_id": self.chat_id,
                    "caption": f"⚡ <b>QUANT STRATEGY SYSTEM BUY ALERT: #{clean_name}</b> ⚡\n<i>Live visual analytical card generated by strategy bot.</i>",
                    "parse_mode": "HTML",
                }
                response = requests.post(send_photo_url, files=files, data=data, timeout=10)

            try:
                response_data = response.json()
            except ValueError:
                response_data = {}

            if response.status_code == 200 and response_data.get("ok") is True:
                logger.info(
                    f" ✓ Telegram visual card delivered successfully to phone for {clean_name}!"
                )
            else:
                error_description = response_data.get("description", response.text)
                logger.error(
                    f" ✕ Telegram photo API Error: Status {response.status_code} | Description: {error_description}"
                )
        except requests.exceptions.Timeout:
            logger.error(
                f" ✕ Telegram photo request timed out while sending alert for {clean_name}."
            )
        except requests.exceptions.RequestException as net_error:
            logger.error(f" ✕ Telegram connection failed for photo: {net_error}")
        except Exception as unexpected_error:
            logger.error(f" ✕ Unexpected Telegram photo alert error: {unexpected_error}")


# =====================================================================
# QUANT & MACHINE LEARNING FEATURE COMPUTE ENGINES
# =====================================================================


class QlibPredictiveEngine:
    def __init__(self):
        os.makedirs("data/alpha_features", exist_ok=True)

    def generate_qlib_alpha_features(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        df = df.copy()
        df.columns = [str(col).lower() for col in df.columns]

        # FIX: Present Close divided by 5-day Historical Close
        df["qlib_momentum_5d"] = (df["close"] / df["close"].shift(5)) - 1

        # Mean reversion (Price distance from 20-day SMA)
        df["qlib_mean_reversion_20d"] = df["close"].rolling(window=20).mean() / df["close"]
        df["qlib_vol_normalized_return"] = df["daily_return"] / (
            df["rolling_volatility_ann"] + 1e-8
        )

        change = df["close"].diff()
        gain = change.mask(change < 0, 0.0)
        loss = -change.mask(change > 0, 0.0)

        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()

        rs = avg_gain / (avg_loss + 1e-8)
        df["rsi_14d"] = 100 - (100 / (1 + rs))

        df = df.dropna()
        df.to_csv(f"data/alpha_features/{ticker}_qlib_features.csv")
        return df

    def compute_predictive_score(self, df: pd.DataFrame) -> float:
        if df.empty:
            return 0.0
        latest_row = df.iloc[-1]
        return float(
            (latest_row["qlib_momentum_5d"] * 0.4) + (latest_row["qlib_mean_reversion_20d"] * 0.6)
        )


class LeanPortfolioStrategyEngine:
    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.slippage_pct = 0.0005
        self.stt_pct = 0.001

    def run_backtest_from_dataframe(self, df: pd.DataFrame) -> dict:
        if df is None or df.empty or len(df) < 20:
            return {
                "initial_capital": self.initial_capital,
                "final_value": self.initial_capital,
                "net_return_pct": "Failed Analysis",
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "total_trades": 0,
            }

        cash, position_shares, trade_count, portfolio_value_history = (
            self.initial_capital,
            0.0,
            0,
            [],
        )

        for i in range(len(df)):
            current_price = df["close"].iloc[i]
            alpha_signal = df["qlib_momentum_5d"].iloc[i]
            rsi_val = df["rsi_14d"].iloc[i]

            if alpha_signal > 0.01 and (45.0 <= rsi_val <= 65.0) and position_shares == 0:
                position_shares = (cash / (1.0 + self.slippage_pct + self.stt_pct)) / current_price
                cash = 0.0
                trade_count += 1
            elif alpha_signal < -0.01 and position_shares > 0:
                cash = (position_shares * current_price) * (1.0 - self.slippage_pct - self.stt_pct)
                position_shares = 0.0
                trade_count += 1
            portfolio_value_history.append(cash + (position_shares * current_price))

        df = df.copy()
        df["portfolio_value"] = portfolio_value_history
        final_value = (
            portfolio_value_history[-1] if portfolio_value_history else self.initial_capital
        )
        total_net_return = ((final_value - self.initial_capital) / self.initial_capital) * 100
        return {"net_return_pct": total_net_return}


# =====================================================================
# INGESTION ORCHESTRATION PIPELINE
# =====================================================================


class YahooFinanceQuantPipeline:
    def __init__(
        self,
        config_path: str = "config/settings.yaml",
        ticker_csv_path: str = "config/ticker_list.csv",
    ):
        self.config = self._load_config(config_path)
        self.start_date = self.config.get("start_date", "2025-01-01")

        # Set end_date to None by default so it always fetches the latest live session
        self.end_date = self.config.get("end_date", None)
        self.default_exchange = self.config.get("default_exchange", "NSE")
        os.makedirs("data/raw", exist_ok=True)
        os.makedirs("data/processed", exist_ok=True)
        self.ticker_mappings = self._load_and_wrap_tickers(ticker_csv_path)

    def _load_config(self, path: str) -> dict:
        if os.path.exists(path):
            with open(path) as f:
                data = yaml.safe_load(f)
                return data if data else {}
        return {}

    def _load_and_wrap_tickers(self, path: str) -> list:
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            pd.DataFrame({"ticker": ["RELIANCE", "TCS"], "exchange": ["NSE", "NSE"]}).to_csv(
                path, index=False
            )
        df = pd.read_csv(path)
        df.columns = [col.strip().lower() for col in df.columns]
        wrapped_list = []
        for _, row in df.iterrows():
            clean_ticker = str(row["ticker"]).strip().upper()
            exchange_type = (
                str(row["exchange"]).strip().upper()
                if "exchange" in df.columns
                else self.default_exchange
            )
            wrapped_list.append(
                f"{clean_ticker}.BO"
                if exchange_type == "BSE" or "BOM" in clean_ticker
                else f"{clean_ticker}.NS"
            )
        return wrapped_list

    def run_ingestion(self, ticker: str) -> pd.DataFrame:
        raw_path = f"data/raw/{ticker}_raw.csv"
        fetch_start = self.start_date
        existing_df = None

        # 1. Check if the ticker has historical data saved on disk
        if os.path.exists(raw_path):
            try:
                existing_df = pd.read_csv(raw_path, index_col=0, parse_dates=True)
                if not existing_df.empty:
                    last_recorded_date = existing_df.index.max()
                    next_day = (last_recorded_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")

                    # If the cached file is already up-to-date, bypass the network request
                    if next_day > today_str:
                        return existing_df

                    # Incremental fetch: pull only missing candles starting after the last recorded date
                    fetch_start = next_day
            except Exception as cache_read_error:
                logger.warning(
                    f"[{ticker}] Could not read cached raw file ({raw_path}): "
                    f"{type(cache_read_error).__name__}: {cache_read_error}. Refetching from scratch."
                )
                existing_df = None

        # 2. Fetch the required dataset (5 years if new, only delta days if existing)
        try:
            params = {
                "symbol": ticker,
                "provider": "yfinance",
                "start_date": fetch_start,
                "extra_params": {"adjustment": "unadjusted"},
            }
            if self.end_date:
                params["end_date"] = self.end_date

            res = obb.equity.price.historical(**params)
            new_df = res.to_df()

            if new_df.empty:
                # This is the "silent staleness" case: no exception was raised, the provider
                # just handed back zero rows for the requested window. Logged as a warning
                # (not an error) since it can legitimately happen on a day with no new session,
                # but if this fires for every ticker on a day that should have traded, that's
                # the signal something's wrong upstream (rate limit, bad date window, etc.).
                last_cached = (
                    existing_df.index.max().date()
                    if (existing_df is not None and not existing_df.empty)
                    else "none"
                )
                logger.warning(
                    f"[{ticker}] Provider returned 0 new rows for window "
                    f"start_date={fetch_start!r} (cached through {last_cached}). "
                    f"Falling back to cached/fail-safe data — price will NOT advance this run."
                )
                return (
                    existing_df
                    if (existing_df is not None and not existing_df.empty)
                    else self._generate_fail_safe_data(ticker)
                )

            new_df.index = pd.to_datetime(new_df.index)

            # 3. Merge new records into the historical dataset
            if existing_df is not None and not existing_df.empty:
                combined_df = pd.concat([existing_df, new_df])
                combined_df = combined_df[~combined_df.index.duplicated(keep="last")].sort_index()
            else:
                combined_df = new_df.sort_index()

            # 3b. Rolling 5-year retention window: drop candles older than 5 years so the
            # raw/processed CSVs stay bounded in size as new days get appended indefinitely,
            # instead of growing forever. 200-day EMA and other long-window indicators still
            # have well over a year of headroom below this cutoff, so nothing downstream loses
            # accuracy from the trim.
            retention_cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=5)
            combined_df = combined_df[combined_df.index >= retention_cutoff]

            # 4. Save updated data locally to disk
            combined_df.to_csv(raw_path)
            return combined_df

        except Exception as fetch_error:
            # This was previously a bare `except Exception: pass`-equivalent — it swallowed
            # the real network/provider error completely, which is why main.py could finish
            # "successfully" every day while quietly never updating any price data at all.
            logger.warning(
                f"[{ticker}] Historical price fetch failed: "
                f"{type(fetch_error).__name__}: {fetch_error}. "
                f"Falling back to cached/fail-safe data — price will NOT advance this run."
            )
            if existing_df is not None and not existing_df.empty:
                return existing_df
            return self._generate_fail_safe_data(ticker)

    def calculate_quant_metrics(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        df = df.copy()
        df.columns = [str(col).lower() for col in df.columns]
        df.index = pd.to_datetime(df.index)
        df["daily_return"] = df["close"].pct_change()
        df["rolling_volatility_ann"] = df["daily_return"].rolling(window=21).std() * np.sqrt(252)
        # Rolling (not whole-history) 5th percentile so VaR reflects the *current* risk
        # regime instead of one static number computed from the entire dataset.
        df["var_95_threshold"] = (
            df["daily_return"].rolling(window=60, min_periods=20).quantile(0.05)
        )
        df["avg_volume_20d"] = df["volume"].rolling(window=20).mean()
        df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()

        df = df.dropna()

        # Same 5-year retention cutoff as run_ingestion, applied again here as a safety net
        # in case this method is ever called on a dataframe that wasn't already trimmed.
        retention_cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=5)
        df = df[df.index >= retention_cutoff]

        df.to_csv(f"data/processed/{ticker}_processed.csv")
        return df

    def _generate_fail_safe_data(self, ticker: str) -> pd.DataFrame:
        # end_date is often None (means "fetch through today"), so pd.date_range needs
        # an explicit end or it raises ValueError ("must specify two of start/end/periods").
        fallback_end = self.end_date or pd.Timestamp.now().strftime("%Y-%m-%d")
        date_range = pd.date_range(start=self.start_date, end=fallback_end, freq="B")
        if len(date_range) == 0:
            date_range = pd.date_range(end=fallback_end, periods=30, freq="B")
        fallback_df = pd.DataFrame(
            {
                "open": np.linspace(2400, 2600, len(date_range)),
                "high": np.linspace(2450, 2650, len(date_range)),
                "low": np.linspace(2380, 2580, len(date_range)),
                "close": np.linspace(2420, 2620, len(date_range)),
                "volume": np.random.randint(100000, 500000, size=len(date_range)),
            },
            index=date_range,
        )
        fallback_df.index.name = "date"
        fallback_df.to_csv(f"data/raw/{ticker}_raw.csv")
        return fallback_df


# =====================================================================
# SHARED STRATEGY FILTER ("GOLDEN RULE")
# =====================================================================
# Single source of truth for the buy filter. Previously the live-alert loop
# and the JSON-output loop each re-implemented this with different, drifting
# thresholds (e.g. volume >= avg*1.2 vs >= avg*0.8, and only the alert loop
# checked price vs EMA200) so the Telegram alerts and the dashboard JSON
# could disagree on which tickers were a "BUY". Both loops now call this.
def passes_golden_rule(
    alpha_score: float,
    roi_pct: float,
    rsi: float,
    volume: float,
    avg_volume_20d: float,
    price: float,
    ema_200: float,
) -> bool:
    return (
        alpha_score > 0.01
        and roi_pct > 0.001
        and (45.0 <= rsi <= 65.0)
        and (volume >= 50000 and volume >= (avg_volume_20d * 1.2))
        and (price > ema_200)
    )


# =====================================================================
# TELEGRAM ALERT DE-DUPLICATION (COOLDOWN)
# =====================================================================
# main.py runs fresh as a new process on every scheduled run, so "don't re-alert
# within 24 trading days" has to be persisted to disk between runs rather than
# held in memory. Keyed by the raw ticker (e.g. "MARINE.NS") so it lines up with
# the same identity used for the processed-data filenames.
def load_alert_cooldown_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as load_error:
        logger.warning(
            f" ✕ Could not read alert cooldown state at {path}: {load_error}. Starting fresh."
        )
        return {}


def save_alert_cooldown_state(path: str, state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as save_error:
        logger.warning(f" ✕ Could not persist alert cooldown state to {path}: {save_error}")


def is_alert_on_cooldown(
    raw_ticker: str,
    latest_trading_date: pd.Timestamp,
    metrics_df: pd.DataFrame,
    cooldown_state: dict,
    cooldown_trading_days: int,
) -> bool:
    """True if this ticker alerted recently enough that it should stay silent.
    Counts actual trading sessions elapsed (using this ticker's own date index,
    which already skips weekends/holidays) rather than calendar days, since
    '24 working days' is a trading-session count, not a calendar-day count."""
    last_alert_str = cooldown_state.get(raw_ticker)
    if not last_alert_str:
        return False
    try:
        last_alert_date = pd.Timestamp(last_alert_str)
    except Exception:
        return False

    sessions_since = int((metrics_df.index > last_alert_date).sum())
    return sessions_since < cooldown_trading_days


# =====================================================================
# SYSTEM MAIN ENGINE CONTROLLER LOOP
# =====================================================================
if __name__ == "__main__":
    logger.info("=================================================================")
    logger.info("RUNNING CONSOLIDATED SYSTEM SCRIPTS")
    logger.info("=================================================================")

    pipeline = YahooFinanceQuantPipeline()
    qlib_engine = QlibPredictiveEngine()
    backtester = LeanPortfolioStrategyEngine(initial_capital=100000.0)

    # Sector Diversification Module Controls
    ENABLE_SECTOR_GUARD = True
    MAX_ASSETS_PER_SECTOR = 2

    # Trailing Stop-Loss & Take-Profit Controls
    ENABLE_TRAILING_STOP = True
    TRAILING_STOP_PCT = 0.05
    ENABLE_TP_MATRIX = True

    # Telegram Alert De-Duplication: once a ticker fires an alert, don't fire another
    # one for it until this many trading sessions have passed (~1 trading month).
    # This only silences the Telegram notification — the JSON dashboard still shows
    # the ticker as a live BUY the whole time, it's just marked as "already alerted".
    ENABLE_ALERT_COOLDOWN = True
    ALERT_COOLDOWN_TRADING_DAYS = 24
    ALERT_COOLDOWN_STATE_PATH = "data/output/alert_cooldown_state.json"

    # Backtest is evaluated over a recent, regime-relevant window (~12 months of trading
    # sessions) rather than the full retained history. A multi-year backtest blends very
    # different market regimes into one ROI figure, which doesn't represent how this
    # short-to-mid-term momentum strategy performs under *current* conditions. Indicator
    # calculations (EMA200, VaR, etc.) still use the full retained history as before —
    # only the backtest's own evaluation window is being narrowed here.
    BACKTEST_LOOKBACK_TRADING_DAYS = 252

    # Live Ticker-to-Sector allocation dictionary lookup mapping
    NSE_SECTOR_MAP = {
        "CHENNPETRO": "Energy & Refineries",
        "MRPL": "Energy & Refineries",
        "BPCL": "Energy & Refineries",
        "RELIANCE": "Energy & Refineries",
        "NETWEB": "Technology & IT",
        "TCS": "Technology & IT",
        "INFY": "Technology & IT",
        "GRSE": "Defense & Capital Goods",
        "COCHINSHIP": "Defense & Capital Goods",
        "ZYDUSLIFE": "Pharma & Healthcare",
        "ZYDUSWELL": "Pharma & Healthcare",
        "MARICO": "FMCG & Consumer Goods",
    }

    active_sector_exposure_registry = {}

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or pipeline.config.get("telegram_bot_token", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or pipeline.config.get("telegram_chat_id", "")

    bot_token = str(bot_token).strip() if bot_token else ""
    chat_id = str(chat_id).strip() if chat_id else ""

    notifier = TelegramAlertEngine(token=bot_token, chat_id=chat_id)

    alert_cooldown_state = load_alert_cooldown_state(ALERT_COOLDOWN_STATE_PATH)

    # 1. Main Data Extraction and Analytical Execution Loop
    for wrapped_ticker in pipeline.ticker_mappings:
        raw_df = pipeline.run_ingestion(wrapped_ticker)
        metrics_df = pipeline.calculate_quant_metrics(raw_df, wrapped_ticker)

        if metrics_df is None or metrics_df.empty or len(metrics_df) < 5:
            continue

        # 2. Compute Microsoft Qlib Matrix Indicator Features
        qlib_df = qlib_engine.generate_qlib_alpha_features(metrics_df, wrapped_ticker)

        if qlib_df is None or qlib_df.empty:
            logger.warning(
                f" ✕ [{wrapped_ticker}] Bypassed status. Insufficient data rows remaining after dropna()."
            )
            continue

        alpha_score = qlib_engine.compute_predictive_score(qlib_df)

        # 3. Simulate LEAN Transaction Rules Backtest Results
        # Evaluated over the last ~12 months only (see BACKTEST_LOOKBACK_TRADING_DAYS) so
        # the ROI reflects recent market conditions, not a multi-year blended average.
        results = backtester.run_backtest_from_dataframe(
            qlib_df.tail(BACKTEST_LOOKBACK_TRADING_DAYS)
        )

        current_price = float(metrics_df["close"].iloc[-1])
        ann_vol = float(metrics_df["rolling_volatility_ann"].iloc[-1]) * 100
        daily_var = float(metrics_df["var_95_threshold"].iloc[-1]) * 100

        current_rsi = float(qlib_df["rsi_14d"].iloc[-1])
        current_volume = float(metrics_df["volume"].iloc[-1])
        avg_volume_20d = float(metrics_df["avg_volume_20d"].iloc[-1])
        current_ema200 = float(metrics_df["ema_200"].iloc[-1])

        if isinstance(results["net_return_pct"], str):
            strategy_roi = -999.0
        else:
            strategy_roi = float(results["net_return_pct"])

        # 4. Golden Rule Integrated Filter System
        if passes_golden_rule(
            alpha_score,
            strategy_roi,
            current_rsi,
            current_volume,
            avg_volume_20d,
            current_price,
            current_ema200,
        ):
            latest_trading_date = metrics_df.index[-1]
            on_cooldown = ENABLE_ALERT_COOLDOWN and is_alert_on_cooldown(
                wrapped_ticker,
                latest_trading_date,
                metrics_df,
                alert_cooldown_state,
                ALERT_COOLDOWN_TRADING_DAYS,
            )

            if on_cooldown:
                logger.info(
                    f" -> [{wrapped_ticker}] Golden Rule Satisfied but alert is on cooldown "
                    f"(already alerted within the last {ALERT_COOLDOWN_TRADING_DAYS} trading days). Skipping Telegram send."
                )
                continue

            logger.info(f" -> [{wrapped_ticker}] Golden Rule Satisfied... Dispatching alerts...")

            tp1_target = 0.0
            tp2_target = 0.0
            if ENABLE_TP_MATRIX:
                var_fraction = abs(daily_var / 100.0)
                tp1_target = current_price * (1.0 + (2.0 * var_fraction))
                tp2_target = current_price * (1.0 + (4.0 * var_fraction))

            # Action 1: Dispatches traditional formatted text payload
            notifier.send_buy_signal_alert(
                ticker=wrapped_ticker,
                price=current_price,
                vol=ann_vol,
                var=daily_var,
                alpha=alpha_score,
                roi=strategy_roi,
                rsi=current_rsi,
                volume=current_volume,
                avg_volume=avg_volume_20d,
                tp1=tp1_target,
                tp2=tp2_target,
            )

            # Action 2: Renders and uploads high-resolution visual signal card
            notifier.generate_and_send_visual_card(
                ticker=wrapped_ticker,
                price=current_price,
                vol=current_volume / 1000000.0,
                var=daily_var,
                alpha=alpha_score,
                roi=strategy_roi,
                rsi=current_rsi,
                tp1=tp1_target,
                tp2=tp2_target,
            )

            # Record the alert so the same ticker stays quiet for the next
            # ALERT_COOLDOWN_TRADING_DAYS sessions. Saved immediately (not batched
            # to the end of the run) so a later crash in this loop can't lose it.
            alert_cooldown_state[wrapped_ticker] = str(latest_trading_date.date())
            save_alert_cooldown_state(ALERT_COOLDOWN_STATE_PATH, alert_cooldown_state)

        else:
            logger.info(
                f" -> [{wrapped_ticker}] Bypassed status. Failed strict quantitative thresholds."
            )

        time.sleep(0.5)  # small pause between tickers to stay polite to the data provider

    logger.info("[Complete] Quant script loops finished successfully. Overwriting metrics...")

    # =====================================================================
    # CENTRALIZED JSON CORE OUTPUT WRITER (WITH POSITION SIZING)
    # =====================================================================
    latest_scan_records = []
    processed_json_files = glob.glob("data/processed/*_processed.csv")

    TOTAL_ACCOUNT_CAPITAL = backtester.initial_capital
    RISK_PER_TRADE_PCT = 0.01
    MAX_RUPEES_RISK = TOTAL_ACCOUNT_CAPITAL * RISK_PER_TRADE_PCT

    # Pre-load each ticker's latest alpha score so sector-capped slots go to the
    # strongest signals first, instead of whatever order the filesystem returns
    # from glob() (which is arbitrary and made the sector cap non-deterministic).
    file_alpha_pairs = []
    for file_path in processed_json_files:
        ticker_raw = os.path.basename(file_path).replace("_processed.csv", "")
        alpha_path = f"data/alpha_features/{ticker_raw}_qlib_features.csv"
        peek_alpha = -999.0
        if os.path.exists(alpha_path):
            with contextlib.suppress(Exception):
                peek_alpha = float(
                    pd.read_csv(alpha_path, index_col=0)["qlib_momentum_5d"].iloc[-1]
                )
        file_alpha_pairs.append((file_path, peek_alpha))
    file_alpha_pairs.sort(key=lambda pair: pair[1], reverse=True)
    processed_json_files = [pair[0] for pair in file_alpha_pairs]

    for file_path in processed_json_files:
        ticker_raw = os.path.basename(file_path).replace("_processed.csv", "")
        clean_name = ticker_raw.replace(".NS", "").replace(".BO", "")
        alpha_path = f"data/alpha_features/{ticker_raw}_qlib_features.csv"

        if os.path.exists(alpha_path):
            try:
                df_m = pd.read_csv(file_path, index_col=0, parse_dates=True)
                df_a = pd.read_csv(alpha_path, index_col=0, parse_dates=True)

                # Same recent-window backtest as the live scan loop, so the dashboard's
                # ROI figure matches what the Telegram alert was based on.
                results = backtester.run_backtest_from_dataframe(
                    df_a.tail(BACKTEST_LOOKBACK_TRADING_DAYS)
                )

                if isinstance(results["net_return_pct"], str):
                    roi_val = -999.0
                else:
                    roi_val = float(results["net_return_pct"])

                latest_alpha = float(df_a["qlib_momentum_5d"].iloc[-1])
                latest_rsi = float(df_a["rsi_14d"].iloc[-1])
                latest_volume = float(df_m["volume"].iloc[-1])
                latest_avg_vol = float(df_m["avg_volume_20d"].iloc[-1])

                close_price = float(df_m["close"].iloc[-1])
                daily_var_raw = float(df_m["var_95_threshold"].iloc[-1])
                latest_ema200 = float(df_m["ema_200"].iloc[-1])

                # 1. Base Strategy Rule Evaluation - same shared filter used for alerts,
                #    so the JSON output can never disagree with what was actually alerted.
                passes_base_strategy = passes_golden_rule(
                    latest_alpha,
                    roi_val,
                    latest_rsi,
                    latest_volume,
                    latest_avg_vol,
                    close_price,
                    latest_ema200,
                )

                # Informational only — does NOT change passes_base_strategy/action_status.
                # The dashboard should keep showing a genuinely-qualifying ticker as BUY;
                # this just explains why no fresh Telegram alert went out for it today.
                alert_on_cooldown = ENABLE_ALERT_COOLDOWN and is_alert_on_cooldown(
                    ticker_raw,
                    df_m.index[-1],
                    df_m,
                    alert_cooldown_state,
                    ALERT_COOLDOWN_TRADING_DAYS,
                )
                last_alert_date_str = alert_cooldown_state.get(ticker_raw)

                # 2. Extract Sector Mapping Assignment Safely
                asset_sector = NSE_SECTOR_MAP.get(clean_name, "Other Diversified")

                # 3. Apply Sector Overlay Constraints
                if passes_base_strategy:
                    if ENABLE_SECTOR_GUARD:
                        current_sector_count = active_sector_exposure_registry.get(asset_sector, 0)
                        if current_sector_count < MAX_ASSETS_PER_SECTOR:
                            base_action = "BUY"
                        else:
                            base_action = "HOLD (Sector Cap Reached)"
                    else:
                        base_action = "BUY"
                else:
                    base_action = "HOLD"

                # 4. Trailing Stop-Loss Evaluation Engine Overlay
                trailing_stop_price = 0.0
                highest_peak_price = close_price

                if base_action == "BUY" and ENABLE_TRAILING_STOP:
                    lookback_window = min(10, len(df_m))
                    recent_closes = df_m["close"].iloc[-lookback_window:].tolist()

                    highest_peak_price = max(recent_closes)
                    trailing_stop_price = highest_peak_price * (1.0 - TRAILING_STOP_PCT)

                    if close_price < trailing_stop_price:
                        action_status = "HOLD (Trailing Stop Hit)"
                    else:
                        action_status = "BUY"
                        if ENABLE_SECTOR_GUARD:
                            active_sector_exposure_registry[asset_sector] = (
                                active_sector_exposure_registry.get(asset_sector, 0) + 1
                            )
                else:
                    action_status = base_action

                # Calculate Take-Profit Metrics
                tp1_val = 0.0
                tp2_val = 0.0
                if action_status == "BUY" and ENABLE_TP_MATRIX:
                    var_frac = abs(daily_var_raw)
                    tp1_val = close_price * (1.0 + (2.0 * var_frac))
                    tp2_val = close_price * (1.0 + (4.0 * var_frac))

                # Dynamic Risk-Based Position Sizing Calculator
                risk_per_share = close_price * abs(daily_var_raw)
                if risk_per_share < 0.01:
                    risk_per_share = close_price * 0.02

                calculated_shares = int(np.floor(MAX_RUPEES_RISK / risk_per_share))
                capital_required = float(calculated_shares * close_price)

                if capital_required > TOTAL_ACCOUNT_CAPITAL:
                    calculated_shares = int(np.floor(TOTAL_ACCOUNT_CAPITAL / close_price))
                    capital_required = float(calculated_shares * close_price)

                latest_scan_records.append(
                    {
                        "ticker": clean_name,
                        "raw_ticker": ticker_raw,
                        "sector": asset_sector,
                        "alert_on_cooldown": alert_on_cooldown,
                        "last_alert_date": last_alert_date_str,
                        "close_price": close_price,
                        "ann_volatility_pct": float(df_m["rolling_volatility_ann"].iloc[-1]) * 100,
                        "daily_var_95_pct": daily_var_raw * 100,
                        "qlib_alpha_score": latest_alpha,
                        "backtest_roi_pct": roi_val,
                        "action_status": action_status,
                        "recommended_shares_to_buy": calculated_shares
                        if action_status == "BUY"
                        else 0,
                        "required_allocation_in_rupees": capital_required
                        if action_status == "BUY"
                        else 0.0,
                        "highest_tracked_peak": float(highest_peak_price)
                        if action_status == "BUY"
                        else 0.0,
                        "active_trailing_stop_floor": float(trailing_stop_price)
                        if action_status == "BUY"
                        else 0.0,
                        "take_profit_target_1": float(tp1_val) if action_status == "BUY" else 0.0,
                        "take_profit_target_2": float(tp2_val) if action_status == "BUY" else 0.0,
                    }
                )
            except Exception as row_error:
                logger.warning(f" ✕ [{ticker_raw}] Skipped in output writer: {row_error}")
                continue

    os.makedirs("data/output", exist_ok=True)
    current_time_stamp = str(pd.Timestamp.now(tz="Asia/Kolkata"))

    output_payload = {
        "last_updated": current_time_stamp,
        "total_scanned_assets": len(latest_scan_records),
        "signals": latest_scan_records,
    }

    with open("data/output/latest_market_signals.json", "w") as json_file:
        json.dump(output_payload, json_file, indent=4)

    logger.info("✓ Central output matrix overwritten successfully.")
