"""
StockSense India — Data Fetcher
Pulls price data, global indices, FII/DII, news from free sources.
"""

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
    NEWS_MAX_AGE_HOURS, SENTIMENT_POSITIVE, SENTIMENT_NEGATIVE
)

logger = logging.getLogger("stocksense.data")

# ── NSE Headers (required to avoid 403) ──────────────────────────────────────
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


# ── Price Data ────────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV data from Yahoo Finance.
    ticker: e.g. 'HDFCBANK.NS' or 'RELIANCE.BO'
    Returns DataFrame with columns: Open, High, Low, Close, Volume
    """
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            logger.warning(f"No data for {ticker}")
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        logger.error(f"fetch_ohlcv({ticker}): {e}")
        return pd.DataFrame()


def fetch_current_price(ticker: str) -> dict:
    """
    Fetch latest price info for a ticker.
    Returns dict: {price, prev_close, change_pct, volume, market_cap}
    """
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        return {
            "ticker":      ticker,
            "price":       info.get("currentPrice") or info.get("regularMarketPrice", 0),
            "prev_close":  info.get("previousClose", 0),
            "change_pct":  info.get("regularMarketChangePercent", 0),
            "volume":      info.get("volume") or info.get("regularMarketVolume", 0),
            "avg_volume":  info.get("averageVolume", 0),
            "market_cap":  info.get("marketCap", 0),
            "pe_ratio":    info.get("trailingPE", None),
            "52w_high":    info.get("fiftyTwoWeekHigh", 0),
            "52w_low":     info.get("fiftyTwoWeekLow", 0),
            "name":        info.get("longName") or info.get("shortName", ticker),
            "sector":      info.get("sector", "Unknown"),
        }
    except Exception as e:
        logger.error(f"fetch_current_price({ticker}): {e}")
        return {}


def fetch_bulk_prices(tickers: list) -> dict:
    """
    Fetch prices for multiple tickers efficiently using yf.download.
    Returns dict of {ticker: latest_close}
    """
    try:
        data = yf.download(tickers, period="5d", interval="1d",
                           progress=False, auto_adjust=True, group_by="ticker")
        result = {}
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    result[ticker] = float(data["Close"].iloc[-1])
                else:
                    result[ticker] = float(data[ticker]["Close"].iloc[-1])
            except Exception:
                result[ticker] = None
        return result
    except Exception as e:
        logger.error(f"fetch_bulk_prices: {e}")
        return {}


# ── Global Market Data ────────────────────────────────────────────────────────

def fetch_global_context() -> dict:
    """
    Fetch overnight global market data:
    - S&P 500, Nasdaq, Dow Jones
    - Gift Nifty (SGX Nifty proxy via ^NSEI futures)
    - Crude oil (CL=F)
    - USD/INR (USDINR=X)
    Returns structured dict for morning briefing.
    """
    indices = {
        "sp500":   "^GSPC",
        "nasdaq":  "^IXIC",
        "dow":     "^DJI",
        "nifty":   "^NSEI",
        "crude":   "CL=F",
        "usdinr":  "USDINR=X",
        "vix":     "^VIX",
    }
    result = {}
    try:
        tickers = list(indices.values())
        data = yf.download(tickers, period="2d", interval="1d",
                           progress=False, auto_adjust=True, group_by="ticker")
        for name, sym in indices.items():
            try:
                closes = data[sym]["Close"].dropna()
                if len(closes) >= 2:
                    prev  = float(closes.iloc[-2])
                    last  = float(closes.iloc[-1])
                    chg   = ((last - prev) / prev) * 100
                    result[name] = {
                        "value":      round(last, 2),
                        "change_pct": round(chg, 2),
                        "direction":  "up" if chg >= 0 else "down",
                    }
            except Exception:
                result[name] = {"value": 0, "change_pct": 0, "direction": "flat"}
    except Exception as e:
        logger.error(f"fetch_global_context: {e}")
    return result


# ── FII / DII Data (NSE) ──────────────────────────────────────────────────────

def fetch_fii_dii() -> dict:
    """
    Scrape FII/DII cash market data from NSE.
    Returns: {fii_net_cr, dii_net_cr, date}
    """
    url = "https://www.nseindia.com/api/fiidiiTradeReact"
    try:
        session = requests.Session()
        # First hit the homepage to get cookies
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        time.sleep(1)
        resp = session.get(url, headers=NSE_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # NSE returns latest day first
            latest = data[0] if data else {}
            return {
                "fii_net_cr": latest.get("fiiNet", 0),
                "dii_net_cr": latest.get("diiNet", 0),
                "date":       latest.get("date", ""),
                "fii_buy_cr": latest.get("fiiBuy", 0),
                "fii_sell_cr":latest.get("fiiSell", 0),
            }
    except Exception as e:
        logger.error(f"fetch_fii_dii: {e}")
    return {"fii_net_cr": 0, "dii_net_cr": 0, "date": ""}


# ── News Sentiment ────────────────────────────────────────────────────────────

def fetch_news_sentiment(symbol: str) -> dict:
    """
    Fetch Google News RSS for a stock symbol and compute sentiment.
    symbol: e.g. 'HDFCBANK' (without .NS)
    Returns: {score, label, headline_count, headlines}
    """
    clean_symbol = symbol.replace(".NS", "").replace(".BO", "")
    url = GNEWS_RSS.format(symbol=clean_symbol)
    headlines = []
    scores    = []
    cutoff    = datetime.now(IST) - timedelta(hours=NEWS_MAX_AGE_HOURS)

    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            pub   = item.findtext("pubDate", "")
            # Basic time filter — skip very old news
            headlines.append(title)
            blob  = TextBlob(title)
            scores.append(blob.sentiment.polarity)
    except Exception as e:
        logger.warning(f"fetch_news_sentiment({clean_symbol}): {e}")

    if not scores:
        return {"score": 0.0, "label": "neutral", "count": 0, "headlines": []}

    avg_score = sum(scores) / len(scores)
    label = (
        "positive" if avg_score > SENTIMENT_POSITIVE else
        "negative" if avg_score < SENTIMENT_NEGATIVE else
        "neutral"
    )
    return {
        "score":     round(avg_score, 4),
        "label":     label,
        "count":     len(scores),
        "headlines": headlines[:5],  # top 5 for display
    }


# ── Delivery % from NSE ───────────────────────────────────────────────────────

def fetch_nse_delivery_pct(symbol: str) -> float:
    """
    Fetch delivery percentage for a stock from NSE.
    High delivery % = genuine buying, not speculative.
    """
    clean = symbol.replace(".NS", "").replace(".BO", "")
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=8)
        time.sleep(0.5)
        url  = NSE_QUOTE_URL + clean
        resp = session.get(url, headers=NSE_HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            return float(data.get("deliveryToTradedQuantity", 0))
    except Exception as e:
        logger.warning(f"fetch_nse_delivery_pct({clean}): {e}")
    return 0.0


# ── Screening: filter universe before deep analysis ───────────────────────────

def screen_universe() -> list:
    """
    Quick filter on the full STOCK_UNIVERSE.
    Returns list of tickers that pass basic liquidity + market cap checks.
    Uses yf.download in bulk for speed.
    """
    from config.settings import MIN_MARKET_CAP_CR, MIN_AVG_VOLUME
    passing = []
    # Batch fetch info — do in groups of 20 to avoid timeouts
    batch_size = 20
    for i in range(0, len(STOCK_UNIVERSE), batch_size):
        batch = STOCK_UNIVERSE[i:i+batch_size]
        for ticker in batch:
            try:
                info = yf.Ticker(ticker).fast_info
                market_cap_cr = (info.market_cap or 0) / 1e7  # convert to crores
                avg_vol       = info.three_month_average_volume or 0
                if market_cap_cr >= MIN_MARKET_CAP_CR and avg_vol >= MIN_AVG_VOLUME:
                    passing.append(ticker)
            except Exception:
                continue
        time.sleep(0.3)  # be polite to Yahoo
    logger.info(f"Universe screened: {len(passing)}/{len(STOCK_UNIVERSE)} passed filters")
    return passing
