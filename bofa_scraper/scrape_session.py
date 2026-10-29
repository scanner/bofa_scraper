import logging

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC

from .account import (
    ACCOUNT_LINK_CSS,
    ACCOUNT_NUMBER_CSS,
    Account,
    Transaction,
)
from .util import (
    Timeout,
    hash_from_classes,
    last_four_from_masked,
    parse_money,
    wait_until,
)

# Maps lowercased label text from the Transaction details dialog to the
# canonical key returned in the dict from get_transaction_details(). Labels
# not present here are passed through as label.lower().replace(' ', '_').
_LABEL_TO_KEY: dict[str, str] = {
    "posting date": "posting_date",
    "description": "description",
    "type": "type",
    "status": "status",
    "amount": "amount",
    "merchant category": "merchant_category",
    "merchant category code": "merchant_category_code",
    "merchant information": "merchant_information",
    "merchant name": "merchant_name",
    "transaction category": "transaction_category",
    "virtual card number": "virtual_card_number",
    "phone number": "phone_number",
    "purchaser": "purchaser",
    "online purchase": "online_purchase",
}

# The transaction table on an account's activity page.
_ACTIVITY_TABLE_CSS = "table#txn-activity-table"

# The dialog that holds the transaction details content.
_TXN_DIALOG_XPATH = '//*[@role="dialog"][.//*[@id="transaction-details-modal"]]'

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
class ScrapeSession:
    """
    An active browser tab opened for a single BofA account detail page.

    Constructed by BofAScraper.open_account(). The overview tab remains open
    in the background while this session operates in a second tab, keeping
    account WebElement references valid. Call close() when done to shut the
    detail tab and return focus to the overview tab.
    """

    driver: webdriver.Firefox
    account: Account

    def __init__(self, driver: webdriver.Firefox, account: Account):
        """
        Open a new browser tab and navigate to the account detail page.

        Reads the last four digits of the account number from the page and
        stores them on the account; see get_last_four().

        Args:
            driver: The shared Firefox WebDriver instance.
            account: The account to open. Its WebElement must still be valid,
                     meaning the overview tab must remain open.

        Raises:
            ValueError: If the account tile element has no href link.
        """
        self.driver = driver
        self.account = account

        logger.info(
            "Starting scraping session for account %s", account.get_name()
        )
        url = (
            self.account.get_element()
            .find_element(By.CSS_SELECTOR, ACCOUNT_LINK_CSS)
            .get_attribute("href")
        )
        if url is None:
            raise ValueError(
                f"Account {account.get_name()!r} has no href on its link element"
            )
        self.driver.execute_script("window.open()")
        self.driver.switch_to.window(self.driver.window_handles[1])
        self.driver.get(url)
        wait_until(
            self.driver,
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, _ACTIVITY_TABLE_CSS)
            ),
            "the activity table",
        )
        self.dismiss_dialog()
        self.account.set_last_four(self._read_last_four())
        logger.info("Tab opened for account %s", account.get_name())

    ####################################################################
    #
    def get_last_four(self) -> str | None:
        """
        Return the last four digits of this account's number.

        Returns:
            The digits read when the session opened, or None if the
            account's page did not show its number.
        """
        return self.account.get_last_four()

    ####################################################################
    #
    def _read_last_four(self) -> str | None:
        """Read the last four digits of the account number from the page."""
        elements = self.driver.find_elements(
            By.CSS_SELECTOR, ACCOUNT_NUMBER_CSS
        )
        last_four = (
            last_four_from_masked(
                elements[0].get_attribute("textContent") or ""
            )
            if elements
            else None
        )
        if last_four is None:
            logger.warning(
                "No account number found on the page for account %s",
                self.account.get_name(),
            )
        return last_four

    ####################################################################
    #
    def dismiss_dialog(self) -> bool:
        """
        Dismiss any modal dialog that may be blocking the current page.

        Tries several XPath patterns that match common BofA OK/Continue
        buttons. Returns True if a visible button was found and clicked,
        False if no matching button was detected.
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
                    wait_until(
                        self.driver,
                        EC.invisibility_of_element(el),
                        "the dialog to close",
                    )
                    return True
        return False

    ####################################################################
    #
    def wait_for_dialog_dismissal(self) -> None:
        """
        Pause until the user manually dismisses a dialog in the browser.

        Call this when dismiss_dialog() cannot locate the button automatically.
        Prints a prompt and blocks on input() until the user presses Enter.
        """
        print(
            f"Dialog detected on account {self.account.get_name()} -- "
            "please dismiss it manually, then press Enter to continue."
        )
        input()

    ####################################################################
    #
    def close(self) -> None:
        """
        Close the account detail tab and return focus to the overview tab.

        Must be called after each session, even on error, so the driver
        remains in a usable state for subsequent accounts.
        """
        logger.info("Closing tab for account %s...", self.account.get_name())
        self.driver.close()
        self.driver.switch_to.window(self.driver.window_handles[0])
        logger.info("Closed")

    ####################################################################
    #
    def scrape_transactions(self) -> "ScrapeSession":
        """
        Scrape all visible transaction rows from the account detail page.

        Walks every element with class 'activity-row' and builds a Transaction
        for each. Results are stored on the Account and returned by
        account.get_transactions(), most recent first.

        Pending/processing rows have no View/Edit link; their has_details flag
        stays False and their txn_hash is derived from the row's CSS class
        rather than a data attribute.

        Returns:
            self, to allow method chaining.
        """
        logger.info(
            "Scraping transactions for account %s...", self.account.get_name()
        )
        i: int = 0
        out: list[Transaction] = []
        row: WebElement
        for row in self.driver.find_elements(By.CLASS_NAME, "activity-row"):
            transaction = Transaction()
            transaction.amount = parse_money(
                row.find_element(By.CLASS_NAME, "amount-cell").text
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
                transaction.has_details = True
            else:
                transaction.txn_hash = hash_from_classes(
                    row.get_attribute("class") or ""
                )
            transaction.running_balance = parse_money(
                row.find_element(By.CLASS_NAME, "avail-balance-cell").text
            )

            out.append(transaction)
            i += 1
        logger.info(
            "Found %d transactions on account %s", i, self.account.get_name()
        )
        self.account.set_transactions(out)
        return self

    ####################################################################
    #
    def load_more_transactions(self) -> "ScrapeSession":
        """
        Click the 'View more transactions' button and wait for more rows.

        Call before scrape_transactions() to include older history beyond what
        BofA initially renders. Can be called multiple times.

        Returns:
            self, to allow method chaining.
        """
        logger.info(
            "Loading more transactions in account %s...",
            self.account.get_name(),
        )
        before = len(self.driver.find_elements(By.CLASS_NAME, "activity-row"))
        view_more = self.driver.find_element(
            By.CLASS_NAME, "view-more-transactions"
        )
        self.driver.execute_script("arguments[0].click();", view_more)
        wait_until(
            self.driver,
            lambda d: (
                len(d.find_elements(By.CLASS_NAME, "activity-row")) > before
            ),
            "more transaction rows",
        )
        logger.info(
            "Loaded more transactions in account %s", self.account.get_name()
        )
        return self

    ####################################################################
    #
    def get_transaction_detail_html(
        self, transaction: Transaction
    ) -> str | None:
        """
        Return the raw outerHTML of the transaction details modal.

        Use this as a discovery probe to inspect BofA's actual DOM structure
        before writing or tuning get_transaction_details(). Opens the dialog,
        captures the outerHTML, then closes the dialog.

        Args:
            transaction: A Transaction scraped by scrape_transactions(). Must
                         have has_details=True; pending/processing rows return
                         None immediately.

        Returns:
            The outerHTML string of the dialog container, or None if the
            transaction has no View/Edit link or the dialog cannot be located.
        """
        if not transaction.has_details:
            return None
        if not self._open_transaction_dialog(transaction):
            return None
        dialog = self._find_transaction_dialog()
        html = dialog.get_attribute("outerHTML") if dialog else None
        self._close_transaction_dialog()
        Timeout.timeout()
        return html

    ####################################################################
    #
    def get_transaction_details(
        self, transaction: Transaction
    ) -> dict[str, str] | None:
        """
        Fetch structured details for a single posted transaction.

        Opens the transaction's View/Edit dialog, extracts each label/value
        pair, then closes the dialog. It then pauses for timeout_duration
        seconds to pace requests; calling this in a tight loop over many
        transactions with a short pause may trigger BofA rate-limiting.

        Only posted transactions expose a View/Edit link. Pending and
        processing transactions have has_details=False and return None.

        Args:
            transaction: A Transaction scraped by scrape_transactions(). Must
                         have has_details=True to have a View/Edit link.

        Returns:
            A dict mapping field names to their string values, or None if the
            transaction has no View/Edit link or the dialog cannot be located.
            Known keys and sample values::

                posting_date            'May 28, 2026'
                description             user-editable transaction label
                type                    'Virtual Card', 'Debit Card', etc.
                status                  'Cleared'
                amount                  '-$14.70'
                raw_description         BofA's original merchant string
                                        (second 'Description' row in dialog)
                merchant_category       'Grocery Stores and Supermarkets'
                merchant_category_code  '5411'
                merchant_information    'MENLO PARK, CA'
                merchant_name           'TRADER JOES'
                transaction_category    'Groceries : Groceries'
                virtual_card_number     masked card number (Virtual Card only)
                phone_number            masked phone number
                purchaser               cardholder name on the purchase
                online_purchase         'Y' for online purchases

            Fields absent from the dialog are omitted. Unrecognized labels are
            included under label.lower().replace(' ', '_'). The key '_raw' is
            set to the dialog's full text when no structured fields could be
            extracted -- useful for diagnosing unexpected dialog layouts.
        """
        if not transaction.has_details:
            return None
        if not self._open_transaction_dialog(transaction):
            return None
        dialog = self._find_transaction_dialog()
        if dialog is None:
            self._close_transaction_dialog()
            return None
        result = self._extract_dialog_fields(dialog)
        self._close_transaction_dialog()
        Timeout.timeout()
        return result

    ####################################################################
    #
    def _open_transaction_dialog(self, transaction: Transaction) -> bool:
        """
        Click the View/Edit link for the transaction to open the detail dialog.

        Looks up the link by its data-txnhash attribute rather than storing
        a stale WebElement reference.

        Args:
            transaction: Must have has_details=True.

        Returns:
            True if the link was found and clicked, False otherwise.
        """
        links = self.driver.find_elements(
            By.CSS_SELECTOR, f'[data-txnhash="{transaction.txn_hash}"]'
        )
        if not links:
            logger.warning(
                "No view-transaction-details link found for txn_hash %r",
                transaction.txn_hash,
            )
            return False
        # JavaScript click avoids any scroll-into-view requirement.
        self.driver.execute_script("arguments[0].click();", links[0])
        wait_until(
            self.driver,
            EC.visibility_of_element_located((By.XPATH, _TXN_DIALOG_XPATH)),
            "the transaction details dialog",
        )
        return True

    def _find_transaction_dialog(self) -> WebElement | None:
        """
        Locate the visible transaction details modal container in the DOM.

        Tries the role='dialog' element that holds the transaction details
        content first, then any visible role='dialog', then a heading whose
        text contains 'Transaction details', walking up to its nearest
        modal-like ancestor. The page holds other dialogs too, such as the
        session-timeout warning.

        Returns:
            The dialog WebElement, or None if it cannot be found.
        """
        for xpath in (_TXN_DIALOG_XPATH, '//*[@role="dialog"]'):
            for el in self.driver.find_elements(By.XPATH, xpath):
                if el.is_displayed():
                    return el

        # Heading-based fallback for pages that omit role="dialog".
        for tag in ("h2", "h3", "h4"):
            for heading in self.driver.find_elements(By.TAG_NAME, tag):
                if "Transaction details" not in heading.text:
                    continue
                if not heading.is_displayed():
                    continue
                try:
                    return heading.find_element(
                        By.XPATH,
                        "./ancestor::*[contains(@class,'modal') "
                        "or contains(@class,'dialog')][1]",
                    )
                except NoSuchElementException:
                    # No modal-like ancestor; use two levels up as fallback.
                    return heading.find_element(By.XPATH, "../..")

        logger.warning("Transaction details dialog not found in DOM")
        return None

    def _close_transaction_dialog(self) -> None:
        """
        Close the transaction details modal.

        Tries common close-button selectors in order, then falls back to
        Escape, and waits for the dialog to disappear. Logs a warning if no
        button is found and Escape is used.
        """
        xpaths = [
            f'{_TXN_DIALOG_XPATH}//button[contains(@class,"spa-ui-layer-close")]',
            '//button[@aria-label="Close"]',
            '//button[@aria-label="close"]',
            '//button[contains(@class,"close")]',
            '//*[contains(@class,"close-button")]',
        ]
        button = next(
            (
                el
                for xpath in xpaths
                for el in self.driver.find_elements(By.XPATH, xpath)
                if el.is_displayed()
            ),
            None,
        )
        if button is not None:
            button.click()
        else:
            logger.warning(
                "No close button found for transaction dialog; sending Escape"
            )
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
        wait_until(
            self.driver,
            EC.invisibility_of_element_located((By.XPATH, _TXN_DIALOG_XPATH)),
            "the transaction details dialog to close",
        )

    def _extract_dialog_fields(self, dialog: WebElement) -> dict[str, str]:
        """
        Extract label/value pairs from the transaction details modal.

        Runs three strategies in sequence:

        1. dl/dt/dd -- each <dt> is the label; its following <dd> is the value.
           Returns immediately if this yields anything.
        2. Foundation grid rows -- .row elements whose direct .columns children
           pair a label column with a value column. Collects what it can but
           does NOT return early, because editable fields (Merchant name,
           Transaction category) use a different DOM structure and are missed.
        3. Text-line fallback -- splits the dialog's visible text on newlines
           and anchors on known label strings to fill in any fields that
           Strategies 1 and 2 missed. Only sets keys not already present.

        If no fields are found by any strategy, returns {'_raw': <dialog text>}
        for diagnostic use.

        'Description' appears twice in the dialog: the first occurrence maps to
        'description' (user-editable label); the second maps to 'raw_description'
        (BofA's original merchant string).

        Args:
            dialog: The modal container WebElement.

        Returns:
            Dict of canonical-key -> value-string pairs.
        """
        result: dict[str, str] = {}
        dialog_text = dialog.text

        # Strategy 1: definition list -- return immediately if it works.
        dts = dialog.find_elements(By.TAG_NAME, "dt")
        if dts:
            for dt in dts:
                label = dt.text.strip()
                if not label:
                    continue
                try:
                    dd = dt.find_element(By.XPATH, "following-sibling::dd[1]")
                except NoSuchElementException:
                    continue
                inputs = dd.find_elements(By.TAG_NAME, "input")
                value = (
                    (inputs[0].get_attribute("value") or "").strip()
                    if inputs
                    else dd.text.strip()
                )
                self._store_field(result, label, value)
            if result:
                return result

        # Strategy 2: Foundation grid rows.
        for row in dialog.find_elements(By.CSS_SELECTOR, ".row"):
            cols = row.find_elements(By.CSS_SELECTOR, ".columns")
            if len(cols) < 2:
                continue
            label = cols[0].text.strip()
            if not label:
                continue
            value_col = cols[-1]
            inputs = value_col.find_elements(By.TAG_NAME, "input")
            if inputs:
                value = (inputs[0].get_attribute("value") or "").strip()
            else:
                value = value_col.text.strip()
            if not value:
                continue
            self._store_field(result, label, value)
        # Do NOT return here -- editable fields (Merchant name, Transaction
        # category) use a different DOM structure and need Strategy 3.

        # Strategy 3: text-line fallback for any fields still missing.
        self._fill_from_dialog_text(result, dialog_text)

        if result:
            return result

        logger.warning(
            "Could not extract structured fields from transaction dialog"
        )
        return {"_raw": dialog_text.strip()}

    @staticmethod
    def _fill_from_dialog_text(result: dict[str, str], text: str) -> None:
        """
        Fill in any known fields still absent from result using line-by-line text.

        Splits the dialog's visible text on newlines, then walks the lines
        looking for strings that match a known label from _LABEL_TO_KEY. When
        a match is found, the next non-empty, non-label line is taken as the
        value and stored only if that key is not already in result.

        This catches editable fields (Merchant name, Transaction category, etc.)
        whose DOM structure differs from the Foundation grid rows that Strategy 2
        handles.

        Args:
            result: Dict being built by _extract_dialog_fields; modified in place.
            text:   The full visible text of the dialog container.
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, line in enumerate(lines[:-1]):
            normalized = line.lower()
            if normalized not in _LABEL_TO_KEY:
                continue
            candidate = lines[i + 1]
            # Skip if the candidate line is itself a known label.
            if candidate.lower() in _LABEL_TO_KEY:
                continue
            if normalized == "description" and "description" in result:
                key = "raw_description"
            else:
                key = _LABEL_TO_KEY.get(
                    normalized, normalized.replace(" ", "_")
                )
            # Only fill gaps -- don't overwrite what Strategies 1/2 already found.
            if key not in result:
                result[key] = candidate

    @staticmethod
    def _store_field(result: dict[str, str], label: str, value: str) -> None:
        """
        Normalize a label/value pair and insert it into result.

        'Description' maps to 'description' on first occurrence and
        'raw_description' on the second, because BofA uses the same label for
        both the user-editable name and the raw merchant description.

        Args:
            result: The dict being built by _extract_dialog_fields.
            label:  Raw label text from the dialog.
            value:  Corresponding value string.
        """
        normalized = label.strip().lower()
        if normalized == "description" and "description" in result:
            key = "raw_description"
        else:
            key = _LABEL_TO_KEY.get(normalized, normalized.replace(" ", "_"))
        result[key] = value
