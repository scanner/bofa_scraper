#!/usr/bin/env python
#
"""Test how scrape_transactions() reads rows and reports one it cannot read."""

# system imports
from collections.abc import Callable
from unittest.mock import MagicMock

# 3rd party imports
import pytest
import pytest_check as check
from selenium.common.exceptions import StaleElementReferenceException

# Project imports
from bofa_scraper import RowParseError, ScrapeSession


####################################################################
#
@pytest.fixture
def row_html() -> str:
    """The outerHTML of a transaction row, with text a test can look for."""
    return "<tr class='activity-row'>synthetic row</tr>"


####################################################################
#
@pytest.fixture
def make_row(row_html: str) -> Callable[..., MagicMock]:
    """
    Factory for a mock transaction row.

    Takes the text of each money cell and the hash on the row's View/Edit
    link; a row with no hash has no link, like a pending row, and carries the
    hash 'pending' in its class. Blank cells report the textContent 'hidden
    value' and are not displayed, like a cell hidden on the page.
    """

    def make(
        amount: str = "-$1.00",
        balance: str = "$2.00",
        link_hash: str | None = None,
    ) -> MagicMock:
        def cell(text: str) -> MagicMock:
            element = MagicMock(text=text)
            element.get_attribute.return_value = text or "hidden value"
            element.is_displayed.return_value = bool(text)
            return element

        cells = {
            "amount-cell": cell(amount),
            "avail-balance-cell": cell(balance),
        }
        attributes = {
            "class": "activity-row txn-pending",
            "outerHTML": row_html,
        }
        row = MagicMock()
        row.find_element.side_effect = lambda _by, name: cells.get(
            name, MagicMock(text="text")
        )
        row.find_elements.return_value = (
            [MagicMock(get_attribute=MagicMock(return_value=link_hash))]
            if link_hash
            else []
        )
        row.get_attribute.side_effect = attributes.get
        return row

    return make


####################################################################
#
@pytest.fixture
def replaced_row() -> MagicMock:
    """
    A row the page replaces just after its blank amount cell's text is read.

    Every later read of the row or the cell raises.
    """
    stale = StaleElementReferenceException()
    cell = MagicMock(text="")
    cell.get_attribute.side_effect = stale
    cell.is_displayed.side_effect = stale
    row = MagicMock()
    row.find_element.return_value = cell
    row.get_attribute.side_effect = stale
    return row


####################################################################
#
def test_scrape_stores_posted_and_pending_rows(
    session: ScrapeSession,
    driver: MagicMock,
    account: MagicMock,
    make_row: Callable[..., MagicMock],
) -> None:
    """
    GIVEN: a page with a posted row and a pending row
    WHEN:  the transactions are scraped
    THEN:  both are stored in page order, with their amounts and balances, and
           each row's hash comes from its link or its class
    """
    driver.find_elements.return_value = [
        make_row("-$1,234.56", "$10.00", link_hash="posted"),
        make_row("$7.00", "$20.00"),
    ]

    session.scrape_transactions()

    posted, pending = account.set_transactions.call_args.args[0]
    check.equal((posted.amount, posted.running_balance), (-1234.56, 10.0))
    check.equal((posted.txn_hash, posted.has_details), ("posted", True))
    check.equal((pending.amount, pending.running_balance), (7.0, 20.0))
    check.equal((pending.txn_hash, pending.has_details), ("pending", False))


####################################################################
#
@pytest.mark.parametrize(
    "bad_cell,cells",
    [
        ("amount-cell", {"amount": ""}),
        ("avail-balance-cell", {"balance": ""}),
    ],
)
def test_blank_money_cell_names_row_and_cell(
    session: ScrapeSession,
    driver: MagicMock,
    account: MagicMock,
    make_row: Callable[..., MagicMock],
    row_html: str,
    bad_cell: str,
    cells: dict[str, str],
) -> None:
    """
    GIVEN: a page whose second row has a blank money cell
    WHEN:  the transactions are scraped
    THEN:  the message reports the row, the cell and how the cell reads, the
           row's HTML is kept out of it, and no rows are stored
    """
    driver.find_elements.return_value = [make_row(), make_row(**cells)]
    with pytest.raises(RowParseError) as excinfo:
        session.scrape_transactions()

    error = excinfo.value
    message = str(error)
    check.equal(error.row_html, row_html)
    check.is_in("row 2", message)
    check.is_in(bad_cell, message)
    check.is_in("text=''", message)
    check.is_in("textContent='hidden value'", message)
    check.is_in("displayed=False", message)
    check.is_not_in("synthetic row", message)
    account.set_transactions.assert_not_called()


####################################################################
#
def test_row_replaced_during_diagnosis_still_names_row_and_cell(
    session: ScrapeSession, driver: MagicMock, replaced_row: MagicMock
) -> None:
    """
    GIVEN: a row the page replaces just after its blank cell's text is read
    WHEN:  the transactions are scraped
    THEN:  the error still names the row and cell, with the details it could
           not read left as None
    """
    driver.find_elements.return_value = [replaced_row]

    with pytest.raises(RowParseError) as excinfo:
        session.scrape_transactions()

    error = excinfo.value
    check.equal((error.row_number, error.cell), (1, "amount-cell"))
    check.is_none(error.text_content)
    check.is_none(error.displayed)
    check.is_none(error.row_html)
