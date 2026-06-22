"""WAHA API client - wraps all endpoints used by the bot."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class WAHAError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"WAHA error {status_code}: {detail}")


class WAHAClient:
    """Async WAHA client.  Instantiate once and reuse (shares connection pool)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.waha_base_url,
            headers={"X-Api-Key": settings.waha_api_key.get_secret_value()},
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Messaging – text
    # ------------------------------------------------------------------

    async def send_text(
        self,
        chat_id: str,
        text: str,
        session: Optional[str] = None,
    ) -> dict:
        """POST /api/sendText"""
        r = await self._client.post(
            "/api/sendText",
            json={
                "session": session or settings.waha_notify_session,
                "chatId": chat_id,
                "text": text,
            },
        )
        self._raise_for_status(r, "sendText")
        return r.json()

    # ------------------------------------------------------------------
    # Messaging – media
    # ------------------------------------------------------------------

    async def send_image(
        self,
        chat_id: str,
        file_path: str,
        mime_type: str,
        filename: str,
        caption: str = "",
        session: Optional[str] = None,
    ) -> dict:
        """POST /api/sendImage  (base64 binary upload)"""
        data_b64 = _read_b64(file_path)
        r = await self._client.post(
            "/api/sendImage",
            json={
                "session": session or settings.waha_notify_session,
                "chatId": chat_id,
                "caption": caption,
                "file": {
                    "mimetype": mime_type,
                    "filename": filename,
                    "data": data_b64,
                },
            },
        )
        self._raise_for_status(r, "sendImage")
        return r.json() if r.content else {}

    async def send_file(
        self,
        chat_id: str,
        file_path: str,
        mime_type: str,
        filename: str,
        caption: str = "",
        session: Optional[str] = None,
    ) -> dict:
        """POST /api/sendFile  (base64 binary upload)"""
        data_b64 = _read_b64(file_path)
        r = await self._client.post(
            "/api/sendFile",
            json={
                "session": session or settings.waha_notify_session,
                "chatId": chat_id,
                "caption": caption,
                "file": {
                    "mimetype": mime_type,
                    "filename": filename,
                    "data": data_b64,
                },
            },
        )
        self._raise_for_status(r, "sendFile")
        return r.json() if r.content else {}

    # ------------------------------------------------------------------
    # Media download
    # ------------------------------------------------------------------

    async def download_media(self, url: str) -> bytes:
        """Download media from a WAHA-served URL (includes auth header).

        The URL in the webhook payload may reference 'localhost' or a different
        host than what we need inside Docker.  We strip the host and use only
        the path+query so that httpx routes the request through the configured
        base_url (settings.waha_base_url).
        """
        parsed = urlparse(url)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        r = await self._client.get(path)
        if r.status_code != 200:
            raise WAHAError(r.status_code, f"download_media {url}: {r.text[:200]}")
        return r.content

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    async def check_contact_exists(
        self, contact_id: str, session: Optional[str] = None
    ) -> bool:
        """GET /api/contacts/check-exists
        contact_id is the WA ID, e.g. '972501234567@c.us'
        Returns True if the number is registered on WhatsApp.
        """
        phone = contact_id.split("@")[0]
        r = await self._client.get(
            "/api/contacts/check-exists",
            params={"phone": phone, "session": session or settings.waha_listen_session},
        )
        if r.status_code != 200:
            logger.warning("check_contact_exists failed", status=r.status_code)
            return False
        data = r.json()
        return bool(data.get("numberExists") or data.get("exists"))

    async def lid_to_phone(
        self, lid: str, session: Optional[str] = None
    ) -> Optional[str]:
        """GET /api/{session}/lids/lid/{lid}
        Resolve a LID JID (e.g. '74402238582871@lid') to a phone JID (e.g. '972501234567@c.us').
        Returns the phone JID string or None if not found.
        """
        lid_bare = lid.split("@")[0]
        sess = session or settings.waha_listen_session
        r = await self._client.get(f"/api/{sess}/lids/lid/{lid_bare}")
        if r.status_code != 200:
            logger.warning("lid_to_phone failed", lid=lid, status=r.status_code)
            return None
        data = r.json()
        return data.get("pn") if isinstance(data, dict) else None

    async def get_contact(
        self, contact_id: str, session: Optional[str] = None
    ) -> Optional[dict]:
        """GET /api/contacts?contactId=XXX&session=XXX
        Returns contact dict or None on error.

        Handles both dict and list responses — some WAHA/engine versions wrap
        the contact in a list; we unwrap and return the first element.
        """
        r = await self._client.get(
            "/api/contacts",
            params={"contactId": contact_id, "session": session or settings.waha_listen_session},
        )
        if r.status_code != 200:
            logger.warning("get_contact failed", status=r.status_code, contact_id=contact_id)
            return None
        data = r.json()
        if isinstance(data, list):
            return data[0] if data else None
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    async def get_group(
        self, group_id: str, session: Optional[str] = None
    ) -> Optional[dict]:
        """GET /api/{session}/groups/{id}"""
        sess = session or settings.waha_listen_session
        r = await self._client.get(f"/api/{sess}/groups/{group_id}")
        if r.status_code != 200:
            logger.warning("get_group failed", status=r.status_code, group_id=group_id)
            return None
        return r.json()

    # ------------------------------------------------------------------
    # Chats (archived status via overview)
    # ------------------------------------------------------------------

    async def get_chat_overview(
        self, chat_id: str, session: Optional[str] = None
    ) -> Optional[dict]:
        """GET /api/{session}/chats/overview?ids[]=chat_id
        Returns the first ChatSummary for the given chat, or None.
        The underlying _chat object may contain isArchived.
        """
        sess = session or settings.waha_listen_session
        r = await self._client.get(
            f"/api/{sess}/chats/overview",
            params={"ids": [chat_id], "limit": 1},
        )
        if r.status_code != 200:
            logger.warning("get_chat_overview failed", status=r.status_code, chat_id=chat_id)
            return None
        data = r.json()
        if isinstance(data, list) and data:
            return data[0]
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _raise_for_status(r: httpx.Response, op: str) -> None:
        if r.status_code not in (200, 201, 204):
            raise WAHAError(r.status_code, f"{op}: {r.text[:300]}")

    async def aclose(self) -> None:
        await self._client.aclose()


def _read_b64(file_path: str) -> str:
    """Read a local file and return base64-encoded string."""
    return base64.b64encode(Path(file_path).read_bytes()).decode()
