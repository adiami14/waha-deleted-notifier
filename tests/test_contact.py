"""Unit tests for the contact lookup service."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.contact_service import (
    resolve_sender_name,
    resolve_group_name,
    is_lid,
    is_valid_phone_jid,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_contact = AsyncMock(return_value={"name": "Moshe Cohen"})
    client.lid_to_phone = AsyncMock(return_value=None)
    client.get_group = AsyncMock(return_value={"subject": "Family Group"})
    return client


@pytest.mark.asyncio
async def test_resolve_sender_name_from_contact(mock_client):
    name = await resolve_sender_name("972501234567@c.us", None, mock_client)
    assert name == "Moshe Cohen"
    mock_client.get_contact.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_sender_name_fallback_to_display(mock_client):
    mock_client.get_contact.return_value = None
    name = await resolve_sender_name("972501234567@c.us", "Avi", mock_client)
    assert name == "Avi"


@pytest.mark.asyncio
async def test_resolve_sender_name_fallback_phone_only(mock_client):
    mock_client.get_contact.return_value = None
    name = await resolve_sender_name("972501234567@c.us", None, mock_client)
    assert name == "+972501234567"


@pytest.mark.asyncio
async def test_resolve_sender_name_contact_no_name(mock_client):
    mock_client.get_contact.return_value = {}
    name = await resolve_sender_name("972501234567@c.us", "Display", mock_client)
    assert name == "Display"


@pytest.mark.asyncio
async def test_resolve_sender_name_exception(mock_client):
    mock_client.get_contact.side_effect = Exception("network error")
    name = await resolve_sender_name("972501234567@c.us", "Fallback", mock_client)
    assert name == "Fallback"


@pytest.mark.asyncio
async def test_resolve_group_name(mock_client):
    name = await resolve_group_name("120363407713984498@g.us", mock_client)
    assert name == "Family Group"


@pytest.mark.asyncio
async def test_resolve_group_name_fallback(mock_client):
    mock_client.get_group.return_value = None
    name = await resolve_group_name("120363407713984498@g.us", mock_client)
    assert name == "120363407713984498@g.us"


# ------------------------------------------------------------------
# LID / phone validation helpers
# ------------------------------------------------------------------

def test_is_lid():
    assert is_lid("74402238582871@lid")
    assert not is_lid("972501234567@c.us")
    assert not is_lid("120363407713984498@g.us")


def test_is_valid_phone_jid():
    assert is_valid_phone_jid("972501234567@c.us")
    assert not is_valid_phone_jid("74402238582871@lid")  # not @c.us
    assert not is_valid_phone_jid("12345@c.us")         # too short
    assert not is_valid_phone_jid("1234567890123456@c.us")  # too long (16 digits)


# ------------------------------------------------------------------
# LID sender resolution
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_lid_direct_contact_lookup(mock_client):
    """get_contact is tried directly with the LID JID first."""
    mock_client.get_contact = AsyncMock(return_value={"name": "טלפון דיסקונט"})
    name = await resolve_sender_name("74402238582871@lid", "Helper", mock_client)
    assert name == "טלפון דיסקונט"


@pytest.mark.asyncio
async def test_resolve_lid_sender_with_display_name(mock_client):
    """When sender is a LID and both direct + LID resolution fail, use display_name."""
    mock_client.get_contact = AsyncMock(return_value=None)
    mock_client.lid_to_phone = AsyncMock(return_value=None)
    name = await resolve_sender_name("74402238582871@lid", "Moshe", mock_client)
    assert name == "Moshe"


@pytest.mark.asyncio
async def test_resolve_lid_sender_lid_resolves_to_phone(mock_client):
    """When direct LID contact fails but LID resolves to phone, use phone contact name."""
    mock_client.get_contact = AsyncMock(side_effect=[None, {"name": "Moshe Cohen"}])
    mock_client.lid_to_phone = AsyncMock(return_value="972501234567@c.us")
    name = await resolve_sender_name("74402238582871@lid", None, mock_client)
    assert name == "Moshe Cohen"


@pytest.mark.asyncio
async def test_resolve_lid_no_display_name_returns_unknown(mock_client):
    """When sender is LID and no display_name and all lookups fail, return 'Unknown'."""
    mock_client.get_contact = AsyncMock(return_value=None)
    mock_client.lid_to_phone = AsyncMock(return_value=None)
    name = await resolve_sender_name("74402238582871@lid", None, mock_client)
    assert name == "Unknown"


@pytest.mark.asyncio
async def test_resolve_valid_phone_shows_plus_prefix(mock_client):
    """When contact lookup returns nothing and JID is valid phone, show +phone."""
    mock_client.get_contact = AsyncMock(return_value=None)
    name = await resolve_sender_name("972501234567@c.us", None, mock_client)
    assert name == "+972501234567"
