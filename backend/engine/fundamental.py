"""
StockSense India — engine/fundamental.py
FIXED VERSION — reads settings correctly, relaxed filters.
Replace your current engine/fundamental.py with this entire file.
"""

import time
import logging
import requests
import yfinance as yf
from config.settings import (
    IST,
    PROMOTER_HOLDING_MIN_PCT,
    DEBT_TO_EQUITY_MAX,
    INSTITUTIONAL_HOLDING_MIN_PCT,
    REVENUE_GROWTH_MIN_PCT,
)

logger = logging.getLogger("stocksense.fundamental")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def fetch_shareholding_yahoo(ticker: str) -> dict:
    """Fetch shareholding data from Yahoo Finance (always available)."""
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        inst_total = float(info.get("heldPercentInstitutions", 0) or 0) * 100
        insider    = float(info.get("heldPercentInsiders",     0) or 0) * 100
        return {
            "promoter_pct":       insider,
            "fii_pct":            inst_total * 0.4,
            "dii_pct":            inst_total * 0.3,
            "mf_pct":             inst_total * 0.3,
            "institutional_total": inst_total,
        }
    except Exception as e:
        logger.error(f"fetch_shareholding_yahoo({ticker}): {e}")
        return {}


def fetch_shareholding_nse(ticker: str) -> dict:
    """Try NSE API for shareholding, fall back to Yahoo if it fails."""
    clean = ticker.replace(".NS", "").replace(".BO", "")
    url   = f"https://www.nseindia.com/api/corporate-share-holdings-master?symbol={clean}"
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=8)
        time.sleep(0.5)
        resp = session.get(url, headers=NSE_HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                latest = data[0] if isinstance(data, list) else data
                return {
                    "promoter_pct":       float(latest.get("promoterAndPromoterGroupHolding", 0)),
                    "fii_pct":            float(latest.get("foreignInstitutionalInvestors", 0)),
                    "dii_pct":            float(latest.get("domesticInstitutionalInvestors", 0)),
                    "mf_pct":             float(latest.get("mutualFunds", 0)),
                    "institutional_total": (
                        float(latest.get("foreignInstitutionalInvestors", 0)) +
                        float(latest.get("domesticInstitutionalInvestors", 0)) +
                        float(latest.get("mutualFunds", 0))
                    ),
                }
    except Exception as e:
        logger.warning(f"fetch_shareholding_nse({clean}): {e}")
    return {}


def fetch_financials(ticker: str) -> dict:
    """Fetch financial metrics from Yahoo Finance."""
    try:
        info = yf.Ticker(ticker).info
        revenue_growth = (info.get("revenueGrowth", 0) or 0) * 100
        earnings_growth = (info.get("earningsGrowth", 0) or 0) * 100

        de_ratio = info.get("debtToEquity", None)
        if de_ratio is not None:
            debt_to_equity = de_ratio / 100
        else:
            total_debt   = info.get("totalDebt", 0) or 0
            total_equity = info.get("totalStockholderEquity", 1) or 1
            debt_to_equity = total_debt / total_equity

        return {
            "revenue_growth_pct":  round(revenue_growth, 2),
            "earnings_growth_pct": round(earnings_growth, 2),
            "debt_to_equity":      round(debt_to_equity, 3),
            "total_debt_cr":       round((info.get("totalDebt", 0) or 0) / 1e7, 1),
            "roe_pct":             round((info.get("returnOnEquity", 0) or 0) * 100, 2),
            "roa_pct":             round((info.get("returnOnAssets", 0) or 0) * 100, 2),
            "profit_margin_pct":   round((info.get("profitMargins", 0) or 0) * 100, 2),
            "pe_ratio":            info.get("trailingPE", None),
            "forward_pe":          info.get("forwardPE", None),
            "pb_ratio":            info.get("priceToBook", None),
            "current_ratio":       info.get("currentRatio", None),
            "market_cap_cr":       round((info.get("marketCap", 0) or 0) / 1e7, 1),
            "revenue_cr":          round((info.get("totalRevenue", 0) or 0) / 1e7, 1),
            "dividend_yield_pct":  round((info.get("dividendYield", 0) or 0) * 100, 2),
        }
    except Exception as e:
        logger.error(f"fetch_financials({ticker}): {e}")
        return {}


def apply_hard_filters(ticker: str, shareholding: dict, financials: dict) -> tuple:
    """
    Apply 4 mandatory filters. Returns (passed, failure_reasons).
    Uses relaxed thresholds from settings.py.
    """
    failures = []

    # Filter 1: Promoter holding
    promoter = shareholding.get("promoter_pct", 0)
    if promoter < PROMOTER_HOLDING_MIN_PCT:
        failures.append(
            f"Promoter {promoter:.1f}% < {PROMOTER_HOLDING_MIN_PCT}% min"
        )

    # Filter 2: Debt-to-equity
    de = financials.get("debt_to_equity", 999)
    if de >= DEBT_TO_EQUITY_MAX:
        failures.append(f"D/E {de:.2f} >= {DEBT_TO_EQUITY_MAX} max")

    # Filter 3: Institutional holding (FII + DII + MF)
    inst = max(
        shareholding.get("institutional_total", 0),
        shareholding.get("fii_pct", 0) + shareholding.get("dii_pct", 0) + shareholding.get("mf_pct", 0)
    )
    if inst < INSTITUTIONAL_HOLDING_MIN_PCT:
        failures.append(
            f"Institutional {inst:.1f}% < {INSTITUTIONAL_HOLDING_MIN_PCT}% min"
        )

    # Filter 4: Revenue growth
    rev_growth = financials.get("revenue_growth_pct", 0)
    if rev_growth < REVENUE_GROWTH_MIN_PCT:
        failures.append(
            f"Revenue growth {rev_growth:.1f}% < {REVENUE_GROWTH_MIN_PCT}% min"
        )

    passed = len(failures) == 0
    if passed:
        logger.info(f"  ✓ {ticker} passed fundamental filters")
    else:
        logger.info(f"  ✗ {ticker} failed: {' | '.join(failures)}")

    return passed, failures


def score_fundamentals_deep(shareholding: dict, financials: dict) -> tuple:
    """Score fundamental quality (0-1). Only called after hard filters pass."""
    score   = 0.50
    signals = []

    promoter = shareholding.get("promoter_pct", 0)
    inst     = max(
        shareholding.get("institutional_total", 0),
        shareholding.get("fii_pct", 0) + shareholding.get("dii_pct", 0) + shareholding.get("mf_pct", 0)
    )
    mf          = shareholding.get("mf_pct", 0)
    de          = financials.get("debt_to_equity", 1)
    roe         = financials.get("roe_pct", 0)
    rev_growth  = financials.get("revenue_growth_pct", 0)
    earn_growth = financials.get("earnings_growth_pct", 0)
    pe          = financials.get("pe_ratio") or 50

    if promoter >= 55:
        score += 0.12; signals.append(f"Strong promoter {promoter:.0f}%")
    elif promoter >= 45:
        score += 0.06; signals.append(f"Solid promoter {promoter:.0f}%")

    if de <= 0.1:
        score += 0.12; signals.append("Virtually debt-free")
    elif de <= 0.3:
        score += 0.08; signals.append(f"Low debt D/E {de:.2f}")
    elif de <= 0.5:
        score += 0.04; signals.append(f"Comfortable debt D/E {de:.2f}")

    if inst >= 25:
        score += 0.10; signals.append(f"Heavy institutional {inst:.0f}%")
    elif inst >= 15:
        score += 0.05; signals.append(f"Good institutional {inst:.0f}%")

    if mf >= 10:
        score += 0.06; signals.append(f"MF conviction {mf:.0f}%")

    if rev_growth >= 20:
        score += 0.10; signals.append(f"Strong revenue +{rev_growth:.0f}%")
    elif rev_growth >= 10:
        score += 0.05; signals.append(f"Healthy revenue +{rev_growth:.0f}%")

    if earn_growth >= 15:
        score += 0.08; signals.append(f"Earnings growth +{earn_growth:.0f}%")

    if roe >= 15:
        score += 0.06; signals.append(f"Strong ROE {roe:.0f}%")

    if 10 < pe < 25:
        score += 0.05; signals.append(f"Attractive P/E {pe:.0f}")

    score = min(score, 1.0)

    parts = []
    if promoter >= 45: parts.append(f"Promoter {promoter:.0f}%")
    if de <= 0.3: parts.append("Low debt")
    if inst >= 15: parts.append(f"Inst {inst:.0f}%")
    if rev_growth >= 10: parts.append(f"Rev +{rev_growth:.0f}%")
    summary = " · ".join(parts[:4])

    return score, signals, summary


def run_fundamental_analysis(ticker: str) -> dict:
    """
    Full fundamental pipeline for one stock.
    Returns dict with passed/failed status and scores.
    """
    logger.info(f"  Fundamental check: {ticker}")

    # Try NSE first, Yahoo as fallback
    shareholding = fetch_shareholding_nse(ticker)
    if not shareholding or shareholding.get("promoter_pct", 0) == 0:
        shareholding = fetch_shareholding_yahoo(ticker)

    financials = fetch_financials(ticker)

    if not shareholding and not financials:
        return {
            "passed": False, "score": 0, "signals": [], "summary": "",
            "failure_reasons": ["Could not fetch fundamental data"],
            "shareholding": {}, "financials": {},
        }

    # If shareholding is empty, still try with defaults (don't block)
    if not shareholding:
        shareholding = {"promoter_pct": 0, "institutional_total": 0,
                        "fii_pct": 0, "dii_pct": 0, "mf_pct": 0}

    if not financials:
        financials = {"debt_to_equity": 0, "revenue_growth_pct": 0}

    passed, failures = apply_hard_filters(ticker, shareholding, financials)

    if not passed:
        return {
            "passed": False, "score": 0, "signals": [], "summary": "",
            "failure_reasons": failures,
            "shareholding": shareholding, "financials": financials,
        }

    score, signals, summary = score_fundamentals_deep(shareholding, financials)

    return {
        "passed": True, "score": score, "signals": signals,
        "summary": summary, "failure_reasons": [],
        "shareholding": shareholding, "financials": financials,
    }
