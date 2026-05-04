"""
StockSense India — UPDATED scheduler/jobs.py
Added 2:00 AM IST overnight scan.
Replace your existing scheduler/jobs.py with this file.
"""

import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from config.settings import IST

logger = logging.getLogger("stocksense.scheduler")


def job_preliminary_scan():
    """7:00 PM IST — EOD scan using closing data."""
    logger.info("=== JOB: Preliminary Scan (7:00 PM) ===")
    try:
        from engine.recommender import run_engine
        candidates = run_engine(mode="eod")
        logger.info(f"Preliminary scan: {len(candidates)} candidates")
    except Exception as e:
        logger.error(f"Preliminary scan failed: {e}", exc_info=True)


def job_early_morning():
    """
    2:00 AM IST — Overnight scan.
    US markets close ~1:30 AM IST. This runs after US close
    to capture overnight moves, earnings releases, and global news.
    Results are stored and used to refine the 9 AM final picks.
    """
    logger.info("=== JOB: Overnight Scan (2:00 AM) ===")
    try:
        from data.fetcher import fetch_global_context, fetch_fii_dii
        from utils.alerts import send_alert

        global_ctx = fetch_global_context()
        fii_data   = fetch_fii_dii()

        # Build overnight summary
        nasdaq = global_ctx.get("nasdaq", {})
        sp500  = global_ctx.get("sp500", {})
        usdinr = global_ctx.get("usdinr", {})
        crude  = global_ctx.get("crude", {})

        nasdaq_chg = nasdaq.get("change_pct", 0)
        sp_chg     = sp500.get("change_pct", 0)
        fii_net    = fii_data.get("fii_net_cr", 0)

        # Determine overall market sentiment
        if nasdaq_chg > 0.5 and sp_chg > 0.5:
            sentiment = "POSITIVE - US markets up strongly. Expect gap-up open."
        elif nasdaq_chg < -0.5 and sp_chg < -0.5:
            sentiment = "NEGATIVE - US markets down. Expect gap-down open."
        else:
            sentiment = "MIXED - US markets flat. Normal open expected."

        msg = (f"US Close: Nasdaq {nasdaq_chg:+.2f}%, S&P {sp_chg:+.2f}%. "
               f"USD/INR: {usdinr.get('value', 0):.2f}. "
               f"Crude: {crude.get('change_pct', 0):+.1f}%. "
               f"{sentiment}")

        logger.info(f"Overnight summary: {msg}")

        # Run a preliminary engine pass with overnight data
        from engine.recommender import run_engine
        candidates = run_engine(mode="overnight")
        logger.info(f"Overnight scan: {len(candidates)} candidates shortlisted for 9 AM")

    except Exception as e:
        logger.error(f"Overnight scan failed: {e}", exc_info=True)


def job_global_pull():
    """6:00 AM IST — Final global data pull before market open."""
    logger.info("=== JOB: Global Data Pull (6:00 AM) ===")
    try:
        from data.fetcher import fetch_global_context, fetch_fii_dii
        from utils.alerts import alert_global_update
        global_ctx = fetch_global_context()
        fii_data   = fetch_fii_dii()
        alert_global_update(global_ctx, fii_data)
        logger.info("Global pull complete")
    except Exception as e:
        logger.error(f"Global pull failed: {e}", exc_info=True)


def job_final_picks():
    """9:00 AM IST — Final picks with all overnight data. Push to app."""
    logger.info("=== JOB: Final Picks (9:00 AM) ===")
    try:
        from engine.recommender import run_engine
        from data.fetcher import fetch_global_context
        from utils.alerts import alert_picks_ready

        picks = run_engine(mode="morning")
        global_ctx = fetch_global_context()
        nasdaq_chg = global_ctx.get("nasdaq", {}).get("change_pct", 0)
        sp_chg     = global_ctx.get("sp500", {}).get("change_pct", 0)
        global_summary = f"US: Nasdaq {nasdaq_chg:+.1f}%, S&P {sp_chg:+.1f}%"

        alert_picks_ready(picks, global_summary)
        logger.info(f"Final picks sent: {len(picks)} recommendations")
    except Exception as e:
        logger.error(f"Final picks failed: {e}", exc_info=True)


def job_intraday_scan_1():
    """11:00 AM IST"""
    logger.info("=== JOB: Intraday Scan 1 (11:00 AM) ===")
    try:
        from engine.monitor import check_intraday_prices
        check_intraday_prices()
    except Exception as e:
        logger.error(f"Intraday scan 1 failed: {e}", exc_info=True)


def job_intraday_scan_2():
    """1:30 PM IST"""
    logger.info("=== JOB: Intraday Scan 2 (1:30 PM) ===")
    try:
        from engine.monitor import check_intraday_prices
        check_intraday_prices()
    except Exception as e:
        logger.error(f"Intraday scan 2 failed: {e}", exc_info=True)


def job_eod_summary():
    """3:45 PM IST — End of day summary."""
    logger.info("=== JOB: EOD Summary (3:45 PM) ===")
    try:
        from engine.monitor import run_eod_summary
        run_eod_summary()
    except Exception as e:
        logger.error(f"EOD summary failed: {e}", exc_info=True)


def start_scheduler():
    from engine.recommender import init_db
    init_db()

    scheduler = BlockingScheduler(timezone=IST)

    scheduler.add_job(job_preliminary_scan, CronTrigger(hour=19, minute=0, timezone=IST),
                      id="preliminary_scan", misfire_grace_time=300)

    # ── NEW: 2 AM overnight scan ──────────────────────────────────────────────
    scheduler.add_job(job_early_morning,    CronTrigger(hour=2,  minute=0, timezone=IST,
                      day_of_week="mon-fri"), id="early_morning", misfire_grace_time=300)

    scheduler.add_job(job_global_pull,      CronTrigger(hour=6,  minute=0, timezone=IST),
                      id="global_pull",      misfire_grace_time=300)
    scheduler.add_job(job_final_picks,      CronTrigger(hour=9,  minute=0, timezone=IST),
                      id="final_picks",      misfire_grace_time=120)
    scheduler.add_job(job_intraday_scan_1,  CronTrigger(hour=11, minute=0, timezone=IST,
                      day_of_week="mon-fri"), id="intraday_1",   misfire_grace_time=120)
    scheduler.add_job(job_intraday_scan_2,  CronTrigger(hour=13, minute=30, timezone=IST,
                      day_of_week="mon-fri"), id="intraday_2",   misfire_grace_time=120)
    scheduler.add_job(job_eod_summary,      CronTrigger(hour=15, minute=45, timezone=IST,
                      day_of_week="mon-fri"), id="eod_summary",  misfire_grace_time=120)

    print("\n" + "="*55)
    print("  StockSense India — Scheduler Running")
    print("="*55)
    print("  7:00 PM  Preliminary EOD scan")
    print("  2:00 AM  Overnight scan (after US markets close)")
    print("  6:00 AM  Global data pull + 8:30 AM alert")
    print("  9:00 AM  Final picks + push notification")
    print(" 11:00 AM  Intraday check")
    print("  1:30 PM  Afternoon scan")
    print("  3:45 PM  EOD summary")
    print("="*55 + "\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
