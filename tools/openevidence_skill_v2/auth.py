from __future__ import annotations

import json
import subprocess
import shutil
import time
from datetime import datetime
from pathlib import Path

from .bootstrap import ensure_runtime_directories, migrate_legacy_state
from .browser import (
    BASE_URL,
    BrowserFactory,
    LOGIN_BUTTON_SELECTORS,
    PAGE_LOAD_TIMEOUT,
    QUERY_INPUT_SELECTORS,
    StealthUtils,
    dismiss_popups,
    find_visible_element,
    load_playwright,
)
from .config import RuntimeContext
from .extract import silent_relogin_possible_from_cookies


HELIUM_DEVTOOLS_ACTIVE_PORT = (
    Path.home() / "Library" / "Application Support" / "net.imput.helium" / "DevToolsActivePort"
)
VALID_SAME_SITE_VALUES = {"Lax", "Strict", "None"}


def load_auth_info(ctx: RuntimeContext) -> dict[str, object]:
    if not ctx.auth_info_file.exists():
        return {
            "authenticated": False,
            "provider": "apple",
            "last_auth": None,
            "last_validation": None,
            "last_successful_runtime": None,
            "last_failure_reason": None,
            "migrated_from": None,
        }
    try:
        return json.loads(ctx.auth_info_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "authenticated": False,
            "provider": "apple",
            "last_auth": None,
            "last_validation": None,
            "last_successful_runtime": None,
            "last_failure_reason": "corrupt-auth-info",
            "migrated_from": None,
        }


