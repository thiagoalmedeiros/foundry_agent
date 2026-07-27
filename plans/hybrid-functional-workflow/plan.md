# Plan: Flow 2 — Hybrid functional workflow with a deterministic validation gate

> A second, standalone MAF **functional-API** workflow that proves a point:
> agents own the generative steps, but a deterministic `.py` script acts as a
> **gate**. It reuses today's discovery / elicitation / authoring agents,
> replaces the LLM validation stage with a direct call to the skill's
> `validate.py`, and loops back to elicitation until the gate passes or a
> customizable cycle cap is hit. **Flow 1 (the existing graph workflow) and the
> hosted production path are left behavior-unchanged.**

## Section 1 — What We Are Doing

1. **Flow 2 module (functional workflow)** — Add `src/foundry_agent/workflow_functional.py`: a `@workflow` async function expressing the same pipeline as Flow 1 (discovery → per-group elicitation → validation → assembler), but written in the MAF functional API (`@workflow` / `@step` / `RunContext.request_info`) and reusing the existing agents and agent-helper functions unchanged. This is the "hybrid" showcase sibling to Flow 1's "pure agentic" graph workflow.

2. **Deterministic gate + bounded re-elicitation loop** — The validation step is **not** an LLM agent: it runs the mounted skill's `validation/validate.py` as a subprocess gate (contract: `python validate.py '<captured JSON>' '<groups JSON>'` → stdout JSON array of failing attribute IDs; empty = pass). On a non-empty result the loop re-opens **only the groups that own the failing IDs**, seeded with what is already captured, and re-runs the gate. It halts when the gate passes, or after `FLOW2_MAX_CYCLES` (env-customizable, **default 40**) cycles — then emits the document with the residual gaps in a non-blocking appendix. Captures are threaded as a structured `{attribute_id: value}` map so the gate needs no LLM to parse content.

3. **Showcase exposure, existing paths untouched** — A `create_hybrid_workflow()` factory (mirroring `create_report_workflow()`) and an additive DevUI switch let a user pick Flow 1 or Flow 2. All edits to shared modules (`agents.py`, `prompts.py`, `main.py`) are **additive only**; `workflow.py`, `chat_agent.py`, and the hosted entrypoint (`hosting.py`) are not modified, so Flow 1 and the production serving path stay byte-for-behavior identical.

4. **Continuous lessons capture** — Lessons are automatically logged to `lessons.md` after every user correction and every agent mistake discovered during execution — without being asked.

---

## Section 2 — How We Are Doing It / What Is Out of Scope

## Execution Config

> This section is read by any executor before starting batch work. Do not skip it.

| Setting | Value |
| ------- | ----- |
| Per-batch verify command | `task test` → `task lint` |
| Global verify command | `task test` → `task lint` |
| Thomas validation | `enabled` |
| Definition of Done | inline (see `## Definition of Done`) |

### Execution rules (always active)

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately after any user correction, any non-obvious failure, or any recurring pattern discovered. Do not wait to be asked. Do not batch multiple lessons into one call.
2. **Status updates** — Every item must be `🔄` before handoff to review. Every item must be `✅` before the next batch starts. Never advance with a `⬜` item in a completed batch.
3. **Verify gate** — After each batch, run `task test` → `task lint`. Because Thomas is enabled, invoke `skill:thomas` as a subagent with the batch's exact `**Verify:**` checklist. Do not mark items `✅` until Thomas returns a WITNESSED PASSING verdict.
4. **Global gate** — After all batches complete, run the global verify command, then invoke `skill:thomas` for a final full-plan validation pass before presenting results.

---

## Definition of Done

Inline criteria — every one must hold before the plan is complete:

- `task test` and `task lint` are green (witnessed, not assumed).
- **Flow 1 is behavior-unchanged**: `workflow.py`, `chat_agent.py`, `hosting.py` are not modified; every edit to `agents.py` / `prompts.py` / `models.py` is purely additive (new symbols; no changed signatures or behavior on existing ones). The pre-existing Flow 1 tests still pass unchanged.
- **No domain knowledge in Flow 2 code**: `workflow_functional.py` contains no attribute IDs (`PAn`), enums, thresholds, or validation rules — those stay in the skill and in `prompts.py` vocabulary (AGENTS.md invariant).
- **The gate carries no LLM**: the validation step invokes `validate.py` as a subprocess directly (no agent, no `run_skill_script` tool call).
- **The loop terminates**: a stubborn/unsatisfiable field cannot hang the interview — the cap (`FLOW2_MAX_CYCLES`, default 40) forces exit with a residual-gap appendix, proven by a test.

