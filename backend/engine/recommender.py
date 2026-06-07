"""
StockSense India — Recommendation Engine v2
True swing is the default profile. Quality swing is an optional stricter overlay.
"""

import logging
import sqlite3
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional
from statistics import median

from config.settings import (
    IST, WEIGHTS, MAX_PICKS, MIN_PICKS, STOPLOSS_PCT, MIN_RR_RATIO,
    HOLD_SESSIONS_MIN, HOLD_SESSIONS_MAX, DB_PATH,
    MIN_TECH_PATTERN_SCORE, COMPOSITE_MIN_SCORE,
    MIN_STOPLOSS_PCT, MAX_STOPLOSS_PCT, ATR_STOPLOSS_MULT, ATR_TARGET_MULT,
    TARGET_PCT_MIN, TARGET_PCT_MAX, RELATIVE_STRENGTH_MIN_PCT,
    RELATIVE_STRENGTH_BONUS_PCT, MARKET_REGIME_SAMPLE,
    REGIME_RISK_ON_BREADTH20, REGIME_CAUTION_BREADTH20,
    REGIME_RISK_ON_RETURN20, REGIME_RISK_OFF_RETURN20,
    EMA_SHORT, EMA_LONG,
    DEFAULT_STRATEGY_PROFILE, SUPPORTED_STRATEGY_PROFILES,
    TRUE_SWING_RELATIVE_STRENGTH_MIN_PCT, TRUE_SWING_BUY_SCORE_FLOOR,
    TRUE_SWING_PATTERN_SCORE_FLOOR, TRUE_SWING_RISK_OFF_BUY_SCORE_MIN,
)
from data.fetcher import (
    fetch_ohlcv, fetch_current_price, fetch_news_sentiment,
    fetch_fii_dii, fetch_global_context, screen_universe,
)
from engine.technical import compute_indicators, detect_signals, detect_patterns
from engine.fundamental import run_fundamental_analysis

logger = logging.getLogger("stocksense.engine")
UNKNOWN_SECTORS = {"", "Unknown", "NSE", "BSE", None}


@dataclass
class StockRecommendation:
    ticker: str; name: str; exchange: str; direction: str
    entry_price: float; entry_low: float; entry_high: float
    target_price: float; target_pct: float
    stoploss_price: float; stoploss_pct: float; rr_ratio: float
    confidence_pct: int; hold_sessions: str; reason: str
    signals: list; global_context: str; sector: str; market_cap_cr: float
    rsi: float; vol_ratio: float; sentiment_label: str; sentiment_score: float
    promoter_pct: float = 0.0; debt_to_equity: float = 0.0
    institutional_pct: float = 0.0; revenue_growth_pct: float = 0.0
    roe_pct: float = 0.0; pe_ratio: float = 0.0
    fundamental_summary: str = ""; fundamental_signals: list = field(default_factory=list)
    regime_label: str = ""; regime_score: float = 0.0
    relative_strength_pct: float = 0.0; atr_pct: float = 0.0
    strategy: str = DEFAULT_STRATEGY_PROFILE
    created_at: str = ""; date: str = ""

    def to_dict(self):
        d = asdict(self)
        d["signals"] = " | ".join(self.signals)
        d["fundamental_signals"] = " | ".join(self.fundamental_signals)
        return d


def _reject(ticker: str, reason: str, **details):
    detail_parts = []
    for key, value in details.items():
        if value is None:
            continue
        detail_parts.append(f"{key}={value}")
    suffix = f" ({', '.join(detail_parts)})" if detail_parts else ""
    logger.info(f"Reject {ticker}: {reason}{suffix}")
    return None


def _latest_market_date(df) -> str:
    """Return the latest trading-session date represented in the OHLCV data."""
    try:
        if df is None or getattr(df, "empty", True):
            return datetime.now(IST).strftime("%Y-%m-%d")
        latest = df.index.max()
        if hasattr(latest, "date"):
            return latest.date().isoformat()
    except Exception:
        pass
    return datetime.now(IST).strftime("%Y-%m-%d")


