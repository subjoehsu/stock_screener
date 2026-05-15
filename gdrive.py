"""
gdrive.py — Google Drive 同步模組

授權方式（依優先順序）：
  1. Streamlit Secrets   [gdrive] 區段 — Streamlit Cloud 部署用
  2. Session 上傳        使用者在 UI 上傳 service_account.json
  3. 本地檔案            gdrive_credentials.json（本機開發用）

Service Account 設定步驟（UI 中也會顯示）：
  1. 前往 https://console.cloud.google.com/
  2. 建立專案 → 啟用「Google Drive API」
  3. IAM → 服務帳戶 → 建立 → 下載 JSON 金鑰
  4. 在 Google Drive 建立資料夾，將服務帳戶 email 加入「編輯者」
  5. 複製資料夾 ID（URL 最後一段）

Note: google-api-python-client 套件需安裝才能使用。
      若未安裝，本模組所有功能靜默降級（不連線）。
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOCAL_CREDS_FILE = Path("gdrive_credentials.json")
SCOPES = ["https://www.googleapis.com/auth/drive"]

# ── Optional import ────────────────────────────────────────
try:
    from google.oauth2 import service_account           # type: ignore
    from googleapiclient.discovery import build          # type: ignore
    from googleapiclient.http import MediaIoBaseUpload   # type: ignore
    _GOOGLE_OK = True
except ImportError:
    _GOOGLE_OK = False


# ─────────────────────────────────────────────────────────
#  GDriveManager
# ─────────────────────────────────────────────────────────

class GDriveManager:
    """Thin wrapper around Google Drive API v3."""

    def __init__(self, creds_dict: dict[str, Any]) -> None:
        if not _GOOGLE_OK:
            raise RuntimeError(
                "google-api-python-client / google-auth 未安裝，"
                "請確認 requirements.txt 已包含相關套件並重新部署。"
            )
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=SCOPES
        )
        self._svc = build("drive", "v3", credentials=credentials,
                          cache_discovery=False)

    # ── Connection test ────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """
        Verify credentials and API access.
        Returns (success: bool, info_or_error: str).
        """
        try:
            info = self._svc.about().get(fields="user").execute()
            email = info.get("user", {}).get("emailAddress", "unknown")
            return True, email
        except Exception as exc:
            return False, str(exc)

    # ── Folder operations ──────────────────────────────────

    def get_or_create_folder(self, name: str, parent_id: str = "") -> str:
        """
        Return folder ID matching `name` under `parent_id`,
        creating it if it doesn't exist.
        """
        q = (
            f"name='{name}' "
            "and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false"
        )
        if parent_id:
            q += f" and '{parent_id}' in parents"

        res   = self._svc.files().list(q=q, fields="files(id,name)").execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]

        body: dict[str, Any] = {
            "name":     name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            body["parents"] = [parent_id]
        folder = self._svc.files().create(body=body, fields="id").execute()
        logger.info("GDrive: created folder '%s' → %s", name, folder["id"])
        return folder["id"]

    # ── File operations ────────────────────────────────────

    def upload_excel(
        self,
        xlsx_bytes: bytes,
        filename: str,
        folder_id: str,
    ) -> str:
        """
        Upload (or overwrite) an Excel file in `folder_id`.
        Returns the Google Drive file ID.
        """
        XLSX_MIME = (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        )
        # Check if a file with this name already exists
        q   = (f"name='{filename}' and '{folder_id}' in parents "
               "and trashed=false")
        res = self._svc.files().list(q=q, fields="files(id)").execute()
        existing = res.get("files", [])

        media = MediaIoBaseUpload(io.BytesIO(xlsx_bytes), mimetype=XLSX_MIME)

        if existing:
            fid = existing[0]["id"]
            self._svc.files().update(
                fileId=fid, media_body=media
            ).execute()
            logger.info("GDrive: updated %s (%s)", filename, fid)
        else:
            body = {"name": filename, "parents": [folder_id]}
            result = self._svc.files().create(
                body=body, media_body=media, fields="id"
            ).execute()
            fid = result["id"]
            logger.info("GDrive: uploaded %s (%s)", filename, fid)

        return fid

    def list_files(self, folder_id: str, limit: int = 20) -> list[dict]:
        """
        List files in `folder_id`, newest first.
        Each item has: id, name, createdTime, size.
        """
        q   = f"'{folder_id}' in parents and trashed=false"
        res = self._svc.files().list(
            q=q,
            fields="files(id,name,createdTime,size)",
            orderBy="createdTime desc",
            pageSize=limit,
        ).execute()
        return res.get("files", [])

    def get_file_link(self, file_id: str) -> str:
        """Return a viewable Google Drive link for a file."""
        return f"https://drive.google.com/file/d/{file_id}/view"

    def delete_file(self, file_id: str) -> None:
        """Move a file to Drive trash."""
        self._svc.files().delete(fileId=file_id).execute()


# ─────────────────────────────────────────────────────────
#  Credential loaders
# ─────────────────────────────────────────────────────────

def google_packages_available() -> bool:
    return _GOOGLE_OK


def load_credentials_from_secrets() -> dict | None:
    """Try to read service account JSON from st.secrets['gdrive']."""
    try:
        import streamlit as st
        sec = st.secrets.get("gdrive")
        if sec:
            # Streamlit stores TOML sections as AttrDict — convert to plain dict
            d = dict(sec)
            # private_key might have literal \\n — fix
            if "private_key" in d:
                d["private_key"] = d["private_key"].replace("\\n", "\n")
            return d
    except Exception:
        pass
    return None


def load_credentials_from_file() -> dict | None:
    """Try to read service account JSON from the local file."""
    if LOCAL_CREDS_FILE.exists():
        try:
            return json.loads(LOCAL_CREDS_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("GDrive: local creds load failed: %s", exc)
    return None


def save_credentials_to_file(creds_dict: dict) -> None:
    """Persist credentials to the local file (dev use only)."""
    try:
        LOCAL_CREDS_FILE.write_text(
            json.dumps(creds_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("GDrive: could not save local creds: %s", exc)


def build_manager_from_any_source(
    session_creds: dict | None = None,
) -> tuple[GDriveManager | None, str]:
    """
    Try to build a GDriveManager from the best available source.

    Priority:
      1. session_creds  (passed in from st.session_state)
      2. Streamlit Secrets [gdrive]
      3. Local file gdrive_credentials.json

    Returns (manager_or_None, status_message).
    """
    if not _GOOGLE_OK:
        return None, "⚠️ google-api-python-client 套件未安裝"

    for source_name, creds in [
        ("session",  session_creds),
        ("secrets",  load_credentials_from_secrets()),
        ("localfile", load_credentials_from_file()),
    ]:
        if not creds:
            continue
        try:
            mgr = GDriveManager(creds)
            ok, info = mgr.test_connection()
            if ok:
                logger.info("GDrive: connected via %s (%s)", source_name, info)
                return mgr, info
            else:
                logger.warning("GDrive: auth failed (%s): %s", source_name, info)
        except Exception as exc:
            logger.warning("GDrive: build failed (%s): %s", source_name, exc)

    return None, "未設定或授權失敗"
