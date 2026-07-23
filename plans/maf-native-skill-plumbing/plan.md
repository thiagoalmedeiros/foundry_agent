# Plan: Replace custom skill plumbing with MAF-native skill mechanisms

> Origin: user directive (2026-07-23) — "MAF already provides a skill mechanism to load
> skills; we should not use custom classes for that. Also field group parses." Verified
> against the installed `agent_framework` (1.0.0b260721): `FileSkillsSource` already
> auto-discovers `.py` files as skill scripts (`DEFAULT_SCRIPT_EXTENSIONS = (".py",)`,
> scan depth 2), and `SkillsProvider` exposes a native `run_skill_script` tool —
> `create_skills()` in `agents.py` even sets `disable_run_skill_script_approval=True`
> already. So the format skill's `validation/validate.py` is *advertised* to the model
> today, but calling it would raise "requires a runner": `SkillScriptRunner` is a
> Protocol only — MAF ships no concrete runner, and `create_skills()` configures none.
> This plan completes the native path and deletes the custom plumbing that duplicates it.
>
> Sequencing: execute AFTER `plans/chat-agent-checkpoint-persistence` finishes (its
> Batches 2–4 are pending). No shared files besides tests/conftest.py; keeping the two
> plans strictly sequential avoids interleaved test churn.

## Section 1 — What We Are Doing

1. **Make the skill's validation script natively runnable** — `skills/policy-report-format/validation/validate.py` gains a CLI entry point (`argv = [captured_values_json, groups_json]` → prints failing ids as JSON), and `create_skills()` gets a minimal `script_runner` (a small async subprocess function satisfying the `SkillScriptRunner` protocol — MAF ships none), so the already-advertised `run_skill_script` tool actually works.

2. **Rewire the Validation stage onto the native tool** — the validation agent calls `run_skill_script` through its mounted `SkillsProvider` instead of a custom per-run bound callable; `validate_document()` loses its `validation_tool` parameter, `ValidationExecutor`/`build_policy_report_workflow` lose their `validator` parameter, and the prompt instruction switches from `run_skill_validation` to the native tool.

3. **Delete the custom plumbing this replaces** — `src/foundry_agent/skill_validation.py` (custom importlib loader + `SkillValidator` Protocol + hand-bound tool), `src/foundry_agent/field_groups_parser.py` (dormant custom parser; live discovery already rides MAF progressive disclosure), and `src/foundry_agent/mechanical_checks.py` (dead — only its own test imports it), each with its dedicated test file, with surviving coverage migrated.

4. **Continuous lessons capture** — Lessons are automatically logged to `lessons.md` after every user correction and every agent mistake discovered during execution — without being asked.

---

## Section 2 — How We Are Doing It / What Is Out of Scope

## Execution Config

> This section is read by any executor before starting batch work. Do not skip it.

| Setting | Value |
| ------- | ----- |
| Per-batch verify command | `task test` → `task lint` |
| Global verify command | `task test` → `task lint` → live smoke (`task hosted:run` + `task hosted:invoke`, user-assisted fallback below) |
| Thomas validation | `enabled` |
| Definition of Done | inline — see `## Definition of Done` below |

### Execution rules (always active)

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately after any user correction, any non-obvious failure, or any recurring pattern discovered. Do not wait to be asked. Do not batch multiple lessons into one call.
2. **Status updates** — Every item must be `🔄` before handoff to review. Every item must be `✅` before the next batch starts. Never advance with a `⬜` item in a completed batch.
3. **Verify gate** — After each batch, run the per-batch verify command listed above. Invoke `skill:thomas` as a subagent with the batch's exact `**Verify:**` checklist. Do not mark items `✅` until Thomas returns a WITNESSED PASSING verdict.
4. **Global gate** — After all batches complete, run the global verify command. Invoke `skill:thomas` for a final full-plan validation pass before presenting results to the user.

## Definition of Done (inline criteria)

1. `task test` green — full offline suite, zero collection errors, with the three custom modules and their test files gone.
2. `task lint` green (`ruff check src/ tests/ main.py`).
3. `grep -rn "skill_validation\|field_groups_parser\|mechanical_checks\|run_skill_validation\|SkillValidator" src/ tests/ main.py` returns zero hits (plans/ exempt — history).
4. The native script path is witnessed working offline: a direct test drives the runner end-to-end (`run_skill_script` → subprocess → JSON verdict back).
5. Final batch: witnessed live smoke through `task hosted:run` / `task hosted:invoke` reaching the interview's opening turn. **User-assisted fallback:** if Azure credentials are invalid/expired, record the failure in `lessons.md`, mark the smoke user-assisted-pending, and surface it — never fake the verdict.

### Design decisions (locked during define — do not re-litigate during build)

