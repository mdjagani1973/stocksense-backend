"""
StockSense India — Recommendation Engine v2
Fundamental hard filter gate runs FIRST before any technical analysis.
"""

import logging
import sqlite3
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional

from config.settings import (
    IST, WEIGHTS, MAX_PICKS, STOPLOSS_PCT, MIN_RR_RATIO,
    HOLD_SESSIONS_MIN, HOLD_SESSIONS_MAX, DB_PATH,
)
from data.fetcher import (
    fetch_ohlcv, fetch_current_price, fetch_news_sentiment,
    fetch_fii_dii, fetch_global_context, screen_universe,
)
from engine.technical import compute_indicators, detect_signals, detect_patterns
from engine.fundamental import run_fundamental_analysis

logger = logging.getLogger("stocksense.engine")


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
    created_at: str = ""; date: str = ""

    def to_dict(self):
        d = asdict(self)
        d["signals"] = " | ".join(self.signals)
        d["fundamental_signals"] = " | ".join(self.fundamental_signals)
        return d


def compute_composite_score(tech, pattern, sentiment, fund, fii_data):
    w = WEIGHTS
    sent_raw = {"positive": 0.8, "neutral": 0.4, "negative": 0.1}.get(
        sentiment.get("label", "neutral"), 0.4)
    composite = (tech.get("score", 0) * w["technical"] +
                 pattern.get("score", 0) * w["pattern"] +
                 sent_raw * w["sentiment"] +
                 fund.get("score", 0.5) * w["fundamental"])
    fii_net = fii_data.get("fii_net_cr", 0)
    direction = tech.get("direction", "neutral")
    if direction == "buy" and fii_net > 500: composite += 0.03
    elif direction == "sell" and fii_net < -500: composite += 0.03

    parts = [p for p in [
        tech.get("reason", ""),
        pattern.get("patterns", [""])[0] if pattern.get("patterns") else "",
        fund.get("summary", ""),
        "Positive news" if sentiment.get("label") == "positive" else "",
        f"FII buying ₹{fii_net:,.0f} Cr" if fii_net > 800 else "",
    ] if p]
    return min(composite, 1.0), " · ".join(parts[:4])


def analyse_stock(ticker: str, fii_data: dict, global_ctx: dict) -> Optional[StockRecommendation]:
    try:
        # 1. FUNDAMENTAL GATE — runs first, reject ~65% of universe here
        fund = run_fundamental_analysis(ticker)
        if not fund["passed"]:
            return None

        # 2. OHLCV + Technical
        df = fetch_ohlcv(ticker, period="3mo", interval="1d")
        if df.empty or len(df) < 30:
            return None
        df = compute_indicators(df)
        tech    = detect_signals(df)
        pattern = detect_patterns(df)
        direction = tech.get("direction", "neutral")
        if direction == "neutral": return None
        if tech.get("score", 0) < 0.30 and pattern.get("score", 0) < 0.30: return None

        # 3. Current price
        info = fetch_current_price(ticker)
        if not info: return None

        # 4. Sentiment
        sentiment = fetch_news_sentiment(ticker)

        # 5. Composite score
        composite, reason = compute_composite_score(tech, pattern, sentiment, fund, fii_data)
        if composite < 0.40: return None

        # 6. Prices
        entry = float(info.get("price") or tech["entry_price"])
        target_pct = tech.get("target_pct", 4.0)
        if direction == "buy":
            target = round(entry * (1 + target_pct / 100), 2)
            stoploss = round(entry * (1 - STOPLOSS_PCT / 100), 2)
            entry_low, entry_high = round(entry * 0.995, 2), round(entry * 1.005, 2)
        else:
            target = round(entry * (1 - target_pct / 100), 2)
            stoploss = round(entry * (1 + STOPLOSS_PCT / 100), 2)
            entry_low = entry_high = entry

        rr = round(abs(target - entry) / abs(stoploss - entry), 1) if abs(stoploss - entry) > 0 else 0
        if rr < MIN_RR_RATIO: return None

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
        global_note = " · ".join(notes[:2]) or "Global markets stable"

        return StockRecommendation(
            ticker=clean, name=info.get("name", clean), exchange=exchange,
            direction=direction, entry_price=entry, entry_low=entry_low,
            entry_high=entry_high, target_price=target, target_pct=round(target_pct, 1),
            stoploss_price=stoploss, stoploss_pct=STOPLOSS_PCT, rr_ratio=rr,
            confidence_pct=int(composite * 100),
            hold_sessions=f"{HOLD_SESSIONS_MIN}–{HOLD_SESSIONS_MAX} sessions",
            reason=reason,
            signals=tech.get("signals", []) + pattern.get("patterns", []) + fund.get("signals", []),
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
            created_at=datetime.now(IST).isoformat(),
            date=datetime.now(IST).strftime("%Y-%m-%d"),
        )
    except Exception as e:
        logger.error(f"analyse_stock({ticker}): {e}", exc_info=True)
        return None


def run_engine(mode: str = "eod") -> list:
    logger.info(f"Engine starting — mode={mode}")
    global_ctx = fetch_global_context()
    fii_data   = fetch_fii_dii()
    universe   = screen_universe()
    logger.info(f"Universe: {len(universe)} stocks. Running fundamental gate first...")
    candidates = [r for t in universe if (r := analyse_stock(t, fii_data, global_ctx))]
    candidates.sort(key=lambda r: r.confidence_pct, reverse=True)
    final_picks = []; sector_count: dict = {}
    for rec in candidates:
        if sector_count.get(rec.sector, 0) < 2:
            final_picks.append(rec)
            sector_count[rec.sector] = sector_count.get(rec.sector, 0) + 1
        if len(final_picks) >= MAX_PICKS: break
    logger.info(f"Final picks: {len(final_picks)}")
    save_picks(final_picks)
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
            created_at TEXT, date TEXT,
            status TEXT DEFAULT 'open', actual_result_pct REAL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, name TEXT, exchange TEXT,
            quantity INTEGER, avg_price REAL, added_at TEXT, notes TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS alerts_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, alert_type TEXT, message TEXT, created_at TEXT)""")
        conn.commit()

def save_picks(picks):
    with sqlite3.connect(DB_PATH) as conn:
        for p in picks:
            d = p.to_dict()
            conn.execute(f"INSERT INTO picks ({','.join(d)}) VALUES ({','.join(['?']*len(d))})",
                         list(d.values()))
        conn.commit()

def get_todays_picks(date=None):
    if not date: date = datetime.now(IST).strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM picks WHERE date=? ORDER BY confidence_pct DESC", (date,)).fetchall()
    return [dict(r) for r in rows]

def get_pick_history(limit=30):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM picks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def update_pick_status(pick_id, status, result_pct=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE picks SET status=?, actual_result_pct=? WHERE id=?",
                     (status, result_pct, pick_id))
        conn.commit()