def compute_composite_score(tech, pattern, sentiment, fund, fii_data):
    w = WEIGHTS
    sent_raw = {"positive": 0.8, "neutral": 0.4, "negative": 0.1}.get(
        sentiment.get("label", "neutral"), 0.4)
    breakdown = {
        "technical": round(tech.get("score", 0) * w["technical"], 3),
        "pattern": round(pattern.get("score", 0) * w["pattern"], 3),
        "sentiment": round(sent_raw * w["sentiment"], 3),
        "fundamental": round(fund.get("score", 0.5) * w["fundamental"], 3),
    }
    composite = sum(breakdown.values())
    fii_net = fii_data.get("fii_net_cr", 0)
    direction = tech.get("direction", "neutral")
    if direction == "buy" and fii_net > 500:
        composite += 0.03
        breakdown["fii_bonus"] = 0.03
    elif direction == "sell" and fii_net < -500:
        composite += 0.03
        breakdown["fii_bonus"] = 0.03
    else:
        breakdown["fii_bonus"] = 0.0

    parts = [p for p in [
        tech.get("reason", ""),
        pattern.get("patterns", [""])[0] if pattern.get("patterns") else "",
        fund.get("summary", ""),
        "Positive news" if sentiment.get("label") == "positive" else "",
        f"FII buying ₹{fii_net:,.0f} Cr" if fii_net > 800 else "",
    ] if p]
    return min(composite, 1.0), " · ".join(parts[:4]), breakdown


def _safe_return_pct(df, lookback: int = 20) -> Optional[float]:
    try:
        if df.empty or len(df) <= lookback:
            return None
        start = float(df["Close"].iloc[-(lookback + 1)])
        end = float(df["Close"].iloc[-1])
        if start <= 0:
            return None
        return round((end / start - 1) * 100, 2)
    except Exception:
        return None


def assess_market_regime(universe: list[str]) -> dict:
    sample = []
    breadth20 = 0
    breadth50 = 0
    returns20 = []
    for ticker in universe[:MARKET_REGIME_SAMPLE]:
        df = fetch_ohlcv(ticker, period="3mo", interval="1d")
        if df.empty or len(df) < 55:
            continue
        df = compute_indicators(df)
        row = df.iloc[-1]
        close = float(row["Close"])
        ema20 = float(row.get(f"ema{EMA_SHORT}", close))
        ema50 = float(row.get(f"ema{EMA_LONG}", close))
        ret20 = _safe_return_pct(df, 20)
        if ret20 is None:
            continue
        sample.append(ticker)
        returns20.append(ret20)
        breadth20 += 1 if close > ema20 else 0
        breadth50 += 1 if close > ema50 else 0

    counted = len(sample)
    if counted < 8:
        return {
            "label": "neutral",
            "score": 0.5,
            "breadth20": 0.5,
            "breadth50": 0.5,
            "benchmark_return20": 0.0,
            "summary": "Regime fallback: insufficient breadth sample",
        }

    breadth20_pct = breadth20 / counted
    breadth50_pct = breadth50 / counted
    benchmark_return20 = round(median(returns20), 2)
    normalized_return = min(max((benchmark_return20 + 5) / 10, 0), 1)
    regime_score = round((breadth20_pct * 0.5) + (breadth50_pct * 0.3) + (normalized_return * 0.2), 3)

    if breadth20_pct >= REGIME_RISK_ON_BREADTH20 and benchmark_return20 >= REGIME_RISK_ON_RETURN20:
        label = "risk_on"
    elif breadth20_pct <= REGIME_CAUTION_BREADTH20 or benchmark_return20 <= REGIME_RISK_OFF_RETURN20:
        label = "risk_off"
    else:
        label = "cautious"

    summary = f"Regime {label.replace('_', ' ')} · breadth20 {breadth20_pct:.0%} · breadth50 {breadth50_pct:.0%} · median20d {benchmark_return20:+.1f}%"
    return {
        "label": label,
        "score": regime_score,
        "breadth20": round(breadth20_pct, 3),
        "breadth50": round(breadth50_pct, 3),
        "benchmark_return20": benchmark_return20,
        "summary": summary,
    }


def _coerce_true_swing_buy(tech: dict, pattern: dict, relative_strength_pct: float, market_regime: dict) -> tuple[dict, bool]:
    buy_score = float(tech.get("buy_score", 0) or 0)
    sell_score = float(tech.get("sell_score", 0) or 0)
    pattern_score = float(pattern.get("score", 0) or 0)
    pattern_direction = pattern.get("direction", "neutral")
    regime_label = market_regime.get("label")

    if tech.get("direction") != "neutral":
        return tech, False
    # In true swing mode, a strong non-bearish pattern can upgrade a neutral technical read.
    # This catches setups that have constructive structure before the directional trigger fully flips.
    if pattern_direction == "sell":
        return tech, False
    if buy_score < TRUE_SWING_BUY_SCORE_FLOOR:
        return tech, False
    if pattern_score < TRUE_SWING_PATTERN_SCORE_FLOOR:
        return tech, False
    if buy_score <= sell_score:
        return tech, False
    if regime_label == "risk_off" and relative_strength_pct < TRUE_SWING_RELATIVE_STRENGTH_MIN_PCT:
        return tech, False

    upgraded = dict(tech)
    upgraded["direction"] = "buy"
    upgraded["score"] = round(max(buy_score, pattern_score * 0.9, (buy_score + pattern_score) / 2), 3)
    upgraded["signals"] = list(tech.get("signals", [])) + ["Pattern-backed swing buy despite neutral technical trigger"]
    upgraded["reason"] = " + ".join(upgraded["signals"][:3])
    return upgraded, True


