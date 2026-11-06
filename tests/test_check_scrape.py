#!/usr/bin/env python
#
"""Test tools/check_scrape.py against a mock scraper and session."""

# system imports
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

# 3rd party imports
import pytest
import pytest_check as check
from pytest_mock import MockerFixture
from selenium.common.exceptions import NoSuchElementException

# Project imports
from bofa_scraper import RowParseError, ScrapeSession
from check_scrape import (
    EXIT_CLEAN,
    EXIT_FAILED,
    EXIT_INCONCLUSIVE,
    check_account,
    main,
)
from dump_pages import Capturer

ROW_HTML = "<tr>synthetic row</tr>"
ROW_ERROR = RowParseError(2, "amount-cell", "", "-$5.00", False, ROW_HTML)
UNREADABLE_ROW_ERROR = RowParseError(2, "amount-cell", "", None, None, None)


####################################################################
#
@pytest.fixture
def mock_session(account: MagicMock) -> MagicMock:
    """A mock ScrapeSession on the mock account, showing one row."""
    session = MagicMock(spec=ScrapeSession)
    session.account = account
    account.get_transactions.return_value = [MagicMock()]
    return session


####################################################################
#
@pytest.fixture
def capturer(tmp_path: Path) -> MagicMock:
    """A mock Capturer whose captures all go to the temporary directory."""
    cap = MagicMock(spec=Capturer)
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
def mock_scraper(
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    mock_session: MagicMock,
) -> MagicMock:
    """
    The signed-in BofAScraper that main() builds, opening mock_session.

    Credentials come from the environment, captures are mocked, and the
    logging changes main() makes are undone afterwards.
    """
    monkeypatch.setenv("BOFA_ID", "synthetic-id")
    monkeypatch.setenv("BOFA_PASSCODE", "synthetic-passcode")
    monkeypatch.setattr(logging.getLogger("bofa_scraper"), "propagate", True)
    mocker.patch("check_scrape.logging.basicConfig")
    mocker.patch("check_scrape.Capturer")
    scraper = mocker.patch("check_scrape.BofAScraper").return_value
    scraper.open_account.return_value = mock_session
    return scraper


####################################################################
#
@pytest.fixture
def mock_check_account(mocker: MockerFixture) -> MagicMock:
    """Replace check_account(); tests set the status for each account."""
    return mocker.patch("check_scrape.check_account")


