"""Integration-style tests for the cleanup task."""
import time
from pathlib import Path

import pytest
import pytest_asyncio

from app import database as db
from app.config import settings
from app.tasks.cleanup import run_cleanup


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "media_dir", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "days_to_save_files", 7)
    await db.init_db()
    yield


@pytest.mark.asyncio
async def test_cleanup_deletes_old_rows():
    old_ts = int(time.time()) - 10 * 86400  # 10 days ago
    # Insert an old message directly
    import aiosqlite
    async with aiosqlite.connect(settings.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO messages (message_id, chat_id, session, created_at)
            VALUES ('old_msg', '123@c.us', 'test', ?)
            """,
            (old_ts,),
        )
        await conn.commit()

    await run_cleanup()

    row = await db.get_message("old_msg")
    assert row is None


@pytest.mark.asyncio
async def test_cleanup_keeps_recent_rows():
    recent_ts = int(time.time()) - 1 * 86400  # 1 day ago
    import aiosqlite
    async with aiosqlite.connect(settings.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO messages (message_id, chat_id, session, created_at)
            VALUES ('recent_msg', '123@c.us', 'test', ?)
            """,
            (recent_ts,),
        )
        await conn.commit()

    await run_cleanup()

    row = await db.get_message("recent_msg")
    assert row is not None


@pytest.mark.asyncio
async def test_cleanup_deletes_physical_file(tmp_path):
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    fake_file = media_dir / "old_file.jpg"
    fake_file.write_bytes(b"fake image data")

    old_ts = int(time.time()) - 10 * 86400
    import aiosqlite
    async with aiosqlite.connect(settings.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO messages (message_id, chat_id, session, file_path, created_at)
            VALUES ('msg_with_file', '123@c.us', 'test', ?, ?)
            """,
            (str(fake_file), old_ts),
        )
        await conn.commit()

    await run_cleanup()

    assert not fake_file.exists()
