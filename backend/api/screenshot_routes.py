"""
StockSense India — Screenshot Upload API Endpoints
Add these routes to api/main.py (or include as a router).
"""

import io
import sqlite3
import logging
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import List

from config.settings import IST, DB_PATH
from utils.screenshot_parser import parse_portfolio_screenshot, parse_multiple_screenshots

logger = logging.getLogger("stocksense.api.screenshot")
router = APIRouter(prefix="/portfolio", tags=["portfolio"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/jpg", "image/webp"}
MAX_FILE_SIZE_MB = 10


@router.post("/upload-screenshot")
async def upload_single_screenshot(
    file: UploadFile = File(...),
    source: str = Form(default="auto"),   # "kite" | "console" | "auto"
    replace_all: bool = Form(default=False),
):
    """
    Upload a single Zerodha Kite or Console screenshot.
    The AI will extract holdings and return them for confirmation.

    - source: 'kite' for Kite mobile app, 'console' for Console browser, 'auto' to detect
    - replace_all: if True, clears existing portfolio before saving
    """
    # Validate file type
    content_type = file.content_type or "image/jpeg"
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {content_type}. Use JPEG or PNG.")

    # Read and size-check
    image_data = await file.read()
    size_mb = len(image_data) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(400, f"File too large ({size_mb:.1f} MB). Max {MAX_FILE_SIZE_MB} MB.")

    logger.info(f"Processing screenshot: {file.filename} ({size_mb:.1f} MB, source={source})")

    # Parse with Claude Vision
    result = parse_portfolio_screenshot(image_data, content_type, source)

    if not result["success"]:
        raise HTTPException(422, f"Could not extract holdings: {result.get('error')}")

    holdings = result["holdings"]
    if not holdings:
        raise HTTPException(422, "No holdings found in screenshot. Please try a clearer image.")

    return {
        "status":           "extracted",
        "holdings_found":   len(holdings),
        "holdings":         holdings,
        "source_detected":  result.get("source", source),
        "notes":            result.get("extraction_notes", ""),
        "message":          f"Found {len(holdings)} holdings. Review and confirm to save.",
    }


@router.post("/upload-screenshots-multi")
async def upload_multiple_screenshots(
    files: List[UploadFile] = File(...),
    source: str = Form(default="auto"),
    replace_all: bool = Form(default=False),
):
    """
    Upload multiple screenshots (e.g. scrolled pages).
    Holdings are merged and deduplicated across all images.
    """
    if len(files) > 10:
        raise HTTPException(400, "Maximum 10 screenshots at once.")

    images = []
    for f in files:
        ct = f.content_type or "image/jpeg"
        if ct not in ALLOWED_TYPES:
            raise HTTPException(400, f"{f.filename}: unsupported type {ct}")
        data = await f.read()
        images.append((data, ct))

    logger.info(f"Processing {len(images)} screenshots (source={source})")
    result = parse_multiple_screenshots(images, source)

    if not result["success"] or not result["holdings"]:
        raise HTTPException(422, "No holdings extracted. Check screenshot quality.")

    return {
        "status":           "extracted",
        "screenshots_used": result["screenshots_used"],
        "holdings_found":   result["total_holdings"],
        "holdings":         result["holdings"],
        "notes":            result.get("notes", ""),
        "message":          f"Found {result['total_holdings']} unique holdings across "
                            f"{result['screenshots_used']} screenshots. Review and confirm.",
    }


@router.post("/confirm-screenshot-holdings")
async def confirm_and_save_holdings(holdings: list, replace_all: bool = False):
    """
    After the user reviews extracted holdings, call this to save them.
    replace_all=True clears portfolio first (full replacement).
    replace_all=False adds/updates only (safe merge).
    """
    if not holdings:
        raise HTTPException(400, "No holdings to save.")

    saved = 0
    skipped = 0
    now = datetime.now(IST).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        if replace_all:
            conn.execute("DELETE FROM portfolio")
            logger.info("Cleared existing portfolio for full replacement")

        for h in holdings:
            ticker = str(h.get("ticker", "")).upper().strip()
            qty    = h.get("quantity")
            price  = h.get("avg_price")

            if not ticker or not qty or not price:
                skipped += 1
                continue

            if not replace_all:
                # Check if ticker already exists — update if yes
                existing = conn.execute(
                    "SELECT id FROM portfolio WHERE ticker=?", (ticker,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE portfolio SET quantity=?, avg_price=?, notes=? WHERE ticker=?",
                        (qty, price, "Updated via screenshot", ticker)
                    )
                    saved += 1
                    continue

            conn.execute(
                """INSERT INTO portfolio (ticker, name, exchange, quantity, avg_price, added_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ticker, h.get("name", ticker), h.get("exchange", "NSE"),
                 qty, price, now, "Imported from Zerodha screenshot")
            )
            saved += 1

        conn.commit()

    logger.info(f"Screenshot import: {saved} saved, {skipped} skipped")
    return {
        "success":  True,
        "saved":    saved,
        "skipped":  skipped,
        "message":  f"Portfolio updated — {saved} holdings saved.",
    }