---

### Key API facts (verified against the installed framework)

- `agent-framework 1.11.0` exports `workflow`, `step`, `RunContext`, `get_run_context`, `FunctionalWorkflow` (confirmed via `.venv` introspection). The functional API is officially **experimental** ("subject to change or removal") — acceptable because Flow 2 is a showcase sibling off the production path; pin the version, do not deepen coupling.
- **HITL replay semantics (load-bearing):** `ctx.request_info()` suspends; on resume via `.run(responses={request_id: value})` the workflow **re-executes from the top**, and `@step`-decorated calls return cached results instead of re-running. Therefore **every agent call in Flow 2 must be wrapped in `@step`** (or a `@step` helper) so resumes do not re-bill the LLM, and every `request_info` must use a **stable, deterministic `request_id`** (derive from group index + turn index) so replay matches. The gate itself is a **plain** function (cheap, deterministic — correct to re-run on resume against the latest captures).
- Offline tests drive a functional workflow the same way as Flow 1: `wf.run("hi")` → `result.get_request_info_events()` → `wf.run(responses={req.request_id: answer})`. Stub clients in `tests/conftest.py` (`StubChatClient`, `make_stub_client`, `make_elicitation_client`) inject canned structured outputs — reuse them; never add a test needing live credentials.

### Implementation checklist

