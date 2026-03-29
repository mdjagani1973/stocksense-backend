"""
StockSense India — FastAPI Backend
REST API consumed by the mobile app (or served as PWA backend).
"""

import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from config.settings import IST, DB_PATH
from engine.recommender import (
    init_db, get_todays_picks, get_pick_history, update_pick_status
)
from utils.alerts import get_recent_alerts
from data.fetcher import fetch_global_context, fetch_fii_dii, fetch_current_price

import sqlite3

# ── App Setup ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("stocksense.api")

app = FastAPI(
    title       = "StockSense India API",
    description = "AI-powered swing trade recommendation engine for NSE/BSE",
    version     = "1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],   # Restrict to your domain in production
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)

@app.on_event("startup")
async def startup():
    init_db()
    logger.info("StockSense India API started")


# ── Pydantic Models ───────────────────────────────────────────────────────────

class PortfolioEntry(BaseModel):
    ticker:   str
    name:     str
    exchange: str
    quantity: int
    avg_price: float
    notes:    Optional[str] = ""

class PickStatusUpdate(BaseModel):
    status:         str        # target_hit | stoploss_hit | expired
    result_pct:     Optional[float] = None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status":    "ok",
        "time_ist":  datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "version":   "1.0.0",
    }


# ── Picks ─────────────────────────────────────────────────────────────────────

@app.get("/picks/today")
def get_today_picks(date: str = Query(default=None)):
    """Get today's buy/sell recommendations."""
    picks = get_todays_picks(date)
    buy  = [p for p in picks if p["direction"] == "buy"]
    sell = [p for p in picks if p["direction"] == "sell"]
    return {
        "date":         date or datetime.now(IST).strftime("%Y-%m-%d"),
        "buy_picks":    buy,
        "sell_picks":   sell,
        "total":        len(picks),
        "generated_at": picks[0]["created_at"] if picks else None,
    }


@app.get("/picks/history")
def pick_history(limit: int = Query(default=30, le=100)):
    """Get historical picks for performance tracking."""
    picks = get_pick_history(limit)
    total     = len(picks)
    hits      = [p for p in picks if p.get("status") == "target_hit"]
    stops     = [p for p in picks if p.get("status") == "stoploss_hit"]
    win_rate  = round(len(hits) / total * 100, 1) if total else 0
    avg_gain  = (sum(p["actual_result_pct"] for p in hits if p.get("actual_result_pct")) /
                 len(hits)) if hits else 0
    avg_loss  = (sum(p["actual_result_pct"] for p in stops if p.get("actual_result_pct")) /
                 len(stops)) if stops else 0
    return {
        "picks":        picks,
        "stats": {
            "total":        total,
            "target_hits":  len(hits),
            "stoploss_hits":len(stops),
            "win_rate_pct": win_rate,
            "avg_gain_pct": round(avg_gain, 2),
            "avg_loss_pct": round(avg_loss, 2),
        }
    }


@app.patch("/picks/{pick_id}/status")
def update_status(pick_id: int, update: PickStatusUpdate):
    """Manually update a pick's status (e.g. if you closed the trade early)."""
    valid_statuses = {"target_hit", "stoploss_hit", "expired", "open"}
    if update.status not in valid_statuses:
        raise HTTPException(400, f"Status must be one of {valid_statuses}")
    update_pick_status(pick_id, update.status, update.result_pct)
    return {"ok": True, "pick_id": pick_id, "new_status": update.status}


# ── Global Market Context ─────────────────────────────────────────────────────

@app.get("/market/global")
def global_context():
    """Get global market snapshot — US indices, crude, USD/INR."""
    ctx = fetch_global_context()
    fii = fetch_fii_dii()
    return {"global": ctx, "fii_dii": fii}


@app.get("/market/status")
def market_status():
    """Is the market currently open?"""
    now = datetime.now(IST)
    is_weekday = now.weekday() < 5
    open_time  = now.replace(hour=9, minute=15, second=0)
    close_time = now.replace(hour=15, minute=30, second=0)
    is_open    = is_weekday and open_time <= now <= close_time
    return {
        "is_open":      is_open,
        "current_time": now.strftime("%H:%M IST"),
        "opens_at":     "09:15 IST",
        "closes_at":    "15:30 IST",
        "day":          now.strftime("%A"),
    }


# ── Portfolio ─────────────────────────────────────────────────────────────────

@app.get("/portfolio")
def get_portfolio():
    """Get all portfolio holdings with live P&L."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM portfolio ORDER BY added_at DESC").fetchall()
    holdings = [dict(r) for r in rows]

    # Enrich with current price
    total_cost  = 0
    total_value = 0
    for h in holdings:
        ticker = h["ticker"] + ".NS"
        try:
            info    = fetch_current_price(ticker)
            current = info.get("price", h["avg_price"])
        except Exception:
            current = h["avg_price"]

        cost          = h["avg_price"] * h["quantity"]
        value         = current * h["quantity"]
        h["current_price"] = round(current, 2)
        h["cost_value"]    = round(cost, 2)
        h["current_value"] = round(value, 2)
        h["pnl"]           = round(value - cost, 2)
        h["pnl_pct"]       = round((value - cost) / cost * 100, 2) if cost else 0
        total_cost  += cost
        total_value += value

    return {
        "holdings":      holdings,
        "total_cost":    round(total_cost, 2),
        "total_value":   round(total_value, 2),
        "total_pnl":     round(total_value - total_cost, 2),
        "total_pnl_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0,
    }


@app.post("/portfolio")
def add_holding(entry: PortfolioEntry):
    """Add a new stock holding to portfolio."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """INSERT INTO portfolio (ticker, name, exchange, quantity, avg_price, added_at, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (entry.ticker.upper(), entry.name, entry.exchange,
             entry.quantity, entry.avg_price,
             datetime.now(IST).isoformat(), entry.notes)
        )
        conn.commit()
        new_id = cursor.lastrowid
    return {"ok": True, "id": new_id, "ticker": entry.ticker}


@app.put("/portfolio/{holding_id}")
def update_holding(holding_id: int, entry: PortfolioEntry):
    """Update an existing holding (e.g. after adding more shares)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """UPDATE portfolio SET ticker=?, name=?, exchange=?,
               quantity=?, avg_price=?, notes=? WHERE id=?""",
            (entry.ticker.upper(), entry.name, entry.exchange,
             entry.quantity, entry.avg_price, entry.notes, holding_id)
        )
        conn.commit()
    return {"ok": True, "id": holding_id}


@app.delete("/portfolio/{holding_id}")
def delete_holding(holding_id: int):
    """Remove a holding from portfolio."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM portfolio WHERE id=?", (holding_id,))
        conn.commit()
    return {"ok": True, "deleted_id": holding_id}


# ── Alerts ────────────────────────────────────────────────────────────────────

@app.get("/alerts")
def recent_alerts(limit: int = Query(default=20, le=50)):
    """Get recent alerts for the Alerts Centre screen."""
    return {"alerts": get_recent_alerts(limit)}


# ── Manual Trigger (for testing / on-demand runs) ────────────────────────────

@app.post("/engine/run")
def trigger_engine_run(mode: str = Query(default="eod")):
    """
    Manually trigger the recommendation engine.
    Use for testing or to force a refresh.
    mode: eod | morning | intraday
    """
    from engine.recommender import run_engine
    try:
        picks = run_engine(mode=mode)
        return {
            "ok":          True,
            "picks_count": len(picks),
            "picks":       [p.to_dict() for p in picks],
        }
    except Exception as e:
        raise HTTPException(500, str(e))
