"""
StockSense India — Intraday Monitor
Watches active picks during market hours.
Triggers alerts when targets or stop-losses are hit.
"""

import logging
import sqlite3
from datetime import datetime
import yfinance as yf
from config.settings import IST, DB_PATH, INTRADAY_ALERT_PCT
from engine.recommender import get_todays_picks, update_pick_status
from utils.alerts import send_alert

logger = logging.getLogger("stocksense.monitor")


def check_intraday_prices():
    """
    Called every 5 minutes during market hours.
    Fetches current prices for all open picks and checks thresholds.
    """
    picks = get_todays_picks()
    open_picks = [p for p in picks if p.get("status") == "open"]

    if not open_picks:
        logger.info("No open picks to monitor")
        return

    tickers = [p["ticker"] + ".NS" for p in open_picks]

    try:
        data = yf.download(tickers, period="1d", interval="5m",
                           progress=False, auto_adjust=True, group_by="ticker")
    except Exception as e:
        logger.error(f"Intraday price fetch failed: {e}")
        return

    for pick in open_picks:
        ticker_ns = pick["ticker"] + ".NS"
        try:
            if len(tickers) == 1:
                current = float(data["Close"].iloc[-1])
            else:
                current = float(data[ticker_ns]["Close"].iloc[-1])
        except Exception:
            continue

        entry     = pick["entry_price"]
        target    = pick["target_price"]
        stoploss  = pick["stoploss_price"]
        direction = pick["direction"]
        name      = pick["name"]
        pick_id   = pick["id"]

        if direction == "buy":
            move_pct = (current - entry) / entry * 100

            # Target hit
            if current >= target:
                result_pct = (current - entry) / entry * 100
                update_pick_status(pick_id, "target_hit", result_pct)
                send_alert(
                    alert_type = "target_hit",
                    ticker     = pick["ticker"],
                    title      = f"{name} — Target Reached!",
                    message    = f"{pick['ticker']} hit ₹{current:.1f} — target ₹{target:.1f} reached. "
                                 f"Consider booking profits. Gain: +{result_pct:.1f}%",
                    priority   = "high",
                )
                logger.info(f"TARGET HIT: {pick['ticker']} at ₹{current:.1f} (+{result_pct:.1f}%)")

            # Stop-loss hit
            elif current <= stoploss:
                result_pct = (current - entry) / entry * 100
                update_pick_status(pick_id, "stoploss_hit", result_pct)
                send_alert(
                    alert_type = "stoploss",
                    ticker     = pick["ticker"],
                    title      = f"⚠️ Stop-loss — {name}",
                    message    = f"{pick['ticker']} at ₹{current:.1f} — stop-loss ₹{stoploss:.1f} breached. "
                                 f"Exit now to protect capital. Loss: {result_pct:.1f}%",
                    priority   = "critical",
                )
                logger.warning(f"STOPLOSS HIT: {pick['ticker']} at ₹{current:.1f} ({result_pct:.1f}%)")

            # Significant intraday move alert (>2%)
            elif abs(move_pct) >= INTRADAY_ALERT_PCT:
                send_alert(
                    alert_type = "intraday_move",
                    ticker     = pick["ticker"],
                    title      = f"{name} moved {move_pct:+.1f}% today",
                    message    = f"{pick['ticker']} at ₹{current:.1f} ({move_pct:+.1f}% from entry). "
                                 f"Target: ₹{target:.1f} | Stop: ₹{stoploss:.1f}",
                    priority   = "medium",
                )

        elif direction == "sell":
            # For sell picks — monitor portfolio holdings
            move_pct = (current - entry) / entry * 100

            if current >= stoploss:  # for sell, stoploss is above entry
                send_alert(
                    alert_type = "stoploss",
                    ticker     = pick["ticker"],
                    title      = f"⚠️ {name} — Exit Alert",
                    message    = f"{pick['ticker']} at ₹{current:.1f} — consider exiting now "
                                 f"as it's approaching the protect level ₹{stoploss:.1f}",
                    priority   = "critical",
                )

    logger.info(f"Intraday check complete for {len(open_picks)} picks")


def run_eod_summary():
    """
    Run at 3:45 PM. Summarise how today's picks performed.
    Expire any picks still open after 3 sessions.
    """
    picks = get_todays_picks()
    total     = len(picks)
    hits      = [p for p in picks if p.get("status") == "target_hit"]
    stops     = [p for p in picks if p.get("status") == "stoploss_hit"]
    still_open = [p for p in picks if p.get("status") == "open"]

    summary_lines = [
        f"Today's StockSense recap: {total} picks",
        f"✅ {len(hits)} target(s) hit" if hits else "",
        f"🚨 {len(stops)} stop-loss(es) triggered" if stops else "",
        f"⏳ {len(still_open)} position(s) still open — carry forward" if still_open else "",
    ]
    message = " | ".join([l for l in summary_lines if l])

    if hits:
        returns = [p["actual_result_pct"] for p in hits if p.get("actual_result_pct")]
        avg_ret = sum(returns) / len(returns) if returns else 0
        message += f" | Avg gain on hits: +{avg_ret:.1f}%"

    send_alert(
        alert_type = "eod_summary",
        ticker     = "MARKET",
        title      = "📊 End-of-Day Summary",
        message    = message,
        priority   = "medium",
    )
    logger.info(f"EOD summary sent: {message}")

    # Mark old open picks as expired (older than 3 sessions)
    _expire_old_picks()


def _expire_old_picks():
    """Auto-expire open picks older than HOLD_SESSIONS_MAX trading days."""
    from config.settings import HOLD_SESSIONS_MAX
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE picks SET status='expired'
            WHERE status='open'
            AND date <= date('now', ?)
        """, (f"-{HOLD_SESSIONS_MAX} days",))
        conn.commit()
    logger.info("Expired old open picks")
