# Plan: Flow 2 chat serving path (no DevUI approval panel)

> DevUI renders a `FunctionalWorkflow` as an **agent** (it has no `executors`), so
> its `request_info` pauses surface as an "Approval Required" function-call panel
> instead of a chat. Flow 1 avoids this with `WorkflowChatAgent`, which turns each
> pause into plain assistant text. This plan gives Flow 2 the same treatment with a
> small **in-memory** chat wrapper — the functional analogue of `WorkflowChatAgent`,
> minus checkpoints (which caused a type-allowlist mismatch: `Checkpoint
> deserialization blocked for type '…:_TurnResult'`). Empirically validated:
> driving the functional workflow through `WorkflowChatAgent` already returned each
> pause as text and the final `# Report` — this plan makes that clean and dedicated.

## Section 1 — What We Are Doing

1. **Flow 2 chat wrapper** — Add `FunctionalWorkflowChatAgent`: a `BaseAgent` that holds one `FunctionalWorkflow` **per conversation in memory** and advances it one turn per user message — starting with `run(text)`, resuming with `run(responses={pending_id: text})`, intercepting each `request_info` pause and returning its prompt as plain assistant text. No approval panel, no checkpoint storage.

2. **Point `--functional` at the chat wrapper** — `create_hybrid_agent()` returns the new wrapper instead of the raw `.as_agent()`, so `python -m foundry_agent.main --functional` serves Flow 2 as a normal DevUI chat.

3. **Tests** — Offline coverage: a pause returns assistant text (not a raw `request_info`), the next message resumes to completion and yields the document, two conversations stay isolated, and the entrypoint builds the wrapper offline.

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

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately after any user correction, any non-obvious failure, or any recurring pattern discovered. Do not wait to be asked.
2. **Status updates** — Every item `🔄` before review, `✅` before the next batch starts. Never advance with a `⬜` item in a completed batch.
3. **Verify gate** — After each batch run `task test` → `task lint`; dispatch `skill:thomas` to witness the batch's `Verify` line. No `✅` until Thomas returns APPROVED.
4. **Global gate** — After all batches, re-run the global verify and a final full-plan `skill:thomas` pass.

---

## Definition of Done

Inline criteria — all must hold:

- `task test` and `task lint` green (witnessed).
- **DevUI serves Flow 2 as chat, not an approval panel**: a `request_info` pause comes back as assistant **text**; the user answers with an ordinary message; no `request_info`/approval event or checkpoint-deserialization error surfaces (proven by an offline chat-drive test).
- **`chat_agent.py`, `workflow.py`, `hosting.py` are not modified**, and Flow 1's behavior/tests are unchanged. The functional gate/loop (`workflow_functional.py` core: discovery → elicitation → gate → assemble) is unchanged — this plan only adds a serving wrapper around it.
- **No domain knowledge** in the wrapper (no `PA/PC/PR/FG` literals, thresholds, or rules).
- **Per-conversation isolation**: two conversation ids drive independent workflow instances.

---

### Key facts (from investigation)

- `WorkflowChatAgent` drives a `FunctionalWorkflow` correctly through `.run(text)` / `.run(responses={id: text})` / `get_request_info_events()` / `get_outputs()` — witnessed returning pause text then the document. It only fails on its forced checkpoint storage (`_TurnResult` not in `WORKFLOW_CHECKPOINT_TYPE_NAMES`). The new wrapper omits checkpoint storage, sidestepping that entirely.
- The pause prompt is `event.data.prompt` (`GroupPrompt.prompt`) — the exact string DevUI showed in the approval panel.
- Input normalization already exists: reuse `workflow_functional._as_text` to turn the incoming `Message` / list / str into text (the bug fixed earlier this session).
- DevUI passes `stream=True` and a `session` (conversation id via `session.session_id`); `WorkflowChatAgent.run` is the reference shape to mirror for the `AgentResponse` / `ResponseStream` return.

### Implementation checklist

#### `src/foundry_agent/chat_agent_functional.py` (new)
- `class FunctionalWorkflowChatAgent(BaseAgent)` with `__init__(self, workflow_factory: Callable[[], FunctionalWorkflow], *, name, description)`.
- Per-conversation state: `self._conversations: dict[str, _FunctionalConversation]`, each holding the `FunctionalWorkflow` instance (built once via the factory) and the current `pending_request_id`.
- `run(self, messages, *, stream=False, session=None, **kwargs)`: derive `conversation_id` from `session.session_id` (else `"default"`), `user_text = _as_text(messages)`, delegate to `_advance`; return an `AgentResponse` (non-stream) or a single-update `ResponseStream` (DevUI uses `stream=True`). Mirror `WorkflowChatAgent.run`.
- `_advance(conversation_id, user_text) -> str`: build the conversation on first use (`factory()`); `run(user_text)` when fresh, else `run(responses={pending_id: user_text})`; inspect the result — `get_request_info_events()` non-empty → store `pending_request_id`, return `event.data.prompt`; otherwise return `get_outputs()[0]` (the document). Wrap in try/except and return the error as assistant text (never an empty bubble), dropping the conversation on failure.
- **No** `checkpoint_storage`, no `FileCheckpointStorage`, no `checkpoint_compat` import.
- Reuse response/text helpers from `chat_agent.py` **only if importable without side effects**; otherwise a minimal local `AgentResponse`/update builder. Do not edit `chat_agent.py`.

