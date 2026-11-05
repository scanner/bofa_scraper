#!/usr/bin/env python
#
"""Test how scrape_transactions() reports a row it cannot read."""

# system imports
from collections.abc import Callable
from unittest.mock import MagicMock

# 3rd party imports
import pytest
import pytest_check as check
from selenium.common.exceptions import StaleElementReferenceException

# Project imports
from bofa_scraper import RowParseError, ScrapeSession

ROW_HTML = "<tr class='activity-row'>synthetic row</tr>"


####################################################################
#
@pytest.fixture
def make_row() -> Callable[..., MagicMock]:
    """
    Factory for a mock transaction row.

    Takes the text of each money cell. Blank cells report the textContent
    'hidden value' and are not displayed, like a cell hidden on the page.
    """

    def make(amount: str = "-$1.00", balance: str = "$2.00") -> MagicMock:
        def cell(text: str) -> MagicMock:
            element = MagicMock(text=text)
            element.get_attribute.return_value = text or "hidden value"
            element.is_displayed.return_value = bool(text)
            return element

        cells = {
            "amount-cell": cell(amount),
            "avail-balance-cell": cell(balance),
        }
        row = MagicMock()
        row.find_element.side_effect = lambda _by, name: cells.get(
            name, MagicMock(text="text")
        )
        row.find_elements.return_value = []
        row.get_attribute.return_value = ROW_HTML
        return row

    return make


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
    make_row: Callable[..., MagicMock],
    bad_cell: str,
    cells: dict[str, str],
) -> None:
    """
    GIVEN: a page whose second row has a blank money cell
    WHEN:  the transactions are scraped
    THEN:  the error names the row and cell, reports how the cell reads, and
           keeps the row's HTML out of the message
    """
    driver.find_elements.return_value = [make_row(), make_row(**cells)]
    with pytest.raises(RowParseError) as excinfo:
        session.scrape_transactions()

    error = excinfo.value
    check.equal(error.row_number, 2)
    check.equal(error.cell, bad_cell)
    check.equal(error.text, "")
    check.equal(error.text_content, "hidden value")
    check.is_false(error.displayed)
    check.equal(error.row_html, ROW_HTML)
    check.is_in(bad_cell, str(error))
    check.is_not_in("synthetic row", str(error))


####################################################################
#
def test_row_replaced_during_diagnosis_still_names_row_and_cell(
    session: ScrapeSession,
    driver: MagicMock,
    make_row: Callable[..., MagicMock],
) -> None:
    """
    GIVEN: a row the page replaces just after its blank cell's text is read
    WHEN:  the transactions are scraped
    THEN:  the error still names the row and cell, with the details it could
           not read left as None
    """
    row = make_row(amount="")
    stale = StaleElementReferenceException()
    row.get_attribute.side_effect = stale
    cell = row.find_element(None, "amount-cell")
    row.find_element.side_effect = None
    row.find_element.return_value = cell
    cell.get_attribute.side_effect = stale
    cell.is_displayed.side_effect = stale
    driver.find_elements.return_value = [row]

    with pytest.raises(RowParseError) as excinfo:
        session.scrape_transactions()

    error = excinfo.value
    check.equal((error.row_number, error.cell), (1, "amount-cell"))
    check.is_none(error.text_content)
    check.is_none(error.displayed)
    check.is_none(error.row_html)


####################################################################
#
def test_bad_row_stores_no_transactions(
    session: ScrapeSession,
    driver: MagicMock,
    account: MagicMock,
    make_row: Callable[..., MagicMock],
) -> None:
    """
    GIVEN: a page with a good row followed by a bad one
    WHEN:  the transactions are scraped
    THEN:  nothing is stored on the account
    """
    driver.find_elements.return_value = [make_row(), make_row(amount="")]
    with pytest.raises(RowParseError):
        session.scrape_transactions()
    account.set_transactions.assert_not_called()
