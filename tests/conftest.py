#!/usr/bin/env python
#
"""
Shared fixtures.

Test inputs are built from the package's own constants and synthetic
values. No captured BofA pages or data are used.
"""

# system imports
from collections.abc import Callable
from pathlib import Path

# 3rd party imports
import pytest

# Project imports
from bofa_scraper import TRANSACTION_DETAIL_FIELDS


####################################################################
#
@pytest.fixture
def dialog_text() -> Callable[[list[tuple[str, str]]], str]:
    """
    Factory for the visible text of a transaction details dialog.

    Takes (label, value) pairs and returns them one per line, label first,
    the way Selenium reports the dialog's text.
    """

    def make(pairs: list[tuple[str, str]]) -> str:
        return "\n".join(f"{label}\n{value}" for label, value in pairs)

    return make


####################################################################
#
@pytest.fixture
def all_dialog_fields() -> list[tuple[str, str, str]]:
    """
    Every known detail field as (dialog label, key, synthetic value).

    'raw_description' appears in the dialog as a second 'Description' row,
    so its dialog label is 'Description', not the label in
    TRANSACTION_DETAIL_FIELDS.
    """
    return [
        (
            "Description" if key == "raw_description" else label,
            key,
            f"value of {key}",
        )
        for key, label in TRANSACTION_DETAIL_FIELDS
    ]


####################################################################
#
@pytest.fixture
def page_file(tmp_path: Path) -> Callable[[str], Path]:
    """Factory that writes an HTML body to a file and returns its path."""

    def make(body: str) -> Path:
        path = tmp_path / "page.html"
        path.write_text(
            "<!doctype html><html><head><title>Test page</title>"
            "<script>var secret = 'script text';</script>"
            "<style>.x { color: red }</style>"
            f"</head><body>{body}</body></html>"
        )
        return path

    return make
