# Plan: Dead-code removal with git rollback baseline

## Section 1 — What We Are Doing

1. **Git safety net** — Initialize a git repository in the project root and record a baseline commit of the current working state, so every deletion in this plan is reversible with a single `git revert`/`git checkout`. Secrets (`.env`) must be verifiably untracked before the first commit.

2. **Dormant module removal** — Delete the three production-unreachable modules identified by the 2026-07-23 dead-code review — `mechanical_checks.py` (superseded by the skill-owned validator), `field_groups_parser.py` (dormant, only referenced from a docstring), `spike_hitl.py` (completed spike) — together with their test files and the `devui:spike` Taskfile target. This removes ~660 lines of custom plumbing that contradicts the MAF-native direction of the codebase.

3. **Live-code cleanup in `workflow.py`** — Remove the never-read `elicitation_turns` state field from the `Run` dataclass and rewrite the docstring paragraph that still points at the deleted `field_groups_parser` module. Checkpoint compatibility is the one real risk here and is verified explicitly.

4. **Witnessed validation and closing commit** — Prove via the full test suite, lint, and a repo-wide reference grep that nothing depended on the deleted code, then commit the deletions on top of the baseline.

5. **Continuous lessons capture** — Lessons are automatically logged to `lessons.md` after every user correction and every agent mistake discovered during execution — without being asked.

---

## Section 2 — How We Are Doing It / What Is Out of Scope

## Execution Config

> This section is read by any executor before starting batch work. Do not skip it.
> Config chosen autonomously from the repo's Taskfile (session was non-interactive); adjust before `/build` if desired.

| Setting | Value |
| ------- | ----- |
| Per-batch verify command | `task test` → `task lint` |
| Global verify command | `task test` → `task lint` → `grep -rn "mechanical_checks\|field_groups_parser\|spike_hitl" src/ tests/ main.py Taskfile.yml` returns nothing |
| Thomas validation | `enabled` |
| Definition of Done | inline criteria (see below) |

### Definition of Done (inline criteria)

1. A baseline commit exists that predates every deletion; `git ls-files` shows `.env` is untracked (`.env.example` may be tracked).
2. `src/foundry_agent/mechanical_checks.py`, `src/foundry_agent/field_groups_parser.py`, `src/foundry_agent/spike_hitl.py`, `tests/test_mechanical_checks.py`, `tests/test_field_groups_parser.py`, `tests/test_spike_hitl.py`, and the `devui:spike` Taskfile target no longer exist.
3. `elicitation_turns` is gone from `workflow.py` **or** was deliberately kept with a logged lesson explaining the checkpoint-compat blocker.
4. No tracked file references the deleted modules (global grep clean).
5. `task test` passes with zero failures and `task lint` is clean.
6. The deletions are committed on top of the baseline; `git diff <baseline>..HEAD --stat` shows only the intended deletions and edits.

### Execution rules (always active)

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately after any user correction, any non-obvious failure, or any recurring pattern discovered. Do not wait to be asked. Do not batch multiple lessons into one call.
2. **Status updates** — Every item must be `🔄` before handoff to review. Every item must be `✅` before the next batch starts. Never advance with a `⬜` item in a completed batch.
3. **Verify gate** — After each batch, run the per-batch verify command listed above. If Thomas is enabled, invoke `skill:thomas` as a subagent with the batch's exact `**Verify:**` checklist. Do not mark items `✅` until Thomas returns a WITNESSED PASSING verdict.
4. **Global gate** — After all batches complete, run the global verify command. If Thomas is enabled, invoke `skill:thomas` for a final full-plan validation pass before presenting results to the user.

---

### Implementation checklist

#### Repo root (git baseline)
- Inspect `hosted.env` and `.env.example` for secret-looking values (keys, tokens, connection strings). `main.py` documents `hosted.env` as non-secret deployment config; verify that claim before letting it into the commit. Extend `.gitignore` if anything looks secret.
- `git init`, `git add -A`, baseline commit: `chore: baseline before dead-code removal`.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

