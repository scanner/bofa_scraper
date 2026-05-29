import logging

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from .account import Account
from .scrape_session import ScrapeSession
from .util import Timeout

logger = logging.getLogger(__name__)


class BofAScraper:
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
    ):
        self.creds["id"] = online_id
        self.creds["passcode"] = passcode
        Timeout.set_duration(timeout_duration)

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
        self.driver.get("https://www.bankofamerica.com/")
        Timeout.timeout()
        logger.info("Initialized web driver")

    def quit(self) -> None:
        self.driver.quit()

    def open_account(self, account: Account) -> ScrapeSession:
        return ScrapeSession(self.driver, account)

    def get_accounts(self) -> list[Account]:
        logger.info("Fetching accounts...")
        out = []
        if not self.logged_in:
            logger.info("Not signed in")
        else:
            i = 0
            for account_element in self.driver.find_elements(
                By.CLASS_NAME, "AccountItem"
            ):
                account = Account(account_element)
                logger.info("Found account: %s", account.get_name())
                out.append(account)
                i = i + 1
            logger.info("Found %d accounts", i)
        return out

    def login(self) -> None:
        logger.info("Logging in...")
        self.driver.find_element(By.ID, "oid").send_keys(self.creds["id"])
        self.driver.find_element(By.ID, "pass").send_keys(
            self.creds["passcode"]
        )
        self.driver.find_element(By.ID, "secure-signin-submit").click()
        Timeout.timeout()

        # Detect 2FA by element presence rather than exact URL, since the
        # redirect URL has changed over time.
        try:
            self.driver.find_element(By.ID, "btnARContinue")
            needs_2fa = True
        except NoSuchElementException:
            url = self.driver.current_url
            needs_2fa = "signOnSuccessRedirect" in url or "auth/signon" in url

        if needs_2fa:
            logger.info("2fa required")
            try:
                self.driver.find_element(By.ID, "btnARContinue").click()
                Timeout.timeout()
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
            Timeout.timeout()

        if self.driver.current_url.startswith(
            "https://secure.bankofamerica.com/myaccounts/"
        ):
            logger.info("Sign in success!")
            self.logged_in = True
            self._dismiss_dialog()
        else:
            logger.info("Sign in failed")
            self.logged_in = False

    def _dismiss_dialog(self) -> bool:
        """
        Dismiss any modal dialog on the current page.

        Tries by id first (most reliable), then by button text. Called after
        login so that overview-page dialogs don't stale account element refs.
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
