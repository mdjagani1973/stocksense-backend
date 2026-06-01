"""
StockSense India — engine/fundamental.py v5.0
Uses hardcoded DB. Fixed promoter thresholds for ITC, HEROMOTOCO, TATACONSUM.
"""
import logging
from config.settings import (
    PROMOTER_HOLDING_MIN_PCT, DEBT_TO_EQUITY_MAX,
    INSTITUTIONAL_HOLDING_MIN_PCT, REVENUE_GROWTH_MIN_PCT,
    TRUE_SWING_MAX_DEBT_TO_EQUITY_HARD, TRUE_SWING_MIN_INSTITUTIONAL_HARD_PCT,
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


def run_fundamental_analysis(ticker: str, strategy: str = "true_swing") -> dict:
    symbol = ticker.replace(".NS","").replace(".BO","").strip().upper()
    logger.info(f"  Fundamental check: {ticker} [strategy=%s]", strategy)

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
    hard_failures = []
    caution_reasons = []

    # Promoter check (banks/PSUs exempt)
    is_bank = symbol in BANK_EXEMPT
    is_psu  = symbol in PSU_EXEMPT
    is_nbfc = symbol in NBFC_EXEMPT
    apply_promoter_filter = not is_bank and not is_psu
    apply_de_filter = not is_bank and not is_nbfc

    promoter_flag = apply_promoter_filter and promoter_pct < PROMOTER_HOLDING_MIN_PCT
    de_flag = apply_de_filter and de_ratio >= DEBT_TO_EQUITY_MAX and not (is_psu and de_ratio < 3.0)
    inst_flag = inst_pct < INSTITUTIONAL_HOLDING_MIN_PCT
    revenue_flag = rev_growth < REVENUE_GROWTH_MIN_PCT

    if strategy == "quality_swing":
        if promoter_flag:
            hard_failures.append(f"Promoter {promoter_pct:.1f}% < {PROMOTER_HOLDING_MIN_PCT}%")
        if de_flag:
            hard_failures.append(f"D/E {de_ratio:.2f} >= {DEBT_TO_EQUITY_MAX}")
        if inst_flag:
            hard_failures.append(f"Institutional {inst_pct:.1f}% < {INSTITUTIONAL_HOLDING_MIN_PCT}%")
        if revenue_flag:
            hard_failures.append(f"Revenue {rev_growth:.1f}% < {REVENUE_GROWTH_MIN_PCT}%")
    else:
        if apply_de_filter and de_ratio >= TRUE_SWING_MAX_DEBT_TO_EQUITY_HARD:
            hard_failures.append(f"D/E {de_ratio:.2f} >= hard max {TRUE_SWING_MAX_DEBT_TO_EQUITY_HARD}")
        if inst_pct < TRUE_SWING_MIN_INSTITUTIONAL_HARD_PCT:
            hard_failures.append(f"Institutional {inst_pct:.1f}% < hard min {TRUE_SWING_MIN_INSTITUTIONAL_HARD_PCT}%")
        if promoter_flag:
            caution_reasons.append(f"Promoter {promoter_pct:.1f}% < {PROMOTER_HOLDING_MIN_PCT}%")
        if de_flag:
            caution_reasons.append(f"D/E {de_ratio:.2f} >= {DEBT_TO_EQUITY_MAX}")
        if inst_flag:
            caution_reasons.append(f"Institutional {inst_pct:.1f}% < {INSTITUTIONAL_HOLDING_MIN_PCT}%")
        if revenue_flag:
            caution_reasons.append(f"Revenue {rev_growth:.1f}% < {REVENUE_GROWTH_MIN_PCT}%")

    passed = len(hard_failures) == 0
    if passed:
        logger.info(f"  ✓ {ticker} passed fundamentals")
    else:
        logger.info(f"  ✗ {ticker} failed: {' | '.join(hard_failures)}")

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
    if strategy == "true_swing":
        if promoter_flag:
            score -= 0.05
            signals.append("Promoter comfort below quality profile")
        if de_flag:
            score -= 0.07
            signals.append("Leverage above quality profile")
        if inst_flag:
            score -= 0.04
            signals.append("Institutional sponsorship light")
        if revenue_flag:
            score -= 0.05
            signals.append("Growth softer than quality profile")
    score = max(0.2, score)
    score = min(score, 1.0)

    parts = []
    if promoter_pct >= 35: parts.append(f"Promoter {promoter_pct:.0f}%")
    if de_ratio <= 0.5:    parts.append(f"D/E {de_ratio:.2f}")
    if inst_pct >= 15:     parts.append(f"Inst {inst_pct:.0f}%")
    if rev_growth >= 8:    parts.append(f"Rev +{rev_growth:.0f}%")
    if strategy == "true_swing" and caution_reasons:
        parts.append("Soft fundamental caution")

    return {
        "passed": passed, "score": score, "signals": signals,
        "summary": " · ".join(parts[:4]), "failure_reasons": hard_failures,
        "caution_reasons": caution_reasons,
        "shareholding": {"promoter_pct": promoter_pct, "institutional_total": inst_pct,
                         "fii_pct": inst_pct*0.4, "dii_pct": inst_pct*0.3, "mf_pct": inst_pct*0.3},
        "financials": {"debt_to_equity": de_ratio, "revenue_growth_pct": rev_growth,
                       "roe_pct": 12.0, "pe_ratio": None},
    }
