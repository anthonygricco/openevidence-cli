from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .auth import clear_auth, import_auth_from_helium, perform_setup, print_status, validate_auth
from .bootstrap import maybe_reexec_into_shared_venv, run_script_from_wrapper
from .browser import BrowserFactory, load_playwright
from .config import RuntimeContext, build_runtime_context
from .parallel import run_parallel_queries
from .query import QueryOptions, format_text_result, run_query_with_retries


DEPRECATED_FLAG_MESSAGES = {
    "api": "--api is deprecated and no longer supported. OpenEvidence runs through browser automation only.",
    "progressive": "--progressive is deprecated and no longer supported.",
    "no_cache": "--no-cache is deprecated and no longer supported.",
    "cache_ttl": "--cache-ttl is deprecated and no longer supported.",
    "timeout": "--timeout is deprecated and no longer supported.",
    "benchmark": "--benchmark is deprecated and no longer supported.",
    "save_images": "--save-images is deprecated and no longer supported.",
    "output_dir": "--output-dir is deprecated and no longer supported.",
    "new_chat": "--new-chat is deprecated and no longer supported.",
}


def _ctx(script_file: str) -> RuntimeContext:
    return build_runtime_context(script_file)


def _handle_deprecated_query_flags(args: argparse.Namespace) -> int | None:
    for field_name, message in DEPRECATED_FLAG_MESSAGES.items():
        if getattr(args, field_name, None) not in (None, False):
            print(message, file=sys.stderr)
            return 2
    return None


def _print_result(result: dict[str, object], output_format: str) -> int:
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(format_text_result(result))
    return 0 if result.get("ok") else 1


def main_run(script_file: str, argv: list[str]) -> int:
    ctx = _ctx(script_file)
    if not argv:
        print("Usage: python run.py <script.py> [args...]")
        print()
        print("Available scripts:")
        for name in (
            "auth_manager.py",
            "ask_question.py",
            "parallel_ask.py",
            "browser_launch_smoke_test.py",
        ):
            print(f"  - {name}")
        return 1
    return run_script_from_wrapper(ctx, argv[0], argv[1:])


