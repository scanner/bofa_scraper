# bofa_scraper
![version](https://img.shields.io/pypi/v/bofa_scraper?color=blue)
![downloads](https://img.shields.io/pypi/dm/bofa_scraper?color=blue)

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
complete lifecycle: login, fetching accounts, scraping transactions, and
printing a summary with [Rich](https://github.com/Texel/rich).

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
    timeout_duration=5,  # seconds to wait for page loads, defaults to 5
    headless=True,       # run browser invisibly, defaults to True
    verbose=True,        # log progress to stdout, defaults to True
)

scraper.login()  # handles 2FA interactively if required
```

Fetch accounts and scrape transactions:
```python
# get_accounts() returns one Account per tile on the overview page.
# Balance is pre-populated; transactions are not fetched until you open
# a scraping session.
accounts = scraper.get_accounts()
accounts[0].get_name()     # str; account display name
accounts[0].get_balance()  # float; current balance

# open_account() opens a new browser tab for the account's detail page.
# scrape_transactions() reads all visible rows and stores them on the
# Account object.  Call load_more_transactions() first to load older rows.
# close() closes the detail tab and returns focus to the overview tab.
(
    scraper.open_account(accounts[0])
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
```

Clean up:
```python
scraper.quit()  # closes the browser process
```


# Security & Licensing
This project is licensed under the GNU General Public License 3.0 (GPLv3).

This project is intended for PERSONAL USE ONLY to document/calculate finances.
**Please take security into account when handling financial credentials.**
