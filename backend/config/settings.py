"""
StockSense India — UPDATED config/settings.py
Relaxed fundamental filters so engine generates picks.
Replace your existing config/settings.py with this file.
"""

import pytz

IST = pytz.timezone("Asia/Kolkata")

# Market Hours
MARKET_OPEN_H  = 9
MARKET_OPEN_M  = 15
MARKET_CLOSE_H = 15
MARKET_CLOSE_M = 30

# ── UPDATED SCHEDULE — 2 AM preliminary scan added ────────────────────────────
SCHEDULE = {
    "preliminary_scan": {"hour": 19, "minute": 0},   # 7:00 PM — EOD scan
    "early_morning":    {"hour":  2, "minute": 0},   # 2:00 AM — overnight data
    "global_pull":      {"hour":  6, "minute": 0},   # 6:00 AM — US/Gift Nifty
    "final_picks":      {"hour":  9, "minute": 0},   # 9:00 AM — push picks
    "intraday_scan_1":  {"hour": 11, "minute": 0},   # 11:00 AM
    "intraday_scan_2":  {"hour": 13, "minute": 30},  # 1:30 PM
    "eod_summary":      {"hour": 15, "minute": 45},  # 3:45 PM
}

# Recommendation Parameters
MAX_PICKS           = 5
MIN_PICKS           = 2
TARGET_PCT_MIN      = 3.0
TARGET_PCT_MAX      = 6.0
STOPLOSS_PCT        = 1.5
MIN_RR_RATIO        = 2.0
HOLD_SESSIONS_MIN   = 2
HOLD_SESSIONS_MAX   = 3
INTRADAY_ALERT_PCT  = 2.0

# ── RELAXED FILTERS — so engine actually finds picks ──────────────────────────
# Original was too strict — almost no stocks passed all 4 simultaneously
MIN_MARKET_CAP_CR   = 2000       # ₹2,000 Cr minimum
MIN_AVG_VOLUME      = 300_000    # Reduced from 500k to 300k
MAX_STOCKS_TO_SCAN  = 200
EXCHANGES           = ["NSE", "BSE"]

# ── SCORING WEIGHTS ────────────────────────────────────────────────────────────
WEIGHTS = {
    "technical":    0.40,   # Increased — more weight on price action
    "pattern":      0.30,
    "sentiment":    0.15,   # Reduced
    "fundamental":  0.15,   # Reduced — filter not score
}

# Technical Thresholds
RSI_OVERSOLD        = 38    # Slightly relaxed from 35
RSI_OVERBOUGHT      = 62    # Slightly relaxed from 65
MACD_SIGNAL_WINDOW  = 9
EMA_SHORT           = 20
EMA_LONG            = 50
VOLUME_SPIKE_MULT   = 1.5   # Reduced from 1.8
BOLLINGER_WINDOW    = 20
BOLLINGER_STD       = 2

# Sentiment
SENTIMENT_POSITIVE  = 0.10   # Relaxed from 0.15
SENTIMENT_NEGATIVE  = -0.10
NEWS_MAX_AGE_HOURS  = 36     # Extended from 24

# Data Sources
YAHOO_BASE     = "https://query1.finance.yahoo.com/v8/finance/chart"
NSE_QUOTE_URL  = "https://www.nseindia.com/api/quote-equity?symbol="
GNEWS_RSS      = "https://news.google.com/rss/search?q={symbol}+stock+India&hl=en-IN&gl=IN&ceid=IN:en"

# Database
DB_PATH = "stocksense.db"

# ── RELAXED FUNDAMENTAL HARD FILTERS ──────────────────────────────────────────
# These are still meaningful but not so strict that 0 stocks pass
HARD_FILTERS = {
    "promoter_holding_min_pct":     35.0,   # Reduced from 40% — many good stocks are 35-40%
    "debt_to_equity_max":            0.8,   # Relaxed from 0.5 — allows more stocks
    "institutional_holding_min_pct": 10.0,  # Reduced from 15% — still shows institutional interest
    "revenue_growth_min_pct":         8.0,  # Reduced from 10% — catches good cos in slow periods
}

# Stock Universe — Nifty 100 + MidCap 50
STOCK_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "WIPRO.NS",
    "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS", "ULTRACEMCO.NS",
    "TECHM.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS", "JSWSTEEL.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "ADANIENT.NS", "ADANIPORTS.NS",
    "BAJAJFINSV.NS", "DRREDDY.NS", "CIPLA.NS", "EICHERMOT.NS", "DIVISLAB.NS",
    "BRITANNIA.NS", "GRASIM.NS", "APOLLOHOSP.NS", "INDUSINDBK.NS", "HEROMOTOCO.NS",
    "TATACONSUM.NS", "HINDALCO.NS", "BPCL.NS", "COALINDIA.NS",
    "SBILIFE.NS", "HDFCLIFE.NS", "M&M.NS", "BAJAJ-AUTO.NS",
    "MUTHOOTFIN.NS", "BANKBARODA.NS", "PFC.NS", "RECLTD.NS", "HAL.NS",
    "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "LTIM.NS",
    "TORNTPHARM.NS", "LUPIN.NS", "AUROPHARMA.NS",
    "HAVELLS.NS", "POLYCAB.NS", "DIXON.NS", "TRENT.NS",
    "IRCTC.NS", "IRFC.NS", "RVNL.NS",
    "ZOMATO.NS", "NAUKRI.NS",
    "CHOLAFIN.NS", "SUNDARMFIN.NS", "MANAPPURAM.NS",
]
