"""
StockSense India — config/settings.py v4.0
"""
import pytz

IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN_H  = 9
MARKET_OPEN_M  = 15
MARKET_CLOSE_H = 15
MARKET_CLOSE_M = 30

SCHEDULE = {
    "preliminary_scan": {"hour": 19, "minute": 0},
    "early_morning":    {"hour":  2, "minute": 0},
    "global_pull":      {"hour":  6, "minute": 0},
    "final_picks":      {"hour":  9, "minute": 0},
    "intraday_scan_1":  {"hour": 11, "minute": 0},
    "intraday_scan_2":  {"hour": 13, "minute": 30},
    "eod_summary":      {"hour": 15, "minute": 45},
}

MAX_PICKS           = 5
MIN_PICKS           = 2
TARGET_PCT_MIN      = 3.0
TARGET_PCT_MAX      = 7.0
STOPLOSS_PCT        = 1.5
MIN_RR_RATIO        = 2.0
HOLD_SESSIONS_MIN   = 3
HOLD_SESSIONS_MAX   = 5
INTRADAY_ALERT_PCT  = 2.0
MIN_STOPLOSS_PCT    = 1.2
MAX_STOPLOSS_PCT    = 3.0
ATR_STOPLOSS_MULT   = 1.15
ATR_TARGET_MULT     = 2.4
MARKET_REGIME_SAMPLE = 40
REGIME_RISK_ON_BREADTH20 = 0.58
REGIME_CAUTION_BREADTH20 = 0.45
REGIME_RISK_ON_RETURN20 = 0.5
REGIME_RISK_OFF_RETURN20 = -1.0
RELATIVE_STRENGTH_MIN_PCT = 0.5
RELATIVE_STRENGTH_BONUS_PCT = 3.0

MIN_MARKET_CAP_CR   = 2000
MIN_AVG_VOLUME      = 100000
MAX_STOCKS_TO_SCAN  = 300
EXCHANGES           = ["NSE", "BSE"]

WEIGHTS = {
    "technical":   0.48,
    "pattern":     0.27,
    "sentiment":   0.08,
    "fundamental": 0.17,
}

TECHNICAL_DIRECTION_MIN_SCORE = 0.38
MIN_TECH_PATTERN_SCORE        = 0.35
COMPOSITE_MIN_SCORE           = 0.43

RSI_OVERSOLD        = 38
RSI_OVERBOUGHT      = 62
MACD_SIGNAL_WINDOW  = 9
EMA_SHORT           = 20
EMA_LONG            = 50
VOLUME_SPIKE_MULT   = 1.5
BOLLINGER_WINDOW    = 20
BOLLINGER_STD       = 2

SENTIMENT_POSITIVE  = 0.10
SENTIMENT_NEGATIVE  = -0.10
NEWS_MAX_AGE_HOURS  = 36

YAHOO_BASE    = "https://query1.finance.yahoo.com/v8/finance/chart"
NSE_QUOTE_URL = "https://www.nseindia.com/api/quote-equity?symbol="
NSE_GAINERS_URL = "https://www.nseindia.com/api/live-analysis-variations?index=gainers"
NSE_LOSERS_URL  = "https://www.nseindia.com/api/live-analysis-variations?index=loosers"
GNEWS_RSS     = "https://news.google.com/rss/search?q={symbol}+stock+India&hl=en-IN&gl=IN&ceid=IN:en"

DB_PATH = "stocksense.db"

# Strategy profiles
DEFAULT_STRATEGY_PROFILE       = "true_swing"
SUPPORTED_STRATEGY_PROFILES    = ("true_swing", "quality_swing")

# Quality swing filters
PROMOTER_HOLDING_MIN_PCT      = 35.0
DEBT_TO_EQUITY_MAX            = 0.8
INSTITUTIONAL_HOLDING_MIN_PCT = 12.0
REVENUE_GROWTH_MIN_PCT        = 10.0

# True swing only hard fails extreme balance-sheet / sponsorship risk.
TRUE_SWING_MAX_DEBT_TO_EQUITY_HARD    = 2.5
TRUE_SWING_MIN_INSTITUTIONAL_HARD_PCT = 5.0

STOCK_UNIVERSE = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "HINDUNILVR.NS","ITC.NS","SBIN.NS","BHARTIARTL.NS","AXISBANK.NS",
    "KOTAKBANK.NS","LT.NS","BAJFINANCE.NS","HCLTECH.NS","WIPRO.NS",
    "ASIANPAINT.NS","MARUTI.NS","TITAN.NS","SUNPHARMA.NS","ULTRACEMCO.NS",
    "TECHM.NS","POWERGRID.NS","NTPC.NS","ONGC.NS","JSWSTEEL.NS",
    "TATAMOTORS.NS","TATASTEEL.NS","ADANIENT.NS","ADANIPORTS.NS",
    "BAJAJFINSV.NS","DRREDDY.NS","CIPLA.NS","EICHERMOT.NS","DIVISLAB.NS",
    "BRITANNIA.NS","GRASIM.NS","APOLLOHOSP.NS","INDUSINDBK.NS","HEROMOTOCO.NS",
    "TATACONSUM.NS","HINDALCO.NS","BPCL.NS","COALINDIA.NS",
    "SBILIFE.NS","HDFCLIFE.NS","M&M.NS","BAJAJ-AUTO.NS",
    "MUTHOOTFIN.NS","BANKBARODA.NS","PFC.NS","RECLTD.NS","HAL.NS",
    "PERSISTENT.NS","COFORGE.NS","MPHASIS.NS","LTIM.NS",
    "TORNTPHARM.NS","LUPIN.NS","AUROPHARMA.NS",
    "HAVELLS.NS","POLYCAB.NS","DIXON.NS","TRENT.NS",
    "IRCTC.NS","IRFC.NS","RVNL.NS","ZOMATO.NS","NAUKRI.NS",
    "CHOLAFIN.NS","SUNDARMFIN.NS","MANAPPURAM.NS",
]
