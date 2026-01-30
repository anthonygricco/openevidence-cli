"""
Browser Utilities for OpenEvidence

Human-like typing, random delays, and browser factory.
"""

from __future__ import annotations

import json
import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.sync_api import BrowserContext, Page, Playwright

from config import (
    BROWSER_PROFILE_DIR,
    STATE_JSON,
    TYPING_WPM_MAX,
    TYPING_WPM_MIN,
)


class StealthUtils:
    """Human-like interaction utilities to avoid bot detection."""

    @staticmethod
    def random_delay(min_ms: int = 100, max_ms: int = 500) -> None:
        """Sleep for a random duration."""
        time.sleep(random.randint(min_ms, max_ms) / 1000)

    @staticmethod
    def human_type(page: Page, selector: str, text: str) -> None:
        """
        Type text with human-like variable delays.

        Args:
            page: Playwright page
            selector: CSS selector for input element
            text: Text to type
        """
        # Calculate base delay from WPM
        avg_wpm = (TYPING_WPM_MIN + TYPING_WPM_MAX) / 2
        base_delay = 60000 / (avg_wpm * 5)  # ms per character

        # Click to focus
        page.click(selector)
        StealthUtils.random_delay(50, 150)

        # Type each character with variable delay
        for char in text:
            # Vary delay based on character type
            if char in ' \n':
                delay = base_delay * random.uniform(0.5, 1.0)
            elif char in '.,!?':
                delay = base_delay * random.uniform(1.2, 2.0)
            else:
                delay = base_delay * random.uniform(0.8, 1.2)

            page.keyboard.type(char, delay=delay)

    @staticmethod
    def human_click(page: Page, selector: str) -> None:
        """Click with slight position randomization."""
        element = page.query_selector(selector)
        if element:
            box = element.bounding_box()
            if box:
                # Click slightly off-center
                x = box['x'] + box['width'] * random.uniform(0.3, 0.7)
                y = box['y'] + box['height'] * random.uniform(0.3, 0.7)
                page.mouse.click(x, y)
                return
        # Fallback to normal click
        page.click(selector)


class BrowserFactory:
    """Factory for creating browser contexts with persistent state."""

    @staticmethod
    def launch_persistent_context(
        playwright: Playwright,
        headless: bool = True,
    ) -> BrowserContext:
        """
        Launch a persistent browser context.

        Uses hybrid auth approach:
        - Persistent browser profile for fingerprint consistency
        - Manual cookie injection for session cookies (Playwright bug workaround)

        Args:
            playwright: Playwright instance
            headless: Run in headless mode

        Returns:
            Browser context
        """
        # Ensure profile directory exists
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        # Launch persistent context
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=headless,
            channel="chrome",  # Use installed Chrome for better compatibility
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",  # Required for sandboxed environments like Alma
                "--disable-setuid-sandbox",
            ],
        )

        # Inject cookies from state.json if it exists (session cookie workaround)
        if STATE_JSON.exists():
            try:
                with open(STATE_JSON, 'r') as f:
                    state = json.load(f)
                    if 'cookies' in state:
                        context.add_cookies(state['cookies'])
            except (json.JSONDecodeError, KeyError):
                pass  # State file corrupted or missing cookies

        return context

    @staticmethod
    def save_state(context: BrowserContext) -> None:
        """
        Save browser state to state.json.

        Args:
            context: Browser context to save state from
        """
        STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(STATE_JSON))
