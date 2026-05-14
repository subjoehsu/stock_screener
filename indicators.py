"""
indicators.py — Technical indicators with multi-timeframe support.

SuperTREX : (14,×4) + (35,×4) + (70,×10)  majority vote
MACD      : default fast=20, slow=120, signal=9  (from chart)
RSI       : default period=13  (from chart)

Multi-timeframe:
  Pass macd_tf / rsi_tf = '45min' | '90min' | '180min' | 'same'
  The base DataFrame is resampled to the target freq, the indicator is
  calculated there, then forward-filled back onto the base timeframe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Map user-facing strings → pandas resample frequencies
RESAMPLE_FREQ: dict[str, str] = {
    "1m":    "1min",
    "5m":    "5min",
    "15m":   "15min",
    "30m":   "30min",
    "45min": "45min",
    "1h":    "60min",
    "90min": "90min",
    "180min":"180min",
    "1d":    "1D",
}

# Minutes per interval (for coarseness comparison)
_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "45min": 45, "1h": 60, "90min": 90, "180min": 180, "1d": 1440,
}

# Maximum calendar days yfinance allows per interval
INTERVAL_MAX_DAYS: dict[str, int] = {
    "1m":  7,
    "5m":  60,
    "15m": 60,
    "30m": 60,
    "1h":  730,
    "1d":  3650,
}


# ── Helpers ───────────────────────────────────────────────

def resample_ohlcv(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample OHLCV DataFrame to a coarser timeframe."""
    return (
        df.resample(freq)
        .agg({"Open": "first", "High": "max", "Low": "min",
              "Close": "last", "Volume": "sum"})
        .dropna()
    )


def _merge_htf(df_base: pd.DataFrame,
               df_htf: pd.DataFrame,
               cols: list[str]) -> pd.DataFrame:
    """Forward-fill higher-timeframe columns onto the base timeframe index."""
    df_base = df_base.copy()
    present = [c for c in cols if c in df_htf.columns]
    if present:
        merged = df_htf[present].reindex(df_base.index, method="ffill")
        for col in present:
            df_base[col] = merged[col]
    return df_base


def _is_coarser(base_interval: str, target_tf: str) -> bool:
    """Return True only when target_tf is strictly coarser than base."""
    if target_tf in ("same", None, ""):
        return False
    b = _MINUTES.get(base_interval, 0)
    t = _MINUTES.get(target_tf, 0)
    return t > b > 0


# ── SuperTrend / SuperTREX ────────────────────────────────

def _supertrend_dir(df: pd.DataFrame, period: int, multiplier: float) -> np.ndarray:
    """Single SuperTrend direction array (+1 bullish, -1 bearish)."""
    close = df["Close"].values.astype(float)
    high  = df["High"].values.astype(float)
    low   = df["Low"].values.astype(float)
    n     = len(close)

    # True Range
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i]  - close[i - 1]))

    # Wilder's ATR (RMA)
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
    direction = np.ones(n, dtype=float)

    for i in range(1, n):
        final_ub[i] = (basic_ub[i]
                       if (basic_ub[i] < final_ub[i-1] or close[i-1] > final_ub[i-1])
                       else final_ub[i-1])
        final_lb[i] = (basic_lb[i]
                       if (basic_lb[i] > final_lb[i-1] or close[i-1] < final_lb[i-1])
                       else final_lb[i-1])
        if direction[i - 1] == 1:
            direction[i] = 1.0 if close[i] >= final_lb[i] else -1.0
        else:
            direction[i] = -1.0 if close[i] <= final_ub[i] else 1.0

    return direction


def add_supertrex(df: pd.DataFrame) -> pd.DataFrame:
    """
    SuperTREX = majority vote of three SuperTrend instances:
    (14,×4), (35,×4), (70,×10)
    Adds: st_dir (+1/-1), st_buy (flip↑), st_sell (flip↓)
    """
    vote = sum(_supertrend_dir(df, p, m) for p, m in [(14, 4), (35, 4), (70, 10)])
    df   = df.copy()
    df["st_dir"]  = np.where(vote > 0, 1, -1)
    prev          = df["st_dir"].shift(1).fillna(0)
    df["st_buy"]  = (df["st_dir"] == 1)  & (prev == -1)
    df["st_sell"] = (df["st_dir"] == -1) & (prev == 1)
    return df


# ── MACD ─────────────────────────────────────────────────

def add_macd(df: pd.DataFrame,
             fast: int = 20, slow: int = 120, signal: int = 9) -> pd.DataFrame:
    """MACD with chart params (fast=20, slow=120, signal=9)."""
    close = df["Close"]
    line  = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig   = line.ewm(span=signal, adjust=False).mean()

    df = df.copy()
    df["macd"]        = line
    df["macd_sig"]    = sig
    df["macd_hist"]   = line - sig
    df["macd_golden"] = (line > sig) & (line.shift(1) <= sig.shift(1))
    df["macd_death"]  = (line < sig) & (line.shift(1) >= sig.shift(1))
    return df


# ── RSI ──────────────────────────────────────────────────

def add_rsi(df: pd.DataFrame, period: int = 13) -> pd.DataFrame:
    """RSI with Wilder's smoothing, period=13 (from chart)."""
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    df    = df.copy()
    df["rsi"] = (100 - 100 / (1 + rs)).fillna(50)
    return df


# ── Moving averages ───────────────────────────────────────

def add_moving_averages(df: pd.DataFrame, ma_period: int = 20) -> pd.DataFrame:
    """MA period is configurable (default 20). Stored as df['ma'] and df['vol_ma']."""
    df = df.copy()
    df["ma"]     = df["Close"].rolling(ma_period).mean()
    df["vol_ma"] = df["Volume"].rolling(ma_period).mean()
    return df


# ── All-in-one (with multi-TF support) ───────────────────

def add_all_indicators(
    df: pd.DataFrame,
    base_interval: str = "15m",
    macd_tf: str = "same",
    rsi_tf:  str = "same",
    ma_period: int = 20,
) -> pd.DataFrame:
    """
    Calculate all indicators on df.

    Parameters
    ----------
    base_interval : The interval of df (e.g. '15m', '1h', '1d').
    macd_tf       : Timeframe for MACD. 'same' → use base_interval.
    rsi_tf        : Timeframe for RSI.  'same' → use base_interval.
    """
    df = add_moving_averages(df, ma_period=ma_period)
    df = add_supertrex(df)

    # ── MACD ──
    if _is_coarser(base_interval, macd_tf):
        freq = RESAMPLE_FREQ.get(macd_tf, macd_tf)
        try:
            htf = resample_ohlcv(df, freq)
            if len(htf) >= 30:
                htf = add_macd(htf)
                df  = _merge_htf(df, htf,
                                 ["macd", "macd_sig", "macd_hist",
                                  "macd_golden", "macd_death"])
            else:
                df = add_macd(df)
        except Exception:
            df = add_macd(df)
    else:
        df = add_macd(df)

    # ── RSI ──
    if _is_coarser(base_interval, rsi_tf):
        freq = RESAMPLE_FREQ.get(rsi_tf, rsi_tf)
        try:
            htf = resample_ohlcv(df, freq)
            if len(htf) >= 20:
                htf = add_rsi(htf)
                df  = _merge_htf(df, htf, ["rsi"])
            else:
                df = add_rsi(df)
        except Exception:
            df = add_rsi(df)
    else:
        df = add_rsi(df)

    # Safety: ensure rsi column always exists
    if "rsi" not in df.columns:
        df = add_rsi(df)

    return df
