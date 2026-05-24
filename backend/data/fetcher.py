"""
StockSense India — data/fetcher.py v5.0
FIXED: Pre-warms bhavcopy cache at startup, symbol aliases, robust OHLCV.
"""

import io, time, logging, requests
import pandas as pd
from datetime import datetime, timedelta
from textblob import TextBlob
import xml.etree.ElementTree as ET
from config.settings import (
    IST, GNEWS_RSS, SENTIMENT_POSITIVE, SENTIMENT_NEGATIVE,
)

logger = logging.getLogger("stocksense.data")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "*/*"}
NSE_HEADERS = {**HEADERS, "Referer": "https://www.nseindia.com/", "Accept-Language": "en-US,en;q=0.9"}

# NSE bhavcopy symbol aliases (some tickers differ from Yahoo Finance names)
SYMBOL_ALIASES = {
    "TATAMOTORS": "TATAMOTORS",  # confirmed
    "MM":         "M&M",
    "BAJAJ-AUTO": "BAJAJ-AUTO",
    "M&M":        "M&M",
}

SECTOR_MAP = {
    "RELIANCE": "Energy",
    "TCS": "Information Technology",
    "HDFCBANK": "Banking",
    "ICICIBANK": "Banking",
    "AXISBANK": "Banking",
    "KOTAKBANK": "Banking",
    "SBIN": "Banking",
    "WIPRO": "Information Technology",
    "HCLTECH": "Information Technology",
    "SUNPHARMA": "Pharma",
    "TITAN": "Consumer Discretionary",
    "TATAMOTORS": "Auto",
    "MARUTI": "Auto",
    "BAJFINANCE": "Financial Services",
    "TECHM": "Information Technology",
    "DIVISLAB": "Pharma",
    "ASIANPAINT": "Consumer Goods",
    "HINDUNILVR": "Consumer Goods",
    "ITC": "Consumer Goods",
    "COALINDIA": "Energy",
    "EICHERMOT": "Auto",
    "BAJAJFINSV": "Financial Services",
    "ADANIPORTS": "Infrastructure",
    "HEROMOTOCO": "Auto",
    "TATACONSUM": "Consumer Goods",
    "BHARTIARTL": "Telecom",
    "NTPC": "Power",
    "POWERGRID": "Power",
    "LT": "Infrastructure",
    "BRITANNIA": "Consumer Goods",
}

# ── Hardcoded Fundamentals DB ─────────────────────────────────────────────────
FUNDAMENTALS_DB = {
    "RELIANCE":   (50.3, 0.37, 26.0, 11.2), "TCS":        (72.3, 0.01, 18.0, 12.5),
    "HDFCBANK":   (26.0, 0.08, 48.0, 18.0), "INFY":       (14.9, 0.02, 52.0, 12.1),
    "ICICIBANK":  (37.0, 0.12, 46.0, 15.3), "BHARTIARTL": (55.8, 0.45, 22.0, 19.4),
    "AXISBANK":   (38.0, 0.13, 44.0, 14.8), "KOTAKBANK":  (25.7, 0.09, 38.0, 16.2),
    "SBIN":       (57.5, 0.18, 28.0, 13.5), "LT":         (0.0,  0.42, 35.0, 14.1),
    "WIPRO":      (72.9, 0.02, 16.0, 10.3), "HCLTECH":    (60.8, 0.01, 20.0, 11.8),
    "SUNPHARMA":  (54.5, 0.11, 31.0, 17.2), "TITAN":      (52.9, 0.08, 28.0, 22.1),
    "TATAMOTORS": (46.4, 0.41, 22.0, 14.3), "MARUTI":     (58.2, 0.01, 24.0, 18.7),
    "BAJFINANCE": (55.9, 3.80, 28.0, 25.3), "TECHM":      (35.7, 0.04, 25.0, 10.8),
    "DRREDDY":    (26.6, 0.05, 36.0, 13.4), "CIPLA":      (33.5, 0.09, 32.0, 12.7),
    "DIVISLAB":   (51.9, 0.01, 28.0, 14.8), "ASIANPAINT": (52.6, 0.07, 26.0, 10.2),
    "HINDUNILVR": (61.9, 0.01, 24.0, 10.8), "ITC":        (41.0, 0.01, 46.0, 11.4),
    "NTPC":       (51.1, 1.82, 22.0, 12.3), "POWERGRID":  (51.3, 2.10, 18.0, 11.7),
    "COALINDIA":  (63.1, 0.01, 18.0, 10.5), "ONGC":       (58.9, 0.48, 14.0,  9.8),
    "BPCL":       (52.5, 0.62, 16.0,  8.9), "GRASIM":     (43.2, 0.38, 28.0, 14.6),
    "EICHERMOT":  (49.5, 0.01, 26.0, 19.3), "BAJAJFINSV": (55.9, 0.01, 24.0, 18.4),
    "ADANIPORTS": (65.1, 0.58, 16.0, 22.3), "HEROMOTOCO": (36.0, 0.02, 24.0, 11.8),
    "TATACONSUM": (36.0, 0.12, 26.0, 12.4), "HINDALCO":   (34.6, 0.55, 22.0, 10.3),
    "APOLLOHOSP": (29.3, 0.42, 32.0, 16.8), "TATASTEEL":  (33.4, 0.82, 16.0,  8.7),
    "JSWSTEEL":   (44.7, 0.78, 18.0,  9.4), "INDUSINDBK": (38.0, 0.14, 42.0, 13.8),
    "LT":         (37.0, 0.42, 35.0, 14.1), "BRITANNIA":  (50.6, 0.08, 22.0, 12.1),
    "NESTLEIND":  (62.8, 0.01, 18.0, 11.4), "PIDILITIND": (69.3, 0.01, 16.0, 14.2),
}

