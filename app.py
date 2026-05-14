"""
SuperTREX 選股系統 — Streamlit Web App  (v2)

New in v2:
  • 全部台股 (TWSE + TPEx) / 全部美股 (S&P 500)，排除 ETF
  • K線、MACD、RSI 可獨立選擇週期
  • 每個買/賣條件可勾選啟用，並可設定參數
  • 新增「收盤價 > 設定值」條件
  • SuperTREX 改為「5日內出現訊號」，而非整段趨勢期間

Run locally : streamlit run app.py
Deploy free : https://streamlit.io/cloud
"""

from __future__ import annotations

import logging
from datetime import datetime

import streamlit as st

from excel_export import build_excel
from screener import run_screener
from stock_lists import fetch_tw_stocks, fetch_us_stocks

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="SuperTREX 選股系統 v2",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────
#  Cache stock lists (refresh every hour)
# ─────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _load_tw(include_tpex: bool) -> dict[str, str]:
    return fetch_tw_stocks(include_tpex=include_tpex)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_us() -> dict[str, str]:
    return fetch_us_stocks()


# ─────────────────────────────────────────────────────────
#  Sidebar
# ─────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 選股設定")

    # ── 市場選擇 ──────────────────────────────────────────
    st.subheader("① 市場")
    use_tw = st.checkbox("🇹🇼 台股", value=True)
    if use_tw:
        tw_scope = st.radio(
            "台股範圍",
            ["TWSE（上市）", "TWSE + TPEx（上市 + 上櫃）"],
            index=1,
            label_visibility="collapsed",
        )
        include_tpex = "TPEx" in tw_scope
    else:
        include_tpex = False

    use_us = st.checkbox("🇺🇸 美股 (S&P 500)", value=True)

    # ── 週期設定 ──────────────────────────────────────────
    st.divider()
    st.subheader("② K線 & 指標週期")

    kline_opts = {"15分鐘": "15m", "30分鐘": "30m", "1小時": "1h", "日線": "1d"}
    kline_lbl  = st.selectbox("K線週期", list(kline_opts.keys()), index=0)
    kline      = kline_opts[kline_lbl]

    macd_opts  = {"同K線": "same", "45分鐘": "45min", "1.5小時": "90min", "3小時": "180min"}
    macd_lbl   = st.selectbox("MACD 週期", list(macd_opts.keys()), index=1)
    macd_tf    = macd_opts[macd_lbl]

    rsi_opts   = {"同K線": "same", "45分鐘": "45min", "1.5小時": "90min", "3小時": "180min"}
    rsi_lbl    = st.selectbox("RSI 週期", list(rsi_opts.keys()), index=1)
    rsi_tf     = rsi_opts[rsi_lbl]

    # ── 買點條件 ──────────────────────────────────────────
    st.divider()
    st.subheader("③ 買點條件")

    def _row(label: str, default: bool = True, has_val: bool = False,
             val_default: float = 0.0, val_min: float = 0.0,
             val_max: float = 9999.0, val_fmt: str = "%.1f",
             key_chk: str = "", key_val: str = "") -> tuple[bool, float]:
        c1, c2 = st.columns([3, 2])
        chk = c1.checkbox(label, value=default, key=key_chk)
        val = (c2.number_input("", value=val_default, min_value=val_min,
                                max_value=val_max, format=val_fmt,
                                key=key_val, label_visibility="collapsed")
               if has_val else val_default)
        return chk, val

    b_st,  _      = _row("SuperTREX 買點 (5日內)",  key_chk="b_st")
    b_mac, _      = _row("MACD 黃金交叉",            key_chk="b_mac")
    b_rsi, b_rsi_v= _row("RSI >", has_val=True, val_default=50.0,
                          val_min=1.0, val_max=99.0, key_chk="b_rsi", key_val="b_rsi_v")
    b_ma,  _      = _row("收盤 > MA20",              key_chk="b_ma")
    b_vol, b_vol_v= _row("成交量 > 均量 ×", has_val=True, val_default=1.5,
                          val_min=1.0, val_max=10.0, key_chk="b_vol", key_val="b_vol_v")
    b_mp,  b_mp_v = _row("收盤價 >", default=False, has_val=True, val_default=10.0,
                          val_min=0.0, val_max=100000.0, key_chk="b_mp", key_val="b_mp_v")

    buy_enabled = sum([b_st, b_mac, b_rsi, b_ma, b_vol, b_mp])
    buy_min = st.slider(
        "最少符合幾項買點條件",
        min_value=1, max_value=max(buy_enabled, 1),
        value=min(buy_enabled, buy_enabled),
        key="buy_min",
    )

    # ── 賣點條件 ──────────────────────────────────────────
    st.divider()
    st.subheader("④ 賣點條件")

    s_st,  _      = _row("SuperTREX 賣點 (5日內)",  key_chk="s_st")
    s_mac, _      = _row("MACD 死亡交叉",            key_chk="s_mac")
    s_rsi, s_rsi_v= _row("RSI <", has_val=True, val_default=45.0,
                          val_min=1.0, val_max=99.0, key_chk="s_rsi", key_val="s_rsi_v")
    s_ma,  _      = _row("跌破 MA20",                key_chk="s_ma")
    s_mp,  s_mp_v = _row("收盤價 <", default=False, has_val=True, val_default=10.0,
                          val_min=0.0, val_max=100000.0, key_chk="s_mp", key_val="s_mp_v")

    sell_enabled = sum([s_st, s_mac, s_rsi, s_ma, s_mp])
    sell_min = st.slider(
        "最少符合幾項賣點條件",
        min_value=1, max_value=max(sell_enabled, 1),
        value=min(sell_enabled, sell_enabled),
        key="sell_min",
    )