#### `src/foundry_agent/main.py`
- `create_hybrid_agent()` returns `FunctionalWorkflowChatAgent(lambda: create_hybrid_workflow(), name=HYBRID_AGENT_NAME, description=HYBRID_AGENT_DESCRIPTION)` instead of `create_hybrid_workflow().as_agent(...)`. Update its docstring. The `--functional` flag and selection logic are unchanged.

#### `tests/test_workflow_functional.py` (or a new `tests/test_chat_agent_functional.py`)
- Pause→text: turn 1 returns the FG1 prompt as assistant text with a pending request recorded; no raw `request_info` in the response.
- Resume→document: turn 2 (answering) drives to completion and returns the assembled document.
- Isolation: two `session_id`s produce independent runs (one pausing doesn't affect the other).
- No checkpoint noise: assert the drive completes without a checkpoint-deserialization error path.

#### `tests/test_devui_entrypoint.py`
- Update `test_devui_entrypoint_serves_flow2_as_a_functional_agent`: assert `create_hybrid_agent()` is now the chat wrapper (`FunctionalWorkflowChatAgent`, name `report-interview-functional`), default entrypoint still Flow 1.

### Validation strategy

Run after each batch:
```
task test
task lint
```
Plus a manual DevUI check by the user: `python -m foundry_agent.main --functional` → chat "hi" → the interview reads as assistant text with reply boxes, no "Approval Required".

### Out of scope

- **Hosted/production serving of Flow 2** — still Flow 1 only; `hosting.py` untouched.
- **Restart-resume / checkpoint parity for Flow 2** — the wrapper is in-memory, so a process restart drops in-flight Flow 2 conversations. Adding a functional-type checkpoint allowlist is a separate follow-up.
- **Any change to Flow 1** (`chat_agent.py`, `workflow.py`, `hosting.py`) or to Flow 2's core interview logic in `workflow_functional.py`.
- **Concurrency hardening** — the "Workflow is already running" guard and unbounded conversation-cache growth are inherited from the `WorkflowChatAgent` pattern and not addressed here.

---

## Section 3 — Tracking List

### Batch 1 — Flow 2 chat wrapper + wiring + tests

| #      | Item                                                             | File/Area                                       | Status |
| ------ | ---------------------------------------------------------------- | ----------------------------------------------- | ------ |
| 1      | `FunctionalWorkflowChatAgent` (in-memory, pause→text)            | `src/foundry_agent/chat_agent_functional.py`    | ✅     |
| 2      | Point `create_hybrid_agent()` at the wrapper                     | `src/foundry_agent/main.py`                      | ✅     |
| 3      | Chat-drive tests (pause→text, resume→doc, isolation, no noise)   | `tests/test_chat_agent_functional.py`           | ✅     |
| 4      | Update entrypoint test to the new wrapper type                  | `tests/test_devui_entrypoint.py`                 | ✅     |
| DoD    | Validate batch against inline DoD                               | `## Definition of Done`                          | ✅     |
| Thomas | Verify this batch                                              | `skill:thomas`                                   | ✅     |

**Verify:** `task test` → `task lint` → new chat-drive tests green (pause returns text, resume yields the document, conversations isolated); all pre-existing tests still green.
**DoD Gate:** Validation subagent confirms: chat wrapper returns text (no raw `request_info`/approval), no checkpoint storage used, `chat_agent.py`/`workflow.py`/`hosting.py` unmodified, wrapper domain-free, per-conversation isolation holds. Mark ✅ only when every criterion passes; on failure fix, log in `lessons.md`, re-run.
**Thomas Gate:** After the DoD Gate, dispatch `skill:thomas` to execute the `Verify` line and confirm witnessed passing output plus all rows ✅. Thomas row ✅ only on **APPROVED**.

---

### Batch 2 — Final validation

| #      | Item                                                                     | File/Area                 | Status |
| ------ | ------------------------------------------------------------------------ | ------------------------- | ------ |
| 1      | Run `task test` → `task lint` — all green                                | repo root                 | ⬜     |
| 2      | Manual review: DoD criteria hold (Flow 1 untouched, no checkpoints, domain-free) | manual code review | ⬜     |
| 3      | Runtime smoke: offline chat-drive shows pause-as-text → answer → document, no approval/checkpoint errors | `tests/…functional` | ⬜     |
| DoD    | Full inline-DoD sign-off                                                 | `## Definition of Done`   | ⬜     |
| Thomas | Full plan sign-off                                                       | `skill:thomas`            | ⛾      |

**Verify:** `task test` → `task lint` → 0 failures; the chat-drive smoke shows a pause surfaced as assistant text and the next message completing the interview.
**DoD Gate:** Validation subagent runs every `## Definition of Done` criterion, pass/fail each. Mandatory; not done until all pass.
**Thomas Gate:** Dispatch `skill:thomas` for the full-plan pass — re-run the global verify, confirm every row ✅, issue a final **APPROVED** / **NOT APPROVED** verdict. Not complete until **APPROVED**.