- **Script CLI contract:** `python validate.py '<captured_values JSON>' '<groups JSON>'` → stdout is a JSON array of failing attribute ids, exit 0 (validation *findings* are data, not process failure). Malformed argv → nonzero exit with a one-line error on stderr, which the runner surfaces to the model so the agent can retry with corrected arguments. The pure `validate()` function stays; `__main__` only wraps it.
- **Runner shape:** one small module-level async function (e.g. `_run_python_skill_script(skill, script, args)`) using `sys.executable` + `asyncio.create_subprocess_exec`, working dir = the script's own directory, a hard timeout (~30s), capturing stdout/stderr. A function — not a class — satisfies the `SkillScriptRunner` Protocol; this is required glue, not replaceable plumbing. Passed as `FileSkillsSource(..., script_runner=...)` inside `create_skills()`.
- **Groups binding trust shift (accepted):** today the run's discovered groups are closure-bound into the tool; natively the model passes them as a JSON argument. Accepted because the validation agent already receives the full group scope in its prompt (`_all_groups_scope`), and the script fails loudly on malformed input rather than guessing. The workflow no longer holds any validation state.
- **Fail-fast (kept, minimally):** `create_policy_report_workflow()` keeps a one-line existence check that `FORMAT_SKILL_DIR/validation/validate.py` is a file, so a skill shipped without its script still fails at build time, not mid-interview. One `Path.is_file()` call, no loader, no Protocol.
- **Validation agent mounts the skills provider:** `create_validation_agent` gains the same `SkillsProvider` mount the discovery/elicitation agents use (constructed with the script runner). Its inline reference pack (`VALIDATION_PACK`) stays — the provider is mounted for the script tool, not to replace the inline content strategy.
- **Security stance unchanged:** the runner executes only scripts discovered inside this repository's `skills/` tree — same trust boundary as today's import-based execution. `skills/policy-report-format/validation/SECURITY.md` is updated to describe subprocess execution instead of in-process import.

### Implementation checklist

#### `skills/policy-report-format/validation/validate.py`
- Add `import json, sys` and an `if __name__ == "__main__":` block: parse `sys.argv[1]` (captured values) and `sys.argv[2]` (groups) as JSON, call `validate()`, `print(json.dumps(result))`; on bad argv print a one-line error to stderr and `sys.exit(2)`.
- Module docstring: execution is now via the skill's own `run_skill_script` tool (subprocess), not import; update the contract paragraph.

#### `skills/policy-report-format/validation/SECURITY.md`
- Update: script runs as a subprocess via the framework's script runner; same repo-trust stance.

