"""Tests for archived chat suppression."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app import database as db
from app.config import settings
from app.handlers.revoke_event import handle_revoke


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "media_dir", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "notify_group_id", "123@g.us")
    await db.init_db()
    yield


def _revoke_event(chat_id: str, msg_id: str = "msg1") -> dict:
    return {
        "event": "message.revoked",
        "id": "evt_001",
        "session": "adiami",
        "payload": {
            "before": {
                "id": msg_id,
                "from": chat_id,
                "body": "hello",
                "hasMedia": False,
            }
        },
    }


@pytest.mark.asyncio
async def test_archived_chat_annotates_notification():
    """Revoke event from archived chat should send notification WITH archived tag."""
    await db.set_chat_archived("555@c.us", True)
    await db.upsert_message(
        message_id="msg1",
        chat_id="555@c.us",
        sender_id="555@c.us",
        session="adiami",
        body="hello",
    )

    mock_client = MagicMock()
    mock_client.get_contact = AsyncMock(return_value=None)
    mock_client.lid_to_phone = AsyncMock(return_value=None)
    mock_client.get_group = AsyncMock(return_value=None)
    mock_client.send_text = AsyncMock()

    event = _revoke_event("555@c.us")
    await handle_revoke(event, mock_client)

    mock_client.send_text.assert_called_once()
    sent_text = mock_client.send_text.call_args[0][1]
    assert "📦Archived Chat📦" in sent_text


@pytest.mark.asyncio
async def test_non_archived_chat_sends_notification():
    """Revoke event from non-archived chat SHOULD send notification."""
    await db.set_chat_archived("555@c.us", False)

    # Pre-populate message so we don't hit unavailable path
    await db.upsert_message(
        message_id="msg1",
        chat_id="555@c.us",
        sender_id="555@c.us",
        session="adiami",
        body="hello",
    )

    mock_client = MagicMock()
    mock_client.get_contact = AsyncMock(return_value=None)
    mock_client.lid_to_phone = AsyncMock(return_value=None)
    mock_client.get_group = AsyncMock(return_value=None)
    mock_client.send_text = AsyncMock()

    event = _revoke_event("555@c.us")
    await handle_revoke(event, mock_client)

    mock_client.send_text.assert_called_once()
    sent_text = mock_client.send_text.call_args[0][1]
    assert "📦" not in sent_text


@pytest.mark.asyncio
async def test_chat_archive_event_updates_db():
    """Processing a chat.archive event should update local state."""
    await db.set_chat_archived("777@c.us", False)
    assert not await db.is_chat_archived("777@c.us")

    await db.set_chat_archived("777@c.us", True)
    assert await db.is_chat_archived("777@c.us")

    await db.set_chat_archived("777@c.us", False)
    assert not await db.is_chat_archived("777@c.us")
