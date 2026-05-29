#!/usr/bin/env python
#
"""
Print a brief overview of each BofA account and its ten most recent
transactions.

Usage:
    uv run ./examples/account_overview.py

Credentials are read from the BOFA_ID and BOFA_PASSCODE environment
variables, or prompted interactively if not set.
"""

# system imports
import os
import sys

# 3rd party imports
from rich import box
from rich.console import Console
from rich.table import Table

# project imports
from bofa_scraper import BofAScraper

########################################################################

console = Console()


####################################################################


def main() -> None:
    """
    Log in to a Bank of America account and print an overview of each
    account and its ten most recent transactions.

    This function demonstrates the complete lifecycle of a bofa_scraper
    session:

    1.  **Construct BofAScraper** -- launches a Firefox WebDriver, navigates
        to bankofamerica.com, and waits for the page to load.  If
        ``headless=True`` (the default) the browser runs invisibly in the
        background.  Always call ``scraper.quit()`` when finished -- it
        closes the browser process.  Wrapping everything in a try/finally
        block guarantees this even when an exception is raised mid-run.

    2.  **Call scraper.login()** -- types the credentials into the sign-in
        form and submits it.  If BofA requires a one-time passcode (2FA),
        the library pauses and prints "input 2fa code:" to stdout; the user
        types the code and presses Enter.  After a successful login,
        ``scraper.logged_in`` is True and the driver is on the "My Accounts"
        overview page.

    3.  **Call scraper.get_accounts()** -- scrapes the overview page for
        account tiles and returns a list of ``Account`` objects.  Each
        ``Account`` holds the account name, current balance, and a reference
        to the underlying Selenium WebElement.  The WebElement reference is
        needed later to open the account's detail page, so the accounts must
        be collected *before* navigating away from the overview page.

    4.  **Call scraper.open_account(account)** -- opens a new browser tab
        and navigates it to that account's transaction detail page, returning
        a ``ScrapeSession``.  The original overview tab remains open in the
        background, which keeps the account WebElement references valid for
        other accounts.  Call ``session.close()`` to close the detail tab and
        return focus to the overview tab.

    5.  **Call session.scrape_transactions()** -- walks all visible
        transaction rows on the detail page and stores them on the
        ``Account`` object via ``account.set_transactions()``.  Transactions
        appear in the order BofA renders them (most recent first).  If you
        need older history, call ``session.load_more_transactions()`` before
        scraping; this clicks BofA's "View more transactions" button and
        waits for the page to reload.

    6.  **Call session.close()** -- closes the detail tab and switches the
        driver back to the overview tab so the next account can be opened.
        This must be called even if scraping fails, hence the try/finally.
    """
    online_id = os.environ.get("BOFA_ID") or console.input(
        "[bold]BofA Online ID:[/bold] "
    )
    passcode = os.environ.get("BOFA_PASSCODE") or console.input(
        "[bold]BofA Passcode:[/bold] ", password=True
    )

    # BofAScraper.__init__ launches Firefox and loads bankofamerica.com.
    # verbose=False suppresses the library's own logging output so that
    # the rich output below is the only thing printed to the terminal.
    # The browser stays open until scraper.quit() is called.
    scraper = BofAScraper(online_id, passcode, verbose=False)

    # Always quit the browser, even if something raises below.
    try:
        with console.status("[bold green]Logging in...[/bold green]"):
            # login() submits the sign-in form and handles 2FA interactively
            # when required.  It sets scraper.logged_in = True on success.
            scraper.login()

        if not scraper.logged_in:
            console.print("[bold red]Login failed.[/bold red]")
            sys.exit(1)

        # get_accounts() scrapes the overview page and returns one Account
        # per tile.  Each Account has the name and balance already populated.
        # The list is empty when not logged in.
        accounts = scraper.get_accounts()
        if not accounts:
            console.print("[yellow]No accounts found.[/yellow]")
            return

        for account in accounts:
            # open_account() opens a new tab for the account's detail page
            # and returns a ScrapeSession bound to that tab.  The overview
            # tab remains open so other accounts can be opened afterward.
            session = scraper.open_account(account)

            try:
                # scrape_transactions() reads all visible transaction rows
                # from the detail page and stores them on the Account object.
                # Call load_more_transactions() first if you need older rows.
                session.scrape_transactions()
            finally:
                # close() shuts the detail tab and returns driver focus to
                # the overview tab.  Must be called for every opened session.
                session.close()

            # --- display ---

            console.rule(f"[bold cyan]{account.get_name()}[/bold cyan]")
            console.print(
                f"  Balance: [bold green]${account.get_balance():,.2f}[/bold green]"
            )

            # get_transactions() returns the list populated by
            # scrape_transactions() above, most recent first.
            transactions = account.get_transactions()
            if not transactions:
                console.print("  [dim]No transactions.[/dim]\n")
                continue

            table = Table(
                box=box.SIMPLE_HEAD, show_footer=False, pad_edge=False
            )
            table.add_column("Date", style="dim", min_width=12)
            table.add_column("Description", no_wrap=False, max_width=40)
            table.add_column("Type", style="dim", min_width=8)
            table.add_column("Amount", justify="right", min_width=10)
            table.add_column(
                "Balance", justify="right", style="dim", min_width=10
            )

            for txn in transactions[:10]:
                amount_str = f"${txn.amount:,.2f}"
                amount_style = "green" if txn.amount >= 0 else "red"
                table.add_row(
                    txn.date,
                    txn.desc,
                    txn.type,
                    f"[{amount_style}]{amount_str}[/{amount_style}]",
                    f"${txn.running_balance:,.2f}",
                )

            console.print(table)
            console.print()

    finally:
        # quit() closes the browser process.  Skipping this leaks a Firefox
        # process even when the script exits normally.
        scraper.quit()


########################################################################

if __name__ == "__main__":
    main()
