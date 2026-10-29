#!/usr/bin/env python
#
"""Test the parsing helpers in bofa_scraper.util."""

# 3rd party imports
import pytest

# Project imports
from bofa_scraper.util import hash_from_classes, is_signed_in_url, parse_money


####################################################################
#
@pytest.mark.parametrize(
    "text,expected",
    [
        ("$1,234.56", 1234.56),
        ("-$16.37", -16.37),
        ("  $0.00\n", 0.0),
    ],
)
def test_parse_money(text: str, expected: float) -> None:
    """
    GIVEN: an amount as displayed on the page
    WHEN:  it is parsed
    THEN:  the sign and value are kept and formatting is dropped
    """
    assert parse_money(text) == expected


####################################################################
#
def test_parse_money_rejects_non_amount() -> None:
    """
    GIVEN: text that is not an amount, such as a pending-row date cell
    WHEN:  it is parsed
    THEN:  ValueError is raised rather than a wrong number returned
    """
    with pytest.raises(ValueError):
        parse_money("Processing")


####################################################################
#
@pytest.mark.parametrize(
    "class_attr,expected",
    [
        ("activity-row txn-abc123 even-row", "abc123"),
        ("activity-row even-row", ""),
    ],
)
def test_hash_from_classes(class_attr: str, expected: str) -> None:
    """
    GIVEN: a transaction row's class attribute
    WHEN:  the hash is extracted
    THEN:  the 'txn-' prefix is removed, or '' is returned without one
    """
    assert hash_from_classes(class_attr) == expected


####################################################################
#
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://secure.bankofamerica.com/accounts-home/?x=1", True),
        ("https://secure.bankofamerica.com/myaccounts/overview.go", True),
        ("https://secure.bankofamerica.com/login/sign-in/signOn.go", False),
        ("https://secure.bankofamerica.com.example/accounts-home/", False),
    ],
)
def test_is_signed_in_url(url: str, expected: bool) -> None:
    """
    GIVEN: the URL the browser is on after submitting the sign-in form
    WHEN:  it is checked for a signed-in landing page
    THEN:  only the overview paths on the BofA secure host count
    """
    assert is_signed_in_url(url) is expected
