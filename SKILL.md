---
name: openevidence
description: Query OpenEvidence for HIPAA-compliant, guideline-backed medical answers. Use when user types /oe or asks for clinical evidence from journals like NEJM, guidelines, or authoritative medical sources.
triggers:
  - /oe
  - openevidence
  - "check the evidence"
  - "what does OE say"
  - "evidence for"
---

# OpenEvidence Skill

Query OpenEvidence (https://www.openevidence.com) for evidence-based medical answers with citations from NEJM, NCCN guidelines, and other authoritative sources.

## When to Use

- User types `/oe` followed by a question
- User explicitly mentions "OpenEvidence"
- User asks for clinical evidence, guideline recommendations
- Medical questions requiring authoritative, cited answers

## Quick Start

### First-Time Setup (One-Time)

```bash
# Authenticate via Apple Sign-In
python3 ~/.openclaw/skills/openevidence/scripts/run.py auth_manager.py setup
```

A browser window opens. Click "Sign in with Apple" and complete login. Session is saved for future use.

### Ask a Question

```bash
python3 ~/.openclaw/skills/openevidence/scripts/run.py ask_question.py \
  --question "What is the evidence for adjuvant osimertinib in EGFR-mutated NSCLC?" --turbo
```

**Use `--turbo` flag** for fastest queries. Use `--fast` for a balance of speed and reliability.

## Usage Patterns

### Basic Query (`/oe`)

User says:
> /oe What's the survival benefit of hypofractionated whole breast radiation?

Run:
```bash
python3 ~/.openclaw/skills/openevidence/scripts/run.py ask_question.py \
  --question "What's the survival benefit of hypofractionated whole breast radiation?" --turbo
```

### Progressive Output (for Telegram/Chat Integration)

For faster time-to-answer in chat contexts, use `--progressive` to get partial results:
```bash
python3 ~/.openclaw/skills/openevidence/scripts/run.py ask_question.py \
  --question "..." --turbo --progressive
```

Output uses `[PARTIAL]...[/PARTIAL]` and `[FINAL]...[/FINAL]` delimiters. First partial appears at ~8-10s, with updates every ~15s.

### Direct API Mode (Fastest)

After a browser run captures the API template, bypass the browser entirely:
```bash
python3 ~/.openclaw/skills/openevidence/scripts/run.py ask_question.py \
  --question "..." --api
```

Falls back to browser mode automatically if API auth fails.

### Batch Mode

Process multiple questions from a file:
```bash
python3 ~/.openclaw/skills/openevidence/scripts/run.py ask_question.py \
  --batch questions.txt --turbo --format json
```

File format: one question per line, `#` comments supported.

### Debug Mode (Show Browser)

If something isn't working, see what's happening:
```bash
python3 ~/.openclaw/skills/openevidence/scripts/run.py ask_question.py \
  --question "..." --show-browser
```

## Commands Reference

### Authentication

```bash
# Initial setup (opens browser for Apple Sign-In)
python3 scripts/run.py auth_manager.py setup

# Check authentication status
python3 scripts/run.py auth_manager.py status

# Re-authenticate (clears old session, starts fresh)
python3 scripts/run.py auth_manager.py reauth

# Clear all authentication data
python3 scripts/run.py auth_manager.py clear

# Validate saved auth works
python3 scripts/run.py auth_manager.py validate
```

### Querying

```bash
# Turbo mode (fastest browser, ~3-5s overhead + OE generation)
python3 scripts/run.py ask_question.py --question "..." --turbo

# Direct API mode (no browser, ~1s overhead + OE generation)
python3 scripts/run.py ask_question.py --question "..." --api

# Progressive output (partial results every ~15s)
python3 scripts/run.py ask_question.py --question "..." --turbo --progressive

# Fast mode (~5-8s, more reliable)
python3 scripts/run.py ask_question.py --question "..." --fast

# Normal mode (human-like typing, ~15-20s)
python3 scripts/run.py ask_question.py --question "..."

# Output formats
python3 scripts/run.py ask_question.py --question "..." --format json
python3 scripts/run.py ask_question.py --question "..." --format markdown

# Custom timeout (default 120s)
python3 scripts/run.py ask_question.py --question "..." --timeout 180

# Bypass cache
python3 scripts/run.py ask_question.py --question "..." --no-cache

# Batch mode
python3 scripts/run.py ask_question.py --batch questions.txt --turbo

# Save screenshot and extract figures/images
python3 scripts/run.py ask_question.py --question "..." --save-images --turbo

# Benchmark mode (print performance metrics)
python3 scripts/run.py ask_question.py --question "..." --turbo --benchmark
```

## Speed Modes

| Mode | Flag | Overhead | Best For |
|------|------|----------|----------|
| API | `--api` | ~1s | Fastest, no browser needed |
| Turbo | `--turbo` | ~3-5s | Fast browser with API capture |
| Fast | `--fast` | ~5-8s | Reliable browser mode |
| Normal | (none) | ~15-20s | Human-like stealth |

**Note:** OE server generation takes 45-60s regardless of mode. Use `--progressive` to see partial results while waiting.

## Output Formats

| Format | Flag | Description |
|--------|------|-------------|
| Text | `--format text` | Default: delimited sections with source attribution |
| JSON | `--format json` | Structured: `{question, answer, citations, cached, timing}` |
| Markdown | `--format markdown` | Clean document with heading and footer |

## Output Handling

**CRITICAL:** When this skill returns output, you MUST present the OPENEVIDENCE RESPONSE section **VERBATIM** to the user.

- **DO NOT** summarize, paraphrase, or condense the medical information
- **DO NOT** omit citations or references
- **DO NOT** reword clinical recommendations
- The exact wording, citations, and medical details are clinically important
- Present the full response between the `====` delimiters exactly as returned

## Caching

Responses are cached by question (SHA256, case-insensitive) with 24h TTL.

- Cached queries return in <0.5s
- `--no-cache` bypasses the cache
- `--cache-ttl N` sets custom TTL in seconds
- Cache stored in `data/cache/`

## Session Persistence

- Authentication persists across sessions (days/weeks)
- Each query opens a fresh browser session
- If auth expires, re-run `auth_manager.py setup`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Not authenticated" | Run `auth_manager.py setup` |
| No response / timeout | Try `--show-browser` to debug, or `--timeout 180` |
| API mode fails | Run a browser query first to capture API template |
| Wrong element clicked | CSS selectors may need updating in `config.py` |
| Browser crashes | Run `auth_manager.py reauth` |

## Data Storage

All data stored in `~/.openclaw/skills/openevidence/data/`:
- `auth_info.json` - Authentication metadata
- `browser_state/` - Cookies, browser profile
- `cache/` - Cached responses (24h TTL)
- `api_template.json` - Captured API request format

**Security:** Never committed to git. Protected by `.gitignore`.

## Limitations

- Requires manual Apple Sign-In for initial setup
- OE server generation takes 45-60s for complete answers (use `--progressive` for early results)
- Rate limits may apply on OpenEvidence side
- CSS selectors may break if OpenEvidence updates their UI
- API mode requires a prior browser run to capture the request template

## Integration Notes

This skill works in both:
- **Claude Code** - Invoked via `/oe` or skill detection
- **Alma** - Symlinked to `~/.config/alma/skills/openevidence`

Both share the same authentication state.