####################################################################
#
@pytest.fixture
def run_main(
    monkeypatch: pytest.MonkeyPatch,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> Callable[[list[str | None], list[str]], int]:
    """
    Factory that runs main() over accounts with the given last four digits.

    Takes those digits, one entry per account, and the command line arguments.
    """

    def run(last_fours: list[str | None], argv: list[str]) -> int:
        monkeypatch.setattr(sys, "argv", ["check_scrape.py", *argv])
        mock_scraper.get_accounts.return_value = [
            MagicMock() for _ in last_fours
        ]
        mock_session.get_last_four.side_effect = last_fours
        return main()

    return run


####################################################################
#
@pytest.mark.parametrize(
    "load_more_error,rows,expected,scrapes,captures",
    [
        (None, 1, EXIT_CLEAN, 2, []),
        (NoSuchElementException(), 1, EXIT_CLEAN, 1, []),
        (None, 0, EXIT_INCONCLUSIVE, 2, ["1234-no-rows"]),
    ],
    ids=["clean", "no-view-more", "no-rows"],
)
def test_check_account_without_failure(
    mock_session: MagicMock,
    account: MagicMock,
    capturer: MagicMock,
    load_more_error: Exception | None,
    rows: int,
    expected: int,
    scrapes: int,
    captures: list[str],
) -> None:
    """
    GIVEN: an account that scrapes without an error
    WHEN:  it is checked
    THEN:  it is clean only if it showed rows, a page with none is captured,
           and the second scrape runs only if there was a 'View more' button
    """
    mock_session.load_more_transactions.side_effect = load_more_error
    account.get_transactions.return_value = [MagicMock()] * rows

    status = check_account(mock_session, capturer, "1234", 0)

    names = [call.args[0] for call in capturer.capture.call_args_list]
    check.equal(status, expected)
    check.equal(mock_session.scrape_transactions.call_count, scrapes)
    check.equal(names, captures)


####################################################################
#
@pytest.mark.parametrize(
    "scrapes,failed_capture,recheck_fails,row_file",
    [
        ([None, ROW_ERROR, None], "1234-second-scrape", False, ROW_HTML),
        ([ROW_ERROR, ROW_ERROR], "1234-first-scrape", True, ROW_HTML),
        (
            [None, NoSuchElementException(), None],
            "1234-second-scrape",
            False,
            None,
        ),
        ([None, UNREADABLE_ROW_ERROR, None], "1234-second-scrape", False, None),
    ],
    ids=["recheck-clean", "recheck-fails", "missing-cell", "row-unreadable"],
)
def test_check_account_failure(
    mock_session: MagicMock,
    capturer: MagicMock,
    no_sleep: MagicMock,
    tmp_path: Path,
    scrapes: list[Exception | None],
    failed_capture: str,
    recheck_fails: bool,
    row_file: str | None,
) -> None:
    """
    GIVEN: a scrape that fails, including a NoSuchElementException from a row's
           cell, which must not pass as an account with no 'View more'
    WHEN:  the account is checked
    THEN:  it is a failure, the stage names the capture, the traceback and any
           row HTML are saved, and the recheck waits and captures the page
    """
    mock_session.scrape_transactions.side_effect = scrapes

    status = check_account(mock_session, capturer, "1234", 10)

    failed, rechecked = capturer.capture.call_args_list
    saved_row = tmp_path / "row.html"
    check.equal(status, EXIT_FAILED)
    check.equal(failed.args, (failed_capture,))
    check.is_in("Traceback", failed.kwargs["error"])
    check.equal(rechecked.args, ("1234-recheck",))
    check.equal("error" in rechecked.kwargs, recheck_fails)
    check.equal(saved_row.read_text() if saved_row.exists() else None, row_file)
    check.equal([call.args for call in no_sleep.call_args_list], [(10,)])


####################################################################
#
@pytest.mark.parametrize(
    "last_fours,argv,statuses,expected,labels",
    [
        (
            ["1111", "2222"],
            ["--last-four", "2222"],
            [EXIT_CLEAN],
            EXIT_CLEAN,
            ["2222"],
        ),
        (["1111"], ["--last-four", "2222"], [], EXIT_INCONCLUSIVE, []),
        ([None], [], [EXIT_CLEAN], EXIT_CLEAN, ["account-1"]),
        (
            ["1111", "2222"],
            [],
            [EXIT_CLEAN, EXIT_INCONCLUSIVE],
            EXIT_INCONCLUSIVE,
            ["1111", "2222"],
        ),
        (
            ["1111", "2222"],
            [],
            [EXIT_FAILED, EXIT_INCONCLUSIVE],
            EXIT_FAILED,
            ["1111", "2222"],
        ),
    ],
    ids=[
        "filter-to-one",
        "filter-matches-none",
        "no-account-number",
        "inconclusive-beats-clean",
        "failed-beats-inconclusive",
    ],
)
def test_main_checks_chosen_accounts_and_returns_worst_status(
    run_main: Callable[[list[str | None], list[str]], int],
    mock_check_account: MagicMock,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
    last_fours: list[str | None],
    argv: list[str],
    statuses: list[int],
    expected: int,
    labels: list[str],
) -> None:
    """
    GIVEN: accounts with the given numbers and check results
    WHEN:  the script runs
    THEN:  only the chosen accounts are checked, the worst status is returned,
           and every tab and the browser are closed
    """
    mock_check_account.side_effect = statuses

    status = run_main(last_fours, argv)

    checked = [call.args[2] for call in mock_check_account.call_args_list]
    check.equal(status, expected)
    check.equal(checked, labels)
    check.equal(mock_session.close.call_count, len(last_fours))
    check.equal(mock_scraper.quit.call_count, 1)


####################################################################
#
def test_main_failed_sign_in_is_inconclusive(
    run_main: Callable[[list[str | None], list[str]], int],
    mock_check_account: MagicMock,
    mock_scraper: MagicMock,
) -> None:
    """
    GIVEN: a sign-in that fails
    WHEN:  the script runs
    THEN:  no account is checked, the result is inconclusive, and the browser
           is closed
    """
    mock_scraper.logged_in = False

    status = run_main(["1111"], [])

    check.equal(status, EXIT_INCONCLUSIVE)
    check.equal(mock_check_account.call_count, 0)
    check.equal(mock_scraper.quit.call_count, 1)
