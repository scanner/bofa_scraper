import logging

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC

from .account import ACCOUNT_ITEM_CSS, Account
from .account import TRANSACTION_DETAIL_FIELDS as TRANSACTION_DETAIL_FIELDS
from .scrape_session import ScrapeSession
from .util import Timeout, is_signed_in_url, wait_until

logger = logging.getLogger(__name__)

_HOMEPAGE_URL = "https://www.bankofamerica.com/"
# How many times to load the homepage looking for the sign-in form.
_SIGN_IN_ATTEMPTS = 3

# Elements that show the sign-in form was answered with a 2FA challenge.
_2FA_LOCATORS = [
    (By.ID, "btnARContinue"),
    (By.CLASS_NAME, "authcode"),
    (By.ID, "authenticationCode"),
]


########################################################################
#
def _signed_in_or_2fa(driver: WebDriver) -> bool:
    """Return True once the browser shows the overview or a 2FA step."""
    return is_signed_in_url(driver.current_url) or any(
        driver.find_elements(*loc) for loc in _2FA_LOCATORS
    )


########################################################################
########################################################################
#
class BofAScraper:
    """
    Entry point for a Bank of America scraping session.

    Launches a Firefox WebDriver, navigates to bankofamerica.com, and
    provides methods to log in, enumerate accounts, and open per-account
    scraping sessions. Always call quit() when finished to close the browser
    process, even when an exception is raised mid-run.

    Typical usage::

        scraper = BofAScraper(online_id, passcode)
        try:
            scraper.login()
            accounts = scraper.get_accounts()
            session = scraper.open_account(accounts[0])
            try:
                session.scrape_transactions()
            finally:
                session.close()
        finally:
            scraper.quit()
    """

    creds: dict[str, str] = {}
    driver: webdriver.Firefox
    logged_in = False

    def __init__(
        self,
        online_id: str,
        passcode: str,
        timeout_duration: float = 5,
        verbose: bool = True,
        headless: bool = True,
        wait_duration: float = 20,
    ):
        """
        Initialize the scraper and open a browser window on bankofamerica.com.

        Args:
            online_id:        BofA Online ID (username).
            passcode:         BofA passcode (password).
            timeout_duration: Seconds to pause after each transaction details
                              dialog closes, to pace requests to BofA.
                              Defaults to 5.
            verbose:          When True, logs progress messages to stdout.
                              Defaults to True.
            headless:         When True, the browser runs invisibly. Set to
                              False to watch or debug the session interactively.
                              Defaults to True.
            wait_duration:    Longest wait, in seconds, for a page to show the
                              element the next step needs. Increase this on
                              slow connections. Defaults to 20.
        """
        self.creds["id"] = online_id
        self.creds["passcode"] = passcode
        Timeout.set_duration(timeout_duration)
        Timeout.set_wait_duration(wait_duration)

        pkg_logger = logging.getLogger("bofa_scraper")
        if verbose and not pkg_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            pkg_logger.addHandler(handler)
        pkg_logger.setLevel(logging.INFO if verbose else logging.WARNING)

        logger.info("Initializing web driver...")
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("--headless")
        self.driver = webdriver.Firefox(options=options)
        self.driver.set_window_size(1280, 972)
        self._open_sign_in_page()
        logger.info("Initialized web driver")

    ####################################################################
    #
    def _open_sign_in_page(self) -> bool:
        """
        Load the BofA homepage until it shows the sign-in form.

        BofA sometimes sends a new visitor to a promotions page with no
        sign-in form instead of the homepage, so the homepage is loaded up
        to _SIGN_IN_ATTEMPTS times.

        Returns:
            True if the sign-in form is on the page.
        """
        for attempt in range(1, _SIGN_IN_ATTEMPTS + 1):
            self.driver.get(_HOMEPAGE_URL)
            if wait_until(
                self.driver,
                EC.presence_of_element_located((By.ID, "oid")),
                "the sign-in form",
            ):
                return True
            logger.info(
                "No sign-in form on %s (attempt %d of %d)",
                self.driver.current_url,
                attempt,
                _SIGN_IN_ATTEMPTS,
            )
        return False

    ####################################################################
    #
    def quit(self) -> None:
        """Close the browser process and release all WebDriver resources."""
        self.driver.quit()

    ####################################################################
    #
    def open_account(self, account: Account) -> ScrapeSession:
        """
        Open a new browser tab for the given account's transaction detail page.

        The overview tab stays open in the background so that WebElement
        references for other accounts remain valid. Call session.close() when
        done to shut the detail tab and return focus to the overview tab.

        Args:
            account: An Account returned by get_accounts(). The overview tab
                     must still be open when this is called.

        Returns:
            A ScrapeSession bound to the new detail tab.
        """
        return ScrapeSession(self.driver, account)

    ####################################################################
    #
    def get_accounts(self) -> list[Account]:
        """
        Scrape the overview page and return one Account per account tile.

        Each Account has its name and balance pre-populated. Transactions are
        not fetched until a ScrapeSession is opened and scrape_transactions()
        is called. Returns an empty list if the scraper is not logged in.

        The overview renders its account list after the page loads, so this
        waits for the first account tile before reading them.
        """
        logger.info("Fetching accounts...")
        out = []
        if not self.logged_in:
            logger.info("Not signed in")
        else:
            wait_until(
                self.driver,
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ACCOUNT_ITEM_CSS)
                ),
                "the account tiles",
            )
            i = 0
            for account_element in self.driver.find_elements(
                By.CSS_SELECTOR, ACCOUNT_ITEM_CSS
            ):
                account = Account(account_element)
                logger.info("Found account: %s", account.get_name())
                out.append(account)
                i += 1
            logger.info("Found %d accounts", i)
        return out

    ####################################################################
    #
    def login(self) -> None:
        """
        Submit the sign-in form and handle 2FA if required.

        Types the stored credentials into the BofA sign-in form and submits.
        If BofA responds with a one-time passcode challenge, the method pauses
        and prints 'input 2fa code:' to stdout; the user types the code and
        presses Enter. Sets logged_in=True on success.

        After a successful login the driver is on the 'My Accounts' overview
        page. Call get_accounts() next to retrieve account tiles.

        Raises:
            RuntimeError: If no sign-in form can be found on the homepage.
        """
        logger.info("Logging in...")
        if (
            not self.driver.find_elements(By.ID, "oid")
            and not self._open_sign_in_page()
        ):
            raise RuntimeError(
                "No sign-in form found; the browser is on "
                f"{self.driver.current_url}"
            )
        self.driver.find_element(By.ID, "oid").send_keys(self.creds["id"])
        self.driver.find_element(By.ID, "pass").send_keys(
            self.creds["passcode"]
        )
        self.driver.find_element(By.ID, "secure-signin-submit").click()
        wait_until(self.driver, _signed_in_or_2fa, "the page after sign-in")

        # Detect 2FA by element presence rather than URL, since the redirect
        # URL has changed over time.
        url = self.driver.current_url
        needs_2fa = (
            any(self.driver.find_elements(*loc) for loc in _2FA_LOCATORS)
            or "signOnSuccessRedirect" in url
            or "auth/signon" in url
        )

        if needs_2fa:
            logger.info("2fa required")
            try:
                self.driver.find_element(By.ID, "btnARContinue").click()
                wait_until(
                    self.driver,
                    lambda d: any(
                        d.find_elements(*loc) for loc in _2FA_LOCATORS[1:]
                    ),
                    "the 2FA code field",
                )
            except NoSuchElementException:
                pass
            print("input 2fa code: ")
            code = input()
            for by, sel in [
                (By.CLASS_NAME, "authcode"),
                (By.ID, "authenticationCode"),
            ]:
                try:
                    self.driver.find_element(by, sel).send_keys(code)
                    break
                except NoSuchElementException:
                    pass
            try:
                self.driver.find_element(By.ID, "yes-recognize").click()
            except NoSuchElementException:
                pass
            try:
                self.driver.find_element(By.ID, "continue-auth-number").click()
            except NoSuchElementException:
                pass
            wait_until(
                self.driver,
                lambda d: is_signed_in_url(d.current_url),
                "the accounts overview after 2FA",
            )

        if is_signed_in_url(self.driver.current_url):
            logger.info("Sign in success!")
            self.logged_in = True
            self._dismiss_dialog()
        else:
            logger.info("Sign in failed")
            self.logged_in = False

    ####################################################################
    #
    def _dismiss_dialog(self) -> bool:
        """
        Dismiss any modal dialog on the current page.

        Called after login to clear overview-page dialogs before account
        elements are scraped. Tries by id first, then by button text.

        Returns:
            True if a visible button was found and clicked, False otherwise.
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
