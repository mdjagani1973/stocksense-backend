"""
StockSense India — Screenshot Portfolio Parser
Uses Claude Vision API (claude-sonnet-4-20250514) to extract holdings
from Zerodha Kite app and Console browser screenshots.

Supports:
  - Zerodha Kite mobile app (holdings screen)
  - Zerodha Console browser (holdings page)
  - Multiple screenshots (e.g. scrolled pages)

Returns structured JSON ready to save to portfolio DB.
"""

import os
import re
import json
import base64
import logging
import requests
from typing import Optional

logger = logging.getLogger("stocksense.screenshot")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-sonnet-4-20250514"

# ── Prompt Templates ───────────────────────────────────────────────────────────

KITE_PROMPT = """
You are a financial data extraction assistant. This is a screenshot from
Zerodha Kite mobile app showing a stock holdings portfolio.

Extract ALL stock holdings visible in this image.

For each holding, extract:
1. Stock name (as shown)
2. Ticker/symbol (e.g. HDFCBANK, RELIANCE, INFY)
3. Exchange (NSE or BSE — default to NSE if not shown)
4. Quantity (number of shares)
5. Average buy price (avg cost / avg price per share in ₹)
6. Current price (LTP / last traded price in ₹) — if visible
7. Current P&L (profit or loss in ₹) — if visible
8. P&L percentage — if visible

Return ONLY a valid JSON object in this exact format, nothing else:
{
  "source": "kite",
  "holdings": [
    {
      "name": "HDFC Bank",
      "ticker": "HDFCBANK",
      "exchange": "NSE",
      "quantity": 10,
      "avg_price": 1500.50,
      "current_price": 1618.00,
      "pnl": 1175.00,
      "pnl_pct": 7.83
    }
  ],
  "extraction_notes": "Any notes about unclear or partially visible data"
}

Important rules:
- If a value is not visible or unclear, use null for that field
- avg_price and current_price must be numbers, not strings
- quantity must be an integer
- ticker should be the NSE/BSE symbol without .NS or .BO
- If you see "HDFC Bank Ltd" the ticker is "HDFCBANK"
- Common mappings: Reliance → RELIANCE, Infosys → INFY, TCS → TCS,
  ICICI Bank → ICICIBANK, Axis Bank → AXISBANK, Tata Motors → TATAMOTORS,
  Wipro → WIPRO, HCL Tech → HCLTECH, Sun Pharma → SUNPHARMA
"""

CONSOLE_PROMPT = """
You are a financial data extraction assistant. This is a screenshot from
Zerodha Console (web browser) showing a stock holdings or portfolio page.

Extract ALL stock holdings visible in this image.

For each holding, extract:
1. Stock name (as shown)
2. Ticker/symbol (NSE/BSE symbol)
3. Exchange (NSE or BSE)
4. Quantity (number of shares held)
5. Average buy price (average cost per share in ₹)
6. Current price (current market price in ₹) — if visible
7. Invested value (total cost in ₹) — if visible
8. Current value (current market value in ₹) — if visible
9. P&L in ₹ — if visible
10. P&L percentage — if visible

Return ONLY a valid JSON object in this exact format, nothing else:
{
  "source": "console",
  "holdings": [
    {
      "name": "Reliance Industries",
      "ticker": "RELIANCE",
      "exchange": "NSE",
      "quantity": 12,
      "avg_price": 2411.00,
      "current_price": 2841.00,
      "invested_value": 28932.00,
      "current_value": 34092.00,
      "pnl": 5160.00,
      "pnl_pct": 17.84
    }
  ],
  "extraction_notes": "Any notes about unclear data or partial visibility"
}

Rules:
- Return null for any field not visible
- All prices/values are numbers (₹), not strings
- quantity is always an integer
- Do not include the ₹ symbol in number fields
- If you see a stock listed twice (same ticker), merge into one entry
"""

GENERIC_PROMPT = """
You are a financial data extraction assistant. This screenshot shows
a stock portfolio or holdings list from a trading platform.

Extract ALL visible stock holdings with:
- Stock name and ticker/symbol
- Exchange (NSE/BSE) if shown, default NSE
- Number of shares/quantity
- Average buy price (cost per share in ₹)
- Current price if visible
- P&L if visible

Return ONLY valid JSON:
{
  "source": "other",
  "holdings": [
    {
      "name": "stock name",
      "ticker": "SYMBOL",
      "exchange": "NSE",
      "quantity": 0,
      "avg_price": 0.0,
      "current_price": null,
      "pnl": null,
      "pnl_pct": null
    }
  ],
  "extraction_notes": ""
}
"""


# ── Main Parser ───────────────────────────────────────────────────────────────

