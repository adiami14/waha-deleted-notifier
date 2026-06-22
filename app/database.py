"""SQLite storage layer using aiosqlite."""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Optional

import aiosqlite

from app.config import settings

CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    message_id   TEXT PRIMARY KEY,
    chat_id      TEXT NOT NULL,
    sender_id    TEXT,
    session      TEXT NOT NULL,
    body         TEXT DEFAULT '',
    has_media    INTEGER DEFAULT 0,
    mime_type    TEXT,
    filename     TEXT,
    file_path    TEXT,
    caption      TEXT,
    created_at   INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS processed_events (
    event_id     TEXT PRIMARY KEY,
    processed_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

CREATE_ARCHIVED_TABLE = """
CREATE TABLE IF NOT EXISTS archived_chats (
    chat_id      TEXT PRIMARY KEY,
    is_archived  INTEGER DEFAULT 0,
    updated_at   INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

CREATE_IDX_MESSAGES_CREATED = """
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
"""

CREATE_INCIDENTS_TABLE = """
CREATE TABLE IF NOT EXISTS notification_incidents (
    id                TEXT PRIMARY KEY,
    incident_type     TEXT NOT NULL,
    occurred_at       INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    message_id        TEXT,
    chat_id           TEXT,
    sender_jid        TEXT,
    notification_text TEXT,
    error_detail      TEXT,
    status            TEXT NOT NULL DEFAULT 'open',
    admin_note        TEXT,
    resolved_at       INTEGER,
    priority          INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_IDX_INCIDENTS_OCCURRED = """
CREATE INDEX IF NOT EXISTS idx_incidents_occurred_at ON notification_incidents(occurred_at);
"""

CREATE_IDX_INCIDENTS_STATUS = """
CREATE INDEX IF NOT EXISTS idx_incidents_status ON notification_incidents(status);
"""

CREATE_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS bot_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


async def init_db() -> None:
    """Create tables if they don't exist."""
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(CREATE_MESSAGES_TABLE)
        await db.execute(CREATE_EVENTS_TABLE)
        await db.execute(CREATE_ARCHIVED_TABLE)
        await db.execute(CREATE_IDX_MESSAGES_CREATED)
        await db.execute(CREATE_INCIDENTS_TABLE)
        await db.execute(CREATE_IDX_INCIDENTS_OCCURRED)
        await db.execute(CREATE_IDX_INCIDENTS_STATUS)
        await db.execute(CREATE_SETTINGS_TABLE)
        await db.commit()


async def is_event_processed(event_id: str) -> bool:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,)
        ) as cur:
            return await cur.fetchone() is not None


async def mark_event_processed(event_id: str) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO processed_events(event_id) VALUES (?)",
            (event_id,),
        )
        await db.commit()


async def upsert_message(
    message_id: str,
    chat_id: str,
    sender_id: Optional[str],
    session: str,
    body: str = "",
    has_media: bool = False,
    mime_type: Optional[str] = None,
    filename: Optional[str] = None,
    file_path: Optional[str] = None,
    caption: Optional[str] = None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO messages
                (message_id, chat_id, sender_id, session, body,
                 has_media, mime_type, filename, file_path, caption)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                file_path = COALESCE(excluded.file_path, file_path),
                mime_type = COALESCE(excluded.mime_type, mime_type),
                filename  = COALESCE(excluded.filename, filename),
                caption   = COALESCE(excluded.caption, caption),
                has_media = excluded.has_media
            """,
            (message_id, chat_id, sender_id, session, body,
             int(has_media), mime_type, filename, file_path, caption),
        )
        await db.commit()


async def get_message(message_id: str) -> Optional[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        # Exact match
        async with db.execute(
            "SELECT * FROM messages WHERE message_id = ?", (message_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
        # GOWS LID fallback: stored ID may have a '_<lid>@lid' participant suffix
        # that the revoke handler can't reconstruct from protocolMessage.key.
        # Match any row whose ID starts with '<message_id>_'.
        async with db.execute(
            "SELECT * FROM messages WHERE message_id LIKE ?",
            (message_id + "_%",),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def set_chat_archived(chat_id: str, is_archived: bool) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO archived_chats(chat_id, is_archived, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                is_archived = excluded.is_archived,
                updated_at  = excluded.updated_at
            """,
            (chat_id, int(is_archived), int(time.time())),
        )
        await db.commit()


