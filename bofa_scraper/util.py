import time
from urllib.parse import urlsplit

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
    Global configurable sleep used between page-load steps.

    A single duration applies to the whole scraping session. Set it once at
    startup via set_duration(); call timeout() wherever the code must wait for
    a page or dialog to finish loading.
    """

    duration: float = 0

    @staticmethod
    def set_duration(t: float) -> None:
        """
        Set the global sleep duration in seconds.

        Args:
            t: Seconds to sleep on each timeout() call. Use 0 in tests.
        """
        Timeout.duration = t

    @staticmethod
    def timeout() -> None:
        """Sleep for the configured duration."""
        time.sleep(Timeout.duration)
