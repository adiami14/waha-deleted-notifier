"""Handle 'message.any' webhook events.

When a message arrives we:
1. Persist message metadata to DB so we can recover it later if deleted.
2. If the message has media and WAHA has already downloaded it (media.url present),
   we download and cache it locally for later attachment to deletion notices.
"""
from __future__ import annotations

from typing import Any

import structlog

from app import database as db
from app.config import settings
from app.services.media_store import download_and_store
from app.waha.client import WAHAClient

logger = structlog.get_logger(__name__)


def _normalize_jid(jid: str, info: dict) -> str:
    """Resolve a @lid JID to @c.us using SenderAlt from GOWS _data.Info.

    GOWS still sends @lid JIDs but provides the real phone JID in
    _data.Info.SenderAlt.  Normalising to @c.us enables address-book contact
    lookup.  Device suffix ':N' in @s.whatsapp.net JIDs is stripped.
    Non-@lid JIDs are returned unchanged.
    """
    if not (jid and jid.endswith("@lid")):
        return jid
    sender_alt: str = info.get("SenderAlt") or ""
    if sender_alt and "@" in sender_alt:
        phone_part = sender_alt.split("@")[0].split(":")[0]
        if phone_part.isdigit() and 7 <= len(phone_part) <= 15:
            return f"{phone_part}@c.us"
    return jid


def _extract_sender(payload: dict, chat_id: str, is_group: bool) -> str:
    """Return the sender JID, normalised to @c.us where possible.

    WEBJS uses 'participant'; GOWS uses 'author' for group message senders.
    GOWS buries the real phone JID in _data.Info.SenderAlt.
    """
    raw_data: dict = payload.get("_data") or {}
    info: dict = raw_data.get("Info") or {}

    if is_group:
        jid = payload.get("participant") or payload.get("author") or payload.get("from") or chat_id
        if jid and jid.endswith("@g.us"):
            jid = chat_id
    else:
        jid = payload.get("from") or chat_id

    return _normalize_jid(jid, info)


async def handle_any(event: dict[str, Any], client: WAHAClient) -> None:
    """Process a message.any webhook event."""
    payload: dict = event.get("payload") or {}
    session: str = event.get("session", settings.waha_listen_session)

    message_id: str = payload.get("id", "")
    if not message_id:
        logger.warning("message.any: missing message id, skipping")
        return

    chat_id: str = payload.get("from") or payload.get("chatId") or ""
    is_group: bool = chat_id.endswith("@g.us")
    sender_id = _extract_sender(payload, chat_id, is_group)

    body: str = payload.get("body") or ""
    has_media: bool = bool(payload.get("hasMedia"))

    mime_type: str | None = None
    filename: str | None = None
    file_path: str | None = None
    # Caption can arrive in 'caption' or 'body' (WAHA puts it in body for media messages)
    explicit_caption = payload.get("caption")
    caption: str | None = explicit_caption or (body if has_media and body else None)
    if not explicit_caption and caption:
        logger.info(
            "caption extracted from body (no explicit caption field)",
            message_id=message_id,
            chat_id=chat_id,
            caption_preview=caption[:100],
        )

    media: dict | None = payload.get("media")
    if has_media and media and isinstance(media, dict):
        mime_type = media.get("mimetype") or payload.get("mimetype")
        filename = media.get("filename") or payload.get("filename")
        media_url: str = media.get("url") or ""

        if media_url and mime_type:
            file_path = await download_and_store(message_id, media_url, mime_type, client)
        else:
            logger.warning(
                "media present but url or mimetype missing — file will NOT be cached",
                message_id=message_id,
                chat_id=chat_id,
                has_url=bool(media_url),
                has_mimetype=bool(mime_type),
            )
    elif has_media:
        # Fallback: try top-level fields (some engines put them there)
        mime_type = payload.get("mimetype")
        filename = payload.get("filename")

    await db.upsert_message(
        message_id=message_id,
        chat_id=chat_id,
        sender_id=sender_id,
        session=session,
        body=body,
        has_media=has_media,
        mime_type=mime_type,
        filename=filename,
        file_path=file_path,
        caption=caption,
    )

    logger.info(
        "message captured",
        message_id=message_id,
        chat_id=chat_id,
        has_media=has_media,
        has_file=file_path is not None,
        caption=caption,
        body_len=len(body),
        mime_type=mime_type,
    )
