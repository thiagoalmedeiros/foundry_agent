# Plan: Global-pipeline workflow-build restructure (skill-driven, zero domain logic in code)

> Origin: `/agentic-sdlc:define` on 2026-07-23. Clarified to a global pipeline +
> LLM discovery + script-gate-plus-adequacy validation; **grill verdict SURVIVES**
> after the constraint was reframed from "better output" to *"a best-practices MAF
> template whose only per-segment change is the loaded skills + prompts."* The
> workflow must carry **zero domain-specific mechanisms**; the domain (groups,
> prompts, and now the validation script) lives entirely in the skill.

## Section 1 — What We Are Doing

1. **Move the validation script into the skill** — The format skill gains an executable resource (`skills/policy-report-format/validation/validate.py`) that presence-checks required fields for whatever domain the skill declares. The workflow stops owning any domain validation logic (`mechanical_checks.py` is retired as workflow code); swap the skill and its own validation travels with it.

2. **Replace deterministic discovery with an LLM Discovery agent** — A new Discovery agent reads the loaded format skill via `load_skill` / `read_skill_resource` and emits the groups + attributes (ids, required flags, adequacy) as structured output. This unwires `field_groups_parser.py` from the active path (kept dormant for the future sequential sibling). Rationale from the grill: the strict parser is very sensitive to skill markdown format, which is exactly what breaks the swap-the-skill portability story.

