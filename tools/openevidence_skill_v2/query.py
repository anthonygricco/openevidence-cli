from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .artifacts import ArtifactOptions, capture_query_artifacts
from .auth import (
    attempt_silent_relogin,
    is_logged_in,
    login_button_visible,
    save_auth_info,
)
from .bootstrap import ensure_runtime_directories, migrate_legacy_state
from .browser import (
    BASE_URL,
    BrowserFactory,
    LOGIN_BUTTON_SELECTORS,
    PAGE_LOAD_TIMEOUT,
    QUERY_INPUT_SELECTORS,
    QUERY_TIMEOUT,
    StealthUtils,
    dismiss_popups,
    find_submit_button,
    find_visible_element,
    load_playwright,
)
from .config import RuntimeContext
from .diagnostics import write_failure_bundle
from .extract import classify_timeout, collect_response_snapshot, normalize_text
from .render import RenderOptions, format_chatwise_result, format_text_result


MODE_SETTINGS = {
    "turbo": {
        "stable_checks": 3,
        "use_human_type": False,
        "after_load": (200, 400),
        "after_submit": (150, 300),
        "min_visible_seconds": 3.0,
        "min_quiet_seconds": 3.0,
    },
    "fast": {
        "stable_checks": 4,
        "use_human_type": False,
        "after_load": (400, 700),
        "after_submit": (250, 500),
        "min_visible_seconds": 3.0,
        "min_quiet_seconds": 3.0,
    },
    "normal": {
        "stable_checks": 4,
        "use_human_type": True,
        "after_load": (1200, 1800),
        "after_submit": (600, 900),
        "min_visible_seconds": 3.5,
        "min_quiet_seconds": 3.0,
    },
}

CITATION_CUE_RE = re.compile(r"\[\d+\]|\b(?:PMID|DOI)\b|\b(?:NCCN|ASCO|ASTRO|ESMO|NEJM|JAMA|LANCET|BMJ)\b", re.IGNORECASE)
THINKING_NOISE_RE = re.compile(r"^(?:Finished thinking\s*)+", re.IGNORECASE)


@dataclass(frozen=True)
class QueryOptions:
    mode: str
    output_format: str
    show_browser: bool
    debug: bool
    profile_dir: Path | None = None
    artifacts: ArtifactOptions = field(default_factory=ArtifactOptions)
    render: RenderOptions = field(default_factory=RenderOptions)


def answer_quality(answer: str) -> tuple[bool, int]:
    stripped = sanitize_answer_text(answer)
    normalized = normalize_text(stripped)
    normalized_len = len(normalized)
    has_citation_cue = bool(CITATION_CUE_RE.search(stripped))
    has_structure = stripped.count("\n") >= 2 or stripped.count("•") >= 2 or stripped.count("- ") >= 2
    confident = normalized_len >= 450 or (normalized_len >= 220 and has_citation_cue) or (normalized_len >= 300 and has_structure)
    return confident, normalized_len


def sanitize_answer_text(answer: str) -> str:
    cleaned = THINKING_NOISE_RE.sub("", answer.strip())
    return cleaned.lstrip()


def response_ready_to_return(
    answer: str,
    *,
    stable_count: int,
    stable_checks: int,
    first_seen_at: float | None,
    last_change_at: float | None,
    now: float,
    loading_visible: bool,
    min_visible_seconds: float,
    min_quiet_seconds: float,
) -> bool:
    if loading_visible or not answer.strip() or first_seen_at is None or last_change_at is None:
        return False
    if stable_count < stable_checks:
        return False

    quiet_seconds = now - last_change_at
    visible_seconds = now - first_seen_at
    confident, normalized_len = answer_quality(answer)
    if confident:
        return quiet_seconds >= min_quiet_seconds and visible_seconds >= min_visible_seconds

    return (
        normalized_len >= 80
        and quiet_seconds >= max(min_quiet_seconds + 2.0, 5.0)
        and visible_seconds >= max(min_visible_seconds + 4.0, 7.0)
    )


def result_confident_enough(result: dict[str, object]) -> bool:
    if not result.get("ok"):
        return False
    confident, normalized_len = answer_quality(str(result.get("answer") or ""))
    return confident or normalized_len >= 700


