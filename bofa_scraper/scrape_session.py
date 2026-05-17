from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from .account import Account, Transaction
from .util import Log, Timeout

class ScrapeSession:
	driver: webdriver.Firefox
	account: Account

	def __init__(self, driver: webdriver.Firefox, account: Account):
		self.driver = driver
		self.account = account

		Log.log('Starting scraping session for account %s' % account.get_name())
		url = self.account.get_element().find_element(By.TAG_NAME, "a").get_attribute("href")
		self.driver.execute_script('window.open()')
		self.driver.switch_to.window(self.driver.window_handles[1])
		self.driver.get(url)
		Timeout.timeout()
		self.dismiss_dialog()
		Log.log('Tab opened for account %s' % account.get_name())

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
					Log.log('Dismissing dialog via: %s' % xpath)
					el.click()
					Timeout.timeout()
					return True
		return False

	def wait_for_dialog_dismissal(self):
		"""
		Pause and wait for the user to manually dismiss a dialog.

		Call this when dismiss_dialog() cannot find the button automatically.
		The scraper will hold here until the user presses Enter, giving time
		to inspect and dismiss the dialog in the browser window.
		"""
		print('Dialog detected on account %s -- please dismiss it manually, then press Enter to continue.' % self.account.get_name())
		input()

	def close(self):
		Log.log('Closing tab for account %s...' % self.account.get_name())
		self.driver.close()
		self.driver.switch_to.window(self.driver.window_handles[0])
		Log.log('Closed')

	def scrape_transactions(self):
		Log.log('Scraping transactions for account %s...' % self.account.get_name())
		i: int = 0
		out: list[Transaction] = []
		row: WebElement
		for row in self.driver.find_elements(By.CLASS_NAME, "activity-row"):
			transaction = Transaction()
			transaction.amount = float(row.find_element(By.CLASS_NAME, "amount-cell").text.replace(",","").replace("$",""))
			transaction.date = row.find_element(By.CLASS_NAME, "date-cell").text
			transaction.desc = row.find_element(By.CLASS_NAME, "desc-cell").text.replace("\nView/Edit","")
			transaction.type = row.find_element(By.CLASS_NAME, "type-cell").text
			view_edit = row.find_elements(By.CLASS_NAME, "view-transaction-details")
			if view_edit:
				transaction.txn_hash = view_edit[0].get_attribute("data-txnhash")
			else:
				# Pending/processing rows have no View/Edit link; fall back to
				# the txn-<hash> CSS class on the <tr>.
				classes = row.get_attribute("class").split()
				transaction.txn_hash = next(
					(c.removeprefix("txn-") for c in classes if c.startswith("txn-")), ""
				)
			transaction.running_balance = float(row.find_element(By.CLASS_NAME, "avail-balance-cell").text.replace(",","").replace("$",""))

			out.append(transaction)
			i = i + 1
		Log.log('Found %d transactions on account %s' % (i, self.account.get_name()))
		self.account.set_transactions(out)
		return self

	def load_more_transactions(self):
		Log.log('Loading more transactions in account %s...' % self.account.get_name())
		view_more = self.driver.find_element(By.CLASS_NAME, "view-more-transactions")
		self.driver.execute_script("arguments[0].click();", view_more)
		Timeout.timeout()
		Log.log('Loaded more transactions in account %s' % self.account.get_name())
		return self
