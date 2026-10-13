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
Telegram bot — NSE pipeline trigger
Whitelists a single Telegram user ID. All other senders are silently ignored.

Commands:
  /start        — show help
  /run_pipeline — choose Rebalance, Monitor, or Mid-Month via buttons, then run
  /run_regime   — run regime_master.py (weekly HMM + liquidity risk)
  /status       — check if pipeline or regime is running

Monitor and Mid-Month share identical Telegram output format.
Difference: monitor is read-only; mid-month writes portfolio_state.parquet.
"""

import asyncio
import json
import logging
import os
import re
import signal
from pathlib import Path

import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["TELEGRAM_USER_ID"])
BASE = Path("/home/ec2-user/nse-factor-engine")
PIPELINE_SCRIPT = BASE / "run_pipeline.py"
REGIME_SCRIPT = BASE / "hmm-factor-engine" / "regime" / "regime_master.py"
FORMAT_PDF_CMD = ["python3", str(BASE / "ops" / "format_portfolio_pdf.py")]
MKT_PDF_DIR = BASE / "market_movement" / "data"
REGIME_PDF_DIR = BASE / "hmm-factor-engine" / "regime" / "data"
SIGNALS_DIR = BASE / "signals" / "stage6"
PIPELINE_TIMEOUT = 3600
REGIME_TIMEOUT = 3600
PARQUET_POLL_INTERVAL = 5
PARQUET_MAX_WAIT = 300
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    filename="/home/ec2-user/telegram_bot.log",
)


def is_allowed(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_USER_ID


# ── Helpers ───────────────────────────────────────────────────────────────────


async def wait_for_parquet(update):
    run_date_str = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%d%m%Y")
    parquet_path = SIGNALS_DIR / f"portfolio_recommendations_{run_date_str}.parquet"
    elapsed = 0
    while elapsed < PARQUET_MAX_WAIT:
        if parquet_path.exists():
            logging.info(f"Parquet found after {elapsed}s: {parquet_path.name}")
            return True
        await asyncio.sleep(PARQUET_POLL_INTERVAL)
        elapsed += PARQUET_POLL_INTERVAL
    await update.message.reply_text(
        f"Portfolio parquet not found after {PARQUET_MAX_WAIT // 60} minutes "
        f"({parquet_path.name}). Stage 6 may have failed — check pipeline logs."
    )
    return False


async def send_pdf(update, pdf_path: Path, label: str):
    if pdf_path.exists():
        with open(pdf_path, "rb") as f:
            await update.message.reply_document(f, filename=pdf_path.name)
    else:
        await update.message.reply_text(f"{label} PDF not found ({pdf_path.name}).")


def format_monitor_mid_message(data, mode):
    """
    Shared formatter for both monitor and mid_month modes.
    Both produce identical JSON structure; only the header differs.
    """
    ACTION_EMOJI = {"HOLD": "🔵", "BUY": "🟢", "SELL": "🔴"}

    # ── Header ────────────────────────────────────────────────────────────────
    if mode == "mid_month":
        header = f"🔀 <b>Mid-Month RSI Overlay · {data['as_of']}</b>"
        n_exits = data.get("n_exits", 0)
        n_replaced = data.get("n_replaced", 0)
        n_cash = data.get("n_cash", 0)
        subheader = (
            f"Rebal: {data.get('rebal_date', '—')} | "
            f"Day {data.get('trading_day', '—')} | "
            f"Nifty500 12m: {data['mkt_ret'] * 100:+.1f}% | "
            f"Port β: {data['port_beta']:.2f}"
        )
        summary = (
            f"📊 {len([s for s in data['stocks'] if s['action'] == 'HOLD'])} HOLD  "
            f"🔴 {n_exits} EXIT  "
            f"🟢 {n_replaced} BUY  "
            f"💰 {n_cash} → Cash"
        )
        lines = [header, subheader, summary, ""]
    else:
        header = f"📊 <b>Monitor · {data['as_of']}</b>"
        lines = [
            header,
            f"Rebal: {data.get('rebal_date', '—')} | "
            f"Nifty500 returns past 12m: {data['mkt_ret'] * 100:+.1f}% | "
            f"Port β: {data['port_beta']:.2f}",
            "",
        ]

    # ── Per-stock rows ────────────────────────────────────────────────────────
    sell_divider_inserted = False
    for s in data["stocks"]:
        # Insert divider before first SELL
        if s["action"] == "SELL" and not sell_divider_inserted:
            lines.append("─" * 32)
            label = (
                "🔴 <b>MID-MONTH EXITS</b>"
                if mode == "mid_month"
                else "🔴 <b>EXITING POSITIONS</b>"
            )
            lines.append(label)
            lines.append("")
            sell_divider_inserted = True

        # RSI colour logic
        if s["action"] == "SELL":
            em = "🔴"
            r, t, chg = s.get("rsi_rebal"), s.get("rsi_today"), s.get("rsi_chg") or 0
            if r is not None and t is not None:
                rsi = f"RSI(rebal→now) {r:.0f}→{t:.0f} ({chg:+.0f})"
            elif t is not None:
                rsi = f"RSI(now) {t:.0f}"
            else:
                rsi = "RSI —"

        elif s.get("rsi_rebal") is not None and s.get("rsi_today") is not None:
            r, t, chg = s["rsi_rebal"], s["rsi_today"], s.get("rsi_chg") or 0
            if r < 50 and t < 50 and chg <= 0:
                em = "🔴"
            elif r < 50 and t < 50 and chg > 0:
                em = "🟠"
            elif r < 50 and t >= 50:
                em = "🔵"
            elif r >= 50 and t < 50:
                em = "🔴"
            else:
                em = "🔵"
            rsi_vals = f"{r:.0f}→{t:.0f} ({chg:+.0f})"
            exit_flag = (r < 50 and t < 50 and chg <= 0) or (r >= 50 and t < 50)
            rsi = (
                f"⚠️ <b>RSI(rebal→now) {rsi_vals}</b>" if exit_flag else f"RSI(rebal→now) {rsi_vals}"
            )

        elif s.get("rsi_today") is not None:
            # rsi_rebal not available (e.g. mid_month BUY — new entry)
            em = ACTION_EMOJI.get(s["action"], "🟢")
            rsi = f"RSI(now) {s['rsi_today']:.0f}"

        else:
            em = ACTION_EMOJI.get(s["action"], "⚪")
            rsi = "RSI —"

        beta = f"β:{s['beta']:.2f}" if s.get("beta") is not None else "β:—"
        alpha = f"α:{s['alpha'] * 100:+.0f}%" if s.get("alpha") is not None else "α:—"
        ret = f"R:{s['ret12m'] * 100:+.0f}%" if s.get("ret12m") is not None else "R:—"
        rank = s.get("rank", "—")
        score = s.get("score")

        action_tag = ""
        if s["action"] == "SELL":
            action_tag = " <b>[EXIT]</b>"
        elif s["action"] == "BUY" and mode == "mid_month":
            replaces = s.get("replaces", "")
            action_tag = f" <b>[MID-BUY ↩ {replaces}]</b>" if replaces else " <b>[MID-BUY]</b>"

        score_str = f"({score:.2f})" if score is not None else ""
        lines.append(f"{em} <b>{rank}. {s['symbol']}</b>{action_tag}  {score_str}")
        lines.append(f"     {rsi} | {beta} | {alpha} | {ret}")
        lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines.append("─" * 32)
    lines.append("⚠️ <i>Exit signal if:</i>")
    lines.append("<i>• Rebal RSI &amp; Today RSI both &lt;50 with RSI declining</i>")
    lines.append("<i>• Rebal RSI &gt;50 and Today RSI &lt;50</i>")

    return "\n".join(lines)


def format_buysell_summary(data, mode):
    """Second message: BUY/SELL summary."""
    if mode == "mid_month":
        buys = sorted([s["symbol"] for s in data["stocks"] if s["action"] == "BUY"])
        sells = sorted([s["symbol"] for s in data["stocks"] if s["action"] == "SELL"])
        title = "📋 <b>Mid-Month Changes</b>"
        buy_label = "🟢 <b>MID-BUY</b>"
        sell_label = "🔴 <b>MID-SELL</b>"
    else:
        buys = sorted([s["symbol"] for s in data["stocks"] if s["action"] == "BUY"])
        sells = sorted([s["symbol"] for s in data["stocks"] if s["action"] == "SELL"])
        title = "📋 <b>BUY/SELL based on momentum score change</b>"
        buy_label = f"🟢 <b>Would BUY  ({len(buys)})</b>"
        sell_label = f"🔴 <b>Would SELL ({len(sells)})</b>"

    lines = [title, ""]
    lines.append(f"{buy_label}: {', '.join(buys) if buys else '—'}")
    lines.append(f"{sell_label}: {', '.join(sells) if sells else '—'}")
    return "\n".join(lines)


async def send_chunks(query, text):
    """Split long messages into ≤4000 char chunks and send."""
    chunks = []
    while len(text) > 4000:
        split_at = text.rfind("\n\n", 0, 4000)
        if split_at == -1:
            split_at = 4000
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    chunks.append(text)
    for chunk in chunks:
        if chunk.strip():
            await query.message.reply_text(chunk.strip(), parse_mode="HTML")


# ── /start ────────────────────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "NSE Pipeline Bot\n\n"
        "Commands:\n"
        "  /run_pipeline — run full pipeline (Rebalance / Monitor / Mid-Month)\n"
        "  /run_regime   — run weekly regime & liquidity risk engine\n"
        "  /status       — check if a run is in progress"
    )


# ── /run_pipeline — show mode buttons ─────────────────────────────────────────


async def run_pipeline_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    keyboard = [
        [
            InlineKeyboardButton("🔄 Rebalance", callback_data="pipeline_rebalance"),
            InlineKeyboardButton("👁 Monitor", callback_data="pipeline_monitor"),
            InlineKeyboardButton("🔀 Mid-Month", callback_data="pipeline_mid_month"),
        ]
    ]
    await update.message.reply_text(
        "Select pipeline mode:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── Button callback — mode selected ───────────────────────────────────────────


async def pipeline_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ALLOWED_USER_ID:
        return

    if query.data == "pipeline_rebalance":
        mode = "rebalance"
    elif query.data == "pipeline_monitor":
        mode = "monitor"
    else:
        mode = "mid_month"

    await query.edit_message_text(f"Mode: {mode.upper()} — starting pipeline...")
    logging.info(f"Pipeline triggered in {mode} mode by user {query.from_user.id}")

    env = os.environ.copy()
    env["STAGE6_MODE"] = mode
    env["TZ"] = "Asia/Kolkata"

    try:
        process = await asyncio.create_subprocess_exec(
            "python3",
            str(PIPELINE_SCRIPT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(BASE),
            env=env,
        )

        json_lines = []
        in_json_block = [False]

        async def read_stdout():
            async for line_bytes in process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").rstrip()

                # Capture JSON for monitor and mid_month
                if mode in ("monitor", "mid_month"):
                    if "<<<MONITOR_JSON_START>>>" in line:
                        in_json_block[0] = True
                        continue
                    elif "<<<MONITOR_JSON_END>>>" in line:
                        in_json_block[0] = False
                        continue
                    elif in_json_block[0]:
                        json_lines.append(line.strip())

                # Stage progress messages
                if "STARTING STAGE 1" in line:
                    await query.message.reply_text("🔄 Stage 1 — Universe fetch started")
                elif "STARTING STAGE 2" in line:
                    await query.message.reply_text("🔄 Stage 2 — Momentum signals")
                elif "STARTING STAGE 3" in line:
                    await query.message.reply_text("🔄 Stage 3 — Quality signals")
                elif "STARTING STAGE 4" in line:
                    await query.message.reply_text("🔄 Stage 4 — Entry filters")
                elif "STARTING STAGE 5" in line:
                    await query.message.reply_text("🔄 Stage 5 — Ranking & selection")
                elif "STARTING STAGE 6" in line:
                    await query.message.reply_text("🔄 Stage 6 — Portfolio recommendations")
                elif "STARTING INDEX FETCH" in line:
                    await query.message.reply_text("🔄 Index fetch — data/fetch_index_data.py")
                elif "STARTING MARKET MOVEMENT — Compute" in line:
                    await query.message.reply_text("🔄 Market movement — computing metrics")
                elif "STARTING MARKET MOVEMENT — Generate" in line:
                    await query.message.reply_text("🔄 Market movement — generating PDF")

                elif "CHECKPOINT" in line and "saving" in line:
                    m = re.search(r"CHECKPOINT\s+(\d+)", line)
                    if m:
                        await query.message.reply_text(f"📊 Stage 1 — {m.group(1)} stocks done")

                elif "completed successfully" in line:
                    if "STAGE 1" in line:
                        await query.message.reply_text("✅ Stage 1 complete")
                    elif "STAGE 2" in line:
                        await query.message.reply_text("✅ Stage 2 complete")
                    elif "STAGE 3" in line:
                        await query.message.reply_text("✅ Stage 3 complete")
                    elif "STAGE 4" in line:
                        await query.message.reply_text("✅ Stage 4 complete")
                    elif "STAGE 5" in line:
                        await query.message.reply_text("✅ Stage 5 complete")
                    elif "STAGE 6" in line:
                        await query.message.reply_text("✅ Stage 6 complete")
                    elif "INDEX FETCH" in line:
                        await query.message.reply_text("✅ Index data fetched")
                    elif "Compute Metrics" in line:
                        await query.message.reply_text("✅ Market metrics computed")
                    elif "Generate PDF" in line:
                        await query.message.reply_text("✅ Market PDF generated")

        try:
            await asyncio.wait_for(read_stdout(), timeout=PIPELINE_TIMEOUT)
        except TimeoutError:
            process.kill()
            await process.wait()
            await query.message.reply_text("Pipeline timed out after 1 hour.")
            return

        await process.wait()

        if process.returncode != 0:
            await query.message.reply_text(
                f"Pipeline failed (exit {process.returncode}). "
                f"Check logs: journalctl -u telegram-pipeline-bot -n 50"
            )
            return

        await query.message.reply_text("Pipeline complete. Generating reports...")

        # ── Monitor + Mid-Month: shared JSON formatting ───────────────────────
        if mode in ("monitor", "mid_month"):
            if json_lines:
                try:
                    data = json.loads("".join(json_lines))
                    msg = format_monitor_mid_message(data, mode)
                    await send_chunks(query, msg)
                    summary = format_buysell_summary(data, mode)
                    await query.message.reply_text(summary, parse_mode="HTML")
                except Exception as _e:
                    await query.message.reply_text(f"Format error: {_e}")
                    logging.exception("Monitor/mid_month format error")
            else:
                await query.message.reply_text(
                    f"{'Monitor' if mode == 'monitor' else 'Mid-month'} "
                    f"mode complete — no summary captured."
                )

        # ── Rebalance: portfolio PDFs ─────────────────────────────────────────
        if mode == "rebalance":
            parquet_ready = await wait_for_parquet(query)
            if not parquet_ready:
                return
            fmt_proc = await asyncio.create_subprocess_exec(
                *FORMAT_PDF_CMD, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            fmt_stdout, fmt_stderr = await fmt_proc.communicate()
            if fmt_proc.returncode == 0:
                for pdf_path in fmt_stdout.decode("utf-8", errors="replace").strip().splitlines():
                    p = Path(pdf_path.strip())
                    if p.exists():
                        with open(p, "rb") as f:
                            await query.message.reply_document(f, filename=p.name)
                    else:
                        await query.message.reply_text(f"PDF not found: {p.name}")
            else:
                err = fmt_stderr.decode("utf-8", errors="replace")[-500:]
                await query.message.reply_text(
                    f"Portfolio PDF failed:\n<pre>{err}</pre>", parse_mode="HTML"
                )

        # ── Market movement PDF — all modes ──────────────────────────────────
        run_date_str = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%d%m%Y")
        await send_pdf(
            query, MKT_PDF_DIR / f"market_movement_report_{run_date_str}.pdf", "Market movement"
        )

    except Exception as e:
        await query.message.reply_text(f"Error: {e}")
        logging.exception("Pipeline error")


# ── /run_regime ───────────────────────────────────────────────────────────────


async def run_regime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    await update.message.reply_text("Starting regime engine...")
    logging.info(f"Regime triggered by user {update.effective_user.id}")

    env = os.environ.copy()
    env["TZ"] = "Asia/Kolkata"

    try:
        process = await asyncio.create_subprocess_exec(
            "python3",
            str(REGIME_SCRIPT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(BASE),
            env=env,
        )

        async def read_stdout():
            async for line_bytes in process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if "STEP 0" in line and "Index Prices" in line:
                    await update.message.reply_text("🔄 Step 0 — checking index prices")
                elif "STEP 1a" in line:
                    await update.message.reply_text("🔄 Step 1a — checking stock prices")
                elif "STEP 1b" in line:
                    await update.message.reply_text(
                        "🔄 Step 1b — liquidity & risk index (4 universes)"
                    )
                elif "STEP 2" in line and "Narrative" in line:
                    await update.message.reply_text("🔄 Step 2 — generating narratives")
                elif "STEP 3a" in line:
                    await update.message.reply_text("🔄 Step 3a — checking HMM index data")
                elif "STEP 3b" in line:
                    await update.message.reply_text("🔄 Step 3b — running HMM forward algo")
                elif "STEP 4" in line and "Combine" in line:
                    await update.message.reply_text("🔄 Step 4 — combining outputs")
                elif "STEP 5b" in line:
                    await update.message.reply_text("🔄 Step 5b — generating regime PDF")
                elif "ALL DONE" in line:
                    await update.message.reply_text("✅ Regime engine complete")
                elif "FATAL ERROR" in line:
                    await update.message.reply_text(f"❌ {line}")

        try:
            await asyncio.wait_for(read_stdout(), timeout=REGIME_TIMEOUT)
        except TimeoutError:
            process.kill()
            await process.wait()
            await update.message.reply_text("Regime engine timed out after 1 hour.")
            return

        await process.wait()

        if process.returncode != 0:
            await update.message.reply_text(
                f"Regime engine failed (exit {process.returncode}). "
                f"Check logs: journalctl -u telegram-pipeline-bot -n 50"
            )
            return

        run_date_str = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")
        await send_pdf(
            update, REGIME_PDF_DIR / f"regime_report_design_{run_date_str}.pdf", "Regime report"
        )

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        logging.exception("Regime error")


# ── /status ───────────────────────────────────────────────────────────────────


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    pipeline_proc = await asyncio.create_subprocess_exec(
        "pgrep",
        "-f",
        "run_pipeline.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    p_out, _ = await pipeline_proc.communicate()

    regime_proc = await asyncio.create_subprocess_exec(
        "pgrep",
        "-f",
        "regime_master.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    r_out, _ = await regime_proc.communicate()

    pipeline_running = bool(p_out.strip())
    regime_running = bool(r_out.strip())

    if not pipeline_running and not regime_running:
        await update.message.reply_text("No pipeline or regime run in progress.")
    else:
        lines = []
        if pipeline_running:
            lines.append("🔄 Pipeline is running.")
        if regime_running:
            lines.append("🔄 Regime engine is running.")
        await update.message.reply_text("\n".join(lines))


# ── Main ──────────────────────────────────────────────────────────────────────


async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("run_pipeline", run_pipeline_cmd))
    app.add_handler(CommandHandler("run_regime", run_regime))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(pipeline_mode_callback, pattern="^pipeline_"))

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)
    loop.add_signal_handler(signal.SIGINT, stop_event.set)

    async with app:
        await app.start()
        await app.updater.start_polling()
        logging.info("Bot started.")
        await stop_event.wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
