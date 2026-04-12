---
name: openevidence
description: Query OpenEvidence for evidence-based medical answers with screenshots and inline images automatically captured. Use when the user types /oe or asks for OpenEvidence.
triggers:
  - /oe
  - openevidence
  - "open evidence"
  - "check the evidence"
  - "what does OE say"
---

# OpenEvidence Skill

Query OpenEvidence and automatically capture answer screenshots and inline images (NCCN flowcharts, Kaplan-Meier curves, trial figures).

## Default Command (ALWAYS USE THIS)

```bash
python3 <SKILL_DIR>/scripts/run.py ask_question.py --question "<QUESTION>" --reliable --format text
```

Replace `<SKILL_DIR>` with the installed `openevidence` skill directory for the current runtime.

Answer screenshots and inline images are captured automatically — no extra flags needed.

For programmatic use, `--format json` is also available and returns a structured JSON object with `answer`, `ok`, and `artifacts` fields.

## After the Query Succeeds

The text output has three parts:

1. **Answer text** — between the `OPENEVIDENCE RESPONSE` header and the `Source:` line. Present this verbatim to the user — do not summarize or paraphrase.
2. **IMAGE ARTIFACTS** — lists file paths to captured inline figure PNGs (NCCN flowcharts, Kaplan-Meier curves, trial figures).
3. **ACTION REQUIRED** — contains an `open` command to display the figures gallery in the browser.

**You MUST:**
- Present the answer text verbatim.
- Run the `open` command shown in the ACTION REQUIRED section to display the HTML gallery of captured figures in the user's browser.
- If there is no ACTION REQUIRED section (no inline images were captured), just show the answer text.

Do NOT skip the `open` command. The gallery contains NCCN flowcharts, Kaplan-Meier curves, and trial figures that are essential to the answer.

## Authentication

If a query fails with an auth error, run:

```bash
python3 <SKILL_DIR>/scripts/run.py auth_manager.py validate
```

If validation fails:

```bash
python3 <SKILL_DIR>/scripts/run.py auth_manager.py reauth
```

If already logged into OpenEvidence in Helium:

```bash
python3 <SKILL_DIR>/scripts/run.py auth_manager.py import-helium
```

## Shared State

- Shared auth: `~/.local/share/openevidence-skill/`
- Artifacts: `~/.local/share/openevidence-skill/artifacts/`