def result_quality_key(result: dict[str, object]) -> tuple[int, int]:
    confident, normalized_len = answer_quality(str(result.get("answer") or ""))
    return (1 if confident else 0, normalized_len)


def _submit_question(page: object, input_selector: str, question: str, use_human_type: bool) -> None:
    if use_human_type:
        StealthUtils.human_type(page, input_selector, question)
    else:
        page.fill(input_selector, question)
    StealthUtils.random_delay(150, 300)

    button = find_submit_button(page, input_selector)
    if button is not None:
        try:
            button.click()
            return
        except Exception:  # noqa: BLE001
            pass
    for key in ("Meta+Enter", "Control+Enter", "Enter"):
        try:
            page.keyboard.press(key)
            return
        except Exception:  # noqa: BLE001
            continue


def _wait_for_response(page: object, settings: dict[str, object], debug: bool = False) -> tuple[str | None, dict[str, object]]:
    stable_checks = int(settings["stable_checks"])
    min_visible_seconds = float(settings["min_visible_seconds"])
    min_quiet_seconds = float(settings["min_quiet_seconds"])
    deadline = time.time() + QUERY_TIMEOUT / 1000
    last_normalized = None
    stable_count = 0
    first_seen_at: float | None = None
    last_change_at: float | None = None
    snapshot: dict[str, object] = {}
    high_demand_polls = 0

    while time.time() < deadline:
        now = time.time()
        dismiss_popups(page, debug=debug)
        snapshot = collect_response_snapshot(page)
        if snapshot.get("high_demand_visible") and not snapshot.get("loading_visible") and not snapshot.get("candidates"):
            high_demand_polls += 1
            if high_demand_polls >= 3:
                return None, snapshot
        else:
            high_demand_polls = 0
        selected = snapshot.get("selected_candidate")
        if selected is not None:
            normalized = normalize_text(selected.text)
            if first_seen_at is None:
                first_seen_at = now
            if normalized == last_normalized:
                stable_count += 1
            else:
                stable_count = 1
                last_normalized = normalized
                last_change_at = now
            if response_ready_to_return(
                selected.text,
                stable_count=stable_count,
                stable_checks=stable_checks,
                first_seen_at=first_seen_at,
                last_change_at=last_change_at,
                now=now,
                loading_visible=bool(snapshot.get("loading_visible")),
                min_visible_seconds=min_visible_seconds,
                min_quiet_seconds=min_quiet_seconds,
            ):
                return sanitize_answer_text(selected.text), snapshot
        else:
            stable_count = 0
        time.sleep(1)
    return None, snapshot


def _timeout_error_message(snapshot: dict[str, object]) -> str:
    reason = classify_timeout(snapshot)
    if reason == "service-overloaded":
        return "OpenEvidence is reporting exceptionally high demand. Retry again later."
    return f"OpenEvidence timed out waiting for a stable response ({reason})."