#### `src/foundry_agent/workflow_functional.py` (new)
- `@workflow`-decorated `async def hybrid_report_workflow(message, ctx: RunContext) -> str` (or a builder returning a `FunctionalWorkflow`, whichever mirrors `build_report_workflow`'s injectable shape for tests).
- Reuse `discover_groups`, `open_group_conversation`, `continue_group_conversation`, `author_document` from `agents.py` — no changes to them.
- Thread a structured `captured: dict[str, str]` map alongside `content`, built from each group's `ConversationTurn.captured` (CLOSED values). This is the gate's first argument.
- Per-group elicitation expressed as a `while not turn.conversation_complete` loop with `ctx.request_info(...)` inside; wrap each agent turn in a `@step` helper; use `request_id=f"g{group_idx}:t{turn_idx}"`.
- After the first full walk, the **gate loop**: `for cycle in range(MAX_CYCLES)`: `failing = run_validation_gate(captured, groups)`; if empty → break; else re-open only `groups_owning(failing, groups)` (where `set(group.attribute_ids) & set(failing)`), seeded with `content`/`captured`, then continue.
- `FLOW2_MAX_CYCLES = int(os.environ.get("FLOW2_MAX_CYCLES", "40"))`.
- On cap exhaustion, build a non-blocking appendix from the still-failing IDs (reuse `build_appendix` from `workflow.py` if it imports cleanly without side effects, else a Flow 2-local equivalent) and append to the assembled document.
- `create_hybrid_workflow(discovery_cache=None)` factory with live agents (mirror `create_report_workflow`); plus an injectable form (agents + `field_groups`) for offline tests (mirror `build_report_workflow`).

#### `src/foundry_agent/agents.py` (additive only)
- Add `async def run_validation_gate(captured: dict[str, str], groups: list[FieldGroup]) -> list[str]`: resolve the format skill's `FileSkillScript` (via a `FileSkillsSource` over `FORMAT_SKILL_DIR`, or the known `FORMAT_SKILL_DIR / VALIDATION_SCRIPT_NAME` path) and run it through the existing `_run_python_skill_script` runner — **no agent, no LLM**. Parse the JSON array; a non-list/error result raises so the harness fails loudly rather than treating an error string as "all passing".
- Inspect the installed `FileSkillsSource` API first for a native "run a discovered script" entry point (AGENTS.md: prefer MAF-native, don't duplicate plumbing); reuse `_run_python_skill_script` as the runner either way.
- Do **not** touch `create_validation_agent` / `validate_document` — those belong to Flow 1.

#### `src/foundry_agent/prompts.py` (additive only, if needed)
- If targeted re-elicitation needs a "focus on these still-missing points" clause, add a new prompt-builder function; do not change existing ones (Flow 1 must keep calling them unchanged).

#### `src/foundry_agent/main.py` (additive only)
- Add a `--functional` (or `--flow2`) flag and a `create_hybrid_agent()` that serves Flow 2 via `WorkflowChatAgent` (same wrapper Flow 1 uses). Default behavior (no flag) is unchanged.

#### `tests/test_workflow_functional.py` (new)
- Reuse `make_stub_client` / `make_elicitation_client` fixtures.
- Happy path: discovery → elicit all groups → gate passes first try → assembles a document (no `request_info` after close).
- Gate-fail-then-pass: gate returns a failing ID once → workflow re-opens only the owning group → next gate passes → document assembled, no appendix.
- Cap backstop: gate always returns a failing ID → workflow stops after `FLOW2_MAX_CYCLES` (set a tiny cap via env/monkeypatch) and emits the residual-gap appendix. **This is the termination proof.**
- Gate contract: `run_validation_gate` is called with the structured capture map and returns the script's IDs, exercising the real `validate.py` subprocess (no stubbed LLM in the gate).
- Negative assertion: `workflow_functional.py` contains no `PAn`/threshold literals (guard the domain-free invariant).

### Validation strategy

Run after each batch:
```
task test
task lint
```

### Out of scope

- **Hosted/production serving of Flow 2 + checkpoint parity** — `hosting.py`, `chat_agent.py`, `checkpoint_compat.py` are not touched; the hosted default stays Flow 1. Serving Flow 2 in production (and its functional-API checkpoint/replay behavior under the host) is a deferred follow-up, not this plan.
- **Any change to Flow 1 behavior** — the graph workflow, its validation agent, and its LLM adequacy/advisory findings are left as-is.
- **Changing `validate.py`'s contract or the skill's rules** — the gate script and what it considers valid (including any "unavailable" escape) are the skill author's domain; Flow 2 reuses the existing 2-argument contract verbatim. No `@step` on the gate.
- **LLM adequacy / advisory (PC/PR) findings in Flow 2** — dropped by design; the gate is purely deterministic. That difference from Flow 1 is the point being proven.
- **Doc sync (ARCHITECTURE/README/AGENTS)** — handled at `/ship` via `skill:docs-sync`, not during build batches.

---

## Section 3 — Tracking List

### Batch 1 — Flow 2 skeleton (happy path, no gate loop)

| #      | Item                                                        | File/Area                                   | Status |
| ------ | ----------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | `@workflow` fn: discovery → walk all groups → assemble      | `src/foundry_agent/workflow_functional.py`  | ✅     |
| 2      | Thread structured `captured: dict[str,str]` + `@step` turns | `src/foundry_agent/workflow_functional.py`  | ✅     |
| 3      | `create_hybrid_workflow()` + injectable test form           | `src/foundry_agent/workflow_functional.py`  | ✅     |
| 4      | Offline happy-path test (stub clients → document)           | `tests/test_workflow_functional.py`         | ✅     |
| DoD    | Validate batch against inline DoD                           | `## Definition of Done`                     | ✅     |
| Thomas | Verify this batch                                           | `skill:thomas`                              | ✅     |

**Verify:** `task test` → `task lint` → new happy-path test green; all pre-existing tests still green (Flow 1 untouched).
**DoD Gate:** Invoke a validation subagent against this batch's output using the `## Definition of Done` criteria (focus: Flow 1 untouched, no domain literals in the new module, agent calls `@step`-wrapped). Mandatory. Mark the DoD row ✅ only after every criterion passes; on any failure, fix it, log the correction in `lessons.md`, and re-run the gate.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` as a subagent to execute this batch's `Verify` line itself and confirm witnessed passing output, and to confirm all this batch's rows are ✅ in `plan.md`. Mark the Thomas row ✅ only on an **APPROVED** verdict.

---

### Batch 2 — Deterministic gate + bounded re-elicitation loop

| #      | Item                                                          | File/Area                                   | Status |
| ------ | ------------------------------------------------------------ | ------------------------------------------- | ------ |
| 1      | `run_validation_gate(captured, groups)` (subprocess, no LLM) | `src/foundry_agent/agents.py` (additive)    | ✅     |
| 2      | Gate loop + targeted re-elicit of owning groups              | `src/foundry_agent/workflow_functional.py`  | ✅     |
| 3      | `FLOW2_MAX_CYCLES` cap (default 40) + residual-gap appendix  | `src/foundry_agent/workflow_functional.py`  | ✅     |
| 4      | Tests: fail→re-elicit→pass, cap-backstop, gate-contract      | `tests/test_workflow_functional.py`         | ✅     |
| DoD    | Validate batch against inline DoD                            | `## Definition of Done`                     | ✅     |
| Thomas | Verify this batch                                            | `skill:thomas`                              | ✅     |

**Verify:** `task test` → `task lint` → gate loop tests green, cap-backstop test proves termination (tiny cap → appendix), real `validate.py` subprocess exercised.
**DoD Gate:** Validation subagent confirms: gate carries no LLM/`run_skill_script`; loop terminates via the cap; `validate.py` contract unchanged; no domain literals in workflow code. Mandatory; same fix-log-rerun rule on failure.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` to execute the `Verify` line itself and confirm witnessed passing output plus all rows ✅. Thomas row ✅ only on **APPROVED**.

---

### Batch 3 — Showcase exposure + guardrails

| #      | Item                                                        | File/Area                                   | Status |
| ------ | ----------------------------------------------------------- | ------------------------------------------- | ------ |
| 1      | Additive `--functional` DevUI switch + `create_hybrid_agent`| `src/foundry_agent/main.py` (additive)      | ✅     |
| 2      | Negative-assertion test: Flow 1 + hosted imports unchanged  | `tests/test_workflow_functional.py`         | ✅     |
| 3      | Domain-free guard test on `workflow_functional.py`          | `tests/test_workflow_functional.py`         | ✅     |
| DoD    | Validate batch against inline DoD                           | `## Definition of Done`                     | ✅     |
| Thomas | Verify this batch                                           | `skill:thomas`                              | ✅     |

**Verify:** `task test` → `task lint` → DevUI entity constructs offline without live calls; guard tests green; `python -m foundry_agent.main --functional --help` parses.
**DoD Gate:** Validation subagent confirms `main.py` default path is unchanged (Flow 1 still the no-flag default) and the domain-free guard holds. Mandatory; same fix-log-rerun rule.
**Thomas Gate:** Dispatch `skill:thomas` to execute the `Verify` line and confirm witnessed passing output plus all rows ✅. Thomas row ✅ only on **APPROVED**.

---

### Batch 4 — Final validation

| #      | Item                                                                 | File/Area           | Status |
| ------ | -------------------------------------------------------------------- | ------------------- | ------ |
| 1      | Run `task test` → `task lint` — all suites green                     | repo root           | ✅     |
| 2      | Manual review: DoD criteria all hold (Flow 1 unchanged, domain-free) | manual code review  | ✅     |
| 3      | Runtime smoke: drive Flow 2 offline through fail→re-elicit→pass & cap | `tests/…functional` | ✅     |
| DoD    | Full inline-DoD sign-off                                             | `## Definition of Done` | ✅  |
| Thomas | Full plan sign-off                                                   | `skill:thomas`      | ✅      |

**Verify:** `task test` → `task lint` → 0 failures; the gate-loop smoke path shows a failing gate re-opening only the owning group, then passing (or capping into the appendix).
**DoD Gate:** Validation subagent runs every `## Definition of Done` criterion and reports pass/fail per criterion. Mandatory; the plan is not done until all pass.
**Thomas Gate:** Dispatch `skill:thomas` for the full-plan validation pass — re-run `task test` → `task lint`, review every section of `plan.md` to confirm all rows are ✅, and issue a final **APPROVED** / **NOT APPROVED** verdict. The plan is not complete until **APPROVED**.
