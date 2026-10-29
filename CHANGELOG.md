# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `tools/dump_pages.py` and `tools/digest_page.py` to capture and summarize rendered BofA pages when the site changes
- `wait_duration` argument to `BofAScraper` -- the longest wait for a page element, default 20 seconds

### Changed

- Page loads, "View more", and the transaction details dialog wait for the elements they need instead of pausing a fixed time, then pause briefly (0.5 to 2 seconds) for the rest of the page to settle
- `timeout_duration` is now only the pause after each transaction details dialog closes, which paces requests to BofA

### Fixed

- Sign-in is detected again after BofA moved the post-login page to `/accounts-home/`
- `get_accounts()` reads the redesigned accounts overview, waiting for the account list to render
- The transaction details dialog lookup and close button are scoped to the transaction dialog, not other dialogs on the page

## [1.1.0] - 2026-05-30

### Added

- `Transaction.has_details` flag -- `True` for posted transactions that expose a View/Edit link; `False` for pending/processing rows
- `ScrapeSession.get_transaction_details(txn)` -- opens the View/Edit dialog for a single posted transaction and returns its fields as a `dict[str, str]`
- `ScrapeSession.get_transaction_detail_html(txn)` -- returns the raw `outerHTML` of the dialog for DOM inspection and parser debugging
- `TRANSACTION_DETAIL_FIELDS` -- exported constant; ordered `list[tuple[str, str]]` of `(key, label)` pairs for all known detail fields
- Docstrings on all public classes and methods across the library

### Changed

- `examples/account_overview.py` now fetches and displays transaction details for each of the ten most recent posted transactions per account

## [1.0.4] - 2026-05-17

### Added

- `running_balance` field on `Transaction` to capture the available balance after each transaction
- `ScrapeSession.dismiss_dialog()` to automatically click common BofA modal dismiss buttons ("Got it", "OK", "Continue") by id or text
- `ScrapeSession.wait_for_dialog_dismissal()` to pause and prompt the user when a dialog cannot be dismissed automatically
- `BofAScraper._dismiss_dialog()` called immediately after login to clear overview-page dialogs before account element references are captured (prevents stale element errors)

### Fixed

- Renamed `Transaction.uuid` to `Transaction.txn_hash` -- the value is a 64-character SHA-256 hex digest, not a UUID
- `txn_hash` is now read from the `data-txnhash` attribute on the View/Edit link rather than parsed from the `<tr>` CSS class, which previously included the spurious `txn-` prefix
- Pending transactions (which have no View/Edit link) no longer crash `scrape_transactions()` -- the hash falls back to the `txn-<hash>` CSS class on the row

## [1.0.3] - 2026-05-15

### Fixed

- Detect 2FA page by element presence (`#btnARContinue`) rather than URL pattern, accommodating BofA redirect URL changes
- Handle multiple possible selectors for the 2FA auth code input field

## [1.0.0] - 2024-01-01

### Added

- Initial packaging and release
- Verbose logging mode
- Headless browser support (untested, have to be careful of websites that go out of their way to guard against headless mode)
- 2FA support
