"""Periodic cleanup: delete media files and DB rows older than DAYS_TO_SAVE_FILES."""
from __future__ import annotations

import time
from pathlib import Path

import structlog

from app import database as db
from app.config import settings

logger = structlog.get_logger(__name__)


async def run_cleanup() -> None:
    """Remove files and DB rows that are older than the configured retention period."""
    cutoff = int(time.time()) - settings.days_to_save_files * 86400

    # 1. Collect file paths from DB rows to be deleted
    paths_to_delete: list[str] = []
    import aiosqlite  # local import to avoid circular
    async with aiosqlite.connect(settings.db_path) as conn:
        async with conn.execute(
            "SELECT file_path FROM messages WHERE created_at < ? AND file_path IS NOT NULL",
            (cutoff,),
        ) as cur:
            rows = await cur.fetchall()
        paths_to_delete = [r[0] for r in rows if r[0]]

    # 2. Delete physical files
    files_removed = 0
    for path in paths_to_delete:
        try:
            p = Path(path)
            if p.exists():
                p.unlink()
                files_removed += 1
        except OSError as exc:
            logger.warning("could not delete file", path=path, error=str(exc))

    # 3. Prune DB rows
    rows_removed = await db.delete_old_messages(cutoff)

    # 4. Prune old dedup event ids (keep last 30 days regardless)
    event_cutoff = int(time.time()) - 30 * 86400
    events_removed = await db.delete_old_events(event_cutoff)

    logger.info(
        "cleanup complete",
        files_removed=files_removed,
        rows_removed=rows_removed,
        events_removed=events_removed,
        cutoff_days=settings.days_to_save_files,
    )