#### Deletions (no source edits needed)
- `src/foundry_agent/mechanical_checks.py` + `tests/test_mechanical_checks.py` — module is imported by no src code; its rules live in `skills/policy-report-format/validation/validate.py` executed via `skill_validation.run_skill_validation`.
- `src/foundry_agent/field_groups_parser.py` + `tests/test_field_groups_parser.py` — only non-test reference is a docstring mention in `workflow.py` (cleaned in Batch 3).
- `src/foundry_agent/spike_hitl.py` + `tests/test_spike_hitl.py` — reachable only via `task devui:spike`.

#### `Taskfile.yml`
- Remove the `devui:spike` target (lines 32–35) entirely; leave `otel:up`/`otel:down` untouched — `otel_collector.py` is live dev tooling.

#### `src/foundry_agent/workflow.py`
- Remove `elicitation_turns: int = 0` from the `Run` dataclass (line 146). Neighbouring fields (`validation_rounds`, `unresolved_ids`, `advisory`) are live — do not touch them.
- Rewrite the docstring paragraph around line 208 that says the strict parser lies "dormant in `~foundry_agent.field_groups_parser`" — after deletion that sentence points at nothing. State instead that group discovery is LLM-driven via `agents.discover_groups`.
- **Checkpoint-compat risk:** `Run` rides in checkpoint payloads (`checkpoint_compat.py` allowlists it). If MAF's restore path passes a stored `elicitation_turns` key as a kwarg to the slimmed dataclass, restore raises `TypeError`. The executor must witness `tests/test_checkpoint_compat.py`, `tests/test_hosted_state.py`, and `tests/test_chat_agent.py` passing after the removal. If restore of old payloads breaks, revert the field removal, keep `elicitation_turns`, and log the lesson — the other deletions stand regardless.

### Validation strategy

Run after each batch:
```
task test
task lint
```

Global gate additionally requires the reference grep from Execution Config to return nothing.

### Out of scope

- **`otel_collector.py`** — live via `task otel:up`; its flagged methods are `http.server` framework overrides, not dead code. No changes.
- **`models.py` schema surface** — `Severity.BLOCKING`, `Finding.severity`, `GapReport.classification` are LLM structured-output contract; removing them would break output validation. No changes.
- **MAF-native refactors beyond deletion** — converting anything else to framework mechanisms is separate work; this plan only removes what is already dead.
- **Docs sync (`README.md` etc.)** — run `/docs-sync` after merge if the deleted modules are mentioned; not part of this plan.
- **Remote/GitHub setup** — the user asked for local rollback capability only; no remote, no push.

---

## Section 3 — Tracking List

### Batch 1 — Git baseline (the rollback point)

| #      | Item                                                                 | File/Area    | Status |
| ------ | -------------------------------------------------------------------- | ------------ | ------ |
| 1      | `Verify .gitignore coverage; inspect hosted.env for secrets`          | `.gitignore` | ✅     |
| 2      | `git init in project root`                                            | repo root    | ✅     |
| 3      | `Baseline commit of current state (chore: baseline before dead-code removal)` | repo root    | ✅     |
| DoD    | Validate batch (DoD criteria 1)                                       | inline DoD   | ✅     |
| Thomas | Verify this batch                                                     | `skill:thomas` | ✅ (witnessed via /verify, user accepted gate) |

**Verify:** `git log --oneline` → exactly one commit; `git status --porcelain` → empty; `git ls-files | grep -x "\.env"` → no output.
**DoD Gate:** Run inline DoD criterion 1 against this batch's output using a validation subagent. This step is **mandatory and cannot be skipped**. Mark the DoD row ✅ only after the subagent confirms it passes. If it fails, fix the failure, log the correction in `lessons.md`, and re-run the gate before proceeding.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 2 — Delete dormant modules, tests, and Taskfile target

