"""Hebrew text formatter for deletion notifications."""
from __future__ import annotations

from typing import Optional

# Right-to-Left Mark — forces RTL rendering in WhatsApp
_RTL = "\u200F"


def format_text_deleted(
    sender_name: str,
    body: str,
    is_group: bool,
    group_name: Optional[str] = None,
    is_archived: bool = False,
) -> str:
    location = _location_str(is_group, group_name)
    text = f'{_RTL}הודעה נמחקה ע"י *{sender_name}*{location} עם התוכן:\n{_RTL}*{body}*'
    return _append_archived(text, is_group, is_archived)


def format_image_deleted(
    sender_name: str,
    caption: Optional[str],
    is_group: bool,
    group_name: Optional[str] = None,
    is_archived: bool = False,
) -> str:
    location = _location_str(is_group, group_name)
    content_part = f"תוכן: *{caption}*" if caption else "ללא תוכן נלווה"
    text = f'{_RTL}הודעה נמחקה ע"י *{sender_name}*{location} עם התמונה הבאה: (מצורף)\n{_RTL}{content_part}'
    return _append_archived(text, is_group, is_archived)


def format_file_deleted(
    sender_name: str,
    filename: Optional[str],
    caption: Optional[str],
    is_group: bool,
    group_name: Optional[str] = None,
    is_archived: bool = False,
) -> str:
    location = _location_str(is_group, group_name)
    fname = filename or "קובץ לא ידוע"
    content_part = f"תוכן: *{caption}*" if caption else "ללא תוכן נלווה"
    text = f'{_RTL}הודעה נמחקה ע"י *{sender_name}*{location} עם הקובץ הבא: *{fname}* (מצורף)\n{_RTL}{content_part}'
    return _append_archived(text, is_group, is_archived)


def format_unavailable(
    sender_name: str,
    is_group: bool,
    group_name: Optional[str] = None,
    is_archived: bool = False,
) -> str:
    location = _location_str(is_group, group_name)
    text = f'{_RTL}הודעה נמחקה ע"י *{sender_name}*{location}\n{_RTL}(התוכן לא זמין)'
    return _append_archived(text, is_group, is_archived)


def _location_str(is_group: bool, group_name: Optional[str]) -> str:
    if is_group:
        name = f'*"{group_name}"*' if group_name else "קבוצה לא ידועה"
        return f" בקבוצה {name}"
    return " בשיחה פרטית"


def _append_archived(text: str, is_group: bool, is_archived: bool) -> str:
    if not is_archived:
        return text
    tag = "📦Archived Group📦" if is_group else "📦Archived Chat📦"
    return f"{text}\n\n{_RTL}{tag}"
