#!/usr/bin/env python
#
"""
Check whether accounts scrape cleanly, and record the page when one does not.

Runs each account through the usual scrape: scrape the rows, click 'View
more', and scrape again. When a scrape fails, this saves a capture of the page
under 'analysis/<timestamp>/', waits, and scrapes the same page again. A cell
that reads correctly the second time points to a render race rather than a
blank cell. The run then moves on to the next account.

Each failure's capture directory holds what tools/dump_pages.py saves, with
the error in error.txt, plus row.html, the failing row's outerHTML, when the
failure was a row that could not be parsed. These files hold real account
data.

Usage:
    uv run tools/check_scrape.py [--last-four 1234] [--no-headless]

Credentials are read from the BOFA_ID and BOFA_PASSCODE environment
variables, or prompted for.

Exit status:
    0  every account checked scraped cleanly and had rows
    1  a scrape failed
    2  the check was inconclusive: sign-in failed, no account was checked, or
       an account showed no rows
"""

# system imports
import argparse
import getpass
import logging
import os
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

# 3rd party imports
from selenium.common.exceptions import NoSuchElementException

# Project imports
from bofa_scraper import BofAScraper, RowParseError, ScrapeSession
from dump_pages import ANALYSIS_DIR, Capturer

logger = logging.getLogger("check_scrape")

EXIT_CLEAN = 0
EXIT_FAILED = 1
EXIT_INCONCLUSIVE = 2


####################################################################
#
def scrape_account(
    session: ScrapeSession, on_stage: Callable[[str], None]
) -> None:
    """
    Scrape, click 'View more', and scrape again.

    An account with no 'View more' button stops after the first scrape.

    Args:
        session:  The open account.
        on_stage: Called with the name of each stage as it starts.
    """
    on_stage("first-scrape")
    session.scrape_transactions()
    on_stage("view-more")
    try:
        session.load_more_transactions()
    except NoSuchElementException:
        logger.info("No 'View more' button")
        return
    on_stage("second-scrape")
    session.scrape_transactions()


####################################################################
#
def record_failure(cap: Capturer, name: str, error: Exception, tb: str) -> Path:
    """
    Save the page and the failing row, if the failure names one.

    Args:
        cap:   Where captures go.
        name:  Label for the capture.
        error: The exception the scrape raised.
        tb:    Its formatted traceback.

    Returns:
        The capture directory.
    """
    out = cap.capture(name, error=tb)
    if isinstance(error, RowParseError) and error.row_html is not None:
        (out / "row.html").write_text(error.row_html)
    return out


####################################################################
#
def recheck(
    session: ScrapeSession, cap: Capturer, name: str, wait: float
) -> None:
    """
    Wait, then scrape the same page again and report the result.

    Args:
        session: The open account, still on the page that failed.
        cap:     Where captures go.
        name:    Label for the capture.
        wait:    Seconds to wait before scraping again.
    """
    logger.info("Scraping the same page again in %g seconds", wait)
    time.sleep(wait)
    try:
        session.scrape_transactions()
    except Exception as e:
        logger.error("Still fails after %g seconds: %s", wait, e)
        record_failure(cap, name, e, traceback.format_exc())
        return
    logger.warning(
        "Scraped cleanly after %g seconds: %d rows",
        wait,
        len(session.account.get_transactions()),
    )
    cap.capture(name)


####################################################################
#
def check_account(
    session: ScrapeSession, cap: Capturer, label: str, recheck_wait: float
) -> int:
    """
    Scrape one open account and record any failure.

    Args:
        session:      The open account.
        cap:          Where captures go.
        label:        Short name for this account's captures.
        recheck_wait: Seconds to wait before scraping a failed page again.

    Returns:
        An exit status for this account.
    """
    stage = ""

    def set_stage(name: str) -> None:
        nonlocal stage
        stage = name

    try:
        scrape_account(session, set_stage)
    except Exception as e:
        logger.error("%s failed at %s: %s", label, stage, e)
        record_failure(cap, f"{label}-{stage}", e, traceback.format_exc())
        recheck(session, cap, f"{label}-recheck", recheck_wait)
        return EXIT_FAILED

    rows = len(session.account.get_transactions())
    if rows == 0:
        logger.warning("%s showed no rows; nothing was checked", label)
        cap.capture(f"{label}-no-rows")
        return EXIT_INCONCLUSIVE
    logger.info("%s scraped cleanly: %d rows", label, rows)
    return EXIT_CLEAN


####################################################################
#
def main() -> int:
    """Sign in, check the chosen accounts, and return the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--last-four",
        help="check only the account whose number ends in these digits",
    )
    parser.add_argument(
        "--recheck-wait",
        type=float,
        default=10,
        help="seconds to wait before scraping a failed page again (default 10)",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run the browser invisibly (default)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="run directory (default analysis/<timestamp>/)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    online_id = os.environ.get("BOFA_ID") or input("BofA Online ID: ")
    passcode = os.environ.get("BOFA_PASSCODE") or getpass.getpass(
        "BofA Passcode: "
    )
    run_dir = args.out or ANALYSIS_DIR / datetime.now().strftime(
        "%Y-%m-%dT%H%M%S"
    )

    scraper = BofAScraper(online_id, passcode, headless=args.headless)
    # BofAScraper adds its own handler; stop its messages printing twice.
    logging.getLogger("bofa_scraper").propagate = False
    statuses: list[int] = []
    try:
        cap = Capturer(scraper.driver, run_dir)
        scraper.login()
        if not scraper.logged_in:
            logger.error("Sign-in failed")
            cap.capture("login-failed")
            return EXIT_INCONCLUSIVE

        for n, account in enumerate(scraper.get_accounts(), start=1):
            session = scraper.open_account(account)
            try:
                last_four = session.get_last_four()
                if args.last_four and last_four != args.last_four:
                    continue
                statuses.append(
                    check_account(
                        session,
                        cap,
                        last_four or f"account-{n}",
                        args.recheck_wait,
                    )
                )
            finally:
                session.close()
    finally:
        scraper.quit()

    if not statuses:
        logger.error("No account was checked")
        return EXIT_INCONCLUSIVE
    if cap.count:
        print(f"Captures written to {run_dir}")
    if EXIT_FAILED in statuses:
        return EXIT_FAILED
    return max(statuses)


########################################################################

if __name__ == "__main__":
    sys.exit(main())
