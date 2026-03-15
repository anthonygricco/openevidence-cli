#!/usr/bin/env python3
"""
OpenEvidence Question Interface

Ask medical questions and get evidence-based answers.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    BASE_URL,
    DATA_DIR,
    ELEMENT_TIMEOUT,
    FAST_MODE,
    LOADING_SELECTORS,
    NORMAL_MODE,
    PAGE_LOAD_TIMEOUT,
    QUERY_INPUT_SELECTORS,
    QUERY_TIMEOUT,
    RESPONSE_NOISE_PATTERNS,
    SUBMIT_BUTTON_SELECTORS,
    TURBO_MODE,
)
from browser_utils import BrowserFactory, StealthUtils
from auth_manager import AuthManager


def find_element(page, selectors: list[str], timeout: int = ELEMENT_TIMEOUT):
    """
    Find an element using multiple selectors.

    Args:
        page: Playwright page
        selectors: List of CSS selectors to try
        timeout: Timeout in milliseconds

    Returns:
        Element if found, None otherwise
    """
    for selector in selectors:
        try:
            element = page.wait_for_selector(
                selector,
                timeout=timeout,
                state="visible",
            )
            if element:
                return element, selector
        except Exception:
            continue
    return None, None


def dismiss_popups(page, quick: bool = False) -> None:
    """
    Dismiss any popups/dialogs (HIPAA consent, cookies, etc.)

    Args:
        quick: If True, only check for dialog/modal presence first (fast path)
    """
    # Fast path: check if any dialog is visible at all
    if quick:
        try:
            dialog = page.query_selector('[role="dialog"], .MuiDialog-root')
            if not dialog or not dialog.is_visible():
                return  # No dialog visible, skip all selectors
        except Exception:
            return

    popup_dismiss_selectors = [
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

    for selector in popup_dismiss_selectors:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                print(f"  Dismissing popup: {selector}")
                btn.click()
                time.sleep(0.3)
        except Exception:
            continue


def is_loading(page) -> bool:
    """Check if page is showing loading indicator using fast JS evaluation."""
    try:
        return page.evaluate('''() => {
            // Check for common loading/thinking indicators via JS (faster than selector iteration)
            const selectors = [
                '[data-testid="loading"]',
                '.MuiCircularProgress-root',
                '[class*="loading"]',
                '[class*="typing"]',
                '[class*="thinking"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.offsetParent !== null) return true;
            }
            return false;
        }''')
    except Exception:
        return False


def clean_response_text(text: str) -> str:
    """Remove UI noise (thinking indicators, loading text) from response."""
    if not text:
        return text

    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip lines that are purely noise
        is_noise = False
        for pattern in RESPONSE_NOISE_PATTERNS:
            if stripped.lower() == pattern.lower() or stripped.lower().startswith(pattern.lower()):
                is_noise = True
                break
        if not is_noise:
            cleaned_lines.append(line)

    # Also strip popup/consent patterns from the start
    result = '\n'.join(cleaned_lines).strip()
    popup_patterns = [
        "protected health information (phi) will be securely processed",
        "cookie",
    ]
    for pattern in popup_patterns:
        if result.lower().startswith(pattern):
            lines = result.split('\n')
            result = '\n'.join(lines[1:]).strip()

    return result


def response_looks_complete(text: str) -> bool:
    """
    Heuristic check: does the response look like a complete OE answer?

    Complete responses typically contain citation markers like [1], [2],
    reference sections, or structured medical content with multiple paragraphs.
    """
    if not text or len(text) < 300:
        return False

    import re
    has_citations = bool(re.search(r'\[\d+\]', text))
    has_references = any(marker in text.lower() for marker in [
        'references', 'sources', 'citation', 'et al.', 'doi:',
        'n engl j med', 'lancet', 'jama', 'j clin oncol',
    ])
    has_multiple_paragraphs = text.count('\n\n') >= 2

    if (has_citations or has_references) and has_multiple_paragraphs:
        return True

    if len(text) > 1000 and has_multiple_paragraphs:
        return True

    return False


def is_response_streaming(page) -> bool:
    """
    Check if OE is still actively streaming/generating the response.

    Uses JS to detect:
    - Cursor/caret blinking animation in the response area
    - Streaming indicator elements
    - Text content still growing (checked by caller via text comparison)
    """
    try:
        return page.evaluate('''() => {
            // Check for streaming cursor/caret indicators
            const article = document.querySelector('article');
            if (!article) return false;

            // Look for animated cursor elements (common in streaming UIs)
            const cursor = article.querySelector('[class*="cursor"], [class*="caret"], [class*="blink"]');
            if (cursor && cursor.offsetParent !== null) return true;

            // Check for any CSS animation on last element (streaming indicator)
            const lastChild = article.lastElementChild;
            if (lastChild) {
                const style = window.getComputedStyle(lastChild);
                if (style.animationName && style.animationName !== 'none') return true;
            }

            return false;
        }''')
    except Exception:
        return False


def get_response_text(page, debug: bool = False, min_chars: int = 100) -> str | None:
    """
    Extract the COMPLETE response text from the page, exactly as shown.

    Args:
        page: Playwright page
        debug: Show debug output
        min_chars: Minimum character count to accept

    Returns:
        Full response text if found, None otherwise
    """
    # Strategy 1: JavaScript extraction (most reliable, gets innerText from article)
    try:
        text = page.evaluate('''() => {
            const article = document.querySelector('article');
            if (article) return article.innerText;
            const main = document.querySelector('main');
            if (main) return main.innerText;
            return null;
        }''')
        if text:
            text = clean_response_text(text.strip())
            if text and len(text) > min_chars:
                if debug:
                    print(f"    DEBUG: JS extraction got {len(text)} chars")
                return text
    except Exception as e:
        if debug:
            print(f"    DEBUG: JS extraction error: {e}")

    # Strategy 2: Playwright selector fallback
    for selector in ['article', 'main']:
        try:
            element = page.query_selector(selector)
            if element:
                text = clean_response_text(element.inner_text().strip())
                if text and len(text) > min_chars:
                    if debug:
                        print(f"    DEBUG: Selector '{selector}' got {len(text)} chars")
                    return text
        except Exception as e:
            if debug:
                print(f"    DEBUG: Selector '{selector}' error: {e}")

    return None


def capture_screenshot(page, output_path: Path) -> bool:
    """Capture a screenshot of the response area."""
    try:
        page.screenshot(path=str(output_path), full_page=True)
        return True
    except Exception as e:
        print(f"  Screenshot error: {e}")
        return False


def extract_images(page, output_dir: Path, debug: bool = False) -> list[str]:
    """
    Extract ALL images from the response exactly as shown.

    Returns:
        List of saved image paths
    """
    saved_images = []
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Find all images within the article/response area
        article = page.query_selector('article')
        if article:
            images = article.query_selector_all('img')
        else:
            images = page.query_selector_all('main img')

        for i, img in enumerate(images):
            try:
                src = img.get_attribute('src')
                alt = img.get_attribute('alt') or f'figure_{i}'

                if not src:
                    continue

                # Clean up alt text for filename
                safe_alt = "".join(c if c.isalnum() else "_" for c in alt[:30])

                if src.startswith('data:image'):
                    # Embedded base64 image
                    import base64
                    header, data = src.split(',', 1)
                    ext = 'png' if 'png' in header else 'jpg'
                    img_path = output_dir / f"figure_{i}_{safe_alt}.{ext}"
                    with open(img_path, 'wb') as f:
                        f.write(base64.b64decode(data))
                    saved_images.append(str(img_path))
                    if debug:
                        print(f"    DEBUG: Saved embedded image: {img_path.name}")

                elif src.startswith('http'):
                    # External URL - download it
                    import urllib.request
                    ext = 'png' if '.png' in src.lower() else 'jpg'
                    img_path = output_dir / f"figure_{i}_{safe_alt}.{ext}"
                    urllib.request.urlretrieve(src, img_path)
                    saved_images.append(str(img_path))
                    if debug:
                        print(f"    DEBUG: Downloaded: {img_path.name}")

            except Exception as e:
                if debug:
                    print(f"    DEBUG: Error extracting image {i}: {e}")
                continue

    except Exception as e:
        if debug:
            print(f"    DEBUG: Image extraction error: {e}")

    return saved_images


def ask_openevidence(
    question: str,
    headless: bool = True,
    debug: bool = False,
    save_images: bool = False,
    output_dir: Path | None = None,
    fast: bool = False,
    turbo: bool = False,
    stream: bool = False,
) -> dict | None:
    """
    Ask a question to OpenEvidence.

    Args:
        question: Medical question to ask
        headless: Run browser in headless mode
        debug: Show debug output
        save_images: Save screenshot and images
        output_dir: Directory for saved images
        fast: Use fast mode (reduced delays, direct input)
        turbo: Use turbo mode (maximum speed, may be less reliable)
        stream: Stream response text as it appears

    Returns:
        Dict with 'answer', 'images', 'screenshot' keys, or None on failure
    """
    auth = AuthManager()

    if not auth.is_authenticated():
        print("Not authenticated. Run: python auth_manager.py setup")
        return None

    # Select timing mode
    if turbo:
        mode = TURBO_MODE
        mode_name = "TURBO"
    elif fast:
        mode = FAST_MODE
        mode_name = "FAST"
    else:
        mode = NORMAL_MODE
        mode_name = "NORMAL"

    print(f"[{mode_name}] Asking: {question[:80]}{'...' if len(question) > 80 else ''}")

    playwright = None
    context = None

    try:
        playwright = sync_playwright().start()
        context = BrowserFactory.launch_persistent_context(
            playwright,
            headless=headless,
        )

        page = context.new_page()

        # Navigate to OpenEvidence
        print("  Opening OpenEvidence...")
        wait_strategy = "commit" if turbo else "domcontentloaded"
        page.goto(BASE_URL, wait_until=wait_strategy, timeout=PAGE_LOAD_TIMEOUT)
        StealthUtils.random_delay(*mode['after_load'])

        # Dismiss any initial popups (HIPAA consent, cookies, etc.)
        dismiss_popups(page)
        StealthUtils.random_delay(*mode['after_popup'])

        # Find chat input
        print("  Looking for chat input...")
        input_element, input_selector = find_element(page, QUERY_INPUT_SELECTORS)

        if not input_element:
            print("  Could not find chat input. Site may have changed.")
            print("  Try running with --show-browser to debug.")
            return None

        print(f"  Found input: {input_selector}")

        # Type the question
        if fast or turbo:
            print("  Entering question (fast)...")
            page.fill(input_selector, question)
            StealthUtils.random_delay(*mode['after_popup'])
        else:
            print("  Typing question...")
            StealthUtils.human_type(page, input_selector, question)
            StealthUtils.random_delay(500, 1000)

        # Submit the question
        print("  Submitting...")

        # Try clicking submit button first
        submit_clicked = False
        for selector in SUBMIT_BUTTON_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    submit_clicked = True
                    break
            except Exception:
                continue

        # Fallback: press Enter
        if not submit_clicked:
            page.keyboard.press("Enter")

        StealthUtils.random_delay(*mode['after_submit'])

        # Dismiss any popups that appear after submission (HIPAA consent, etc.)
        dismiss_popups(page)
        StealthUtils.random_delay(*mode['after_popup'])

        # Wait for response
        if stream:
            print("  Streaming response...\n")
            print("=" * 60)
            print("OPENEVIDENCE RESPONSE")
            print("=" * 60 + "\n")
        else:
            print("  Waiting for response...")

        answer = None
        stable_count = 0
        last_text = None
        printed_len = 0  # For streaming: track how much we've printed
        deadline = time.time() + QUERY_TIMEOUT / 1000
        submit_time = time.time()

        poll_interval = mode.get('poll_interval', 1.0)
        min_chars = mode.get('min_response_chars', 300)
        min_wait = mode.get('min_wait_after_submit', 3.0)
        # Use faster polling for streaming
        if stream:
            poll_interval = 0.2

        while time.time() < deadline:
            elapsed = time.time() - submit_time

            # Dismiss any popups that might appear (quick check in poll loop)
            dismiss_popups(page, quick=True)

            # Check if still loading
            if is_loading(page):
                time.sleep(poll_interval)
                continue

            # Try to get response text
            text = get_response_text(page, debug=debug, min_chars=min_chars)

            if text:
                # Don't accept responses before minimum wait time
                if elapsed < min_wait:
                    if debug:
                        print(f"    DEBUG: Got {len(text)} chars but only {elapsed:.1f}s elapsed (min {min_wait}s)")
                    last_text = text
                    time.sleep(poll_interval)
                    continue

                if stream:
                    # Print new content as it appears
                    # Only print if text is strictly growing (avoid re-render duplicates)
                    if len(text) > printed_len and text[:printed_len] == last_text[:printed_len] if last_text else True:
                        new_content = text[printed_len:]
                        # Skip if new content looks like a re-render (repeated fragments)
                        if last_text and new_content in last_text:
                            stable_count += 1
                        else:
                            print(new_content, end='', flush=True)
                            printed_len = len(text)
                            stable_count = 0
                    elif len(text) == printed_len:
                        stable_count += 1
                    else:
                        # Text shrunk or changed significantly - might be re-render
                        stable_count += 1

                    last_text = text
                    if stable_count >= mode['stable_checks'] + 3:  # Extra checks for streaming
                        answer = text
                        break
                else:
                    # Non-streaming: wait for stability
                    if text == last_text:
                        # Check if OE is still actively streaming
                        if is_response_streaming(page):
                            # Still streaming — don't increment stable count
                            if debug:
                                print(f"    DEBUG: Text stable but OE still streaming ({len(text)} chars)")
                            time.sleep(poll_interval)
                            continue
                        stable_count += 1
                        # Accept if stable AND (looks complete OR enough stable checks)
                        if stable_count >= mode['stable_checks']:
                            if response_looks_complete(text) or stable_count >= mode['stable_checks'] + 2:
                                answer = text
                                break
                    else:
                        stable_count = 0
                        last_text = text

            time.sleep(poll_interval)

        # For streaming, use whatever we have if we timed out
        if stream and not answer and printed_len > 0:
            answer = get_response_text(page, debug=debug)

        if stream:
            print("\n")  # End streaming output

        if answer:
            print(f"  Got response ({len(answer)} chars)")

            result = {
                'answer': answer,
                'images': [],
                'screenshot': None,
            }

            # Capture images if requested
            if save_images:
                if output_dir is None:
                    output_dir = DATA_DIR / "responses"
                output_dir.mkdir(parents=True, exist_ok=True)

                # Save screenshot
                screenshot_path = output_dir / "response_screenshot.png"
                if capture_screenshot(page, screenshot_path):
                    result['screenshot'] = str(screenshot_path)
                    print(f"  Saved screenshot: {screenshot_path}")

                # Extract and save images
                images = extract_images(page, output_dir, debug=debug)
                result['images'] = images
                if images:
                    print(f"  Saved {len(images)} images")

            return result
        else:
            print("  No response received (timeout)")
            return None

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        if debug:
            traceback.print_exc()
        return None

    finally:
        if context:
            context.close()
        if playwright:
            playwright.stop()


def main():
    parser = argparse.ArgumentParser(description="Ask OpenEvidence a question")
    parser.add_argument(
        "--question", "-q",
        required=True,
        help="The medical question to ask",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show the browser window (for debugging)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show debug output for response detection",
    )
    parser.add_argument(
        "--save-images",
        action="store_true",
        help="Save screenshot and extract images from response",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        help="Directory to save images (default: data/responses)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Fast mode: reduced delays (~5-8 seconds)",
    )
    parser.add_argument(
        "--turbo",
        action="store_true",
        help="Turbo mode: maximum speed (~3-5 seconds), may be less reliable",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream response as it appears (shows text incrementally)",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None

    result = ask_openevidence(
        question=args.question,
        headless=not args.show_browser,
        debug=args.debug,
        save_images=args.save_images,
        output_dir=output_dir,
        fast=args.fast,
        turbo=args.turbo,
        stream=args.stream,
    )

    if result:
        answer = result['answer']

        # For non-streaming mode, print the full response
        if not args.stream:
            print()
            print("=" * 60)
            print("OPENEVIDENCE RESPONSE [PRESENT VERBATIM - DO NOT SUMMARIZE]")
            print("=" * 60)
            print()
            print(answer)
            print()

        # Show saved files
        if result.get('screenshot'):
            print(f"Screenshot: {result['screenshot']}")
        if result.get('images'):
            print(f"Images saved: {', '.join(result['images'])}")

        print("-" * 60)
        print("Source: OpenEvidence (https://www.openevidence.com)")
        print("-" * 60)
    else:
        print()
        print("Failed to get response from OpenEvidence.")
        print("Try running with --show-browser to debug.")
        sys.exit(1)


if __name__ == "__main__":
    main()