def parse_portfolio_screenshot(
    image_data: bytes,
    image_type: str = "image/jpeg",
    source_hint: str = "auto",   # "kite" | "console" | "auto"
) -> dict:
    """
    Send screenshot to Claude Vision API and extract holdings.

    Args:
        image_data:  Raw image bytes (JPEG or PNG)
        image_type:  MIME type — 'image/jpeg' or 'image/png'
        source_hint: Help the parser pick the right prompt

    Returns:
        {
            "success": bool,
            "holdings": [...],
            "source": str,
            "extraction_notes": str,
            "error": str | None
        }
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "success": False,
            "holdings": [],
            "error": "ANTHROPIC_API_KEY not set in .env",
        }

    # Encode image to base64
    b64_image = base64.standard_b64encode(image_data).decode("utf-8")

    # Choose prompt based on source hint
    if source_hint == "kite":
        prompt = KITE_PROMPT
    elif source_hint == "console":
        prompt = CONSOLE_PROMPT
    else:
        # Auto-detect: send a quick detection prompt
        prompt = _build_auto_prompt()

    # Call Claude Vision API
    try:
        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_type,
                                "data": b64_image,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        resp = requests.post(ANTHROPIC_API_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        result = resp.json()

        # Extract the text content
        raw_text = result["content"][0]["text"].strip()
        logger.info(f"Claude Vision response ({len(raw_text)} chars)")

        # Parse JSON from response
        parsed = _extract_json(raw_text)
        if not parsed:
            return {
                "success": False,
                "holdings": [],
                "error": f"Could not parse JSON from response: {raw_text[:200]}",
            }

        holdings = parsed.get("holdings", [])
        # Clean and validate each holding
        holdings = [_clean_holding(h) for h in holdings if h.get("ticker")]
        holdings = [h for h in holdings if h is not None]

        logger.info(f"Extracted {len(holdings)} holdings from screenshot")
        return {
            "success":           True,
            "holdings":          holdings,
            "source":            parsed.get("source", source_hint),
            "extraction_notes":  parsed.get("extraction_notes", ""),
            "raw_count":         len(parsed.get("holdings", [])),
            "error":             None,
        }

    except requests.HTTPError as e:
        logger.error(f"Claude API HTTP error: {e}")
        return {"success": False, "holdings": [], "error": str(e)}
    except Exception as e:
        logger.error(f"Screenshot parse error: {e}", exc_info=True)
        return {"success": False, "holdings": [], "error": str(e)}


def parse_multiple_screenshots(
    images: list[tuple[bytes, str]],   # list of (image_data, mime_type)
    source_hint: str = "auto",
) -> dict:
    """
    Parse multiple screenshots and merge holdings.
    Handles scrolled pages — e.g. Kite shows 10 stocks per screen.

    Returns merged, deduplicated holdings list.
    """
    all_holdings = []
    seen_tickers = set()
    notes        = []

    for i, (img_data, mime_type) in enumerate(images):
        logger.info(f"Parsing screenshot {i+1}/{len(images)}...")
        result = parse_portfolio_screenshot(img_data, mime_type, source_hint)

        if not result["success"]:
            logger.warning(f"Screenshot {i+1} failed: {result.get('error')}")
            notes.append(f"Screenshot {i+1}: {result.get('error', 'parse failed')}")
            continue

        for h in result["holdings"]:
            ticker = h.get("ticker", "").upper()
            if ticker and ticker not in seen_tickers:
                seen_tickers.add(ticker)
                all_holdings.append(h)
            elif ticker in seen_tickers:
                logger.info(f"  Duplicate {ticker} in screenshot {i+1} — skipped")

        if result.get("extraction_notes"):
            notes.append(f"Screenshot {i+1}: {result['extraction_notes']}")

    return {
        "success":          len(all_holdings) > 0,
        "holdings":         all_holdings,
        "total_holdings":   len(all_holdings),
        "screenshots_used": len(images),
        "notes":            " | ".join(notes) if notes else "",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_auto_prompt() -> str:
    """Combined prompt that handles both Kite and Console."""
    return (
        KITE_PROMPT
        + "\n\nIf this looks more like Zerodha Console (browser, table format), "
        + "use 'console' as the source value instead of 'kite'."
    )


def _extract_json(text: str) -> Optional[dict]:
    """Robustly extract JSON from Claude's response."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in markdown code fences
    patterns = [
        r"```json\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
        r"\{.*\}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1) if "```" in pattern else match.group(0))
            except json.JSONDecodeError:
                continue
    return None


def _clean_holding(h: dict) -> Optional[dict]:
    """Validate and clean a single holding dict."""
    try:
        ticker = str(h.get("ticker", "")).upper().strip()
        if not ticker or ticker == "NULL":
            return None

        # Clean numeric fields
        def to_float(v):
            if v is None: return None
            try: return float(str(v).replace(",", "").replace("₹", "").strip())
            except: return None

        def to_int(v):
            if v is None: return None
            try: return int(float(str(v).replace(",", "").strip()))
            except: return None

        avg_price = to_float(h.get("avg_price"))
        quantity  = to_int(h.get("quantity"))

        # Must have at least ticker, quantity, avg_price
        if not avg_price or not quantity or avg_price <= 0 or quantity <= 0:
            logger.warning(f"Skipping {ticker}: missing price or quantity")
            return None

        return {
            "name":          str(h.get("name", ticker)).strip(),
            "ticker":        ticker,
            "exchange":      str(h.get("exchange", "NSE")).upper().strip(),
            "quantity":      quantity,
            "avg_price":     avg_price,
            "current_price": to_float(h.get("current_price")),
            "invested_value":to_float(h.get("invested_value")) or round(avg_price * quantity, 2),
            "current_value": to_float(h.get("current_value")),
            "pnl":           to_float(h.get("pnl")),
            "pnl_pct":       to_float(h.get("pnl_pct")),
        }
    except Exception as e:
        logger.error(f"_clean_holding error: {e}")
        return None
