# OpenEvidence CLI

A Python CLI tool to query [OpenEvidence](https://www.openevidence.com) for evidence-based medical answers with citations from authoritative sources like NEJM, NCCN guidelines, and peer-reviewed literature.

## Features

- **Evidence-based answers**: Get medical information backed by citations from authoritative sources
- **Session persistence**: Authenticate once, query many times
- **Multiple speed modes**: Normal (stealth), Fast, and Turbo modes
- **Image extraction**: Save screenshots and figures from responses
- **Headless operation**: Run without visible browser window

## Requirements

- Python 3.10+
- macOS or Linux (Windows untested)
- OpenEvidence account (free, requires Apple Sign-In)

## Installation

```bash
# Clone the repository
git clone https://github.com/anthonygricco/openevidence-cli.git
cd openevidence-cli

# The tool auto-creates a virtual environment on first run
python3 scripts/run.py --help
```

## Quick Start

### 1. Authenticate (one-time setup)

```bash
python3 scripts/run.py auth_manager.py setup
```

A browser window opens. Sign in with Apple and complete the login. Your session is saved for future use.

### 2. Ask a question

```bash
# Fast mode (recommended)
python3 scripts/run.py ask_question.py \
  --question "What is the evidence for adjuvant osimertinib in EGFR-mutated NSCLC?" \
  --fast

# Turbo mode (maximum speed)
python3 scripts/run.py ask_question.py \
  --question "Your question here" \
  --turbo
```

## Usage

### Authentication Commands

```bash
# Initial setup (opens browser)
python3 scripts/run.py auth_manager.py setup

# Check status
python3 scripts/run.py auth_manager.py status

# Re-authenticate
python3 scripts/run.py auth_manager.py reauth

# Clear saved auth
python3 scripts/run.py auth_manager.py clear

# Validate saved auth works
python3 scripts/run.py auth_manager.py validate
```

### Query Commands

```bash
# Basic query (normal mode - human-like typing)
python3 scripts/run.py ask_question.py --question "Your medical question"

# Fast mode (~5-8 seconds)
python3 scripts/run.py ask_question.py --question "..." --fast

# Turbo mode (~3-5 seconds, may be less reliable)
python3 scripts/run.py ask_question.py --question "..." --turbo

# Save screenshot and images
python3 scripts/run.py ask_question.py --question "..." --save-images --fast

# Debug mode (show browser)
python3 scripts/run.py ask_question.py --question "..." --show-browser
```

### Speed Modes

| Mode | Flag | Response Time | Reliability |
|------|------|---------------|-------------|
| Normal | (default) | ~15-20s | Highest |
| Fast | `--fast` | ~5-8s | High |
| Turbo | `--turbo` | ~3-5s | Good |

## Example Output

```
[FAST] Asking: What is the evidence for adjuvant osimertinib in EGFR-mutated NSCLC?
  Opening OpenEvidence...
  Looking for chat input...
  Found input: textarea[placeholder*="Ask"]
  Entering question (fast)...
  Submitting...
  Waiting for response...
  Got response (4521 chars)

============================================================
OPENEVIDENCE RESPONSE
============================================================

The ADAURA trial (Wu et al., NEJM 2020) demonstrated that adjuvant
osimertinib significantly improved disease-free survival in patients
with stage IB-IIIA EGFR-mutated NSCLC after complete tumor resection...

[Full response with citations]

------------------------------------------------------------
Source: OpenEvidence (https://www.openevidence.com)
------------------------------------------------------------
```

## Project Structure

```
openevidence/
├── scripts/
│   ├── run.py           # Entry point, handles venv setup
│   ├── auth_manager.py  # Authentication management
│   ├── ask_question.py  # Query interface
│   ├── browser_utils.py # Browser automation utilities
│   └── config.py        # Configuration and selectors
├── data/                # Auth data (gitignored)
├── requirements.txt
├── SKILL.md            # Claude Code skill documentation
└── README.md
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Not authenticated" | Run `auth_manager.py setup` |
| No response / timeout | Try `--show-browser` to debug |
| Browser crashes | Run `auth_manager.py reauth` |
| Slow responses | Use `--fast` or `--turbo` flag |

## Security Notes

- Authentication data is stored locally in `data/` (gitignored)
- Never commit your `data/` directory
- Session cookies may expire after days/weeks - re-run setup if needed

## Limitations

- Requires manual Apple Sign-In for initial authentication
- CSS selectors may break if OpenEvidence updates their UI
- Rate limits may apply on OpenEvidence side

## License

MIT License - see [LICENSE](LICENSE)

## Disclaimer

This tool is for educational and research purposes. Always verify medical information with qualified healthcare professionals. The authors are not responsible for any medical decisions made based on information obtained through this tool.