def analyse_stock(
    ticker: str,
    fii_data: dict,
    global_ctx: dict,
    market_regime: dict,
    strategy: str = DEFAULT_STRATEGY_PROFILE,
) -> Optional[StockRecommendation]:
    try:
        if strategy not in SUPPORTED_STRATEGY_PROFILES:
            return _reject(ticker, "unsupported strategy", strategy=strategy)

        # 1. Fundamental overlay
        fund = run_fundamental_analysis(ticker, strategy=strategy)
        if not fund["passed"]:
            return _reject(ticker, "fundamentals failed", failures=" | ".join(fund.get("failure_reasons", [])))

        # 2. OHLCV + Technical
        df = fetch_ohlcv(ticker, period="3mo", interval="1d")
        if df.empty or len(df) < 30:
            return _reject(ticker, "ohlcv unavailable", rows=len(df))
        df = compute_indicators(df)
        tech = detect_signals(df)
        pattern = detect_patterns(df)
        tech, coerced_buy = _coerce_true_swing_buy(
            tech,
            pattern,
            relative_strength_pct=(_safe_return_pct(df, 20) or 0.0) - float(market_regime.get("benchmark_return20", 0.0) or 0.0),
            market_regime=market_regime,
        ) if strategy == "true_swing" else (tech, False)
        direction = tech.get("direction", "neutral")
        relative_strength_pct = (_safe_return_pct(df, 20) or 0.0) - float(market_regime.get("benchmark_return20", 0.0) or 0.0)
        if direction == "neutral":
            return _reject(
                ticker,
                "technical direction neutral",
                rows=len(df),
                buy_score=tech.get("buy_score"),
                sell_score=tech.get("sell_score"),
                rsi=round(tech.get("rsi", 50), 1),
                macd=round(tech.get("macd", 0), 3),
                macd_sig=round(tech.get("macd_sig", 0), 3),
                pattern_score=round(pattern.get("score", 0), 3),
            )
        if tech.get("score", 0) < MIN_TECH_PATTERN_SCORE and pattern.get("score", 0) < MIN_TECH_PATTERN_SCORE:
            return _reject(
                ticker,
                "weak technical and pattern scores",
                tech_score=round(tech.get("score", 0), 3),
                pattern_score=round(pattern.get("score", 0), 3),
                direction=direction,
            )
        rs_min = TRUE_SWING_RELATIVE_STRENGTH_MIN_PCT if strategy == "true_swing" else RELATIVE_STRENGTH_MIN_PCT
        if direction == "buy" and relative_strength_pct < rs_min:
            return _reject(
                ticker,
                "relative strength too weak for long swing",
                rs=round(relative_strength_pct, 2),
                regime=market_regime.get("label"),
            )
        risk_off_buy_floor = TRUE_SWING_RISK_OFF_BUY_SCORE_MIN if strategy == "true_swing" else 0.6
        if direction == "buy" and market_regime.get("label") == "risk_off" and tech.get("score", 0) < risk_off_buy_floor:
            return _reject(
                ticker,
                "buy rejected in risk-off regime without exceptional strength",
                tech_score=round(tech.get("score", 0), 3),
                rs=round(relative_strength_pct, 2),
                regime=market_regime.get("label"),
            )

        # 3. Current price
        info = fetch_current_price(ticker)
        if not info:
            return _reject(ticker, "current price unavailable")

        # 4. Sentiment
        sentiment = fetch_news_sentiment(ticker)

        # 5. Composite score
        composite, reason, breakdown = compute_composite_score(tech, pattern, sentiment, fund, fii_data)
        if direction == "buy":
            if relative_strength_pct >= RELATIVE_STRENGTH_BONUS_PCT:
                composite += 0.03
                breakdown["rs_bonus"] = 0.03
            else:
                breakdown["rs_bonus"] = 0.0
            if market_regime.get("label") == "cautious":
                composite -= 0.02
                breakdown["regime_adjustment"] = -0.02
            else:
                breakdown["regime_adjustment"] = 0.0
        elif direction == "sell":
            if relative_strength_pct <= -RELATIVE_STRENGTH_BONUS_PCT:
                composite += 0.02
                breakdown["rs_bonus"] = 0.02
            else:
                breakdown["rs_bonus"] = 0.0
            if market_regime.get("label") == "risk_off":
                composite += 0.02
                breakdown["regime_adjustment"] = 0.02
            else:
                breakdown["regime_adjustment"] = 0.0
        if composite < COMPOSITE_MIN_SCORE:
            return _reject(
                ticker,
                "composite score below threshold",
                composite=round(composite, 3),
                technical=breakdown["technical"],
                pattern=breakdown["pattern"],
                sentiment=breakdown["sentiment"],
                fundamental=breakdown["fundamental"],
            )

        # 6. Prices
        entry = float(info.get("price") or tech["entry_price"])
        atr_pct = float(tech.get("atr_pct", 0.0) or 0.0)
        stoploss_pct = min(max(max(STOPLOSS_PCT, atr_pct * ATR_STOPLOSS_MULT), MIN_STOPLOSS_PCT), MAX_STOPLOSS_PCT)
        target_pct = min(max(max(float(tech.get("target_pct", 4.0) or 4.0), TARGET_PCT_MIN), atr_pct * ATR_TARGET_MULT), TARGET_PCT_MAX)
        if direction == "buy":
            target = round(entry * (1 + target_pct / 100), 2)
            stoploss = round(entry * (1 - stoploss_pct / 100), 2)
            entry_low, entry_high = round(entry * 0.995, 2), round(entry * 1.005, 2)
        else:
            target = round(entry * (1 - target_pct / 100), 2)
            stoploss = round(entry * (1 + stoploss_pct / 100), 2)
            entry_low = entry_high = entry

        rr = round(abs(target - entry) / abs(stoploss - entry), 1) if abs(stoploss - entry) > 0 else 0
        if rr < MIN_RR_RATIO:
            return _reject(
                ticker,
                "risk-reward below threshold",
                rr=rr,
                target_pct=round(target_pct, 2),
                stoploss_pct=round(stoploss_pct, 2),
                direction=direction,
            )

        sh = fund.get("shareholding", {}); fi = fund.get("financials", {})
        inst = max(sh.get("institutional_total", 0),
                   sh.get("fii_pct", 0) + sh.get("dii_pct", 0) + sh.get("mf_pct", 0))
        exchange = "NSE" if ".NS" in ticker else "BSE"
        clean = ticker.replace(".NS", "").replace(".BO", "")

        # Global context note
        notes = []
        nasdaq = global_ctx.get("nasdaq", {})
        if info.get("sector") in {"Technology", "Communication Services"} and nasdaq:
            chg = nasdaq.get("change_pct", 0)
            notes.append(f"Nasdaq {chg:+.2f}%")
        crude = global_ctx.get("crude", {})
        if crude and abs(crude.get("change_pct", 0)) > 1:
            notes.append(f"Crude {crude.get('change_pct', 0):+.1f}%")
        usdinr = global_ctx.get("usdinr", {})
        if usdinr: notes.append(f"₹/USD {usdinr.get('value', 84):.2f}")
        notes.append(market_regime.get("summary", ""))
        global_note = " · ".join([n for n in notes if n][:3]) or "Global markets stable"
        reason_bits = [reason, f"RS {relative_strength_pct:+.1f}%", market_regime.get("label", "").replace("_", " ")]
        enriched_reason = " · ".join([bit for bit in reason_bits if bit])
        if strategy == "quality_swing":
            enriched_reason += " · quality overlay"
        elif coerced_buy:
            enriched_reason += " · pattern-led true swing allowance"

        combined_signals = tech.get("signals", []) + pattern.get("patterns", []) + fund.get("signals", [])
        if strategy == "true_swing":
            combined_signals.append("Strategy profile: True Swing")
            combined_signals.extend([f"Caution: {reason}" for reason in fund.get("caution_reasons", [])[:2]])
        else:
            combined_signals.append("Strategy profile: Quality Swing")
        combined_signals.extend([
            f"Market regime: {market_regime.get('label', 'neutral').replace('_', ' ')}",
            f"Relative strength {relative_strength_pct:+.1f}%",
        ])

        recommendation = StockRecommendation(
            ticker=clean, name=info.get("name", clean), exchange=exchange,
            direction=direction, entry_price=entry, entry_low=entry_low,
            entry_high=entry_high, target_price=target, target_pct=round(target_pct, 1),
            stoploss_price=stoploss, stoploss_pct=round(stoploss_pct, 2), rr_ratio=rr,
            confidence_pct=int(composite * 100),
            hold_sessions=f"{HOLD_SESSIONS_MIN}–{HOLD_SESSIONS_MAX} sessions",
            reason=enriched_reason,
            signals=combined_signals,
            global_context=global_note, sector=info.get("sector", "Unknown"),
            market_cap_cr=round((info.get("market_cap", 0) or 0) / 1e7, 0),
            rsi=round(tech.get("rsi", 50), 1), vol_ratio=round(tech.get("vol_ratio", 1), 2),
            sentiment_label=sentiment.get("label", "neutral"),
            sentiment_score=sentiment.get("score", 0),
            promoter_pct=sh.get("promoter_pct", 0),
            debt_to_equity=fi.get("debt_to_equity", 0),
            institutional_pct=round(inst, 1),
            revenue_growth_pct=fi.get("revenue_growth_pct", 0),
            roe_pct=fi.get("roe_pct", 0), pe_ratio=fi.get("pe_ratio") or 0,
            fundamental_summary=fund.get("summary", ""),
            fundamental_signals=fund.get("signals", []),
            regime_label=market_regime.get("label", ""),
            regime_score=market_regime.get("score", 0),
            relative_strength_pct=round(relative_strength_pct, 2),
            atr_pct=round(atr_pct, 2),
            strategy=strategy,
            created_at=datetime.now(IST).isoformat(),
            date=_latest_market_date(df),
        )
        logger.info(
            "Accept %s: strategy=%s direction=%s confidence=%s composite=%.3f tech=%.3f pattern=%.3f rr=%.1f sector=%s",
            ticker,
            strategy,
            direction,
            recommendation.confidence_pct,
            composite,
            tech.get("score", 0),
            pattern.get("score", 0),
            rr,
            recommendation.sector,
        )
        return recommendation
    except Exception as e:
        logger.error(f"analyse_stock({ticker}): {e}", exc_info=True)
        return None