def main_auth_manager(script_file: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Manage OpenEvidence authentication")
    subparsers = parser.add_subparsers(dest="command")
    for name in ("setup", "status", "validate", "reauth", "clear", "import-helium"):
        subparsers.add_parser(name)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    ctx = _ctx(script_file)
    if args.command == "status":
        return print_status(ctx)
    if args.command == "clear":
        return clear_auth(ctx)
    if args.command == "setup":
        reexec = maybe_reexec_into_shared_venv(ctx, script_file, argv)
        if reexec is not None:
            return reexec
        return perform_setup(ctx)
    if args.command == "reauth":
        clear_auth(ctx)
        reexec = maybe_reexec_into_shared_venv(ctx, script_file, ["setup"])
        if reexec is not None:
            return reexec
        return perform_setup(ctx)
    if args.command == "validate":
        reexec = maybe_reexec_into_shared_venv(ctx, script_file, argv)
        if reexec is not None:
            return reexec
        ok = validate_auth(ctx)
        print("Authentication valid!" if ok else "Authentication invalid.")
        return 0 if ok else 1
    if args.command == "import-helium":
        reexec = maybe_reexec_into_shared_venv(ctx, script_file, argv)
        if reexec is not None:
            return reexec
        return import_auth_from_helium(ctx)
    return 1


def main_ask_question(script_file: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Ask OpenEvidence a question")
    parser.add_argument("--question", "-q", help="The medical question to ask")
    parser.add_argument("--batch", help="Text file containing one question per line")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--turbo", action="store_true", help="Fastest browser path")
    mode_group.add_argument("--fast", action="store_true", help="Conservative fast browser path")
    mode_group.add_argument("--reliable", action="store_true", help="Retry turbo -> fast -> normal until one succeeds")
    parser.add_argument("--show-browser", action="store_true", help="Show the browser window for debugging")
    parser.add_argument("--debug", action="store_true", help="Verbose debug logging")
    parser.add_argument("--format", choices=("json", "text"), default="json", help="Output format")

    parser.add_argument("--api", action="store_true", dest="api", help=argparse.SUPPRESS)
    parser.add_argument("--progressive", action="store_true", dest="progressive", help=argparse.SUPPRESS)
    parser.add_argument("--no-cache", action="store_true", dest="no_cache", help=argparse.SUPPRESS)
    parser.add_argument("--cache-ttl", type=int, dest="cache_ttl", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=int, dest="timeout", help=argparse.SUPPRESS)
    parser.add_argument("--benchmark", action="store_true", dest="benchmark", help=argparse.SUPPRESS)
    parser.add_argument("--save-images", action="store_true", dest="save_images", help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", dest="output_dir", help=argparse.SUPPRESS)
    parser.add_argument("--new-chat", action="store_true", dest="new_chat", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    deprecated = _handle_deprecated_query_flags(args)
    if deprecated is not None:
        return deprecated

    questions: list[str] = []
    if args.question:
        questions.append(args.question)
    if args.batch:
        batch_path = Path(args.batch)
        if not batch_path.exists():
            print(f"Batch file not found: {batch_path}", file=sys.stderr)
            return 1
        questions.extend(
            line.strip()
            for line in batch_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    if not questions:
        parser.error("one of --question or --batch is required")

    mode = "normal"
    if args.turbo:
        mode = "turbo"
    elif args.fast:
        mode = "fast"
    elif args.reliable:
        mode = "reliable"

    ctx = _ctx(script_file)
    reexec = maybe_reexec_into_shared_venv(ctx, script_file, argv)
    if reexec is not None:
        return reexec

    results = []
    for question in questions:
        result = run_query_with_retries(
            ctx,
            question,
            QueryOptions(
                mode=mode,
                output_format=args.format,
                show_browser=args.show_browser,
                debug=args.debug,
            ),
        )
        results.append(result)

    if len(results) == 1:
        return _print_result(results[0], args.format)

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False))
    else:
        print("\n\n".join(format_text_result(result) for result in results))
    return 0 if all(result.get("ok") for result in results) else 1


def main_parallel_ask(script_file: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run multiple OpenEvidence queries in parallel")
    parser.add_argument("questions", nargs="*", help="Questions to ask")
    parser.add_argument("--file", "-f", help="File with one question per line")
    parser.add_argument("--max-parallel", "-p", type=int, default=3, help="Max parallel queries (default: 3)")
    parser.add_argument("--turbo", action="store_true", help="Use turbo mode")
    parser.add_argument("--fast", action="store_true", help="Use fast mode")
    parser.add_argument("--reliable", action="store_true", help="Use reliable retry mode")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--show-browser", action="store_true")
    args = parser.parse_args(argv)

    questions = list(args.questions)
    if args.file:
        batch_path = Path(args.file)
        if not batch_path.exists():
            print(f"Questions file not found: {batch_path}", file=sys.stderr)
            return 1
        questions.extend(
            line.strip()
            for line in batch_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    if not questions:
        print("No questions provided.", file=sys.stderr)
        return 1

    ctx = _ctx(script_file)
    extra_flags: list[str] = []
    if args.turbo:
        extra_flags.append("--turbo")
    elif args.fast:
        extra_flags.append("--fast")
    elif args.reliable:
        extra_flags.append("--reliable")
    if args.debug:
        extra_flags.append("--debug")
    if args.show_browser:
        extra_flags.append("--show-browser")

    results = run_parallel_queries(ctx, questions, max_parallel=args.max_parallel, extra_flags=extra_flags)
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(result.get("ok") for result in results) else 1


def main_browser_smoke_test(script_file: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="OpenEvidence browser launch smoke test")
    parser.add_argument("--show-browser", action="store_true", help="Show the browser window for debugging")
    args = parser.parse_args(argv)

    ctx = _ctx(script_file)
    reexec = maybe_reexec_into_shared_venv(ctx, script_file, argv)
    if reexec is not None:
        return reexec

    playwright_manager = load_playwright()
    playwright = None
    context = None
    try:
        playwright = playwright_manager().start()
        context = BrowserFactory.launch_persistent_context(playwright, ctx, headless=not args.show_browser)
        page = context.new_page()
        page.goto("about:blank")
        print("OK: browser context launched successfully.")
        return 0
    finally:
        if context:
            context.close()
        if playwright:
            playwright.stop()
