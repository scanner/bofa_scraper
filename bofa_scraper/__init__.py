from typing import List

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from .util import Log, Timeout
from .account import Account
from .scrape_session import ScrapeSession

class BofAScraper:
	creds = dict()
	driver: webdriver.Firefox
	logged_in = False

	def __init__(self, online_id: str, passcode: str, timeout_duration=5, verbose=True, headless=True):
		self.creds["id"] = online_id
		self.creds["passcode"] = passcode
		Log.set_verbose(verbose)
		Timeout.set_duration(timeout_duration)

		Log.log("Initializing web driver...")
		options = webdriver.FirefoxOptions()
		options.headless = headless
		self.driver = webdriver.Firefox(options=options)
		self.driver.set_window_size(1280, 972)
		self.driver.get("https://www.bankofamerica.com/")
		Timeout.timeout()
		Log.log("Initialized web driver")
	
	def quit(self):
		self.driver.quit()

	def open_account(self, account: Account) -> ScrapeSession:
		return ScrapeSession(self.driver, account)

	def get_accounts(self) -> List[Account]:
		Log.log("Fetching accounts...")
		out = []
		if not self.logged_in:
			Log.log("Not signed in")
		else:
			i = 0
			for account_element in self.driver.find_elements(By.CLASS_NAME, "AccountItem"):
				account = Account(account_element)
				Log.log("Found account: %s" % account.get_name())
				out.append(account)
				i = i + 1
			Log.log("Found %d accounts" % i)
		return out

	def login(self):
		Log.log('Logging in...')
		self.driver.find_element(By.ID, "oid").send_keys(self.creds["id"])
		self.driver.find_element(By.ID, "pass").send_keys(self.creds["passcode"])
		self.driver.find_element(By.ID, "secure-signin-submit").click()
		Timeout.timeout()

		# Detect 2FA by element presence rather than exact URL, since the
		# redirect URL has changed over time.
		try:
			self.driver.find_element(By.ID, "btnARContinue")
			needs_2fa = True
		except NoSuchElementException:
			url = self.driver.current_url
			needs_2fa = (
				"signOnSuccessRedirect" in url
				or "auth/signon" in url
			)

		if needs_2fa:
			Log.log('2fa required')
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

		if self.driver.current_url.startswith('https://secure.bankofamerica.com/myaccounts/'):
			Log.log('Sign in success!')
			self.logged_in = True
			self._dismiss_dialog()
		else:
			Log.log('Sign in failed')
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
					Log.log('Dismissing dialog via: %s' % xpath)
					el.click()
					Timeout.timeout()
					return True
		return False