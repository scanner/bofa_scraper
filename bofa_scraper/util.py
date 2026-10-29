import logging
import random
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

# Where BofA lands after a successful sign-in: the accounts overview
# ('/accounts-home/' since late 2026, '/myaccounts/' before that).
SIGNED_IN_HOST = "secure.bankofamerica.com"
SIGNED_IN_PATHS = ("/accounts-home/", "/myaccounts/")


def parse_money(text: str) -> float:
    """
    Convert a displayed amount such as '-$1,234.56' to a float.

    Args:
        text: The amount as shown on the page, with optional sign, '$',
              thousands separators and surrounding whitespace.

    Returns:
        The amount; negative for debits.

    Raises:
        ValueError: If the text is not an amount.
    """
    return float(text.strip().replace("$", "").replace(",", ""))


def hash_from_classes(class_attr: str) -> str:
    """
    Return the transaction hash from a row's 'txn-<hash>' CSS class.

    Pending and processing rows carry their hash only this way, not in a
    data attribute.

    Args:
        class_attr: The row's class attribute.

    Returns:
        The hash, or '' if the row has no 'txn-' class.
    """
    return next(
        (
            c.removeprefix("txn-")
            for c in class_attr.split()
            if c.startswith("txn-")
        ),
        "",
    )


def is_signed_in_url(url: str) -> bool:
    """Return True if url is a page BofA shows after a successful sign-in."""
    parts = urlsplit(url)
    return parts.netloc == SIGNED_IN_HOST and parts.path.startswith(
        SIGNED_IN_PATHS
    )


class Timeout:
    """
    Global timing settings for the scraping session.

    'duration' is a fixed pause, used only to pace requests to BofA between
    transaction detail dialogs. 'wait_duration' is the longest wait_until()
    waits for a page element. Once an element appears, wait_until() pauses
    a random time between 'settle_min' and 'settle_max' seconds so that
    content still loading around it can finish. Set these once at startup.
    """

    duration: float = 0
    wait_duration: float = 20
    settle_min: float = 0.5
    settle_max: float = 2.0

    @staticmethod
    def set_duration(t: float) -> None:
        """
        Set the global sleep duration in seconds.

        Args:
            t: Seconds to sleep on each timeout() call. Use 0 in tests.
        """
        Timeout.duration = t

    @staticmethod
    def set_wait_duration(t: float) -> None:
        """
        Set the longest wait for a page element, in seconds.

        Args:
            t: Seconds wait_until() waits before giving up.
        """
        Timeout.wait_duration = t

    @staticmethod
    def set_settle_range(low: float, high: float) -> None:
        """
        Set the range of the pause after a waited-for element appears.

        Args:
            low:  Shortest pause in seconds. Use 0 with high=0 in tests.
            high: Longest pause in seconds.
        """
        Timeout.settle_min = low
        Timeout.settle_max = high

    @staticmethod
    def timeout() -> None:
        """Sleep for the configured duration."""
        time.sleep(Timeout.duration)

    @staticmethod
    def settle() -> None:
        """Sleep a random time in the settle range."""
        time.sleep(random.uniform(Timeout.settle_min, Timeout.settle_max))


def wait_until(
    driver: WebDriver, condition: Callable[[WebDriver], object], what: str
) -> bool:
    """
    Wait up to Timeout.wait_duration seconds for condition to hold.

    When it holds, pause for Timeout.settle() so the rest of the dynamically
    loaded content around the element can settle before the next action.
    A timeout is logged as a warning, not raised, so callers carry on and
    report whatever the page holds.

    Args:
        driver:    The WebDriver.
        condition: Called with the driver until it returns a truthy value,
                   such as a selenium expected_conditions check.
        what:      What is being waited for, for the warning.

    Returns:
        True if the condition held, False on timeout.
    """
    try:
        WebDriverWait(driver, Timeout.wait_duration).until(condition)
    except TimeoutException:
        logger.warning(
            "Timed out after %gs waiting for %s", Timeout.wait_duration, what
        )
        return False
    Timeout.settle()
    return True
