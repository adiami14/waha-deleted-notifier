"""Contact name lookup — direct get_contact approach with LID/GOWS fallback."""
from __future__ import annotations

from typing import Optional

import structlog

from app.waha.client import WAHAClient

logger = structlog.get_logger(__name__)


def is_lid(jid: str) -> bool:
    return isinstance(jid, str) and jid.endswith("@lid")


def is_valid_phone_jid(jid: str) -> bool:
    """Return True if jid looks like a real phone number JID (7-15 digits @c.us)."""
    if not (isinstance(jid, str) and jid.endswith("@c.us")):
        return False
    digits = jid.split("@")[0]
    return digits.isdigit() and 7 <= len(digits) <= 15


def _format_phone(jid: str) -> Optional[str]:
    """Return '+NNNN' from '972501234567@c.us', or None if not a valid phone JID."""
    if not is_valid_phone_jid(jid):
        return None
    return "+" + jid.split("@")[0]


def _extract_name(contact: dict) -> Optional[str]:
    """Pick the best display name from a WAHA contact dict.

    Field names vary by engine and WAHA version — we check all known variants
    so that a future engine change does not silently degrade to display_name.

    Priority: address-book name > verified/business name > WhatsApp push name.
    """
    return (
        contact.get("name")           # saved in phone address book
        or contact.get("shortName")
        or contact.get("verifiedName")  # WhatsApp Business verified
        or contact.get("formattedName")
        or contact.get("displayName")
        or contact.get("pushname")    # WhatsApp profile name (not address book)
        or contact.get("notify")      # alternative field used by some WAHA versions
        or None
    )


async def resolve_sender_name(
    sender_jid: str,
    display_name: Optional[str],
    client: WAHAClient,
    session: Optional[str] = None,
) -> str:
    """Return the best available display name for a sender.

    Resolution order:
    1. WAHA get_contact with the sender JID as-is
       - GOWS engine sends @c.us JIDs — looked up directly
       - WEBJS engine sends @lid JIDs — also attempted directly first
    2. If @lid (WEBJS only): try to resolve to phone JID via lid_to_phone, then
       get_contact again.  With GOWS the LID endpoint does not exist; lid_to_phone
       returns None gracefully so this path is a no-op on GOWS.
    3. display_name from webhook payload (notifyName / pushname)
    4. Formatted phone number (only if JID is a valid @c.us phone JID)
    5. "Unknown"
    """
    if not sender_jid:
        return display_name or "Unknown"

    # Step 1 — try get_contact directly with whatever JID we have
    name = await _try_get_contact_name(sender_jid, client, session)
    if name:
        return name

    # Step 2 — for LIDs (WEBJS): resolve to phone JID, then contact-lookup again.
    # GOWS sends @c.us JIDs so is_lid() is always False on GOWS — this step is skipped.
    if is_lid(sender_jid):
        try:
            phone_jid = await client.lid_to_phone(sender_jid, session)
            if phone_jid:
                logger.info("lid resolved to phone jid", lid=sender_jid, phone=phone_jid)
                name = await _try_get_contact_name(phone_jid, client, session)
                if name:
                    return name
        except Exception as exc:
            logger.warning("lid_to_phone error", lid=sender_jid, error=str(exc))

    # Step 3 — display_name from webhook payload
    if display_name:
        return display_name

    # Step 4 — formatted phone number (works for GOWS @c.us JIDs)
    phone = _format_phone(sender_jid)
    if phone:
        return phone

    return "Unknown"


async def _try_get_contact_name(
    jid: str, client: WAHAClient, session: Optional[str]
) -> Optional[str]:
    """Call GET /api/contacts and return the best name, or None on failure/empty.

    Logs the raw contact fields at WARNING level whenever name extraction fails
    so that future engine changes are immediately diagnosable from logs.
    """
    try:
        contact = await client.get_contact(jid, session)
        if contact:
            name = _extract_name(contact)
            if name:
                logger.info("contact name resolved", jid=jid, name=name)
                return name
            # Name extraction failed — log raw keys so we can adapt to engine changes
            logger.warning(
                "contact_name_extraction_failed",
                jid=jid,
                contact_keys=list(contact.keys()),
                contact_preview={k: contact[k] for k in list(contact.keys())[:8]},
            )
    except Exception as exc:
        logger.warning("get_contact error", jid=jid, error=str(exc))
    return None


def _extract_group_name(data: dict) -> Optional[str]:
    """Pick the best group name from a WAHA response dict (engine-agnostic)."""
    chat = data.get("_chat") or {}
    return (
        data.get("subject")
        or data.get("name")
        or data.get("Name")       # GOWS engine returns capital-N key
        or data.get("title")
        or chat.get("subject")
        or chat.get("name")
        or None
    )


async def resolve_group_name(
    group_jid: str,
    client: WAHAClient,
    session: Optional[str] = None,
) -> str:
    """Return group subject/name, or the JID as fallback.

    Tries the groups endpoint first; falls back to chat overview (more
    reliable on GOWS which may return the subject in a different shape).
    """
    # Step 1 — groups endpoint
    try:
        group = await client.get_group(group_jid, session)
        if group:
            name = _extract_group_name(group)
            if name:
                return name
            logger.warning("get_group returned no usable name field", group_jid=group_jid, keys=list(group.keys()))
    except Exception as exc:
        logger.warning("get_group failed", group_jid=group_jid, error=str(exc))

    # Step 2 — chat overview (GOWS-compatible fallback)
    try:
        overview = await client.get_chat_overview(group_jid, session)
        if overview:
            name = _extract_group_name(overview)
            if name:
                return name
    except Exception as exc:
        logger.warning("get_chat_overview for group name failed", group_jid=group_jid, error=str(exc))

    return group_jid
