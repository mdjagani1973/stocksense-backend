"""
StockSense India — Fundamental Analysis Engine
Hard filter gate + scoring for fundamentally strong stocks only.

MANDATORY FILTERS (stock is REJECTED if any fail):
  1. Promoter holding > 40%
  2. Debt-to-equity < 0.5
  3. FII + DII + MF holding > 15% combined
  4. Revenue growth > 10% YoY

Sources: Yahoo Finance (yfinance) + NSE shareholding scraper
"""

import time
import logging
import requests
import yfinance as yf
from config.settings import IST, NSE_HEADERS

logger = logging.getLogger("stocksense.fundamental")

# ── Hard Filter Thresholds ─────────────────────────────────────────────────────
HARD_FILTERS = {
    "promoter_holding_min_pct":    40.0,   # % — mandatory
    "debt_to_equity_max":           0.5,   # ratio — mandatory (0.5 = 50 paise debt per ₹1 equity)
    "institutional_holding_min_pct":15.0,  # FII+DII+MF combined % — mandatory
    "revenue_growth_min_pct":      10.0,   # YoY % — mandatory
}

# ── Scoring Thresholds (bonus points, not hard gates) ─────────────────────────
SCORE_THRESHOLDS = {
    "promoter_holding_strong":     55.0,   # > 55% = strong signal
    "debt_free":                    0.1,   # < 0.1 = practically debt free
    "institutional_strong":        25.0,   # > 25% = heavy institutional interest
    "revenue_growth_strong":       20.0,   # > 20% = high growth
    "roe_good":                    15.0,   # Return on equity > 15%
    "profit_growth_good":          15.0,   # Net profit growth > 15% YoY
    "pe_reasonable_max":           40.0,   # P/E below 40 = not overpriced
    "current_ratio_good":           1.5,   # Current ratio > 1.5 = liquid
}


# ── NSE Shareholding Scraper ──────────────────────────────────────────────────

def fetch_shareholding_nse(symbol: str) -> dict:
    """
    Fetch shareholding pattern from NSE API.
    Returns: {promoter_pct, fii_pct, dii_pct, mf_pct, public_pct}

    NSE updates this quarterly. We use the latest available quarter.
    """
    clean = symbol.replace(".NS", "").replace(".BO", "")
    url   = f"https://www.nseindia.com/api/corporate-share-holdings-master?symbol={clean}"

    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        time.sleep(0.8)
        resp = session.get(url, headers=NSE_HEADERS, timeout=10)

        if resp.status_code != 200:
            logger.warning(f"NSE shareholding {clean}: HTTP {resp.status_code}")
            return {}

        data = resp.json()
        if not data:
            return {}

        # NSE returns list of quarters — take the most recent
        latest = data[0] if isinstance(data, list) else data

        return {
            "promoter_pct": float(latest.get("promoterAndPromoterGroupHolding", 0)),
            "fii_pct":      float(latest.get("foreignInstitutionalInvestors", 0)),
            "dii_pct":      float(latest.get("domesticInstitutionalInvestors", 0)),
            "mf_pct":       float(latest.get("mutualFunds", 0)),
            "public_pct":   float(latest.get("publicAndOthers", 0)),
            "quarter":      latest.get("date", ""),
        }

    except Exception as e:
        logger.error(f"fetch_shareholding_nse({clean}): {e}")
        return {}


def fetch_shareholding_yahoo(ticker: str) -> dict:
    """
    Fallback: get institutional holding % from Yahoo Finance.
    Less detailed than NSE but always available.
    """
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        return {
            "promoter_pct": float(info.get("heldPercentInsiders", 0)) * 100,
            "fii_pct":      float(info.get("heldPercentInstitutions", 0)) * 100 * 0.4,  # estimate
            "dii_pct":      float(info.get("heldPercentInstitutions", 0)) * 100 * 0.3,  # estimate
            "mf_pct":       float(info.get("heldPercentInstitutions", 0)) * 100 * 0.3,  # estimate
            "institutional_total": float(info.get("heldPercentInstitutions", 0)) * 100,
        }
    except Exception as e:
        logger.error(f"fetch_shareholding_yahoo({ticker}): {e}")
        return {}


