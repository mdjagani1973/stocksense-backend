"""
StockSense India — config/settings.py
FIXED VERSION — compatible with all existing engine code.
Replace your current settings.py with this entire file.
"""

import pytz

# ── Timezone ──────────────────────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")

# ── Market Hours ──────────────────────────────────────────────────────────────
MARKET_OPEN_H  = 9
MARKET_OPEN_M  = 15
MARKET_CLOSE_H = 15
MARKET_CLOSE_M = 30

# ── Scheduler Times (IST) ────────────────────────────────────────────────────
SCHEDULE = {
    "preliminary_scan": {"hour": 19, "minute": 0},
    "early_morning":    {"hour":  2, "minute": 0},
    "global_pull":      {"hour":  6, "minute": 0},
    "final_picks":      {"hour":  9, "minute": 0},
    "intraday_scan_1":  {"hour": 11, "minute": 0},
    "intraday_scan_2":  {"hour": 13, "minute": 30},
    "eod_summary":      {"hour": 15, "minute": 45},
}

# ── Recommendation Parameters ────────────────────────────────────────────────
MAX_PICKS           = 5
MIN_PICKS           = 2
TARGET_PCT_MIN      = 3.0
TARGET_PCT_MAX      = 6.0
STOPLOSS_PCT        = 1.5
MIN_RR_RATIO        = 2.0
HOLD_SESSIONS_MIN   = 2
HOLD_SESSIONS_MAX   = 3
INTRADAY_ALERT_PCT  = 2.0

# ── Stock Universe Filters ────────────────────────────────────────────────────
MIN_MARKET_CAP_CR   = 2000
MIN_AVG_VOLUME      = 300_000
MAX_STOCKS_TO_SCAN  = 200
EXCHANGES           = ["NSE", "BSE"]

# ── Scoring Weights ───────────────────────────────────────────────────────────
WEIGHTS = {
    "technical":   0.40,
    "pattern":     0.30,
    "sentiment":   0.15,
    "fundamental": 0.15,
}

# ── Technical Indicator Thresholds ───────────────────────────────────────────
RSI_OVERSOLD        = 38
RSI_OVERBOUGHT      = 62
MACD_SIGNAL_WINDOW  = 9
EMA_SHORT           = 20
EMA_LONG            = 50
VOLUME_SPIKE_MULT   = 1.5
BOLLINGER_WINDOW    = 20
BOLLINGER_STD       = 2

# ── Sentiment Thresholds ─────────────────────────────────────────────────────
SENTIMENT_POSITIVE  = 0.10
SENTIMENT_NEGATIVE  = -0.10
NEWS_MAX_AGE_HOURS  = 36

# ── Data Sources ─────────────────────────────────────────────────────────────
YAHOO_BASE    = "https://query1.finance.yahoo.com/v8/finance/chart"
NSE_QUOTE_URL = "https://www.nseindia.com/api/quote-equity?symbol="
NSE_GAINERS_URL = "https://www.nseindia.com/api/live-analysis-variations?index=gainers"
NSE_LOSERS_URL  = "https://www.nseindia.com/api/live-analysis-variations?index=loosers"
GNEWS_RSS     = "https://news.google.com/rss/search?q={symbol}+stock+India&hl=en-IN&gl=IN&ceid=IN:en"

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = "stocksense.db"

# ── RELAXED Fundamental Hard Filter Thresholds ───────────────────────────────
# These are read by engine/fundamental.py as individual variables
# Relaxed so more stocks pass and engine generates picks
PROMOTER_HOLDING_MIN_PCT     = 35.0   # was 40% — relaxed
DEBT_TO_EQUITY_MAX           = 0.8    # was 0.5 — relaxed
INSTITUTIONAL_HOLDING_MIN_PCT = 10.0  # was 15% — relaxed
REVENUE_GROWTH_MIN_PCT       = 8.0    # was 10% — relaxed

# ── Stock Universe ────────────────────────────────────────────────────────────
STOCK_UNIVERSE = [
    # Nifty 50 Large Caps
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "WIPRO.NS",
    "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS", "ULTRACEMCO.NS",
    "TECHM.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS", "JSWSTEEL.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "ADANIENT.NS", "ADANIPORTS.NS",
    "BAJAJFINSV.NS", "DRREDDY.NS", "CIPLA.NS", "EICHERMOT.NS", "DIVISLAB.NS",
    "BRITANNIA.NS", "GRASIM.NS", "APOLLOHOSP.NS", "INDUSINDBK.NS",
    "HEROMOTOCO.NS", "TATACONSUM.NS", "HINDALCO.NS", "BPCL.NS",
    "COALINDIA.NS", "SBILIFE.NS", "HDFCLIFE.NS", "M&M.NS", "BAJAJ-AUTO.NS",
    # Mid Caps
    "MUTHOOTFIN.NS", "BANKBARODA.NS", "PFC.NS", "RECLTD.NS", "HAL.NS",
    "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "LTIM.NS",
    "TORNTPHARM.NS", "LUPIN.NS", "AUROPHARMA.NS",
    "HAVELLS.NS", "POLYCAB.NS", "DIXON.NS", "TRENT.NS",
    "IRCTC.NS", "IRFC.NS", "RVNL.NS",
    "ZOMATO.NS", "NAUKRI.NS",
    "CHOLAFIN.NS", "SUNDARMFIN.NS", "MANAPPURAM.NS",
]
