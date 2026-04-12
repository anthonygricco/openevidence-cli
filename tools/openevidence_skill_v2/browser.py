from __future__ import annotations

import json
import os
import random
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .config import RuntimeContext

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


BASE_URL = "https://www.openevidence.com"
LOGIN_URL = "https://www.openevidence.com/api/auth/login"
QUERY_INPUT_SELECTORS = [
    'textarea[placeholder*="Ask"]',
    'textarea[placeholder*="question"]',
    'input[placeholder*="Ask"]',
    '[data-testid="chat-input"]',
    "textarea",
]
LOGIN_BUTTON_SELECTORS = [
    'button:has-text("Log In")',
    'a:has-text("Log In")',
    '[data-testid="login-button"]',
]
SUBMIT_BUTTON_SELECTORS = [
    'button[aria-label="Submit question"]',
    'button[aria-label*="Submit"]',
    'button[aria-label*="submit"]',
    'button[aria-label="Send"]',
    'button[aria-label*="Send"]',
    '[data-testid="send-button"]',
    'button[type="submit"]',
]
POPUP_DISMISS_SELECTORS = [
    'button:has-text("OK")',
    'button:has-text("Accept")',
    'button:has-text("I Agree")',
    'button:has-text("Continue")',
    'button:has-text("Got it")',
    'button:has-text("Dismiss")',
    'button:has-text("Close")',
    '[aria-label="Close"]',
    '[data-testid="close-button"]',
    '.MuiDialog-root button',
    '[role="dialog"] button',
]
LOADING_SELECTORS = [
    '[data-testid="loading"]',
    '.MuiCircularProgress-root',
    '[class*="loading"]',
    '[class*="typing"]',
    '[class*="thinking"]',
]
PAGE_LOAD_TIMEOUT = 30000
ELEMENT_TIMEOUT = 10000
LOGIN_TIMEOUT = 120000
QUERY_TIMEOUT = 120000


def load_playwright() -> object:
    from patchright.sync_api import sync_playwright

    return sync_playwright


class StealthUtils:
    @staticmethod
    def random_delay(min_ms: int = 100, max_ms: int = 500) -> None:
        time.sleep(random.randint(min_ms, max_ms) / 1000)

    @staticmethod
    def human_type(page: object, selector: str, text: str) -> None:
        page.click(selector)
        StealthUtils.random_delay(50, 150)
        base_delay = 50
        for char in text:
            multiplier = 1.0
            if char in " \n":
                multiplier = 0.6
            elif char in ".,!?":
                multiplier = 1.6
            page.keyboard.type(char, delay=base_delay * multiplier)


def _copy_tree_contents(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{dst.name}-tmp-", dir=str(dst.parent)))
    temp_target = temp_dir / dst.name
    try:
        shutil.copytree(
            src,
            temp_target,
            ignore=shutil.ignore_patterns("Singleton*", "lockfile", "Crashpad", "BrowserMetrics-*"),
        )
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        os.replace(temp_target, dst)
    finally:
        if temp_target.exists():
            shutil.rmtree(temp_target, ignore_errors=True)
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


@contextmanager
def _profile_template_lock(ctx: RuntimeContext):
    lock_path = ctx.shared_profile_template_dir.parent / ".profile-template.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def sync_profile_from_template(ctx: RuntimeContext, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    with _profile_template_lock(ctx):
        if destination.exists():
            return
        if ctx.shared_profile_template_dir.exists():
            _copy_tree_contents(ctx.shared_profile_template_dir, destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)


def sync_template_from_profile(ctx: RuntimeContext, source_profile: Path) -> None:
    if not source_profile.exists():
        return
    with _profile_template_lock(ctx):
        ctx.shared_profile_template_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            _copy_tree_contents(source_profile, ctx.shared_profile_template_dir)
        except (shutil.Error, OSError, FileNotFoundError):
            # The live Chromium profile can mutate while we snapshot it. State.json remains authoritative.
            return


class BrowserFactory:
    @staticmethod
    def cleanup_runtime_artifacts(profile_dir: Path) -> None:
        if not profile_dir.exists():
            return
        for artifact in profile_dir.glob("Singleton*"):
            try:
                if artifact.is_dir() and not artifact.is_symlink():
                    shutil.rmtree(artifact)
                else:
                    artifact.unlink()
            except FileNotFoundError:
                continue

    @staticmethod
    def browser_channel() -> str | None:
        raw = os.environ.get("OPENEVIDENCE_BROWSER_CHANNEL", "").strip().lower()
        if raw in {"", "chromium", "bundled", "default", "playwright"}:
            return None
        if raw in {"chrome", "google-chrome", "system-chrome"}:
            return "chrome"
        return None

    @staticmethod
    def launch_persistent_context(
        playwright: object,
        ctx: RuntimeContext,
        headless: bool = True,
        profile_dir: Path | None = None,
    ) -> object:
        profile = profile_dir or ctx.local_profile_dir
        sync_profile_from_template(ctx, profile)
        BrowserFactory.cleanup_runtime_artifacts(profile)

        launch_kwargs: dict[str, object] = {
            "user_data_dir": str(profile),
            "headless": headless,
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        }
        channel = BrowserFactory.browser_channel()
        if channel is not None:
            launch_kwargs["channel"] = channel

        try:
            context = playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception:
            if channel is None:
                raise
            launch_kwargs.pop("channel", None)
            context = playwright.chromium.launch_persistent_context(**launch_kwargs)

        if ctx.state_file.exists():
            try:
                raw_state = json.loads(ctx.state_file.read_text(encoding="utf-8"))
                cookies = raw_state.get("cookies") or []
                if cookies:
                    context.add_cookies(cookies)
            except json.JSONDecodeError:
                pass
        return context

    @staticmethod
    def save_state(context: object, ctx: RuntimeContext, profile_dir: Path | None = None) -> None:
        ctx.data_dir.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(ctx.state_file))
        sync_template_from_profile(ctx, profile_dir or ctx.local_profile_dir)


