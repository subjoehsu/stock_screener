"""
backtest.py — Strategy backtesting on historical daily data.

Fetches up to 3 years of daily OHLCV, computes all indicators,
then simulates long-only trades:
  Entry : buy_min_signals buy conditions triggered
  Exit  : sell_min_signals sell conditions triggered

Returns
-------
(trades_df, stats_dict, plotly_figure)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data_fetcher import fetch_tw, fetch_us
from indicators import add_all_indicators

logger = logging.getLogger(__name__)


# ── Precompute rolling signals ────────────────────────────

def _build_signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    Attach precomputed boolean signal columns to df.
    All rolling operations are vectorised — O(n) not O(n²).
    """
    df = df.copy()
    ma_p = cfg.get("ma_period", 20)

    # SuperTREX — rolling window in calendar days (daily bars)
    buy_days  = max(1, cfg.get("buy_supertrex_hours",  120) // 24)
    sell_days = max(1, cfg.get("sell_supertrex_hours", 120) // 24)
    df["_st_buy_roll"]  = df["st_buy"].rolling(buy_days,  min_periods=1).max().astype(bool)
    df["_st_sell_roll"] = df["st_sell"].rolling(sell_days, min_periods=1).max().astype(bool)

    # MACD cross — any golden/death cross in last 20 bars
    df["_macd_golden_roll"] = df["macd_golden"].rolling(20, min_periods=1).max().astype(bool)
    df["_macd_death_roll"]  = df["macd_death"].rolling(20, min_periods=1).max().astype(bool)

    # RSI threshold
    df["_rsi_buy"]  = df["rsi"] > cfg.get("buy_rsi_threshold",  50)
    df["_rsi_sell"] = df["rsi"] < cfg.get("sell_rsi_threshold", 45)

    # Price vs MA
    df["_ma_buy"]  = df["Close"] > df["ma"]
    df["_ma_sell"] = df["Close"] < df["ma"]

    # Volume spike
    mult = cfg.get("buy_volume_mult", 1.5)
    df["_vol_buy"] = df["Volume"] > df["vol_ma"] * mult

    # Min price thresholds
    if cfg.get("buy_min_price", False):
        df["_minprice_buy"] = df["Close"] > cfg.get("buy_min_price_value", 0)
    else:
        df["_minprice_buy"] = True

    if cfg.get("sell_min_price", False):
        df["_minprice_sell"] = df["Close"] < cfg.get("sell_min_price_value", 0)
    else:
        df["_minprice_sell"] = False   # sell min-price is never triggered unless enabled

    return df


def _buy_score(row: pd.Series, cfg: dict) -> int:
    score = 0
    if cfg.get("buy_supertrex",      True) and row["_st_buy_roll"]:       score += 1
    if cfg.get("buy_macd_golden",    True) and row["_macd_golden_roll"]:  score += 1
    if cfg.get("buy_rsi",            True) and row["_rsi_buy"]:           score += 1
    if cfg.get("buy_price_above_ma", True) and row["_ma_buy"]:            score += 1
    if cfg.get("buy_volume_spike",   True) and row["_vol_buy"]:           score += 1
    if cfg.get("buy_min_price",     False) and row["_minprice_buy"]:      score += 1
    return score


def _sell_score(row: pd.Series, cfg: dict) -> int:
    score = 0
    if cfg.get("sell_supertrex",      True) and row["_st_sell_roll"]:     score += 1
    if cfg.get("sell_macd_death",     True) and row["_macd_death_roll"]:  score += 1
    if cfg.get("sell_rsi",            True) and row["_rsi_sell"]:         score += 1
    if cfg.get("sell_price_below_ma", True) and row["_ma_sell"]:          score += 1
    if cfg.get("sell_min_price",     False) and row["_minprice_sell"]:    score += 1
    return score


# ── Main backtest function ────────────────────────────────

def run_backtest(
    stock_id: str,
    market: str,
    cfg: dict,
    years: int = 3,
) -> tuple[pd.DataFrame, dict[str, Any], go.Figure]:
    """
    Simulate strategy on `years` years of daily data.

    Parameters
    ----------
    stock_id : ticker / stock code
    market   : "TW" or "US"
    cfg      : same config dict used by the screener
    years    : 1, 2, or 3

    Returns
    -------
    (trades_df, stats_dict, plotly_figure)
    """
    # ── 1. Fetch data ─────────────────────────────────────
    days     = years * 365 + 60          # small buffer
    fetch_fn = fetch_tw if market == "TW" else fetch_us
    df       = fetch_fn(stock_id, interval="1d", days=days)

    if df is None or df.empty:
        raise ValueError(f"無法取得「{stock_id}」的歷史日線資料，請確認代號正確。")

    # ── 2. Calculate indicators (daily, same-TF) ─────────
    df = add_all_indicators(
        df,
        base_interval="1d",
        macd_tf="same",
        rsi_tf="same",
        ma_period=cfg.get("ma_period", 20),
    )

    # ── 3. Precompute signal columns ──────────────────────
    df = _build_signals(df, cfg)

    buy_min  = cfg.get("buy_min_signals",  3)
    sell_min = cfg.get("sell_min_signals", 2)

    # ── 4. Simulate trades (long-only) ───────────────────
    in_position   = False
    entry_price   = 0.0
    entry_date    = None
    trades: list[dict] = []

    buy_dates:  list = []
    sell_dates: list = []
    buy_prices: list = []
    sell_prices: list = []

    for i in range(len(df)):
        row  = df.iloc[i]
        date = df.index[i]

        # Skip warm-up period (MA not yet computed)
        if pd.isna(row.get("ma")):
            continue

        b = _buy_score(row, cfg)
        s = _sell_score(row, cfg)

        if not in_position:
            if b >= buy_min:
                in_position = True
                entry_price = float(row["Close"])
                entry_date  = date
                buy_dates.append(date)
                buy_prices.append(entry_price)
        else:
            if s >= sell_min:
                exit_price = float(row["Close"])
                pnl        = (exit_price - entry_price) / entry_price * 100
                hold_days  = (date - entry_date).days
                trades.append({
                    "買入日期":   entry_date.strftime("%Y-%m-%d"),
                    "買入價格":   round(entry_price, 3),
                    "賣出日期":   date.strftime("%Y-%m-%d"),
                    "賣出價格":   round(exit_price, 3),
                    "報酬率(%)":  round(pnl, 2),
                    "持有天數":   hold_days,
                    "結果":       "獲利 ✓" if pnl > 0 else "虧損 ✗",
                })
                sell_dates.append(date)
                sell_prices.append(exit_price)
                in_position = False

    # ── 5. Statistics ─────────────────────────────────────
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

    if not trades:
        stats: dict[str, Any] = {
            "交易次數": 0,
            "勝率":     "—",
            "平均報酬": "—",
            "最高報酬": "—",
            "最低報酬": "—",
            "累積報酬": "—",
            "最大單筆虧損": "—",
        }
    else:
        pnls  = [t["報酬率(%)"] for t in trades]
        wins  = sum(1 for p in pnls if p > 0)
        cumul = 1.0
        for p in pnls:
            cumul *= 1 + p / 100
        cumul = (cumul - 1) * 100

        stats = {
            "交易次數":    len(trades),
            "勝率":        f"{wins / len(trades) * 100:.1f}%  （{wins} 勝 / {len(trades) - wins} 敗）",
            "平均報酬":    f"{np.mean(pnls):+.2f}%",
            "最高報酬":    f"{max(pnls):+.2f}%",
            "最低報酬":    f"{min(pnls):+.2f}%",
            "累積報酬":    f"{cumul:+.2f}%",
            "最大單筆虧損": f"{min(pnls):+.2f}%",
        }

    # ── 6. Plotly chart ───────────────────────────────────
    ma_period = cfg.get("ma_period", 20)

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.55, 0.22, 0.23],
        subplot_titles=["價格 + MA + 買賣點", f"RSI（閾值 買>{cfg.get('buy_rsi_threshold',50)} / 賣<{cfg.get('sell_rsi_threshold',45)}）", "MACD 柱狀圖"],
    )

    # ── Price line
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"],
        name="收盤價", line=dict(color="#4e79a7", width=1.5)
    ), row=1, col=1)

    # ── MA line
    if "ma" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ma"],
            name=f"MA{ma_period}",
            line=dict(color="#f28e2b", width=1.2, dash="dot"),
        ), row=1, col=1)

    # ── Buy markers (green triangles up)
    if buy_dates:
        fig.add_trace(go.Scatter(
            x=buy_dates, y=buy_prices,
            mode="markers", name="買入",
            marker=dict(symbol="triangle-up", size=11,
                        color="#2ca02c", line=dict(width=1, color="#145a14")),
        ), row=1, col=1)

    # ── Sell markers (red triangles down)
    if sell_dates:
        fig.add_trace(go.Scatter(
            x=sell_dates, y=sell_prices,
            mode="markers", name="賣出",
            marker=dict(symbol="triangle-down", size=11,
                        color="#d62728", line=dict(width=1, color="#7a1414")),
        ), row=1, col=1)

    # ── RSI
    fig.add_trace(go.Scatter(
        x=df.index, y=df["rsi"],
        name="RSI", line=dict(color="#9467bd", width=1.2)
    ), row=2, col=1)

    for lvl, clr in [
        (cfg.get("buy_rsi_threshold",  50), "rgba(0,160,0,0.5)"),
        (cfg.get("sell_rsi_threshold", 45), "rgba(200,0,0,0.5)"),
        (50,                                "rgba(128,128,128,0.3)"),
    ]:
        fig.add_hline(y=lvl, line_dash="dot", line_color=clr,
                      line_width=1, row=2, col=1)

    # ── MACD histogram + lines
    if "macd_hist" in df.columns:
        hist = df["macd_hist"].fillna(0)
        colors = ["#2ca02c" if v >= 0 else "#d62728" for v in hist]
        fig.add_trace(go.Bar(
            x=df.index, y=hist,
            name="MACD柱", marker_color=colors, opacity=0.65,
        ), row=3, col=1)

    if "macd" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd"],
            name="MACD線", line=dict(color="#1f77b4", width=1)
        ), row=3, col=1)

    if "macd_sig" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd_sig"],
            name="訊號線", line=dict(color="#ff7f0e", width=1)
        ), row=3, col=1)

    fig.update_layout(
        height=700,
        title_text=f"{stock_id}（{'台股' if market == 'TW' else '美股'}）— 回測圖 {years} 年日線",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="價格",  row=1, col=1)
    fig.update_yaxes(title_text="RSI",   row=2, col=1, range=[0, 100])
    fig.update_yaxes(title_text="MACD",  row=3, col=1)

    return trades_df, stats, fig
