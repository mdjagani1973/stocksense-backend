"""
StockSense India — Central Configuration
All tunable parameters in one place.
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
    "preliminary_scan":  {"hour": 19, "minute": 0},   # 7:00 PM — EOD scan
    "global_pull":       {"hour":  6, "minute": 0},   # 6:00 AM — US/Gift Nifty
    "final_picks":       {"hour":  9, "minute": 0},   # 9:00 AM — push to app
    "intraday_scan_1":   {"hour": 11, "minute": 0},   # 11:00 AM
    "intraday_scan_2":   {"hour": 13, "minute": 30},  # 1:30 PM
    "eod_summary":       {"hour": 15, "minute": 45},  # 3:45 PM
}

# ── Recommendation Parameters ────────────────────────────────────────────────
MAX_PICKS           = 5          # max picks per day
MIN_PICKS           = 3          # min picks before publishing
TARGET_PCT_MIN      = 3.0        # minimum expected move %
TARGET_PCT_MAX      = 6.0        # maximum expected move %
STOPLOSS_PCT        = 1.5        # stop-loss %
MIN_RR_RATIO        = 2.0        # minimum reward:risk ratio
HOLD_SESSIONS_MIN   = 2          # minimum hold sessions
HOLD_SESSIONS_MAX   = 3          # maximum hold sessions
INTRADAY_ALERT_PCT  = 2.0        # alert if pick moves this % intraday

# ── Stock Universe Filters ────────────────────────────────────────────────────
MIN_MARKET_CAP_CR   = 2000       # crores — large & mid cap only
MIN_AVG_VOLUME      = 500_000    # 5 lakh shares daily avg
MAX_STOCKS_TO_SCAN  = 200        # top N stocks to analyse each run
EXCHANGES           = ["NSE", "BSE"]

# ── Scoring Weights (must sum to 1.0) ────────────────────────────────────────
WEIGHTS = {
    "technical":    0.35,
    "pattern":      0.30,
    "sentiment":    0.20,
    "fundamental":  0.15,
}

# ── Technical Indicator Thresholds ───────────────────────────────────────────
RSI_OVERSOLD        = 35         # buy signal
RSI_OVERBOUGHT      = 65         # sell signal
MACD_SIGNAL_WINDOW  = 9
EMA_SHORT           = 20
EMA_LONG            = 50
VOLUME_SPIKE_MULT   = 1.8        # volume > N × 20-day avg = spike
BOLLINGER_WINDOW    = 20
BOLLINGER_STD       = 2

# ── Sentiment Thresholds ─────────────────────────────────────────────────────
SENTIMENT_POSITIVE  = 0.15       # TextBlob polarity above this = positive
SENTIMENT_NEGATIVE  = -0.15      # below this = negative
NEWS_MAX_AGE_HOURS  = 24         # only use news within last N hours

# ── Data Sources ─────────────────────────────────────────────────────────────
YAHOO_BASE          = "https://query1.finance.yahoo.com/v8/finance/chart"
NSE_QUOTE_URL       = "https://www.nseindia.com/api/quote-equity?symbol="
NSE_GAINERS_URL     = "https://www.nseindia.com/api/live-analysis-variations?index=gainers"
NSE_LOSERS_URL      = "https://www.nseindia.com/api/live-analysis-variations?index=loosers"
GNEWS_RSS           = "https://news.google.com/rss/search?q={symbol}+stock+India&hl=en-IN&gl=IN&ceid=IN:en"

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH             = "stocksense.db"

# ── Nifty 100 + MidCap 50 Universe (Yahoo Finance tickers) ──────────────────
# .NS = NSE, .BO = BSE
STOCK_UNIVERSE = [
    # Large Cap — Nifty 50
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "WIPRO.NS",
    "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS", "ULTRACEMCO.NS",
    "NESTLEIND.NS", "TECHM.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS",
    "JSWSTEEL.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "ADANIENT.NS", "ADANIPORTS.NS",
    "BAJAJFINSV.NS", "DRREDDY.NS", "CIPLA.NS", "EICHERMOT.NS", "DIVISLAB.NS",
    "BRITANNIA.NS", "GRASIM.NS", "APOLLOHOSP.NS", "INDUSINDBK.NS", "HEROMOTOCO.NS",
    "SHRIRAMFIN.NS", "TATACONSUM.NS", "HINDALCO.NS", "BPCL.NS", "COALINDIA.NS",
    "SBILIFE.NS", "HDFCLIFE.NS", "M&M.NS", "BAJAJ-AUTO.NS", "VEDL.NS",
    # Mid Cap additions
    "MUTHOOTFIN.NS", "BANKBARODA.NS", "PFC.NS", "RECLTD.NS", "HAL.NS",
    "PIIND.NS", "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "LTIM.NS",
    "AUROPHARMA.NS", "TORNTPHARM.NS", "LUPIN.NS", "ALKEM.NS", "IPCALAB.NS",
    "VOLTAS.NS", "HAVELLS.NS", "POLYCAB.NS", "KEI.NS", "DIXON.NS",
    "PAGEIND.NS", "VBL.NS", "TRENT.NS", "NYKAA.NS", "DMART.NS",
    "IRCTC.NS", "IRFC.NS", "HUDCO.NS", "RVNL.NS", "RAILTEL.NS",
    "ZOMATO.NS", "PAYTM.NS", "POLICYBZR.NS", "NAUKRI.NS", "JUSTDIAL.NS",
    "CHOLAFIN.NS", "BAJAJHLDNG.NS", "SUNDARMFIN.NS", "MANAPPURAM.NS", "IIFL.NS",
]


NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept": "application/json, text/plain, */*",
    "Connection": "keep-alive"
}