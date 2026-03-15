# OpenEvidence CLI

A Python CLI tool to query [OpenEvidence](https://www.openevidence.com) for evidence-based medical answers with citations from authoritative sources like NEJM, NCCN guidelines, and peer-reviewed literature.

## What's New in v2.0.0

- **`--reliable` mode** — auto-retries with escalating strategies (turbo → fast → normal). Recommended default.
- **Parallel queries** — run multiple questions simultaneously, each in its own browser
- **Response caching** — SHA256-keyed, 24h TTL. Cache hits return in <0.5s
- **Progressive output** — `[PARTIAL]`/`[FINAL]` streaming for chat integrations
- **Direct API mode** — bypass browser entirely using captured cookies
- **Output formats** — text, JSON, or markdown
- **Pre-flight checks** — connectivity health check, auth validation, stale lock cleanup
- **HIPAA popup handling** — auto-dismisses verification dialogs

See [CHANGELOG.md](CHANGELOG.md) for the full history.

## Requirements

- Python 3.10+
- macOS or Linux (Windows untested)
- OpenEvidence account (requires healthcare practitioner verification)

## Installation

### Standalone CLI

```bash
git clone https://github.com/anthonygricco/openevidence-cli.git
cd openevidence-cli

# Auto-creates a virtual environment on first run
python3 scripts/run.py --help
```

### As a Claude Code Skill

```bash
git clone https://github.com/anthonygricco/openevidence-cli.git ~/.claude/skills/openevidence
```

Claude Code auto-detects the `SKILL.md` file. Use `/oe` followed by any medical question.

## Quick Start

### 1. Authenticate (one-time)

```bash
python3 scripts/run.py auth_manager.py setup
```

A browser window opens. Sign in and complete login. Session is saved for future use.

### 2. Ask a question

```bash
# Recommended: reliable mode (auto-retries if needed)
python3 scripts/run.py ask_question.py \
  --question "What is the evidence for adjuvant osimertinib in EGFR-mutated NSCLC?" \
  --reliable

# Fast single query
python3 scripts/run.py ask_question.py \
  --question "SBRT outcomes in early-stage NSCLC?" \
  --turbo

# Multiple questions in parallel
python3 scripts/parallel_ask.py \
  "Role of pembrolizumab in NSCLC?" \
  "Evidence for SBRT in oligometastatic disease?" \
  "Hypofractionation in breast cancer outcomes?"
```

## Usage

### Speed Modes

| Mode | Flag | Overhead | Reliability | Notes |
|------|------|----------|-------------|-------|
| Normal | *(default)* | ~15-20s | Highest | Human-like typing |
| Fast | `--fast` | ~5-8s | High | Fills input directly |
| Turbo | `--turbo` | ~3-5s | Good | Minimal delays |
| Reliable | `--reliable` | ~3-20s | Highest | Starts turbo, escalates on failure |

> **Note:** OE server generation takes ~55-60s regardless of mode. Overhead is local browser time only.

### Query Options

```bash
# Reliable mode (recommended)
python3 scripts/run.py ask_question.py -q "..." --reliable

# With JSON output
python3 scripts/run.py ask_question.py -q "..." --turbo --format json

# Markdown output
python3 scripts/run.py ask_question.py -q "..." --fast --format markdown

# Progressive streaming (for chat integrations)
python3 scripts/run.py ask_question.py -q "..." --turbo --progressive

# Direct API mode (no browser, requires prior browser run to capture template)
python3 scripts/run.py ask_question.py -q "..." --api

# Custom timeout
python3 scripts/run.py ask_question.py -q "..." --timeout 180

# Skip cache
python3 scripts/run.py ask_question.py -q "..." --no-cache

# Performance benchmarking
python3 scripts/run.py ask_question.py -q "..." --turbo --benchmark

# Debug (visible browser)
python3 scripts/run.py ask_question.py -q "..." --show-browser --debug

# Save screenshots and images
python3 scripts/run.py ask_question.py -q "..." --save-images
```

### Parallel Queries

Run 2+ questions simultaneously, each in its own browser instance:

```bash
# From command line arguments
python3 scripts/parallel_ask.py \
  "Question one?" \
  "Question two?" \
  "Question three?"

# From a file (one question per line)
python3 scripts/parallel_ask.py --file questions.txt

# Control concurrency
python3 scripts/parallel_ask.py --max-parallel 5 --file questions.txt
```

Wall-clock time ≈ one query (~60s) instead of N × 60s serial.

### Batch Mode (Serial)

Process questions sequentially from a file:

```bash
python3 scripts/run.py ask_question.py --batch questions.txt --turbo --format json
```

File format: one question per line, `#` for comments.

### Authentication

```bash
python3 scripts/run.py auth_manager.py setup      # Initial setup (opens browser)
python3 scripts/run.py auth_manager.py status      # Check auth status
python3 scripts/run.py auth_manager.py reauth      # Re-authenticate
python3 scripts/run.py auth_manager.py validate    # Validate saved cookies
python3 scripts/run.py auth_manager.py clear       # Clear saved auth
```

### Caching

Responses are cached by default (SHA256 of lowercased question, 24h TTL):

```bash
# Skip cache for fresh results
python3 scripts/run.py ask_question.py -q "..." --no-cache

# Custom TTL (in seconds)
python3 scripts/run.py ask_question.py -q "..." --cache-ttl 3600
```

Cache is stored in `data/cache/`. First hit: ~60s. Cached hit: <0.5s.

## Example Output

```
$ python3 scripts/run.py ask_question.py \
    -q "What is the evidence for proton therapy in pediatric CNS tumors?" \
    --reliable --benchmark

[RELIABLE] Attempt 1/3 (turbo)
[TURBO] Asking: What is the evidence for proton therapy in pediatric CNS tumors?
  Opening OpenEvidence...
  Entering question...
  Waiting for response...
  Got response (6054 chars, 11 citations)

============================================================
OPENEVIDENCE RESPONSE
============================================================

Proton beam therapy (PBT) has emerged as a preferred radiation modality
for many pediatric CNS tumors due to its superior dose conformality
and reduced integral dose to developing normal tissues...

[Full response with 11 citations]

------------------------------------------------------------
Source: OpenEvidence (https://www.openevidence.com)
------------------------------------------------------------

Performance: turbo mode | 49.5s total | 6054 chars | 11 citations | complete
```

## Project Structure

```
openevidence-cli/
├── scripts/
│   ├── run.py              # Entry point, manages venv
│   ├── ask_question.py     # Core query engine (946 lines)
│   ├── parallel_ask.py     # Parallel multi-query runner
│   ├── auth_manager.py     # Authentication management
│   ├── browser_utils.py    # Stealth browser utilities
│   └── config.py           # Selectors, timeouts, modes
├── data/                   # Auth + cache data (gitignored)
│   ├── state.json          # Saved cookies
│   ├── api_template.json   # Captured API request template
│   └── cache/              # Response cache
├── SKILL.md                # Claude Code skill documentation
├── CHANGELOG.md            # Version history
├── requirements.txt
└── README.md
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Not authenticated" | Run `auth_manager.py setup` |
| No response / timeout | Try `--show-browser --debug` to see what's happening |
| Browser won't launch | Stale locks — `--reliable` mode auto-cleans these |
| Slow responses | OE server generation is ~55-60s; local overhead is minimal in turbo |
| HIPAA popup blocking | Auto-handled in v2.0.0; update if on older version |
| Expired cookies | Run `auth_manager.py validate`, then `reauth` if needed |
| API mode returns empty | Known issue — use browser mode (default) instead |

## Security Notes

- Authentication data is stored locally in `data/` (gitignored)
- Never commit your `data/` directory
- Session cookies expire after weeks/months — re-run setup if needed
- Pre-flight auth validation warns early on expired sessions

## Limitations

- Requires manual sign-in for initial authentication
- CSS selectors may break if OpenEvidence updates their UI
- API mode content extraction has known issues (browser mode is reliable)
- Rate limits may apply on OpenEvidence side

## License

MIT License — see [LICENSE](LICENSE)

## Disclaimer

**Account Eligibility:** OpenEvidence accounts are only available to verified healthcare practitioners. You must have a valid OpenEvidence account to use this tool.

**Terms of Service Notice:** This tool uses browser automation to interact with OpenEvidence. This method of access may violate OpenEvidence's Terms of Service. The authors are not affiliated with or endorsed by OpenEvidence. Use at your own risk.

**Medical Disclaimer:** For educational and research purposes only. Always verify medical information with qualified healthcare professionals.
