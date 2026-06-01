"""
StockSense India — Intraday Monitor
Watches active picks during market hours.
Triggers alerts when targets or stop-losses are hit.
"""

import logging
import sqlite3
import yfinance as yf
from config.settings import DB_PATH, DEFAULT_STRATEGY_PROFILE
from engine.recommender import get_todays_picks, update_pick_status
from utils.alerts import send_alert

logger = logging.getLogger("stocksense.monitor")


def _download_intraday_bars(tickers: list[str]):
    return yf.download(
        tickers,
        period="1d",
        interval="5m",
        progress=False,
        auto_adjust=True,
        group_by="ticker",
    )


def _quote_symbol(pick: dict) -> str:
    suffix = ".BO" if str(pick.get("exchange", "NSE")).upper() == "BSE" else ".NS"
    return f"{pick['ticker']}{suffix}"


def _ticker_bars(data, tickers: list[str], ticker_ns: str):
    try:
        if len(tickers) == 1:
            bars = data[["Open", "High", "Low", "Close"]].copy()
        else:
            bars = data[ticker_ns][["Open", "High", "Low", "Close"]].copy()
        return bars.dropna()
    except Exception:
        return None


def _buy_entry_hit(low: float, high: float, entry_low: float, entry_high: float) -> bool:
    return low <= entry_high and high >= entry_low


def _buy_result_pct(entry: float, level: float) -> float:
    return round(((level - entry) / entry) * 100, 2) if entry > 0 else 0.0


def _sell_result_pct(entry: float, level: float) -> float:
    return round(((entry - level) / entry) * 100, 2) if entry > 0 else 0.0


def _mark_entry_triggered(pick: dict, when_label: str):
    update_pick_status(pick["id"], "open", None)
    send_alert(
        alert_type="entry_triggered",
        ticker=pick["ticker"],
        title=f"{pick['name']} — Entry Triggered",
        message=(
            f"{pick['ticker']} entered the planned zone ₹{pick['entry_low']:.1f}-₹{pick['entry_high']:.1f}. "
            f"Track is now active for target ₹{pick['target_price']:.1f} and stop ₹{pick['stoploss_price']:.1f}. "
            f"Observed {when_label}."
        ),
        priority="medium",
    )


def _mark_target_hit(pick: dict, level: float):
    result_pct = _buy_result_pct(pick["entry_price"], level) if pick["direction"] == "buy" else _sell_result_pct(pick["entry_price"], level)
    update_pick_status(pick["id"], "target_hit", result_pct)
    send_alert(
        alert_type="target_hit",
        ticker=pick["ticker"],
        title=f"{pick['name']} — Target Touched",
        message=(
            f"{pick['ticker']} touched the target zone around ₹{level:.1f}. "
            f"Theoretical swing outcome logged at {result_pct:+.1f}%."
        ),
        priority="high",
    )


def _mark_stoploss_hit(pick: dict, level: float, ambiguous: bool = False):
    result_pct = _buy_result_pct(pick["entry_price"], level) if pick["direction"] == "buy" else _sell_result_pct(pick["entry_price"], level)
    update_pick_status(pick["id"], "stoploss_hit", result_pct)
    message = (
        f"{pick['ticker']} breached the protect level around ₹{level:.1f}. "
        f"Theoretical swing outcome logged at {result_pct:+.1f}%."
    )
    if ambiguous:
        message += " Target and stop were both touched inside the same bar, so the conservative stop outcome was recorded."
    send_alert(
        alert_type="stoploss",
        ticker=pick["ticker"],
        title=f"{pick['name']} — Stop-loss Hit",
        message=message,
        priority="critical",
    )


def _mark_missed_move(pick: dict, level: float):
    update_pick_status(pick["id"], "missed_move", None)
    send_alert(
        alert_type="missed_move",
        ticker=pick["ticker"],
        title=f"{pick['name']} — Missed Move",
        message=(
            f"{pick['ticker']} touched target-like levels near ₹{level:.1f} without ever triggering the planned entry zone "
            f"₹{pick['entry_low']:.1f}-₹{pick['entry_high']:.1f}. Logged as missed move, not a win."
        ),
        priority="medium",
    )


