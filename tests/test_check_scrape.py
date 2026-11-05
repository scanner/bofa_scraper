#!/usr/bin/env python
#
"""Test tools/check_scrape.py against a mock session."""

# system imports
from pathlib import Path
from unittest.mock import MagicMock

# 3rd party imports
import pytest
import pytest_check as check
from pytest_mock import MockerFixture
from selenium.common.exceptions import NoSuchElementException

# Project imports
from bofa_scraper import RowParseError, ScrapeSession
from bofa_scraper.account import Account
from check_scrape import (
    EXIT_CLEAN,
    EXIT_FAILED,
    EXIT_INCONCLUSIVE,
    check_account,
    scrape_account,
)

ROW_HTML = "<tr class='activity-row'>synthetic row</tr>"


####################################################################
#
@pytest.fixture
def mock_session() -> MagicMock:
    """A mock ScrapeSession showing one row."""
    session = MagicMock(spec=ScrapeSession)
    session.account = MagicMock(spec=Account)
    session.account.get_transactions.return_value = [MagicMock()]
    return session


####################################################################
#
@pytest.fixture
def capturer(tmp_path: Path) -> MagicMock:
    """A mock Capturer whose captures all go to the temporary directory."""
    cap = MagicMock()
    cap.capture.return_value = tmp_path
    return cap


####################################################################
#
@pytest.fixture
def no_sleep(mocker: MockerFixture) -> MagicMock:
    """Replace the pause before a recheck."""
    return mocker.patch("check_scrape.time.sleep")


####################################################################
#
@pytest.fixture
def row_error() -> RowParseError:
    """The error for a blank, hidden amount cell."""
    return RowParseError(
        row_number=2,
        cell="amount-cell",
        text="",
        text_content="-$5.00",
        displayed=False,
        row_html=ROW_HTML,
    )


####################################################################
#
def test_scrape_account_without_view_more(mock_session: MagicMock) -> None:
    """
    GIVEN: an account with no 'View more' button
    WHEN:  it is scraped
    THEN:  the run stops after the first scrape without failing
    """
    mock_session.load_more_transactions.side_effect = NoSuchElementException()
    stages: list[str] = []
    scrape_account(mock_session, stages.append)
    check.equal(stages, ["first-scrape", "view-more"])
    check.equal(mock_session.scrape_transactions.call_count, 1)


####################################################################
#
def test_missing_cell_in_second_scrape_is_a_failure(
    mock_session: MagicMock, capturer: MagicMock, no_sleep: MagicMock
) -> None:
    """
    GIVEN: a second scrape that raises NoSuchElementException for a row cell
    WHEN:  the account is checked
    THEN:  it counts as a failure, not as an account with no 'View more'
    """
    mock_session.scrape_transactions.side_effect = [
        mock_session,
        NoSuchElementException(),
        mock_session,
    ]
    assert check_account(mock_session, capturer, "1234", 0) == EXIT_FAILED


####################################################################
#
@pytest.mark.parametrize(
    "rows,expected",
    [(1, EXIT_CLEAN), (0, EXIT_INCONCLUSIVE)],
)
def test_check_account_without_failure(
    mock_session: MagicMock,
    capturer: MagicMock,
    rows: int,
    expected: int,
) -> None:
    """
    GIVEN: an account that scrapes without an error
    WHEN:  it is checked
    THEN:  it is clean only if it showed rows
    """
    mock_session.account.get_transactions.return_value = [MagicMock()] * rows
    assert check_account(mock_session, capturer, "1234", 0) == expected


####################################################################
#
def test_failed_stage_is_captured_with_the_row(
    mock_session: MagicMock,
    capturer: MagicMock,
    no_sleep: MagicMock,
    row_error: RowParseError,
    tmp_path: Path,
) -> None:
    """
    GIVEN: a second scrape that fails on a row, then reads cleanly on recheck
    WHEN:  the account is checked
    THEN:  it is a failure, the stage names the capture, the row is saved,
           and the recheck waits and captures the page again
    """
    mock_session.scrape_transactions.side_effect = [
        mock_session,
        row_error,
        mock_session,
    ]

    status = check_account(mock_session, capturer, "1234", 10)

    names = [call.args[0] for call in capturer.capture.call_args_list]
    check.equal(status, EXIT_FAILED)
    check.equal(names, ["1234-second-scrape", "1234-recheck"])
    check.equal((tmp_path / "row.html").read_text(), ROW_HTML)
    no_sleep.assert_called_once_with(10)
