"""Unit tests for status_tracker compose slot classification (no Playwright)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from status_tracker import _classify_compose_slot_from_type_event  # noqa: E402


def test_classify_recipient_from_target_metadata():
    ev = {
        "action": "type",
        "status": "success",
        "args": {
            "text": "a@b.com",
            "target_description": "label=To, role=textbox",
            "target_name": "To",
            "target_role": "textbox",
        },
    }
    assert _classify_compose_slot_from_type_event(ev) == "recipient"


def test_classify_subject_from_target_metadata():
    ev = {
        "action": "type",
        "status": "success",
        "args": {
            "text": "A short poem",
            "target_description": "label=Add a subject, role=textbox",
            "target_name": "Add a subject",
            "target_role": "textbox",
        },
    }
    assert _classify_compose_slot_from_type_event(ev) == "subject"


def test_classify_none_without_target_metadata():
    ev = {
        "action": "type",
        "status": "success",
        "args": {"text": "hello"},
    }
    assert _classify_compose_slot_from_type_event(ev) is None


def test_classify_none_for_non_type():
    ev = {
        "action": "click",
        "status": "success",
        "args": {"role": "button", "name": "Send"},
    }
    assert _classify_compose_slot_from_type_event(ev) is None
