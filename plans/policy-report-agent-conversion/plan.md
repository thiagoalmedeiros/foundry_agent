# Plan: Convert d3_initiative_poc into a self-contained Policy Report Foundry agent

> Origin: `/agentic-sdlc:define` — "clean update this project and convert it in a generic
> foundry IA agent". Scope hardened via grill-me on 2026-07-22: **policy-report-hardwired,
> cleanly** — a self-contained, fork-per-domain Foundry agent template carrying a Policy
> Report domain, NOT a domain-agnostic engine. DoD: offline green per batch + witnessed
> live smoke at the end.

## Section 1 — What We Are Doing

1. **Author the Policy Report domain as in-repo skills** — Create `skills/policy-report-format/` (SKILL.md + the 10 reference files the prompt packs read) and `skills/elicitation/` (SKILL.md + question-loop references, EL1–EL14), designed to satisfy the strict `field_groups_parser` contract, so the project is self-contained: today the code points at `../../skills/d3/` which does not exist and the suite cannot even collect.

2. **Rename and repoint the package** — `src/d3_initiative_poc` becomes `src/foundry_agent` (distribution `foundry-agent`); `SKILLS_DIR` becomes repo-local (`<repo>/skills`); every import, Taskfile task, `azure.yaml` entry, and the root `main.py` shim follows.

3. **Rewrite the domain-coupled code for the new domain** — `field_groups_parser` (IA→PA prefix), `mechanical_checks` (new adequacy rules: PA2 title length, PA3 policy-type enum, placeholder scan), `prompts.py` (policy vocabulary, PA/PC/PR/FG identifiers, policy-type classification replacing Problem/Threat/Opportunity), `models.py` descriptions — honestly hardwired to Policy Report per the grill decision.

4. **Restore a green, witnessed verification path** — Rewrite the test fixtures and skill-content pins for the new domain until `task test` + `task lint` are fully green, then finish with one witnessed live smoke through the production serving path (`task hosted:run` / `task hosted:invoke`).

5. **Clean update of the repo itself** — `git init` + `.gitignore` + baseline commit, purge stale artifacts (`.checkpoints/*`, `output/server.log`, `.DS_Store`, `*.egg-info`), add the missing `.env.example` the README references, rewrite README/azure.yaml/Taskfile prose for the new identity.

6. **Continuous lessons capture** — Lessons are automatically logged to `lessons.md` after every user correction and every agent mistake discovered during execution — without being asked.

---

## Section 2 — How We Are Doing It / What Is Out of Scope

## Execution Config

> This section is read by any executor before starting batch work. Do not skip it.

| Setting | Value |
| ------- | ----- |
| Per-batch verify command | `task test` + `task lint` (batch-specific expected state noted per batch — the suite is red at baseline and first goes fully green at Batch 5) |
| Global verify command | `task test` + `task lint` + live smoke: `task hosted:run` then `task hosted:invoke` |
| Thomas validation | `enabled` |
| Definition of Done | inline criteria — see `## Definition of Done` below |

### Execution rules (always active)

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately after any user correction, any non-obvious failure, or any recurring pattern discovered. Do not wait to be asked. Do not batch multiple lessons into one call.
2. **Status updates** — Every item must be `🔄` before handoff to review. Every item must be `✅` before the next batch starts. Never advance with a `⬜` item in a completed batch.
3. **Verify gate** — After each batch, run the per-batch verify command listed above. Invoke `skill:thomas` as a subagent with the batch's exact `**Verify:**` checklist. Do not mark items `✅` until Thomas returns a WITNESSED PASSING verdict.
4. **Global gate** — After all batches complete, run the global verify command. Invoke `skill:thomas` for a final full-plan validation pass before presenting results to the user.

## Definition of Done (inline criteria)