PREQUALIFIED_STOCKS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","AXISBANK.NS",
    "KOTAKBANK.NS","SBIN.NS","WIPRO.NS","HCLTECH.NS","SUNPHARMA.NS",
    "TITAN.NS","TATAMOTORS.NS","MARUTI.NS","BAJFINANCE.NS","TECHM.NS",
    "DIVISLAB.NS","ASIANPAINT.NS","HINDUNILVR.NS","ITC.NS","COALINDIA.NS",
    "EICHERMOT.NS","BAJAJFINSV.NS","ADANIPORTS.NS","HEROMOTOCO.NS","TATACONSUM.NS",
    "BHARTIARTL.NS","NTPC.NS","POWERGRID.NS","LT.NS","BRITANNIA.NS",
]

_bhavcopy_cache = {}  # date_str -> DataFrame
_cache_warmed   = False


def _safe_float(val, default=0.0):
    """Safely convert pandas scalar or Series to float."""
    try:
        if hasattr(val, 'iloc'): return float(val.iloc[0])
        if hasattr(val, 'item'): return float(val.item())
        return float(val) if val is not None else default
    except Exception:
        return default


def _normalize_symbol(symbol: str) -> str:
    return "".join(ch for ch in str(symbol).upper() if ch.isalnum())


def _select_symbol_rows(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    row = df[df['SYMBOL'] == symbol]
    if not row.empty:
        return row

    normalized_symbol = _normalize_symbol(symbol)
    normalized_matches = df['SYMBOL'].astype(str).map(_normalize_symbol) == normalized_symbol
    return df[normalized_matches]


def _get_nse_session():
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        time.sleep(0.3)
    except Exception:
        pass
    return session


def get_trading_dates(n: int = 30) -> list:
    dates, d = [], datetime.now(IST)
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)
    return dates


