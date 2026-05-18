"""
SuperTREX 選股系統 — Streamlit Web App  (v5)

v5 changes:
  • 盤後自動選股：台股 14:00 / 美股 08:00（台北時間）自動觸發
  • 市場狀態面板：顯示盤後資料就緒狀況與下次更新倒數
  • Session-key 快取失效：盤後 session key 改變時自動重抓股票清單

Run locally : streamlit run app.py
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import streamlit as st

from backtest import run_backtest
from excel_export import build_excel
from gdrive import (
    GDriveManager, google_packages_available,
    build_manager_from_any_source, save_credentials_to_file,
)
from market_hours import market_status, combined_scan_key, tw_session_key, us_session_key
from scan_history import save_scan, list_scans, load_xlsx
from screener import run_screener
from stock_lists import fetch_tw_stocks, fetch_us_stocks, DJIA, NASDAQ100

# ── streamlit-autorefresh (optional) ──────────────────────
try:
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
    _AUTOREFRESH_OK = True
except ImportError:
    _AUTOREFRESH_OK = False

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="SuperTREX 選股系統 v5",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────
#  Shared option maps (used in both sidebar and backtest tab)
# ─────────────────────────────────────────────────────────
KLINE_OPTS: dict[str, str] = {
    "5分鐘":  "5m",
    "15分鐘": "15m",
    "30分鐘": "30m",
    "1小時":  "1h",
    "日線":   "1d",
}
MACD_OPTS: dict[str, str] = {
    "同K線":   "same",
    "5分鐘":   "5m",
    "15分鐘":  "15m",
    "45分鐘":  "45min",
    "1.5小時": "90min",
    "3小時":   "180min",
}
RSI_OPTS: dict[str, str] = {
    "同K線":   "same",
    "5分鐘":   "5m",
    "15分鐘":  "15m",
    "45分鐘":  "45min",
    "1.5小時": "90min",
    "3小時":   "180min",
}

# ─────────────────────────────────────────────────────────
#  Cache stock lists
#  session_key changes after market close → forces re-fetch
# ─────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _load_tw(include_tpex: bool, session_key: str = "") -> dict[str, str]:
    """session_key is used only to bust the cache; unused inside the fn."""
    return fetch_tw_stocks(include_tpex=include_tpex)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_us(sp500: bool, nasdaq: bool, djia: bool, include_all: bool,
             session_key: str = "") -> dict[str, str]:
    """session_key is used only to bust the cache; unused inside the fn."""
    return fetch_us_stocks(
        include_sp500=sp500,
        include_nasdaq=nasdaq,
        include_djia=djia,
        include_all=include_all,
    )


# ─────────────────────────────────────────────────────────
#  Helper: render a checkbox + optional number input row
# ─────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────
#  Sidebar — screener settings
# ─────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 選股設定")

    # ── ① 市場 ────────────────────────────────────────────
    st.subheader("① 市場")
    use_tw = st.checkbox("🇹🇼 台股", value=True)
    if use_tw:
        tw_scope     = st.radio(
            "台股範圍",
            ["TWSE（上市）", "TWSE + TPEx（上市 + 上櫃）"],
            index=1, label_visibility="collapsed",
        )
        include_tpex = "TPEx" in tw_scope
    else:
        include_tpex = False

    use_us = st.checkbox("🇺🇸 美股", value=True)
    if use_us:
        use_all_us = st.checkbox(
            "全部美股（~5 000 檔，需 10–15 分）",
            value=False,
            help="NASDAQ + NYSE 完整清單，適合日線掃描。",
        )
        if not use_all_us:
            use_sp500  = st.checkbox("S&P 500（約 500 檔）",     value=True)
            use_nasdaq = st.checkbox("NASDAQ-100（約 100 檔）",  value=True)
            use_djia   = st.checkbox("道瓊工業（30 檔）",         value=True)
        else:
            use_sp500 = use_nasdaq = use_djia = False
    else:
        use_all_us = use_sp500 = use_nasdaq = use_djia = False

    # ── ② K線 & 指標週期 ──────────────────────────────────
    st.divider()
    st.subheader("② K線 & 指標週期")

    kline_lbl = st.selectbox("K線週期", list(KLINE_OPTS.keys()), index=1,   # 預設 15分鐘
                              key="sc_kline")
    kline     = KLINE_OPTS[kline_lbl]

    macd_lbl  = st.selectbox("MACD 週期", list(MACD_OPTS.keys()), index=2,  # 預設 15分鐘
                              key="sc_macd")
    macd_tf   = MACD_OPTS[macd_lbl]

    rsi_lbl   = st.selectbox("RSI 週期",  list(RSI_OPTS.keys()),  index=2,  # 預設 15分鐘
                              key="sc_rsi")
    rsi_tf    = RSI_OPTS[rsi_lbl]

    ma_period = st.number_input(
        "MA 週期（均線天數）", min_value=5, max_value=250, value=20, step=1,
        help="影響「收盤>MA」與「成交量均量」條件，預設20",
        key="sc_ma",
    )

    # ── ③ 買點條件 ────────────────────────────────────────
    st.divider()
    st.subheader("③ 買點條件")

    b_st,  _       = _row("SuperTREX 買點",        key_chk="b_st")
    b_st_h         = st.number_input(
        "  ↳ 窗口（小時）", min_value=1, max_value=720, value=5, step=1,
        key="b_st_h", help="5h = 買點出現於近 5 小時內；120h ≈ 5 交易日",
    )
    b_mac, _       = _row("MACD 黃金交叉",          key_chk="b_mac")
    b_rsi, b_rsi_v = _row("RSI >", has_val=True, val_default=50.0,
                           val_min=1.0, val_max=99.0,
                           key_chk="b_rsi", key_val="b_rsi_v")
    b_ma,  _       = _row(f"收盤 > MA{int(ma_period)}", key_chk="b_ma")
    b_vol, b_vol_v = _row("成交量 > 均量 ×", has_val=True, val_default=1.5,
                           val_min=1.0, val_max=10.0,
                           key_chk="b_vol", key_val="b_vol_v")
    b_mp,  b_mp_v  = _row("收盤價 >", default=True, has_val=True, val_default=15.0,
                           val_min=0.0, val_max=100000.0,
                           key_chk="b_mp", key_val="b_mp_v")

    buy_enabled = sum([b_st, b_mac, b_rsi, b_ma, b_vol, b_mp])
    buy_min     = st.slider(
        "最少符合幾項買點條件",
        min_value=1, max_value=max(buy_enabled, 1),
        value=min(buy_enabled, buy_enabled), key="buy_min",
    )

    # ── ④ 賣點條件 ────────────────────────────────────────
    st.divider()
    st.subheader("④ 賣點條件")

    s_st,  _       = _row("SuperTREX 賣點",         key_chk="s_st")
    s_st_h         = st.number_input(
        "  ↳ 窗口（小時）", min_value=1, max_value=720, value=5, step=1,
        key="s_st_h", help="5h = 賣點出現於近 5 小時內",
    )
    s_mac, _       = _row("MACD 死亡交叉",           key_chk="s_mac")
    s_rsi, s_rsi_v = _row("RSI <", has_val=True, val_default=45.0,
                           val_min=1.0, val_max=99.0,
                           key_chk="s_rsi", key_val="s_rsi_v")
    s_ma,  _       = _row(f"跌破 MA{int(ma_period)}", key_chk="s_ma")
    s_mp,  s_mp_v  = _row("收盤價 <", default=True, has_val=True, val_default=15.0,
                           val_min=0.0, val_max=100000.0,
                           key_chk="s_mp", key_val="s_mp_v")

    sell_enabled = sum([s_st, s_mac, s_rsi, s_ma, s_mp])
    sell_min     = st.slider(
        "最少符合幾項賣點條件",
        min_value=1, max_value=max(sell_enabled, 1),
        value=min(sell_enabled, sell_enabled), key="sell_min",
    )

    # ── ⑤ 盤後資料狀態 ────────────────────────────────────
    st.divider()
    st.subheader("⑤ 盤後資料狀態")

    mkt = market_status()
    st.caption(f"🕐 現在時間：{mkt['now_str']}")

    _tw_col, _us_col = st.columns(2)
    with _tw_col:
        st.markdown(f"{mkt['tw_icon']} {mkt['tw_msg']}")
    with _us_col:
        st.markdown(f"{mkt['us_icon']} {mkt['us_msg']}")

    # ── ⑥ Google Drive 同步 ────────────────────────────────
    st.divider()
    st.subheader("⑥ Google Drive 同步")

    # ── 連線狀態 ──────────────────────────────────────────
    _gdm: GDriveManager | None = st.session_state.get("gdrive_mgr")
    _gfolder: str              = st.session_state.get("gdrive_folder_id", "")
    _gconn: bool               = st.session_state.get("gdrive_connected", False)

    if _gconn and _gdm:
        _guser = st.session_state.get("gdrive_user", "")
        st.success(f"✅ 已連結：{_guser}")
        if _gfolder:
            st.caption(f"同步資料夾 ID：`{_gfolder}`")
        if st.button("🔌 中斷連線", key="gdrive_disconnect"):
            for k in ("gdrive_mgr","gdrive_connected","gdrive_user",
                      "gdrive_folder_id","gdrive_creds"):
                st.session_state.pop(k, None)
            st.rerun()
    else:
        st.info("尚未連結 Google Drive")

        if not google_packages_available():
            st.warning(
                "⚠️ Google 套件未安裝。\n\n"
                "請確認 `requirements.txt` 含有：\n"
                "```\ngoogle-auth>=2.22.0\n"
                "google-api-python-client>=2.100.0\n```"
            )
        else:
            with st.expander("🔧 設定說明", expanded=False):
                st.markdown(
                    """
