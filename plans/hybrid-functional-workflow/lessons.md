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

### [2026-07-25] — Functional-workflow request_info must live inside a @step
**Context:** Building Flow 2 (MAF functional API, agent-framework 1.11.0) with multi-pause per-group elicitation; verified resume behavior against `_functional.py` source plus a standalone probe.
**Mistake:** The first design put `ctx.request_info(...)` in the workflow body (a plain helper). On the *second* resume the workflow replays from the top and re-hits the *first* pause, but `run(responses=...)` **replaces** the response map (`_set_responses`, only the newest reply) instead of accumulating — so the earlier pause is no longer answered and re-suspends, and the walk never advances past group 0.
**Rule:** Put each `request_info` **inside** the `@step` that consumes its reply. Once answered, the whole step is cached and replay short-circuits it before re-reaching the suspend point, so a resume only needs the single newest response. Use stable `request_id`s (`g<group>:t<turn>`). `WorkflowInterrupted` is a `BaseException`, so it is exempt from the step's `except Exception` — request_info inside `@step` is fully supported.
**Applies to:** `src/foundry_agent/workflow_functional.py` (any functional-API HITL loop)

### [2026-07-25] — Flow 2's deterministic gate enforces validate.py's rules literally
**Context:** Wiring the deterministic gate into Flow 2 and reusing conftest-style captured values in the tests.
**Mistake:** Carried `PA3="Security"` (a value Flow 1's LLM-stub validation happily accepted) as a happy-path captured value. Flow 2's gate runs the *real* `validate.py`, where PA3 is a closed-value "report status" ∉ {draft, under review, approved, closed} — so the gate failed PA3 and the "happy path" silently entered the re-elicitation loop instead of passing (assertions still passed for the wrong reason, running the full cap loop).
**Rule:** For Flow 2 (and any deterministic-gate path), captured test values must satisfy `validate.py`'s actual rules — sanctioned closed-value fields (PA3 status, PA17 disposition), no placeholders, every required attribute present. Never reuse Flow-1 LLM-stub values as if a script would accept them; a happy-path Flow 2 test should also assert the appendix is *absent*.
**Applies to:** `tests/test_workflow_functional.py`, `src/foundry_agent/agents.py::run_validation_gate`

### [2026-07-25] — Render Flow 2 content from the authoritative map, don't fold incrementally
**Context:** The gate loop re-opens a group across cycles; each pass captures that group's values again.
**Mistake:** Batch 1 appended a `## Captured values` block per group into a growing `content` string. Under the re-elicitation loop that stacks a fresh duplicate block every cycle, and the assembler then sees both the stale and the corrected value for a re-elicited attribute.
**Rule:** Keep a single authoritative `{attribute_id: value}` map and render content from it on demand (`_render_content`) for every group open and for assembly — never append captured blocks incrementally once a loop can revisit a group.
**Applies to:** `src/foundry_agent/workflow_functional.py` (`_render_content`, the gate loop)

### [2026-07-27] — Expose a functional workflow via .as_agent(), not WorkflowChatAgent
**Context:** Batch 3 wiring a `--functional` DevUI switch; the plan tentatively said "serve via WorkflowChatAgent (same wrapper Flow 1 uses)."
**Mistake:** `WorkflowChatAgent` is typed for the graph `Workflow` and built around its checkpoint-based resume — the wrong wrapper for a `FunctionalWorkflow` (top-replay + in-memory step cache), and adapting it would mean editing `chat_agent.py`, which the plan's Out of Scope forbids.
**Rule:** Expose a `FunctionalWorkflow` through its native `.as_agent()` → `FunctionalWorkflowAgent`, which DevUI's `serve(entities=[...])` accepts. One workflow instance backs that agent, so per-conversation isolation / hosted checkpoint parity is a separate (deferred) concern — don't hack it into the graph chat wrapper.
**Applies to:** `src/foundry_agent/main.py::create_hybrid_agent`
