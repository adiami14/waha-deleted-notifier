"""Download and persist media files attached to WhatsApp messages."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import structlog

from app.config import settings
from app.waha.client import WAHAClient

logger = structlog.get_logger(__name__)

# MIME type → file extension map (mirrors Node-RED flow logic)
_MIME_EXT: dict[str, str] = {
    "jpeg": "jpeg",
    "jpg": "jpg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
    "ogg": "oga",
    "oga": "oga",
    "opus": "opus",
    "mpeg": "mp3",
    "x-m4a": "m4a",
    "mp4": "mp4",
    "quicktime": "mov",
    "pdf": "pdf",
}


def _ext_from_mime(mime: str) -> str:
    """Derive a file extension from a mime type string."""
    mime_clean = mime.split(";")[0].strip().lower()
    if "/" in mime_clean:
        sub = mime_clean.split("/")[1]
    else:
        sub = mime_clean
    sub = re.sub(r"[^a-z0-9.+\-]", "", sub) or "bin"
    return _MIME_EXT.get(sub, sub)


def media_path_for(message_id: str, mime: str) -> Path:
    """Canonical local path for a given message's media."""
    ext = _ext_from_mime(mime)
    # Sanitise message_id for use as a filename
    safe_id = re.sub(r"[^a-zA-Z0-9_\-.]", "_", message_id)
    return Path(settings.media_dir) / f"{safe_id}.{ext}"


async def download_and_store(
    message_id: str,
    media_url: str,
    mime: str,
    client: WAHAClient,
) -> Optional[str]:
    """Download media from WAHA and write to local storage.

    Returns the absolute path to the saved file, or None on failure.
    """
    dest = media_path_for(message_id, mime)
    if dest.exists():
        logger.debug("media already cached", path=str(dest))
        return str(dest)

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = await client.download_media(media_url)
        dest.write_bytes(data)
        logger.info("media saved", message_id=message_id, path=str(dest), size=len(data))
        return str(dest)
    except Exception as exc:
        logger.error("media download failed", message_id=message_id, error=str(exc))
        return None
