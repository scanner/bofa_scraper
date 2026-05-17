# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
