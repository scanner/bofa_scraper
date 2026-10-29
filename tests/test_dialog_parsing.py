#!/usr/bin/env python
#
"""Test transaction details dialog label handling and text parsing."""

# system imports
from collections.abc import Callable

# 3rd party imports
import pytest

# Project imports
from bofa_scraper import TRANSACTION_DETAIL_FIELDS
from bofa_scraper.scrape_session import _LABEL_TO_KEY, ScrapeSession


########################################################################
########################################################################
#
class TestLabelTables:
    """TRANSACTION_DETAIL_FIELDS and _LABEL_TO_KEY must agree."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "key,label",
        [f for f in TRANSACTION_DETAIL_FIELDS if f[0] != "raw_description"],
    )
    def test_field_label_maps_to_its_key(self, key: str, label: str) -> None:
        """
        GIVEN: a documented detail field
        WHEN:  its dialog label is looked up
        THEN:  it maps to the field's documented key
        """
        assert _LABEL_TO_KEY[label.lower()] == key

    ####################################################################
    #
    def test_every_mapped_key_is_documented(self) -> None:
        """
        GIVEN: the label-to-key map used by the parser
        WHEN:  its keys are compared with TRANSACTION_DETAIL_FIELDS
        THEN:  every key the parser produces is a documented field
        """
        documented = {key for key, _ in TRANSACTION_DETAIL_FIELDS}
        assert set(_LABEL_TO_KEY.values()) <= documented


########################################################################
########################################################################
#
class TestStoreField:
    """Tests for ScrapeSession._store_field."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "existing,label,key",
        [
            ({}, "Description", "description"),
            ({"description": "edited"}, "Description", "raw_description"),
            ({}, "  Posting Date ", "posting_date"),
            ({}, "Reference number", "reference_number"),
        ],
    )
    def test_label_to_key(
        self, existing: dict[str, str], label: str, key: str
    ) -> None:
        """
        GIVEN: a result dict, possibly already holding a description
        WHEN:  a label/value pair is stored
        THEN:  it lands under the canonical key; a second 'Description'
               becomes 'raw_description' and unknown labels are snake_cased
        """
        result = dict(existing)
        ScrapeSession._store_field(result, label, "value")
        assert result[key] == "value"


########################################################################
########################################################################
#
class TestFillFromDialogText:
    """Tests for ScrapeSession._fill_from_dialog_text."""

    ####################################################################
    #
    def test_reads_every_known_field(
        self,
        dialog_text: Callable[[list[tuple[str, str]]], str],
        all_dialog_fields: list[tuple[str, str, str]],
    ) -> None:
        """
        GIVEN: dialog text holding every known field in dialog order
        WHEN:  it is parsed into an empty result
        THEN:  each value is stored under its key, including the second
               'Description' as 'raw_description'
        """
        text = dialog_text([(lbl, val) for lbl, _, val in all_dialog_fields])
        result: dict[str, str] = {}
        ScrapeSession._fill_from_dialog_text(result, text)
        assert result == {key: val for _, key, val in all_dialog_fields}

    ####################################################################
    #
    def test_keeps_values_already_found(
        self, dialog_text: Callable[[list[tuple[str, str]]], str]
    ) -> None:
        """
        GIVEN: a result already holding a status from an earlier strategy
        WHEN:  dialog text with a different status is parsed
        THEN:  the earlier value is kept
        """
        result = {"status": "from grid"}
        ScrapeSession._fill_from_dialog_text(
            result, dialog_text([("Status", "from text")])
        )
        assert result == {"status": "from grid"}

    ####################################################################
    #
    def test_label_followed_by_label_is_skipped(self) -> None:
        """
        GIVEN: a label with no value line before the next label
        WHEN:  the text is parsed
        THEN:  the first label gets no value rather than the next label
        """
        result: dict[str, str] = {}
        ScrapeSession._fill_from_dialog_text(
            result, "Merchant name\nTransaction category\nShopping"
        )
        assert result == {"transaction_category": "Shopping"}