# ── Financial Metrics from Yahoo ──────────────────────────────────────────────

def fetch_financials(ticker: str) -> dict:
    """
    Fetch key financial metrics from Yahoo Finance.
    Returns structured dict with all fundamental data points.
    """
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info

        # Revenue growth — compare TTM vs prior year
        revenue_growth_pct = (info.get("revenueGrowth", 0) or 0) * 100

        # Earnings growth
        earnings_growth_pct = (info.get("earningsGrowth", 0) or 0) * 100

        # Debt metrics
        total_debt   = info.get("totalDebt", 0) or 0
        total_equity = info.get("totalStockholderEquity", 0) or 1  # avoid div/0
        debt_to_equity = total_debt / total_equity if total_equity else 999

        # Also available directly
        de_ratio = info.get("debtToEquity", None)
        if de_ratio is not None:
            debt_to_equity = de_ratio / 100   # Yahoo gives it as percentage

        return {
            # Growth
            "revenue_growth_pct":   round(revenue_growth_pct, 2),
            "earnings_growth_pct":  round(earnings_growth_pct, 2),

            # Debt
            "debt_to_equity":       round(debt_to_equity, 3),
            "total_debt_cr":        round(total_debt / 1e7, 1),

            # Profitability
            "roe_pct":              round((info.get("returnOnEquity", 0) or 0) * 100, 2),
            "roa_pct":              round((info.get("returnOnAssets", 0) or 0) * 100, 2),
            "profit_margin_pct":    round((info.get("profitMargins", 0) or 0) * 100, 2),
            "operating_margin_pct": round((info.get("operatingMargins", 0) or 0) * 100, 2),

            # Valuation
            "pe_ratio":             info.get("trailingPE", None),
            "forward_pe":           info.get("forwardPE", None),
            "peg_ratio":            info.get("pegRatio", None),
            "pb_ratio":             info.get("priceToBook", None),
            "ev_ebitda":            info.get("enterpriseToEbitda", None),

            # Liquidity
            "current_ratio":        info.get("currentRatio", None),
            "quick_ratio":          info.get("quickRatio", None),

            # Size
            "market_cap_cr":        round((info.get("marketCap", 0) or 0) / 1e7, 1),
            "revenue_cr":           round((info.get("totalRevenue", 0) or 0) / 1e7, 1),

            # Dividends
            "dividend_yield_pct":   round((info.get("dividendYield", 0) or 0) * 100, 2),
        }

    except Exception as e:
        logger.error(f"fetch_financials({ticker}): {e}")
        return {}


# ── Hard Filter Gate ──────────────────────────────────────────────────────────

