"""
StockSense India — Technical Analysis Engine
Computes all indicators and returns a scored signal for each stock.
"""

import logging
import numpy as np
import pandas as pd
import ta  # Technical Analysis library
from config.settings import (
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    EMA_SHORT, EMA_LONG,
    BOLLINGER_WINDOW, BOLLINGER_STD,
    VOLUME_SPIKE_MULT,
    MACD_SIGNAL_WINDOW,
)

logger = logging.getLogger("stocksense.technical")


# ── Compute All Indicators ────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all technical indicators to the OHLCV DataFrame.
    Requires: Open, High, Low, Close, Volume columns.
    Returns same DataFrame with extra columns added.
    """
    if df.empty or len(df) < 30:
        logger.warning("Insufficient data for indicators (need 30+ rows)")
        return df

    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]

    # ── RSI ──────────────────────────────────────────────────────────────────
    df["rsi"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

    # ── MACD ─────────────────────────────────────────────────────────────────
    macd_obj        = ta.trend.MACD(close=close, window_slow=26,
                                     window_fast=12, window_sign=MACD_SIGNAL_WINDOW)
    df["macd"]      = macd_obj.macd()
    df["macd_sig"]  = macd_obj.macd_signal()
    df["macd_hist"] = macd_obj.macd_diff()

    # ── EMA ──────────────────────────────────────────────────────────────────
    df[f"ema{EMA_SHORT}"] = ta.trend.EMAIndicator(close=close, window=EMA_SHORT).ema_indicator()
    df[f"ema{EMA_LONG}"]  = ta.trend.EMAIndicator(close=close, window=EMA_LONG).ema_indicator()

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb              = ta.volatility.BollingerBands(close=close,
                                                    window=BOLLINGER_WINDOW,
                                                    window_dev=BOLLINGER_STD)
    df["bb_upper"]  = bb.bollinger_hband()
    df["bb_lower"]  = bb.bollinger_lband()
    df["bb_mid"]    = bb.bollinger_mavg()
    df["bb_pct"]    = bb.bollinger_pband()  # 0=lower, 1=upper

    # ── Volume Analysis ───────────────────────────────────────────────────────
    df["vol_ma20"]   = volume.rolling(20).mean()
    df["vol_ratio"]  = volume / df["vol_ma20"]   # > VOLUME_SPIKE_MULT = spike

    # ── ADX (trend strength) ──────────────────────────────────────────────────
    adx_obj   = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
    df["adx"] = adx_obj.adx()
    df["adx_pos"] = adx_obj.adx_pos()
    df["adx_neg"] = adx_obj.adx_neg()

    # ── Stochastic RSI ────────────────────────────────────────────────────────
    stoch_rsi     = ta.momentum.StochRSIIndicator(close=close, window=14)
    df["stoch_k"] = stoch_rsi.stochrsi_k()
    df["stoch_d"] = stoch_rsi.stochrsi_d()

    # ── ATR (volatility / stop-loss sizing) ───────────────────────────────────
    df["atr"] = ta.volatility.AverageTrueRange(high=high, low=low,
                                                close=close, window=14).average_true_range()

    # ── Price position within 52-week range ───────────────────────────────────
    df["52w_high"] = close.rolling(252).max()
    df["52w_low"]  = close.rolling(252).min()
    df["52w_pos"]  = (close - df["52w_low"]) / (df["52w_high"] - df["52w_low"] + 1e-9)

    return df


# ── Detect Signals ────────────────────────────────────────────────────────────

def detect_signals(df: pd.DataFrame) -> dict:
    """
    Analyse the latest row of indicators and return buy/sell signals with scores.
    Returns:
      {
        "direction": "buy" | "sell" | "neutral",
        "score": 0.0–1.0,           # technical score only
        "signals": [...],            # list of triggered signals
        "reason": "...",             # human-readable summary
        "entry_price": float,
        "target_pct": float,
        "atr": float,
      }
    """
    if df.empty or len(df) < 30:
        return _empty_signal()

    row  = df.iloc[-1]   # latest
    prev = df.iloc[-2]   # previous day

    signals_buy  = []
    signals_sell = []
    score_buy    = 0.0
    score_sell   = 0.0

    close = float(row["Close"])

    # ── RSI Signal ────────────────────────────────────────────────────────────
    rsi = float(row.get("rsi", 50))
    if rsi < RSI_OVERSOLD:
        signals_buy.append(f"RSI oversold at {rsi:.1f}")
        score_buy += 0.25
    elif rsi < 45:
        signals_buy.append(f"RSI approaching oversold ({rsi:.1f})")
        score_buy += 0.12
    if rsi > RSI_OVERBOUGHT:
        signals_sell.append(f"RSI overbought at {rsi:.1f}")
        score_sell += 0.25
    elif rsi > 58:
        signals_sell.append(f"RSI elevated ({rsi:.1f})")
        score_sell += 0.12

    # ── MACD Signal ───────────────────────────────────────────────────────────
    macd      = float(row.get("macd", 0))
    macd_sig  = float(row.get("macd_sig", 0))
    prev_macd = float(prev.get("macd", 0))
    prev_sig  = float(prev.get("macd_sig", 0))

    bullish_cross = (prev_macd <= prev_sig) and (macd > macd_sig)
    bearish_cross = (prev_macd >= prev_sig) and (macd < macd_sig)

    if bullish_cross:
        signals_buy.append("MACD bullish crossover confirmed")
        score_buy += 0.20
    elif macd > macd_sig and macd > 0:
        signals_buy.append("MACD above signal line (positive)")
        score_buy += 0.10

    if bearish_cross:
        signals_sell.append("MACD bearish crossover confirmed")
        score_sell += 0.20
    elif macd < macd_sig and macd < 0:
        signals_sell.append("MACD below signal line (negative)")
        score_sell += 0.10

    # ── EMA Trend Signal ──────────────────────────────────────────────────────
    ema20 = float(row.get(f"ema{EMA_SHORT}", close))
    ema50 = float(row.get(f"ema{EMA_LONG}", close))

    if close > ema20 > ema50:
        signals_buy.append(f"Price above EMA{EMA_SHORT} & EMA{EMA_LONG} — uptrend")
        score_buy += 0.15
    elif close > ema20:
        signals_buy.append(f"Price above EMA{EMA_SHORT}")
        score_buy += 0.08
    elif close < ema20 < ema50:
        signals_sell.append(f"Price below EMA{EMA_SHORT} & EMA{EMA_LONG} — downtrend")
        score_sell += 0.15

    # ── Bollinger Band Signal ─────────────────────────────────────────────────
    bb_pct   = float(row.get("bb_pct", 0.5))
    bb_lower = float(row.get("bb_lower", close))
    bb_upper = float(row.get("bb_upper", close))

    if bb_pct < 0.10:
        signals_buy.append(f"Price near lower Bollinger Band — potential reversal")
        score_buy += 0.15
    if bb_pct > 0.90:
        signals_sell.append(f"Price near upper Bollinger Band — stretched")
        score_sell += 0.15

    # ── Volume Spike ──────────────────────────────────────────────────────────
    vol_ratio = float(row.get("vol_ratio", 1.0))
    if vol_ratio >= VOLUME_SPIKE_MULT:
        spike_str = f"Volume spike {vol_ratio:.1f}× average"
        signals_buy.append(spike_str)
        signals_sell.append(spike_str)
        score_buy  += 0.15
        score_sell += 0.10

    # ── ADX Trend Strength ────────────────────────────────────────────────────
    adx = float(row.get("adx", 0))
    if adx > 25:
        adx_pos = float(row.get("adx_pos", 0))
        adx_neg = float(row.get("adx_neg", 0))
        if adx_pos > adx_neg:
            signals_buy.append(f"Strong trend confirmed (ADX {adx:.1f})")
            score_buy += 0.10
        else:
            signals_sell.append(f"Strong downtrend (ADX {adx:.1f})")
            score_sell += 0.10

    # ── Stochastic RSI ────────────────────────────────────────────────────────
    stoch_k = float(row.get("stoch_k", 0.5))
    if stoch_k < 0.20:
        signals_buy.append("Stochastic RSI in oversold zone")
        score_buy += 0.10
    elif stoch_k > 0.80:
        signals_sell.append("Stochastic RSI in overbought zone")
        score_sell += 0.10

    # ── Decide Direction ──────────────────────────────────────────────────────
    atr = float(row.get("atr", close * 0.015))

    if score_buy >= score_sell and score_buy >= 0.35:
        # Estimate target based on ATR and historical resistance
        target_pct = min(max(_estimate_target_pct(df, "buy"), 3.0), 6.0)
        return {
            "direction":   "buy",
            "score":       min(score_buy, 1.0),
            "signals":     signals_buy,
            "reason":      " + ".join(signals_buy[:3]),
            "entry_price": close,
            "target_pct":  target_pct,
            "atr":         atr,
            "rsi":         rsi,
            "vol_ratio":   vol_ratio,
        }
    elif score_sell > score_buy and score_sell >= 0.35:
        target_pct = min(max(_estimate_target_pct(df, "sell"), 3.0), 6.0)
        return {
            "direction":   "sell",
            "score":       min(score_sell, 1.0),
            "signals":     signals_sell,
            "reason":      " + ".join(signals_sell[:3]),
            "entry_price": close,
            "target_pct":  target_pct,
            "atr":         atr,
            "rsi":         rsi,
            "vol_ratio":   vol_ratio,
        }
    else:
        return _empty_signal(close)


def _estimate_target_pct(df: pd.DataFrame, direction: str) -> float:
    """
    Estimate target % move based on recent price swings (ATR-based).
    Looks at the last 20 days of highs/lows to gauge realistic move.
    """
    try:
        recent = df.tail(20)
        avg_range = ((recent["High"] - recent["Low"]) / recent["Close"]).mean() * 100
        # Target is ~2× average daily range, capped at 6%
        return round(min(avg_range * 2.5, 6.0), 1)
    except Exception:
        return 4.0


def _empty_signal(price: float = 0) -> dict:
    return {
        "direction":   "neutral",
        "score":       0.0,
        "signals":     [],
        "reason":      "No strong signal",
        "entry_price": price,
        "target_pct":  0.0,
        "atr":         0.0,
        "rsi":         50,
        "vol_ratio":   1.0,
    }


# ── Pattern Recognition ────────────────────────────────────────────────────────

def detect_patterns(df: pd.DataFrame) -> dict:
    """
    Detect common price patterns in the last 10–20 sessions.
    Returns: {score: 0–1, patterns: [...], direction: buy/sell/neutral}
    """
    if df.empty or len(df) < 20:
        return {"score": 0.0, "patterns": [], "direction": "neutral"}

    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    recent = df.tail(20)

    patterns = []
    score    = 0.0
    direction_votes = {"buy": 0, "sell": 0}

    # ── Support / Resistance Test ─────────────────────────────────────────────
    last_close = float(close.iloc[-1])
    recent_lows  = low.tail(10)
    recent_highs = high.tail(10)

    support    = float(recent_lows.quantile(0.15))
    resistance = float(recent_highs.quantile(0.85))

    dist_to_support    = abs(last_close - support) / last_close
    dist_to_resistance = abs(resistance - last_close) / last_close

    if dist_to_support < 0.015:          # within 1.5% of support
        patterns.append(f"Price at key support zone ₹{support:.1f}")
        score += 0.30
        direction_votes["buy"] += 2

    if dist_to_resistance < 0.015:       # within 1.5% of resistance
        patterns.append(f"Price at key resistance zone ₹{resistance:.1f}")
        score += 0.25
        direction_votes["sell"] += 2

    # ── Gap Analysis ──────────────────────────────────────────────────────────
    if len(df) >= 2:
        prev_close  = float(close.iloc[-2])
        open_today  = float(df["Open"].iloc[-1])
        gap_pct     = (open_today - prev_close) / prev_close * 100

        if gap_pct > 1.0:
            patterns.append(f"Gap-up open (+{gap_pct:.1f}%) — bullish momentum")
            score += 0.20
            direction_votes["buy"] += 1
        elif gap_pct < -1.0:
            patterns.append(f"Gap-down open ({gap_pct:.1f}%) — bearish pressure")
            score += 0.20
            direction_votes["sell"] += 1

    # ── Consecutive Sessions Trend ────────────────────────────────────────────
    last_5 = close.tail(5).tolist()
    up_days   = sum(1 for i in range(1, len(last_5)) if last_5[i] > last_5[i-1])
    down_days = len(last_5) - 1 - up_days

    if up_days >= 3:
        patterns.append(f"{up_days} of last 5 sessions closed higher")
        score += 0.15
        direction_votes["buy"] += 1
    if down_days >= 3:
        patterns.append(f"{down_days} of last 5 sessions closed lower")
        score += 0.15
        direction_votes["sell"] += 1

    # ── 52-Week Proximity ─────────────────────────────────────────────────────
    pos_52w = float(df["52w_pos"].iloc[-1]) if "52w_pos" in df.columns else 0.5
    if pos_52w < 0.15:
        patterns.append("Near 52-week low — potential reversal zone")
        score += 0.20
        direction_votes["buy"] += 1
    elif pos_52w > 0.90:
        patterns.append("Near 52-week high — overbought territory")
        score += 0.15
        direction_votes["sell"] += 1

    dominant = "buy" if direction_votes["buy"] >= direction_votes["sell"] else "sell"
    if direction_votes["buy"] == direction_votes["sell"]:
        dominant = "neutral"

    return {
        "score":      min(score, 1.0),
        "patterns":   patterns,
        "direction":  dominant,
        "support":    support,
        "resistance": resistance,
    }
