"""
StockSense India — engine/fundamental.py v4.0
Uses hardcoded fundamentals DB instead of Yahoo Finance (which is blocked on Render).
"""

import logging
from config.settings import (
    PROMOTER_HOLDING_MIN_PCT, DEBT_TO_EQUITY_MAX,
    INSTITUTIONAL_HOLDING_MIN_PCT, REVENUE_GROWTH_MIN_PCT,
)
from data.fetcher import FUNDAMENTALS_DB

logger = logging.getLogger("stocksense.fundamental")


def run_fundamental_analysis(ticker: str) -> dict:
    """
    Look up fundamental data from hardcoded DB.
    Falls back to passing with neutral score if not found.
    """
    symbol = ticker.replace(".NS","").replace(".BO","").strip().upper()
    logger.info(f"  Fundamental check: {ticker}")

    fund = FUNDAMENTALS_DB.get(symbol)

    if not fund:
        # Not in DB — give neutral pass so engine still analyses it
        logger.info(f"  {ticker} not in fundamentals DB — using neutral pass")
        return {
            "passed": True, "score": 0.5, "signals": ["Data not in DB"],
            "summary": "", "failure_reasons": [],
            "shareholding": {"promoter_pct": 40, "institutional_total": 15,
                             "fii_pct": 5, "dii_pct": 5, "mf_pct": 5},
            "financials": {"debt_to_equity": 0.3, "revenue_growth_pct": 10,
                           "roe_pct": 12, "pe_ratio": None},
        }

    promoter_pct, de_ratio, inst_pct, rev_growth = fund

    failures = []

    # For banks/NBFCs, promoter can be 0 — don't fail them on promoter
    is_bank = symbol in ("HDFCBANK","ICICIBANK","AXISBANK","KOTAKBANK","SBIN",
                         "INDUSINDBK","BANDHANBNK","FEDERALBNK","IDFCFIRSTB")
    effective_promoter = promoter_pct if not is_bank else max(promoter_pct, PROMOTER_HOLDING_MIN_PCT)

    if effective_promoter < PROMOTER_HOLDING_MIN_PCT:
        failures.append(f"Promoter {promoter_pct:.1f}% < {PROMOTER_HOLDING_MIN_PCT}%")

    # For NBFCs/banks, D/E naturally high — relax to 5.0
    is_nbfc = symbol in ("BAJFINANCE","BAJAJFINSV","CHOLAFIN","SUNDARMFIN","MUTHOOTFIN")
    effective_de_max = 5.0 if (is_bank or is_nbfc) else DEBT_TO_EQUITY_MAX
    if de_ratio >= effective_de_max:
        failures.append(f"D/E {de_ratio:.2f} >= {effective_de_max}")

    if inst_pct < INSTITUTIONAL_HOLDING_MIN_PCT:
        failures.append(f"Institutional {inst_pct:.1f}% < {INSTITUTIONAL_HOLDING_MIN_PCT}%")

    if rev_growth < REVENUE_GROWTH_MIN_PCT:
        failures.append(f"Revenue growth {rev_growth:.1f}% < {REVENUE_GROWTH_MIN_PCT}%")

    passed = len(failures) == 0
    if passed:
        logger.info(f"  ✓ {ticker} passed fundamentals")
    else:
        logger.info(f"  ✗ {ticker} failed: {' | '.join(failures)}")

    # Score
    score = 0.5
    signals = []

    if promoter_pct >= 55:
        score += 0.12; signals.append(f"Strong promoter {promoter_pct:.0f}%")
    elif promoter_pct >= 40:
        score += 0.06; signals.append(f"Solid promoter {promoter_pct:.0f}%")

    if de_ratio <= 0.1:
        score += 0.12; signals.append("Virtually debt-free")
    elif de_ratio <= 0.4:
        score += 0.08; signals.append(f"Low debt D/E {de_ratio:.2f}")

    if inst_pct >= 30:
        score += 0.10; signals.append(f"High institutional {inst_pct:.0f}%")
    elif inst_pct >= 15:
        score += 0.05; signals.append(f"Good institutional {inst_pct:.0f}%")

    if rev_growth >= 20:
        score += 0.10; signals.append(f"Strong revenue +{rev_growth:.0f}%")
    elif rev_growth >= 10:
        score += 0.05; signals.append(f"Healthy revenue +{rev_growth:.0f}%")

    score = min(score, 1.0)

    parts = []
    if promoter_pct >= 40: parts.append(f"Promoter {promoter_pct:.0f}%")
    if de_ratio <= 0.4:    parts.append(f"D/E {de_ratio:.2f}")
    if inst_pct >= 15:     parts.append(f"Inst {inst_pct:.0f}%")
    if rev_growth >= 10:   parts.append(f"Rev +{rev_growth:.0f}%")
    summary = " · ".join(parts[:4])

    return {
        "passed": passed, "score": score, "signals": signals,
        "summary": summary, "failure_reasons": failures,
        "shareholding": {
            "promoter_pct": promoter_pct,
            "institutional_total": inst_pct,
            "fii_pct": inst_pct * 0.4,
            "dii_pct": inst_pct * 0.3,
            "mf_pct":  inst_pct * 0.3,
        },
        "financials": {
            "debt_to_equity":    de_ratio,
            "revenue_growth_pct": rev_growth,
            "roe_pct":           12.0,
            "pe_ratio":          None,
        },
    }
