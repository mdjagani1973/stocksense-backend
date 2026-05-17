"""
StockSense India — data/fetcher.py v4.0
Uses NSE bhavcopy (official EOD data, no IP blocking) + hardcoded fundamentals.
Yahoo Finance and stooq both block Render datacenter IPs — this avoids both.
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

# ── Hardcoded Fundamentals DB ─────────────────────────────────────────────────
# (promoter%, debt_to_equity, institutional%, revenue_growth%)
# Source: NSE quarterly shareholding reports + annual reports
FUNDAMENTALS_DB = {
    "RELIANCE":   (50.3, 0.37, 26.0, 11.2), "TCS":        (72.3, 0.01, 18.0, 12.5),
    "HDFCBANK":   (0.0,  0.08, 48.0, 18.0), "INFY":       (14.9, 0.02, 52.0, 12.1),
    "ICICIBANK":  (0.0,  0.12, 46.0, 15.3), "BHARTIARTL": (55.8, 0.45, 22.0, 19.4),
    "AXISBANK":   (8.2,  0.13, 44.0, 14.8), "KOTAKBANK":  (25.7, 0.09, 38.0, 16.2),
    "SBIN":       (57.5, 0.18, 28.0, 13.5), "LT":         (0.0,  0.42, 35.0, 14.1),
    "WIPRO":      (72.9, 0.02, 16.0, 10.3), "HCLTECH":    (60.8, 0.01, 20.0, 11.8),
    "SUNPHARMA":  (54.5, 0.11, 31.0, 17.2), "TITAN":      (52.9, 0.08, 28.0, 22.1),
    "TATAMOTORS": (46.4, 0.41, 22.0, 14.3), "MARUTI":     (58.2, 0.01, 24.0, 18.7),
    "BAJFINANCE": (55.9, 3.80, 28.0, 25.3), "TECHM":      (35.7, 0.04, 25.0, 10.8),
    "DRREDDY":    (26.6, 0.05, 36.0, 13.4), "CIPLA":      (33.5, 0.09, 32.0, 12.7),
    "DIVISLAB":   (51.9, 0.01, 28.0, 14.8), "ASIANPAINT": (52.6, 0.07, 26.0, 10.2),
    "HINDUNILVR": (61.9, 0.01, 24.0, 10.8), "ITC":        (0.0,  0.01, 46.0, 11.4),
    "NTPC":       (51.1, 1.82, 22.0, 12.3), "POWERGRID":  (51.3, 2.10, 18.0, 11.7),
    "COALINDIA":  (63.1, 0.01, 18.0, 10.5), "ONGC":       (58.9, 0.48, 14.0, 9.8),
    "BPCL":       (52.5, 0.62, 16.0, 8.9),  "GRASIM":     (43.2, 0.38, 28.0, 14.6),
    "EICHERMOT":  (49.5, 0.01, 26.0, 19.3), "BAJAJFINSV": (55.9, 0.01, 24.0, 18.4),
    "ADANIPORTS": (65.1, 0.58, 16.0, 22.3), "HEROMOTOCO": (34.6, 0.02, 24.0, 11.8),
    "TATACONSUM": (34.7, 0.12, 26.0, 12.4), "HINDALCO":   (34.6, 0.55, 22.0, 10.3),
    "APOLLOHOSP": (29.3, 0.42, 32.0, 16.8), "TATASTEEL":  (33.4, 0.82, 16.0, 8.7),
    "JSWSTEEL":   (44.7, 0.78, 18.0, 9.4),  "INDUSINDBK": (16.4, 0.14, 42.0, 13.8),
}

# Pre-qualified stocks that pass fundamental filters (saves API calls)
PREQUALIFIED_STOCKS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "AXISBANK.NS","KOTAKBANK.NS","SBIN.NS","WIPRO.NS","HCLTECH.NS",
    "SUNPHARMA.NS","TITAN.NS","TATAMOTORS.NS","MARUTI.NS","BAJFINANCE.NS",
    "TECHM.NS","DRREDDY.NS","CIPLA.NS","DIVISLAB.NS","ASIANPAINT.NS",
    "HINDUNILVR.NS","ITC.NS","NTPC.NS","POWERGRID.NS","COALINDIA.NS",
    "EICHERMOT.NS","BAJAJFINSV.NS","ADANIPORTS.NS","HEROMOTOCO.NS","TATACONSUM.NS",
]

_bhavcopy_cache = {}  # date_str -> DataFrame

def _get_nse_session():
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        time.sleep(0.5)
    except Exception:
        pass
    return session

def fetch_bhavcopy(date: datetime) -> pd.DataFrame:
    """Fetch NSE EOD bhavcopy for a date. Cached in memory."""
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
            if 'SYMBOL' in cu:                           col_map[c] = 'SYMBOL'
            elif cu in ('OPEN_PRICE','OPEN'):             col_map[c] = 'OPEN'
            elif cu in ('HIGH_PRICE','HIGH'):             col_map[c] = 'HIGH'
            elif cu in ('LOW_PRICE','LOW'):               col_map[c] = 'LOW'
            elif cu in ('CLOSE_PRICE','CLOSE','LTP'):     col_map[c] = 'CLOSE'
            elif any(x in cu for x in ('TTL_TRD','TOTTRDQTY','VOLUME','QTY')):
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

        df = df.dropna(subset=['CLOSE'])
        df['DATE'] = date.date()
        logger.info(f"Bhavcopy {date.strftime('%d-%b-%Y')}: {len(df)} stocks loaded")
        _bhavcopy_cache[date_str] = df
        return df

    except Exception as e:
        logger.warning(f"Bhavcopy {date_str}: {e}")
        _bhavcopy_cache[date_str] = pd.DataFrame()
        return pd.DataFrame()

def get_trading_dates(n: int = 30) -> list:
    """Return last n weekdays."""
    dates, d = [], datetime.now(IST)
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)
    return dates

def _safe_float(val, default=0.0):
    """Safely convert pandas scalar or Series to float."""
    try:
        if hasattr(val, 'iloc'): return float(val.iloc[0])
        if hasattr(val, 'item'): return float(val.item())
        return float(val)
    except Exception:
        return default

def fetch_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """Build OHLCV from bhavcopy. Fetches last 30 trading days."""
    symbol = ticker.replace(".NS","").replace(".BO","").strip().upper()
    dates  = get_trading_dates(30)
    rows   = []

    for date in dates:
        df = fetch_bhavcopy(date)
        if df.empty:
            continue
        row = df[df['SYMBOL'] == symbol]
        if not row.empty:
            r = row.iloc[0]
            try:
                vol = r['VOLUME'] if 'VOLUME' in r.index else 0
                rows.append({
                    'Date':   pd.Timestamp(r['DATE']),
                    'Open':   _safe_float(r['OPEN']) if not hasattr(r['OPEN'], '__len__') else float(r['OPEN'].iloc[0]),
                    'High':   _safe_float(r['HIGH']) if not hasattr(r['HIGH'], '__len__') else float(r['HIGH'].iloc[0]),
                    'Low':    _safe_float(r['LOW'])  if not hasattr(r['LOW'],  '__len__') else float(r['LOW'].iloc[0]),
                    'Close':  _safe_float(r['CLOSE']) if not hasattr(r['CLOSE'], '__len__') else float(r['CLOSE'].iloc[0]),
                    'Volume': float(vol) if not hasattr(vol, '__len__') else float(vol.iloc[0]) if len(vol)>0 else 0,
                })
            except Exception as row_err:
                logger.debug(f"Row parse error: {row_err}")
                continue
        time.sleep(0.1)

    if not rows:
        logger.warning(f"No bhavcopy data for {symbol}")
        return pd.DataFrame()

    return pd.DataFrame(rows).set_index('Date').sort_index()

def fetch_current_price(ticker: str) -> dict:
    """Get latest price from most recent bhavcopy."""
    symbol = ticker.replace(".NS","").replace(".BO","").strip().upper()

    for date in get_trading_dates(5):
        df = fetch_bhavcopy(date)
        if df.empty:
            continue
        row = df[df['SYMBOL'] == symbol]
        if not row.empty:
            r = row.iloc[0]
            return {
                "ticker":     ticker,
                "price":      _safe_float(r['CLOSE']),
                "prev_close": _safe_float(r['OPEN']),
                "change_pct": round((_safe_float(r['CLOSE'])-_safe_float(r['OPEN']))/_safe_float(r['OPEN'])*100, 2) if _safe_float(r['OPEN'])>0 else 0,
                "market_cap": 0,
                "pe_ratio":   None,
                "52w_high":   0,
                "52w_low":    0,
                "name":       symbol,
                "sector":     "NSE",
                "avg_volume": _safe_float(r.get("VOLUME", 0)),
                "volume":     _safe_float(r.get("VOLUME", 0)),
            }
        time.sleep(0.1)
    return {}

def fetch_bulk_prices(tickers: list) -> dict:
    result  = {t: None for t in tickers}
    symbols = {t.replace(".NS","").replace(".BO","").upper(): t for t in tickers}
    for date in get_trading_dates(3):
        df = fetch_bhavcopy(date)
        if df.empty:
            continue
        for _, row in df.iterrows():
            sym = str(row['SYMBOL'])
            if sym in symbols and result[symbols[sym]] is None:
                result[symbols[sym]] = _safe_float(row['CLOSE'])
        if all(v is not None for v in result.values()):
            break
        time.sleep(0.2)
    return result

def fetch_global_context() -> dict:
    result = {}
    # USD/INR — confirmed working from Render
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=8, headers=HEADERS)
        if r.status_code == 200:
            inr = r.json().get("rates",{}).get("INR")
            if inr:
                result["usdinr"] = {"value": round(inr,2), "change_pct": 0, "direction": "flat"}
    except Exception as e:
        logger.warning(f"USD/INR: {e}")

    # US indices via Yahoo Finance v6 (different endpoint, sometimes works)
    try:
        r = requests.get(
            "https://query2.finance.yahoo.com/v6/finance/quote?symbols=%5EGSPC,%5EIXIC",
            headers={**HEADERS,"Origin":"https://finance.yahoo.com","Referer":"https://finance.yahoo.com/"},
            timeout=8)
        if r.status_code == 200:
            quotes = r.json().get("quoteResponse",{}).get("result",[])
            for q in quotes:
                sym = q.get("symbol","")
                chg = q.get("regularMarketChangePercent",0)
                val = q.get("regularMarketPrice",0)
                if "GSPC" in sym:
                    result["sp500"]  = {"value":val,"change_pct":round(chg,2),"direction":"up" if chg>=0 else "down"}
                elif "IXIC" in sym:
                    result["nasdaq"] = {"value":val,"change_pct":round(chg,2),"direction":"up" if chg>=0 else "down"}
    except Exception as e:
        logger.warning(f"US indices: {e}")

    logger.info(f"Global context: {list(result.keys())}")
    return result

def fetch_fii_dii() -> dict:
    try:
        session = _get_nse_session()
        resp = session.get("https://www.nseindia.com/api/fiidiiTradeReact", headers=NSE_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            latest = data[0] if data else {}
            return {"fii_net_cr": latest.get("fiiNet",0), "dii_net_cr": latest.get("diiNet",0),
                    "fii_buy_cr": latest.get("fiiBuy",0), "fii_sell_cr": latest.get("fiiSell",0),
                    "date": latest.get("date","")}
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
            title = item.findtext("title","")
            if title:
                headlines.append(title)
                scores.append(TextBlob(title).sentiment.polarity)
    except Exception:
        pass
    if not scores:
        return {"score":0.0,"label":"neutral","count":0,"headlines":[]}
    avg = sum(scores)/len(scores)
    label = "positive" if avg>SENTIMENT_POSITIVE else "negative" if avg<SENTIMENT_NEGATIVE else "neutral"
    return {"score":round(avg,4),"label":label,"count":len(scores),"headlines":headlines[:5]}

def fetch_nse_delivery_pct(symbol: str) -> float:
    return 0.0  # Skip to avoid NSE rate limits

def screen_universe() -> list:
    """Return pre-qualified stocks — avoids blocked API calls."""
    logger.info(f"Pre-qualified universe: {len(PREQUALIFIED_STOCKS)} stocks")
    return PREQUALIFIED_STOCKS