**步驟：**
1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立/選取專案 → 搜尋啟用 **Google Drive API**
3. IAM → **服務帳戶** → 建立 → 下載 **JSON 金鑰**
4. 在 Google Drive 建立資料夾，將服務帳戶的 `client_email` 加入**編輯者**
5. 複製資料夾網址最後的 **資料夾 ID**

> Streamlit Cloud 部署：將 JSON 金鑰內容貼入 Secrets → `[gdrive]` 區段
                    """.strip()
                )

            _creds_file = st.file_uploader(
                "上傳 Service Account JSON 金鑰",
                type="json",
                key="gdrive_upload",
                help="從 Google Cloud Console 下載的服務帳戶 JSON 金鑰檔",
            )
            _creds_text = st.text_area(
                "或直接貼上 JSON 內容",
                height=100,
                key="gdrive_paste",
                placeholder='{"type":"service_account","project_id":"..."}',
            )
            _folder_id_input = st.text_input(
                "Google Drive 資料夾 ID",
                key="gdrive_folder_input",
                placeholder="1aBcDeFgHiJkLmNo...",
                help="資料夾網址最後一段，如 /folders/1aBcDeFg…",
            )

            if st.button("🔗 連結 Google Drive", key="gdrive_connect_btn",
                         type="primary"):
                _raw_creds: dict | None = None
                if _creds_file:
                    try:
                        import json as _json
                        _raw_creds = _json.loads(
                            _creds_file.read().decode("utf-8")
                        )
                    except Exception as _e:
                        st.error(f"JSON 解析失敗：{_e}")
                elif _creds_text.strip():
                    try:
                        import json as _json
                        _raw_creds = _json.loads(_creds_text.strip())
                    except Exception as _e:
                        st.error(f"JSON 解析失敗：{_e}")

                if _raw_creds:
                    try:
                        _test_mgr = GDriveManager(_raw_creds)
                        _ok, _info = _test_mgr.test_connection()
                        if _ok:
                            _folder = _folder_id_input.strip()
                            st.session_state["gdrive_mgr"]       = _test_mgr
                            st.session_state["gdrive_creds"]     = _raw_creds
                            st.session_state["gdrive_connected"] = True
                            st.session_state["gdrive_user"]      = _info
                            st.session_state["gdrive_folder_id"] = _folder
                            save_credentials_to_file(_raw_creds)  # local dev cache
                            st.success(f"✅ 連結成功：{_info}")
                            st.rerun()
                        else:
                            st.error(f"授權失敗：{_info}")
                    except Exception as _e:
                        st.error(f"連線錯誤：{_e}")
                else:
                    st.warning("請上傳 JSON 金鑰檔或貼上 JSON 內容")

        # Try auto-connect from secrets / local file on first load
        if not _gconn and google_packages_available():
            if "gdrive_auto_tried" not in st.session_state:
                st.session_state["gdrive_auto_tried"] = True
                _auto_mgr, _auto_info = build_manager_from_any_source()
                if _auto_mgr:
                    st.session_state["gdrive_mgr"]       = _auto_mgr
                    st.session_state["gdrive_connected"] = True
                    st.session_state["gdrive_user"]      = _auto_info
                    st.session_state["gdrive_folder_id"] = ""
                    st.rerun()


# ─────────────────────────────────────────────────────────
#  Screener config (from sidebar)
# ─────────────────────────────────────────────────────────
cfg = {
    "base_interval":       kline,
    "macd_tf":             macd_tf,
    "rsi_tf":              rsi_tf,
    "ma_period":           int(ma_period),
    "buy_supertrex":       b_st,
    "buy_supertrex_hours": int(b_st_h),
    "buy_macd_golden":     b_mac,
    "buy_rsi":             b_rsi,
    "buy_rsi_threshold":   b_rsi_v,
    "buy_price_above_ma":  b_ma,
    "buy_volume_spike":    b_vol,
    "buy_volume_mult":     b_vol_v,
    "buy_min_price":       b_mp,
    "buy_min_price_value": b_mp_v,
    "buy_min_signals":     buy_min,
    "sell_supertrex":       s_st,
    "sell_supertrex_hours": int(s_st_h),
    "sell_macd_death":      s_mac,
    "sell_rsi":             s_rsi,
    "sell_rsi_threshold":   s_rsi_v,
    "sell_price_below_ma":  s_ma,
    "sell_min_price":       s_mp,
    "sell_min_price_value": s_mp_v,
    "sell_min_signals":     sell_min,
}


# ─────────────────────────────────────────────────────────
#  Main area — two tabs
# ─────────────────────────────────────────────────────────
st.title("📈 SuperTREX 選股系統 v5")
st.caption("全市場掃描｜多指標多時框｜可選條件｜策略回測｜Excel 輸出｜盤後自動更新")
st.divider()

tab_scan, tab_bt = st.tabs(["🔍 選股掃描", "📊 策略回測"])


# ═════════════════════════════════════════════════════════
#  TAB 1 — Screener
# ═════════════════════════════════════════════════════════
with tab_scan:
    # ── Session keys for cache-busting after market close ──
    _tw_skey  = tw_session_key()    # e.g. "TW-2025-05-14-post"
    _us_skey  = us_session_key()    # e.g. "US-2025-05-14-post"
    _scan_key = combined_scan_key()

    # Load stock lists (session_key busts cache when market closes)
    tw_dict: dict[str, str] = {}
    us_dict: dict[str, str] = {}

    if use_tw:
        with st.spinner("載入台股清單…"):
            tw_dict = _load_tw(include_tpex, session_key=_tw_skey)

    if use_us and (use_all_us or use_sp500 or use_nasdaq or use_djia):
        msg = "載入全部美股清單（~5 000 檔）…" if use_all_us else "載入美股清單…"
        with st.spinner(msg):
            us_dict = _load_us(use_sp500, use_nasdaq, use_djia, use_all_us,
                               session_key=_us_skey)

    tasks: list[tuple[str, str, str]] = (
        [(sid, n, "TW") for sid, n in tw_dict.items()] +
        [(tkr, n, "US") for tkr, n in us_dict.items()]
    )

    # Info metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("台股", f"{len(tw_dict):,} 檔")
    c2.metric("美股", f"{len(us_dict):,} 檔")
    c3.metric("合計掃描", f"{len(tasks):,} 檔")
    est_sec = max(1, len(tasks) // 15 // 2)
    c4.metric("預估時間",
              f"約 {est_sec} 秒" if est_sec < 60 else f"約 {est_sec // 60} 分鐘")

    if use_all_us:
        st.info("⚠️ 全部美股模式啟用：掃描 5 000+ 檔需 10–15 分鐘，建議搭配「日線」K線以加速。")

    st.caption(
        "📌 說明：掃描結果只顯示**符合最低條件門檻**的股票。"
        "美股因流動性差異，部分小型股可能無分鐘線資料而自動跳過。"
        "資料來源為 Yahoo Finance 當天最新盤後資料。"
    )
    st.divider()

    run_btn = st.button(
        "🔍  開始選股", type="primary",
        use_container_width=True, disabled=(len(tasks) == 0),
    )

    if run_btn:
        progress_bar = st.progress(0.0, text="準備中…")
        status_slot  = st.empty()

        def _cb(cur: int, tot: int, label: str) -> None:
            progress_bar.progress(cur / tot, text=f"掃描中 {cur}/{tot} — {label}")

        with st.spinner("運算指標中，請稍候…"):
            try:
                buy_df, sell_df, scan_stats = run_screener(tasks, cfg, progress_callback=_cb)
            except Exception as exc:
                st.error(f"執行錯誤：{exc}")
                st.stop()

        progress_bar.progress(1.0, text="✅ 完成！")
        status_slot.empty()
        _run_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        st.session_state["buy_df"]    = buy_df
        st.session_state["sell_df"]   = sell_df
        st.session_state["scan_stats"] = scan_stats
        st.session_state["run_time"]  = _run_time

        # ── Auto-save to history (local + GDrive) ─────────
        _cfg_summary = {
            "kline":    cfg.get("base_interval"),
            "macd_tf":  cfg.get("macd_tf"),
            "rsi_tf":   cfg.get("rsi_tf"),
            "buy_min":  cfg.get("buy_min_signals"),
            "sell_min": cfg.get("sell_min_signals"),
        }
        _gdrive_mgr    = st.session_state.get("gdrive_mgr")
        _gdrive_folder = st.session_state.get("gdrive_folder_id", "")
        try:
            _sid = save_scan(
                buy_df, sell_df, scan_stats,
                _run_time, _scan_key, _cfg_summary,
                gdrive_mgr=_gdrive_mgr,
                gdrive_folder_id=_gdrive_folder,
            )
            st.session_state["last_saved_scan_id"] = _sid
            if _gdrive_mgr and _gdrive_folder:
                st.toast("☁️ 已同步至 Google Drive", icon="✅")
        except Exception as _exc:
            logger.warning("scan_history save error: %s", _exc)

    # Display results
    if "buy_df" in st.session_state:
        buy_df     = st.session_state["buy_df"]
        sell_df    = st.session_state["sell_df"]
        run_time   = st.session_state.get("run_time", "")
        scan_stats = st.session_state.get("scan_stats", {})

        st.subheader(f"選股結果　　*{run_time}*")

        # ── 掃描透明度統計 ──────────────────────────────────
        if scan_stats:
            total     = scan_stats.get("total",     0)
            ok        = scan_stats.get("data_ok",   0)
            fail      = scan_stats.get("data_fail", 0)
            b_pass    = scan_stats.get("buy_pass",  0)
            s_pass    = scan_stats.get("sell_pass", 0)
            near_b    = scan_stats.get("near_buy",  0)
            near_s    = scan_stats.get("near_sell", 0)
            b_min     = scan_stats.get("buy_min",   0)
            s_min     = scan_stats.get("sell_min",  0)

            with st.expander("🔬 掃描統計（點開查看完整漏斗分析）", expanded=True):
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("📋 清單收錄", f"{total:,} 檔")
                sc2.metric(
                    "✅ 資料有效",  f"{ok:,} 檔",
                    delta=f"跳過 {fail:,} 檔（無資料/K棒不足）",
                    delta_color="off",
                )
                sc3.metric(
                    f"🟢 買點達標（≥{b_min}項）", f"{b_pass:,} 檔",
                    delta=f"差一步 {near_b:,} 檔（{b_min-1}/{b_min}項）",
                    delta_color="off",
                )
                sc4.metric(
                    f"🔴 賣點達標（≥{s_min}項）", f"{s_pass:,} 檔",
                    delta=f"差一步 {near_s:,} 檔（{s_min-1}/{s_min}項）",
                    delta_color="off",
                )

                # Visual funnel
                pct_ok   = ok   / total * 100 if total else 0
                pct_bpass = b_pass / ok  * 100 if ok    else 0
                st.markdown(
                    f"""
