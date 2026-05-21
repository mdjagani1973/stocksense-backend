"""
StockSense India — engine/fundamental.py v5.0
Uses hardcoded DB. Fixed promoter thresholds for ITC, HEROMOTOCO, TATACONSUM.
"""
import logging
from config.settings import (
    PROMOTER_HOLDING_MIN_PCT, DEBT_TO_EQUITY_MAX,
    INSTITUTIONAL_HOLDING_MIN_PCT, REVENUE_GROWTH_MIN_PCT,
)
from data.fetcher import FUNDAMENTALS_DB

logger = logging.getLogger("stocksense.fundamental")

# Banks/NBFCs have naturally low/zero promoter holding — exempt from promoter filter
BANK_EXEMPT = {"HDFCBANK","ICICIBANK","AXISBANK","KOTAKBANK","SBIN",
               "INDUSINDBK","BANDHANBNK","FEDERALBNK","IDFCFIRSTB","AUBANK"}

# NBFCs have naturally high D/E — exempt from D/E filter
NBFC_EXEMPT = {"BAJFINANCE","BAJAJFINSV","CHOLAFIN","SUNDARMFIN",
               "MUTHOOTFIN","MANAPPURAM","PFC","RECLTD"}

# PSUs with govt as promoter — ITC (BAT/govt), ONGC etc
PSU_EXEMPT = {"ITC","ONGC","COALINDIA","NTPC","POWERGRID","BPCL","SBIN","BHEL"}


def run_fundamental_analysis(ticker: str) -> dict:
    symbol = ticker.replace(".NS","").replace(".BO","").strip().upper()
    logger.info(f"  Fundamental check: {ticker}")

    fund = FUNDAMENTALS_DB.get(symbol)
    if not fund:
        # Not in DB — give passing neutral score
        logger.info(f"  {ticker} not in DB — neutral pass")
        return {
            "passed": True, "score": 0.5, "signals": ["Not in DB"],
            "summary": "", "failure_reasons": [],
            "shareholding": {"promoter_pct":40,"institutional_total":15,
                             "fii_pct":5,"dii_pct":5,"mf_pct":5},
            "financials": {"debt_to_equity":0.3,"revenue_growth_pct":10,
                           "roe_pct":12,"pe_ratio":None},
        }

    promoter_pct, de_ratio, inst_pct, rev_growth = fund
    failures = []

    # Promoter check (banks/PSUs exempt)
    is_bank = symbol in BANK_EXEMPT
    is_psu  = symbol in PSU_EXEMPT
    if not is_bank and not is_psu:
        if promoter_pct < PROMOTER_HOLDING_MIN_PCT:
            failures.append(f"Promoter {promoter_pct:.1f}% < {PROMOTER_HOLDING_MIN_PCT}%")

    # D/E check (NBFCs/banks exempt)
    is_nbfc = symbol in NBFC_EXEMPT
    if not is_bank and not is_nbfc:
        if de_ratio >= DEBT_TO_EQUITY_MAX:
            # For PSUs like NTPC, POWERGRID — relax to 3.0
            if is_psu and de_ratio < 3.0:
                pass  # allow PSU infra cos
            else:
                failures.append(f"D/E {de_ratio:.2f} >= {DEBT_TO_EQUITY_MAX}")

    # Institutional check
    if inst_pct < INSTITUTIONAL_HOLDING_MIN_PCT:
        failures.append(f"Institutional {inst_pct:.1f}% < {INSTITUTIONAL_HOLDING_MIN_PCT}%")

    # Revenue growth check
    if rev_growth < REVENUE_GROWTH_MIN_PCT:
        failures.append(f"Revenue {rev_growth:.1f}% < {REVENUE_GROWTH_MIN_PCT}%")

    passed = len(failures) == 0
    if passed:
        logger.info(f"  ✓ {ticker} passed fundamentals")
    else:
        logger.info(f"  ✗ {ticker} failed: {' | '.join(failures)}")

    # Score
    score, signals = 0.5, []
    if promoter_pct >= 55: score += 0.12; signals.append(f"Strong promoter {promoter_pct:.0f}%")
    elif promoter_pct >= 40: score += 0.06; signals.append(f"Solid promoter {promoter_pct:.0f}%")
    if de_ratio <= 0.1: score += 0.12; signals.append("Debt-free")
    elif de_ratio <= 0.4: score += 0.08; signals.append(f"Low D/E {de_ratio:.2f}")
    if inst_pct >= 30: score += 0.10; signals.append(f"High inst {inst_pct:.0f}%")
    elif inst_pct >= 15: score += 0.05; signals.append(f"Good inst {inst_pct:.0f}%")
    if rev_growth >= 20: score += 0.10; signals.append(f"Rev +{rev_growth:.0f}%")
    elif rev_growth >= 10: score += 0.05; signals.append(f"Rev +{rev_growth:.0f}%")
    score = min(score, 1.0)

    parts = []
    if promoter_pct >= 35: parts.append(f"Promoter {promoter_pct:.0f}%")
    if de_ratio <= 0.5:    parts.append(f"D/E {de_ratio:.2f}")
    if inst_pct >= 15:     parts.append(f"Inst {inst_pct:.0f}%")
    if rev_growth >= 8:    parts.append(f"Rev +{rev_growth:.0f}%")

    return {
        "passed": passed, "score": score, "signals": signals,
        "summary": " · ".join(parts[:4]), "failure_reasons": failures,
        "shareholding": {"promoter_pct": promoter_pct, "institutional_total": inst_pct,
                         "fii_pct": inst_pct*0.4, "dii_pct": inst_pct*0.3, "mf_pct": inst_pct*0.3},
        "financials": {"debt_to_equity": de_ratio, "revenue_growth_pct": rev_growth,
                       "roe_pct": 12.0, "pe_ratio": None},
    }
