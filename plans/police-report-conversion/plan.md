# Plan: Convert Policy Report → Police Report on a domain-neutral flow

## Section 1 — What We Are Doing

1. **Author the `police-report-format` skill** — Rename `skills/policy-report-format/` → `skills/police-report-format/` and rewrite all of its content (SKILL.md, the reference files, the canonical template, and `validation/validate.py`) as a **law-enforcement incident/offense report** using a **two-level Required / Optional** field model (no Conditional tier). This is the only domain-specific artifact; its content correctness is validated by an external pipeline, not by this repo.

2. **Make the flow genuinely domain-neutral** — Strip *all* domain knowledge AND domain-named API out of `src/foundry_agent/`: genericize the public workflow/agent names, the agent `AGENT_NAME`/descriptions, cache-key and skill-source ids, and remove policy vocabulary + hardcoded attribute ranges/enums from `prompts.py`. Relocate the domain-neutral *behavior* that `prompts.py` currently duplicates (attribution honesty, Socratic assist, inference discipline) into the `elicitation` skill, leaving `prompts.py` as lean, skill-driven orchestration. Outcome: swapping the domain later touches only the skill.

3. **De-domain the test suite** — Neutralize the offline test doubles: strip policy vocabulary from `conftest.py` stubs and the input fixture, delete the *skill-content* validation assertions (not this repo's responsibility), and keep the *workflow-mechanism* tests but repoint them at a small domain-neutral fixture skill. `task test` proves flow mechanics on neutral data.

4. **Prove behavior parity live, then clean up** — Because the stubbed suite cannot see prompt-quality regressions, capture a live behavioral **baseline** (police skill + current prompt) via `task hosted:invoke` *before* any prompt trim, re-run the same script after, and diff. Only once parity is witnessed, remove dead code and orphaned old files.

5. **Continuous lessons capture** — Lessons are automatically logged to `lessons.md` after every user correction and every agent mistake discovered during execution — without being asked.

---

## Section 2 — How We Are Doing It / What Is Out of Scope

## Execution Config

> This section is read by any executor before starting batch work. Do not skip it.

| Setting | Value |
| ------- | ----- |
| Per-batch verify command | `task test` → `task lint` |
| Global verify command | `task test` → `task lint` (+ grep-clean + live parity per DoD) |
| Thomas validation | `enabled` |
| Definition of Done | inline criteria (see `## Definition of Done`) |

### Execution rules (always active)

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately after any user correction, any non-obvious failure, or any recurring pattern discovered. Do not wait to be asked. Do not batch multiple lessons into one call.
2. **Status updates** — Every item is `🔄` while in progress and `✅` before the next batch starts. Never advance with a `⬜` item in a completed batch. After each `plan.md` status edit, re-read the section to confirm the ✅ landed.
3. **Verify gate** — After each batch run `task test` → `task lint`. Then invoke `skill:thomas` as a subagent with the batch's exact `**Verify:**` checklist. Do not mark items `✅` until Thomas returns a WITNESSED PASSING verdict.
4. **DoD gate** — After each batch's Verify passes, run the applicable Definition-of-Done criteria (a validation subagent). The DoD row must be `✅` before the next batch starts.
5. **Global gate** — After all batches, run the global verify + full DoD. Thomas performs a final full-plan pass before results are presented.

## Definition of Done

Inline criteria (per-batch gate checks the criteria applicable to that batch; the final batch checks all five):

1. **`task test` green** — the offline suite passes on neutral fixtures.
2. **`task lint` green** — `ruff check src/ tests/ main.py` clean.
3. **Flow carries zero domain knowledge** — `grep -riE 'polic(y|ies)|POL-|governance|regulatory|compliance' src/ tests/` returns nothing except the legitimate `FORMAT_SKILL_NAME` skill-name pointer; no hardcoded attribute counts/enums remain in `prompts.py`.
4. **Live behavior parity witnessed** — the post-trim `task hosted:invoke` transcript matches the pre-trim baseline on: discovery order, honest attribution (Doc / user / inferred), inference-confirm cadence, the `run_skill_script` call shape, and assembled-document structure.
5. **Old files + dead code removed** — the `policy-report-format` skill dir is gone, no orphaned constants/helpers remain, and `src/*.egg-info/SOURCES.txt` is refreshed.

---

### Implementation checklist

#### `skills/police-report-format/` (via `git mv` from `policy-report-format`)
- `SKILL.md` — `name: police-report-format`; description → the law-enforcement incident/offense report; routing table updated. **Retain the opaque `PAn` / `FGn` / `PCn` / `PRn` code scheme** (never user-surfaced per EL10; `models.py` + `validate.py._order` treat them as opaque) — only human-readable names + content change. *(Overridable at build if semantic codes are wanted.)*
- `references/*.md` — rewrite all of `definitions`, `attributes`, `field-groups`, `characteristics`, `rules`, `statement-patterns`, `population-guidance`, `inference-guidance`, `validation`, `template` for police-report field groups and attributes. Requirement column collapses to **Required / Optional only**; genuinely conditional fields (e.g. arrestee details only when an arrest occurred) live inside a field group's **Adequacy** prose, not a global tier.
- `validation/validate.py` — drop the Conditional branches (`PA13`/`PA27`/`PA28`) and the `_POLICY_TYPES` enum; keep the generic placeholder + none-allowed machinery; add the police domain's deterministic rules (e.g. incident-number format, required non-empty narrative, ISO date). Update the module docstring. `SECURITY.md` is generic — unchanged.

#### `src/foundry_agent/prompts.py`
- Remove domain KNOWLEDGE: the `Governance/Operational/Security/Compliance` enum, "policy frameworks", "regulatory instrument"/"effective date" examples, and the hardcoded `PA1-PA32`/`PC1-PC12`/`PR1-PR18` counts → skill-driven phrasing ("the attributes / characteristics / rules the skill declares").
- Rename "Policy Report" role labels → neutral ("the document" / "the report").
- `FORMAT_SKILL_NAME` value → `"police-report-format"` (Batch 3).
- Relocate duplicated behavioral prose → point at the elicitation skill; **KEEP orchestration**: agent roles, output-schema expectations, the one-group-at-a-time flow, and the `run_skill_script` arg contract ("a LIST of exactly two JSON strings"). **The arg contract is do-not-touch** — trimming it silently breaks live validation while every stubbed test stays green.

#### `src/foundry_agent/{workflow,main,hosting,chat_agent,agents}.py`
- Genericize the public API + all call sites/imports: `create_policy_report_workflow` → `create_report_workflow`, `build_policy_report_workflow` → `build_report_workflow`, `create_policy_report_agent` → `create_report_agent` (exact neutral names a build decision); `AGENT_NAME` → neutral (e.g. `"report-interview-agent"`) or skill-derived; `_CACHE_KEY_PREFIX`, `source_id="policy_skills"` → neutral; all "Policy Report" descriptions/docstrings de-domained.
- Retain the flow's *generic* conditional-handling capability (so other skills may declare conditionals) — build no new conditional logic; the police skill simply doesn't use it.

#### `src/foundry_agent/models.py`
- Docstrings only: `policy-report-format` → "the mounted format skill"; "Policy Report" → "the document". Field descriptions stay generic.

#### `skills/elicitation/references/question-loop.md`
- Audit `ELICITATION_INSTRUCTIONS` against EL1–EL14 first; most behavior (Socratic assist EL11, judged capture EL3/EL5, confirm-inferred EL13, no-internal-ids EL10) is already there. Move any domain-neutral behavior *not* yet covered into this file so `prompts.py` can point instead of duplicate.

#### `tests/`
- `conftest.py` — strip policy vocabulary from `GROUPS`, the turn stubs, `INCOMPLETE_VALIDATION`, `STUB_DOCUMENT`; repoint `INPUT_FILE` to a neutral input fixture. Update all renamed flow-symbol imports.
- `fixtures/` — replace `policy-input-file.md`; add a tiny domain-neutral **mechanism fixture skill** (`SKILL.md` + `validation/validate.py`) for the runner/discovery tests.
- `test_skill_script.py` — repoint the mechanism / CLI / runner / discovery / drift-guard tests at the neutral fixture skill; **DELETE the skill-content assertions** (policy enum, `PA13`-when-Compliance conditional, None-allowed, title word cap).
- All other test files — update renamed symbols and strip stray policy strings.

### Validation strategy

Run after each batch:
```
task test
task lint
```
Batch 4 additionally runs the live parity check:
```
task hosted:run              # serve on :8088 (real model)
task hosted:invoke MESSAGE=… # replay the fixed QA script; diff vs saved baseline
```

### Out of scope

- **Skill content correctness** (whether the police report's fields are complete/accurate) — owned by the external skill-validation pipeline, per the agreed boundary; not gated by this repo's tests.
- **Docs rewrite** (`README.md`, `ARCHITECTURE.md`, `AGENTS.md` still describe a "Policy Report") — deferred to `/ship` via `skill:docs-sync`; not touched here.
- **`.checkpoints/` runtime data, `infra/` bicep, `.env*`, `azure.yaml`** — no domain logic; untouched.
- **New conditional-requirement machinery** — the two-level police skill needs none; the flow keeps its existing generic capability but grows no new logic.
- **Speculative refactors** beyond the domain swap + prompt slim.

---

## Section 3 — Tracking List

### Batch 1 — Author the `police-report-format` skill (content only, flow still on policy)

| #      | Item                                                                 | File/Area                                             | Status |
| ------ | -------------------------------------------------------------------- | ----------------------------------------------------- | ------ |
| 1      | `SKILL.md + definitions/attributes/field-groups (identity+fields, two-level)` | `skills/police-report-format/`                | ✅     |
| 2      | `Remaining references (characteristics, rules, statement-patterns, population, inference, validation, template)` | `skills/police-report-format/references/` | ✅     |
| 3      | `validate.py rewrite — two-level, drop conditional/enum, police rules` | `skills/police-report-format/validation/validate.py` | ✅     |
| 4      | `Smoke-run the new validate.py CLI on a sample capture set`          | `skills/police-report-format/validation/`             | ✅     |
| DoD    | Validate batch (criteria 1, 2)                                       | inline DoD                                            | ✅     |
| Thomas | Verify this batch                                                    | `skill:thomas`                                        | ✅     |

**Verify:** `task test` (still green — policy skill remains mounted) → `task lint` → `python skills/police-report-format/validation/validate.py '{"PA1":"x"}' '[{"attribute_ids":["PA1"]}]'` returns a JSON array.
**DoD Gate:** Invoke a validation subagent against criteria 1–2. Mandatory. Mark the DoD row ✅ only after both pass; on failure, fix, log in `lessons.md`, re-run.
**Thomas Gate:** After Verify + DoD pass, dispatch `skill:thomas` to execute every check itself and confirm witnessed passing output, and that all batch rows are ✅ in `plan.md`. Mark Thomas ✅ only on **APPROVED**.

---

### Batch 2 — Genericize the flow + de-domain the tests (still mounting the policy skill)

| #      | Item                                                                          | File/Area                                              | Status |
| ------ | ----------------------------------------------------------------------------- | ------------------------------------------------------ | ------ |
| 1      | `Genericize public API + AGENT_NAME/ids/descriptions + all call sites`        | `src/foundry_agent/{workflow,main,hosting,chat_agent,agents}.py` | ✅     |
| 2      | `Strip domain knowledge/vocabulary from prompts.py (enums, ranges, labels); keep behavior+orchestration` | `src/foundry_agent/prompts.py` + `models.py` docstrings | ✅     |
| 3      | `Neutralize conftest stubs + input fixture; add neutral mechanism fixture skill; repoint + trim test_skill_script` | `tests/conftest.py`, `tests/fixtures/`, `tests/test_skill_script.py` | ✅     |
| 4      | `Sweep remaining test files for renamed symbols + policy strings`             | `tests/*.py`                                            | ✅     |
| DoD    | Validate batch (criteria 1, 2, 3)                                             | inline DoD                                             | ✅     |
| Thomas | Verify this batch                                                            | `skill:thomas`                                         | ✅     |
_Heaviest batch — atomic by necessity: renaming the public API breaks every importer at once, so src + tests move together to keep a green checkpoint._

**Verify:** `task test` → `task lint` both green (flow now carries no domain, still mounting the **policy** skill) → `grep -riE 'polic(y|ies)|POL-|governance|regulatory|compliance' src/ tests/` returns only the `FORMAT_SKILL_NAME` pointer value.
**DoD Gate:** Validation subagent against criteria 1–3 (criterion 3 tolerates the still-`policy-report-format` skill-name pointer this batch). Mandatory; fix + log + re-run on any failure.
**Thomas Gate:** Dispatch `skill:thomas` to witness Verify + DoD and confirm all rows ✅. Mark ✅ only on **APPROVED**.

---

### Batch 3 — Cut the mount over to the police skill (thesis checkpoint)

| #      | Item                                                                 | File/Area                                    | Status |
| ------ | -------------------------------------------------------------------- | -------------------------------------------- | ------ |
| 1      | `git rm old skills/policy-report-format/; set FORMAT_SKILL_NAME → police-report-format` | `skills/`, `src/foundry_agent/prompts.py`   | ✅     |
| 2      | `Update residual old-skill-name references (pack header comment, inline-reference sourcing, any test string)` | `src/foundry_agent/prompts.py`, `tests/`    | ✅     |
| 3      | `Confirm discovery + mechanism tests green on the police skill`      | `tests/`                                     | ✅     |
| DoD    | Validate batch (criteria 1, 2, 3, 5-partial)                        | inline DoD                                    | ✅     |
| Thomas | Verify this batch                                                   | `skill:thomas`                               | ✅     |
_This batch operationally proves the thesis: with the flow + tests already domain-neutral, swapping the domain touches only the skill dir + its name pointer._

**Verify:** `task test` → `task lint` green (now mounting the **police** skill) → `grep -riE 'polic(y|ies)|POL-|governance' src/ tests/` returns nothing (police content lives only under `skills/`).
**DoD Gate:** Validation subagent against criteria 1–3 (now with zero policy references) + criterion 5's "old skill dir removed". Mandatory.
**Thomas Gate:** Dispatch `skill:thomas` to witness Verify + DoD and all rows ✅. Mark ✅ only on **APPROVED**.

---

### Batch 4 — Slim `prompts.py` to skill-driven orchestration + live parity gate

| #      | Item                                                                          | File/Area                                            | Status |
| ------ | ----------------------------------------------------------------------------- | ---------------------------------------------------- | ------ |
| 1      | `Capture live baseline FIRST (police skill + current prompt) via QA script → save transcripts` | `plans/police-report-conversion/baseline/before.json` | ✅     |
| 2      | `Audit prompt prose vs EL1–EL15/format skill; relocate honest-sourcing behavior into the skills (EL15)` | `skills/elicitation/references/question-loop.md`, `skills/elicitation/SKILL.md` | ✅     |
| 3      | `Slim ELICITATION_INSTRUCTIONS to orchestration + pointers (37→19 lines; run_skill_script arg contract untouched)` | `src/foundry_agent/prompts.py`                | ✅     |
| DoD    | Validate batch (criteria 1, 2, 3, 4)                                          | inline DoD                                           | ✅     |
| Thomas | Verify this batch                                                            | `skill:thomas`                                       | ✅     |
_Hard sequencing gate: item 1 (baseline) MUST complete before any edit in items 2–3, or the parity check has nothing to diff against._

**Verify:** `task test` → `task lint` green → live re-run: `task hosted:run` + replay the QA script with `task hosted:invoke`; diff the transcript against the Batch-4 baseline → **behavior parity** on discovery order, attribution honesty, inference-confirm cadence, the `run_skill_script` call shape, and assembled-document structure.
**DoD Gate:** Validation subagent against criteria 1–4; criterion 4 (live parity) is mandatory and cannot be witnessed by `task test` — it requires the before/after transcript diff. Fix + log + re-run on any drift.
**Thomas Gate:** Dispatch `skill:thomas` to witness the Verify (including the live diff) + DoD and all rows ✅. Mark ✅ only on **APPROVED**.

---

### Batch 5 — Cleanup + final full-plan sign-off

| #      | Item                                                                 | File/Area                          | Status |
| ------ | -------------------------------------------------------------------- | ---------------------------------- | ------ |
| 1      | `Remove dead code / orphaned constants + helpers; refresh egg-info SOURCES.txt` | `src/foundry_agent/`, `src/*.egg-info/` | ✅     |
| 2      | `Final grep sweep: zero policy/police domain terms in src+tests (police only under skills/)` | repo root                   | ✅     |
| 3      | `Confirm git status coherent (old files gone, new skill tracked)`    | repo root                          | ✅     |
| DoD    | Full Definition of Done (criteria 1–5)                              | inline DoD                          | ✅     |
| Thomas | Full plan sign-off                                                   | `skill:thomas`                     | ✅     |

**Verify:** `task test` → `task lint` → 0 failures; `grep -riE 'polic(y|ies)|POL-|governance|regulatory|compliance' src/ tests/` empty; `git status` shows the old skill removed and the new one tracked.
**DoD Gate:** Validation subagent against **all five** criteria, reported pass/fail per criterion. Mandatory.
**Thomas Gate:** Dispatch `skill:thomas` for the full-plan pass — re-run the global verify, review every `plan.md` section to confirm all rows ✅, and issue a final **APPROVED / NOT APPROVED** verdict. The plan is not complete until **APPROVED**.