def apply_hard_filters(
    ticker:       str,
    shareholding: dict,
    financials:   dict,
) -> tuple[bool, list[str]]:
    """
    Apply all 4 mandatory filters.
    Returns (passed: bool, failure_reasons: list)
    A stock MUST pass ALL 4 to proceed to scoring.
    """
    failures = []

    # ── Filter 1: Promoter Holding > 40% ─────────────────────────────────────
    promoter = shareholding.get("promoter_pct", 0)
    if promoter < HARD_FILTERS["promoter_holding_min_pct"]:
        failures.append(
            f"Promoter holding {promoter:.1f}% < {HARD_FILTERS['promoter_holding_min_pct']}% required"
        )

    # ── Filter 2: Debt-to-Equity < 0.5 ───────────────────────────────────────
    de = financials.get("debt_to_equity", 999)
    if de >= HARD_FILTERS["debt_to_equity_max"]:
        failures.append(
            f"D/E ratio {de:.2f} ≥ {HARD_FILTERS['debt_to_equity_max']} limit"
        )

    # ── Filter 3: FII + DII + MF > 15% combined ──────────────────────────────
    fii = shareholding.get("fii_pct", 0)
    dii = shareholding.get("dii_pct", 0)
    mf  = shareholding.get("mf_pct", 0)
    institutional_total = shareholding.get("institutional_total", fii + dii + mf)
    combined = max(institutional_total, fii + dii + mf)
    if combined < HARD_FILTERS["institutional_holding_min_pct"]:
        failures.append(
            f"FII+DII+MF holding {combined:.1f}% < {HARD_FILTERS['institutional_holding_min_pct']}% required"
        )

    # ── Filter 4: Revenue Growth > 10% YoY ───────────────────────────────────
    rev_growth = financials.get("revenue_growth_pct", 0)
    if rev_growth < HARD_FILTERS["revenue_growth_min_pct"]:
        failures.append(
            f"Revenue growth {rev_growth:.1f}% < {HARD_FILTERS['revenue_growth_min_pct']}% required"
        )

    passed = len(failures) == 0
    if not passed:
        logger.info(f"  ✗ {ticker} FAILED hard filters: {' | '.join(failures)}")
    else:
        logger.info(f"  ✓ {ticker} PASSED all hard filters")

    return passed, failures


# ── Fundamental Scoring (bonus layer, only if hard filters pass) ──────────────

def score_fundamentals_deep(
    shareholding: dict,
    financials:   dict,
) -> tuple[float, list[str], str]:
    """
    After passing hard filters, score the stock's fundamental quality.
    Returns (score 0–1, positive_signals list, summary_string)

    This score feeds into the composite recommendation score.
    """
    score   = 0.50   # base: stock already passed hard filters
    signals = []
    th      = SCORE_THRESHOLDS

    promoter      = shareholding.get("promoter_pct", 0)
    fii           = shareholding.get("fii_pct", 0)
    dii           = shareholding.get("dii_pct", 0)
    mf            = shareholding.get("mf_pct", 0)
    institutional = max(shareholding.get("institutional_total", 0), fii + dii + mf)

    de          = financials.get("debt_to_equity", 1)
    roe         = financials.get("roe_pct", 0)
    rev_growth  = financials.get("revenue_growth_pct", 0)
    earn_growth = financials.get("earnings_growth_pct", 0)
    pe          = financials.get("pe_ratio") or 50
    curr_ratio  = financials.get("current_ratio") or 1
    div_yield   = financials.get("dividend_yield_pct", 0)

    # ── Promoter conviction ───────────────────────────────────────────────────
    if promoter >= th["promoter_holding_strong"]:
        score += 0.12
        signals.append(f"Strong promoter holding {promoter:.1f}%")
    elif promoter >= 45:
        score += 0.06
        signals.append(f"Solid promoter holding {promoter:.1f}%")

    # ── Debt quality ──────────────────────────────────────────────────────────
    if de <= th["debt_free"]:
        score += 0.12
        signals.append("Virtually debt-free company")
    elif de <= 0.25:
        score += 0.08
        signals.append(f"Very low debt (D/E {de:.2f})")
    elif de <= 0.4:
        score += 0.04
        signals.append(f"Comfortable debt level (D/E {de:.2f})")

    # ── Institutional conviction ──────────────────────────────────────────────
    if institutional >= th["institutional_strong"]:
        score += 0.10
        signals.append(f"Heavy institutional interest ({institutional:.1f}% FII+DII+MF)")
    elif institutional >= 18:
        score += 0.05
        signals.append(f"Good institutional holding ({institutional:.1f}%)")

    # ── MF specifically (smart money in India) ────────────────────────────────
    if mf >= 10:
        score += 0.06
        signals.append(f"MF holding {mf:.1f}% — mutual fund conviction")

    # ── Revenue growth ────────────────────────────────────────────────────────
    if rev_growth >= th["revenue_growth_strong"]:
        score += 0.10
        signals.append(f"Strong revenue growth {rev_growth:.1f}% YoY")
    elif rev_growth >= 12:
        score += 0.05
        signals.append(f"Healthy revenue growth {rev_growth:.1f}% YoY")

    # ── Earnings / profitability ──────────────────────────────────────────────
    if earn_growth >= th["profit_growth_good"]:
        score += 0.08
        signals.append(f"Earnings growth {earn_growth:.1f}% YoY")
    elif earn_growth >= 10:
        score += 0.04

    if roe >= th["roe_good"]:
        score += 0.06
        signals.append(f"Strong ROE {roe:.1f}%")
    elif roe >= 12:
        score += 0.03

    # ── Valuation reasonableness ──────────────────────────────────────────────
    if 10 < pe < 25:
        score += 0.05
        signals.append(f"Attractive valuation (P/E {pe:.1f})")
    elif 25 <= pe <= th["pe_reasonable_max"]:
        score += 0.02

    # ── Liquidity ─────────────────────────────────────────────────────────────
    if curr_ratio >= th["current_ratio_good"]:
        score += 0.04
        signals.append(f"Strong liquidity (current ratio {curr_ratio:.1f})")

    # ── Dividend (stability signal) ───────────────────────────────────────────
    if div_yield >= 1.5:
        score += 0.03
        signals.append(f"Dividend yield {div_yield:.1f}%")

    score = min(score, 1.0)

    # Build a concise summary for the recommendation card
    summary_parts = []
    if promoter >= 50:
        summary_parts.append(f"Promoter {promoter:.0f}%")
    if de <= 0.25:
        summary_parts.append("Low debt")
    elif de <= 0.5:
        summary_parts.append(f"D/E {de:.2f}")
    if institutional >= 20:
        summary_parts.append(f"Inst. {institutional:.0f}%")
    if rev_growth >= 15:
        summary_parts.append(f"Rev +{rev_growth:.0f}%")
    if roe >= 15:
        summary_parts.append(f"ROE {roe:.0f}%")

    summary = " · ".join(summary_parts[:4])

    return score, signals, summary