def fetch_bhavcopy(date: datetime) -> pd.DataFrame:
    """Fetch NSE bhavcopy for a date. In-memory cached."""
    date_str = date.strftime("%d%m%Y")
    if date_str in _bhavcopy_cache:
        return _bhavcopy_cache[date_str]

    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    try:
        session = _get_nse_session()
        resp = session.get(url, headers=NSE_HEADERS, timeout=15)
        if resp.status_code != 200 or len(resp.text) < 100:
            _bhavcopy_cache[date_str] = pd.DataFrame()
            return pd.DataFrame()

        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip() for c in df.columns]

        if 'SERIES' in df.columns:
            df = df[df['SERIES'].str.strip() == 'EQ']

        col_map = {}
        for c in df.columns:
            cu = c.strip().upper()
            if 'SYMBOL' in cu:                                   col_map[c] = 'SYMBOL'
            elif cu in ('OPEN_PRICE','OPEN'):                    col_map[c] = 'OPEN'
            elif cu in ('HIGH_PRICE','HIGH'):                    col_map[c] = 'HIGH'
            elif cu in ('LOW_PRICE','LOW'):                      col_map[c] = 'LOW'
            elif cu in ('CLOSE_PRICE','CLOSE','LTP','LAST'):     col_map[c] = 'CLOSE'
            elif any(x in cu for x in ('TTL_TRD','TOTTRDQTY','VOLUME','TRADED_QTY')):
                col_map[c] = 'VOLUME'

        df = df.rename(columns=col_map)
        if not all(c in df.columns for c in ['SYMBOL','OPEN','HIGH','LOW','CLOSE']):
            _bhavcopy_cache[date_str] = pd.DataFrame()
            return pd.DataFrame()

        df['SYMBOL'] = df['SYMBOL'].str.strip()
        for col in ['OPEN','HIGH','LOW','CLOSE']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        if 'VOLUME' not in df.columns:
            df['VOLUME'] = 0
        else:
            df['VOLUME'] = pd.to_numeric(df['VOLUME'], errors='coerce').fillna(0)

        df = df.dropna(subset=['CLOSE'])
        df['DATE'] = date.date()
        logger.info(f"Bhavcopy {date.strftime('%d-%b-%Y')}: {len(df)} stocks loaded")
        _bhavcopy_cache[date_str] = df
        return df

    except Exception as e:
        logger.warning(f"Bhavcopy {date_str}: {e}")
        _bhavcopy_cache[date_str] = pd.DataFrame()
        return pd.DataFrame()


def warm_bhavcopy_cache(n_days: int = 30):
    """
    Pre-fetch last n_days of bhavcopy at engine startup.
    This means fetch_ohlcv() reads from cache instantly instead of
    downloading 30 files per stock call.
    """
    global _cache_warmed
    if _cache_warmed:
        return
    logger.info(f"Warming bhavcopy cache for last {n_days} trading days...")
    dates = get_trading_dates(n_days)
    for date in dates:
        fetch_bhavcopy(date)
        time.sleep(0.1)
    _cache_warmed = True
    cached = sum(1 for df in _bhavcopy_cache.values() if not df.empty)
    logger.info(f"Cache warmed: {cached}/{n_days} bhavcopy files loaded")


def fetch_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """Build OHLCV from cached bhavcopy. Instant if cache is warmed."""
    symbol = ticker.replace(".NS","").replace(".BO","").strip().upper()
    symbol = SYMBOL_ALIASES.get(symbol, symbol)

    days  = {"1mo": 22, "3mo": 66, "6mo": 130, "1y": 252}.get(period, 30)
    dates = get_trading_dates(days)
    rows  = []

    for date in dates:
        df = fetch_bhavcopy(date)
        if df.empty:
            continue
        row = _select_symbol_rows(df, symbol)
        if not row.empty:
            r = row.iloc[0]
            try:
                rows.append({
                    'Date':   pd.Timestamp(r['DATE']),
                    'Open':   _safe_float(r['OPEN']),
                    'High':   _safe_float(r['HIGH']),
                    'Low':    _safe_float(r['LOW']),
                    'Close':  _safe_float(r['CLOSE']),
                    'Volume': _safe_float(r.get('VOLUME', 0)),
                })
            except Exception as e:
                logger.debug(f"Row error {symbol}: {e}")
                continue

    if not rows:
        logger.warning(f"No bhavcopy data for {symbol}")
        return pd.DataFrame()

    result = pd.DataFrame(rows).set_index('Date').sort_index()
    logger.info(f"OHLCV {symbol}: {len(result)} rows")
    return result


def fetch_current_price(ticker: str) -> dict:
    """Latest price from most recent bhavcopy."""
    symbol = ticker.replace(".NS","").replace(".BO","").strip().upper()
    symbol = SYMBOL_ALIASES.get(symbol, symbol)

    for date in get_trading_dates(5):
        df = fetch_bhavcopy(date)
        if df.empty:
            continue
        row = _select_symbol_rows(df, symbol)
        if not row.empty:
            r = row.iloc[0]
            close = _safe_float(r['CLOSE'])
            open_ = _safe_float(r['OPEN'])
            chg   = ((close - open_) / open_ * 100) if open_ > 0 else 0
            return {
                "ticker": ticker, "price": close, "prev_close": open_,
                "change_pct": round(chg, 2), "market_cap": 0,
                "pe_ratio": None, "52w_high": 0, "52w_low": 0,
                "name": symbol, "sector": SECTOR_MAP.get(symbol, "Unknown"),
                "avg_volume": _safe_float(r.get('VOLUME', 0)),
                "volume":     _safe_float(r.get('VOLUME', 0)),
            }
    return {}


