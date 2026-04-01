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

Use OpenEvidence for evidence-backed medical answers when the user explicitly wants OpenEvidence or a guideline/journal-grounded answer.

## When To Use

- User types `/oe`
- User explicitly asks for OpenEvidence
- User wants clinical evidence, guideline language, or source-backed medical synthesis

## Command Rule

Always use the wrapper:

```bash
python3 <SKILL_DIR>/scripts/run.py auth_manager.py status
python3 <SKILL_DIR>/scripts/run.py ask_question.py --question "..."
```

Replace `<SKILL_DIR>` with the installed OpenEvidence skill directory for the current runtime. Do not hard-code `~/.claude/skills` or `~/.codex/skills`.

## Supported Commands

Authentication:

```bash
python3 <SKILL_DIR>/scripts/run.py auth_manager.py setup
python3 <SKILL_DIR>/scripts/run.py auth_manager.py status
python3 <SKILL_DIR>/scripts/run.py auth_manager.py validate
python3 <SKILL_DIR>/scripts/run.py auth_manager.py reauth
python3 <SKILL_DIR>/scripts/run.py auth_manager.py clear
python3 <SKILL_DIR>/scripts/run.py auth_manager.py import-helium
```

Queries:

```bash
python3 <SKILL_DIR>/scripts/run.py ask_question.py --question "..." --reliable --format text
python3 <SKILL_DIR>/scripts/run.py ask_question.py --question "..." --turbo --format json
python3 <SKILL_DIR>/scripts/run.py ask_question.py --question "..." --fast --show-browser
python3 <SKILL_DIR>/scripts/run.py ask_question.py --batch questions.txt --reliable --format json
python3 <SKILL_DIR>/scripts/parallel_ask.py --file questions.txt --max-parallel 3 --reliable
python3 <SKILL_DIR>/scripts/run.py browser_launch_smoke_test.py
```

## Flags

Supported query flags:

- `--question`
- `--batch`
- `--turbo`
- `--fast`
- `--reliable`
- `--show-browser`
- `--debug`
- `--format json|text`

Unsupported legacy flags such as `--api`, `--progressive`, `--no-cache`, `--cache-ttl`, `--save-images`, and `--timeout` are deprecated and should not be used.

## Recommended Defaults

- Use `--reliable` unless the caller has a strong reason to force one speed mode.
- Use `--format text` when the answer will be shown directly to the user.
- Use `--format json` for programmatic consumers.
- Use `parallel_ask.py` when you need to run multiple OpenEvidence questions in one turn.

## Output Handling

When OpenEvidence returns a successful text response, present the `OPENEVIDENCE RESPONSE` block verbatim.

- Do not summarize the OpenEvidence answer.
- Do not strip citations or clinically relevant wording.
- Do not paraphrase recommendations.

## Shared State

The skill now uses one shared state root across Codex, Claude Code, Alma, and OpenClaw:

- Shared auth and shared venv: `~/.local/share/openevidence-skill/`
- Runtime-local browser profiles: `~/.local/state/openevidence-skill/profiles/<runtime>/`

This means you authenticate once and the saved session is reused across runtimes, while each runtime gets its own local profile to avoid profile lock conflicts.

## Troubleshooting

- If auth looks stale, run `python3 <SKILL_DIR>/scripts/run.py auth_manager.py validate`
- If validation fails, run `python3 <SKILL_DIR>/scripts/run.py auth_manager.py reauth`
- If you are already logged into OpenEvidence in Helium, run `python3 <SKILL_DIR>/scripts/run.py auth_manager.py import-helium`
- If browser launch fails in a sandboxed app, keep the default bundled Chromium and do not force system Chrome
- Use `python3 <SKILL_DIR>/scripts/run.py browser_launch_smoke_test.py --show-browser` for a lightweight launch check
