"""
SuperTREX 股票選股系統 — Streamlit Web App

Run locally:  streamlit run app.py
Deploy free:  https://streamlit.io/cloud  (push this folder to GitHub)
"""

from __future__ import annotations

import logging
from datetime import datetime

import streamlit as st

from excel_export import build_excel
from screener import run_screener

logging.basicConfig(level=logging.WARNING)

# ─────────────────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SuperTREX 選股系統",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────
#  Sidebar — settings
# ─────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 選股設定")

    market_choice = st.multiselect(
        "選擇市場",
        options=["TW", "US"],
        default=["TW", "US"],
        format_func=lambda x: "🇹🇼 台股" if x == "TW" else "🇺🇸 美股",
    )

    interval = st.selectbox(
        "K線週期",
        options=["15m", "30m", "1h", "1d"],
        index=0,
        format_func=lambda x: {
            "15m": "15 分鐘",
            "30m": "30 分鐘",
            "1h":  "1 小時",
            "1d":  "日線",
        }[x],
    )

    st.divider()
    st.subheader("買點門檻（共 5 項）")
    buy_min = st.slider(
        "最少符合幾項買點條件",
        min_value=3, max_value=5, value=5,
        help="設 5 = 必須全部符合（最嚴格）",
    )

    st.subheader("賣點門檻（共 4 項）")
    sell_min = st.slider(
        "最少符合幾項賣點條件",
        min_value=2, max_value=4, value=4,
        help="設 4 = 必須全部符合（最嚴格）",
    )

    st.divider()
    with st.expander("📋 選股條件說明"):
        st.markdown("""
**買點條件 (5 項)**
1. SuperTREX = Buy
2. MACD 黃金交叉（近20根K棒）
3. RSI > 50
4. 收盤 > 20MA
5. 成交量 > 均量 × 1.5

**賣點條件 (4 項)**
1. SuperTREX = Sell
2. MACD 死亡交叉（近20根K棒）
3. RSI < 45
4. 跌破 20MA

**SuperTREX 參數**
- (14期, ×4) + (35期, ×4) + (70期, ×10)
- 三組多數決

**MACD 參數** fast=20, slow=120, signal=9

**RSI 參數** period=13
        """)

# ─────────────────────────────────────────────────────────
#  Main content
# ─────────────────────────────────────────────────────────
st.title("📈 SuperTREX 股票選股系統")
st.caption("台股 & 美股 ｜ 多指標自動篩選 ｜ 輸出 Excel 報表")
st.divider()

col_btn, col_mkt, col_intv = st.columns([3, 1, 1])
with col_btn:
    run_btn = st.button(
        "🔍  開始選股",
        type="primary",
        use_container_width=True,
        disabled=len(market_choice) == 0,
    )
with col_mkt:
    st.metric("市場", " + ".join(market_choice) if market_choice else "—")
with col_intv:
    label_map = {"15m": "15分", "30m": "30分", "1h": "1小時", "1d": "日線"}
    st.metric("週期", label_map[interval])

st.divider()

# ─────────────────────────────────────────────────────────
#  Run screener
# ─────────────────────────────────────────────────────────
if run_btn:
    if not market_choice:
        st.error("請至少選擇一個市場！")
        st.stop()

    progress_bar  = st.progress(0.0, text="準備中…")
    status_slot   = st.empty()

    def _progress(current: int, total: int, label: str) -> None:
        pct  = current / total
        progress_bar.progress(pct, text=f"分析中 {current}/{total} — {label}")
        status_slot.caption(f"正在處理：{label}")

    with st.spinner("抓取股價資料 & 計算指標中，請稍候…"):
        try:
            buy_df, sell_df = run_screener(
                markets=market_choice,
                interval=interval,
                buy_min=buy_min,
                sell_min=sell_min,
                progress_callback=_progress,
            )
        except Exception as exc:
            st.error(f"執行錯誤：{exc}")
            st.stop()

    progress_bar.progress(1.0, text="✅ 分析完成！")
    status_slot.empty()

    # Persist results
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

    tab_buy, tab_sell = st.tabs([
        f"🟢 買點訊號　{len(buy_df)} 檔",
        f"🔴 賣點訊號　{len(sell_df)} 檔",
    ])

    def _style_check(val):
        if val == "✓":
            return "color: #1e6823; font-weight: bold; background-color: #c6efce"
        if val == "✗":
            return "color: #9c0006; background-color: #ffc7ce"
        return ""

    with tab_buy:
        if buy_df.empty:
            st.info("目前無符合買點條件的股票。")
        else:
            check_cols = [c for c in buy_df.columns
                          if c in {"SuperTREX=Buy", "MACD黃金交叉", "RSI>50",
                                   "收盤>MA20", "成交量爆量×1.5"}]
            styled = buy_df.style.map(_style_check, subset=check_cols)
            st.dataframe(styled, use_container_width=True, height=420)

    with tab_sell:
        if sell_df.empty:
            st.info("目前無符合賣點條件的股票。")
        else:
            check_cols = [c for c in sell_df.columns
                          if c in {"SuperTREX=Sell", "MACD死亡交叉", "RSI<45", "跌破MA20"}]
            styled = sell_df.style.map(_style_check, subset=check_cols)
            st.dataframe(styled, use_container_width=True, height=420)

    # ── Download button ──────────────────────────────────
    st.divider()
    try:
        excel_bytes = build_excel(buy_df, sell_df, run_time)
        filename    = f"SuperTREX_選股_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        st.download_button(
            label="📥  下載 Excel 報表",
            data=excel_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="secondary",
        )
    except Exception as exc:
        st.warning(f"Excel 產生失敗：{exc}")

# ─────────────────────────────────────────────────────────
#  Footer
# ─────────────────────────────────────────────────────────
st.divider()
st.caption(
    "資料來源：Yahoo Finance（台股 .TW / 美股）｜"
    "15分鐘K棒限最近59個曆日｜"
    "本工具僅供參考，不構成投資建議。"
)
