"""
scan_history.py — 掃描結果歷史記錄管理

每次選股掃描完成（手動或盤後自動）後，呼叫 save_scan() 將 Excel 與
中繼資料 JSON 儲存至 scan_history/ 目錄。

保留策略：最多保留 10 天的記錄；超過 10 天的檔案在下次儲存時自動刪除。

目錄結構：
  scan_history/
    YYYYMMDD_HHMM.xlsx     ← Excel 報表
    YYYYMMDD_HHMM.json     ← 中繼資料（stats、session key、設定摘要）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# 本機歷史記錄目錄（優先使用絕對路徑；若不存在則退回相對路徑）
_ABS_HISTORY = Path(r"C:\Users\user\OneDrive\桌面\claude-Code\台美股選股機")
HISTORY_DIR  = _ABS_HISTORY if _ABS_HISTORY.exists() or _ABS_HISTORY.parent.exists() \
               else Path("scan_history")

MAX_DAYS    = 10          # 超過幾天的記錄自動刪除
MAX_RECORDS = 50          # 最多保留幾筆（防止意外累積）


# ─────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────

def _ensure_dir() -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _parse_ts(stem: str) -> datetime | None:
    """Parse datetime from filename stem 'YYYYMMDD_HHMM'."""
    try:
        return datetime.strptime(stem[:13], "%Y%m%d_%H%M")
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────

def save_scan(
    buy_df:      pd.DataFrame,
    sell_df:     pd.DataFrame,
    scan_stats:  dict[str, Any],
    run_time:    str,
    scan_key:    str,
    cfg_summary: dict[str, Any] | None = None,
    gdrive_mgr:  Any = None,
    gdrive_folder_id: str = "",
) -> str:
    """
    Persist a scan result.

    Parameters
    ----------
    buy_df / sell_df   : screener output DataFrames
    scan_stats         : dict from run_screener()
    run_time           : display string  "YYYY-MM-DD HH:MM"
    scan_key           : combined_scan_key() string
    cfg_summary        : optional lightweight config dict for display
    gdrive_mgr         : optional GDriveManager instance for cloud backup
    gdrive_folder_id   : Google Drive folder ID to upload into

    Returns
    -------
    scan_id  (str)  — e.g. "20250514_1400"
    """
    from excel_export import build_excel   # avoid circular import at module level

    _ensure_dir()
    cleanup_old_scans()   # prune before adding

    # Derive a stable ID from run_time
    try:
        ts = datetime.strptime(run_time, "%Y-%m-%d %H:%M")
    except ValueError:
        ts = datetime.now()
    scan_id = ts.strftime("%Y%m%d_%H%M")

    # ── Build Excel bytes ──────────────────────────────────
    xlsx_bytes: bytes | None = None
    try:
        xlsx_bytes = build_excel(buy_df, sell_df, run_time)
    except Exception as exc:
        logger.warning("scan_history: Excel build failed (%s): %s", scan_id, exc)

    # ── Save Excel locally ─────────────────────────────────
    if xlsx_bytes:
        xlsx_path = HISTORY_DIR / f"{scan_id}.xlsx"
        try:
            xlsx_path.write_bytes(xlsx_bytes)
        except Exception as exc:
            logger.warning("scan_history: local Excel write failed (%s): %s",
                           scan_id, exc)

    # ── Upload to Google Drive ─────────────────────────────
    gdrive_file_id: str = ""
    if gdrive_mgr and gdrive_folder_id and xlsx_bytes:
        try:
            fname = f"SuperTREX_{scan_id}.xlsx"
            gdrive_file_id = gdrive_mgr.upload_excel(
                xlsx_bytes, fname, gdrive_folder_id
            )
            logger.info("scan_history: GDrive upload OK → %s", gdrive_file_id)
        except Exception as exc:
            logger.warning("scan_history: GDrive upload failed (%s): %s",
                           scan_id, exc)

    # ── Save metadata JSON ──────────────────────────────────
    meta: dict[str, Any] = {
        "scan_id":       scan_id,
        "run_time":      run_time,
        "scan_key":      scan_key,
        "scan_stats":    scan_stats,
        "cfg_summary":   cfg_summary or {},
        "has_xlsx":      xlsx_bytes is not None,
        "gdrive_file_id": gdrive_file_id,
    }
    json_path = HISTORY_DIR / f"{scan_id}.json"
    try:
        json_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("scan_history: JSON save failed (%s): %s", scan_id, exc)

    logger.info("scan_history: saved %s", scan_id)
    return scan_id


def list_scans(limit: int = MAX_RECORDS) -> list[dict[str, Any]]:
    """
    Return scan metadata sorted newest-first, up to `limit` records.
    Only returns records that have a corresponding JSON file.
    """
    _ensure_dir()
    scans: list[dict[str, Any]] = []

    for json_file in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
        if len(scans) >= limit:
            break
        try:
            meta = json.loads(json_file.read_text(encoding="utf-8"))
            # Verify Excel presence on disk (may differ from saved flag)
            xlsx_path = HISTORY_DIR / f"{meta['scan_id']}.xlsx"
            meta["has_xlsx"] = xlsx_path.exists()
            scans.append(meta)
        except Exception as exc:
            logger.debug("scan_history: skipping %s — %s", json_file, exc)

    return scans


def load_xlsx(scan_id: str) -> bytes | None:
    """Return Excel bytes for a given scan_id, or None if not found."""
    xlsx_path = HISTORY_DIR / f"{scan_id}.xlsx"
    if xlsx_path.exists():
        return xlsx_path.read_bytes()
    return None


def cleanup_old_scans(days: int = MAX_DAYS) -> int:
    """
    Delete scan files older than `days` calendar days.

    Returns the number of files deleted.
    """
    _ensure_dir()
    cutoff  = datetime.now() - timedelta(days=days)
    deleted = 0
    for f in list(HISTORY_DIR.iterdir()):
        if f.suffix not in (".json", ".xlsx"):
            continue
        ts = _parse_ts(f.stem)
        if ts is None:
            continue
        if ts < cutoff:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass

    if deleted:
        logger.info("scan_history: deleted %d old file(s)", deleted)
    return deleted


def record_count() -> int:
    """Return how many complete scan records exist (JSON + Excel pairs)."""
    _ensure_dir()
    return sum(1 for _ in HISTORY_DIR.glob("*.json"))