**漏斗流程：**
`{total:,} 檔清單`
→ 資料有效 **{ok:,} 檔**（{pct_ok:.0f}%，{fail:,} 檔因無資料/K棒不足被跳過）
→ 買點達標 **{b_pass:,} 檔**（有效股的 {pct_bpass:.1f}%）
→ 另有 **{near_b:,} 檔** 差一項就達標（可考慮將「最少符合買點項數」降低 1 格）
                    """.strip()
                )

        def _style(val: object) -> str:
            if val == "✓": return "color:#1e6823;font-weight:bold;background:#c6efce"
            if val == "✗": return "color:#9c0006;background:#ffc7ce"
            return ""

        CHECK_BUY  = {"SuperTREX買點", "MACD黃金交叉"}
        CHECK_SELL = {"SuperTREX賣點", "MACD死亡交叉"}

        def _show(df: pd.DataFrame, extra: set) -> None:
            if df.empty:
                st.info("無符合條件的股票。")
                return
            chk = [c for c in df.columns
                   if c in (CHECK_BUY | CHECK_SELL | extra)
                   or c.startswith("RSI") or c.startswith("成交量")
                   or c.startswith("收盤") or c.startswith("跌破")]
            styled = df.style.map(_style, subset=chk) if chk else df.style
            st.dataframe(styled, use_container_width=True, height=420)

        tab_b, tab_s = st.tabs([
            f"🟢 買點訊號　{len(buy_df)} 檔",
            f"🔴 賣點訊號　{len(sell_df)} 檔",
        ])
        with tab_b:
            _show(buy_df,  {f"RSI>{int(b_rsi_v)}", f"成交量>{b_vol_v}x均量",
                             f"收盤>{b_mp_v}"})
        with tab_s:
            _show(sell_df, {f"RSI<{int(s_rsi_v)}", f"收盤<{s_mp_v}"})

        st.divider()
        try:
            xlsx  = build_excel(buy_df, sell_df, run_time)
            fname = f"SuperTREX_選股_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            st.download_button(
                "📥  下載 Excel 報表", data=xlsx, file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"Excel 產生失敗：{exc}")

    # ── 歷史掃描記錄 ─────────────────────────────────────────
    st.divider()
    st.subheader("📂 歷史掃描記錄（最近 10 天）")

    _history = list_scans()

    if not _history:
        st.info("尚無歷史記錄。執行選股後將自動儲存。")
    else:
        # Header row
        _hcols = st.columns([3, 2, 2, 2, 2, 1])
        for _c, _h in zip(_hcols, ["掃描時間", "掃描股票", "資料有效", "買點達標", "賣點達標", "報表"]):
            _c.markdown(f"**{_h}**")

        _gconn_hist = st.session_state.get("gdrive_connected", False)

        # Column headers
        _hc = st.columns([3, 2, 2, 2, 2, 1, 1])
        for _col, _lbl in zip(_hc, ["掃描時間", "掃描股票", "資料有效",
                                     "買點達標", "賣點達標", "本機", "雲端"]):
            _col.markdown(f"**{_lbl}**")

        for _rec in _history:
            _stats  = _rec.get("scan_stats", {})
            _rt     = _rec.get("run_time", _rec["scan_id"])
            _sid    = _rec["scan_id"]
            _is_new = (_sid == st.session_state.get("last_saved_scan_id", ""))
            _cfg_s  = _rec.get("cfg_summary", {})
            _kline  = _cfg_s.get("kline", "")
            _gfid   = _rec.get("gdrive_file_id", "")

            _tag   = " 🆕" if _is_new else ""
            _label = f"{_rt}{_tag}"
            if _kline:
                _label += f"  ·  {_kline}"

            _rc = st.columns([3, 2, 2, 2, 2, 1, 1])
            _rc[0].write(_label)
            _rc[1].write(f"{_stats.get('total', '-'):,} 檔")
            _rc[2].write(f"{_stats.get('data_ok', '-'):,} 檔")
            _rc[3].write(f"🟢 {_stats.get('buy_pass', '-')}")
            _rc[4].write(f"🔴 {_stats.get('sell_pass', '-')}")

            # Local download
            if _rec.get("has_xlsx"):
                _xb = load_xlsx(_sid)
                if _xb:
                    _rc[5].download_button(
                        "📥",
                        data=_xb,
                        file_name=f"SuperTREX_{_sid}.xlsx",
                        mime=(
                            "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"
                        ),
                        key=f"hist_dl_{_sid}",
                        help=f"下載 {_rt} 的 Excel 報表",
                    )
                else:
                    _rc[5].write("—")
            else:
                _rc[5].write("—")

            # GDrive link / upload button
            if _gfid:
                _link = f"https://drive.google.com/file/d/{_gfid}/view"
                _rc[6].markdown(f"[☁️]({_link})")
            elif _gconn_hist and _rec.get("has_xlsx"):
                if _rc[6].button("⬆️", key=f"gd_up_{_sid}",
                                 help="手動上傳此筆到 Google Drive"):
                    _xb2 = load_xlsx(_sid)
                    _gmgr2 = st.session_state.get("gdrive_mgr")
                    _gfld2 = st.session_state.get("gdrive_folder_id", "")
                    if _xb2 and _gmgr2 and _gfld2:
                        try:
                            _new_fid = _gmgr2.upload_excel(
                                _xb2, f"SuperTREX_{_sid}.xlsx", _gfld2
                            )
                            st.toast(f"☁️ 已上傳至 Google Drive", icon="✅")
                        except Exception as _ue:
                            st.error(f"上傳失敗：{_ue}")
                    else:
                        st.warning("請先設定 Google Drive 資料夾 ID")
            else:
                _rc[6].write("—")

        st.caption(
            f"共 {len(_history)} 筆記錄  ·  超過 10 天的報表自動刪除  ·  "
            "每次掃描（手動或盤後自動）皆會自動儲存"
        )

    st.divider()
    st.caption(
        "資料來源：Yahoo Finance（台股 .TW / 美股）｜"
        "分鐘K棒限最近 59 曆日｜本工具僅供參考，不構成投資建議。"
    )


# ═════════════════════════════════════════════════════════
#  TAB 2 — Backtesting
# ═════════════════════════════════════════════════════════
with tab_bt:
    st.subheader("📊 策略回測")
    st.caption(
        "在歷史資料上模擬買賣訊號，驗證策略勝率。"
        "左側可獨立設定回測所用的 K線/指標週期與買賣條件，與左側選股設定互相獨立。"
    )
    st.divider()

    # ── Left: settings  /  Right: results ────────────────
    col_s, col_r = st.columns([1, 2], gap="large")

    # ── Settings column ───────────────────────────────────
    with col_s:
        st.markdown("### 🎯 股票 & 週期")

        bt_ticker = st.text_input(
            "股票代號",
            value="2330",
            placeholder="台股如 2330；美股如 AAPL",
            key="bt_ticker_input",
        )
        bt_mkt_raw = st.radio(
            "市場", ["🇹🇼 台股 (TW)", "🇺🇸 美股 (US)"],
            horizontal=True, key="bt_mkt",
        )
        bt_market = "TW" if "TW" in bt_mkt_raw else "US"

        bt_kline_lbl = st.selectbox(
            "K線週期", list(KLINE_OPTS.keys()), index=4,   # 預設 日線
            key="bt_kline",
        )
        bt_kline = KLINE_OPTS[bt_kline_lbl]

        if bt_kline == "1d":
            bt_years = st.slider("回測年數", 1, 3, 3, key="bt_years")
            st.caption("日線資料最長 3 年")
        else:
            bt_years = 1
            bar_map  = {"5m": 12, "15m": 4, "30m": 2, "1h": 1}
            bars_day = bar_map.get(bt_kline, 4)
            st.caption(
                f"分鐘線最多 59 日 ≈ {59 * bars_day * 7:,} 根 K 棒"
            )

        bt_macd_lbl = st.selectbox(
            "MACD 週期", list(MACD_OPTS.keys()), index=3, key="bt_macd"
        )
        bt_macd_tf = MACD_OPTS[bt_macd_lbl]

        bt_rsi_lbl = st.selectbox(
            "RSI 週期", list(RSI_OPTS.keys()), index=3, key="bt_rsi"
        )
        bt_rsi_tf = RSI_OPTS[bt_rsi_lbl]

        bt_ma_p = st.number_input(
            "MA 週期", min_value=5, max_value=250, value=20, step=1, key="bt_ma"
        )

        st.markdown("---")
        st.markdown("### 📈 買點條件")

        bt_b_st, _         = _row("SuperTREX 買點",          key_chk="bt_b_st")
        bt_b_st_h          = st.number_input(
            "  ↳ 窗口（小時）", min_value=1, max_value=720, value=5,
            step=1, key="bt_b_st_h", help="5h = 買點出現於近 5 小時內",
        )
        bt_b_mac, _        = _row("MACD 黃金交叉",            key_chk="bt_b_mac")
        bt_b_rsi, bt_b_rsi_v = _row(
            "RSI >", has_val=True, val_default=50.0,
            val_min=1.0, val_max=99.0, key_chk="bt_b_rsi", key_val="bt_b_rsi_v",
        )
        bt_b_ma, _         = _row(f"收盤 > MA{int(bt_ma_p)}", key_chk="bt_b_ma")
        bt_b_vol, bt_b_vol_v = _row(
            "成交量 > 均量 ×", has_val=True, val_default=1.5,
            val_min=1.0, val_max=10.0, key_chk="bt_b_vol", key_val="bt_b_vol_v",
        )
        bt_b_mp, bt_b_mp_v = _row(
            "收盤價 >", default=True, has_val=True, val_default=15.0,
            val_min=0.0, val_max=100000.0, key_chk="bt_b_mp", key_val="bt_b_mp_v",
        )

        bt_buy_en  = sum([bt_b_st, bt_b_mac, bt_b_rsi, bt_b_ma, bt_b_vol, bt_b_mp])
        bt_buy_min = st.slider(
            "最少符合幾項買點", 1, max(bt_buy_en, 1),
            min(bt_buy_en, bt_buy_en), key="bt_buy_min",
        )

        st.markdown("---")
        st.markdown("### 📉 賣點條件")

        bt_s_st, _         = _row("SuperTREX 賣點",           key_chk="bt_s_st")
        bt_s_st_h          = st.number_input(
            "  ↳ 窗口（小時）", min_value=1, max_value=720, value=5,
            step=1, key="bt_s_st_h", help="5h = 賣點出現於近 5 小時內",
        )
        bt_s_mac, _        = _row("MACD 死亡交叉",             key_chk="bt_s_mac")
        bt_s_rsi, bt_s_rsi_v = _row(
            "RSI <", has_val=True, val_default=45.0,
            val_min=1.0, val_max=99.0, key_chk="bt_s_rsi", key_val="bt_s_rsi_v",
        )
        bt_s_ma, _         = _row(f"跌破 MA{int(bt_ma_p)}",   key_chk="bt_s_ma")
        bt_s_mp, bt_s_mp_v = _row(
            "收盤價 <", default=True, has_val=True, val_default=15.0,
            val_min=0.0, val_max=100000.0, key_chk="bt_s_mp", key_val="bt_s_mp_v",
        )

        bt_sell_en  = sum([bt_s_st, bt_s_mac, bt_s_rsi, bt_s_ma, bt_s_mp])
        bt_sell_min = st.slider(
            "最少符合幾項賣點", 1, max(bt_sell_en, 1),
            min(bt_sell_en, bt_sell_en), key="bt_sell_min",
        )

        # Build backtest config (independent from screener cfg)
        bt_cfg = {
            "base_interval":       bt_kline,
            "macd_tf":             bt_macd_tf,
            "rsi_tf":              bt_rsi_tf,
            "ma_period":           int(bt_ma_p),
            "buy_supertrex":       bt_b_st,
            "buy_supertrex_hours": int(bt_b_st_h),
            "buy_macd_golden":     bt_b_mac,
            "buy_rsi":             bt_b_rsi,
            "buy_rsi_threshold":   bt_b_rsi_v,
            "buy_price_above_ma":  bt_b_ma,
            "buy_volume_spike":    bt_b_vol,
            "buy_volume_mult":     bt_b_vol_v,
            "buy_min_price":       bt_b_mp,
            "buy_min_price_value": bt_b_mp_v,
            "buy_min_signals":     bt_buy_min,
            "sell_supertrex":       bt_s_st,
            "sell_supertrex_hours": int(bt_s_st_h),
            "sell_macd_death":      bt_s_mac,
            "sell_rsi":             bt_s_rsi,
            "sell_rsi_threshold":   bt_s_rsi_v,
            "sell_price_below_ma":  bt_s_ma,
            "sell_min_price":       bt_s_mp,
            "sell_min_price_value": bt_s_mp_v,
            "sell_min_signals":     bt_sell_min,
        }

        st.markdown("---")
        bt_run = st.button(
            "▶  執行回測", type="primary",
            use_container_width=True, key="bt_run_btn",
        )

    # ── Results column ────────────────────────────────────
    with col_r:

        if bt_run:
            ticker_clean = bt_ticker.strip().upper()
            if not ticker_clean:
                st.warning("請輸入股票代號。")
            else:
                with st.spinner(f"回測 {ticker_clean}…"):
                    try:
                        trades_df, stats, fig = run_backtest(
                            stock_id=ticker_clean,
                            market=bt_market,
                            cfg=bt_cfg,
                            years=bt_years,
                            interval=bt_kline,
                        )
                        st.session_state["bt_trades"] = trades_df
                        st.session_state["bt_stats"]  = stats
                        st.session_state["bt_fig"]    = fig
                        st.session_state["bt_label"]  = ticker_clean
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"回測失敗：{exc}")

        if "bt_stats" in st.session_state:
            trades_df = st.session_state["bt_trades"]
            stats     = st.session_state["bt_stats"]
            fig       = st.session_state["bt_fig"]
            bt_label  = st.session_state.get("bt_label", "")

            st.subheader(f"回測結果：{bt_label}")

            # Stats cards
            stat_items = list(stats.items())
            cols = st.columns(len(stat_items))
            for col, (k, v) in zip(cols, stat_items):
                col.metric(k, v)

            # Interactive chart
            st.plotly_chart(fig, use_container_width=True)

            # Trade log
            if not trades_df.empty:
                st.subheader("交易明細")

                def _bt_style(val: object) -> str:
                    if isinstance(val, str):
                        if "獲利" in val: return "color:#1e6823;font-weight:bold;background:#c6efce"
                        if "虧損" in val: return "color:#9c0006;background:#ffc7ce"
                    if isinstance(val, (int, float)):
                        if val > 0: return "color:#1e6823;font-weight:bold"
                        if val < 0: return "color:#9c0006"
                    return ""

                st.dataframe(
                    trades_df.style.map(_bt_style, subset=["報酬率(%)", "結果"]),
                    use_container_width=True, height=320,
                )
                st.download_button(
                    "📥  下載交易明細 CSV",
                    data=trades_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                    file_name=f"backtest_{bt_label}_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )
            else:
                st.info(
                    "回測期間內未產生任何交易。\n\n"
                    "建議：降低「最少符合條件項數」，或擴大 SuperTREX 窗口小時數。"
                )
        else:
            st.info("👈 在左側設定參數後，點擊「▶ 執行回測」開始。")