1. `task test` green — entire offline suite (stubbed chat clients), zero collection errors.
2. `task lint` green (`ruff check src/ tests/ main.py`).
3. Self-contained: no code/config path resolves outside the repo root; `grep -ri "d3\|initiative" src/ tests/ main.py Taskfile.yml azure.yaml README.md pyproject.toml` returns zero hits (plans/ folder exempt — it records history).
4. Final batch only: witnessed live smoke — `task hosted:run` serves on :8088 and one `task hosted:invoke` turn returns the interview's opening elicitation turn (a `request_info` pause) with no server error. **User-assisted fallback:** if the `.env` Azure credentials are invalid/expired, record the failure output in `lessons.md`, mark the smoke item as user-assisted-pending, and surface it — do not fake the verdict.

### The Policy Report domain design (authoritative for Batch 2 — do not re-invent during build)

**Identifiers:** attributes `PA1…PA32`, characteristics `PC1…PC12`, rules `PR1…PR18`, groups `FG1…FG8`. Capture-line format becomes `- PAn — value`.

**Field groups** (each needs `### FGn — <name>` heading, one `**Framing:**` line, one `| Attributes | … |` table row, one `**Adequacy:**` paragraph, plus a final `### Group → attribute coverage map` table ending with the sentence `All 32 attributes are covered exactly once.`):

| Group | Name | Attributes |
| ----- | ---- | ---------- |
| FG1 | Identification & Classification | PA1 Policy ID (`POL-<domain>-<seq>`), PA2 Title (≤ 10 words), PA3 Policy Type, PA4 Status, PA5 Version, PA6 Policy Owner |
| FG2 | Purpose & Scope | PA7 Purpose Statement, PA8 Scope of Application, PA9 Exclusions, PA10 Effective Date |
| FG3 | Background & Drivers | PA11 Context Narrative (2–5 paragraphs), PA12 Business Drivers, PA13 Regulatory Drivers *(conditional)*, PA14 Risk Addressed |
| FG4 | Definitions & References | PA15 Key Terms, PA16 Related Policies, PA17 External References |
| FG5 | Policy Statements | PA18 Core Policy Statements, PA19 Guiding Principles, PA20 Exception Criteria |
| FG6 | Roles & Responsibilities | PA21 Owner Responsibilities, PA22 Approver, PA23 Affected Roles & Duties, PA24 Escalation Path |
| FG7 | Compliance & Enforcement | PA25 Monitoring & Measurement, PA26 Non-Compliance Consequences, PA27 Exception Process, PA28 Audit Requirements *(conditional)* |
| FG8 | Lifecycle & Communication | PA29 Review Cadence, PA30 Revision History Requirements, PA31 Communication & Training Plan, PA32 Retirement Criteria |

**Classification driver:** PA3 Policy Type is exactly one of **Governance / Operational / Security / Compliance** — it plays the conditional-requirement role D3's Problem/Threat/Opportunity played (`GapReport.classification`). Conditionals: PA13 required when PA3 = Compliance; PA28 required when PA3 ∈ {Security, Compliance}.

**Mechanical checks (deterministic, FG1-adequacy-cited):** PA2 ≤ 10 words (blocking), PA3 ∈ the 4-value enum (blocking), placeholder scan over required captured values (blocking) — direct analogues of the current IA2/IA3 checks, keeping `mechanical_checks.py`'s shape.

**Reference files** `skills/policy-report-format/references/` must contain exactly the union of the prompt packs: `definitions.md`, `attributes.md`, `field-groups.md`, `inference-guidance.md`, `population-guidance.md`, `statement-patterns.md`, `rules.md`, `characteristics.md`, `validation.md`, `template.md`. The template declares the canonical document sections (target: 17 sections mirroring FG order plus front-matter and `## Advisory findings` appendix). Statement patterns cover at least PA7 (purpose pattern: "This policy establishes … in order to …") and PA18 (modal MUST/SHOULD statement rules).

**Elicitation skill** `skills/elicitation/` is domain-neutral: keep the EL1–EL14 invariant IDs the code and prompts already cite (EL4 batched-cadence default overridden by the workflow, EL7 exact-ID capture, EL8 groups-from-skill, EL10 no internal IDs to users, EL11 Socratic assist / coach-on-mismatch, EL12 verbatim framing line, EL13 confirm-inferred-first, EL14 turn layout), reconstructed from the quotations in `prompts.py` and the README — the original file is gone; the quotes are the contract.