3. **Flatten per-group cycle into one global pipeline** — Discovery → one global Gap Analysis (all groups at once) → a single **agent-paced, skill-guided** batched multi-turn Elicitation → Validation (runs the skill's script via a tool **and** applies LLM adequacy) → loop back to Elicitation on failure → Assembler. Two **global** budgets (elicitation-turn cap, validation-reopen cap) replace the per-group `MAX_GROUP_TURNS` / `MAX_GROUP_ROUNDS`.

4. **Keep both serving paths and re-prove on Foundry** — `hosting.py`'s `HOSTED_AGENT_MODE=chat|workflow` and `WorkflowChatAgent` keep working against the new workflow; the plan ends with a witnessed live smoke through the hosted `/responses` chat path against the deployed `gpt-5-mini`.

5. **Continuous lessons capture** — Lessons are automatically logged to `lessons.md` after every user correction and every agent mistake discovered during execution — without being asked.

---

## Section 2 — How We Are Doing It / What Is Out of Scope

## Execution Config

> This section is read by any executor before starting batch work. Do not skip it.

| Setting | Value |
| ------- | ----- |
| Per-batch verify command | `task test` + `task lint` (batch-specific expected state noted per batch — the suite is red between Batch 2 and Batch 5 and first goes fully green at Batch 5) |
| Global verify command | `task test` + `task lint` + live smoke: `task hosted:run` (HOSTED_AGENT_MODE=chat) then `task hosted:invoke` / raw `/responses` curl |
| Thomas validation | `enabled` |
| Definition of Done | inline criteria — see `## Definition of Done` below |

### Execution rules (always active)

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately after any user correction, any non-obvious failure, or any recurring pattern discovered. Do not wait to be asked. Do not batch multiple lessons into one call.
2. **Status updates** — Every item must be `🔄` before handoff to review. Every item must be `✅` before the next batch starts. Never advance with a `⬜` item in a completed batch.
3. **Verify gate** — After each batch, run the per-batch verify command. Dispatch `skill:thomas` as a subagent with the batch's exact `**Verify:**` checklist. Do not mark items `✅` until Thomas returns a WITNESSED PASSING verdict.
4. **Global gate** — After all batches complete, run the global verify command. Invoke `skill:thomas` for a final full-plan validation pass before presenting results.

## Definition of Done (inline criteria)

1. `task test` green — entire offline suite (stubbed chat clients), zero collection errors.
2. `task lint` green (`ruff check src/ tests/ main.py`).
3. **Zero domain logic in the workflow** — `src/foundry_agent/` (workflow/agents/models wiring) contains no policy-specific rules, attribute lists, enums, or thresholds; the domain lives entirely in `skills/` + `prompts.py` instruction text. Verified by inspection + grep for domain tokens (`PA\d`, `Governance|Operational|Security|Compliance`, hardcoded field names) in the workflow/validation modules → zero hits.
4. Final batch only: witnessed live smoke — `task hosted:run` (chat mode) serves on :8088 and one `/responses` turn returns a valid **assistant-text** elicitation turn (not a silent `request_info` function call), no server error. **User-assisted fallback:** if Azure credentials/deployment are unavailable, record output in `lessons.md`, mark the item user-assisted-pending, and surface it — do not fake the verdict.

### Target design (authoritative for build — do not re-derive)

**Pipeline (graph API / `WorkflowBuilder`), replacing the per-group cycle:**

```
discovery ──▶ gap_analysis ──▶ elicitation ──▶ validation ──┬─(reopen: gaps remain, rounds left)──▶ elicitation
                                    ▲                        ├─(pass)──────────────────────────────▶ assembler
                                    └────────────────────────┘
```

**Discovery agent (new).** Reads the format skill (`load_skill` + `read_skill_resource`) and returns structured groups. Reuse/rename the existing `FieldGroups` / `FieldGroup` models (`models.py`) as the output schema — but populated by the agent, not the parser. The schema MUST still carry exact attribute IDs + `required` + `adequacy`, because the skill's validation script and the assembler template mapping depend on those IDs (grill residual: the contract moves into the output schema, it does not vanish). Emit a warning (not a raise) if discovery yields zero groups.

**Gap Analysis agent (global).** One call over the whole input + all discovered groups; returns every attribute's status (populated / missing / inferred) across all groups. Replaces the per-group `analyze_gaps`.

**Elicitation agent (agent-paced, skill-guided).** A single multi-turn conversation. The agent decides its own pacing from the elicitation skill's guidance (related fields at a time, not one-field-per-turn machinery and not a 30-field wall). Returns cumulative captured values each turn + a `conversation_complete` flag. Bounded by `MAX_ELICITATION_TURNS` (default 30, tunable).

**Validation agent (script-runner + adequacy).** Given a domain-neutral function-tool `run_skill_validation` that dynamically loads the format skill's `validation/validate.py` (via `importlib` from `FORMAT_SKILL_DIR`) and calls its `validate(captured_values, groups) -> list[missing_or_failing_ids]`. The agent invokes the tool for the deterministic presence result, then applies LLM adequacy judgment against the skill's rules, and returns `complete` + `missing_ids` + advisory findings. On `complete=false` with rounds left → back to elicitation with the specific gaps; else → assembler. Bounded by `MAX_VALIDATION_ROUNDS` (default 3, tunable). The tool is generic; the *logic* is the skill's script.

**Assembler agent.** Unchanged in spirit — emits the document per the skill's template from the captured values.

**Skill validation script contract** (`skills/policy-report-format/validation/validate.py`):
- Pure, importable, no side effects; a module-level `def validate(captured_values: dict[str, str], groups: list[dict]) -> list[str]` returning the ids of required attributes that are absent/placeholder for THIS domain.
- Carries the domain's presence rules that `mechanical_checks.py` used to hold (title ≤ 10 words, PA3 enum, placeholder scan, None-is-valid for PA9/PA15) — but as skill content, not workflow code.
- A `SECURITY.md` note (or header comment) documents the trusted-in-repo-skills posture: the runner imports and executes skill-provided code, acceptable because skills ship in this repo and `SkillsProvider` approvals are already disabled for the same reason.

### Implementation checklist

#### `skills/policy-report-format/validation/validate.py` (Batch 1)
- Author `validate(captured_values, groups)` porting `mechanical_checks.py`'s rules as domain content; header comment states the trusted-skill security posture.
- Optionally add a tiny `skills/_fixtures/` toy skill's `validate.py` later (Batch 5) to prove the runner is skill-agnostic.

#### `src/foundry_agent/skill_validation.py` (new, Batch 4)
- `run_skill_validation` function-tool: `importlib`-load `<FORMAT_SKILL_DIR>/validation/validate.py`, call its `validate(...)`, return the missing-id list. Domain-neutral; raises a clear error if the skill ships no `validate.py`.

#### `src/foundry_agent/agents.py` + `prompts.py` (Batches 2–4)
- New `create_discovery_agent` + discovery instructions (reads skill, emits groups). Rewrite gap-analysis instructions to global scope. Rewrite validation instructions to "call `run_skill_validation`, then judge adequacy." Keep all instruction text skill-driven and domain-neutral.
- `create_validation_agent` gains the `run_skill_validation` tool.

#### `src/foundry_agent/workflow.py` (Batch 4)
- New executors: `DiscoveryExecutor` (agent-backed, replaces parser call), global `GapAnalysisExecutor`, `ElicitationExecutor` (single conversation), `ValidationExecutor` (tool + adequacy), `AssemblerExecutor`. Remove the per-group loop, `MAX_GROUP_TURNS`, `MAX_GROUP_ROUNDS`, `Reclarify`/per-group `Run` routing. Add `MAX_ELICITATION_TURNS`, `MAX_VALIDATION_ROUNDS`. Rewire `build_policy_report_workflow` edges to the graph above.

#### `models.py` (Batch 2)
- Discovery output schema (reuse `FieldGroups`); add a global `GapReport` shape if the per-group one no longer fits; a `ValidationResult` carrying `missing_ids` from the script + adequacy verdict.

#### Retire / unwire (Batches 2 & 4)
- `field_groups_parser.py`: keep the file (dormant, documented "used by the sequential sibling"), remove its call from the workflow.
- `mechanical_checks.py`: delete as workflow code (its rules now live in the skill script); remove `test_mechanical_checks.py` or repoint it at the skill script.

#### `tests/` (Batch 5)
- Rewrite `conftest.py` fixtures for the global pipeline (discovered-groups stub, global gap report, single elicitation conversation). Rewrite `test_workflow.py` for the global graph + two budgets. Replace `test_field_groups_parser.py` discovery-path assertions with discovery-agent tests. Replace `test_mechanical_checks.py` with skill-validation-script + `run_skill_validation` tests. Sweep `test_gap_analysis`, `test_elicitation_skill`, `test_hardening`, `test_skill_mount`, `test_hosting`.

#### Docs (Batch 6)
- README: describe the global-pipeline workflow-build design, the skill-owns-validation pattern, and name the sequential sibling as future work. Sweep Taskfile/azure.yaml prose. Run the DoD-3 zero-domain-logic grep.

### Validation strategy

Run after each batch: `task test && task lint`. Batches 2–4 are expected-red in the specific shapes noted per batch (the suite can't be green until the tests are rewritten in Batch 5). Global gate (Batch 7): `task test && task lint`, then `task hosted:run` (chat mode) + a `/responses` turn returning assistant text.

### Out of scope

- **The sequential-orchestration sibling** — MAF `SequentialBuilder` variant that reintroduces deterministic code (the parser, script-replacing-agents). Explicitly deferred; this plan is the workflow-build sibling only.
- **Deleting `field_groups_parser.py`** — kept dormant for that sibling.
- **New domains / a second skill** — the toy fixture skill (Batch 5) exists only to prove the runner is skill-agnostic, not as a shipped domain.
- **Foundry redeploy** — `azd deploy` is `/ship`; this plan only witnesses a *local* hosted smoke. (Re-deploy happens after merge.)
- **Prompt-quality tuning** beyond the role rewrites; **dependency upgrades**; **`.env`** (user-owned).

---

## Section 3 — Tracking List

### Batch 1 — Skill owns its validation script

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | Author `validate(captured_values, groups)` porting mechanical rules as skill content | `skills/policy-report-format/validation/validate.py` | ✅ |
| 2      | Document trusted-in-repo-skill security posture (header/SECURITY note) | `skills/policy-report-format/validation/` | ✅ |
| 3      | Standalone check: import the script and run it over known-good and known-missing captured sets | scratch/manual | ✅ |
| DoD    | Validate batch                                                    | inline DoD criteria 2                        | ✅ |
| Thomas | Verify this batch                                                 | `skill:thomas`                               | ✅ |

**Verify:** `task lint` → green (no `src/` change). `task test` → still green (nothing unwired yet). `uv run python -c "import importlib.util, ..."` loads `validation/validate.py` and returns `[]` for a fully-populated set and the right missing ids for a gappy set.
**DoD Gate:** run inline DoD criterion 2 via a validation subagent; mark ✅ only on pass; on failure fix, log in `lessons.md`, re-run.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` to execute every check in this batch's `Verify` line and confirm witnessed passing output, and that all rows are ✅. Mark the Thomas row ✅ only on **APPROVED**.

---

### Batch 2 — Discovery agent + models (unwire the parser)

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | `create_discovery_agent` + discovery instructions (reads skill, emits groups) + `discover_groups` helper | `agents.py`, `prompts.py`  | ✅ |
| 2      | Discovery output schema — reused `FieldGroups` as-is; no new global model shapes needed this batch (gap/validation shapes deferred to Batch 3/4 where they're used) | `models.py` | ✅ |
| 3      | Unwire `field_groups_parser` from the workflow (DiscoveryExecutor is now agent-backed); file kept dormant with a STATUS docstring | `workflow.py`, `field_groups_parser.py` | ✅ |
| DoD    | Validate batch                                                    | inline DoD criteria 2                        | ✅ |
| Thomas | Verify this batch                                                 | `skill:thomas`                               | ✅ |

**Verify:** `task lint` → green. `uv run python -c "from foundry_agent.agents import create_discovery_agent"` imports. `task test` → **witnessed 158 passed / 0 failed** (deviation from the predicted "expected red": the change was cleanly additive — discovery source swapped parser→agent while the per-group downstream graph stays intact until Batch 4, and every existing test injects `field_groups=GROUPS` so no discovery call runs). 4 new `test_discovery.py` tests pass; `test_field_groups_parser.py` still green (parser dormant but exercised directly); zero import/collection/src-origin errors.
**DoD Gate / Thomas Gate:** as Batch 1.

---

### Batch 3 — Global gap analysis + agent-paced elicitation

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | Global Gap Analysis (one pass over all groups) + instructions — `create_global_gap_analysis_agent` / `analyze_gaps_globally` / `GLOBAL_GAP_ANALYSIS_INSTRUCTIONS` / `_all_groups_scope`, additive (old per-group path untouched) | `agents.py`, `prompts.py`, `models.py` | ✅ |
| 2      | Agent-paced, skill-guided batched Elicitation — new `ConversationTurn` model + `create_batched_elicitation_agent` / `open_\|continue_\|reopen_elicitation_conversation` / `BATCHED_ELICITATION_INSTRUCTIONS` / `_open_fields_clause`, additive | `agents.py`, `prompts.py`, `models.py` | ✅ |
| 3      | Elicitation skill guidance updated: EL4 now describes agent-paced whole-document batching (never one-at-a-time, never all-at-once); EL14 extended for multi-field turns | `skills/elicitation/references/question-loop.md` | ✅ |
| DoD    | Validate batch                                                    | inline DoD criteria 2                        | ✅ |
| Thomas | Verify this batch                                                 | `skill:thomas`                               | ✅ |

**Verify:** `task lint` → green. `uv run python -c "from foundry_agent import prompts, agents"` builds all packs/agents without OSError. `task test` → **witnessed 176 passed / 0 failed** (158 prior + 18 new tests in `test_global_gap_analysis.py`/`test_batched_elicitation.py`; additive as in Batch 2 — old per-group functions/instructions untouched, `workflow.py` untouched this batch, zero errors originating in `src/`).
**DoD Gate / Thomas Gate:** as Batch 1.

---

### Batch 4 — Validation (script tool + adequacy) & the global workflow graph

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | `run_skill_validation` function-tool: `load_skill_validator` (eager, fail-fast at build time) + `bind_skill_validation_tool` (cheap, per-run closure) | `src/foundry_agent/skill_validation.py` | ✅ |
| 2      | Validation agent = tool call + LLM adequacy (`validate_document`, new `VALIDATION_INSTRUCTIONS`); `mechanical_checks.py` retired to dormant (STATUS note, unwired, same pattern as the parser) | `agents.py`, `prompts.py`, `mechanical_checks.py` | ✅ |
| 3      | New global workflow graph: `Run`/`Analyzed`/`Elicited`/`Reclarify`/`Assemble`/`ConversationPause`; discovery→gap→elicit→validate→(reopen\|assemble); `MAX_ELICITATION_TURNS=30` / `MAX_VALIDATION_ROUNDS=3`; per-group loop + old budgets removed. Batch 2/3's transitional names renamed to their final permanent names (`analyze_gaps`, `create_gap_analysis_agent`, `create_elicitation_agent`); old per-group functions/`ElicitationTurn`/`_group_scope`+`_target_clause`+`_later_clause` deleted | `workflow.py`, `agents.py`, `prompts.py`, `models.py` | ✅ |
| 4      | Keep `hosting.py` chat + workflow modes wired to the new workflow; fixed `checkpoint_compat.py`'s coupling to the renamed `GroupTurn`→`ConversationPause` dataclass (a real gap the rename exposed, not anticipated in the original item scope) | `hosting.py`, `checkpoint_compat.py` | ✅ |
| DoD    | Validate batch                                                    | inline DoD criteria 2                        | ✅ |
| Thomas | Verify this batch                                                 | `skill:thomas`                               | ✅ |

**Verify:** `task lint` → green. Imports resolve; a stubbed build wires without raising. `run_skill_validation` returns the skill's missing-id list for a gappy capture set — witnessed against the REAL skill (`load_skill_validator(FORMAT_SKILL_DIR)`), not just a stub. Two full-graph smokes run live (stubbed agents, real skill validator): happy path (discovery→analysis→open→HITL pause→continue→close→validate→assemble, exactly 1 analysis call / 2 elicitation calls / 1 validation call) and the reopen/stale-finding regression (round 1 inadequate-with-finding → round 2 clean → the finding is absent from the final document, reproducing the exact regression the old per-group design guarded against). `task test` (`--continue-on-collection-errors`) → **112 passed, 8 failed, 7 collection errors** — every single one traced by hand to an old per-group symbol/signature/type-name string (`open_group_elicitation`, `ElicitationTurn`, `GroupTurn`, `MAX_GROUP_ROUNDS`, `CLOSING_TURN`, or `analyze_gaps` called with a single `FieldGroup` instead of a list); zero errors originate in `workflow.py`/`skill_validation.py`/`agents.py`/`prompts.py`/`models.py` themselves. DoD-3 grep (`PA\d|PC\d|PR\d|Governance|Operational|Compliance` in `workflow.py`+`skill_validation.py`) → zero hits; one real domain-token leak caught and fixed along the way (a concrete `PA1`/`PA2` example in the validation tool's own docstring — the text an LLM reads as the tool description — genericized to `{"<id>": "<value>"}`).
**DoD Gate / Thomas Gate:** as Batch 1.

---

### Batch 5 — Rewrite the test suite (first all-green gate)

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | `conftest.py` rebuilt: `ConversationTurn`-based turn fixtures (`OPEN_TURN`/`CLOSING_TURN`/`FOLLOW_UP_TURN`/`UNRESOLVED_TURN`), `make_elicitation_client` rebuilt for one whole-document conversation, new `VALIDATOR` (real skill, loaded once) for every workflow-building test | `tests/conftest.py` | ✅ |
| 2      | `test_workflow.py` fully rewritten for the global graph + two budgets (19→18 tests, same coverage shape); `test_skill_validation.py` NEW — formal pytest coverage for `run_skill_validation`/`load_skill_validator`/`bind_skill_validation_tool` against the REAL skill (`test_mechanical_checks.py` stays as dormant-module coverage, untouched); parser discovery-path tests already replaced by Batch 2's `test_discovery.py` | `tests/` | ✅ |
| 3      | Swept `test_hardening` (cross-group-capture tests RETIRED — the mechanism is structurally impossible in the global design, not merely untested; input-hardening tests kept), `test_gap_analysis`+`test_elicitation_skill` (consolidated with Batch 3's `test_global_gap_analysis.py`/`test_batched_elicitation.py`, which are deleted), `test_skill_mount`, `test_usage`, `test_checkpoint_compat`, `test_cache_key`, `test_hosting`, `test_hosted_state`, `test_chat_agent` (`validator=` added everywhere; per-group-cycling and gap-analysis-sees-later-replies assertions rewritten for the one-analysis-pass design); `test_models` needed no changes | `tests/` | ✅ |
| DoD    | Validate batch                                                    | inline DoD criteria 1–2                      | ✅ |
| Thomas | Verify this batch                                                 | `skill:thomas`                               | ✅ |

**Verify:** `task test` → **witnessed 170 passed, 0 failed, 0 collection errors** — fully green, first all-green gate. `task lint` → green.
**DoD Gate / Thomas Gate:** as Batch 1 (criteria 1–2).

---

### Batch 6 — Docs + zero-domain-logic sweep

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | README fully rewritten: global pipeline, LLM discovery agent (parser dormant), skill-owns-validation pattern (`skill_validation.py`), agent-paced elicitation, `HOSTED_AGENT_MODE=chat`, sequential sibling named as explicit future work, updated layout tree + termination policy + fork guide | `README.md` | ✅ |
| 2      | azure.yaml + `hosting.py`/`main.py` `AGENT_DESCRIPTION` swept — found and fixed two REAL stale strings still claiming "one-question-per-turn"/"one question per remaining gap" (served to clients, not just docs); Taskfile.yml/pyproject.toml checked, no stale prose found (`--group dev`/`[dependency-groups]` are unrelated uv/TOML terms) | `azure.yaml`, `src/foundry_agent/hosting.py`, `main.py` | ✅ |
| 3      | DoD-3 grep over `workflow.py`+`agents.py`+`skill_validation.py` → found and fixed one real hit (agents.py's own module docstring hardcoded "FG1-FG8"/"PA1-PA32" as an example — genericized since a domain fork would have different ranges); zero hits after | repo root | ✅ |
| DoD    | Validate batch                                                    | inline DoD criteria 1–3                      | ✅ |
| Thomas | Verify this batch                                                 | `skill:thomas`                               | ✅ |

**Verify:** `task test` → **witnessed 170 passed, 0 failed** (unchanged — doc/prose batch). `task lint` → green. Grep for domain tokens (`PA\d`, the 4 policy-type words, hardcoded field names) in `src/foundry_agent/workflow.py`, `agents.py`, `skill_validation.py` → **zero hits, witnessed after fixing the one real leak found** (agents.py docstring). Every README-referenced file path confirmed to exist on disk.
**Thomas re-verification (2026-07-23):** re-ran `task test` (170 passed/0 failed, exit 0, twice) and `task lint` (clean, exit 0) first-hand. Re-ran the domain-token grep: `workflow.py`/`agents.py` zero hits; `skill_validation.py` surfaced one incidental match on the bare word "Security" in its module docstring's security-posture note — inspected in context and confirmed it references code-execution trust (the required `validation/SECURITY.md`, which exists on disk), not the domain's policy-type enum. Judged not a DoD-3 violation. Verified all README markdown-links, layout-tree entries, and prose-referenced paths (25 total) exist on disk. **APPROVED.**
**DoD Gate / Thomas Gate:** as Batch 1 (criteria 1–3).

---

### Batch 7 — Final validation: global gate + witnessed live smoke

| #      | Item                                                              | File/Area                                   | Status |
| ------ | ----------------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | Global verify (`task test` + `task lint`) — all green             | repo root                                    | ✅ |
| 2      | Live smoke: `task hosted:run` (chat mode) up on :8088; a `/responses` turn returns an assistant-text elicitation turn, no server error | serving path | ✅ |
| 3      | Record smoke evidence in `plans/workflow-build-global-pipeline/smoke-evidence.md`; note whether Foundry redeploy is deferred to `/ship` | plan folder | ✅ |
| DoD    | Validate batch                                                    | inline DoD criteria 1–4                      | ✅ |
| Thomas | Full plan sign-off                                                | `skill:thomas`                               | ✅ |

**Verify:** global verify → **witnessed 170 passed, 0 failed** + `task lint` clean, both exit 0. Live smoke → HTTP 200, `output_text` assistant turn (not `request_info`), 28,751.7ms server-side, zero ERROR/Traceback lines across the full server log (real Azure `gpt-5-mini` calls, chat mode). Evidence recorded in `smoke-evidence.md`; Foundry redeploy explicitly deferred to `/ship` (out of scope for this plan per Section 2).
**DoD Gate:** all four inline DoD criteria via a validation subagent.
**Thomas Gate:** Dispatch `skill:thomas` for the full-plan pass — re-run global verify, confirm every row ✅, issue final **APPROVED / NOT APPROVED**. Plan is not complete until **APPROVED**.

**Thomas full-plan re-verification (2026-07-23):** independently re-ran every check — did not reuse the build step's results. `task test` → 170 passed/0 failed, exit 0. `task lint` → clean, exit 0. Fresh domain-token grep across `workflow.py`/`agents.py`/`skill_validation.py` → same result as Batch 6 (zero hits in the first two; one incidental "Security" match in `skill_validation.py`'s required trust-posture docstring, re-inspected and re-confirmed non-domain — `validation/SECURITY.md` still exists on disk). Fresh live smoke against a newly started `HOSTED_AGENT_MODE=chat` server on :8088: `/responses` POST → HTTP 200, `type: "message"`/`role: "assistant"`/`output_text` turn (FG1 opening batch, six fields), 272,565.5ms server-side, zero ERROR/Traceback lines in the fresh server log. Every tracking row across Batches 1–7 confirmed ✅ by direct inspection of `plan.md`. **APPROVED — plan complete.**
