"""
StockSense India — data/fetcher.py v3.0
FIXED: Robust stooq.com parsing, correct index symbols, hardcoded fallback list.
"""

import io
import time
import logging
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from textblob import TextBlob
import xml.etree.ElementTree as ET
from config.settings import (
    IST, GNEWS_RSS, NSE_QUOTE_URL, STOCK_UNIVERSE,
    NEWS_MAX_AGE_HOURS, SENTIMENT_POSITIVE, SENTIMENT_NEGATIVE,
    MIN_MARKET_CAP_CR, MIN_AVG_VOLUME,
)

logger = logging.getLogger("stocksense.data")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

STOOQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# Hardcoded quality stocks — used when screen_universe() returns too few results
QUALITY_FALLBACK_UNIVERSE = [
    "HDFCBANK.NS", "INFY.NS", "TCS.NS", "RELIANCE.NS", "ICICIBANK.NS",
    "BHARTIARTL.NS", "AXISBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "LT.NS",
    "WIPRO.NS", "HCLTECH.NS", "SUNPHARMA.NS", "TITAN.NS", "TATAMOTORS.NS",
    "MARUTI.NS", "BAJFINANCE.NS", "TECHM.NS", "DRREDDY.NS", "CIPLA.NS",
    "DIVISLAB.NS", "ASIANPAINT.NS", "HINDUNILVR.NS", "ITC.NS", "NTPC.NS",
    "POWERGRID.NS", "COALINDIA.NS", "ONGC.NS", "BPCL.NS", "GRASIM.NS",
]


def fetch_stooq_csv(symbol: str, days: int = 90) -> pd.DataFrame:
    """Fetch historical data from stooq.com with robust CSV parsing."""
    url = "https://stooq.com/q/d/l/?s=" + symbol + "&i=d"
    try:
        resp = requests.get(url, headers=STOOQ_HEADERS, timeout=12)
        if resp.status_code != 200 or len(resp.text) < 30:
            return pd.DataFrame()

        text = resp.text.strip()
        lines = text.split('\n')

        # Find the CSV header line (contains "Date")
        header_idx = 0
        for i, line in enumerate(lines):
            if 'Date' in line or 'date' in line.lower():
                header_idx = i
                break

        clean_text = '\n'.join(lines[header_idx:])
        df = pd.read_csv(io.StringIO(clean_text), on_bad_lines='skip', engine='python')
        df.columns = [c.strip().title() for c in df.columns]

        if 'Date' not in df.columns or 'Close' not in df.columns:
            return pd.DataFrame()

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date']).set_index('Date').sort_index()

        cutoff = datetime.now() - timedelta(days=days)
        df = df[df.index >= pd.Timestamp(cutoff)]

        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df.dropna(subset=['Close'])

    except Exception as e:
        logger.debug("stooq " + symbol + ": " + str(e))
        return pd.DataFrame()


def fetch_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """OHLCV — stooq primary, yfinance fallback."""
    days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}.get(period, 90)
    clean = ticker.replace(".NS", "").replace(".BO", "").lower()

    df = fetch_stooq_csv(clean + ".ns", days)
    if not df.empty and len(df) >= 10:
        logger.info("stooq OK: " + ticker + " " + str(len(df)) + " rows")
        return df

    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if not df.empty:
            return df
    except Exception as e:
        logger.warning("yfinance fallback " + ticker + ": " + str(e))

    return pd.DataFrame()


def fetch_current_price(ticker: str) -> dict:
    """Current price — stooq primary, yfinance fallback."""
    clean = ticker.replace(".NS", "").replace(".BO", "").lower()

    price, prev_close = None, None
    df = fetch_stooq_csv(clean + ".ns", days=10)
    if not df.empty and 'Close' in df.columns and len(df) >= 1:
        price = float(df['Close'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2]) if len(df) >= 2 else price

    meta = {"name": ticker.replace(".NS", ""), "sector": "Unknown",
            "market_cap": 0, "52w_high": 0, "52w_low": 0, "avg_volume": 0}

    try:
        info = yf.Ticker(ticker).info
        if not price or price <= 0:
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            prev_close = info.get("previousClose", price)
        meta["name"]       = info.get("longName") or info.get("shortName", meta["name"])
        meta["sector"]     = info.get("sector", "Unknown")
        meta["market_cap"] = info.get("marketCap", 0) or 0
        meta["52w_high"]   = info.get("fiftyTwoWeekHigh", 0) or 0
        meta["52w_low"]    = info.get("fiftyTwoWeekLow", 0) or 0
        meta["avg_volume"] = info.get("averageVolume", 0) or 0
    except Exception as e:
        logger.debug("yfinance meta " + ticker + ": " + str(e))

    if not price or price <= 0:
        return {}

    chg = ((price - prev_close) / prev_close * 100) if prev_close and prev_close > 0 else 0
    return {
        "ticker": ticker, "price": price, "prev_close": prev_close or price,
        "change_pct": round(chg, 2), "market_cap": meta["market_cap"],
        "pe_ratio": None, "52w_high": meta["52w_high"], "52w_low": meta["52w_low"],
        "name": meta["name"], "sector": meta["sector"],
        "avg_volume": meta["avg_volume"], "volume": meta["avg_volume"],
    }


