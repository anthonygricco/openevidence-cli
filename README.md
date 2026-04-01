# OpenEvidence CLI

A Python wrapper around OpenEvidence browser automation for evidence-backed medical answers.

## Status

The current code path uses thin wrapper scripts in `scripts/` and the shared implementation in `tools/openevidence_skill/`.

This repo supports:

- Apple-sign-in authentication management
- `turbo`, `fast`, and `reliable` query modes
- text or JSON output
- parallel multi-question querying
- shared auth state across runtimes with runtime-local browser profiles
- browser launch smoke testing

## Requirements

- Python 3.10+
- `patchright`
- An OpenEvidence account

## Installation

```bash
git clone https://github.com/anthonygricco/openevidence-cli.git
cd openevidence-cli
python3 -m pip install -r requirements.txt
```

## Quick Start

Authenticate once:

```bash
python3 scripts/run.py auth_manager.py setup
```

Check auth:

```bash
python3 scripts/run.py auth_manager.py status
python3 scripts/run.py auth_manager.py validate
```

Ask a question:

```bash
python3 scripts/run.py ask_question.py \
  --question "What is the evidence for adjuvant osimertinib in EGFR-mutated NSCLC?" \
  --reliable \
  --format text
```

Run multiple questions:

```bash
python3 scripts/parallel_ask.py \
  --file questions.txt \
  --max-parallel 3 \
  --reliable
```

Run a browser smoke test:

```bash
python3 scripts/run.py browser_launch_smoke_test.py
```

## Supported Commands

Authentication:

```bash
python3 scripts/run.py auth_manager.py setup
python3 scripts/run.py auth_manager.py status
python3 scripts/run.py auth_manager.py validate
python3 scripts/run.py auth_manager.py reauth
python3 scripts/run.py auth_manager.py clear
python3 scripts/run.py auth_manager.py import-helium
```

Queries:

```bash
python3 scripts/run.py ask_question.py --question "..." --reliable --format text
python3 scripts/run.py ask_question.py --question "..." --turbo --format json
python3 scripts/run.py ask_question.py --question "..." --fast --show-browser
python3 scripts/run.py ask_question.py --batch questions.txt --reliable --format json
python3 scripts/parallel_ask.py --file questions.txt --max-parallel 3 --reliable
```

Supported query flags:

- `--question`
- `--batch`
- `--turbo`
- `--fast`
- `--reliable`
- `--show-browser`
- `--debug`
- `--format json|text`

Deprecated legacy flags such as `--api`, `--progressive`, `--no-cache`, `--cache-ttl`, `--save-images`, and `--timeout` are no longer supported.

## Shared State

The skill uses a shared state root:

- Shared auth and shared venv: `~/.local/share/openevidence-skill/`
- Runtime-local browser profiles: `~/.local/state/openevidence-skill/profiles/<runtime>/`

That means you authenticate once and reuse the saved session across supported runtimes while avoiding profile lock conflicts.

## Repository Layout

```text
openevidence-cli/
├── scripts/
│   ├── run.py
│   ├── ask_question.py
│   ├── auth_manager.py
│   ├── parallel_ask.py
│   └── browser_launch_smoke_test.py
├── tools/openevidence_skill/
│   ├── cli.py
│   ├── query.py
│   ├── auth.py
│   ├── browser.py
│   ├── extract.py
│   └── tests/
├── SKILL.md
├── requirements.txt
└── README.md
```

## Testing

```bash
PYTHONPATH=$PWD python3 -m unittest discover -s tools/openevidence_skill/tests -p 'test_*.py'
```

## Notes

- Successful text output is intended to be presented verbatim.
- The current response logic waits for a more complete/stable answer before returning, which reduces mid-stream truncation.
- Browser state and auth files are intentionally not tracked by git.

## License

MIT License. See [LICENSE](LICENSE).
