#!/usr/bin/env python
#
"""Test tools/digest_page.py on small synthetic pages."""

# system imports
from collections.abc import Callable
from pathlib import Path

# 3rd party imports
import pytest
import pytest_check as check
from bs4 import BeautifulSoup, Tag

# Project imports
from digest_page import digest, looks_hidden, normalize, short_href

HASH_A = "0123456789abcdef" * 4
HASH_B = "FEDCBA9876543210" * 4


####################################################################
#
@pytest.mark.parametrize(
    "token,expected",
    [
        (f"txn-{HASH_A}", "txn-HEX"),
        (f"txn-{HASH_B}", "txn-HEX"),
        ("account-12_id", "account-N_id"),
        ("cafe", "cafe"),
    ],
)
def test_normalize(token: str, expected: str) -> None:
    """
    GIVEN: an id or class token
    WHEN:  it is normalized
    THEN:  long hex runs (either case) and digit runs are replaced, and
           ordinary words are left alone
    """
    assert normalize(token) == expected


####################################################################
#
@pytest.mark.parametrize(
    "href,expected",
    [
        (
            "/brain/redirect.go?target=x&adx=SECRET",
            "/brain/redirect.go?target&adx",
        ),
        ("https://example.com/a/b", "example.com/a/b"),
        ("javascript:void(0);", "javascript:void(0);"),
    ],
)
def test_short_href(href: str, expected: str) -> None:
    """
    GIVEN: a link href
    WHEN:  it is shortened for the digest
    THEN:  query values are dropped, keeping parameter names, and
           non-navigating hrefs are kept as they are
    """
    assert short_href(href) == expected


####################################################################
#
@pytest.mark.parametrize(
    "html,hidden",
    [
        ('<div><p id="t">x</p></div>', False),
        ('<div hidden><p id="t">x</p></div>', True),
        ('<div aria-hidden="true"><p id="t">x</p></div>', True),
        ('<div class="row hidden"><p id="t">x</p></div>', True),
    ],
)
def test_looks_hidden(html: str, hidden: bool) -> None:
    """
    GIVEN: an element whose ancestor may be marked hidden in markup
    WHEN:  it is checked
    THEN:  the hidden attribute, aria-hidden and a 'hidden' class count
    """
    el = BeautifulSoup(html, "lxml").find(id="t")
    assert isinstance(el, Tag)
    assert looks_hidden(el) is hidden


####################################################################
#
@pytest.fixture
def table_page(page_file: Callable[[str], Path]) -> Path:
    """
    A page with three hash-classed rows inside single-child wrappers.

    Each row has a link whose href carries a query value that must not
    appear in the digest. A hidden dialog with a form field follows the
    table.
    """
    rows = "".join(
        f'<tr class="activity-row txn-{h}"><td class="date-cell">day {n}</td>'
        f'<td><a class="view" href="/details?token=SECRET{n}">Open {n}</a>'
        "</td></tr>"
        for n, h in enumerate((HASH_A, HASH_B, HASH_A[::-1]))
    )
    dialog = (
        '<div role="dialog" aria-hidden="true">'
        '<input id="amount" type="text" name="amount"></div>'
    )
    return page_file(
        f"<div><div><table><tbody>{rows}</tbody></table></div></div>{dialog}"
    )


####################################################################
#
def test_digest_summarizes_rows(table_page: Path) -> None:
    """
    GIVEN: a page of hash-classed table rows with links
    WHEN:  it is digested
    THEN:  the rows form one repeated group, the links one grouped line,
           wrappers fold onto one outline line, the dialog and its field
           are listed as hidden, and scripts and query values are left out
    """
    text = digest(table_page)

    check.is_in("`tr.activity-row.txn-HEX` x3 under `tbody`", text)
    check.is_in("`a.view` [href='/details?token']  x3, first:", text)
    check.is_in("  div > div > table > tbody", text)
    check.is_in("- Title: Test page", text)
    check.is_in("### `div` (hidden?)", text)
    check.is_in("`input#amount` [type='text' name='amount']  (hidden?)", text)
    check.is_not_in("SECRET", text)
    check.is_not_in("script text", text)
