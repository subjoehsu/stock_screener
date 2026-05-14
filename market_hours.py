"""
market_hours.py — 盤後時間判斷與快取 Key 計算

台股：收盤 13:30 TPE → 盤後資料在 14:00 TPE 後可用
美股：收盤 04:00 TPE（約）→ 盤後資料在 08:00 TPE 後可用

Session key 邏輯：
  - 每個交易日分為兩個 slot：「pre」（盤中）和「post」（盤後）
  - slot 改變時 st.cache_data 的快取自動失效，觸發重新抓取
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TPE = ZoneInfo("Asia/Taipei")

# 台股盤後基準時間（每天 14:00 TPE）
TW_POST_HOUR = 14

# 美股盤後基準時間（每天 08:00 TPE，即美東前一日約 16:00 後 +12h）
US_POST_HOUR = 8


def _now() -> datetime:
    return datetime.now(TPE)


def is_weekday(dt: datetime | None = None) -> bool:
    if dt is None:
        dt = _now()
    return dt.weekday() < 5   # Monday=0 … Friday=4


def is_tw_post_close(dt: datetime | None = None) -> bool:
    """True when TW post-market data is available (weekday & hour >= 14)."""
    if dt is None:
        dt = _now()
    return is_weekday(dt) and dt.hour >= TW_POST_HOUR


def is_us_post_close(dt: datetime | None = None) -> bool:
    """True when US post-market data is available (weekday & hour >= 8)."""
    if dt is None:
        dt = _now()
    return is_weekday(dt) and dt.hour >= US_POST_HOUR


def tw_session_key(dt: datetime | None = None) -> str:
    """
    Cache key for TW stock list.
    Changes once per trading day at TW_POST_HOUR.
    Example: 'TW-2025-05-14-post'
    """
    if dt is None:
        dt = _now()
    d    = dt.strftime("%Y-%m-%d")
    slot = "post" if is_tw_post_close(dt) else "pre"
    return f"TW-{d}-{slot}"


def us_session_key(dt: datetime | None = None) -> str:
    """
    Cache key for US stock list.
    Changes once per trading day at US_POST_HOUR.
    Example: 'US-2025-05-14-post'
    """
    if dt is None:
        dt = _now()
    d    = dt.strftime("%Y-%m-%d")
    slot = "post" if is_us_post_close(dt) else "pre"
    return f"US-{d}-{slot}"


def combined_scan_key() -> str:
    """Combined key for triggering auto-scan when either market closes."""
    return f"{tw_session_key()}|{us_session_key()}"


def _next_event_dt(post_hour: int, dt: datetime) -> datetime:
    """Return the next datetime when `post_hour` will be reached on a weekday."""
    candidate = dt.replace(hour=post_hour, minute=0, second=0, microsecond=0)
    if candidate > dt and is_weekday(candidate):
        return candidate
    # Advance day by day until we land on a weekday
    candidate += timedelta(days=1)
    while not is_weekday(candidate):
        candidate += timedelta(days=1)
    return candidate.replace(hour=post_hour, minute=0, second=0, microsecond=0)


def market_status() -> dict:
    """
    Returns display-ready status info for both markets.

    Keys: tw_icon, tw_msg, us_icon, us_msg, now_str
    """
    now = _now()

    def _fmt(icon_ready, icon_wait, ready: bool, label: str, post_hour: int) -> tuple[str, str]:
        if ready:
            return icon_ready, f"{label}盤後資料已就緒（今日 {post_hour:02d}:00 後）"
        nxt  = _next_event_dt(post_hour, now)
        mins = max(0, int((nxt - now).total_seconds() / 60))
        hhmm = nxt.strftime("%m/%d %H:%M")
        if mins < 90:
            return icon_wait, f"{label}盤後資料將在 **{mins} 分鐘後** 可用（{hhmm} TPE）"
        elif mins < 24 * 60:
            h = mins // 60
            m = mins % 60
            return icon_wait, f"{label}盤後資料將在 {h}h{m:02d}m 後可用（{hhmm} TPE）"
        else:
            return icon_wait, f"{label}盤後資料將在 {hhmm} TPE 後可用"

    tw_icon, tw_msg = _fmt("✅", "⏳", is_tw_post_close(now), "🇹🇼 台股", TW_POST_HOUR)
    us_icon, us_msg = _fmt("✅", "⏳", is_us_post_close(now), "🇺🇸 美股", US_POST_HOUR)

    return {
        "tw_icon": tw_icon,
        "tw_msg":  tw_msg,
        "us_icon": us_icon,
        "us_msg":  us_msg,
        "now_str": now.strftime("%Y-%m-%d %H:%M TPE"),
        "tw_ready": is_tw_post_close(now),
        "us_ready": is_us_post_close(now),
    }