def run_engine(mode: str = "eod", strategy: str = DEFAULT_STRATEGY_PROFILE) -> list:
    if strategy not in SUPPORTED_STRATEGY_PROFILES:
        raise ValueError(f"Unsupported strategy profile: {strategy}")
    logger.info(f"Engine starting — mode={mode}, strategy={strategy}")
    global_ctx = fetch_global_context()
    fii_data   = fetch_fii_dii()
    universe   = screen_universe()
    market_regime = assess_market_regime(universe)
    logger.info(f"Universe: {len(universe)} stocks. Running strategy profile {strategy}...")
    logger.info("Market regime assessment: %s", market_regime.get("summary"))
    candidates = []
    for ticker in universe:
        recommendation = analyse_stock(ticker, fii_data, global_ctx, market_regime, strategy=strategy)
        if recommendation:
            candidates.append(recommendation)
    logger.info(f"Candidates after scoring: {len(candidates)}")
    candidates.sort(key=lambda r: r.confidence_pct, reverse=True)
    final_picks = []; sector_count: dict = {}
    sector_capped = 0
    for rec in candidates:
        sector_key = rec.sector if rec.sector not in UNKNOWN_SECTORS else None
        if sector_key and sector_count.get(sector_key, 0) >= 2:
            sector_capped += 1
            logger.info(f"Skip {rec.ticker}: sector cap reached for {sector_key}")
            continue

        final_picks.append(rec)
        if sector_key:
            sector_count[sector_key] = sector_count.get(sector_key, 0) + 1
        if len(final_picks) >= MAX_PICKS: break
    logger.info(f"Final picks: {len(final_picks)} (strategy={strategy}, candidates={len(candidates)}, sector_capped={sector_capped})")
    save_picks(final_picks, strategy=strategy)
    if len(final_picks) < MIN_PICKS:
        try:
            from utils.alerts import send_alert
            send_alert(
                alert_type="quiet_market",
                ticker="MARKET",
                title="Swing engine kept today selective",
                message=f"Only {len(final_picks)} {strategy.replace('_', ' ')} pick(s) passed the current swing profile. {market_regime.get('summary', 'Market regime cautious.')}",
                priority="low",
            )
        except Exception as exc:
            logger.warning("Quiet-market alert failed: %s", exc)
    return final_picks


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, name TEXT, exchange TEXT, direction TEXT,
            entry_price REAL, entry_low REAL, entry_high REAL,
            target_price REAL, target_pct REAL, stoploss_price REAL,
            stoploss_pct REAL, rr_ratio REAL, confidence_pct INTEGER,
            hold_sessions TEXT, reason TEXT, signals TEXT,
            global_context TEXT, sector TEXT, market_cap_cr REAL,
            rsi REAL, vol_ratio REAL, sentiment_label TEXT, sentiment_score REAL,
            promoter_pct REAL, debt_to_equity REAL, institutional_pct REAL,
            revenue_growth_pct REAL, roe_pct REAL, pe_ratio REAL,
            fundamental_summary TEXT, fundamental_signals TEXT,
            regime_label TEXT, regime_score REAL, relative_strength_pct REAL, atr_pct REAL,
            strategy TEXT DEFAULT 'true_swing',
            created_at TEXT, date TEXT,
            status TEXT DEFAULT 'pending', actual_result_pct REAL,
            entry_triggered_at TEXT, exit_triggered_at TEXT, lifecycle_note TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, name TEXT, exchange TEXT,
            quantity INTEGER, avg_price REAL, added_at TEXT, notes TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS alerts_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, alert_type TEXT, message TEXT, created_at TEXT)""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(picks)").fetchall()}
        migrations = {
            "regime_label": "ALTER TABLE picks ADD COLUMN regime_label TEXT",
            "regime_score": "ALTER TABLE picks ADD COLUMN regime_score REAL DEFAULT 0",
            "relative_strength_pct": "ALTER TABLE picks ADD COLUMN relative_strength_pct REAL DEFAULT 0",
            "atr_pct": "ALTER TABLE picks ADD COLUMN atr_pct REAL DEFAULT 0",
            "strategy": "ALTER TABLE picks ADD COLUMN strategy TEXT DEFAULT 'true_swing'",
            "entry_triggered_at": "ALTER TABLE picks ADD COLUMN entry_triggered_at TEXT",
            "exit_triggered_at": "ALTER TABLE picks ADD COLUMN exit_triggered_at TEXT",
            "lifecycle_note": "ALTER TABLE picks ADD COLUMN lifecycle_note TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)
        conn.commit()

def save_picks(picks, strategy: str = DEFAULT_STRATEGY_PROFILE):
    run_date = picks[0].date if picks else datetime.now(IST).strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        deleted = conn.execute("DELETE FROM picks WHERE date=? AND strategy=?", (run_date, strategy)).rowcount
        logger.info(f"Cleared {deleted} existing picks for {run_date} [{strategy}] before saving latest engine output")
        for p in picks:
            d = p.to_dict()
            d["strategy"] = strategy
            d["status"] = "pending"
            d["actual_result_pct"] = None
            d["entry_triggered_at"] = None
            d["exit_triggered_at"] = None
            d["lifecycle_note"] = ""
            conn.execute(f"INSERT INTO picks ({','.join(d)}) VALUES ({','.join(['?']*len(d))})",
                         list(d.values()))
        conn.commit()

def get_todays_picks(date=None, strategy: str = DEFAULT_STRATEGY_PROFILE):
    if not date: date = datetime.now(IST).strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM picks WHERE date=? AND strategy=? ORDER BY confidence_pct DESC",
            (date, strategy),
        ).fetchall()
    return [dict(r) for r in rows]

def get_pick_history(limit=30, strategy: str = DEFAULT_STRATEGY_PROFILE):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM picks WHERE strategy=? ORDER BY created_at DESC LIMIT ?",
            (strategy, limit),
        ).fetchall()
    return [dict(r) for r in rows]

def update_pick_status(pick_id, status, result_pct=None):
    with sqlite3.connect(DB_PATH) as conn:
        now = datetime.now(IST).isoformat()
        extra = {}
        if status == "open":
            extra["entry_triggered_at"] = now
        elif status in {"target_hit", "stoploss_hit", "expired", "missed_move"}:
            extra["exit_triggered_at"] = now

        set_clause = "status=?, actual_result_pct=?"
        values = [status, result_pct]
        for key, value in extra.items():
            set_clause += f", {key}=?"
            values.append(value)
        values.append(pick_id)
        conn.execute(f"UPDATE picks SET {set_clause} WHERE id=?", values)
        conn.commit()
