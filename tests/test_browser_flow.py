#!/usr/bin/env python
#
"""Test the sign-in retry and account number lookup against a mock driver."""

# system imports
from unittest.mock import MagicMock

# 3rd party imports
import pytest
from pytest_mock import MockerFixture

# Project imports
import bofa_scraper
from bofa_scraper import BofAScraper, ScrapeSession
from bofa_scraper.account import Account


####################################################################
#
@pytest.fixture
def mock_wait_until(mocker: MockerFixture) -> MagicMock:
    """Replace the scraper's wait_until(); tests set its results."""
    return mocker.patch.object(bofa_scraper, "wait_until")


####################################################################
#
@pytest.fixture
def driver() -> MagicMock:
    """A mock WebDriver; tests set what its lookups return."""
    return MagicMock()


####################################################################
#
@pytest.fixture
def scraper(driver: MagicMock) -> BofAScraper:
    """A BofAScraper on the mock driver, built without starting Firefox."""
    s = BofAScraper.__new__(BofAScraper)
    s.driver = driver
    return s


####################################################################
#
@pytest.fixture
def session(driver: MagicMock) -> ScrapeSession:
    """A ScrapeSession on the mock driver with a mock account, opening no tab."""
    s = ScrapeSession.__new__(ScrapeSession)
    s.driver = driver
    s.account = MagicMock(spec=Account)
    return s


####################################################################
#
@pytest.mark.parametrize(
    "form_found,expected,loads",
    [
        ([False, True], True, 2),
        ([False, False, False], False, 3),
    ],
)
def test_open_sign_in_page_reloads_until_form_appears(
    scraper: BofAScraper,
    driver: MagicMock,
    mock_wait_until: MagicMock,
    form_found: list[bool],
    expected: bool,
    loads: int,
) -> None:
    """
    GIVEN: a homepage that shows the sign-in form only on some loads
    WHEN:  the sign-in page is opened
    THEN:  the homepage is reloaded until the form appears, up to the
           attempt limit
    """
    mock_wait_until.side_effect = form_found
    result = scraper._open_sign_in_page()
    assert (result, driver.get.call_count) == (expected, loads)


####################################################################
#
def test_login_raises_without_sign_in_form(
    scraper: BofAScraper, driver: MagicMock, mock_wait_until: MagicMock
) -> None:
    """
    GIVEN: a browser that never reaches a page with the sign-in form
    WHEN:  login() is called
    THEN:  it raises RuntimeError naming the page the browser is on
    """
    driver.find_elements.return_value = []
    driver.current_url = "https://promotions.example/offer"
    mock_wait_until.return_value = False
    with pytest.raises(RuntimeError, match="promotions.example"):
        scraper.login()


####################################################################
#
@pytest.mark.parametrize(
    "texts,expected",
    [
        (["xxxxxxxx1234"], "1234"),
        ([], None),
    ],
)
def test_read_last_four(
    session: ScrapeSession,
    driver: MagicMock,
    texts: list[str],
    expected: str | None,
) -> None:
    """
    GIVEN: an account page with or without its masked account number
    WHEN:  the session reads the account number
    THEN:  the last four digits are returned, or None when it is missing
    """
    driver.find_elements.return_value = [
        MagicMock(get_attribute=MagicMock(return_value=t)) for t in texts
    ]
    assert session._read_last_four() == expected