| #      | Item                                                      | File/Area                                                        | Status |
| ------ | ---------------------------------------------------------- | ---------------------------------------------------------------- | ------ |
| 1      | `Delete mechanical_checks.py + its test`                   | `src/foundry_agent/mechanical_checks.py`, `tests/test_mechanical_checks.py` | ✅     |
| 2      | `Delete field_groups_parser.py + its test (+ obsolete cross-test in test_discovery.py)` | `src/foundry_agent/field_groups_parser.py`, `tests/test_field_groups_parser.py`, `tests/test_discovery.py` | ✅     |
| 3      | `Delete spike_hitl.py + its test`                          | `src/foundry_agent/spike_hitl.py`, `tests/test_spike_hitl.py`    | ✅     |
| 4      | `Remove devui:spike target`                                | `Taskfile.yml`                                                    | ✅     |
| DoD    | Validate batch (DoD criterion 2)                           | inline DoD                                                        | ✅     |
| Thomas | Verify this batch                                          | `skill:thomas`                                                    | ✅     |

**Verify:** `task test` → all remaining tests green (expect ~3 fewer test files collected); `task lint` → clean; `grep -rn "mechanical_checks\|spike_hitl" src/ tests/ main.py Taskfile.yml` → no hits; `grep -rn "field_groups_parser" src/ tests/ main.py Taskfile.yml` → only the `workflow.py` docstring hit (removed in Batch 3).
**DoD Gate:** Run inline DoD criterion 2 using a validation subagent. Mandatory; on failure fix, log to `lessons.md`, re-run.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 3 — workflow.py cleanup (checkpoint-sensitive)

| #      | Item                                                                  | File/Area                          | Status |
| ------ | ---------------------------------------------------------------------- | ---------------------------------- | ------ |
| 1      | `Remove elicitation_turns field from Run dataclass`                     | `src/foundry_agent/workflow.py:146` | ✅     |
| 2      | `Rewrite docstring referencing deleted field_groups_parser`             | `src/foundry_agent/workflow.py:~208` | ✅     |
| 3      | `Witness checkpoint-compat tests + NEW legacy-payload regression test (checkpoints pickle state — restore never calls __init__, so removal is safe by construction)` | `tests/test_checkpoint_compat.py`, `tests/test_hosted_state.py`, `tests/test_chat_agent.py` | ✅     |
| DoD    | Validate batch (DoD criterion 3)                                        | inline DoD                          | ✅     |
| Thomas | Verify this batch                                                       | `skill:thomas`                      | ✅     |

**Verify:** `task test` → all green, explicitly including the three checkpoint/state test files; `task lint` → clean; `grep -rn "field_groups_parser\|elicitation_turns" src/ tests/ main.py` → no hits except `tests/test_checkpoint_compat.py`'s legacy-payload regression test, which names the removed field on purpose.
**DoD Gate:** Run inline DoD criterion 3 using a validation subagent. Mandatory; on failure fix, log to `lessons.md`, re-run.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 4 — Final validation and closing commit

| #      | Item                                                            | File/Area   | Status |
| ------ | ---------------------------------------------------------------- | ----------- | ------ |
| 1      | `Global reference grep — zero hits for all three deleted modules` | repo root   | 🔄     |
| 2      | `Run task test + task lint (global gate)`                        | repo root   | 🔄     |
| 3      | `Commit deletions (chore: remove dead code — mechanical_checks, field_groups_parser, spike_hitl)` | repo root   | 🔄     |
| DoD    | Validate full plan (DoD criteria 1–6)                            | inline DoD  | ⬜     |
| Thomas | Full plan sign-off                                                | `skill:thomas` | ⛾   |

**Verify:** Global verify command from Execution Config → 0 test failures, lint clean, grep silent; `git log --oneline` shows baseline + deletion commits; `git diff <baseline>..HEAD --stat` shows only the six deleted files, `Taskfile.yml`, `workflow.py`, and any `.gitignore` addition.
**DoD Gate:** Run all six inline DoD criteria using a validation subagent, reported pass/fail per criterion. Mandatory; on any failure fix, log to `lessons.md`, re-run.
**Thomas Gate:** Dispatch `skill:thomas` as a subagent for the full-plan validation pass. Thomas re-runs the global verify command, reviews every section of `plan.md` to confirm all rows are ✅, and issues a final **APPROVED** or **NOT APPROVED** verdict for the plan as a whole. The plan is not complete until this verdict is **APPROVED**.