def _process_buy_pick(pick: dict, bars):
    status = pick.get("status") or "pending"
    activated = status == "open"
    target = float(pick["target_price"])
    stoploss = float(pick["stoploss_price"])
    entry_low = float(pick.get("entry_low") or pick["entry_price"])
    entry_high = float(pick.get("entry_high") or pick["entry_price"])

    for idx, bar in bars.iterrows():
        high = float(bar["High"])
        low = float(bar["Low"])
        close = float(bar["Close"])
        when_label = idx.strftime("%H:%M IST") if hasattr(idx, "strftime") else "intraday bar"

        if not activated:
            if high >= target and low > entry_high:
                _mark_missed_move(pick, target)
                return
            if _buy_entry_hit(low, high, entry_low, entry_high):
                _mark_entry_triggered(pick, when_label)
                activated = True

        if activated:
            if low <= stoploss and high >= target:
                _mark_stoploss_hit(pick, stoploss, ambiguous=True)
                return
            if high >= target:
                _mark_target_hit(pick, target)
                return
            if low <= stoploss:
                _mark_stoploss_hit(pick, stoploss)
                return


def _process_sell_pick(pick: dict, bars):
    status = pick.get("status") or "pending"
    if status == "pending":
        update_pick_status(pick["id"], "open", None)
    target = float(pick["target_price"])
    stoploss = float(pick["stoploss_price"])

    for _, bar in bars.iterrows():
        high = float(bar["High"])
        low = float(bar["Low"])
        if high >= stoploss and low <= target:
            _mark_stoploss_hit(pick, stoploss, ambiguous=True)
            return
        if low <= target:
            _mark_target_hit(pick, target)
            return
        if high >= stoploss:
            _mark_stoploss_hit(pick, stoploss)
            return


def check_intraday_prices():
    """
    Called every 5 minutes during market hours.
    Fetches current prices for all open picks and checks thresholds.
    """
    picks = get_todays_picks(strategy=DEFAULT_STRATEGY_PROFILE)
    open_picks = [p for p in picks if p.get("status") in {"pending", "open"}]

    if not open_picks:
        logger.info("No pending/open picks to monitor")
        return

    tickers = [_quote_symbol(p) for p in open_picks]

    try:
        data = _download_intraday_bars(tickers)
    except Exception as e:
        logger.error(f"Intraday price fetch failed: {e}")
        return

    for pick in open_picks:
        ticker_ns = _quote_symbol(pick)
        bars = _ticker_bars(data, tickers, ticker_ns)
        if bars is None or bars.empty:
            continue

        if pick["direction"] == "buy":
            _process_buy_pick(pick, bars)
        elif pick["direction"] == "sell":
            _process_sell_pick(pick, bars)

    logger.info(f"Intraday check complete for {len(open_picks)} picks")


def run_eod_summary():
    """
    Run at 3:45 PM. Summarise how today's picks performed.
    Expire any picks still open after 3 sessions.
    """
    picks = get_todays_picks(strategy=DEFAULT_STRATEGY_PROFILE)
    total     = len(picks)
    hits      = [p for p in picks if p.get("status") == "target_hit"]
    stops     = [p for p in picks if p.get("status") == "stoploss_hit"]
    pending = [p for p in picks if p.get("status") == "pending"]
    still_open = [p for p in picks if p.get("status") == "open"]
    missed = [p for p in picks if p.get("status") == "missed_move"]

    summary_lines = [
        f"Today's StockSense recap: {total} picks",
        f"✅ {len(hits)} target(s) hit" if hits else "",
        f"🚨 {len(stops)} stop-loss(es) triggered" if stops else "",
        f"🎯 {len(missed)} missed move(s) logged" if missed else "",
        f"🕒 {len(pending)} pick(s) never triggered entry" if pending else "",
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
            WHERE status IN ('pending', 'open')
            AND date <= date('now', ?)
        """, (f"-{HOLD_SESSIONS_MAX} days",))
        conn.commit()
    logger.info("Expired old open picks")
