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
python3 ~/.claude/skills/openevidence/scripts/run.py auth_manager.py setup
```

A browser window opens. Click "Sign in with Apple" and complete login. Session is saved for future use.

### Ask a Question

```bash
python3 ~/.claude/skills/openevidence/scripts/run.py ask_question.py \
  --question "What is the evidence for adjuvant osimertinib in EGFR-mutated NSCLC?" --turbo
```

**Use `--turbo` flag** for fastest queries (~3-5 seconds). Use `--fast` for a balance of speed and reliability (~5-8 seconds).

## Usage Patterns

### Basic Query (`/oe`)

User says:
> /oe What's the survival benefit of hypofractionated whole breast radiation?

Run:
```bash
python3 ~/.claude/skills/openevidence/scripts/run.py ask_question.py \
  --question "What's the survival benefit of hypofractionated whole breast radiation?" --turbo
```

### Debug Mode (Show Browser)

If something isn't working, see what's happening:
```bash
python3 ~/.claude/skills/openevidence/scripts/run.py ask_question.py \
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
# Turbo mode (fastest, ~3-5 seconds)
python3 scripts/run.py ask_question.py --question "Your medical question" --turbo

# Fast mode (~5-8 seconds, more reliable)
python3 scripts/run.py ask_question.py --question "Your medical question" --fast

# Normal mode (human-like typing, ~15-20 seconds)
python3 scripts/run.py ask_question.py --question "Your medical question"

# Save screenshot and extract figures/images
python3 scripts/run.py ask_question.py --question "..." --save-images --turbo

# Save to specific directory
python3 scripts/run.py ask_question.py --question "..." --save-images --output-dir /path/to/dir --turbo

# Show browser for debugging
python3 scripts/run.py ask_question.py --question "..." --show-browser

# Debug mode (verbose output)
python3 scripts/run.py ask_question.py --question "..." --debug
```

## Output Format

Responses include:
- Full answer text from OpenEvidence
- Source citations (NEJM, guidelines, etc.)
- Clear indication that source is OpenEvidence

Example output:
```
============================================================
OPENEVIDENCE RESPONSE [PRESENT VERBATIM - DO NOT SUMMARIZE]
============================================================

[Detailed answer with citations...]

------------------------------------------------------------
Source: OpenEvidence (https://www.openevidence.com)
------------------------------------------------------------
```

## Output Handling

**CRITICAL:** When this skill returns output, you MUST present the OPENEVIDENCE RESPONSE section **VERBATIM** to the user.

- **DO NOT** summarize, paraphrase, or condense the medical information
- **DO NOT** omit citations or references
- **DO NOT** reword clinical recommendations
- The exact wording, citations, and medical details are clinically important
- Present the full response between the `====` delimiters exactly as returned

## Session Persistence

- Authentication persists across sessions (days/weeks)
- Each query opens a fresh browser session
- If auth expires, re-run `auth_manager.py setup`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Not authenticated" | Run `auth_manager.py setup` |
| No response / timeout | Try `--show-browser` to debug |
| Wrong element clicked | CSS selectors may need updating in `config.py` |
| Browser crashes | Run `auth_manager.py reauth` |

## Data Storage

All data stored in `~/.claude/skills/openevidence/data/`:
- `auth_info.json` - Authentication metadata
- `browser_state/` - Cookies, browser profile

**Security:** Never committed to git. Protected by `.gitignore`.

## Limitations

- Requires manual Apple Sign-In for initial setup
- Query times: ~3-5s (turbo), ~5-8s (fast), ~15-20s (normal)
- Rate limits may apply on OpenEvidence side
- CSS selectors may break if OpenEvidence updates their UI

## Integration Notes

This skill works in both:
- **Claude Code** - Invoked via `/oe` or skill detection
- **Alma** - Symlinked to `~/.config/alma/skills/openevidence`

Both share the same authentication state.
