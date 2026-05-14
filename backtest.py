"""
backtest.py — Strategy backtesting on historical data.

Supports any interval ('5m', '15m', '30m', '1h', '1d').
  Daily (1d)     : up to 3 years
  Intraday       : up to 59–730 days (yfinance limits)

Config keys used (same as screener cfg, but use the backtest-specific ones
passed from the UI):
  base_interval, macd_tf, rsi_tf, ma_period
  buy_* / sell_* conditions and thresholds
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data_fetcher import fetch_tw, fetch_us
from indicators import INTERVAL_MAX_DAYS, _MINUTES, add_all_indicators

logger = logging.getLogger(__name__)


# ── Precompute rolling signals ────────────────────────────

def _build_signals(df: pd.DataFrame, cfg: dict, interval: str = "1d") -> pd.DataFrame:
    """
    Attach vectorised rolling signal columns.
    SuperTREX window is specified in hours → converted to bars based on interval.
    """
    df = df.copy()

    # Convert hours → number of bars for the rolling window
    bar_mins   = _MINUTES.get(interval, 1440)       # minutes per bar
    buy_bars   = max(1, cfg.get("buy_supertrex_hours",  120) * 60 // bar_mins)
    sell_bars  = max(1, cfg.get("sell_supertrex_hours", 120) * 60 // bar_mins)

    df["_st_buy_roll"]      = df["st_buy"].rolling(buy_bars,  min_periods=1).max().astype(bool)
    df["_st_sell_roll"]     = df["st_sell"].rolling(sell_bars, min_periods=1).max().astype(bool)

    # MACD cross — any event in last 20 bars
    df["_macd_golden_roll"] = df["macd_golden"].rolling(20, min_periods=1).max().astype(bool)
    df["_macd_death_roll"]  = df["macd_death"].rolling(20,  min_periods=1).max().astype(bool)

    # RSI thresholds
    df["_rsi_buy"]  = df["rsi"] > cfg.get("buy_rsi_threshold",  50)
    df["_rsi_sell"] = df["rsi"] < cfg.get("sell_rsi_threshold", 45)

    # Price vs MA
    df["_ma_buy"]  = df["Close"] > df["ma"]
    df["_ma_sell"] = df["Close"] < df["ma"]

    # Volume spike
    mult = cfg.get("buy_volume_mult", 1.5)
    df["_vol_buy"] = df["Volume"] > df["vol_ma"] * mult

    # Optional price floors/ceilings
    df["_minprice_buy"]  = (df["Close"] > cfg.get("buy_min_price_value",  0)
                            if cfg.get("buy_min_price",  False) else pd.Series(True,  index=df.index))
    df["_minprice_sell"] = (df["Close"] < cfg.get("sell_min_price_value", 0)
                            if cfg.get("sell_min_price", False) else pd.Series(False, index=df.index))

    return df


def _buy_score(row: pd.Series, cfg: dict) -> int:
    s = 0
    if cfg.get("buy_supertrex",      True)  and row.get("_st_buy_roll",      False): s += 1
    if cfg.get("buy_macd_golden",    True)  and row.get("_macd_golden_roll",  False): s += 1
    if cfg.get("buy_rsi",            True)  and row.get("_rsi_buy",           False): s += 1
    if cfg.get("buy_price_above_ma", True)  and row.get("_ma_buy",            False): s += 1
    if cfg.get("buy_volume_spike",   True)  and row.get("_vol_buy",           False): s += 1
    if cfg.get("buy_min_price",      False) and row.get("_minprice_buy",      False): s += 1
    return s


def _sell_score(row: pd.Series, cfg: dict) -> int:
    s = 0
    if cfg.get("sell_supertrex",      True)  and row.get("_st_sell_roll",    False): s += 1
    if cfg.get("sell_macd_death",     True)  and row.get("_macd_death_roll",  False): s += 1
    if cfg.get("sell_rsi",            True)  and row.get("_rsi_sell",         False): s += 1
    if cfg.get("sell_price_below_ma", True)  and row.get("_ma_sell",          False): s += 1
    if cfg.get("sell_min_price",      False) and row.get("_minprice_sell",    False): s += 1
    return s


# ── Main entry point ──────────────────────────────────────

def run_backtest(
    stock_id: str,
    market:   str,
    cfg:      dict,
    years:    int  = 3,
    interval: str  = "1d",
) -> tuple[pd.DataFrame, dict[str, Any], go.Figure]:
    """
    Simulate the strategy on historical data.

    Parameters
    ----------
    stock_id : ticker / stock code
    market   : "TW" or "US"
    cfg      : config dict (same schema as screener, supports macd_tf / rsi_tf)
    years    : only used when interval == "1d" (1–3 years)
    interval : "5m" | "15m" | "30m" | "1h" | "1d"

    Returns
    -------
    (trades_df, stats_dict, plotly_figure)
    """
    # ── 1. Determine look-back period ─────────────────────
    if interval == "1d":
        days = years * 365 + 60
    else:
        days = INTERVAL_MAX_DAYS.get(interval, 60)

    # ── 2. Fetch data ─────────────────────────────────────
    fetch_fn = fetch_tw if market == "TW" else fetch_us
    df       = fetch_fn(stock_id, interval=interval, days=days)

    if df is None or df.empty:
        raise ValueError(
            f"無法取得「{stock_id}」的歷史資料（{interval}）。\n"
            "請確認代號正確，並注意分鐘線只有近期資料。"
        )

    # ── 3. Calculate indicators ───────────────────────────
    macd_tf = cfg.get("macd_tf", "same")
    rsi_tf  = cfg.get("rsi_tf",  "same")

    df = add_all_indicators(
        df,
        base_interval=interval,
        macd_tf=macd_tf,
        rsi_tf=rsi_tf,
        ma_period=cfg.get("ma_period", 20),
    )

    # ── 4. Precompute signals ─────────────────────────────
    df = _build_signals(df, cfg, interval=interval)

    buy_min  = cfg.get("buy_min_signals",  3)
    sell_min = cfg.get("sell_min_signals", 2)

    # ── 5. Simulate trades (long-only) ───────────────────
    in_pos      = False
    entry_price = 0.0
    entry_date  = None
    trades: list[dict] = []
    buy_dates:  list = []
    sell_dates: list = []
    buy_prices: list = []
    sell_prices: list = []

    for i in range(len(df)):
        row  = df.iloc[i]
        date = df.index[i]

        if pd.isna(row.get("ma")):   # skip MA warm-up period
            continue

        b = _buy_score(row, cfg)
        s = _sell_score(row, cfg)

        if not in_pos:
            if b >= buy_min:
                in_pos      = True
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
                    "買入日期":   entry_date.strftime("%Y-%m-%d %H:%M") if interval != "1d"
                                  else entry_date.strftime("%Y-%m-%d"),
                    "買入價格":   round(entry_price, 3),
                    "賣出日期":   date.strftime("%Y-%m-%d %H:%M") if interval != "1d"
                                  else date.strftime("%Y-%m-%d"),
                    "賣出價格":   round(exit_price, 3),
                    "報酬率(%)":  round(pnl, 2),
                    "持有天數":   hold_days,
                    "結果":       "獲利 ✓" if pnl > 0 else "虧損 ✗",
                })
                sell_dates.append(date)
                sell_prices.append(exit_price)
                in_pos = False

    # ── 6. Statistics ─────────────────────────────────────
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

    if not trades:
        stats: dict[str, Any] = {
            "交易次數": 0,
            "勝率":     "—",
            "平均報酬": "—",
            "最高報酬": "—",
            "最低報酬": "—",
            "累積報酬": "—",
        }
    else:
        pnls  = [t["報酬率(%)"] for t in trades]
        wins  = sum(1 for p in pnls if p > 0)
        cumul = 1.0
        for p in pnls:
            cumul *= 1 + p / 100
        cumul = (cumul - 1) * 100

        stats = {
            "交易次數": len(trades),
            "勝率":     f"{wins / len(trades) * 100:.1f}%  ({wins}勝/{len(trades) - wins}敗)",
            "平均報酬": f"{np.mean(pnls):+.2f}%",
            "最高報酬": f"{max(pnls):+.2f}%",
            "最低報酬": f"{min(pnls):+.2f}%",
            "累積報酬": f"{cumul:+.2f}%",
        }

    # ── 7. Plotly chart ───────────────────────────────────
    ma_p  = cfg.get("ma_period", 20)
    b_thr = cfg.get("buy_rsi_threshold",  50)
    s_thr = cfg.get("sell_rsi_threshold", 45)

    interval_labels = {
        "5m": "5分鐘", "15m": "15分鐘", "30m": "30分鐘",
        "1h": "1小時", "1d": "日線",
    }
    itv_lbl = interval_labels.get(interval, interval)
    title = (
        f"{stock_id}（{'台股' if market == 'TW' else '美股'}）— "
        f"回測 {itv_lbl}K線"
        + (f"  {years} 年" if interval == "1d" else "  近 59 日")
    )

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.55, 0.22, 0.23],
        subplot_titles=[
            "價格 + MA + 買賣點",
            f"RSI（買>{b_thr} / 賣<{s_thr}）",
            "MACD 柱狀圖",
        ],
    )

    # Price + MA
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"],
        name="收盤價", line=dict(color="#4e79a7", width=1.5),
    ), row=1, col=1)

    if "ma" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ma"],
            name=f"MA{ma_p}",
            line=dict(color="#f28e2b", width=1.2, dash="dot"),
        ), row=1, col=1)

    if buy_dates:
        fig.add_trace(go.Scatter(
            x=buy_dates, y=buy_prices, mode="markers", name="買入",
            marker=dict(symbol="triangle-up", size=11, color="#2ca02c",
                        line=dict(width=1, color="#145a14")),
        ), row=1, col=1)

    if sell_dates:
        fig.add_trace(go.Scatter(
            x=sell_dates, y=sell_prices, mode="markers", name="賣出",
            marker=dict(symbol="triangle-down", size=11, color="#d62728",
                        line=dict(width=1, color="#7a1414")),
        ), row=1, col=1)

    # RSI
    fig.add_trace(go.Scatter(
        x=df.index, y=df["rsi"],
        name="RSI", line=dict(color="#9467bd", width=1.2),
    ), row=2, col=1)
    for lvl, clr in [(b_thr, "rgba(0,160,0,0.5)"),
                     (s_thr, "rgba(200,0,0,0.5)"),
                     (50,    "rgba(128,128,128,0.3)")]:
        fig.add_hline(y=lvl, line_dash="dot", line_color=clr,
                      line_width=1, row=2, col=1)

    # MACD
    if "macd_hist" in df.columns:
        hist   = df["macd_hist"].fillna(0)
        colors = ["#2ca02c" if v >= 0 else "#d62728" for v in hist]
        fig.add_trace(go.Bar(
            x=df.index, y=hist,
            name="MACD柱", marker_color=colors, opacity=0.65,
        ), row=3, col=1)
    if "macd" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd"],
            name="MACD", line=dict(color="#1f77b4", width=1),
        ), row=3, col=1)
    if "macd_sig" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd_sig"],
            name="Signal", line=dict(color="#ff7f0e", width=1),
        ), row=3, col=1)

    fig.update_layout(
        height=700,
        title_text=title,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="價格", row=1, col=1)
    fig.update_yaxes(title_text="RSI",  row=2, col=1, range=[0, 100])
    fig.update_yaxes(title_text="MACD", row=3, col=1)

    return trades_df, stats, fig
