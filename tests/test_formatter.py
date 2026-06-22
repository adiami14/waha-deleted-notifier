"""Unit tests for the Hebrew text formatter."""
import pytest

from app.services.formatter import (
    format_file_deleted,
    format_image_deleted,
    format_text_deleted,
    format_unavailable,
    _RTL,
)


class TestTextDeleted:
    def test_group_with_body(self):
        result = format_text_deleted("Moshe", "שלום", is_group=True, group_name="Family")
        assert "Moshe" in result
        assert "שלום" in result
        assert "Family" in result
        assert "קבוצה" in result

    def test_dm_with_body(self):
        result = format_text_deleted("Avi", "hey", is_group=False)
        assert "Avi" in result
        assert "hey" in result
        assert "שיחה פרטית" in result

    def test_group_no_group_name(self):
        result = format_text_deleted("X", "body", is_group=True, group_name=None)
        assert "X" in result
        assert "body" in result


class TestImageDeleted:
    def test_no_caption(self):
        result = format_image_deleted("Sara", None, is_group=False)
        assert "Sara" in result
        assert "מצורף" in result
        assert "ללא תוכן נלווה" in result

    def test_with_caption(self):
        result = format_image_deleted("Sara", "nice photo", is_group=True, group_name="Work")
        assert "nice photo" in result
        assert "Work" in result
        assert "תוכן:" in result

    def test_group(self):
        result = format_image_deleted("Sara", None, is_group=True, group_name="Squad")
        assert "Squad" in result
        assert "קבוצה" in result


class TestFileDeleted:
    def test_with_filename_no_caption(self):
        result = format_file_deleted("Roni", "report.pdf", None, is_group=False)
        assert "Roni" in result
        assert "report.pdf" in result
        assert "מצורף" in result
        assert "ללא תוכן נלווה" in result

    def test_no_filename(self):
        result = format_file_deleted("X", None, "docs", is_group=False)
        assert "קובץ לא ידוע" in result

    def test_caption_included(self):
        result = format_file_deleted("X", "file.zip", "attachment here", is_group=False)
        assert "attachment here" in result


class TestUnavailable:
    def test_group(self):
        result = format_unavailable("Unknown", is_group=True, group_name="TestGroup")
        assert "Unknown" in result
        assert "התוכן לא זמין" in result
        assert "TestGroup" in result

    def test_dm(self):
        result = format_unavailable("Bob", is_group=False)
        assert "Bob" in result
        assert "התוכן לא זמין" in result
        assert "שיחה פרטית" in result


class TestRTL:
    def test_all_messages_start_with_rtl_mark(self):
        assert format_text_deleted("X", "body", False).startswith(_RTL)
        assert format_image_deleted("X", None, False).startswith(_RTL)
        assert format_file_deleted("X", "f.pdf", None, False).startswith(_RTL)
        assert format_unavailable("X", False).startswith(_RTL)


class TestArchived:
    def test_archived_group_appends_tag(self):
        result = format_text_deleted("X", "body", is_group=True, group_name="G", is_archived=True)
        assert "📦Archived Group📦" in result

    def test_archived_chat_appends_tag(self):
        result = format_text_deleted("X", "body", is_group=False, is_archived=True)
        assert "📦Archived Chat📦" in result

    def test_not_archived_no_tag(self):
        result = format_text_deleted("X", "body", is_group=True, group_name="G", is_archived=False)
        assert "📦" not in result