async def is_chat_archived(chat_id: str) -> bool:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT is_archived FROM archived_chats WHERE chat_id = ?",
            (chat_id,),
        ) as cur:
            row = await cur.fetchone()
            return bool(row[0]) if row else False


async def delete_old_messages(older_than_ts: int) -> int:
    """Delete messages (and associated metadata) older than a timestamp.
    Returns count of rows deleted."""
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT message_id, file_path FROM messages WHERE created_at < ?",
            (older_than_ts,),
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            return 0

        ids = [r[0] for r in rows]
        placeholders = ",".join("?" * len(ids))
        await db.execute(
            f"DELETE FROM messages WHERE message_id IN ({placeholders})", ids
        )
        await db.commit()
        return len(ids)


async def delete_old_events(older_than_ts: int) -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM processed_events WHERE processed_at < ?",
            (older_than_ts,),
        ) as cur:
            (count,) = await cur.fetchone()
        if count:
            await db.execute(
                "DELETE FROM processed_events WHERE processed_at < ?",
                (older_than_ts,),
            )
            await db.commit()
        return count


# ---------------------------------------------------------------------------
# Notification incidents CRUD
# ---------------------------------------------------------------------------

async def create_incident(
    incident_type: str,
    message_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    sender_jid: Optional[str] = None,
    notification_text: Optional[str] = None,
    error_detail: Optional[str] = None,
) -> str:
    """Insert a new incident row and return its id."""
    incident_id = str(uuid.uuid4())
    occurred_at = int(time.time())
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO notification_incidents
                (id, incident_type, occurred_at, message_id, chat_id,
                 sender_jid, notification_text, error_detail, status, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', 0)
            """,
            (incident_id, incident_type, occurred_at, message_id, chat_id,
             sender_jid, notification_text, error_detail),
        )
        await db.commit()
    return incident_id


async def list_incidents(
    status: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        if status:
            sql = (
                "SELECT * FROM notification_incidents WHERE status = ? "
                "ORDER BY priority ASC, occurred_at DESC LIMIT ?"
            )
            params = (status, limit)
        else:
            sql = (
                "SELECT * FROM notification_incidents "
                "ORDER BY priority ASC, occurred_at DESC LIMIT ?"
            )
            params = (limit,)
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_incident(incident_id: str) -> Optional[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM notification_incidents WHERE id = ?", (incident_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def update_incident_status(
    incident_id: str,
    status: str,
    resolved_at: Optional[int] = None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "UPDATE notification_incidents SET status = ?, resolved_at = ? WHERE id = ?",
            (status, resolved_at, incident_id),
        )
        await db.commit()


async def update_incident_note(incident_id: str, note: Optional[str]) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "UPDATE notification_incidents SET admin_note = ? WHERE id = ?",
            (note, incident_id),
        )
        await db.commit()


async def reorder_incidents(ids: list[str]) -> None:
    """Set priority = index position for each id in the list."""
    async with aiosqlite.connect(settings.db_path) as db:
        for i, incident_id in enumerate(ids):
            await db.execute(
                "UPDATE notification_incidents SET priority = ? WHERE id = ?",
                (i, incident_id),
            )
        await db.commit()


# ---------------------------------------------------------------------------
# Bot runtime settings (key-value, persisted in SQLite)
# ---------------------------------------------------------------------------

async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT value FROM bot_settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "INSERT INTO bot_settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()
