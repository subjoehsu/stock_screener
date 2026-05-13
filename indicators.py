"""
Technical indicators: SuperTREX, MACD, RSI, MA.

SuperTREX params (from chart): periods=(14,35,70), multipliers=(4,4,10)
MACD params (from chart):      fast=20, slow=120, signal=9
RSI params (from chart):       period=13
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────
#  SuperTrend / SuperTREX
# ─────────────────────────────────────────────────────────

def _supertrend_direction(df: pd.DataFrame, period: int, multiplier: float) -> np.ndarray:
    """
    Compute SuperTrend direction array (+1 = bullish, -1 = bearish).
    Uses Wilder's ATR (RMA) smoothing.
    """
    close = df["Close"].values.astype(float)
    high  = df["High"].values.astype(float)
    low   = df["Low"].values.astype(float)
    n = len(close)

    # True Range
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )

    # Wilder's ATR (RMA): seed with simple average of first `period` bars
    atr = np.zeros(n)
    if n >= period:
        atr[period - 1] = np.mean(tr[1:period]) if period > 1 else tr[0]
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    hl2       = (high + low) / 2.0
    basic_ub  = hl2 + multiplier * atr
    basic_lb  = hl2 - multiplier * atr

    final_ub  = basic_ub.copy()
    final_lb  = basic_lb.copy()
    direction = np.ones(n, dtype=float)   # 1 = bullish (initial assumption)

    for i in range(1, n):
        # Upper band: only tighten downward unless price breaks above
        final_ub[i] = (
            basic_ub[i]
            if (basic_ub[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1])
            else final_ub[i - 1]
        )
        # Lower band: only tighten upward unless price breaks below
        final_lb[i] = (
            basic_lb[i]
            if (basic_lb[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1])
            else final_lb[i - 1]
        )
        # Trend direction
        if direction[i - 1] == 1:          # was bullish → stay bullish unless close < lb
            direction[i] = 1.0 if close[i] >= final_lb[i] else -1.0
        else:                               # was bearish → stay bearish unless close > ub
            direction[i] = -1.0 if close[i] <= final_ub[i] else 1.0

    return direction


def add_supertrex(df: pd.DataFrame) -> pd.DataFrame:
    """
    SuperTREX: majority vote of three SuperTrend instances.
    Configs: (period=14, mult=4), (period=35, mult=4), (period=70, mult=10)

    Adds columns:
      st_dir   : +1 (bullish) or -1 (bearish)
      st_buy   : True on the bar the trend flips to bullish
      st_sell  : True on the bar the trend flips to bearish
    """
    configs = [(14, 4), (35, 4), (70, 10)]
    vote = sum(_supertrend_direction(df, p, m) for p, m in configs)  # range -3..+3

    df = df.copy()
    df["st_dir"]  = np.where(vote > 0, 1, -1)
    prev          = df["st_dir"].shift(1).fillna(0)
    df["st_buy"]  = (df["st_dir"] == 1)  & (prev == -1)
    df["st_sell"] = (df["st_dir"] == -1) & (prev == 1)
    return df


# ─────────────────────────────────────────────────────────
#  MACD
# ─────────────────────────────────────────────────────────

def add_macd(df: pd.DataFrame, fast: int = 20, slow: int = 120, signal: int = 9) -> pd.DataFrame:
    """
    MACD with parameters shown in chart image (fast=20, slow=120, signal=9).

    Adds columns: macd, macd_sig, macd_hist, macd_golden, macd_death
    """
    close    = df["Close"]
    ema_fast = close.ewm(span=fast,   adjust=False).mean()
    ema_slow = close.ewm(span=slow,   adjust=False).mean()
    line     = ema_fast - ema_slow
    sig      = line.ewm(span=signal,  adjust=False).mean()

    df = df.copy()
    df["macd"]         = line
    df["macd_sig"]     = sig
    df["macd_hist"]    = line - sig
    df["macd_golden"]  = (line > sig) & (line.shift(1) <= sig.shift(1))  # golden cross
    df["macd_death"]   = (line < sig) & (line.shift(1) >= sig.shift(1))  # death cross
    return df


# ─────────────────────────────────────────────────────────
#  RSI
# ─────────────────────────────────────────────────────────

def add_rsi(df: pd.DataFrame, period: int = 13) -> pd.DataFrame:
    """
    RSI using Wilder's smoothing (EWM alpha=1/period).
    Period 13 as shown in chart image.

    Adds column: rsi
    """
    delta    = df["Close"].diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)

    df = df.copy()
    df["rsi"] = (100 - 100 / (1 + rs)).fillna(50)
    return df


# ─────────────────────────────────────────────────────────
#  Moving Averages & Volume MA
# ─────────────────────────────────────────────────────────

def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma20"]     = df["Close"].rolling(20).mean()
    df["vol_ma20"] = df["Volume"].rolling(20).mean()
    return df


# ─────────────────────────────────────────────────────────
#  All-in-one
# ─────────────────────────────────────────────────────────

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = add_moving_averages(df)
    df = add_supertrex(df)
    df = add_macd(df)
    df = add_rsi(df)
    return df
