from __future__ import annotations

from dataclasses import dataclass

from .browser import LOGIN_BUTTON_SELECTORS, LOADING_SELECTORS, QUERY_INPUT_SELECTORS


RESPONSE_SELECTORS = [
    '[data-testid="assistant-message"]',
    '[data-testid="ai-message"]',
    '[data-testid="answer"]',
    '[class*="assistant"]',
    '[class*="response"]',
    '[class*="answer"]',
    '[class*="message"] article',
    "main article",
    "article",
]
IGNORED_TEXT_FRAGMENTS = (
    "protected health information",
    "cookie",
    "log in",
    "sign in",
)


@dataclass(frozen=True)
class CandidateText:
    selector: str
    index: int
    text: str


def normalize_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def dom_safe_selectors(selectors: list[str]) -> list[str]:
    safe: list[str] = []
    for selector in selectors:
        if ":has-text(" in selector:
            continue
        safe.append(selector)
    return safe


def choose_last_assistant_turn(candidates: list[CandidateText]) -> CandidateText | None:
    filtered: list[CandidateText] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_text(candidate.text)
        if not normalized or len(normalized) < 10:
            continue
        if any(fragment in normalized for fragment in IGNORED_TEXT_FRAGMENTS):
            continue
        key = f"{candidate.selector}:{normalized}"
        if key in seen:
            continue
        filtered.append(candidate)
        seen.add(key)
    if not filtered:
        return None
    return filtered[-1]


def silent_relogin_possible_from_cookies(cookies: list[dict[str, object]]) -> bool:
    for cookie in cookies:
        name = str(cookie.get("name") or "").lower()
        domain = str(cookie.get("domain") or "").lower()
        if "auth0" in name or "auth0" in domain:
            return True
        if name in {"did", "did_compat"} and "auth.openevidence.com" in domain:
            return True
    return False


def classify_timeout(snapshot: dict[str, object] | None) -> str:
    if not snapshot:
        return "timeout-without-snapshot"
    if snapshot.get("login_visible"):
        return "login-required"
    if snapshot.get("loading_visible"):
        return "loading-never-settled"
    if snapshot.get("input_visible") and not snapshot.get("candidates"):
        return "response-not-detected"
    return "generic-timeout"


def collect_response_snapshot(page: object) -> dict[str, object]:
    payload = {
        "responseSelectors": RESPONSE_SELECTORS,
        "loadingSelectors": LOADING_SELECTORS,
        "loginSelectors": dom_safe_selectors(LOGIN_BUTTON_SELECTORS),
        "inputSelectors": QUERY_INPUT_SELECTORS,
    }
    script = """
    (payload) => {
      const isVisible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        return style && style.display !== "none" && style.visibility !== "hidden";
      };
      const textOf = (element) => (element && element.innerText ? element.innerText.trim() : "");
      const candidates = [];
      for (const selector of payload.responseSelectors) {
        const elements = Array.from(document.querySelectorAll(selector));
        elements.forEach((element, index) => {
          if (!isVisible(element)) return;
          const text = textOf(element);
          if (!text) return;
          candidates.push({selector, index, text});
        });
      }
      const anyVisible = (selectors) => selectors.some((selector) => {
        try {
          const element = document.querySelector(selector);
          return isVisible(element);
        } catch (error) {
          return false;
        }
      });
      const loginTextVisible = Array.from(document.querySelectorAll("button,a")).some((element) => (
        isVisible(element) && textOf(element).toLowerCase().includes("log in")
      ));
      return {
        url: window.location.href,
        candidates,
        loading_visible: anyVisible(payload.loadingSelectors),
        login_visible: loginTextVisible || anyVisible(payload.loginSelectors),
        input_visible: anyVisible(payload.inputSelectors),
      };
    }
    """
    snapshot = page.evaluate(script, payload)
    raw_candidates = snapshot.get("candidates") or []
    candidates = [
        CandidateText(
            selector=str(item.get("selector")),
            index=int(item.get("index", 0)),
            text=str(item.get("text", "")),
        )
        for item in raw_candidates
    ]
    snapshot["candidates"] = candidates
    snapshot["selected_candidate"] = choose_last_assistant_turn(candidates)
    return snapshot
