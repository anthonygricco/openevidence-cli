#!/usr/bin/env python3
"""
OpenEvidence Question Interface

Ask medical questions and get evidence-based answers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
    STATE_JSON,
    SUBMIT_BUTTON_SELECTORS,
    TURBO_MODE,
)
from browser_utils import BrowserFactory, StealthUtils
from auth_manager import AuthManager


CACHE_DIR = DATA_DIR / "cache"


def get_cache_key(question: str) -> str:
    """Generate a cache key from the question text."""
    normalized = question.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def get_cached_response(question: str, cache_ttl: int = 86400) -> dict | None:
    """
    Check cache for a previous response to this question.

    Args:
        question: The question text
        cache_ttl: Cache time-to-live in seconds (default 24 hours)

    Returns:
        Cached result dict or None if not cached/expired
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = get_cache_key(question)
    cache_file = CACHE_DIR / f"{key}.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r') as f:
            cached = json.load(f)

        # Check TTL
        cached_time = cached.get('timestamp', 0)
        if time.time() - cached_time > cache_ttl:
            cache_file.unlink()
            return None

        return cached.get('result')
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def save_to_cache(question: str, result: dict) -> None:
    """Save a response to the cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = get_cache_key(question)
    cache_file = CACHE_DIR / f"{key}.json"

    # Don't cache timings (they're per-run)
    cache_result = {k: v for k, v in result.items() if k != 'timings'}

    try:
        with open(cache_file, 'w') as f:
            json.dump({
                'question': question,
                'timestamp': time.time(),
                'result': cache_result,
            }, f, indent=2)
    except OSError:
        pass


API_TEMPLATE_FILE = DATA_DIR / "api_template.json"


def ask_via_api(
    question: str,
    progressive: bool = False,
    debug: bool = False,
    timeout: int = 120,
    no_cache: bool = False,
    cache_ttl: int = 86400,
) -> dict | None:
    """
    Ask OpenEvidence via direct API, bypassing browser entirely.
    Requires api_template.json from a previous browser-mode run.
    Falls back gracefully if template is missing or auth fails.
    """
    import urllib.request
    import urllib.error

    # Check cache first
    if not no_cache:
        cached = get_cached_response(question, cache_ttl)
        if cached:
            if progressive:
                print("[FINAL]", flush=True)
                print(cached.get('answer', ''), flush=True)
                print("[/FINAL]", flush=True)
            else:
                print(f"[CACHED] Returning cached response ({len(cached.get('answer', ''))} chars)")
            cached['timings'] = {'cache_hit': 0.0}
            return cached

    # Load API template (captured from a previous browser run)
    if not API_TEMPLATE_FILE.exists():
        if debug:
            print("  No API template found. Run a browser query first to capture API format.")
        return None

    try:
        with open(API_TEMPLATE_FILE) as f:
            template = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # Load cookies from browser state
    if not STATE_JSON.exists():
        if debug:
            print("  No browser state found. Run auth first.")
        return None

    try:
        with open(STATE_JSON) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    cookies = state.get('cookies', [])
    cookie_str = '; '.join(
        f"{c['name']}={c['value']}"
        for c in cookies
        if 'openevidence.com' in c.get('domain', '')
    )
    if not cookie_str:
        if debug:
            print("  No OpenEvidence cookies found in state.")
        return None

    timings = {}
    phase_start = time.time()

    # Build POST body from template
    body = template.get('body_template', {}).copy()
    question_field = template.get('question_field', 'question')
    body[question_field] = question

    # Build headers
    headers = {}
    for k, v in template.get('headers', {}).items():
        if k.lower() not in ('cookie', 'host', 'content-length'):
            headers[k] = v
    headers['Cookie'] = cookie_str
    headers.setdefault('Content-Type', 'application/json')
    headers.setdefault('Origin', 'https://www.openevidence.com')
    headers.setdefault('Referer', 'https://www.openevidence.com/')
    headers.setdefault('User-Agent', (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/131.0.0.0 Safari/537.36'
    ))

    api_url = template.get('url', 'https://www.openevidence.com/api/article')
    print(f"[API] Asking: {question[:80]}{'...' if len(question) > 80 else ''}")

    # POST /api/article to create question
    try:
        post_data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(api_url, data=post_data, headers=headers, method='POST')
        resp = urllib.request.urlopen(req, timeout=30)

        if resp.status != 201:
            if debug:
                print(f"  API POST returned {resp.status}, expected 201")
            return None

        result_data = json.loads(resp.read())
        article_id = result_data.get('id') or result_data.get('uuid') or result_data.get('articleId')

        if not article_id:
            if debug:
                print(f"  No article ID in POST response: {list(result_data.keys())}")
            return None

        timings['api_post'] = time.time() - phase_start
        if debug:
            print(f"  Article created: {article_id}")

    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
        if debug:
            print(f"  API POST failed: {e}")
        return None

    # Poll GET /api/article/<uuid> for response
    phase_start = time.time()
    poll_url = f"https://www.openevidence.com/api/article/{article_id}"
    deadline = time.time() + timeout
    poll_start = time.time()

    # Progressive state
    prog_last_time = 0.0
    prog_last_len = 0
    prog_first = False

    print("  Polling for response...")
    answer = None

    while time.time() < deadline:
        try:
            poll_req = urllib.request.Request(poll_url, headers={
                'Cookie': cookie_str,
                'User-Agent': headers.get('User-Agent', ''),
                'Accept': 'application/json',
            })
            resp = urllib.request.urlopen(poll_req, timeout=15)
            data = json.loads(resp.read())

            status = data.get('status') or data.get('state')
            content = (
                data.get('content') or data.get('answer')
                or data.get('response') or data.get('body') or ''
            )

            elapsed = time.time() - poll_start

            # Progressive: emit partial results at intervals
            if progressive and isinstance(content, str) and len(content) > 200:
                should_emit = False
                if not prog_first and elapsed >= 8:
                    should_emit = True
                    prog_first = True
                elif prog_first:
                    if elapsed - prog_last_time >= 15 and len(content) - prog_last_len > 300:
                        should_emit = True
                if should_emit:
                    prog_last_time = elapsed
                    prog_last_len = len(content)
                    print("[PARTIAL]", flush=True)
                    print(content, flush=True)
                    print("[/PARTIAL]", flush=True)

            if status in ('complete', 'completed', 'done', 'finished', 'success'):
                if isinstance(content, str) and len(content) > 200:
                    answer = content
                    break
                elif debug:
                    print(f"  Status={status} but content short ({len(content) if content else 0} chars)")

            if debug and content:
                print(f"  Poll: status={status}, {len(content)} chars, {elapsed:.0f}s")

        except Exception as e:
            if debug:
                print(f"  Poll error: {e}")

        time.sleep(0.5)

    if answer:
        timings['response_wait'] = time.time() - phase_start
        print(f"  Got response ({len(answer)} chars)")

        if progressive:
            print("[FINAL]", flush=True)
            print(answer, flush=True)
            print("[/FINAL]", flush=True)

        result = {
            'answer': answer,
            'images': [],
            'screenshot': None,
            'timings': timings,
        }

        if not no_cache:
            save_to_cache(question, result)

        return result
    else:
        print("  No response received via API")
        return None


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
    - Send button disabled (still generating)
    - Stop/cancel button visible (still generating)
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

            // Check for stop/cancel button (visible during generation)
            const stopBtn = document.querySelector('button[aria-label="Stop"], button:has(svg[data-testid="StopIcon"]), [class*="stop"]');
            if (stopBtn && stopBtn.offsetParent !== null) return true;

            // Check if send button is disabled (still generating)
            const sendBtn = document.querySelector('button[type="submit"], button[aria-label="Send"]');
            if (sendBtn && sendBtn.disabled) return true;

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
    progressive: bool = False,
    benchmark: bool = False,
    no_cache: bool = False,
    cache_ttl: int = 86400,
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
        progressive: Emit [PARTIAL]/[FINAL] delimited output at intervals
        benchmark: Collect and return phase timing data
        no_cache: Bypass cache
        cache_ttl: Cache time-to-live in seconds (default 24h)

    Returns:
        Dict with 'answer', 'images', 'screenshot' keys, or None on failure
    """
    # Check cache first (unless bypassed)
    if not no_cache:
        cached = get_cached_response(question, cache_ttl)
        if cached:
            if progressive:
                print("[FINAL]", flush=True)
                print(cached.get('answer', ''), flush=True)
                print("[/FINAL]", flush=True)
            else:
                print(f"[CACHED] Returning cached response ({len(cached.get('answer', ''))} chars)")
            cached['timings'] = {'cache_hit': 0.0}
            return cached

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

    # Phase timing
    timings = {}
    phase_start = time.time()

    playwright = None
    context = None

    # Shared state for API interception
    api_done = {'done': False, 'api_text': None, 'article_id': None, 'last_status': None}

    def on_response(response):
        """Monitor network responses to detect when OE's API finishes streaming."""
        url = response.url
        # Skip static assets, images, fonts, etc.
        skip_patterns = ['.js', '.css', '.png', '.jpg', '.svg', '.ico', '.woff', '.ttf',
                         'fonts.', 'analytics', 'gtag', 'sentry', 'segment', '_next/static',
                         'storage.googleapis.com', 'cookieyes']
        if any(p in url for p in skip_patterns):
            return

        try:
            # Capture article creation (POST /api/article → 201)
            if '/api/article' in url and response.status == 201:
                try:
                    body = response.json()
                    article_id = body.get('id') or body.get('uuid')
                    if article_id:
                        api_done['article_id'] = article_id
                        if debug:
                            print(f"    DEBUG API: Article created: {article_id}")
                except Exception:
                    pass

            # Monitor article polling (GET /api/article/<uuid>) for completion
            if api_done.get('article_id') and api_done['article_id'] in url and response.status == 200:
                try:
                    body = response.json()
                    status = body.get('status') or body.get('state')
                    api_done['last_status'] = status
                    # Detect completion from API response fields
                    if status in ('complete', 'completed', 'done', 'finished', 'success'):
                        api_done['done'] = True
                        if debug:
                            print(f"    DEBUG API: Article complete (status={status})")
                    # Also check for content fields that indicate completion
                    content = body.get('content') or body.get('answer') or body.get('response') or body.get('body')
                    if content and isinstance(content, str) and len(content) > 500:
                        api_done['api_text'] = content
                except Exception:
                    pass

            # Completion tracker signal
            if '/api/article/ct' in url and 'status=success' in url:
                api_done['done'] = True
                if debug:
                    print(f"    DEBUG API: Completion tracker fired")

            # Log other API calls in debug mode
            if debug and '/api/' in url and 'events' not in url:
                content_type = response.headers.get('content-type', '')
                print(f"    DEBUG API: {response.status} {content_type[:30]} {url[:100]}")
        except Exception:
            pass

    try:
        playwright = sync_playwright().start()
        context = BrowserFactory.launch_persistent_context(
            playwright,
            headless=headless,
        )
        timings['browser_launch'] = time.time() - phase_start

        page = context.new_page()

        # Capture API request template for future --api mode
        def on_request(request):
            if ('/api/article' in request.url and request.method == 'POST'
                    and '/ct' not in request.url and request.post_data):
                try:
                    body = json.loads(request.post_data)
                    # Identify which field holds the question
                    q_field = None
                    for key, value in body.items():
                        if isinstance(value, str) and len(value) > 20 and question[:20].lower() in value.lower():
                            q_field = key
                            break
                    template = {
                        'url': request.url,
                        'headers': {
                            k: v for k, v in request.headers.items()
                            if k.lower() not in ('cookie', 'host', 'content-length')
                        },
                        'body_template': {k: v for k, v in body.items() if k != q_field},
                        'question_field': q_field or 'question',
                    }
                    with open(API_TEMPLATE_FILE, 'w') as f:
                        json.dump(template, f, indent=2)
                    if debug:
                        print(f"    DEBUG: Captured API template (question_field={q_field})")
                except Exception:
                    pass

        page.on("request", on_request)

        # Set up API interception to detect completion faster
        page.on("response", on_response)

        # Navigate to OpenEvidence
        phase_start = time.time()
        print("  Opening OpenEvidence...")
        wait_strategy = "commit" if turbo else "domcontentloaded"
        page.goto(BASE_URL, wait_until=wait_strategy, timeout=PAGE_LOAD_TIMEOUT)
        StealthUtils.random_delay(*mode['after_load'])

        # Dismiss any initial popups (HIPAA consent, cookies, etc.)
        dismiss_popups(page)
        StealthUtils.random_delay(*mode['after_popup'])
        timings['page_load'] = time.time() - phase_start

        # Find chat input
        phase_start = time.time()
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
        timings['input'] = time.time() - phase_start

        # Submit the question
        phase_start = time.time()
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

        timings['submit'] = time.time() - phase_start

        # Wait for response
        phase_start = time.time()
        if stream:
            print("  Streaming response...\n")
            print("=" * 60)
            print("OPENEVIDENCE RESPONSE")
            print("=" * 60 + "\n")
        elif progressive:
            print("  Waiting for response (progressive output)...")
        else:
            print("  Waiting for response...")

        answer = None
        stable_count = 0
        last_text = None
        printed_len = 0  # For streaming: track how much we've printed
        deadline = time.time() + QUERY_TIMEOUT / 1000
        submit_time = time.time()

        base_poll_interval = mode.get('poll_interval', 1.0)
        poll_interval = base_poll_interval
        min_chars = mode.get('min_response_chars', 300)
        min_wait = mode.get('min_wait_after_submit', 3.0)
        first_text_seen = False
        # Progressive output state
        progressive_last_emit_time = 0.0
        progressive_last_emit_len = 0
        progressive_first_emitted = False
        # Use faster polling for streaming/progressive
        if stream:
            poll_interval = 0.2
        elif progressive:
            poll_interval = 0.3

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
                # Adaptive polling: once we see text, slow down slightly
                if not first_text_seen:
                    first_text_seen = True
                    if not stream and not progressive:
                        poll_interval = base_poll_interval * 1.5  # Text is flowing, poll less aggressively

                # Progressive: emit partial results at intervals
                if progressive and len(text) > 200:
                    should_emit = False
                    if not progressive_first_emitted and elapsed >= 8:
                        should_emit = True
                        progressive_first_emitted = True
                    elif progressive_first_emitted:
                        time_since = elapsed - progressive_last_emit_time
                        growth = len(text) - progressive_last_emit_len
                        if time_since >= 15 and growth > 300:
                            should_emit = True
                    if should_emit:
                        progressive_last_emit_time = elapsed
                        progressive_last_emit_len = len(text)
                        print("[PARTIAL]", flush=True)
                        print(text, flush=True)
                        print("[/PARTIAL]", flush=True)

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
                        # If API signaled done, accept immediately if text looks complete
                        if api_done['done'] and response_looks_complete(text):
                            if debug:
                                print(f"    DEBUG: API done + complete response ({len(text)} chars)")
                            answer = text
                            break

                        # Check if OE is still actively streaming
                        if is_response_streaming(page) and not api_done['done']:
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

        # If API captured text directly and it's better than DOM extraction, use it
        if api_done.get('api_text') and (not answer or len(api_done['api_text']) > len(answer)):
            if debug:
                print(f"    DEBUG: Using API-captured text ({len(api_done['api_text'])} chars vs DOM {len(answer) if answer else 0})")
            # Prefer DOM text as it includes rendered formatting, but API text is a good fallback
            if not answer:
                answer = api_done['api_text']

        if stream:
            print("\n")  # End streaming output

        # Retry logic: if response is short/incomplete, wait more and try again
        if answer and not response_looks_complete(answer) and len(answer) < 1000:
            print(f"  Response looks incomplete ({len(answer)} chars), retrying extraction...")
            for retry in range(3):
                time.sleep(2.0)
                retry_text = get_response_text(page, debug=debug, min_chars=min_chars)
                if retry_text and len(retry_text) > len(answer):
                    answer = retry_text
                    if response_looks_complete(answer):
                        print(f"  Retry {retry + 1}: got complete response ({len(answer)} chars)")
                        break
                    print(f"  Retry {retry + 1}: got {len(retry_text)} chars, still growing...")

        # If we still have nothing, do a final extraction attempt with lower threshold
        if not answer:
            print("  Attempting final extraction with lower threshold...")
            time.sleep(2.0)
            answer = get_response_text(page, debug=debug, min_chars=100)
            if answer:
                print(f"  Final extraction got {len(answer)} chars")

        if answer:
            timings['response_wait'] = time.time() - phase_start
            print(f"  Got response ({len(answer)} chars)")

            # Progressive: emit final result
            if progressive:
                print("[FINAL]", flush=True)
                print(answer, flush=True)
                print("[/FINAL]", flush=True)

            result = {
                'answer': answer,
                'images': [],
                'screenshot': None,
                'timings': timings,
            }

            # Save to cache
            if not no_cache:
                save_to_cache(question, result)

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
    parser.add_argument(
        "--progressive",
        action="store_true",
        help="Emit [PARTIAL] and [FINAL] delimited output for progressive display",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Print performance metrics (latency, char count, completeness)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass response cache",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=86400,
        help="Cache time-to-live in seconds (default: 86400 = 24h)",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Use direct API mode (no browser). Requires a prior browser run to capture API template.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format: text (default), json, or markdown",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None

    start_time = time.time()

    result = None

    # Try API mode first if requested
    if args.api:
        result = ask_via_api(
            question=args.question,
            progressive=args.progressive,
            debug=args.debug,
            no_cache=args.no_cache,
            cache_ttl=args.cache_ttl,
        )
        if not result:
            print("  API mode failed, falling back to browser...")

    # Fall back to browser mode
    if not result:
        result = ask_openevidence(
            question=args.question,
            headless=not args.show_browser,
            debug=args.debug,
            save_images=args.save_images,
            output_dir=output_dir,
            fast=args.fast,
            turbo=args.turbo,
            stream=args.stream,
            progressive=args.progressive,
            benchmark=args.benchmark,
            no_cache=args.no_cache,
            cache_ttl=args.cache_ttl,
        )

    elapsed = time.time() - start_time

    if result:
        answer = result['answer']

        if args.format == "json":
            # JSON output: structured data
            import re
            output = {
                'question': args.question,
                'answer': answer,
                'citations': len(re.findall(r'\[\d+\]', answer)),
                'cached': 'cache_hit' in result.get('timings', {}),
                'timing': round(elapsed, 1),
                'source': 'https://www.openevidence.com',
            }
            if result.get('images'):
                output['images'] = result['images']
            if result.get('screenshot'):
                output['screenshot'] = result['screenshot']
            print(json.dumps(output, indent=2))

        elif args.format == "markdown":
            # Markdown output: clean document
            print(f"# OpenEvidence Response\n")
            print(f"**Question:** {args.question}\n")
            print(answer)
            print(f"\n---\n*Source: [OpenEvidence](https://www.openevidence.com) | {elapsed:.1f}s*")

        else:
            # Default text format
            if not args.stream and not args.progressive:
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

        # Benchmark output (all formats)
        if args.benchmark:
            import re
            has_citations = bool(re.search(r'\[\d+\]', answer))
            citation_count = len(re.findall(r'\[\d+\]', answer))
            has_refs = 'references' in answer.lower() or 'et al.' in answer.lower()
            mode_name = "api" if args.api else "turbo" if args.turbo else "fast" if args.fast else "normal"
            print()
            print("=" * 60)
            print("BENCHMARK RESULTS")
            print("=" * 60)
            print(f"  Mode:         {mode_name}")
            print(f"  Latency:      {elapsed:.1f}s")
            print(f"  Response:     {len(answer)} chars")
            print(f"  Citations:    {citation_count} markers ({'yes' if has_citations else 'no'})")
            print(f"  References:   {'yes' if has_refs else 'no'}")
            print(f"  Complete:     {'yes' if response_looks_complete(answer) else 'no'}")
            print(f"  Paragraphs:   {answer.count(chr(10) + chr(10)) + 1}")

            # Phase timings
            timings = result.get('timings', {})
            if timings:
                print()
                print("  Phase Breakdown:")
                for phase, duration in timings.items():
                    print(f"    {phase:20s} {duration:.1f}s")
                accounted = sum(timings.values())
                print(f"    {'overhead':20s} {elapsed - accounted:.1f}s")
            print("=" * 60)
    else:
        print()
        print("Failed to get response from OpenEvidence.")
        print("Try running with --show-browser to debug.")
        sys.exit(1)


if __name__ == "__main__":
    main()
