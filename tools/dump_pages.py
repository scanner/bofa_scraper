#!/usr/bin/env python
#
"""
Log in to Bank of America and capture rendered pages for analysis.

Each capture is a directory under 'analysis/<timestamp>/' holding:

- page.html        the rendered DOM ('document.documentElement.outerHTML')
- page.digest.md   the summary written by tools/digest_page.py
- screenshot.png   a full-page screenshot
- meta.txt         URL, title and capture time
- error.txt        the traceback, when the step that led here failed

Two modes:

- Auto (default): after login, capture the overview, the opened Accounts
  menu, each account's activity page, the activity page after 'View more',
  a transaction details dialog, and a 'Processing' info popup. A step that
  fails is recorded and the run continues, so a capture of what broke is
  still made.
- Manual ('--manual'): after login, navigate in the browser yourself and
  press Enter at the prompt to capture whatever is on screen.

Usage:
    uv run tools/dump_pages.py [--manual] [--accounts N] [--wait SECONDS]

Credentials are read from the BOFA_ID and BOFA_PASSCODE environment
variables, or prompted for. The browser is visible unless '--headless' is
given.
"""

# system imports
import argparse
import getpass
import logging
import os
import sys
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

# 3rd party imports
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

# Project imports
from bofa_scraper import BofAScraper
from bofa_scraper.util import Timeout
from digest_page import digest, digest_path

logger = logging.getLogger("dump_pages")

ANALYSIS_DIR = Path(__file__).resolve().parent.parent / "analysis"

# Account links in the Accounts menu, then any account-details redirect link.
ACCOUNT_LINK_SELECTORS = [
    'a[id^="nav_accounts_categorytype-"]',
    'a[href*="target=acctdetails"]',
]


########################################################################
########################################################################
#
class Capturer:
    """Saves numbered page captures into one run directory."""

    ####################################################################
    #
    def __init__(self, driver: WebDriver, run_dir: Path):
        """
        Args:
            driver:  The logged-in WebDriver.
            run_dir: Directory that receives one subdirectory per capture.
        """
        self.driver = driver
        self.run_dir = run_dir
        self.count = 0

    ####################################################################
    #
    def capture(self, name: str, error: str | None = None) -> Path:
        """
        Save the current page as the next numbered capture.

        Each artifact is saved independently, so a failed screenshot still
        leaves the DOM and digest behind.

        Args:
            name:  Short label for the capture directory.
            error: Traceback text from the step that led here, if it failed.

        Returns:
            The capture directory.
        """
        self.count += 1
        out = self.run_dir / f"{self.count:02d}-{name}"
        out.mkdir(parents=True, exist_ok=True)
        if error:
            (out / "error.txt").write_text(error)

        try:
            (out / "meta.txt").write_text(
                f"url: {self.driver.current_url}\n"
                f"title: {self.driver.title}\n"
                f"captured: {datetime.now().isoformat(timespec='seconds')}\n"
            )
        except WebDriverException as e:
            logger.warning("%s: could not read URL/title: %r", name, e)

        page = out / "page.html"
        try:
            html = self.driver.execute_script(
                "return document.documentElement.outerHTML"
            )
            page.write_text(f"<!doctype html>\n{html}")
        except WebDriverException as e:
            logger.warning("%s: could not read DOM: %r", name, e)

        try:
            self.driver.save_full_page_screenshot(str(out / "screenshot.png"))
        except WebDriverException as e:
            logger.warning("%s: could not take screenshot: %r", name, e)

        if page.exists():
            try:
                digest_path(page).write_text(digest(page))
            except Exception:
                logger.warning("%s: digest failed", name, exc_info=True)
                (out / "digest-error.txt").write_text(traceback.format_exc())

        logger.info("Captured %s%s", out, " (step failed)" if error else "")
        return out

    ####################################################################
    #
    def step(self, name: str, action: Callable[[], object]) -> bool:
        """
        Run one navigation action, then capture the page whether it worked.

        Args:
            name:   Label for the capture.
            action: Performs the navigation or click.

        Returns:
            True if the action completed without raising.
        """
        logger.info("Step: %s", name)
        try:
            action()
        except Exception:
            logger.warning("Step %s failed", name, exc_info=True)
            self.capture(name, error=traceback.format_exc())
            return False
        self.capture(name)
        return True


####################################################################
#
def settle() -> None:
    """Wait for the page's own JavaScript to fetch and render its data."""
    Timeout.timeout()


####################################################################
#
def js_click(driver: WebDriver, el: WebElement) -> None:
    """Click through JavaScript, which works on covered or hidden elements."""
    driver.execute_script("arguments[0].click();", el)
    settle()


####################################################################
#
def press_escape(driver: WebDriver) -> None:
    """Send Escape to close any open dialog; failures are only logged."""
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        settle()
    except WebDriverException as e:
        logger.warning("Escape failed: %r", e)