def run_single_query(ctx: RuntimeContext, question: str, options: QueryOptions) -> dict[str, object]:
    ensure_runtime_directories(ctx)
    migrate_legacy_state(ctx)

    playwright_manager = load_playwright()
    playwright = None
    context = None
    page = None
    try:
        playwright = playwright_manager().start()
        context = BrowserFactory.launch_persistent_context(
            playwright,
            ctx,
            headless=not options.show_browser,
            profile_dir=options.profile_dir,
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        StealthUtils.random_delay(*MODE_SETTINGS[options.mode]["after_load"])
        dismiss_popups(page, debug=options.debug)

        if login_button_visible(page):
            if not attempt_silent_relogin(page, ctx, debug=options.debug):
                snapshot = collect_response_snapshot(page)
                diagnostics_dir = write_failure_bundle(
                    ctx,
                    "login-required",
                    snapshot=snapshot,
                    page=page,
                    extra={"question": question},
                )
                save_auth_info(
                    ctx,
                    authenticated=False,
                    last_failure_reason="login-required",
                    last_validation=datetime.now().isoformat(),
                )
                return {
                    "ok": False,
                    "question": question,
                    "error": "Authentication expired. Run auth_manager.py reauth.",
                    "diagnostics_dir": str(diagnostics_dir),
                }

        input_element, input_selector = find_visible_element(page, QUERY_INPUT_SELECTORS)
        if not input_element or not input_selector:
            snapshot = collect_response_snapshot(page)
            diagnostics_dir = write_failure_bundle(
                ctx,
                "missing-input",
                snapshot=snapshot,
                page=page,
                extra={"question": question},
            )
            return {
                "ok": False,
                "question": question,
                "error": "Could not find the OpenEvidence input box.",
                "diagnostics_dir": str(diagnostics_dir),
            }

        _submit_question(page, input_selector, question, use_human_type=MODE_SETTINGS[options.mode]["use_human_type"])
        StealthUtils.random_delay(*MODE_SETTINGS[options.mode]["after_submit"])
        dismiss_popups(page, debug=options.debug)

        answer, snapshot = _wait_for_response(page, MODE_SETTINGS[options.mode], debug=options.debug)
        if answer:
            artifacts = capture_query_artifacts(page, ctx, question, snapshot, options.artifacts)
            BrowserFactory.save_state(context, ctx, options.profile_dir or ctx.local_profile_dir)
            if options.profile_dir is None or options.profile_dir == ctx.local_profile_dir:
                BrowserFactory.cleanup_runtime_artifacts(ctx.local_profile_dir)
            save_auth_info(
                ctx,
                authenticated=True,
                last_successful_runtime=ctx.runtime_id,
                last_failure_reason=None,
                last_validation=datetime.now().isoformat(),
            )
            return {
                "ok": True,
                "question": question,
                "answer": answer,
                "source": "OpenEvidence",
                "runtime_id": ctx.runtime_id,
                "mode": options.mode,
                "artifacts": artifacts,
            }

        diagnostics_dir = write_failure_bundle(
            ctx,
            classify_timeout(snapshot),
            snapshot=snapshot,
            page=page,
            extra={"question": question, "mode": options.mode},
        )
        save_auth_info(
            ctx,
            authenticated=False if snapshot.get("login_visible") else True,
            last_failure_reason=classify_timeout(snapshot),
            last_validation=datetime.now().isoformat(),
        )
        return {
            "ok": False,
            "question": question,
            "error": _timeout_error_message(snapshot),
            "diagnostics_dir": str(diagnostics_dir),
        }
    except Exception as exc:  # noqa: BLE001
        snapshot: dict[str, object] = {}
        if page is not None:
            try:
                snapshot = collect_response_snapshot(page)
            except Exception:  # noqa: BLE001
                snapshot = {"url": getattr(page, "url", None)}
        diagnostics_dir = write_failure_bundle(
            ctx,
            "unexpected-error",
            snapshot=snapshot,
            page=page,
            extra={"question": question, "mode": options.mode, "error": str(exc)},
        )
        save_auth_info(
            ctx,
            authenticated=False,
            last_failure_reason="unexpected-error",
            last_validation=datetime.now().isoformat(),
        )
        return {
            "ok": False,
            "question": question,
            "error": f"OpenEvidence query failed unexpectedly: {exc}",
            "diagnostics_dir": str(diagnostics_dir),
        }
    finally:
        if context:
            context.close()
        if playwright:
            playwright.stop()


def run_query_with_retries(ctx: RuntimeContext, question: str, options: QueryOptions) -> dict[str, object]:
    modes = [options.mode]
    if options.mode == "reliable":
        modes = ["turbo", "fast", "normal"]

    last_result: dict[str, object] | None = None
    best_success: dict[str, object] | None = None
    for mode in modes:
        attempt_options = QueryOptions(
            mode=mode,
            output_format=options.output_format,
            show_browser=options.show_browser,
            debug=options.debug,
            profile_dir=options.profile_dir,
            artifacts=options.artifacts,
            render=options.render,
        )
        last_result = run_single_query(ctx, question, attempt_options)
        if last_result.get("ok"):
            if best_success is None or result_quality_key(last_result) > result_quality_key(best_success):
                best_success = last_result
            if options.mode != "reliable" or result_confident_enough(last_result):
                return last_result
    return best_success or last_result or {"ok": False, "question": question, "error": "Unknown query failure."}


__all__ = [
    "QueryOptions",
    "answer_quality",
    "sanitize_answer_text",
    "response_ready_to_return",
    "run_query_with_retries",
    "run_single_query",
    "format_text_result",
    "format_chatwise_result",
]