# ─────────────────────────────────────────────────────────
#  Build screener config
# ─────────────────────────────────────────────────────────
cfg = {
    # Timeframes
    "base_interval": kline,
    "macd_tf":       macd_tf,
    "rsi_tf":        rsi_tf,

    # Buy
    "buy_supertrex":       b_st,
    "buy_supertrex_days":  7,
    "buy_macd_golden":     b_mac,
    "buy_rsi":             b_rsi,
    "buy_rsi_threshold":   b_rsi_v,
    "buy_price_above_ma":  b_ma,
    "buy_volume_spike":    b_vol,
    "buy_volume_mult":     b_vol_v,
    "buy_min_price":       b_mp,
    "buy_min_price_value": b_mp_v,
    "buy_min_signals":     buy_min,

    # Sell
    "sell_supertrex":       s_st,
    "sell_supertrex_days":  7,
    "sell_macd_death":      s_mac,
    "sell_rsi":             s_rsi,
    "sell_rsi_threshold":   s_rsi_v,
    "sell_price_below_ma":  s_ma,
    "sell_min_price":       s_mp,
    "sell_min_price_value": s_mp_v,
    "sell_min_signals":     sell_min,
}


# ─────────────────────────────────────────────────────────
#  Main — header + stock count preview
# ─────────────────────────────────────────────────────────
st.title("📈 SuperTREX 選股系統 v2")
st.caption("全市場掃描｜多指標多時框｜可選條件｜Excel 輸出")
st.divider()

# Load stock lists (cached)
tw_dict: dict[str, str] = {}
us_dict: dict[str, str] = {}

if use_tw:
    with st.spinner("載入台股清單…"):
        tw_dict = _load_tw(include_tpex)

if use_us:
    with st.spinner("載入美股清單 (S&P 500)…"):
        us_dict = _load_us()

# Build task list
tasks: list[tuple[str, str, str]] = []
for sid, name in tw_dict.items():
    tasks.append((sid, name, "TW"))
for tkr, name in us_dict.items():
    tasks.append((tkr, name, "US"))