def fetch_bulk_prices(tickers: list) -> dict:
    """Bulk price fetch via stooq."""
    result = {}
    for ticker in tickers:
        clean = ticker.replace(".NS", "").replace(".BO", "").lower()
        df = fetch_stooq_csv(clean + ".ns", days=5)
        result[ticker] = float(df['Close'].iloc[-1]) if not df.empty else None
        time.sleep(0.1)
    return result


def fetch_global_context() -> dict:
    """US indices, Nifty, crude, USD/INR."""
    result = {}

    stooq_indices = {
        "sp500":  "^spx",
        "nasdaq": "^ndx",
        "nifty":  "^nse",
        "vix":    "^vix",
    }

    for name, sym in stooq_indices.items():
        df = fetch_stooq_csv(sym, days=5)
        if not df.empty and len(df) >= 2 and 'Close' in df.columns:
            last = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2])
            chg  = ((last - prev) / prev * 100) if prev else 0
            result[name] = {"value": round(last, 2), "change_pct": round(chg, 2),
                            "direction": "up" if chg >= 0 else "down"}

    # Crude via stooq
    df_crude = fetch_stooq_csv("cl.f", days=5)
    if not df_crude.empty and len(df_crude) >= 2:
        last = float(df_crude['Close'].iloc[-1])
        prev = float(df_crude['Close'].iloc[-2])
        chg  = ((last - prev) / prev * 100) if prev else 0
        result["crude"] = {"value": round(last, 2), "change_pct": round(chg, 2),
                           "direction": "up" if chg >= 0 else "down"}

    # USD/INR via open.er-api (free, CORS-enabled, works from any server)
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=6,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            inr = r.json().get("rates", {}).get("INR")
            if inr:
                result["usdinr"] = {"value": round(inr, 2), "change_pct": 0, "direction": "flat"}
    except Exception as e:
        logger.warning("open.er-api: " + str(e))

    # Fallback USD/INR via stooq
    if "usdinr" not in result:
        for sym in ["usd/inr", "usdinr"]:
            df_inr = fetch_stooq_csv(sym, days=5)
            if not df_inr.empty and 'Close' in df_inr.columns:
                val = float(df_inr['Close'].iloc[-1])
                if val < 10:
                    val = round(1 / val, 2)
                result["usdinr"] = {"value": val, "change_pct": 0, "direction": "flat"}
                break

    logger.info("Global context: " + str(list(result.keys())))
    return result


def fetch_fii_dii() -> dict:
    """FII/DII from NSE."""
    url = "https://www.nseindia.com/api/fiidiiTradeReact"
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        time.sleep(1)
        resp = session.get(url, headers=NSE_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            latest = data[0] if data else {}
            return {
                "fii_net_cr":  latest.get("fiiNet", 0),
                "dii_net_cr":  latest.get("diiNet", 0),
                "fii_buy_cr":  latest.get("fiiBuy", 0),
                "fii_sell_cr": latest.get("fiiSell", 0),
                "date":        latest.get("date", ""),
            }
    except Exception as e:
        logger.error("fetch_fii_dii: " + str(e))
    return {"fii_net_cr": 0, "dii_net_cr": 0, "date": ""}


def fetch_news_sentiment(symbol: str) -> dict:
    """Google News RSS sentiment."""
    clean = symbol.replace(".NS", "").replace(".BO", "")
    url   = GNEWS_RSS.format(symbol=clean)
    scores, headlines = [], []
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            if title:
                headlines.append(title)
                scores.append(TextBlob(title).sentiment.polarity)
    except Exception as e:
        logger.debug("news " + clean + ": " + str(e))

    if not scores:
        return {"score": 0.0, "label": "neutral", "count": 0, "headlines": []}

    avg   = sum(scores) / len(scores)
    label = ("positive" if avg > SENTIMENT_POSITIVE else
             "negative" if avg < SENTIMENT_NEGATIVE else "neutral")
    return {"score": round(avg, 4), "label": label,
            "count": len(scores), "headlines": headlines[:5]}


def fetch_nse_delivery_pct(symbol: str) -> float:
    """NSE delivery percentage."""
    clean = symbol.replace(".NS", "").replace(".BO", "")
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=8)
        time.sleep(0.5)
        resp = session.get(NSE_QUOTE_URL + clean, headers=NSE_HEADERS, timeout=8)
        if resp.status_code == 200:
            return float(resp.json().get("deliveryToTradedQuantity", 0))
    except Exception:
        pass
    return 0.0


def screen_universe() -> list:
    """
    Screen stocks via stooq. Falls back to QUALITY_FALLBACK_UNIVERSE
    if fewer than 10 stocks pass — guarantees engine always has stocks.
    """
    passing = []
    for ticker in STOCK_UNIVERSE:
        try:
            clean = ticker.replace(".NS", "").replace(".BO", "").lower()
            df = fetch_stooq_csv(clean + ".ns", days=30)
            if not df.empty and len(df) >= 5 and 'Close' in df.columns:
                if float(df['Close'].iloc[-1]) > 0:
                    passing.append(ticker)
            time.sleep(0.05)
        except Exception:
            continue

    logger.info("Universe screened: " + str(len(passing)) + "/" + str(len(STOCK_UNIVERSE)) + " passed")

    if len(passing) < 10:
        logger.warning(
            "Only " + str(len(passing)) + " stocks screened — "
            "using QUALITY_FALLBACK_UNIVERSE (" + str(len(QUALITY_FALLBACK_UNIVERSE)) + " stocks)"
        )
        return QUALITY_FALLBACK_UNIVERSE

    return passing
