"""
StockSense India — Main Entry Point
Run this to start both the API server and the scheduler together.
"""

import threading
import logging
import uvicorn

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("stocksense.main")


def run_api():
    """Start FastAPI on port 8000."""
    uvicorn.run(
        "api.main:app",
        host    = "0.0.0.0",
        port = int(os.environ.get("PORT", 8000))
        reload  = False,
        log_level = "info",
    )


def run_scheduler():
    """Start the APScheduler in a separate thread."""
    from scheduler.jobs import start_scheduler
    start_scheduler()


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════╗
║   StockSense India v1.0                  ║
║   AI-Powered NSE/BSE Swing Trade Engine  ║
╚══════════════════════════════════════════╝
    """)

    # Run API in a background thread
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    logger.info("API server started on http://0.0.0.0:8000")

    # Run scheduler in main thread (blocking)
    run_scheduler()
