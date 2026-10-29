from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

# One tile per account on the accounts overview page.
ACCOUNT_ITEM_CSS = "div.account-item"
# The account's name and the link to its activity page. Select it by class:
# a tile can also hold other links, such as an offer pop-up.
ACCOUNT_LINK_CSS = "a.account-link"
# The balance is the last span; an earlier visually hidden span holds the
# label 'Current Balance'.
ACCOUNT_BALANCE_CSS = "div.total > span:last-of-type"

# Ordered list of (key, label) pairs for all fields that may appear in the
# dict returned by ScrapeSession.get_transaction_details(). The order matches
# the natural top-to-bottom sequence of the BofA dialog. Fields absent from a
# particular transaction's dialog are omitted from the returned dict; callers
# should use .get() rather than direct indexing.
#
# 'description' is the user-editable transaction name at the top of the dialog.
# 'raw_description' is BofA's original merchant string (a second "Description"
# row further down); it may be identical to 'description' when the user has not
# edited the name.
# 'virtual_card_number' and 'phone_number' are only present for Virtual Card
# transactions.
TRANSACTION_DETAIL_FIELDS: list[tuple[str, str]] = [
    ("posting_date", "Posting date"),
    ("description", "Description"),
    ("type", "Type"),
    ("status", "Status"),
    ("amount", "Amount"),
    ("raw_description", "Raw description"),
    ("merchant_category", "Merchant category"),
    ("merchant_category_code", "Merchant category code"),
    ("merchant_information", "Merchant information"),
    ("merchant_name", "Merchant name"),
    ("transaction_category", "Transaction category"),
    ("virtual_card_number", "Virtual card number"),
    ("phone_number", "Phone number"),
]


class Transaction:
    """
    A single transaction row scraped from a BofA account detail page.

    Attributes are set by ScrapeSession.scrape_transactions() after the object
    is constructed. has_details is the only attribute with a class-level
    default; all others must be assigned before being read.
    """

    amount: float
    date: str
    desc: str
    type: str
    txn_hash: str
    running_balance: float
    # True when the row has a View/Edit link; only those transactions support
    # ScrapeSession.get_transaction_details().
    has_details: bool = False


class Account:
    """
    An account tile scraped from the BofA overview page.

    Name and balance are populated at construction time from the tile element.
    Transactions are populated later by ScrapeSession.scrape_transactions()
    and retrieved via get_transactions().
    """

    __name: str
    __balance: float
    __transactions: list[Transaction]
    __element: WebElement

    def __init__(self, account_element: WebElement):
        """
        Build an Account from a single overview-page account tile element.

        Args:
            account_element: The account tile WebElement (ACCOUNT_ITEM_CSS)
                             from the overview page.
        """
        self.__element = account_element
        # textContent rather than innerHTML: the name is wrapped in empty
        # framework comments.
        self.__name = (
            self.__element.find_element(
                By.CSS_SELECTOR, ACCOUNT_LINK_CSS
            ).get_attribute("textContent")
            or ""
        ).strip()
        self.__balance = float(
            (
                account_element.find_element(
                    By.CSS_SELECTOR, ACCOUNT_BALANCE_CSS
                ).get_attribute("textContent")
                or ""
            )
            .strip()
            .replace("$", "")
            .replace(",", "")
        )
        self.__transactions = []

    def get_name(self) -> str:
        """Return the account display name."""
        return self.__name

    def get_balance(self) -> float:
        """Return the current account balance."""
        return self.__balance

    def get_transactions(self) -> list[Transaction]:
        """
        Return the transaction list populated by scrape_transactions().

        Returns an empty list until scrape_transactions() has been called on
        the ScrapeSession for this account.
        """
        return self.__transactions

    def get_element(self) -> WebElement:
        """
        Return the raw overview-page WebElement for this account tile.

        Used internally by ScrapeSession to navigate to the account detail
        page. Only valid while the overview tab remains open.
        """
        return self.__element

    def set_transactions(self, transactions: list[Transaction]) -> None:
        """
        Replace the stored transaction list.

        Called by ScrapeSession.scrape_transactions(). Callers should read
        results via get_transactions().

        Args:
            transactions: New transaction list, most recent first.
        """
        self.__transactions = transactions