def fetch_bulk_prices(tickers: list) -> dict:
    result  = {t: None for t in tickers}
    symbols = {SYMBOL_ALIASES.get(t.replace(".NS","").replace(".BO","").upper(),
               t.replace(".NS","").replace(".BO","").upper()): t for t in tickers}
    for date in get_trading_dates(3):
        df = fetch_bhavcopy(date)
        if df.empty:
            continue
        for _, row in df.iterrows():
            sym = str(row['SYMBOL']).strip()
            mapped = symbols.get(sym)
            if not mapped:
                normalized_sym = _normalize_symbol(sym)
                for candidate_symbol, candidate_ticker in symbols.items():
                    if _normalize_symbol(candidate_symbol) == normalized_sym:
                        mapped = candidate_ticker
                        break
            if mapped and result[mapped] is None:
                result[mapped] = _safe_float(row['CLOSE'])
        if all(v is not None for v in result.values()):
            break
    return result


def fetch_global_context() -> dict:
    result = {}
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=8, headers=HEADERS)
        if r.status_code == 200:
            inr = r.json().get("rates", {}).get("INR")
            if inr:
                result["usdinr"] = {"value": round(inr, 2), "change_pct": 0, "direction": "flat"}
    except Exception as e:
        logger.warning(f"USD/INR: {e}")

    try:
        r = requests.get(
            "https://query2.finance.yahoo.com/v6/finance/quote?symbols=%5EGSPC,%5EIXIC",
            headers={**HEADERS, "Origin": "https://finance.yahoo.com", "Referer": "https://finance.yahoo.com/"},
            timeout=8)
        if r.status_code == 200:
            quotes = r.json().get("quoteResponse", {}).get("result", [])
            for q in quotes:
                sym = q.get("symbol", "")
                chg = q.get("regularMarketChangePercent", 0)
                val = q.get("regularMarketPrice", 0)
                if "GSPC" in sym:
                    result["sp500"]  = {"value": val, "change_pct": round(chg,2), "direction": "up" if chg>=0 else "down"}
                elif "IXIC" in sym:
                    result["nasdaq"] = {"value": val, "change_pct": round(chg,2), "direction": "up" if chg>=0 else "down"}
    except Exception as e:
        logger.warning(f"US indices: {e}")

    logger.info(f"Global context: {list(result.keys())}")
    return result


def fetch_fii_dii() -> dict:
    try:
        session = _get_nse_session()
        resp = session.get("https://www.nseindia.com/api/fiidiiTradeReact", headers=NSE_HEADERS, timeout=10)
        if resp.status_code == 200:
            data   = resp.json()
            latest = data[0] if data else {}
            return {"fii_net_cr": latest.get("fiiNet", 0), "dii_net_cr": latest.get("diiNet", 0),
                    "fii_buy_cr": latest.get("fiiBuy", 0), "fii_sell_cr": latest.get("fiiSell", 0),
                    "date": latest.get("date", "")}
    except Exception as e:
        logger.error(f"fetch_fii_dii: {e}")
    return {"fii_net_cr": 0, "dii_net_cr": 0, "date": ""}


def fetch_news_sentiment(symbol: str) -> dict:
    clean = symbol.replace(".NS","").replace(".BO","")
    scores, headlines = [], []
    try:
        resp = requests.get(GNEWS_RSS.format(symbol=clean), timeout=8, headers=HEADERS)
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            if title:
                headlines.append(title)
                scores.append(TextBlob(title).sentiment.polarity)
    except Exception:
        pass
    if not scores:
        return {"score": 0.0, "label": "neutral", "count": 0, "headlines": []}
    avg   = sum(scores) / len(scores)
    label = "positive" if avg > SENTIMENT_POSITIVE else "negative" if avg < SENTIMENT_NEGATIVE else "neutral"
    return {"score": round(avg,4), "label": label, "count": len(scores), "headlines": headlines[:5]}


def fetch_nse_delivery_pct(symbol: str) -> float:
    return 0.0


def screen_universe() -> list:
    """Warm bhavcopy cache then return pre-qualified stocks."""
    warm_bhavcopy_cache(30)
    logger.info(f"Pre-qualified universe: {len(PREQUALIFIED_STOCKS)} stocks")
    return PREQUALIFIED_STOCKS
