"""
screener.py — Flexible stock screener, all conditions configurable.

Config dict keys
────────────────
Timeframes
  base_interval   : '15m' | '30m' | '1h' | '1d'
  macd_tf         : 'same' | '45min' | '90min' | '180min'
  rsi_tf          : 'same' | '45min' | '90min' | '180min'

Buy conditions  (each can be enabled/disabled)
  buy_supertrex        : bool  — SuperTREX buy flip within last N days
  buy_supertrex_days   : int   — look-back window (calendar days, default 7)
  buy_macd_golden      : bool  — MACD golden cross within last 20 bars
  buy_rsi              : bool
  buy_rsi_threshold    : float — default 50
  buy_price_above_ma   : bool  — Close > MA20
  buy_volume_spike     : bool
  buy_volume_mult      : float — default 1.5
  buy_min_price        : bool  — Close > threshold
  buy_min_price_value  : float
  buy_min_signals      : int   — minimum conditions that must pass

Sell conditions (same pattern, prefix 'sell_')
  sell_supertrex / sell_supertrex_days
  sell_macd_death
  sell_rsi / sell_rsi_threshold (default 45)
  sell_price_below_ma
  sell_min_price / sell_min_price_value
  sell_min_signals
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import pandas as pd

from data_fetcher import fetch_tw, fetch_us
from indicators import add_all_indicators

logger = logging.getLogger(__name__)


# ── Signal evaluation ─────────────────────────────────────

def _recent_days(df: pd.DataFrame, calendar_days: int) -> pd.DataFrame:
    cutoff = df.index[-1] - pd.Timedelta(days=calendar_days)
    return df[df.index >= cutoff]


def evaluate_buy(df: pd.DataFrame, cfg: dict) -> dict[str, bool]:
    last    = df.iloc[-1]
    bar20   = df.iloc[-min(20, len(df)):]
    win5d   = _recent_days(df, cfg.get("buy_supertrex_days", 7))
    signals : dict[str, bool] = {}

    if cfg.get("buy_supertrex", True):
        signals["SuperTREX買點(5日內)"] = bool(win5d["st_buy"].any())

    if cfg.get("buy_macd_golden", True):
        signals["MACD黃金交叉"] = bool(bar20["macd_golden"].any())

    if cfg.get("buy_rsi", True):
        thr = cfg.get("buy_rsi_threshold", 50)
        signals[f"RSI>{int(thr)}"] = bool(last.get("rsi", 50) > thr)

    if cfg.get("buy_price_above_ma", True):
        ma  = last.get("ma")
        mp  = cfg.get("ma_period", 20)
        signals[f"收盤>MA{mp}"] = bool(last["Close"] > ma) if pd.notna(ma) else False

    if cfg.get("buy_volume_spike", True):
        mult   = cfg.get("buy_volume_mult", 1.5)
        vol_ma = last.get("vol_ma")
        signals[f"成交量>{mult}x均量"] = (
            bool(last["Volume"] > vol_ma * mult) if pd.notna(vol_ma) else False
        )

    if cfg.get("buy_min_price", False):
        val = cfg.get("buy_min_price_value", 0)
        signals[f"收盤>{val}"] = bool(last["Close"] > val)

    return signals


def evaluate_sell(df: pd.DataFrame, cfg: dict) -> dict[str, bool]:
    last    = df.iloc[-1]
    bar20   = df.iloc[-min(20, len(df)):]
    win5d   = _recent_days(df, cfg.get("sell_supertrex_days", 7))
    signals : dict[str, bool] = {}

    if cfg.get("sell_supertrex", True):
        signals["SuperTREX賣點(5日內)"] = bool(win5d["st_sell"].any())

    if cfg.get("sell_macd_death", True):
        signals["MACD死亡交叉"] = bool(bar20["macd_death"].any())

    if cfg.get("sell_rsi", True):
        thr = cfg.get("sell_rsi_threshold", 45)
        signals[f"RSI<{int(thr)}"] = bool(last.get("rsi", 50) < thr)

    if cfg.get("sell_price_below_ma", True):
        ma  = last.get("ma")
        mp  = cfg.get("ma_period", 20)
        signals[f"跌破MA{mp}"] = bool(last["Close"] < ma) if pd.notna(ma) else False

    if cfg.get("sell_min_price", False):
        val = cfg.get("sell_min_price_value", 0)
        signals[f"收盤<{val}"] = bool(last["Close"] < val)

    return signals


# ── Single-stock analysis ─────────────────────────────────

def _analyze(
    stock_id: str,
    name: str,
    market: str,
    cfg: dict,
) -> dict[str, Any] | None:
    interval = cfg.get("base_interval", "15m")
    fetch_fn = fetch_tw if market == "TW" else fetch_us

    df = fetch_fn(stock_id, interval=interval)
    if df is None:
        return None

    try:
        df = add_all_indicators(
            df,
            base_interval=interval,
            macd_tf=cfg.get("macd_tf",   "same"),
            rsi_tf =cfg.get("rsi_tf",    "same"),
            ma_period=cfg.get("ma_period", 20),
        )
    except Exception as exc:
        logger.warning("Indicator error [%s %s]: %s", market, stock_id, exc)
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    chg  = (
        (float(last["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100
        if float(prev["Close"]) != 0 else 0.0
    )

    buy_sigs  = evaluate_buy(df, cfg)
    sell_sigs = evaluate_sell(df, cfg)

    return {
        "stock_id":   stock_id,
        "name":       name,
        "market":     market,
        "close":      round(float(last["Close"]), 2),
        "change_pct": round(chg, 2),
        "rsi":        round(float(last.get("rsi", 50)), 1),
        "ma":         round(float(last["ma"]), 2)          if pd.notna(last.get("ma"))       else None,
        "macd_hist":  round(float(last["macd_hist"]), 4) if pd.notna(last.get("macd_hist")) else None,
        "supertrex":  "買入區 ▲" if last["st_dir"] == 1 else "賣出區 ▼",
        "buy_sigs":   buy_sigs,
        "sell_sigs":  sell_sigs,
        "buy_count":  sum(buy_sigs.values()),
        "sell_count": sum(sell_sigs.values()),
        "buy_total":  len(buy_sigs),
        "sell_total": len(sell_sigs),
    }


# ── Main entry point ──────────────────────────────────────

def run_screener(
    tasks: list[tuple[str, str, str]],   # (stock_id, name, market)
    cfg: dict,
    progress_callback: Callable[[int, int, str], None] | None = None,
    max_workers: int = 15,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Screen all stocks in tasks list.

    Returns
    -------
    (buy_df, sell_df)
    """
    buy_min  = cfg.get("buy_min_signals",  5)
    sell_min = cfg.get("sell_min_signals", 4)
    total    = len(tasks)
    done     = [0]

    buy_rows : list[dict] = []
    sell_rows: list[dict] = []

    def _wrap(task: tuple) -> dict | None:
        return _analyze(*task, cfg)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(_wrap, t): t for t in tasks}

        for fut in as_completed(fut_map):
            done[0] += 1
            t = fut_map[fut]
            if progress_callback:
                progress_callback(done[0], total, f"{t[2]}:{t[0]}")

            try:
                result = fut.result()
            except Exception as exc:
                logger.warning("Future error: %s", exc)
                continue

            if result is None:
                continue

            base = {
                "代號":      result["stock_id"],
                "名稱":      result["name"],
                "市場":      result["market"],
                "收盤價":    result["close"],
                "漲跌幅(%)": result["change_pct"],
                "RSI":       result["rsi"],
                f"MA{cfg.get('ma_period',20)}": result["ma"],
                "MACD柱狀":  result["macd_hist"],
                "SuperTREX": result["supertrex"],
            }

            if result["buy_count"] >= buy_min:
                row = dict(base)
                for k, v in result["buy_sigs"].items():
                    row[k] = "✓" if v else "✗"
                row["符合條件"] = f"{result['buy_count']}/{result['buy_total']}"
                buy_rows.append(row)

            if result["sell_count"] >= sell_min:
                row = dict(base)
                for k, v in result["sell_sigs"].items():
                    row[k] = "✓" if v else "✗"
                row["符合條件"] = f"{result['sell_count']}/{result['sell_total']}"
                sell_rows.append(row)

    def _to_df(rows: list[dict]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        return (
            pd.DataFrame(rows)
            .sort_values("符合條件", ascending=False)
            .reset_index(drop=True)
        )

    return _to_df(buy_rows), _to_df(sell_rows)
