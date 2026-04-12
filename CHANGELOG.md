# Changelog

All notable changes to the OpenEvidence CLI skill.

## [v2.1.0] - 2026-04-12

### Features
- **Automatic artifact capture**: `ask_question.py` now saves the final answer screenshot and rendered inline figures (NCCN flowcharts, Kaplan-Meier curves, trial figures) by default. No flags required.
- **HTML gallery rendering**: captured figures are written alongside an `index.html` gallery. Text output ends with an `ACTION REQUIRED` block containing an `open` command to launch the gallery in the browser.
- **`chatwise` output format** (`--format chatwise`): markdown output tailored for ChatWise clients, with references and artifact links inlined.
- **Artifact embedding** (`--embed-artifacts`, `--max-embed-bytes`): inline small artifact PNGs as data URIs directly in `chatwise` markdown.
- **Full-page screenshot** (`--save-page-screenshot`): optional full-page capture after answer stabilization.

### Flags
- New: `--save-inline-images` / `--no-save-inline-images` (default on), `--save-answer-screenshot` / `--no-save-answer-screenshot` (default on), `--save-page-screenshot`, `--artifact-dir`, `--embed-artifacts`, `--max-embed-bytes`
- Re-enabled as aliases: `--save-images` (→ `--save-inline-images`), `--output-dir` (→ `--artifact-dir`). These were deprecated in v2.0.0 and are back as ergonomic aliases for the new artifact pipeline.

### Structure
- Renamed `tools/openevidence_skill/` → `tools/openevidence_skill_v2/` to reflect the artifact-capture upgrade. Wrapper scripts in `scripts/` now import from the v2 package.
- New modules: `tools/openevidence_skill_v2/artifacts.py` (capture pipeline) and `tools/openevidence_skill_v2/render.py` (gallery and chatwise rendering).

### Docs
- SKILL.md rewritten around the new default (`--reliable --format text` with automatic screenshot/figure capture) and the `ACTION REQUIRED` contract for opening the gallery.
- README updated with the new flags, `chatwise` format, and artifact output locations.

### Upgrading from v2.0.0
- No code changes required for the common call site — `ask_question.py --question ... --reliable --format text` still works and now also produces artifacts.
- If you depend on the import path, update `from tools.openevidence_skill` → `from tools.openevidence_skill_v2`.
- If you run the test suite, the discover path is now `tools/openevidence_skill_v2/tests`.

---

## [v2.0.0] - 2026-03-15

### Reliability
- **`--reliable` mode** (new recommended default): auto-retry with escalating strategies (turbo → fast → normal), up to 3 attempts with backoff
- **Pre-flight health check**: HEAD request to openevidence.com before launching browser — fails fast when site is unreachable
- **Cookie auth validation**: verifies session cookies are still valid before browser launch
- **Stale lock cleanup**: detects and removes Chromium lock files from crashed previous runs
- **Tightened turbo stability**: stable_checks 2→3, min_wait_after_submit 2→3s
- **Stronger completion detection**: References section with author names as primary signal
- Response quality gate: rejects answers <200 chars or missing citations

### Features
- **Parallel query runner** (`parallel_ask.py`): run 2+ queries simultaneously, each in own browser, wall-clock time ≈ one query
- **HIPAA popup handling**: auto-dismisses "I am a healthcare professional" verification dialog

### Fixes
- **API mode response extraction**: now checks `output`/`partial_output` fields (OE's actual response fields) instead of guessing
- **API mode question nesting**: fixed `body.inputs.question` path (was setting top-level field)

---

## [Cycle 15] - 2026-03-15
- Updated SKILL.md with full documentation for all new features
- Created CHANGELOG.md covering all 15 improvement cycles
- Final benchmark and polish

## [Cycle 14] - 2026-03-15
- Added `--timeout` flag (default 120s) to override response wait time
- Timeout wired through browser mode, API mode, and batch processing
- Removed hardcoded QUERY_TIMEOUT dependency

## [Cycle 13] - 2026-03-15
- Added `--batch file.txt` for processing multiple questions from a file
- One question per line, `#` comments supported
- Batch works with `--api` mode and `--format json`
- `--question` now optional when `--batch` is provided

## [Cycle 12] - 2026-03-15
- Added `--format` flag: `text` (default), `json`, `markdown`
- JSON: structured `{question, answer, citations, cached, timing, source}`
- Markdown: clean document with heading, question, answer, and source footer

## [Cycle 11] - 2026-03-15
- Verified response caching implementation (from cycle 9)
- Cache roundtrip, TTL expiry, and case-insensitive keys validated
- No code changes needed

## [Cycle 10] - 2026-03-15
- Added `--api` flag for direct HTTP API calls (no browser launch)
- Browser mode now captures API request template (`api_template.json`)
- API mode extracts cookies from `state.json`, POSTs to `/api/article`, polls for response
- Falls back to browser mode if API auth fails or template is missing
- Supports progressive output in API mode

## [Cycle 9] - 2026-03-15
- Added `--progressive` flag for `[PARTIAL]`/`[FINAL]` delimited output
- First partial emits at ~8s with 200+ chars, subsequent every ~15s if 300+ new chars
- Enables Telegram/chat callers to show early partial results
- Implemented response caching: SHA256 key, 24h TTL, `--no-cache`, `--cache-ttl`
- Cached responses return in <0.5s

## [Cycle 8] - 2026-02-25
- Direct API exploration and article tracking
- Discovered OE uses `/api/article` endpoints (POST → create, GET → poll)
- Added API response interception to detect completion signals
- 97% of latency is OE server generation time (~55-60s), overhead ~1.5s

## [Cycle 7] - 2026-02-25
- API interception and smarter streaming detection
- `on_response` handler monitors `/api/article` for completion
- `is_response_streaming()` JS check for active generation

## [Cycle 6] - 2026-02-25
- Timing instrumentation and turbo mode optimization
- Phase-level timing breakdown (browser_launch, page_load, input, submit, response_wait)
- Turbo mode: 50-100ms delays, 0.3s polling, 2s minimum wait

## [Cycle 5] - 2026-02-25
- Polish, `--benchmark` flag, documentation updates
- Benchmark output: mode, latency, char count, citations, completeness, phase breakdown

## [Cycle 4] - 2026-02-25
- Retry and error recovery
- Auto-retry if response is short/incomplete (<1000 chars)
- Final extraction attempt with lower threshold on failure

## [Cycle 3] - 2026-02-25
- JS-based selectors and streaming detection
- Faster `is_loading()` via JavaScript evaluation
- `get_response_text()` uses JS `innerText` extraction from `<article>`

## [Cycle 2] - 2026-02-25
- Speed up browser launch and input
- Fast/turbo modes with `page.fill()` instead of human typing
- Reduced delays in fast mode

## [Cycle 1] - 2026-02-25
- Fix response extraction
- Multiple selector fallbacks for response area
- Clean response text from UI noise patterns
