"""
OpenEvidence Configuration

CSS selectors and settings for browser automation.
These may need adjustment based on OpenEvidence UI changes.
"""

from pathlib import Path

# Base URLs
BASE_URL = "https://www.openevidence.com"
LOGIN_URL = "https://www.openevidence.com/api/auth/login"
CHAT_URL = "https://www.openevidence.com"  # Main page has chat interface

# Data directories
SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "data"
BROWSER_STATE_DIR = DATA_DIR / "browser_state"
BROWSER_PROFILE_DIR = BROWSER_STATE_DIR / "browser_profile"
STATE_JSON = BROWSER_STATE_DIR / "state.json"
AUTH_INFO_JSON = DATA_DIR / "auth_info.json"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)

# Login page selectors (Auth0-based)
LOGIN_BUTTON_SELECTORS = [
    'button:has-text("Log In")',
    'a:has-text("Log In")',
    '[data-testid="login-button"]',
    '.MuiButton-root:has-text("Log In")',
]

# Apple Sign-In selectors (on Auth0 login page)
APPLE_LOGIN_SELECTORS = [
    'button:has-text("Continue with Apple")',
    'button:has-text("Sign in with Apple")',
    '[data-provider="apple"]',
    'a:has-text("Apple")',
    '.apple-button',
    '[aria-label*="Apple"]',
]

# Chat input selectors (Material-UI based)
QUERY_INPUT_SELECTORS = [
    'textarea[placeholder*="Ask"]',
    'textarea[placeholder*="question"]',
    'input[placeholder*="Ask"]',
    '.MuiOutlinedInput-input',
    '.MuiInputBase-input',
    '[data-testid="chat-input"]',
    'textarea',
]

# Submit button selectors
SUBMIT_BUTTON_SELECTORS = [
    'button[type="submit"]',
    'button:has-text("Send")',
    'button[aria-label="Send"]',
    '.MuiButton-contained',
    '[data-testid="send-button"]',
    'button svg[data-testid="SendIcon"]',
    'button:has(svg)',  # Button containing an icon (common for send)
]

# Response area selectors (OpenEvidence uses Material-UI)
RESPONSE_SELECTORS = [
    # Try specific OpenEvidence patterns first
    '[data-testid="response"]',
    '[data-testid="answer"]',
    '[data-testid="ai-message"]',
    '[data-testid="assistant-message"]',
    # Common chat UI patterns
    '[class*="response"]',
    '[class*="answer"]',
    '[class*="assistant"]',
    '[class*="ai-message"]',
    '[class*="bot-message"]',
    '[class*="chat-message"]',
    # Material-UI markdown/prose containers
    '[class*="prose"]',
    '[class*="markdown"]',
    '[class*="MuiBox"]',
    # Generic message containers
    '[class*="message"]:not([class*="user"])',
    'div[class*="Message"]',
    # Broader fallbacks
    'article',
    'main [class*="content"]',
]

# Loading/thinking indicators
LOADING_SELECTORS = [
    '[data-testid="loading"]',
    '.MuiCircularProgress-root',
    '[class*="loading"]',
    '[class*="typing"]',
    '[class*="thinking"]',
]

# Success indicators (logged in state)
LOGGED_IN_INDICATORS = [
    '[data-testid="user-menu"]',
    '[data-testid="avatar"]',
    'button:has-text("Log Out")',
    'a:has-text("Log Out")',
    '.user-avatar',
    '[class*="profile"]',
]

# Timeouts (milliseconds)
PAGE_LOAD_TIMEOUT = 30000
LOGIN_TIMEOUT = 120000  # 2 minutes for manual login
QUERY_TIMEOUT = 120000  # 2 minutes for response
ELEMENT_TIMEOUT = 10000

# Stealth settings (normal mode)
TYPING_WPM_MIN = 160
TYPING_WPM_MAX = 240

# Fast mode settings (aggressive for speed)
FAST_MODE = {
    'after_load': (300, 500),        # Minimal wait after page load
    'after_popup': (100, 200),       # Quick popup dismiss
    'after_submit': (200, 400),      # Quick submit wait
    'stable_checks': 1,              # Single stability check
    'poll_interval': 0.5,            # Faster polling (seconds)
}

# Turbo mode settings (maximum speed, may be less reliable)
TURBO_MODE = {
    'after_load': (100, 200),
    'after_popup': (50, 100),
    'after_submit': (100, 200),
    'stable_checks': 1,
    'poll_interval': 0.3,
}

# Normal mode settings (human-like for stealth)
NORMAL_MODE = {
    'after_load': (2000, 3000),
    'after_popup': (500, 1000),
    'after_submit': (1000, 2000),
    'stable_checks': 3,
    'poll_interval': 1.0,
}