# Info row
c1, c2, c3, c4 = st.columns(4)
c1.metric("台股", f"{len(tw_dict):,} 檔")
c2.metric("美股", f"{len(us_dict):,} 檔")
c3.metric("合計掃描", f"{len(tasks):,} 檔")

# Estimate time
est_sec = max(1, len(tasks) // 15 // 2)
est_str = f"約 {est_sec} 秒" if est_sec < 60 else f"約 {est_sec//60} 分鐘"
c4.metric("預估時間", est_str)

st.divider()

run_btn = st.button(
    "🔍  開始選股",
    type="primary",
    use_container_width=True,
    disabled=(len(tasks) == 0),
)

# ─────────────────────────────────────────────────────────
#  Run screener
# ─────────────────────────────────────────────────────────
if run_btn:
    progress_bar = st.progress(0.0, text="準備中…")
    status_slot  = st.empty()

    def _cb(cur: int, tot: int, label: str) -> None:
        progress_bar.progress(cur / tot, text=f"掃描中 {cur}/{tot} — {label}")

    with st.spinner("運算指標中，請稍候…"):
        try:
            buy_df, sell_df = run_screener(tasks, cfg, progress_callback=_cb)
        except Exception as exc:
            st.error(f"執行錯誤：{exc}")
            st.stop()

    progress_bar.progress(1.0, text="✅ 完成！")
    status_slot.empty()

    st.session_state["buy_df"]   = buy_df
    st.session_state["sell_df"]  = sell_df
    st.session_state["run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")


# ─────────────────────────────────────────────────────────
#  Display results
# ─────────────────────────────────────────────────────────
if "buy_df" in st.session_state:
    buy_df   = st.session_state["buy_df"]
    sell_df  = st.session_state["sell_df"]
    run_time = st.session_state.get("run_time", "")

    st.subheader(f"選股結果　　*{run_time}*")

    def _style(val: object) -> str:
        if val == "✓":
            return "color:#1e6823;font-weight:bold;background:#c6efce"
        if val == "✗":
            return "color:#9c0006;background:#ffc7ce"
        return ""

    tab_b, tab_s = st.tabs([
        f"🟢 買點訊號　{len(buy_df)} 檔",
        f"🔴 賣點訊號　{len(sell_df)} 檔",
    ])

    CHECK_BUY  = {"SuperTREX買點(5日內)", "MACD黃金交叉", "收盤>MA20", "跌破MA20"}
    CHECK_SELL = {"SuperTREX賣點(5日內)", "MACD死亡交叉", "收盤>MA20", "跌破MA20"}

    def _show(df: pd.DataFrame, check_set: set) -> None:
        if df.empty:
            st.info("無符合條件的股票。")
            return
        chk_cols = [c for c in df.columns if c in check_set
                    or c.startswith("RSI") or c.startswith("成交量")
                    or c.startswith("收盤")]
        styled = df.style.map(_style, subset=chk_cols) if chk_cols else df.style
        st.dataframe(styled, use_container_width=True, height=420)

    with tab_b:
        _show(buy_df,  CHECK_BUY  | {f"RSI>{int(b_rsi_v)}", f"成交量>{b_vol_v}x均量",
                                      f"收盤>{b_mp_v}"})
    with tab_s:
        _show(sell_df, CHECK_SELL | {f"RSI<{int(s_rsi_v)}", f"收盤<{s_mp_v}"})

    # ── Download ──────────────────────────────────────────
    st.divider()
    try:
        xlsx = build_excel(buy_df, sell_df, run_time)
        fname = f"SuperTREX_選股_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        st.download_button(
            "📥  下載 Excel 報表",
            data=xlsx, file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception as exc:
        st.warning(f"Excel 產生失敗：{exc}")

# ─────────────────────────────────────────────────────────
st.divider()
st.caption(
    "資料來源：Yahoo Finance（台股 .TW / 美股 S&P 500）｜"
    "15分鐘K棒限最近59曆日｜本工具僅供參考，不構成投資建議。"
)