# ── Full Fundamental Analysis Pipeline ────────────────────────────────────────

def run_fundamental_analysis(ticker: str) -> dict:
    """
    Complete fundamental pipeline for one stock.
    Called by the recommender engine before technical analysis.

    Returns:
    {
        "passed":        bool,           # False = reject immediately
        "score":         float,          # 0–1 fundamental quality score
        "signals":       list[str],      # positive signals
        "summary":       str,            # short card summary
        "failure_reasons": list[str],    # why it failed (if failed)
        "shareholding":  dict,
        "financials":    dict,
    }
    """
    logger.info(f"  Running fundamental analysis: {ticker}")

    # 1. Fetch shareholding (NSE first, Yahoo fallback)
    shareholding = fetch_shareholding_nse(ticker)
    if not shareholding or shareholding.get("promoter_pct", 0) == 0:
        logger.info(f"  NSE shareholding unavailable for {ticker} — using Yahoo fallback")
        shareholding = fetch_shareholding_yahoo(ticker)

    # 2. Fetch financials
    financials = fetch_financials(ticker)

    if not shareholding or not financials:
        return {
            "passed":          False,
            "score":           0,
            "signals":         [],
            "summary":         "",
            "failure_reasons": ["Could not fetch fundamental data"],
            "shareholding":    {},
            "financials":      {},
        }

    # 3. Apply hard filter gate
    passed, failures = apply_hard_filters(ticker, shareholding, financials)

    if not passed:
        return {
            "passed":          False,
            "score":           0,
            "signals":         [],
            "summary":         "",
            "failure_reasons": failures,
            "shareholding":    shareholding,
            "financials":      financials,
        }

    # 4. Score the fundamentals (only if hard filters passed)
    score, signals, summary = score_fundamentals_deep(shareholding, financials)

    return {
        "passed":          True,
        "score":           score,
        "signals":         signals,
        "summary":         summary,
        "failure_reasons": [],
        "shareholding":    shareholding,
        "financials":      financials,
    }
