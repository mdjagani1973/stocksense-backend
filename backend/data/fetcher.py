"""
StockSense India — data/fetcher.py
FIXED: Uses stooq.com for OHLCV price data (Yahoo Finance blocks Render server IPs).
Keeps yfinance for fundamental data (P/E, market cap etc) which still works.
"""

import io
import time
import logging
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
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
}


# ── OHLCV via stooq.com (works from Render, no auth needed) ──────────────────

def ticker_to_stooq(ticker: str) -> str:
    """Convert NSE ticker to stooq format. HDFCBANK.NS -> hdfcbank.ns"""
    clean = ticker.replace(".NS", "").replace(".BO", "").lower()
    return clean + ".ns"


def fetch_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV data from stooq.com.
    stooq.com is free, no API key, works from any server.
    """
    stooq_sym = ticker_to_stooq(ticker)
    url = f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d"
    try:
        resp = requests.get(url, headers=STOOQ_HEADERS, timeout=10)
        if resp.status_code != 200 or len(resp.text) < 50:
            logger.warning(f"stooq empty response for {ticker}")
            return _fetch_ohlcv_yfinance(ticker, period, interval)

        df = pd.read_csv(io.StringIO(resp.text), parse_dates=["Date"])
        df = df.rename(columns={"Date":"Date","Open":"Open","High":"High",
                                  "Low":"Low","Close":"Close","Volume":"Volume"})
        df = df.set_index("Date").sort_index()

        # Filter to requested period
        days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}.get(period, 90)
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df.index >= pd.Timestamp(cutoff)]

        if df.empty:
            return _fetch_ohlcv_yfinance(ticker, period, interval)

        logger.info(f"stooq OK: {ticker} — {len(df)} rows")
        return df

    except Exception as e:
        logger.warning(f"stooq failed for {ticker}: {e} — trying yfinance")
        return _fetch_ohlcv_yfinance(ticker, period, interval)


def _fetch_ohlcv_yfinance(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """Fallback: yfinance (may be blocked on some servers)."""
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        return df
    except Exception as e:
        logger.error(f"yfinance also failed for {ticker}: {e}")
        return pd.DataFrame()


def fetch_current_price(ticker: str) -> dict:
    """
    Fetch latest price for a ticker.
    Uses stooq for price, yfinance for metadata (name, sector, market cap).
    """
    stooq_sym = ticker_to_stooq(ticker)
    url = f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d"

    price = None
    prev_close = None

    try:
        resp = requests.get(url, headers=STOOQ_HEADERS, timeout=8)
        if resp.status_code == 200 and len(resp.text) > 50:
            df = pd.read_csv(io.StringIO(resp.text))
            if not df.empty:
                latest = df.iloc[-1]
                price = float(latest.get("Close", 0))
                if len(df) >= 2:
                    prev_close = float(df.iloc[-2].get("Close", price))
                else:
                    prev_close = price
    except Exception as e:
        logger.warning(f"stooq price fetch failed for {ticker}: {e}")

    # Get metadata from yfinance (less frequent, more tolerant of blocking)
    meta = {}
    try:
        info = yf.Ticker(ticker).info
        meta = {
            "name":       info.get("longName") or info.get("shortName", ticker),
            "sector":     info.get("sector", "Unknown"),
            "market_cap": info.get("marketCap", 0),
            "pe_ratio":   info.get("trailingPE", None),
            "52w_high":   info.get("fiftyTwoWeekHigh", 0),
            "52w_low":    info.get("fiftyTwoWeekLow", 0),
            "avg_volume": info.get("averageVolume", 0),
        }
        # If stooq failed, try yfinance price
        if not price:
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            prev_close = info.get("previousClose", price)
    except Exception as e:
        logger.warning(f"yfinance metadata failed for {ticker}: {e}")

    if not price:
        return {}

    change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0

    return {
        "ticker":      ticker,
        "price":       price,
        "prev_close":  prev_close or price,
        "change_pct":  round(change_pct, 2),
        "market_cap":  meta.get("market_cap", 0),
        "pe_ratio":    meta.get("pe_ratio"),
        "52w_high":    meta.get("52w_high", 0),
        "52w_low":     meta.get("52w_low", 0),
        "name":        meta.get("name", ticker.replace(".NS", "")),
        "sector":      meta.get("sector", "Unknown"),
        "avg_volume":  meta.get("avg_volume", 0),
        "volume":      meta.get("avg_volume", 0),
    }


def fetch_bulk_prices(tickers: list) -> dict:
    """Fetch latest close prices for multiple tickers via stooq."""
    result = {}
    for ticker in tickers:
        try:
            stooq_sym = ticker_to_stooq(ticker)
            url = f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d"
            resp = requests.get(url, headers=STOOQ_HEADERS, timeout=6)
            if resp.status_code == 200 and len(resp.text) > 50:
                df = pd.read_csv(io.StringIO(resp.text))
                result[ticker] = float(df.iloc[-1]["Close"]) if not df.empty else None
            else:
                result[ticker] = None
        except Exception:
            result[ticker] = None
        time.sleep(0.1)  # be polite
    return result


# ── Global Market Context ─────────────────────────────────────────────────────

def fetch_global_context() -> dict:
    """
    Fetch US indices and macro data.
    Uses stooq for indices — works reliably from Render.
    """
    indices = {
        "sp500":  "^spx",    # S&P 500 on stooq
        "nasdaq": "^ndx",    # Nasdaq 100
        "nifty":  "^nse",    # Nifty 50
        "vix":    "^vix",    # VIX
    }
    result = {}
    for name, sym in indices.items():
        url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
        try:
            resp = requests.get(url, headers=STOOQ_HEADERS, timeout=8)
            if resp.status_code == 200 and len(resp.text) > 50:
                df = pd.read_csv(io.StringIO(resp.text))
                if len(df) >= 2:
                    last = float(df.iloc[-1]["Close"])
                    prev = float(df.iloc[-2]["Close"])
                    chg  = ((last - prev) / prev * 100) if prev else 0
                    result[name] = {
                        "value":      round(last, 2),
                        "change_pct": round(chg, 2),
                        "direction":  "up" if chg >= 0 else "down",
                    }
        except Exception as e:
            logger.warning(f"stooq global {sym}: {e}")

    # Crude oil and USD/INR via yfinance (usually works for these)
    for name, sym in [("crude", "CL=F"), ("usdinr", "USDINR=X")]:
        try:
            df = yf.download(sym, period="5d", interval="1d",
                             progress=False, auto_adjust=True)
            if len(df) >= 2:
                last = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                chg  = ((last - prev) / prev * 100) if prev else 0
                result[name] = {
                    "value":      round(last, 2),
                    "change_pct": round(chg, 2),
                    "direction":  "up" if chg >= 0 else "down",
                }
        except Exception as e:
            logger.warning(f"yfinance {sym}: {e}")

    return result


# ── FII / DII Data ────────────────────────────────────────────────────────────

def fetch_fii_dii() -> dict:
    """Fetch FII/DII data from NSE."""
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
        logger.error(f"fetch_fii_dii: {e}")
    return {"fii_net_cr": 0, "dii_net_cr": 0, "date": ""}


# ── News Sentiment ────────────────────────────────────────────────────────────

def fetch_news_sentiment(symbol: str) -> dict:
    """Fetch Google News RSS and compute sentiment score."""
    clean = symbol.replace(".NS", "").replace(".BO", "")
    url   = GNEWS_RSS.format(symbol=clean)
    scores, headlines = [], []
    try:
        resp = requests.get(url, timeout=8,
                            headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            if title:
                headlines.append(title)
                scores.append(TextBlob(title).sentiment.polarity)
    except Exception as e:
        logger.warning(f"news sentiment {clean}: {e}")

    if not scores:
        return {"score": 0.0, "label": "neutral", "count": 0, "headlines": []}

    avg = sum(scores) / len(scores)
    label = ("positive" if avg > SENTIMENT_POSITIVE else
             "negative" if avg < SENTIMENT_NEGATIVE else "neutral")
    return {"score": round(avg, 4), "label": label,
            "count": len(scores), "headlines": headlines[:5]}


# ── Delivery % from NSE ───────────────────────────────────────────────────────

def fetch_nse_delivery_pct(symbol: str) -> float:
    """Fetch delivery percentage from NSE."""
    clean = symbol.replace(".NS", "").replace(".BO", "")
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=8)
        time.sleep(0.5)
        resp = session.get(NSE_QUOTE_URL + clean, headers=NSE_HEADERS, timeout=8)
        if resp.status_code == 200:
            return float(resp.json().get("deliveryToTradedQuantity", 0))
    except Exception as e:
        logger.warning(f"delivery_pct {clean}: {e}")
    return 0.0


# ── Universe Screening ────────────────────────────────────────────────────────

def screen_universe() -> list:
    """
    Quick filter on STOCK_UNIVERSE using stooq for price/volume data.
    Returns tickers that pass basic liquidity checks.
    """
    passing = []
    for ticker in STOCK_UNIVERSE:
        try:
            stooq_sym = ticker_to_stooq(ticker)
            url = f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d"
            resp = requests.get(url, headers=STOOQ_HEADERS, timeout=6)
            if resp.status_code != 200 or len(resp.text) < 50:
                continue
            df = pd.read_csv(io.StringIO(resp.text))
            if df.empty or len(df) < 5:
                continue
            # Basic check: has recent data and reasonable volume
            latest_close = float(df.iloc[-1]["Close"])
            avg_vol = float(df["Volume"].tail(20).mean()) if "Volume" in df.columns else 0

            # Accept if volume check passes OR if volume data not available
            if latest_close > 0 and (avg_vol >= MIN_AVG_VOLUME or avg_vol == 0):
                passing.append(ticker)
            time.sleep(0.05)
        except Exception as e:
            logger.debug(f"screen {ticker}: {e}")
            continue

    logger.info(f"Universe screened: {len(passing)}/{len(STOCK_UNIVERSE)} passed")
    return passing
