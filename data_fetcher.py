"""
Data fetching module.

Primary source : Yahoo Finance (yfinance) — supports both US tickers and
                 Taiwan tickers with ".TW" suffix (e.g. "2330.TW").
Optional source: FinMind — Taiwan daily OHLCV (requires API token for
                 higher rate limits; leave token blank for free tier).

Yahoo Finance 15-minute history is limited to the last ~60 calendar days,
which gives ~900-1500 bars — more than enough for all indicators.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from indicators import INTERVAL_MAX_DAYS

logger = logging.getLogger(__name__)

# Column names yfinance may return (handle both old and new versions)
_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns returned by yfinance when downloading one ticker."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_yfinance(
    ticker: str,
    interval: str = "15m",
    days: int = 59,
) -> pd.DataFrame | None:
    """
    Download OHLCV data from Yahoo Finance.

    Parameters
    ----------
    ticker   : Yahoo Finance ticker symbol (e.g. "AAPL" or "2330.TW")
    interval : "15m" | "30m" | "1h" | "1d"
    days     : look-back window in calendar days
               (max 59 for intraday; up to 1095 for "1d")

    Returns
    -------
    DataFrame with columns [Open, High, Low, Close, Volume], or None on failure.
    """
    end     = datetime.now()
    max_d   = INTERVAL_MAX_DAYS.get(interval, 60)
    start   = end - timedelta(days=min(days, max_d))

    try:
        raw = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:
        logger.warning("yfinance download failed for %s: %s", ticker, exc)
        return None

    if raw is None or raw.empty:
        return None

    df = _flatten_columns(raw)

    # Keep only required columns
    missing = [c for c in _OHLCV if c not in df.columns]
    if missing:
        logger.warning("Missing columns %s for %s", missing, ticker)
        return None

    df = df[_OHLCV].dropna()

    # Remove timezone info from index for compatibility
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # Need at least 130 bars for MACD(slow=120) warm-up
    if len(df) < 130:
        logger.info("Not enough data for %s (%d bars)", ticker, len(df))
        return None

    return df


# ── Taiwan stocks ─────────────────────────────────────────

def fetch_tw(stock_id: str, interval: str = "15m", days: int = 59) -> pd.DataFrame | None:
    """
    Fetch a Taiwan stock via Yahoo Finance.

    stock_id can be:
      • A raw code    e.g. "2330"     → tries 2330.TW first, then 2330.TWO
      • A full ticker e.g. "2330.TW"  → used directly (上市)
                          "6230.TWO"  → used directly (上櫃)
    """
    if "." in stock_id:
        # Already carries the exchange suffix — use as-is
        return fetch_yfinance(stock_id, interval=interval, days=days)
    # Raw code: try 上市 (.TW) first, fall back to 上櫃 (.TWO)
    df = fetch_yfinance(f"{stock_id}.TW", interval=interval, days=days)
    if df is None:
        df = fetch_yfinance(f"{stock_id}.TWO", interval=interval, days=days)
    return df


# ── US stocks ─────────────────────────────────────────────

def fetch_us(ticker: str, interval: str = "15m", days: int = 59) -> pd.DataFrame | None:
    """Fetch a US stock using Yahoo Finance."""
    return fetch_yfinance(ticker, interval=interval, days=days)


# ── FinMind (optional, Taiwan daily) ──────────────────────

def fetch_finmind_daily(
    stock_id: str,
    api_token: str = "",
    days: int = 365,
) -> pd.DataFrame | None:
    """
    Fetch Taiwan daily OHLCV data from FinMind.
    Requires: pip install FinMind
    Returns None silently if FinMind is not installed.
    """
    try:
        from FinMind.data import DataLoader  # type: ignore
    except ImportError:
        logger.info("FinMind not installed; skipping.")
        return None

    try:
        dl = DataLoader()
        if api_token:
            dl.login(api_token=api_token)

        end   = datetime.now()
        start = end - timedelta(days=days)
        raw   = dl.taiwan_stock_daily(
            stock_id=stock_id,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        if raw is None or raw.empty:
            return None

        df = raw.rename(columns={
            "date":   "Date",
            "open":   "Open",
            "max":    "High",
            "min":    "Low",
            "close":  "Close",
            "Trading_Volume": "Volume",
        })
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        df = df[_OHLCV].dropna()
        return df if len(df) >= 130 else None

    except Exception as exc:
        logger.warning("FinMind fetch failed for %s: %s", stock_id, exc)
        return None