def find_visible_element(page: object, selectors: list[str], timeout_ms: int = ELEMENT_TIMEOUT) -> tuple[object | None, str | None]:
    for selector in selectors:
        try:
            element = page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
            if element:
                return element, selector
        except Exception:  # noqa: BLE001
            continue
    return None, None


def find_submit_button(page: object, input_selector: str) -> object | None:
    payload = {
        "inputSelector": input_selector,
        "submitSelectors": SUBMIT_BUTTON_SELECTORS,
    }
    script = """
    (payload) => {
      const input = document.querySelector(payload.inputSelector);
      if (!input) return null;

      const isVisible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style && style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };

      const textOf = (element) => (element && element.innerText ? element.innerText.trim() : "");
      const inputRect = input.getBoundingClientRect();
      const seen = new Set();
      let best = null;

      const scoreButton = (element, selector, index) => {
        if (!isVisible(element) || element.disabled) return;
        const rect = element.getBoundingClientRect();
        const aria = (element.getAttribute("aria-label") || "").toLowerCase();
        const text = textOf(element).toLowerCase();
        const type = (element.getAttribute("type") || "").toLowerCase();
        const deltaY = Math.abs((rect.y + rect.height / 2) - (inputRect.y + inputRect.height / 2));
        const distancePenalty = Math.abs((rect.x + rect.width / 2) - (inputRect.x + inputRect.width));
        let score = 0;

        if (aria.includes("submit question")) score += 2000;
        else if (aria.includes("submit")) score += 1200;
        else if (aria.includes("send")) score += 900;
        else if (text.includes("send")) score += 700;
        if (type === "submit") score += 300;
        if (rect.x >= inputRect.x + inputRect.width - 160) score += 250;
        if (rect.x >= inputRect.x) score += 80;
        if (deltaY <= 80) score += 160;
        if (deltaY <= 24) score += 120;
        score -= Math.round(distancePenalty);

        if (best === null || score > best.score) {
          best = { selector, index, score };
        }
      };

      for (const selector of payload.submitSelectors) {
        const elements = Array.from(document.querySelectorAll(selector));
        elements.forEach((element, index) => {
          const key = selector + "::" + index + "::" + (element.getAttribute("aria-label") || "") + "::" + textOf(element);
          if (seen.has(key)) return;
          seen.add(key);
          scoreButton(element, selector, index);
        });
      }
      return best ? { selector: best.selector, index: best.index } : null;
    }
    """
    try:
        target = page.evaluate(script, payload)
    except Exception:  # noqa: BLE001
        return None
    if not target:
        return None
    try:
        return page.locator(str(target["selector"])).nth(int(target["index"]))
    except Exception:  # noqa: BLE001
        return None


def dismiss_popups(page: object, debug: bool = False) -> None:
    for selector in POPUP_DISMISS_SELECTORS:
        try:
            button = page.query_selector(selector)
            if button and button.is_visible():
                if debug:
                    print(f"  Dismissing popup via {selector}")
                button.click()
                time.sleep(0.5)
        except Exception:  # noqa: BLE001
            continue
