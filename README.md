# bofa_scraper

Bank of America does not currently have a consumer-facing API for requesting
balance and transaction data. The goal of this project is to make personal
data accessible to allow for automated budgeting projects.

This project includes a web scraper written in [Python](https://www.python.org/) using
[Selenium](https://www.selenium.dev/). As such, this project is not capable
of fetching any data that could not be collected by a human in a web browser.
**Please always take care to secure your account credentials!**


# Getting Started
1. Install the package.
```
pip install bofa_scraper
```
2. Install Firefox. Selenium Manager automatically downloads the matching
   GeckoDriver -- no manual driver installation is required.


# Usage

## Example script

[`examples/account_overview.py`](examples/account_overview.py) shows the
complete lifecycle: login, fetching accounts, scraping transactions, fetching
transaction details, and printing a summary with [Rich](https://github.com/Texel/rich).

```
uv run ./examples/account_overview.py
```

## API

Initialize and log in:
```python
from bofa_scraper import BofAScraper

scraper = BofAScraper(
    'YOUR_BankOfAmerica_ONLINE_ID',
    'YOUR_BankOfAmerica_PASSCODE',
    wait_duration=20,    # longest wait for a page element, defaults to 20
    timeout_duration=5,  # pause after each transaction details dialog, defaults to 5
    headless=True,       # run browser invisibly, defaults to True
    verbose=True,        # log progress to stdout, defaults to True
)

scraper.login()  # handles 2FA interactively if required
```

Fetch accounts and scrape transactions:
```python
# get_accounts() returns one Account per tile on the overview page.
# Name and balance are pre-populated; transactions are not fetched until
# you open a scraping session.
accounts = scraper.get_accounts()
accounts[0].get_name()       # str; the account's nickname. Holds no part
                             #      of the account number.
accounts[0].get_balance()    # float; current balance
accounts[0].get_last_four()  # None until the account has been opened

# open_account() opens a new browser tab for the account's detail page and
# reads the last four digits of the account number there. The overview
# page does not show them, so to pick accounts by number, open each one
# and check before scraping it.
session = scraper.open_account(accounts[0])
session.get_last_four()      # str | None; e.g. "1234". Also stored on the
                             #      Account: accounts[0].get_last_four()

# scrape_transactions() reads all visible rows and stores them on the
# Account object.  Call load_more_transactions() first to load older rows.
# close() closes the detail tab and returns focus to the overview tab.
(
    session
        .scrape_transactions()
        .load_more_transactions()   # click "View more transactions"
        .scrape_transactions()      # re-scrape to include newly loaded rows
        .close()
)

# Transactions are stored on the Account, most recent first.
transactions = accounts[0].get_transactions()
transactions[0].amount          # float; negative for debits
transactions[0].date            # str; "MM/DD/YYYY", or "Processing" for pending
transactions[0].desc            # str
transactions[0].type            # str; e.g. "Virtual Card", "Debit Card", "Deposit"
transactions[0].running_balance # float; available balance after this transaction
transactions[0].txn_hash        # str; BofA's internal transaction identifier.
                                #      Not stable across sessions -- do not use
                                #      as a persistent unique key.
transactions[0].has_details     # bool; True when a View/Edit link is present.
                                #      Only posted transactions have details;
                                #      pending/processing rows do not.
```

## Transaction details

Posted transactions expose a **View/Edit** dialog in the BofA UI. Calling
`get_transaction_details()` opens that dialog, extracts the fields, and closes
it. Only transactions where `has_details` is `True` support this call.

Because each call opens and closes a browser dialog, fetching details for many
transactions in a row adds real wall-clock time. Fetch only the details you
need -- for example, transactions that have appeared since your last run.

```python
session = scraper.open_account(accounts[0])
try:
    session.scrape_transactions()

    for txn in accounts[0].get_transactions():
        if not txn.has_details:
            continue  # pending/processing rows have no View/Edit link

        details = session.get_transaction_details(txn)  # dict[str, str] | None
        if details:
            print(details)
finally:
    session.close()
```

`get_transaction_details()` returns a `dict[str, str]` (or `None` if the
dialog cannot be opened). The canonical ordered list of known fields is
exported as `TRANSACTION_DETAIL_FIELDS` -- a `list[tuple[str, str]]` of
`(key, label)` pairs in the order they appear in the BofA dialog:

```python
from bofa_scraper import TRANSACTION_DETAIL_FIELDS

for key, label in TRANSACTION_DETAIL_FIELDS:
    print(f"{key}: {details.get(key, '(not present)')}")
```

Fields returned by `get_transaction_details()`:

| Key                      | Example value                                          | Notes                           |
|--------------------------|--------------------------------------------------------|---------------------------------|
| `posting_date`           | `'May 28, 2026'`                                       |                                 |
| `description`            | `'Corner Market'`                                      | User-editable label             |
| `type`                   | `'Virtual Card'`                                       |                                 |
| `status`                 | `'Cleared'`                                            |                                 |
| `amount`                 | `'-$14.70'`                                            | Raw string as shown in dialog   |
| `raw_description`        | `'CORNER MARKET 05/26 MOBILE PURCHASE SPRINGFIELD IL'` | BofA's original merchant string |
| `merchant_category`      | `'Grocery Stores and Supermarkets'`                    |                                 |
| `merchant_category_code` | `'5411'`                                               | ISO 18245 MCC                   |
| `merchant_information`   | `'SPRINGFIELD, IL'`                                    |                                 |
| `merchant_name`          | `'CORNER MARKET'`                                      | User-editable                   |
| `transaction_category`   | `'Groceries : Groceries'`                              | User-editable                   |
| `virtual_card_number`    | `'XXXX-XXXX-XXXX-1439'`                                | Virtual Card transactions only  |
| `phone_number`           | `'XXX-XXX-1439'`                                       | Masked; not always present      |
| `purchaser`              | `'JANE DOE'`                                           | Cardholder; not always present  |
| `online_purchase`        | `'Y'`                                                  | Online purchases only           |

Fields not present in a particular transaction's dialog are omitted from the
returned dict. Always use `dict.get()` rather than direct indexing.

### Raw HTML probe

If you need to inspect BofA's actual dialog DOM (e.g. to diagnose a missing
field or verify the parser is working correctly), use
`get_transaction_detail_html()` instead. It opens the same dialog and returns
its `outerHTML` as a string without attempting to parse it:

```python
html = session.get_transaction_detail_html(txn)
print(html)
```

Clean up:
```python
scraper.quit()  # closes the browser process
```


# Development

```
make test      # run the test suite
make lint      # install the pre-commit hook and run all checks
```

The tests use only synthetic inputs built from the package's own constants;
they do not contact Bank of America.

## When the site changes

`tools/dump_pages.py` signs in with a visible browser and saves the rendered
page, a screenshot, and a digest at each step of the usual flow (overview,
account activity, "View more", transaction details). Pass `--manual` to
capture pages you navigate to yourself.

```
uv run tools/dump_pages.py
```

`tools/digest_page.py` turns a saved page into a short Markdown summary of its
dialogs, links, buttons, repeated rows, and structure, for comparing against
the selectors the scraper uses. `dump_pages.py` runs it on each capture.

Captures are written under `analysis/`, which is not stored in git.


# Security & Licensing
This project is licensed under the GNU General Public License 3.0 (GPLv3).

This project is intended for PERSONAL USE ONLY to document/calculate finances.
**Please take security into account when handling financial credentials.**