####################################################################
#
def find_by_text(
    driver: WebDriver, texts: list[str], tags: str = "a|button"
) -> WebElement:
    """
    Return the first visible element of the given tags whose text starts with
    one of the candidates.

    Prefix matching tolerates screen-reader text appended to a link, as in
    'View/Edit <merchant>'.

    Args:
        driver: The WebDriver.
        texts:  Candidate text prefixes, matched after whitespace
                normalization.
        tags:   '|'-separated tag names to consider.

    Raises:
        LookupError: If no visible element matches.
    """
    tag_test = " or ".join(f"self::{t}" for t in tags.split("|"))
    for text in texts:
        xpath = (
            f"//*[({tag_test}) and starts-with(normalize-space(), '{text}')]"
        )
        for el in driver.find_elements(By.XPATH, xpath):
            if el.is_displayed():
                return el
    raise LookupError(f"No visible {tags} with text in {texts!r}")


####################################################################
#
def account_links(driver: WebDriver) -> list[tuple[str, str]]:
    """
    Return (name, href) for each account link found on the page.

    The Accounts menu is usually collapsed, so names are read with
    textContent rather than the visible text.
    """
    seen: dict[str, str] = {}
    for css in ACCOUNT_LINK_SELECTORS:
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            href = el.get_attribute("href") or ""
            name = " ".join((el.get_attribute("textContent") or "").split())
            if href and href not in seen:
                seen[href] = name or f"account-{len(seen) + 1}"
        if seen:
            break
    return [(name, href) for href, name in seen.items()]


####################################################################
#
def run_auto(driver: WebDriver, cap: Capturer, max_accounts: int) -> None:
    """
    Walk the standard pages and capture each one.

    Args:
        driver:       The logged-in WebDriver, on the post-login page.
        cap:          Where captures go.
        max_accounts: Number of accounts whose activity pages are captured.
    """
    cap.capture("after-login")

    cap.step(
        "accounts-menu",
        lambda: js_click(driver, find_by_text(driver, ["Accounts"])),
    )
    links = account_links(driver)
    logger.info("Found %d account links", len(links))
    if not links:
        return

    for n, (name, href) in enumerate(links[:max_accounts], start=1):
        logger.info("Account %d: %s", n, name)

        def open_account(href: str = href) -> None:
            driver.get(href)
            settle()

        if not cap.step(f"activity-{n}", open_account):
            continue
        if n > 1:
            continue

        # Interactions are only captured on the first account; the rest
        # share its page layout.
        cap.step(
            "view-more",
            lambda: js_click(
                driver, find_by_text(driver, ["View more", "View More"])
            ),
        )
        cap.step(
            "txn-dialog",
            lambda: js_click(driver, find_by_text(driver, ["View/Edit"])),
        )
        press_escape(driver)
        cap.step(
            "processing-popup",
            lambda: js_click(driver, find_by_text(driver, ["Processing"])),
        )
        press_escape(driver)


####################################################################
#
def run_manual(cap: Capturer) -> None:
    """Capture the current page each time the user presses Enter."""
    print(
        "Navigate in the browser, then enter a short name and press Enter to "
        "capture the page. Enter 'q' to finish."
    )
    while True:
        name = input("capture name (blank for 'page', q to quit): ").strip()
        if name.lower() == "q":
            return
        cap.capture("-".join(name.split()) or "page")


####################################################################
#
def main() -> int:
    """Log in, capture pages, and leave the browser closed."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--manual",
        action="store_true",
        help="capture on demand instead of walking the standard pages",
    )
    parser.add_argument(
        "--accounts",
        type=int,
        default=1,
        help="number of accounts whose activity pages are captured (default 1)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=8,
        help="seconds to let each page render before capturing (default 8)",
    )
    parser.add_argument(
        "--headless", action="store_true", help="run the browser invisibly"
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

    scraper = BofAScraper(
        online_id, passcode, timeout_duration=args.wait, headless=args.headless
    )
    # BofAScraper adds its own handler; stop its messages printing twice.
    logging.getLogger("bofa_scraper").propagate = False
    try:
        cap = Capturer(scraper.driver, run_dir)
        try:
            scraper.login()
        except Exception:
            logger.warning("Login raised", exc_info=True)
            cap.capture("login-failed", error=traceback.format_exc())
            return 1
        # login() may report failure even after a successful login when the
        # landing URL changes, so capture regardless of logged_in.
        logger.info("login() reports logged_in=%s", scraper.logged_in)

        if args.manual:
            run_manual(cap)
        else:
            run_auto(scraper.driver, cap, args.accounts)
    finally:
        scraper.quit()

    print(f"Captures written to {run_dir}")
    return 0


########################################################################

if __name__ == "__main__":
    sys.exit(main())
