#!/usr/bin/env python
#
"""Test the helpers in bofa_scraper.util."""

# system imports
from unittest.mock import MagicMock

# 3rd party imports
import pytest
from pytest_mock import MockerFixture

# Project imports
from bofa_scraper.util import (
    Timeout,
    hash_from_classes,
    is_signed_in_url,
    parse_money,
    wait_until,
)


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


####################################################################
#
@pytest.fixture
def mock_settle(mocker: MockerFixture) -> MagicMock:
    """
    Replace Timeout.settle() with a mock so nothing sleeps.

    Also sets wait_duration to 0 so a condition that never holds times out
    at once.
    """
    mocker.patch.object(Timeout, "wait_duration", 0)
    return mocker.patch.object(Timeout, "settle")


####################################################################
#
@pytest.mark.parametrize("holds,settles", [(True, 1), (False, 0)])
def test_wait_until_settles_only_when_condition_holds(
    mock_settle: MagicMock, holds: bool, settles: int
) -> None:
    """
    GIVEN: a condition that either holds at once or never holds
    WHEN:  wait_until() waits on it
    THEN:  it reports whether the condition held, and pauses to let the
           page settle only when it did
    """
    result = wait_until(object(), lambda d: holds, "a test condition")  # type: ignore[arg-type]
    assert (result, mock_settle.call_count) == (holds, settles)