#### `src/foundry_agent/agents.py`
- Add the `_run_python_skill_script` runner function (design decision above).
- `create_skills()`: pass `script_runner=_run_python_skill_script` to `FileSkillsSource`.
- `create_validation_agent()`: accept and mount the skills provider (mirroring `create_discovery_agent`'s signature shape).
- `validate_document()`: drop the `validation_tool` parameter and the `tools=[...]` ChatOptions entry — the tool now arrives via the mounted provider.

#### `src/foundry_agent/prompts.py`
- `VALIDATION_INSTRUCTIONS` step 1: replace "ALWAYS call the run_skill_validation tool" with the native call — name the skill, the script, and the exact two-argument JSON contract.

#### `src/foundry_agent/workflow.py`
- `ValidationExecutor`: drop `validator` field and `bind_skill_validation_tool` call; `_validate` calls the slimmed `validate_document`.
- `build_policy_report_workflow()`: drop the `validator` parameter.
- `create_policy_report_workflow()`: drop `load_skill_validator`; add the one-line script existence check; wire the provider into `create_validation_agent`.
- Remove `field_groups_parser` docstring references (module header + `DiscoveryExecutor` docstring).

#### Deletions
- `src/foundry_agent/skill_validation.py`, `src/foundry_agent/field_groups_parser.py`, `src/foundry_agent/mechanical_checks.py`.
- `tests/test_skill_validation.py`, `tests/test_field_groups_parser.py`, `tests/test_mechanical_checks.py`.

#### `tests/`
- `tests/conftest.py`: remove `VALIDATOR` and its `load_skill_validator` import; update every `build_policy_report_workflow(validator=VALIDATOR, ...)` call site (conftest helpers, `test_workflow.py`, `test_chat_agent.py`, `test_hosted_state.py`, `test_hosting.py` — enumerate via grep during build).
- `tests/test_cache_key.py`: check its `skill_validation` usage during build; rewire or drop the affected case.
- `tests/test_discovery.py`: remove any `field_groups_parser` imports/cases; keep the LLM-discovery coverage.
- New `tests/test_skill_script.py`: (a) direct `validate()` behavior cases migrated from `test_skill_validation.py` (placeholders, conditionals, title cap, enum, ordering); (b) CLI round-trip via subprocess — good argv → JSON verdict on stdout, exit 0; malformed argv → exit 2 + stderr message; (c) runner end-to-end — `_run_python_skill_script` against the real `FileSkillScript` discovered by `FileSkillsSource`, witnessing the advertised script actually executes and returns the verdict (DoD criterion 4).

### Validation strategy

Run after each batch:
```
task test
task lint
```

Global/final: the same two commands plus the live smoke (`task hosted:run`, then `task hosted:invoke`), with the user-assisted fallback recorded in the DoD.

### Out of scope

- **The elicitation skill and all reference content** — no skill *content* changes; only the validation script's entry point and SECURITY.md wording.
- **Inline reference packs** (`_skill_pack`, `INLINE_REFERENCE_INSTRUCTIONS`) — a deliberate cost optimization, not custom skill-loading machinery; untouched.
- **The checkpoint-persistence plan** (`plans/chat-agent-checkpoint-persistence`) — independent; its remaining batches run first.
- **`checkpoint_compat.py`** — unrelated to skill plumbing; governed by its own upstream-fix exit, untouched here.
- **Discovery behavior** — already MAF-native (progressive disclosure); only the dormant parser is removed, no change to the live path.

---

## Section 3 — Tracking List

### Batch 1 — Native script execution path

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | CLI entry point + docstring update in the skill's validation script | `skills/policy-report-format/validation/validate.py` | ⬜ |
| 2      | `_run_python_skill_script` runner + `script_runner=` wiring in `create_skills()` | `src/foundry_agent/agents.py` | ⬜ |
| 3      | SECURITY.md updated to the subprocess execution model | `skills/policy-report-format/validation/SECURITY.md` | ⬜ |
| 4      | New `tests/test_skill_script.py`: CLI round-trip + runner end-to-end (DoD criterion 4) | `tests/test_skill_script.py` | ⬜ |
| Thomas | Verify this batch | `skill:thomas` | ⛾ |

**Verify:** `task test` → `task lint` → both green; new script tests witnessed passing (CLI JSON round-trip, runner executes the discovered script). Existing suite untouched and green — the custom path still exists in this batch.
**Thomas Gate:** After the `Verify` command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 2 — Rewire the Validation stage onto the native tool

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | `create_validation_agent` mounts the provider; `validate_document` drops `validation_tool` | `src/foundry_agent/agents.py` | ⬜ |
| 2      | `VALIDATION_INSTRUCTIONS` step 1 rewritten to the native `run_skill_script` contract | `src/foundry_agent/prompts.py` | ⬜ |
| 3      | `ValidationExecutor` / `build_policy_report_workflow` drop `validator`; `create_policy_report_workflow` gains the one-line existence check | `src/foundry_agent/workflow.py` | ⬜ |
| 4      | Update every `validator=`/stub call site so the suite compiles and passes | `tests/conftest.py` + affected test files | ⬜ |
| Thomas | Verify this batch | `skill:thomas` | ⛾ |

**Verify:** `task test` → `task lint` → both green with the workflow no longer holding any validation state.
**Thomas Gate:** After the `Verify` command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 3 — Delete the custom plumbing

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | Delete `skill_validation.py` + migrate surviving cases into `test_skill_script.py`; delete `test_skill_validation.py` | `src/foundry_agent/`, `tests/` | ⬜ |
| 2      | Delete `field_groups_parser.py` + `test_field_groups_parser.py`; clean `test_discovery.py` and `workflow.py` docstring references | `src/foundry_agent/`, `tests/` | ⬜ |
| 3      | Delete `mechanical_checks.py` + `test_mechanical_checks.py` | `src/foundry_agent/`, `tests/` | ⬜ |
| 4      | Zero-reference sweep: DoD criterion 3 grep returns no hits | repo-wide | ⬜ |
| Thomas | Verify this batch | `skill:thomas` | ⛾ |

**Verify:** `task test` → `task lint` → both green; the DoD grep (`skill_validation|field_groups_parser|mechanical_checks|run_skill_validation|SkillValidator` over `src/ tests/ main.py`) returns zero hits.
**Thomas Gate:** After the `Verify` command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 4 — Final validation

| #      | Item                                               | File/Area                    | Status |
| ------ | -------------------------------------------------- | ----------------------------- | ------ |
| 1      | Run `task test` — full suite green                 | repo root                     | ⬜ |
| 2      | Run `task lint` — clean                             | repo root                     | ⬜ |
| 3      | Witnessed live smoke: `task hosted:run` + `task hosted:invoke` reach the opening elicitation turn (user-assisted fallback per DoD criterion 5) | manual | ⬜ |
| 4      | Full DoD review (criteria 1–5)                      | manual code review            | ⬜ |
| Thomas | Full plan sign-off | `skill:thomas` | ⛾ |

**Verify:** global verify command → 0 failures; live smoke witnessed (or user-assisted-pending recorded per the fallback).
**Thomas Gate:** Dispatch `skill:thomas` as a subagent for the full-plan validation pass. Thomas re-runs the global verify command, reviews every section of `plan.md` to confirm all rows are ✅, and issues a final **APPROVED** or **NOT APPROVED** verdict for the plan as a whole. The plan is not complete until this verdict is **APPROVED**.
