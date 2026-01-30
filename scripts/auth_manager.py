#!/usr/bin/env python3
"""
OpenEvidence Authentication Manager

Handles login via Apple Sign-In, session persistence, and auth status.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from patchright.sync_api import sync_playwright

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    BASE_URL,
    LOGIN_URL,
    DATA_DIR,
    STATE_JSON,
    AUTH_INFO_JSON,
    BROWSER_PROFILE_DIR,
    LOGIN_BUTTON_SELECTORS,
    APPLE_LOGIN_SELECTORS,
    LOGGED_IN_INDICATORS,
    PAGE_LOAD_TIMEOUT,
    LOGIN_TIMEOUT,
)
from browser_utils import BrowserFactory, StealthUtils


class AuthManager:
    """Manages OpenEvidence authentication state."""

    def __init__(self):
        self.auth_info_path = AUTH_INFO_JSON
        self.state_path = STATE_JSON

    def is_authenticated(self) -> bool:
        """Check if we have saved authentication state."""
        if not self.state_path.exists():
            return False
        if not self.auth_info_path.exists():
            return False

        try:
            with open(self.auth_info_path, 'r') as f:
                info = json.load(f)
                return info.get('authenticated', False)
        except (json.JSONDecodeError, KeyError):
            return False

    def get_auth_info(self) -> dict:
        """Get authentication info."""
        if not self.auth_info_path.exists():
            return {}
        try:
            with open(self.auth_info_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    def save_auth_info(self, authenticated: bool, email: str = None) -> None:
        """Save authentication info."""
        info = {
            'authenticated': authenticated,
            'email': email,
            'last_auth': datetime.now().isoformat(),
            'provider': 'apple',
        }
        self.auth_info_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.auth_info_path, 'w') as f:
            json.dump(info, f, indent=2)

    def clear_auth(self) -> None:
        """Clear all authentication data."""
        if self.state_path.exists():
            self.state_path.unlink()
        if self.auth_info_path.exists():
            self.auth_info_path.unlink()
        if BROWSER_PROFILE_DIR.exists():
            shutil.rmtree(BROWSER_PROFILE_DIR)
        print("Authentication data cleared.")


def setup_auth() -> bool:
    """
    Interactive authentication setup.

    Opens browser for user to manually log in via Apple Sign-In.
    Saves session state after successful login.

    Returns:
        True if authentication successful
    """
    print("OpenEvidence Authentication Setup")
    print("=" * 40)
    print()
    print("A browser window will open.")
    print("Please log in using 'Sign in with Apple'.")
    print()

    auth = AuthManager()
    playwright = None
    context = None

    try:
        playwright = sync_playwright().start()

        # Launch VISIBLE browser for manual login
        context = BrowserFactory.launch_persistent_context(
            playwright,
            headless=False,  # Must be visible for manual login
        )

        page = context.new_page()

        # Navigate to OpenEvidence
        print("Opening OpenEvidence...")
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        StealthUtils.random_delay(1000, 2000)

        # Check if already logged in
        for selector in LOGGED_IN_INDICATORS:
            try:
                if page.query_selector(selector):
                    print("Already logged in!")
                    BrowserFactory.save_state(context)
                    auth.save_auth_info(authenticated=True)
                    return True
            except Exception:
                continue

        # Click login button
        print("Looking for login button...")
        login_clicked = False
        for selector in LOGIN_BUTTON_SELECTORS:
            try:
                element = page.query_selector(selector)
                if element and element.is_visible():
                    print(f"  Clicking: {selector}")
                    element.click()
                    login_clicked = True
                    break
            except Exception:
                continue

        if not login_clicked:
            print("Could not find login button. Please click it manually.")

        # Wait for user to complete login
        print()
        print("=" * 50)
        print("IMPORTANT: Complete the Apple Sign-In in the browser.")
        print("The script will wait until you finish logging in.")
        print("=" * 50)
        print()
        print("Press ENTER here after you have successfully logged in...")

        # Wait for user confirmation instead of auto-detecting
        # This avoids false positives from the homepage textarea
        try:
            input()
        except EOFError:
            # Running non-interactively, fall back to polling
            pass

        # Give the page a moment to settle after login
        time.sleep(3)

        # Now verify we're actually logged in
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        time.sleep(2)

        # Check for logged-in indicators
        for selector in LOGGED_IN_INDICATORS:
            try:
                if page.query_selector(selector):
                    print("Login verified!")
                    BrowserFactory.save_state(context)
                    auth.save_auth_info(authenticated=True)
                    return True
            except Exception:
                continue

        # Check for user-specific elements that only appear when logged in
        # Look for profile/avatar elements or "Log Out" instead of generic textarea
        user_indicators = [
            'button:has-text("Log Out")',
            'a:has-text("Log Out")',
            '[data-testid="user-avatar"]',
            '[class*="avatar"]',
            '[class*="profile"]',
            'img[alt*="profile"]',
            'img[alt*="avatar"]',
        ]

        for selector in user_indicators:
            try:
                if page.query_selector(selector):
                    print("Login verified! (User profile detected)")
                    BrowserFactory.save_state(context)
                    auth.save_auth_info(authenticated=True)
                    return True
            except Exception:
                continue

        # Final fallback: assume success if user pressed Enter
        print("Assuming login successful based on user confirmation.")
        print("If queries fail, run 'auth_manager.py reauth'")
        BrowserFactory.save_state(context)
        auth.save_auth_info(authenticated=True)
        return True

    except Exception as e:
        print(f"Error during setup: {e}")
        return False

    finally:
        if context:
            context.close()
        if playwright:
            playwright.stop()


def check_status() -> None:
    """Check and display authentication status."""
    auth = AuthManager()

    print("OpenEvidence Authentication Status")
    print("=" * 40)

    if auth.is_authenticated():
        info = auth.get_auth_info()
        print(f"Status: Authenticated")
        print(f"Provider: {info.get('provider', 'unknown')}")
        print(f"Last auth: {info.get('last_auth', 'unknown')}")
        if info.get('email'):
            print(f"Email: {info.get('email')}")
    else:
        print("Status: Not authenticated")
        print()
        print("Run 'python auth_manager.py setup' to authenticate.")


def validate_auth() -> bool:
    """
    Validate that saved auth actually works.

    Opens headless browser and checks if we're logged in.

    Returns:
        True if auth is valid
    """
    auth = AuthManager()

    if not auth.is_authenticated():
        print("Not authenticated. Run setup first.")
        return False

    print("Validating authentication...")

    playwright = None
    context = None

    try:
        playwright = sync_playwright().start()
        context = BrowserFactory.launch_persistent_context(
            playwright,
            headless=True,
        )

        page = context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        StealthUtils.random_delay(1000, 2000)

        # Check for logged-in indicators
        for selector in LOGGED_IN_INDICATORS:
            try:
                if page.query_selector(selector):
                    print("Authentication valid!")
                    return True
            except Exception:
                continue

        # Check for chat input
        try:
            chat_input = page.query_selector('textarea')
            if chat_input:
                print("Authentication valid! (Chat interface detected)")
                return True
        except Exception:
            pass

        print("Authentication expired or invalid.")
        print("Run 'python auth_manager.py reauth' to re-authenticate.")
        return False

    except Exception as e:
        print(f"Validation error: {e}")
        return False

    finally:
        if context:
            context.close()
        if playwright:
            playwright.stop()


def main():
    parser = argparse.ArgumentParser(description="OpenEvidence Authentication Manager")
    parser.add_argument(
        "command",
        choices=["setup", "status", "reauth", "clear", "validate"],
        help="Command to run",
    )

    args = parser.parse_args()

    if args.command == "setup":
        success = setup_auth()
        sys.exit(0 if success else 1)

    elif args.command == "status":
        check_status()

    elif args.command == "reauth":
        auth = AuthManager()
        auth.clear_auth()
        success = setup_auth()
        sys.exit(0 if success else 1)

    elif args.command == "clear":
        auth = AuthManager()
        auth.clear_auth()

    elif args.command == "validate":
        success = validate_auth()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
