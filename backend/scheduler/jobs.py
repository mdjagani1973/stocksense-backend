"""
StockSense India — Scheduler
All scheduled jobs using APScheduler with IST timezone.
"""

import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from config.settings import IST, SCHEDULE

logger = logging.getLogger("stocksense.scheduler")


def job_preliminary_scan():
    """7:00 PM IST — EOD scan using closing data."""
    logger.info("=== JOB: Preliminary Scan (7:00 PM) ===")
    try:
        from engine.recommender import run_engine
        # Run full engine — results saved to DB as 'preliminary'
        candidates = run_engine(mode="eod")
        logger.info(f"Preliminary scan complete: {len(candidates)} candidates shortlisted")
    except Exception as e:
        logger.error(f"Preliminary scan failed: {e}", exc_info=True)


def job_global_pull():
    """6:00 AM IST — Pull overnight global data for morning briefing."""
    logger.info("=== JOB: Global Data Pull (6:00 AM) ===")
    try:
        from data.fetcher import fetch_global_context, fetch_fii_dii
        from utils.alerts import alert_global_update
        global_ctx = fetch_global_context()
        fii_data   = fetch_fii_dii()
        alert_global_update(global_ctx, fii_data)
        logger.info("Global pull complete and 8:30 AM alert queued")
    except Exception as e:
        logger.error(f"Global pull failed: {e}", exc_info=True)


def job_final_picks():
    """9:00 AM IST — Finalise picks with overnight data and push alert."""
    logger.info("=== JOB: Final Picks (9:00 AM) ===")
    try:
        from engine.recommender import run_engine, get_todays_picks
        from data.fetcher import fetch_global_context, fetch_fii_dii
        from utils.alerts import alert_picks_ready

        # Re-run engine with fresh morning data (incorporates overnight moves)
        picks = run_engine(mode="morning")

        # Build global context summary for the notification
        global_ctx = fetch_global_context()
        nasdaq_chg = global_ctx.get("nasdaq", {}).get("change_pct", 0)
        sp_chg     = global_ctx.get("sp500", {}).get("change_pct", 0)
        global_summary = f"US: Nasdaq {nasdaq_chg:+.1f}%, S&P {sp_chg:+.1f}%"

        alert_picks_ready(picks, global_summary)
        logger.info(f"Final picks ready: {len(picks)} recommendations pushed")
    except Exception as e:
        logger.error(f"Final picks job failed: {e}", exc_info=True)


def job_intraday_scan_1():
    """11:00 AM IST — Mid-morning intraday price check."""
    logger.info("=== JOB: Intraday Scan 1 (11:00 AM) ===")
    try:
        from engine.monitor import check_intraday_prices
        check_intraday_prices()
    except Exception as e:
        logger.error(f"Intraday scan 1 failed: {e}", exc_info=True)


def job_intraday_scan_2():
    """1:30 PM IST — Afternoon intraday price check."""
    logger.info("=== JOB: Intraday Scan 2 (1:30 PM) ===")
    try:
        from engine.monitor import check_intraday_prices
        check_intraday_prices()
    except Exception as e:
        logger.error(f"Intraday scan 2 failed: {e}", exc_info=True)


def job_eod_summary():
    """3:45 PM IST — End of day summary and pick expiry."""
    logger.info("=== JOB: EOD Summary (3:45 PM) ===")
    try:
        from engine.monitor import run_eod_summary
        run_eod_summary()
    except Exception as e:
        logger.error(f"EOD summary failed: {e}", exc_info=True)


def is_trading_day() -> bool:
    """Returns True if today is a weekday (Mon–Fri). Holiday check can be added."""
    return datetime.now(IST).weekday() < 5   # 0=Mon, 4=Fri


def start_scheduler():
    """
    Start the APScheduler with all jobs on IST cron triggers.
    Runs as a blocking process — keep it alive with a process manager (e.g. systemd, PM2).
    """
    from engine.recommender import init_db
    init_db()

    scheduler = BlockingScheduler(timezone=IST)

    # ── Register all jobs ────────────────────────────────────────────────────
    scheduler.add_job(
        job_preliminary_scan,
        CronTrigger(hour=19, minute=0, timezone=IST),
        id="preliminary_scan",
        name="7:00 PM — EOD preliminary scan",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        job_global_pull,
        CronTrigger(hour=6, minute=0, timezone=IST),
        id="global_pull",
        name="6:00 AM — Global data pull",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        job_final_picks,
        CronTrigger(hour=9, minute=0, timezone=IST),
        id="final_picks",
        name="9:00 AM — Final picks + push notification",
        misfire_grace_time=120,
    )
    scheduler.add_job(
        job_intraday_scan_1,
        CronTrigger(hour=11, minute=0, timezone=IST, day_of_week="mon-fri"),
        id="intraday_1",
        name="11:00 AM — Intraday scan 1",
        misfire_grace_time=120,
    )
    scheduler.add_job(
        job_intraday_scan_2,
        CronTrigger(hour=13, minute=30, timezone=IST, day_of_week="mon-fri"),
        id="intraday_2",
        name="1:30 PM — Intraday scan 2",
        misfire_grace_time=120,
    )
    scheduler.add_job(
        job_eod_summary,
        CronTrigger(hour=15, minute=45, timezone=IST, day_of_week="mon-fri"),
        id="eod_summary",
        name="3:45 PM — EOD summary",
        misfire_grace_time=120,
    )

    logger.info("Scheduler started. All jobs registered:")
    for job in scheduler.get_jobs():
        logger.info(f"  [{job.id}] {job.name}")

    print("\n" + "="*55)
    print("  StockSense India — Scheduler Running")
    print("="*55)
    print("  7:00 PM  →  Preliminary EOD scan")
    print("  6:00 AM  →  Global data pull + 8:30 AM alert")
    print("  9:00 AM  →  Final picks + push notification")
    print(" 11:00 AM  →  Intraday price check")
    print("  1:30 PM  →  Afternoon scan")
    print("  3:45 PM  →  EOD summary")
    print("="*55 + "\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user")
        scheduler.shutdown()
