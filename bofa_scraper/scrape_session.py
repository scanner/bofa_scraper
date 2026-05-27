import logging

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from .account import Account, Transaction
from .util import Timeout

logger = logging.getLogger(__name__)


class ScrapeSession:
    driver: webdriver.Firefox
    account: Account

    def __init__(self, driver: webdriver.Firefox, account: Account):
        self.driver = driver
        self.account = account

        logger.info(
            "Starting scraping session for account %s", account.get_name()
        )
        url = (
            self.account.get_element()
            .find_element(By.TAG_NAME, "a")
            .get_attribute("href")
        )
        if url is None:
            raise ValueError(
                f"Account {account.get_name()!r} has no href on its link element"
            )
        self.driver.execute_script("window.open()")
        self.driver.switch_to.window(self.driver.window_handles[1])
        self.driver.get(url)
        Timeout.timeout()
        self.dismiss_dialog()
        logger.info("Tab opened for account %s", account.get_name())

    def dismiss_dialog(self) -> bool:
        """
        Dismiss any modal dialog that may be blocking the page.

        Tries several XPath patterns for common BofA OK/Continue buttons.
        If none match, prompts the user to dismiss it manually and waits for
        Enter before continuing. Returns True if a dialog was dismissed (auto
        or manual), False if no dialog was detected.
        """
        xpaths = [
            '//*[@id="gotItButton"]',
            '//button[normalize-space()="Got it"]',
            '//button[normalize-space()="Got it!"]',
            '//button[normalize-space()="OK"]',
            '//button[normalize-space()="Ok"]',
            '//button[normalize-space()="Continue"]',
            '//a[normalize-space()="OK"]',
            '//a[normalize-space()="Ok"]',
        ]
        for xpath in xpaths:
            for el in self.driver.find_elements(By.XPATH, xpath):
                if el.is_displayed():
                    logger.info("Dismissing dialog via: %s", xpath)
                    el.click()
                    Timeout.timeout()
                    return True
        return False

    def wait_for_dialog_dismissal(self) -> None:
        """
        Pause and wait for the user to manually dismiss a dialog.

        Call this when dismiss_dialog() cannot find the button automatically.
        The scraper will hold here until the user presses Enter, giving time
        to inspect and dismiss the dialog in the browser window.
        """
        print(
            f"Dialog detected on account {self.account.get_name()} -- please dismiss it manually, then press Enter to continue."
        )
        input()

    def close(self) -> None:
        logger.info("Closing tab for account %s...", self.account.get_name())
        self.driver.close()
        self.driver.switch_to.window(self.driver.window_handles[0])
        logger.info("Closed")

    def scrape_transactions(self) -> "ScrapeSession":
        logger.info(
            "Scraping transactions for account %s...", self.account.get_name()
        )
        i: int = 0
        out: list[Transaction] = []
        row: WebElement
        for row in self.driver.find_elements(By.CLASS_NAME, "activity-row"):
            transaction = Transaction()
            transaction.amount = float(
                row.find_element(By.CLASS_NAME, "amount-cell")
                .text.replace(",", "")
                .replace("$", "")
            )
            transaction.date = row.find_element(By.CLASS_NAME, "date-cell").text
            transaction.desc = row.find_element(
                By.CLASS_NAME, "desc-cell"
            ).text.replace("\nView/Edit", "")
            transaction.type = row.find_element(By.CLASS_NAME, "type-cell").text
            view_edit = row.find_elements(
                By.CLASS_NAME, "view-transaction-details"
            )
            if view_edit:
                transaction.txn_hash = (
                    view_edit[0].get_attribute("data-txnhash") or ""
                )
            else:
                # Pending/processing rows have no View/Edit link; fall back to
                # the txn-<hash> CSS class on the <tr>.
                classes = (row.get_attribute("class") or "").split()
                transaction.txn_hash = next(
                    (
                        c.removeprefix("txn-")
                        for c in classes
                        if c.startswith("txn-")
                    ),
                    "",
                )
            transaction.running_balance = float(
                row.find_element(By.CLASS_NAME, "avail-balance-cell")
                .text.replace(",", "")
                .replace("$", "")
            )

            out.append(transaction)
            i = i + 1
        logger.info(
            "Found %d transactions on account %s", i, self.account.get_name()
        )
        self.account.set_transactions(out)
        return self

    def load_more_transactions(self) -> "ScrapeSession":
        logger.info(
            "Loading more transactions in account %s...",
            self.account.get_name(),
        )
        view_more = self.driver.find_element(
            By.CLASS_NAME, "view-more-transactions"
        )
        self.driver.execute_script("arguments[0].click();", view_more)
        Timeout.timeout()
        logger.info(
            "Loaded more transactions in account %s", self.account.get_name()
        )
        return self
