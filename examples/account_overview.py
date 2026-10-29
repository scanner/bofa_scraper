#!/usr/bin/env python
#
"""
Print a brief overview of each BofA account and its ten most recent
transactions, including the expanded transaction details from the View/Edit
dialog for each posted transaction.

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
from bofa_scraper import TRANSACTION_DETAIL_FIELDS, BofAScraper
from bofa_scraper.account import Transaction

########################################################################

console = Console()

# Fields to show in the detail block, as a subset of TRANSACTION_DETAIL_FIELDS.
# 'type' and 'amount' are already in the summary table above, so they are
# omitted here to avoid redundancy.
_SKIP_IN_DETAIL = {"type", "amount"}
_DETAIL_FIELDS = [
    (key, label)
    for key, label in TRANSACTION_DETAIL_FIELDS
    if key not in _SKIP_IN_DETAIL
]


####################################################################


def _print_transaction_details(
    txn: Transaction, details: dict[str, str]
) -> None:
    """
    Print the detail block for a single transaction.

    Shows the transaction header line then a two-column table of the detail
    fields that are present in the dict.

    Args:
        txn:     The Transaction whose summary line to print as a header.
        details: Dict returned by ScrapeSession.get_transaction_details().
    """
    amount_style = "green" if txn.amount >= 0 else "red"
    console.print(
        f"  [dim]{txn.date}[/dim]  {txn.desc[:60]}"
        f"  [{amount_style}]${txn.amount:,.2f}[/{amount_style}]"
    )

    table = Table(
        box=box.SIMPLE,
        show_header=False,
        show_footer=False,
        pad_edge=True,
        padding=(0, 1),
    )
    table.add_column("Field", style="dim", min_width=22, no_wrap=True)
    table.add_column("Value", no_wrap=False, max_width=60)

    for key, label in _DETAIL_FIELDS:
        value = details.get(key)
        if value:
            table.add_row(label, value)

    # Surface any fields the parser found that aren't in _DETAIL_FIELDS.
    known = {k for k, _ in _DETAIL_FIELDS} | {"type", "amount", "_raw"}
    for key, value in details.items():
        if key not in known:
            table.add_row(key, value)

    console.print(table)


####################################################################


def main() -> None:
    """
    Log in to Bank of America and print an overview of each account.

    For each account, shows a summary table of the ten most recent
    transactions followed by the expanded View/Edit dialog details for each
    of those transactions that has a details link (posted transactions only;
    pending/processing rows are skipped).

    Session lifecycle:
      - BofAScraper opens a Firefox window and loads bankofamerica.com.
      - login() submits credentials and handles 2FA interactively.
      - get_accounts() scrapes the overview page; each Account carries name
        and balance only -- transactions are not fetched until a session is
        opened.
      - open_account() opens a second tab for that account's detail page.
        The overview tab stays open to keep Account WebElement refs valid.
      - scrape_transactions() reads all visible rows and stores them on the
        Account; call load_more_transactions() first to include older rows.
      - get_transaction_details() opens and closes the View/Edit dialog for
        a single transaction; call it inside the session before close().
      - session.close() shuts the detail tab and returns focus to the
        overview tab; must be called even on error.
      - scraper.quit() closes the browser process; always called in finally.
    """
    online_id = os.environ.get("BOFA_ID") or console.input(
        "[bold]BofA Online ID:[/bold] "
    )
    passcode = os.environ.get("BOFA_PASSCODE") or console.input(
        "[bold]BofA Passcode:[/bold] ", password=True
    )

    scraper = BofAScraper(online_id, passcode, verbose=False)

    try:
        with console.status("[bold green]Logging in...[/bold green]"):
            scraper.login()

        if not scraper.logged_in:
            console.print("[bold red]Login failed.[/bold red]")
            sys.exit(1)

        accounts = scraper.get_accounts()
        if not accounts:
            console.print("[yellow]No accounts found.[/yellow]")
            return

        for account in accounts:
            session = scraper.open_account(account)

            # Fetch transactions and their details inside the session so the
            # browser tab is still open when we call get_transaction_details().
            top_txns: list[Transaction] = []
            all_details: list[dict[str, str] | None] = []
            try:
                session.scrape_transactions()
                top_txns = account.get_transactions()[:10]
                with console.status(
                    f"[dim]Fetching details for {account.get_name()}...[/dim]"
                ):
                    for txn in top_txns:
                        all_details.append(
                            session.get_transaction_details(txn)
                            if txn.has_details
                            else None
                        )
            finally:
                session.close()

            # --- display ---

            console.rule(
                f"[bold cyan]{account.get_name()} "
                f"...{account.get_last_four() or '????'}[/bold cyan]"
            )
            console.print(
                f"  Balance: [bold green]${account.get_balance():,.2f}[/bold green]"
            )

            if not top_txns:
                console.print("  [dim]No transactions.[/dim]\n")
                continue

            # Summary table.
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

            for txn in top_txns:
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

            # Per-transaction detail blocks.
            any_details = any(d is not None for d in all_details)
            if any_details:
                console.print("\n[bold]Transaction Details[/bold]")
                for txn, details in zip(top_txns, all_details):
                    if details is not None:
                        _print_transaction_details(txn, details)

            console.print()

    finally:
        scraper.quit()


########################################################################

if __name__ == "__main__":
    main()
