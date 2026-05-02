"""
StockSense India — Main Entry Point (Render-compatible)
"""

import sys
import os
import threading
import logging

# ── Ensure project root is in Python path ─────────────────────────────────────
# This fixes import errors when running on Render
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("stocksense.main")


def run_api():
    """Start FastAPI on the port Render expects (default 10000)."""
    import uvicorn
    port = int(os.environ.get("PORT", 10000))  # Render sets PORT automatically
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )


def run_scheduler():
    """Start the APScheduler (blocking)."""
    try:
        from scheduler.jobs import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.error(f"Scheduler failed to start: {e}")
        # Don't crash the whole app if scheduler fails
        # API will still work for manual triggers


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════╗
║   StockSense India v1.0                  ║
║   Starting on Render...                  ║
╚══════════════════════════════════════════╝
    """)

    # Initialise database first
    try:
        from engine.recommender import init_db
        init_db()
        logger.info("Database initialised successfully")
    except Exception as e:
        logger.error(f"DB init failed: {e}")

    # Run scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("Scheduler thread started")

    # Run API in main thread (blocking — Render needs this)
    logger.info("Starting API server...")
    run_api()
