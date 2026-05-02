"""
StockSense India — FastAPI Backend (Render-compatible)
"""

import os
import sys
import logging
import sqlite3
from datetime import datetime

# Ensure root path is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from config.settings import IST, DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger("stocksense.api")

app = FastAPI(
    title="StockSense India API",
    description="AI-powered swing trade recommendation engine for NSE/BSE",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    from engine.recommender import init_db
    init_db()
    logger.info("StockSense India API started ✓")


# ── Models ────────────────────────────────────────────────────────────────────

class PortfolioEntry(BaseModel):
    ticker: str
    name: str
    exchange: str
    quantity: int
    avg_price: float
    notes: Optional[str] = ""

class PickStatusUpdate(BaseModel):
    status: str
    result_pct: Optional[float] = None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "time_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "version": "1.0.0",
    }


# ── Market ────────────────────────────────────────────────────────────────────

@app.get("/market/status")
def market_status():
    now = datetime.now(IST)
    is_weekday = now.weekday() < 5
    open_time  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    is_open    = is_weekday and open_time <= now <= close_time
    return {
        "is_open": is_open,
        "current_time": now.strftime("%H:%M IST"),
        "opens_at": "09:15 IST",
        "closes_at": "15:30 IST",
        "day": now.strftime("%A"),
    }


@app.get("/market/global")
def global_context():
    try:
        from data.fetcher import fetch_global_context, fetch_fii_dii
        ctx = fetch_global_context()
        fii = fetch_fii_dii()
        return {"global": ctx, "fii_dii": fii}
    except Exception as e:
        logger.error(f"global_context error: {e}")
        return {"global": {}, "fii_dii": {}, "error": str(e)}


# ── Picks ─────────────────────────────────────────────────────────────────────

@app.get("/picks/today")
def get_today_picks(date: str = Query(default=None)):
    from engine.recommender import get_todays_picks
    picks = get_todays_picks(date)
    buy   = [p for p in picks if p["direction"] == "buy"]
    sell  = [p for p in picks if p["direction"] == "sell"]
    return {
        "date": date or datetime.now(IST).strftime("%Y-%m-%d"),
        "buy_picks": buy,
        "sell_picks": sell,
        "total": len(picks),
        "generated_at": picks[0]["created_at"] if picks else None,
    }


@app.get("/picks/history")
def pick_history(limit: int = Query(default=30, le=100)):
    from engine.recommender import get_pick_history
    picks  = get_pick_history(limit)
    total  = len(picks)
    hits   = [p for p in picks if p.get("status") == "target_hit"]
    stops  = [p for p in picks if p.get("status") == "stoploss_hit"]
    win_rate = round(len(hits) / total * 100, 1) if total else 0
    return {
        "picks": picks,
        "stats": {
            "total": total,
            "target_hits": len(hits),
            "stoploss_hits": len(stops),
            "win_rate_pct": win_rate,
        }
    }


@app.patch("/picks/{pick_id}/status")
def update_status(pick_id: int, update: PickStatusUpdate):
    from engine.recommender import update_pick_status
    valid = {"target_hit", "stoploss_hit", "expired", "open"}
    if update.status not in valid:
        raise HTTPException(400, f"Status must be one of {valid}")
    update_pick_status(pick_id, update.status, update.result_pct)
    return {"ok": True, "pick_id": pick_id, "new_status": update.status}


# ── Portfolio ─────────────────────────────────────────────────────────────────

@app.get("/portfolio")
def get_portfolio():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM portfolio ORDER BY added_at DESC"
        ).fetchall()
    holdings    = [dict(r) for r in rows]
    total_cost  = sum(h["avg_price"] * h["quantity"] for h in holdings)
    total_value = total_cost
    return {
        "holdings": holdings,
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_pnl": 0,
        "total_pnl_pct": 0,
    }


@app.post("/portfolio")
def add_holding(entry: PortfolioEntry):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """INSERT INTO portfolio
               (ticker, name, exchange, quantity, avg_price, added_at, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (entry.ticker.upper(), entry.name, entry.exchange,
             entry.quantity, entry.avg_price,
             datetime.now(IST).isoformat(), entry.notes)
        )
        conn.commit()
    return {"ok": True, "id": cursor.lastrowid, "ticker": entry.ticker}


@app.put("/portfolio/{holding_id}")
def update_holding(holding_id: int, entry: PortfolioEntry):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """UPDATE portfolio
               SET ticker=?, name=?, exchange=?, quantity=?, avg_price=?, notes=?
               WHERE id=?""",
            (entry.ticker.upper(), entry.name, entry.exchange,
             entry.quantity, entry.avg_price, entry.notes, holding_id)
        )
        conn.commit()
    return {"ok": True, "id": holding_id}


@app.delete("/portfolio/{holding_id}")
def delete_holding(holding_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM portfolio WHERE id=?", (holding_id,))
        conn.commit()
    return {"ok": True, "deleted_id": holding_id}


# ── Alerts ────────────────────────────────────────────────────────────────────

@app.get("/alerts")
def recent_alerts(limit: int = Query(default=20, le=50)):
    from utils.alerts import get_recent_alerts
    return {"alerts": get_recent_alerts(limit)}


# ── Manual engine trigger ─────────────────────────────────────────────────────

@app.post("/engine/run")
def trigger_engine(mode: str = Query(default="eod")):
    try:
        from engine.recommender import run_engine
        picks = run_engine(mode=mode)
        return {
            "ok": True,
            "picks_count": len(picks),
            "picks": [p.to_dict() for p in picks],
        }
    except Exception as e:
        logger.error(f"Engine run failed: {e}")
        raise HTTPException(500, str(e))
