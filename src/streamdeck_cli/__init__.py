"""streamdeck-cli: a command-line tool for managing Elgato Stream Deck profiles, pages, and actions.

The official Elgato CLI / SDK only supports building *plugins* — there is no first-party tool
for managing the *profiles, pages, and actions* the user has already laid out in the
Stream Deck app. This project reverse-engineers the on-disk JSON schema used by the
Stream Deck 7.x desktop app and exposes it through a safe, testable Python CLI.

Mac-only (Windows uses a different path: ``%APPDATA%\\Elgato\\StreamDeck\\``). Tested
against Stream Deck 7.3.1 (build 22604).
"""

__version__ = "0.1.0"
