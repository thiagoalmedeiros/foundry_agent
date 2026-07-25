# Lessons Learned

_Append an entry whenever the user corrects an approach, something fails
in a non-obvious way, or a pattern worth remembering is discovered. Read
this file at the start of every working session._

## Format

Each lesson follows this structure:

### [YYYY-MM-DD] — [Short Title]
**Context:** What was happening when this was discovered
**Mistake:** What went wrong (or what was nearly missed)
**Rule:** The rule to prevent recurrence
**Applies to:** [file, area, or task]

---

### [2026-07-24] — Domain vocabulary hides in pyproject.toml → egg-info
**Context:** Batch 2 de-domained the flow, but the DoD grep over `src/` still flagged `src/foundry_agent.egg-info/PKG-INFO` ("Policy Report authoring interview").
**Mistake:** Only the `.py` sources were edited; the package `description` (and a header comment) in `pyproject.toml` still carried the domain, and the editable-install metadata mirrored it into `src/*.egg-info/`.
**Rule:** When grep-cleaning domain vocabulary from `src/`, also fix `pyproject.toml` (description + comments) and run `uv sync --reinstall-package foundry-agent` to regenerate egg-info before re-grepping. See [[prefer-maf-native-mechanisms]] for the egg-info-staleness gotcha in AGENTS.md.
**Applies to:** `pyproject.toml`, `src/*.egg-info/`, DoD grep-clean (criterion 3)

### [2026-07-24] — Elicitation agent never loads its behavior skill; behavior is prompt-carried
**Context:** Batch 4's live before/after both showed 7 "did not call load_skill('elicitation')" warnings — the elicitation agent never loads the elicitation skill; its behavior comes entirely from the prompt.
**Mistake:** The slim's premise ("move behavior to the skill and point at it, keep it small") would have silently degraded behavior — a pointer to a skill the agent never loads delivers nothing. The stubbed `task test` cannot see this; only the live run did.
**Rule:** For the elicitation agent, load-bearing behavior must stay INLINE in the prompt (tighten, don't delete in favor of a pointer) or be inlined from the skill like the stateless packs. Always verify a "skill-driven" prompt change with a live before/after run, never `task test` alone. A truly skill-driven elicitation agent needs the agent to actually load the skill (a follow-up beyond this plan).
**Applies to:** `src/foundry_agent/prompts.py` (ELICITATION_INSTRUCTIONS), `skills/elicitation`, the live parity gate
