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
Phase 3 — Telegram push for the sharpest live options-flow events.

Called by the collector each cycle with the freshly enriched rows. Flags four
kinds of event, ranks them, applies a per-(contract, rule) cooldown so a standing
condition doesn't re-fire every cycle, caps how many go out per cycle, and sends
one concise digest to Telegram.

Thresholds are env-tunable (OF_* below) — calibrate after watching a live day.
Sends to OF_TELEGRAM_CHAT_ID if set, else the shared TELEGRAM_CHAT_ID (same
channel as price alerts). Set OPTIONS_ALERTS=0 to disable.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def _f(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


ENABLED = os.getenv("OPTIONS_ALERTS", "1").lower() not in ("0", "false", "no", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.getenv("OF_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

OI_PCT = _f("OF_OI_PCT", 20)  # |day OI change %| for buildup/unwinding
D5_OI = _f("OF_D5_OI", 100000)  # min |5-min OI change| (units)
D5_VOL = _f("OF_D5_VOL", 300000)  # min 5-min volume (units)
IV_JUMP = _f("OF_IV_JUMP", 5)  # min |IV change| over the window (vol pts)
PX_MOVE = _f("OF_PX_MOVE", 30)  # min |price move %| over the window
COOLDOWN = _f("OF_COOLDOWN_MIN", 20) * 60
MAX_PER_CYCLE = int(_f("OF_MAX_PER_CYCLE", 6))

_EMOJI = {
    "Long Buildup": "🟢",
    "Short Buildup": "🔴",
    "Short Covering": "🟡",
    "Long Unwinding": "🟠",
}


def configured():
    return ENABLED and bool(TG_TOKEN) and bool(TG_CHAT)


def _send(text):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = json.dumps(
            {"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": True}
        ).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:
        print(f"  telegram send failed: {e}")
        return False


def _label(r):
    dte = r.get("dte")
    return (
        f"{r['underlying']} {r['strike']:g} {r['kind']} ({int(dte)}d)"
        if dte is not None
        else f"{r['underlying']} {r['strike']:g} {r['kind']}"
    )


def _candidates(rows):
    """(key, severity, text) tuples for every event this cycle."""
    out = []
    for r in rows:
        ltp = r.get("ltp")
        chg = r.get("chg_pct")
        chg_s = f"{chg:+.1f}%" if chg is not None else "—"
        iv = r.get("iv")
        d5oi, d5vol = r.get("d5_oi"), r.get("d5_vol")
        d5iv, d5px = r.get("d5_iv"), r.get("d5_price_pct")
        oipct, vol, bu = r.get("oi_chg_day_pct"), r.get("volume"), r.get("buildup")

        if (
            oipct is not None
            and abs(oipct) >= OI_PCT
            and d5oi is not None
            and abs(d5oi) >= D5_OI
            and bu in _EMOJI
        ):
            out.append(
                (
                    f"oi:{r['token']}",
                    abs(oipct),
                    f"{_EMOJI[bu]} {_label(r)} — {bu}\n"
                    f"   OI {oipct:+.0f}% day · 5m {d5oi:+,.0f} · "
                    f"₹{ltp:g} ({chg_s}) · IV {iv if iv is not None else '—'}",
                )
            )

        if d5vol is not None and d5vol >= D5_VOL:
            out.append(
                (
                    f"vol:{r['token']}",
                    d5vol / D5_VOL,
                    f"🔊 {_label(r)} — volume surge\n"
                    f"   5m vol {d5vol:+,.0f} · Vol÷OI "
                    f"{r.get('vol_oi', '—')} · ₹{ltp:g} ({chg_s})",
                )
            )

        dl = r.get("delta")
        if d5iv is not None and abs(d5iv) >= IV_JUMP and dl is not None and 0.15 <= abs(dl) <= 0.85:
            out.append(
                (
                    f"iv:{r['token']}",
                    abs(d5iv),
                    f"⚡ {_label(r)} — IV {d5iv:+.1f} in 5m\n"
                    f"   IV {iv if iv is not None else '—'} · ₹{ltp:g} · δ {dl}",
                )
            )

        if d5px is not None and abs(d5px) >= PX_MOVE and vol is not None and vol >= D5_VOL:
            op = f"{oipct:+.0f}%" if oipct is not None else "—"
            out.append(
                (
                    f"px:{r['token']}",
                    abs(d5px),
                    f"🚀 {_label(r)} — {d5px:+.0f}% in 5m\n   ₹{ltp:g} · OI {op} · vol {vol:,.0f}",
                )
            )
    return out


def maybe_push(rows, state):
    """Evaluate rows, respect cooldown, send a digest of the top new events.
    `state` is a dict carried across cycles: {alert_key: last_sent_epoch}."""
    if not configured():
        return 0
    now = time.time()
    fresh = [c for c in _candidates(rows) if now - state.get(c[0], 0) >= COOLDOWN]
    fresh.sort(key=lambda c: -c[1])
    pick = fresh[:MAX_PER_CYCLE]
    if not pick:
        return 0
    for key, _, _ in pick:
        state[key] = now
    header = f"📈 Options flow • {datetime.now(IST):%H:%M IST}"
    _send(header + "\n\n" + "\n".join(t for _, _, t in pick))
    return len(pick)


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv[1:]:
        if not (TG_TOKEN and TG_CHAT):
            print(
                "ERROR: TELEGRAM_BOT_TOKEN and a chat id "
                "(OF_TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID) must be set.",
                file=sys.stderr,
            )
            sys.exit(1)
        ok = _send(f"✅ Options-flow alerts connected • {datetime.now(IST):%d %b %H:%M IST}")
        print(f"{'sent ✓' if ok else 'FAILED'} → chat {TG_CHAT}")
        sys.exit(0 if ok else 1)
    print(
        "usage: python alerts.py --test   (sends one test message to the "
        "configured options-alerts channel)"
    )