def save_auth_info(
    ctx: RuntimeContext,
    *,
    authenticated: bool,
    last_successful_runtime: str | None = None,
    last_failure_reason: str | None = None,
    last_validation: str | None = None,
    last_auth: str | None = None,
    migrated_from: str | None = None,
) -> None:
    ensure_runtime_directories(ctx)
    existing = load_auth_info(ctx)
    payload = {
        "authenticated": authenticated,
        "provider": existing.get("provider", "apple"),
        "last_auth": last_auth if last_auth is not None else existing.get("last_auth"),
        "last_validation": last_validation if last_validation is not None else existing.get("last_validation"),
        "last_successful_runtime": (
            last_successful_runtime
            if last_successful_runtime is not None
            else existing.get("last_successful_runtime")
        ),
        "last_failure_reason": last_failure_reason,
        "migrated_from": migrated_from if migrated_from is not None else existing.get("migrated_from"),
    }
    ctx.auth_info_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def auth_cookies(ctx: RuntimeContext) -> list[dict[str, object]]:
    if not ctx.state_file.exists():
        return []
    try:
        state = json.loads(ctx.state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(state.get("cookies") or [])


def normalize_browser_cookie(cookie: dict[str, object]) -> dict[str, object] | None:
    name = str(cookie.get("name") or "").strip()
    value = str(cookie.get("value") or "")
    domain = str(cookie.get("domain") or "").strip()
    path = str(cookie.get("path") or "/").strip() or "/"
    if not name or not domain or "openevidence.com" not in domain.lower():
        return None

    normalized: dict[str, object] = {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path,
        "httpOnly": bool(cookie.get("httpOnly")),
        "secure": bool(cookie.get("secure")),
    }
    expires = normalize_browser_cookie_expiration(cookie)
    if expires is not None:
        normalized["expires"] = expires

    same_site = str(cookie.get("sameSite") or "").strip().title()
    if same_site in VALID_SAME_SITE_VALUES:
        normalized["sameSite"] = same_site
    return normalized


def normalize_browser_cookie_expiration(cookie: dict[str, object]) -> float | int | None:
    if bool(cookie.get("session")):
        return -1
    raw = cookie.get("expires")
    if raw in (None, ""):
        return -1
    try:
        expires = float(raw)
    except (TypeError, ValueError):
        return -1
    if expires <= 0:
        return -1
    return expires


def storage_state_from_browser_cookies(browser_cookies: list[dict[str, object]]) -> dict[str, object]:
    deduped: dict[str, dict[str, object]] = {}
    for cookie in browser_cookies:
        normalized = normalize_browser_cookie(cookie)
        if normalized is None:
            continue
        key = f"{normalized['domain']}:{normalized['path']}:{normalized['name']}"
        deduped[key] = normalized
    return {
        "cookies": list(deduped.values()),
        "origins": [],
    }


def _clear_runtime_profiles(ctx: RuntimeContext) -> None:
    for path in (ctx.local_profile_dir, ctx.shared_profile_template_dir):
        if path.exists():
            shutil.rmtree(path)


def export_helium_live_cookies(ctx: RuntimeContext) -> list[dict[str, object]]:
    if not HELIUM_DEVTOOLS_ACTIVE_PORT.exists():
        raise RuntimeError(
            f"Helium is not exposing DevTools metadata at {HELIUM_DEVTOOLS_ACTIVE_PORT}. Leave Helium running and try again."
        )

    script_path = ctx.repo_root / "tools" / "openevidence_skill_v2" / "helium_cdp_export.mjs"
    if not script_path.exists():
        raise RuntimeError(f"Missing Helium export helper: {script_path}")

    try:
        result = subprocess.run(
            ["node", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Node.js is required for Helium session import.") from exc

    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or "Helium cookie export failed."
        raise RuntimeError(message)

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Helium cookie export returned invalid JSON: {result.stdout.strip()}") from exc

    raw_cookies = payload.get("cookies")
    if not isinstance(raw_cookies, list):
        raise RuntimeError("Helium cookie export did not return a cookies list.")
    return [cookie for cookie in raw_cookies if isinstance(cookie, dict)]


def import_auth_from_helium(ctx: RuntimeContext, debug: bool = False) -> int:
    ensure_runtime_directories(ctx)
    migrate_legacy_state(ctx)

    try:
        browser_cookies = export_helium_live_cookies(ctx)
    except RuntimeError as exc:
        save_auth_info(
            ctx,
            authenticated=False,
            last_successful_runtime=None,
            last_failure_reason="helium-import-failed",
        )
        print(str(exc))
        return 1

    storage_state = storage_state_from_browser_cookies(browser_cookies)
    imported_cookies = storage_state.get("cookies") or []
    if not imported_cookies:
        save_auth_info(
            ctx,
            authenticated=False,
            last_successful_runtime=None,
            last_failure_reason="helium-import-no-openevidence-cookies",
        )
        print("No OpenEvidence cookies were found in the live Helium session.")
        return 1

    ctx.data_dir.mkdir(parents=True, exist_ok=True)
    ctx.state_file.write_text(json.dumps(storage_state, indent=2), encoding="utf-8")
    _clear_runtime_profiles(ctx)

    valid = validate_auth(ctx, debug=debug)
    if valid:
        save_auth_info(
            ctx,
            authenticated=True,
            last_successful_runtime=ctx.runtime_id,
            last_failure_reason=None,
            last_validation=datetime.now().isoformat(),
            last_auth=datetime.now().isoformat(),
        )
        print(f"Imported {len(imported_cookies)} OpenEvidence cookies from the live Helium session.")
        print("Authentication valid!")
        return 0

    save_auth_info(
        ctx,
        authenticated=False,
        last_successful_runtime=None,
        last_failure_reason="helium-import-validation-failed",
        last_validation=datetime.now().isoformat(),
    )
    print(f"Imported {len(imported_cookies)} OpenEvidence cookies from the live Helium session.")
    print("Authentication invalid after import.")
    return 1


def login_button_visible(page: object) -> bool:
    for selector in LOGIN_BUTTON_SELECTORS:
        try:
            element = page.query_selector(selector)
            if element and element.is_visible():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def query_input_visible(page: object) -> bool:
    for selector in QUERY_INPUT_SELECTORS:
        try:
            element = page.query_selector(selector)
            if element and element.is_visible():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def is_logged_in(page: object) -> bool:
    if login_button_visible(page):
        return False
    return query_input_visible(page)


def attempt_silent_relogin(page: object, ctx: RuntimeContext, debug: bool = False) -> bool:
    if not silent_relogin_possible_from_cookies(auth_cookies(ctx)):
        return False
    if not login_button_visible(page):
        return True

    if debug:
        print("  Attempting silent re-login...")
    for selector in LOGIN_BUTTON_SELECTORS:
        try:
            element = page.query_selector(selector)
            if element and element.is_visible():
                element.click()
                break
        except Exception:  # noqa: BLE001
            continue

    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(1)
        dismiss_popups(page, debug=debug)
        if is_logged_in(page):
            BrowserFactory.save_state(page.context, ctx)
            save_auth_info(
                ctx,
                authenticated=True,
                last_successful_runtime=ctx.runtime_id,
                last_failure_reason=None,
                last_validation=datetime.now().isoformat(),
                last_auth=datetime.now().isoformat(),
            )
            return True
    return False


def validate_auth(ctx: RuntimeContext, *, headless: bool = True, debug: bool = False) -> bool:
    ensure_runtime_directories(ctx)
    migrate_legacy_state(ctx)

    playwright_manager = load_playwright()
    playwright = None
    context = None
    try:
        playwright = playwright_manager().start()
        context = BrowserFactory.launch_persistent_context(playwright, ctx, headless=headless)
        page = context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        StealthUtils.random_delay(500, 1000)
        dismiss_popups(page, debug=debug)
        valid = is_logged_in(page)
        save_auth_info(
            ctx,
            authenticated=valid,
            last_successful_runtime=ctx.runtime_id if valid else None,
            last_failure_reason=None if valid else "validation-failed",
            last_validation=datetime.now().isoformat(),
        )
        if valid:
            BrowserFactory.save_state(context, ctx, ctx.local_profile_dir)
            BrowserFactory.cleanup_runtime_artifacts(ctx.local_profile_dir)
            BrowserFactory.cleanup_runtime_artifacts(ctx.shared_profile_template_dir)
        return valid
    finally:
        if context:
            context.close()
        if playwright:
            playwright.stop()


def print_status(ctx: RuntimeContext) -> int:
    info = load_auth_info(ctx)
    print("OpenEvidence Authentication Status")
    print("=" * 40)
    print(f"Status: {'Authenticated' if info.get('authenticated') else 'Not authenticated'}")
    print(f"Provider: {info.get('provider', 'apple')}")
    print(f"Last auth: {info.get('last_auth')}")
    print(f"Last validation: {info.get('last_validation')}")
    print(f"Last successful runtime: {info.get('last_successful_runtime')}")
    if info.get("last_failure_reason"):
        print(f"Last failure reason: {info.get('last_failure_reason')}")
    return 0


def clear_auth(ctx: RuntimeContext) -> int:
    for path in (
        ctx.auth_info_file,
        ctx.state_file,
    ):
        if path.exists():
            path.unlink()
    for path in (
        ctx.local_profile_dir,
        ctx.shared_profile_template_dir,
    ):
        if path.exists():
            shutil.rmtree(path)
    save_auth_info(
        ctx,
        authenticated=False,
        last_successful_runtime=None,
        last_failure_reason=None,
        last_validation=None,
        last_auth=None,
    )
    print("Authentication data cleared.")
    return 0


def perform_setup(ctx: RuntimeContext, debug: bool = False) -> int:
    ensure_runtime_directories(ctx)
    migrate_legacy_state(ctx)

    print("OpenEvidence Authentication Setup")
    print("=" * 40)
    print()
    print("A browser window will open.")
    print("Please log in using 'Sign in with Apple'.")
    print()

    playwright_manager = load_playwright()
    playwright = None
    context = None
    try:
        playwright = playwright_manager().start()
        context = BrowserFactory.launch_persistent_context(playwright, ctx, headless=False)
        page = context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        StealthUtils.random_delay(1000, 2000)
        dismiss_popups(page, debug=debug)

        if is_logged_in(page):
            BrowserFactory.save_state(context, ctx, ctx.local_profile_dir)
            BrowserFactory.cleanup_runtime_artifacts(ctx.local_profile_dir)
            save_auth_info(
                ctx,
                authenticated=True,
                last_successful_runtime=ctx.runtime_id,
                last_failure_reason=None,
                last_validation=datetime.now().isoformat(),
                last_auth=datetime.now().isoformat(),
            )
            print("Already logged in.")
            return 0

        _, selector = find_visible_element(page, LOGIN_BUTTON_SELECTORS)
        if selector:
            page.click(selector)
        else:
            print("Could not find the login button automatically. Please click it manually.")

        print()
        print("=" * 50)
        print("Complete the Apple Sign-In in the browser.")
        print("Press ENTER here after you finish logging in.")
        print("=" * 50)
        print()
        try:
            input()
        except EOFError:
            pass

        time.sleep(3)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        time.sleep(2)
        dismiss_popups(page, debug=debug)

        valid = is_logged_in(page)
        BrowserFactory.save_state(context, ctx, ctx.local_profile_dir)
        BrowserFactory.cleanup_runtime_artifacts(ctx.local_profile_dir)
        save_auth_info(
            ctx,
            authenticated=valid,
            last_successful_runtime=ctx.runtime_id if valid else None,
            last_failure_reason=None if valid else "manual-login-not-verified",
            last_validation=datetime.now().isoformat(),
            last_auth=datetime.now().isoformat(),
        )
        if valid:
            print("Login verified.")
            return 0
        print("Login could not be verified automatically. Run validate after reauth if queries fail.")
        return 1
    finally:
        if context:
            context.close()
        if playwright:
            playwright.stop()
