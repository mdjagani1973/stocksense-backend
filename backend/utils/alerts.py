"""
StockSense India — Alert System
Sends push notifications via Firebase Cloud Messaging (FCM).
Also logs all alerts to the database.
"""

import os
import json
import logging
import sqlite3
import requests
from datetime import datetime
from config.settings import IST, DB_PATH

logger = logging.getLogger("stocksense.alerts")

# ── FCM Config (set via .env) ────────────────────────────────────────────────
FCM_SERVER_KEY  = os.getenv("FCM_SERVER_KEY", "")    # Firebase server key
FCM_DEVICE_TOKEN = os.getenv("FCM_DEVICE_TOKEN", "") # Your phone's FCM token
FCM_URL         = "https://fcm.googleapis.com/fcm/send"

# Priority colours for notification display
PRIORITY_CONFIG = {
    "critical": {"color": "#FF4D6D", "sound": "alarm"},
    "high":     {"color": "#00D68F", "sound": "default"},
    "medium":   {"color": "#FFB347", "sound": "default"},
    "low":      {"color": "#4D9FFF", "sound": "silent"},
}


def send_alert(
    alert_type: str,
    ticker:     str,
    title:      str,
    message:    str,
    priority:   str = "medium",
    data:       dict = None,
) -> bool:
    """
    Send a push notification and log to database.

    alert_type: 'picks_ready' | 'target_hit' | 'stoploss' |
                'intraday_move' | 'eod_summary' | 'global_update'
    priority:   'critical' | 'high' | 'medium' | 'low'
    """
    # Always log first (even if push fails)
    _log_alert(alert_type, ticker, title, message)

    # Send push notification
    if FCM_SERVER_KEY and FCM_DEVICE_TOKEN:
        return _send_fcm(title, message, priority, data or {})
    else:
        logger.warning("FCM not configured — alert logged only. Set FCM_SERVER_KEY and FCM_DEVICE_TOKEN in .env")
        return False


def _send_fcm(title: str, message: str, priority: str, extra_data: dict) -> bool:
    """Send push notification via Firebase Cloud Messaging."""
    cfg = PRIORITY_CONFIG.get(priority, PRIORITY_CONFIG["medium"])

    payload = {
        "to": FCM_DEVICE_TOKEN,
        "priority": "high" if priority in ("critical", "high") else "normal",
        "notification": {
            "title": title,
            "body":  message,
            "sound": cfg["sound"],
            "color": cfg["color"],
            "click_action": "FLUTTER_NOTIFICATION_CLICK",
        },
        "data": {
            "alert_type": priority,
            **extra_data,
        },
    }

    try:
        resp = requests.post(
            FCM_URL,
            headers={
                "Authorization": f"key={FCM_SERVER_KEY}",
                "Content-Type":  "application/json",
            },
            data=json.dumps(payload),
            timeout=10,
        )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("success", 0) == 1:
                logger.info(f"Push sent: {title}")
                return True
            else:
                logger.error(f"FCM error: {result}")
        else:
            logger.error(f"FCM HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"FCM send failed: {e}")
    return False


def _log_alert(alert_type: str, ticker: str, title: str, message: str):
    """Persist alert to SQLite for display in the Alerts Centre screen."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO alerts_log (ticker, alert_type, message, created_at) VALUES (?,?,?,?)",
                (ticker, alert_type, f"{title} | {message}",
                 datetime.now(IST).isoformat())
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Alert log failed: {e}")


def get_recent_alerts(limit: int = 20) -> list[dict]:
    """Retrieve recent alerts for the Alerts Centre screen."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM alerts_log ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_recent_alerts: {e}")
        return []


# ── Pre-built alert messages ───────────────────────────────────────────────────

def alert_picks_ready(picks: list, global_summary: str):
    """Send morning 9 AM alert when picks are ready."""
    buy_picks  = [p for p in picks if p.direction == "buy"]
    sell_picks = [p for p in picks if p.direction == "sell"]

    tickers = ", ".join([p.ticker for p in buy_picks[:3]])
    message = (
        f"{len(buy_picks)} buy + {len(sell_picks)} sell candidates ready. "
        f"Top picks: {tickers}. Market opens in 15 mins. "
        f"{global_summary}"
    )
    send_alert(
        alert_type = "picks_ready",
        ticker     = "MARKET",
        title      = "📊 Today's StockSense Picks Are Ready",
        message    = message,
        priority   = "high",
    )


def alert_global_update(global_ctx: dict, fii_data: dict):
    """Send 8:30 AM global pre-market update."""
    nasdaq = global_ctx.get("nasdaq", {})
    sp500  = global_ctx.get("sp500", {})
    fii    = fii_data.get("fii_net_cr", 0)

    nasdaq_str = f"Nasdaq {nasdaq.get('change_pct', 0):+.2f}%"
    sp_str     = f"S&P {sp500.get('change_pct', 0):+.2f}%"
    fii_str    = f"FII {'buying' if fii > 0 else 'selling'} ₹{abs(fii):,.0f} Cr"

    message = f"{nasdaq_str} | {sp_str} | {fii_str} | Final picks at 9:00 AM"
    send_alert(
        alert_type = "global_update",
        ticker     = "MARKET",
        title      = "🌐 Pre-Market Global Update",
        message    = message,
        priority   = "medium",
    )