**Naming:** package/module `foundry_agent`, distribution `foundry-agent`, azd project name `foundry-agent`, hosted agent service + wire model name `policy-report-agent`, skill names `policy-report-format` and `elicitation`, `SkillsProvider` `source_id="policy_skills"`.

### Implementation checklist

#### Repo hygiene (Batch 1)
- `git init`; author `.gitignore` (`.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, `.checkpoints/`, `output/`, `.env`, `.DS_Store`).
- Delete `.checkpoints/*`, `output/server.log`, `.DS_Store`, `src/d3_initiative_poc.egg-info/`.
- Add `.env.example` with the keys the code reads: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`, `AZURE_OPENAI_API_KEY` (optional — managed identity fallback), `OTEL_EXPORTER_OTLP_ENDPOINT` (values blank/placeholder; never copy real values from `.env`).
- Baseline commit before any surgery.

#### `skills/` (Batch 2)
- Author both skills per the domain design above. `field-groups.md` must parse: headings `### FGn — <name>`, attribute rows accept `PA4` / `PA4 Status` / `PA7–PA10` range forms (no spaces around the dash), coverage-map section heading contains "coverage map".
- Each `SKILL.md` carries the name + description + routing table to references (mirrors what `FileSkillsSource` advertises and the README describes as load_skill → read_skill_resource flow).

#### `src/foundry_agent/` (Batches 3–4)
- `git mv src/d3_initiative_poc src/foundry_agent`; update every `from d3_initiative_poc…` import (all 14 modules), `pyproject.toml` (`name = "foundry-agent"`, description, comments), root `main.py` shim, `Taskfile.yml` module paths (`foundry_agent.main`, `.hosting`, `.spike_hitl`, `.otel_collector`) and `hosted:invoke` model string → `policy-report-agent`, `azure.yaml` (names, description, metadata; keep protocol/env blocks intact; change the `ai-project` deployments block from `gpt-5.4` to the generic test model `gpt-5-mini`, format OpenAI, version `2025-08-07` — user decision 2026-07-22: any generic model is fine for testing; gpt-4o-mini rejected as deprecated, gpt-5.4-mini rejected for zero GlobalStandard quota on this subscription, gpt-5-mini deployed live via az CLI).
- `prompts.py`: `SKILLS_DIR = PACKAGE_DIR / "skills"`; `FORMAT_SKILL_NAME = "policy-report-format"`; `ELICITATION_SKILL_NAME = "elicitation"`; rewrite the five instruction blocks to policy vocabulary (PA/PC/PR/FG ids, PA1–PA32 / PC1–PC12 / PR1–PR18 ranges, policy-type classification, "Never answer from prior knowledge of policy frameworks — if the skill does not say it, it is not true here"). Pack tuples keep the same 10 file names.
- `field_groups_parser.py`: `_SINGLE_ID`/`_RANGE_ID` regexes IA→PA; docstrings updated; `removeprefix("IA")` → `"PA"`.
- `mechanical_checks.py`: `_CAPTURED_LINE` IA→PA; `_CLASSIFICATIONS = {governance, operational, security, compliance}`; checks keyed to PA3/PA2; citations quote the NEW skill's adequacy text verbatim.
- `models.py`: description strings (`'IA4'`→`'PA7'` examples, classification description → policy type), module docstring; enum classes unchanged.
- `agents.py`, `workflow.py`, `chat_agent.py`, `hosting.py`, `usage.py`, `checkpoint_compat.py`, `spike_hitl.py`, `main.py`, `otel_collector.py`, `__init__.py`: rename-driven edits, `source_id="policy_skills"`, cache-key / server-id strings, docstring sweeps. `checkpoint_compat.py` maps old module path → new (verify its shim logic still targets the renamed types).

#### `tests/` (Batch 5)
- `tests/conftest.py`: rebuild `GROUPS` / `COMPLETE_REPORT` fixtures around the PA domain (stub clients stay as-is).
- `test_field_groups_parser.py`, `test_mechanical_checks.py`, `test_skill_mount.py`, `test_elicitation_skill.py`: repin to the new skill files (`### FG1 — Identification & Classification`, `All 32 attributes are covered exactly once.`, both `SKILL.md`s on disk, PA enum/title checks).
- Remaining 16 test modules: import renames plus any content assertions naming IA ids, "initiative", or the old skill names.

#### Docs & config (Batch 6)
- `README.md`: full rewrite — what the template is (self-contained MAF + Foundry-hosted interview agent, policy-report domain, fork-per-domain), serving paths, layout tree, running instructions; drop D3 history and stale plan/kb links; keep the graph-vs-functional API finding only if condensed as an architecture note (executor's judgment).
- Final sweep: DoD criterion 3 grep must be zero-hit.

### Validation strategy

Run after each batch:
```
task test && task lint
```
Batches 1–4 have batch-specific expected states written in their Verify lines (the suite cannot be green before the tests are rewritten in Batch 5 — a red `task test` there is only acceptable in the exact expected shape stated per batch, nothing else).

Global (Batch 7): `task test && task lint`, then `task hosted:run` (server up on :8088, OTel collector via `otel:up` dependency) and `task hosted:invoke MESSAGE="Draft a remote-work security policy for a mid-size fintech."` → expect an OpenAI-`/responses` payload whose output contains the FG1 opening elicitation turn (framing line + first field) as a `request_info` function call, no 5xx, no traceback in `output/`/server logs.

### Out of scope

- **Domain-agnostic engine** — explicit grill-me decision: no prefix-agnostic parser, no skill-declared constraint DSL, no second fixture skill. Genericity = fork this template per domain.
- **Dependency upgrades** — pins are days old (`agent-framework*` b260721+, `openai>=2.45`); no bumps unless a rename breaks resolution.
- **Azure deployment** — `azure.yaml` is updated but `azd provision`/`azd deploy` stay user-assisted, outside this plan.
- **Restoring the original D3 skills** — gone by design; their contracts survive only as the parser/prompts/tests reconstruction above.
- **New features** — no persistence beyond existing checkpointing, no DevUI enhancements, no multi-document support, no prompt-quality tuning beyond faithful domain transposition.
- **`.env`** — user-owned; never edited, never committed (only `.env.example` is added).

---

## Section 3 — Tracking List

### Batch 1 — Repo hygiene & git baseline

| #      | Item                                                              | File/Area                          | Status |
| ------ | ----------------------------------------------------------------- | ---------------------------------- | ------ |
| 1      | `git init` + author `.gitignore`                                   | repo root                          | ✅     |
| 2      | Purge stale artifacts (.checkpoints/*, output/server.log, .DS_Store, egg-info) | repo root, `src/`     | ✅     |
| 3      | Add `.env.example` (keys only, no real values)                     | `.env.example`                     | ✅     |
| 4      | Baseline commit of the cleaned pre-conversion tree                 | git                                | ✅     |
| DoD    | Validate batch                                                     | inline DoD criteria 2 (lint)       | ✅     |
| Thomas | Verify this batch                                                  | `skill:thomas`                     | ✅     |

**Verify:** `task lint` → green. `task test` → still red, but ONLY with the known baseline failure (2 collection errors: `FileNotFoundError` on `…/skills/d3/initiative-format/references/field-groups.md`). `git log --oneline` → exactly one baseline commit; `git status` clean.
**DoD Gate:** Run inline DoD criterion 2 against this batch via a validation subagent. Mark the DoD row ✅ only after it confirms. If any criterion fails, fix, log the correction in `lessons.md`, and re-run the gate before proceeding.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas also verifies all tracking-list rows for this batch are ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues **APPROVED**.

---

### Batch 2 — Author the two skills (the domain foundation)

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | `policy-report-format` SKILL.md + 10 reference files per the domain design | `skills/policy-report-format/`      | ✅     |
| 2      | `elicitation` SKILL.md + question-loop references (EL1–EL14)       | `skills/elicitation/`                        | ✅     |
| 3      | Self-review: field-groups.md satisfies every parser expectation (headings, rows, coverage map, exactly-once) | `skills/policy-report-format/references/field-groups.md` | ✅     |
| DoD    | Validate batch                                                     | inline DoD criteria 2 (lint)                 | ✅     |
| Thomas | Verify this batch                                                  | `skill:thomas`                               | ✅     |

**Verify:** `task lint` → green (no code changed). Structural check of the new content: `uv run python - <<'EOF'` parsing `skills/policy-report-format/references/field-groups.md` with the *current* parser pointed at the file after a temporary in-test prefix substitution is NOT required — instead assert manually: 8 `### FG` headings, 8 `**Framing:**` lines, 8 `| Attributes |` rows, 8 `**Adequacy:**` paragraphs, coverage-map table present, PA1–PA32 each claimed exactly once, closing sentence `All 32 attributes are covered exactly once.` present. All 10 pack reference files + both SKILL.md files exist and are non-empty.
**DoD Gate:** as Batch 1.
**Thomas Gate:** as Batch 1.

---

### Batch 3 — Package rename & repoint

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | `git mv src/d3_initiative_poc src/foundry_agent` + all import updates (src + tests) | `src/foundry_agent/`, `tests/` | ✅     |
| 2      | `pyproject.toml` (name/description), root `main.py`, `Taskfile.yml` module refs + invoke model string | repo root       | ✅     |
| 3      | `azure.yaml` names/description/metadata → `foundry-agent` / `policy-report-agent` | `azure.yaml`                  | ✅     |
| 4      | `prompts.py` skill constants → repo-local `skills/`, new skill names | `src/foundry_agent/prompts.py`             | ✅     |
| DoD    | Validate batch                                                     | inline DoD criteria 2 (lint)                 | ✅     |
| Thomas | Verify this batch                                                  | `skill:thomas`                               | ✅     |

**Verify:** `task lint` → green. `uv run python -c "import foundry_agent, foundry_agent.hosting, foundry_agent.workflow"` → imports resolve. `task test` → expected red confined to: content assertions still pinned to D3 wording and the parser still expecting `IA` ids (no import errors, no missing skill files at the new path). *Witnessed deviation (2026-07-22): 7 additional failures read the out-of-repo `kb/examples` fixture via `conftest.py:31` — latent monorepo remnant invisible until collection was unblocked; vendored fixture is now an explicit Batch 5 item (see lessons.md).*
**DoD Gate:** as Batch 1.
**Thomas Gate:** as Batch 1.

---

### Batch 4 — De-D3 the domain-coupled code

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | `field_groups_parser.py` IA→PA (regexes, removeprefix, docs)       | `src/foundry_agent/field_groups_parser.py`   | ✅     |
| 2      | `mechanical_checks.py` rewritten to PA2/PA3 + placeholder rules with verbatim new-skill citations | `src/foundry_agent/mechanical_checks.py` | ✅     |
| 3      | `prompts.py` five instruction blocks + `models.py` descriptions → policy vocabulary | `src/foundry_agent/prompts.py`, `models.py` | ✅     |
| 4      | Docstring/string sweep of remaining modules (`agents.py`, `workflow.py`, `chat_agent.py`, `hosting.py`, `usage.py`, `checkpoint_compat.py`, `spike_hitl.py`, `main.py`, `otel_collector.py`) incl. `source_id="policy_skills"`; public symbols renamed (`create_policy_report_workflow` etc.), OTel usage attrs → `foundry_agent.usage.*` | `src/foundry_agent/` | ✅     |
| DoD    | Validate batch                                                     | inline DoD criteria 2 (lint)                 | ✅     |
| Thomas | Verify this batch                                                  | `skill:thomas`                               | ✅     |

**Verify:** `task lint` → green. `uv run python -c "from foundry_agent.field_groups_parser import parse_field_groups; groups = parse_field_groups(); assert len(groups.groups) == 8, groups"` → parses the authored skill end-to-end. `uv run python -c "from foundry_agent import prompts"` → all 10 pack files read at import/construction paths without OSError. `task test` → expected red confined to test-content assertions (Batch 5's job); zero errors originating in `src/`.
**DoD Gate:** as Batch 1.
**Thomas Gate:** as Batch 1.

---

### Batch 5 — Rewrite the test suite for the new domain

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | `conftest.py` fixtures (GROUPS, COMPLETE_REPORT) → PA domain; replace the out-of-repo `INPUT_FILE` (`kb/examples/...`, conftest.py:31) with a vendored in-repo sample policy input document | `tests/conftest.py`, `tests/fixtures/` | ✅     |
| 2      | Skill-reading tests repinned (`test_skill_mount`, `test_field_groups_parser`, `test_mechanical_checks`, `test_elicitation_skill`) | `tests/` | ✅     |
| 3      | Content-assertion sweep across the other 16 test modules           | `tests/`                                     | ✅     |
| DoD    | Validate batch                                                     | inline DoD criteria 1–2                      | ✅     |
| Thomas | Verify this batch                                                  | `skill:thomas`                               | ✅     |

**Verify:** `task test` → **fully green, zero collection errors** (first all-green gate). `task lint` → green.
**DoD Gate:** as Batch 1, criteria 1–2.
**Thomas Gate:** as Batch 1.

---

### Batch 6 — Docs, config prose, zero-D3 sweep

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | README.md full rewrite for the template identity                   | `README.md`                                  | ✅     |
| 2      | Taskfile/azure.yaml/pyproject comment & description prose sweep    | repo root (verified already clean from Batch 3) | ✅     |
| 3      | Zero-hit grep sweep (DoD criterion 3) + commit the conversion      | repo root, git                               | ✅     |
| DoD    | Validate batch                                                     | inline DoD criteria 1–3                      | ✅     |
| Thomas | Verify this batch                                                  | `skill:thomas`                               | ✅     |

**Verify:** `task test` + `task lint` → green. `grep -ri "d3\|initiative" src/ tests/ main.py Taskfile.yml azure.yaml README.md pyproject.toml` → zero hits. `git status` clean after commit.
**DoD Gate:** as Batch 1, criteria 1–3.
**Thomas Gate:** as Batch 1.

---

### Batch 7 — Final validation: global gate + witnessed live smoke

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | Run global verify (`task test` + `task lint`) — all green          | repo root                                    | ✅     |
| 2      | Live smoke: `task hosted:run` up on :8088, `task hosted:invoke` with the policy prompt returns the FG1 opening turn as a `request_info` pause, no errors | serving path | ✅     |
| 3      | Record smoke evidence (request/response excerpt) in `smoke-evidence.md` (deviation: lessons.md is reserved for 4-field lessons per skill:lessons-learned; evidence lives beside it); final commit | `plans/policy-report-agent-conversion/` | ✅     |
| DoD    | Validate batch                                                     | inline DoD criteria 1–4                      | ✅     |
| Thomas | Full plan sign-off                                                 | `skill:thomas`                               | ✅     |

**Verify:** global verify command from Execution Config → 0 failures; the live `/responses` payload visibly contains the FG1 framing + first-field turn. If Azure credentials fail: record output in `lessons.md`, mark item 2 `user-assisted-pending`, surface to the user — the plan is then complete EXCEPT this item and must say so.
**Environment pre-check (recorded 2026-07-22):** `.env` verified — the API key authenticates on the OpenAI data plane at the resource root `https://thiagoalmedeiros-4833-resource.services.ai.azure.com` (probe returned `DeploymentNotFound`, not 401). `AZURE_OPENAI_ENDPOINT` fixed to that root (the `/api/projects/...` form 404s) and `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-5-mini` set. **Resolved 2026-07-22:** the `gpt-5-mini` deployment (version 2025-08-07, GlobalStandard, capacity 50) was created via az CLI (`az cognitiveservices account deployment create` on `rg-thiagoalmedeiros-1229` / `thiagoalmedeiros-4833-resource`) and verified live — a one-shot `/openai/v1/chat/completions` call through the data-plane key returned a completion from `gpt-5-mini-2025-08-07`. No environment blockers remain for this batch's smoke.
**DoD Gate:** all four inline DoD criteria via a validation subagent.
**Thomas Gate:** Dispatch `skill:thomas` for the full-plan pass — re-runs the global verify command, reviews every section of `plan.md` to confirm all rows ✅, and issues the final **APPROVED / NOT APPROVED** verdict. The plan is not complete until **APPROVED**.
