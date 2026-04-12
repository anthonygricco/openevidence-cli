# OpenEvidence CLI

A Python wrapper around OpenEvidence browser automation for evidence-backed medical answers — with automatic capture of answer screenshots and inline figures (NCCN flowcharts, Kaplan-Meier curves, trial figures).

## Status

The current code path uses thin wrapper scripts in `scripts/` and the shared implementation in `tools/openevidence_skill_v2/`.

This repo supports:

- Apple-sign-in authentication management
- `turbo`, `fast`, and `reliable` query modes
- `text`, `json`, and `chatwise` output formats
- automatic capture of the final answer screenshot and inline figures (default on)
- optional full-page screenshot capture
- embedded data-URI artifacts for `chatwise` markdown output
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

The answer text prints to stdout. Captured figure PNGs and the answer screenshot are written under `~/.local/share/openevidence-skill/artifacts/` by default, and the text output includes an `IMAGE ARTIFACTS` block plus an `ACTION REQUIRED` line with an `open` command that launches an HTML gallery of the captured figures.

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
python3 scripts/run.py ask_question.py --question "..." --reliable --format chatwise --embed-artifacts
python3 scripts/run.py ask_question.py --batch questions.txt --reliable --format json
python3 scripts/parallel_ask.py --file questions.txt --max-parallel 3 --reliable
```

### Query flags

Core:

- `--question` — single question string
- `--batch` — path to a file of questions, one per line
- `--turbo` / `--fast` / `--reliable` — query mode (reliable recommended)
- `--show-browser` — run headed
- `--debug` — verbose diagnostics
- `--format json|text|chatwise` — output format

Artifact capture:

- `--save-inline-images` / `--no-save-inline-images` — save rendered inline figures from the final answer (default: on)
- `--save-answer-screenshot` / `--no-save-answer-screenshot` — save a cropped screenshot of the answer card (default: on)
- `--save-page-screenshot` — save a full-page screenshot after the answer stabilizes
- `--artifact-dir PATH` — override the artifact output directory
- `--save-images` and `--output-dir` are accepted as aliases for `--save-inline-images` and `--artifact-dir`

Chatwise embedding:

- `--embed-artifacts` — embed small artifact PNGs as data URIs when using `--format chatwise`
- `--max-embed-bytes N` — maximum PNG size eligible for embedding (default: 1,000,000)

## Shared State

The skill uses a shared state root:

- Shared auth and shared venv: `~/.local/share/openevidence-skill/`
- Captured artifacts: `~/.local/share/openevidence-skill/artifacts/`
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
├── tools/openevidence_skill_v2/
│   ├── cli.py
│   ├── query.py
│   ├── auth.py
│   ├── browser.py
│   ├── extract.py
│   ├── artifacts.py
│   ├── render.py
│   └── tests/
├── SKILL.md
├── CHANGELOG.md
├── requirements.txt
└── README.md
```

## Testing

```bash
PYTHONPATH=$PWD python3 -m unittest discover -s tools/openevidence_skill_v2/tests -p 'test_*.py'
```

## Notes

- Successful text output is intended to be presented verbatim.
- The response logic waits for a more complete/stable answer before returning, which reduces mid-stream truncation.
- Inline figure capture runs after answer stabilization and does not block the text output.
- Browser state and auth files are intentionally not tracked by git.

## License

MIT License. See [LICENSE](LICENSE).
