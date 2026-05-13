"""
Core screening logic.

Buy  conditions (5 items — all must pass, or user-defined minimum):
  1. SuperTREX direction == Bullish (+1)
  2. MACD golden cross within last CROSS_WINDOW bars
  3. RSI > 50
  4. Close > MA20
  5. Volume > vol_MA20 × 1.5

Sell conditions (4 items):
  1. SuperTREX direction == Bearish (-1)
  2. MACD death cross within last CROSS_WINDOW bars
  3. RSI < 45
  4. Close < MA20
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import pandas as pd

from data_fetcher import fetch_tw, fetch_us
from indicators import add_all_indicators
from stock_lists import TW_STOCKS, TW_STOCK_NAMES, US_STOCKS

logger = logging.getLogger(__name__)

CROSS_WINDOW = 20   # bars to look back for MACD crossover detection (~1 session)


# ─────────────────────────────────────────────────────────
#  Signal checkers
# ─────────────────────────────────────────────────────────

def _buy_signals(df: pd.DataFrame) -> dict[str, bool]:
    last   = df.iloc[-1]
    recent = df.iloc[-CROSS_WINDOW:]

    ma20     = last["ma20"]
    vol_ma20 = last["vol_ma20"]

    return {
        "SuperTREX=Buy":  bool(last["st_dir"] == 1),
        "MACD黃金交叉":    bool(recent["macd_golden"].any()),
        "RSI>50":         bool(last["rsi"] > 50),
        "收盤>MA20":       bool(last["Close"] > ma20)     if pd.notna(ma20)     else False,
        "成交量爆量×1.5":  bool(last["Volume"] > vol_ma20 * 1.5) if pd.notna(vol_ma20) else False,
    }


def _sell_signals(df: pd.DataFrame) -> dict[str, bool]:
    last   = df.iloc[-1]
    recent = df.iloc[-CROSS_WINDOW:]

    ma20 = last["ma20"]

    return {
        "SuperTREX=Sell": bool(last["st_dir"] == -1),
        "MACD死亡交叉":    bool(recent["macd_death"].any()),
        "RSI<45":         bool(last["rsi"] < 45),
        "跌破MA20":        bool(last["Close"] < ma20) if pd.notna(ma20) else False,
    }


# ─────────────────────────────────────────────────────────
#  Single-stock analysis
# ─────────────────────────────────────────────────────────

def _analyze(
    stock_id: str,
    name: str,
    market: str,
    interval: str,
) -> dict[str, Any] | None:
    # Fetch
    fetch_fn = fetch_tw if market == "TW" else fetch_us
    df = fetch_fn(stock_id, interval=interval)
    if df is None:
        return None

    # Indicators
    try:
        df = add_all_indicators(df)
    except Exception as exc:
        logger.warning("Indicator error %s %s: %s", market, stock_id, exc)
        return None

    if df.iloc[-1].isna().any():
        pass  # allow partial NaN — individual checks guard with pd.notna()

    last      = df.iloc[-1]
    prev      = df.iloc[-2] if len(df) > 1 else last
    change_pct = (
        (float(last["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100
        if float(prev["Close"]) != 0 else 0.0
    )

    buy  = _buy_signals(df)
    sell = _sell_signals(df)

    return {
        "stock_id":   stock_id,
        "name":       name,
        "market":     market,
        "close":      round(float(last["Close"]), 2),
        "change_pct": round(change_pct, 2),
        "rsi":        round(float(last["rsi"]), 1),
        "ma20":       round(float(last["ma20"]), 2) if pd.notna(last["ma20"]) else None,
        "macd_hist":  round(float(last["macd_hist"]), 4) if pd.notna(last["macd_hist"]) else None,
        "supertrex":  "買入區 ▲" if last["st_dir"] == 1 else "賣出區 ▼",
        "buy":        buy,
        "sell":       sell,
        "buy_count":  sum(buy.values()),
        "sell_count": sum(sell.values()),
    }


# ─────────────────────────────────────────────────────────
#  Main screener entry point
# ─────────────────────────────────────────────────────────

def run_screener(
    markets: list[str],
    interval: str = "15m",
    buy_min: int = 5,
    sell_min: int = 4,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Screen all stocks in the given markets.

    Returns
    -------
    (buy_df, sell_df) — DataFrames of stocks meeting buy / sell thresholds.
    """
    tasks: list[tuple[str, str, str]] = []
    if "TW" in markets:
        for sid in TW_STOCKS:
            tasks.append((sid, TW_STOCK_NAMES.get(sid, sid), "TW"))
    if "US" in markets:
        for tkr in US_STOCKS:
            tasks.append((tkr, tkr, "US"))

    total    = len(tasks)
    buy_rows : list[dict] = []
    sell_rows: list[dict] = []

    for i, (stock_id, name, market) in enumerate(tasks):
        if progress_callback:
            progress_callback(i + 1, total, f"{market}:{stock_id}")

        result = _analyze(stock_id, name, market, interval)
        if result is None:
            continue

        base_row = {
            "代號":      result["stock_id"],
            "名稱":      result["name"],
            "市場":      result["market"],
            "收盤價":    result["close"],
            "漲跌幅(%)": result["change_pct"],
            "RSI":       result["rsi"],
            "MA20":      result["ma20"],
            "MACD柱狀":  result["macd_hist"],
            "SuperTREX": result["supertrex"],
        }

        if result["buy_count"] >= buy_min:
            row = dict(base_row)
            for k, v in result["buy"].items():
                row[k] = "✓" if v else "✗"
            row["符合條件"] = f"{result['buy_count']}/5"
            buy_rows.append(row)

        if result["sell_count"] >= sell_min:
            row = dict(base_row)
            for k, v in result["sell"].items():
                row[k] = "✓" if v else "✗"
            row["符合條件"] = f"{result['sell_count']}/4"
            sell_rows.append(row)

    def _to_df(rows: list[dict]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df.sort_values("符合條件", ascending=False)
        return df.reset_index(drop=True)

    return _to_df(buy_rows), _to_df(sell_rows)
