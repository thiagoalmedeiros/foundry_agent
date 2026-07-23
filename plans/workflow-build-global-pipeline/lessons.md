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

### [2026-07-23] — This template is judged as a teaching artifact, not on output quality
**Context:** Defining the global-pipeline restructure; the first grill attack was "nothing is broken about the live/deployed per-group flow — this is a preference rewrite."
**Mistake:** Nearly planned around "better interview output." The user reframed: the repo is a best-practices MAF TEMPLATE whose only per-segment change should be the loaded skills + prompts — so custom mechanisms that don't align with the framework ARE the breakage, even with perfect output.
**Rule:** Judge every design choice in this repo by "does the workflow stay domain-free and does this demonstrate the framework's blessed pattern," NOT by output quality. Bespoke machinery (strict parser, custom per-group budgets, one-field cadence override) is a liability here.
**Applies to:** all of src/foundry_agent/, plan scope decisions

### [2026-07-23] — The deterministic parser's format-sensitivity is what breaks portability
**Context:** Grill pushed back that restoring an LLM discovery agent reintroduces token cost + drift-blindness the strict parser was built to remove.
**Mistake:** Assumed the parser was strictly better because it fails loudly. For a swap-the-skill template, that same strictness is the liability — a new segment's author must match the exact markdown grammar or the parser raises.
**Rule:** In this workflow-build sibling, discovery is an LLM agent (tolerant of skill format). The deterministic parser is deferred to the sequential-orchestration sibling, where format-strictness is the point. Do not reintroduce the parser into this workflow's active path.
**Applies to:** field_groups_parser.py, discovery agent, the sequential sibling

### [2026-07-23] — Domain validation logic belongs in the skill, not the workflow
**Context:** Step-4 clarification exposed a contradiction: "an agent runs a python script" vs "we will not rely on [workflow] code."
**Mistake:** Framed the python presence-check as workflow code (mechanical_checks.py), which contradicts the zero-domain-logic-in-code thesis.
**Rule:** The validation script is SKILL content (skills/<format>/validation/validate.py); a domain-neutral workflow tool (run_skill_validation) importlib-loads and runs whatever the loaded skill ships. Swap the skill → its validation travels with it. The workflow never contains domain rules.
**Applies to:** skill_validation.py, skills/*/validation/, mechanical_checks.py retirement

### [2026-07-23] — `task lint` does not cover skill Python scripts
**Context:** Batch 1 added `skills/policy-report-format/validation/validate.py`, a load-bearing Python module the workflow will import and run. `task lint` is `ruff check src/ tests/ main.py` — it never sees `skills/**/*.py`.
**Mistake:** Nearly reported "DoD lint criterion green" while the new skill script was outside the linted scope entirely (a lint error there would pass the DoD falsely). Caught it and linted the file directly.
**Rule:** Skill scripts are code — extend the `task lint` (and ideally `task test`) scope to include `skills/**/*.py` in a later batch (Batch 6 config sweep is the natural home), and until then lint new skill scripts directly with `uv run --group dev ruff check <path>`.
**Applies to:** Taskfile.yml lint task, DoD criterion 2, skills/**/*.py

### [2026-07-23] — Shared test infra (conftest.py) is not "the old suite" — it blocks everything
**Context:** Batch 4 deleted `ElicitationTurn` (superseded by `ConversationTurn`). `tests/conftest.py` imports `ElicitationTurn` at module level for its `OPEN_TURN`/`CLOSING_TURN`/etc. fixtures — deleting the model broke conftest.py's own import, which cascaded into a collection error for EVERY test file in the suite, including Batch 2/3's own passing tests, not just the old per-group files the plan expected to go red.
**Mistake:** Assumed "delete the old model, old tests go red" without checking whether shared fixtures (not just individual test files) depend on it. conftest.py is infrastructure, not "one more old test file" — its breakage isn't confined the way a leaf test file's is.
**Rule:** Before deleting a model/symbol referenced anywhere, grep conftest.py (and any other shared fixture file) specifically, not just the leaf test files — a break there is whole-suite-blocking and must be fixed in the SAME batch that causes it (removing the now-unbuildable fixtures is fine; rebuilding new-shape equivalents is still the next batch's job if that's what the plan already assigned there).
**Applies to:** tests/conftest.py, any future model/symbol deletion

### [2026-07-23] — Production code can silently couple to a renamed type by string/import, not just by call site
**Context:** Renaming `workflow.py`'s `GroupTurn` → `ConversationPause` (part of the global-graph rewrite) broke `checkpoint_compat.py` — a production module, not a test — which imports `GroupTurn` by name to build its checkpoint-type allowlist. It surfaced as 9 unrelated-looking failures in `test_observability.py` (which imports `hosting.py` → `checkpoint_compat.py` transitively) before the real cause was traced.
**Mistake:** Nearly filed the `test_observability.py` failures as "expected red, old test noise" without reading the actual traceback — the failure looked superficially like the same old-symbol category but its ROOT was a production file that needed a real fix, not just tolerance.
**Rule:** Never bucket a failure as "expected/old" without reading its own traceback first — a coincidental-looking failure can trace to a real production coupling a rename broke, not just a stale test. Grep the WHOLE src/ tree (not just the file being edited) for every renamed symbol before declaring a rename complete.
**Applies to:** checkpoint_compat.py, workflow.py, any future dataclass rename

### [2026-07-23] — A new required constructor parameter breaks every existing call site silently until run
**Context:** Batch 4 added `validator: SkillValidator` as a required keyword-only parameter to `build_policy_report_workflow`. Batch 5 discovered that EVERY test file's local workflow-building helper (`_workflow`/`_stub_workflow`/`_agent`'s factory — six files) omitted it, since Batch 4's own Thomas-witnessed checks only exercised inline scripts that already knew about the new parameter.
**Mistake:** Nothing caught this until actually running the rewritten test suite — `task lint` is silent on missing keyword arguments (ruff doesn't type-check), so this class of break is invisible until execution.
**Rule:** After adding a required parameter to a widely-called factory/builder function, grep every call site across `tests/` (not just `src/`) before considering the change complete — lint passing is not evidence a required-arg addition is safe.
**Applies to:** build_policy_report_workflow, any future required-parameter addition to a shared factory

### [2026-07-23] — A live-smoke timeout budget doesn't carry over across a restructured pipeline
**Context:** Batch 7 live smoke against the hosted chat-mode server (`task hosted:run` + a `/responses` turn).
**Mistake:** A 2-minute curl timeout for the first live-smoke attempt was based on the old per-group design's single 42.95s witnessed run (recorded in the prior plan's `smoke-evidence.md`); the new global pipeline's Discovery agent alone makes ~3 real model round-trips (`load_skill` + multiple `read_skill_resource` calls) before gap analysis and elicitation even start, so total first-turn latency is materially higher — the retry's server-side latency was 28,751.7ms, but wall-clock from server start through the killed first attempt's wasted calls ran well past 2 minutes.
**Rule:** For a live smoke against a newly restructured multi-agent pipeline, do not reuse a timeout budget witnessed under a different (especially per-step-reduced) architecture — budget for one real model round-trip per agent-to-skill interaction the new design introduces, and default to a generous timeout (5+ minutes) for a first-ever live run of a changed pipeline shape.
**Applies to:** any future live-smoke batch, `task hosted:invoke`, Batch 7-style DoD gates
