# Plan: Give WorkflowChatAgent (chat mode) real restart survival via checkpoint persistence

> SUPERSEDED-IN-PART 2026-07-23: Batches 2-3 were executed by `plans/local-deploy-sim` Batch 2 (rows marked by reference below); its Batch 3 witnessed restart-survival demo covers this plan's Batch 4 intent.
>

> Origin: user asked to "move current implementation of session store/persistence to
> durabletask for agent framework" — grilled via `skill:grill-me` and rejected as stated:
> the Microsoft Agent Framework Durable Extension is a competing *hosting model* (Azure
> Functions or a standalone Durable Task worker + Durable Task Scheduler backend), not a
> pluggable storage backend under this project's production host
> (`agent-framework-foundry-hosting`'s `ResponsesHostServer`). Adopting it would mean
> giving up Foundry Hosted Agent deployment (`azd ai agent run`, the Foundry playground),
> which the user explicitly ruled out ("I do not want to replace").
>
> A codebase review (this session) found the actual replaceable custom mechanism instead:
> `WorkflowChatAgent` (chat mode, `HOSTED_AGENT_MODE=chat`) holds conversation state in a
> plain in-process `dict` and never touches the framework's own `CheckpointStorage` /
> `checkpoint_id` API at all — unlike "workflow" mode, which already gets restart survival
> for free from `ResponsesHostServer`'s own `FileCheckpointStorage` management. This plan
> wires that same framework-native mechanism into chat mode directly, with zero new
> infrastructure and zero hosting-model change.

## Section 1 — What We Are Doing

1. **Checkpoint every chat-mode turn** — `WorkflowChatAgent` (`src/foundry_agent/chat_agent.py`) gains its own `FileCheckpointStorage`, scoped per conversation, and passes it into every `Workflow.run(...)` call so each turn's state lands on disk the same way workflow mode's already does — instead of living only in the in-process `dict` it uses today.

2. **Resume from checkpoint on a cache miss** — when a conversation isn't found in the in-process map (the process restarted or was redeployed since that conversation was last active), `_advance()` checks disk for a persisted checkpoint before falling back to a brand-new workflow, restores it, and picks the conversation back up mid-interview instead of silently restarting from question one.

3. **Fail-safe cleanup on error** — the existing "drop the conversation and surface the error as chat text" path also clears that conversation's on-disk checkpoint, so a broken run can never be resurrected by a later restore.

4. **Continuous lessons capture** — Lessons are automatically logged to `lessons.md` after every user correction and every agent mistake discovered during execution — without being asked.

---

## Section 2 — How We Are Doing It / What Is Out of Scope

## Execution Config

> This section is read by any executor before starting batch work. Do not skip it.

| Setting | Value |
| ------- | ----- |
| Per-batch verify command | `task test` (offline pytest suite, no live model calls) → `task lint` (ruff over `src/`, `tests/`, `main.py`) |
| Global verify command | `task test` → `task lint` → manual restart-survival smoke (Batch 4) |
| Thomas validation | `enabled` |
| Definition of Done | inline — see `## Definition of Done` below |

### Execution rules (always active)

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately after any user correction, any non-obvious failure, or any recurring pattern discovered. Do not wait to be asked. Do not batch multiple lessons into one call.
2. **Status updates** — Every item must be `🔄` before handoff to review. Every item must be `✅` before the next batch starts. Never advance with a `⬜` item in a completed batch.
3. **Verify gate** — After each batch, run the per-batch verify command listed above. Invoke `skill:thomas` as a subagent with the batch's exact `**Verify:**` checklist. Do not mark items `✅` until Thomas returns a WITNESSED PASSING verdict.
4. **Global gate** — After all batches complete, run the global verify command. Invoke `skill:thomas` for a final full-plan validation pass before presenting results to the user.

## Definition of Done (inline criteria)

1. `task test` green — full offline suite, including new persistence tests, zero collection errors.
2. `task lint` green (`ruff check src/ tests/ main.py`).
3. Witnessed restart-survival smoke (Batch 4): drive a chat-mode conversation to a mid-interview elicitation pause, kill the process, restart it, send the pending reply, and confirm the interview resumes from where it paused — not from question one.
4. Scope discipline: `checkpoint_compat.py`, `hosting.py`'s workflow-mode (`create_hosted_agent`) wiring, `azure.yaml`, and `tests/test_hosted_state.py`'s existing invariant are untouched — `git diff --stat` shows changes confined to `chat_agent.py`, its tests, and `hosting.py`'s module docstring (documentation only).

### Reference implementation to mirror

`agent_framework_foundry_hosting._responses.ResponsesHostServer._handle_inner_workflow` (installed at `.venv/lib/python3.14/site-packages/agent_framework_foundry_hosting/_responses.py`, lines ~641-802) already solves this exact problem for workflow mode and is the concrete reference for the call sequence:

1. Build a `FileCheckpointStorage` scoped to the conversation (host: per `context_id` + `user_id`; here: per `conversation_id`).
2. `restore_storage.get_latest(workflow_name=...)` — find the latest checkpoint, if any.
3. If one exists, a **restore-only** call — `workflow.run(checkpoint_id=latest.checkpoint_id, checkpoint_storage=restore_storage)` — loads prior state into the `Workflow` object; its output is discarded (the host consumes the events; we read `get_request_info_events()` off the result instead, to recover the pending elicitation id).
4. The turn's real call passes `checkpoint_storage=write_storage` (no `checkpoint_id`) to persist the new state.
5. `_delete_not_latest_checkpoints` prunes everything but the newest checkpoint after each turn.

The one structural difference: `ResponsesHostServer` reconstructs a fresh `WorkflowAgent`/`Workflow` and does the restore-then-continue dance on **every** request (it's stateless per-request). `WorkflowChatAgent` keeps a **warm** `Workflow` object in `self._conversations` for the life of the process, so the restore-only call is needed exactly once per conversation — only on a cache miss — not on every turn.

### Implementation checklist

#### `src/foundry_agent/chat_agent.py`
- Add a checkpoint-root constant, env-tunable like `MAX_USER_INPUT_CHARS` in `workflow.py` (e.g. `CHAT_CHECKPOINT_STORAGE_PATH`, default `.checkpoints/chat` relative to `cwd()` — a sibling of workflow mode's `.checkpoints`, already covered by the existing `.gitignore` entry for `.checkpoints/`).
- Add a conversation-id sanitizer (reject/escape anything that isn't a safe single path segment — mirrors the host's own safety property for `user_id` in `_approval_storage_for_user`) before it's used to build a directory path, since `conversation_id` ultimately derives from caller-supplied `session.session_id`.
- Add `_checkpoint_storage_for(conversation_id: str) -> FileCheckpointStorage`, importing `WORKFLOW_CHECKPOINT_TYPE_NAMES` from `foundry_agent.checkpoint_compat` for `allowed_checkpoint_types` (reused as-is, not re-derived — this is the same list, just supplied directly at construction time rather than monkeypatched in, so no patch is needed here).
- In `_advance()`: pass `checkpoint_storage=` into both existing `conversation.workflow.run(...)` call sites (fresh-start and reply-continuation).
- In `_advance()`: on a `self._conversations.get(conversation_id)` miss, before calling `self._workflow_factory()`, check `_checkpoint_storage_for(conversation_id).get_latest(workflow_name=<workflow's declared name>)`. If a checkpoint exists: build the workflow via the factory, do the restore-only `run(checkpoint_id=..., checkpoint_storage=...)` call, and set `pending_request_id` from `result.get_request_info_events()` (falling back to a fresh workflow, with a logged warning, if restoration yields no pending request — e.g. a stale/corrupted checkpoint).
- After a successful turn, prune old checkpoints for that conversation (mirror `_delete_not_latest_checkpoints`: keep only the latest).
- In the existing `except Exception` branch in `_advance()` (currently just `self._conversations.pop(conversation_id, None)`): also best-effort delete every checkpoint for that conversation_id, so a later cache-miss restore can never resurrect the broken run.

#### `src/foundry_agent/hosting.py`
- Update the module docstring's **Chat mode** section: it currently states "a session restart loses the interview" as the accepted trade-off against workflow mode's checkpointing — that claim is no longer true after this plan and must be corrected to describe the new checkpoint-backed behavior instead. Note explicitly that hosted chat mode's `conversation_id` still resolves to the fixed string `"default"` (no `session=` is passed by `ResponsesHostServer._handle_inner_agent`), which is an existing, documented assumption (one persistent per-session container per conversation in that deployment) — out of scope for this plan, left as-is.

#### `tests/test_chat_agent_persistence.py` (new)
- Import `WorkflowChatAgent` and a stub-client-backed workflow factory (reuse `tests/conftest.py`'s existing stub fixtures the same way `test_hosted_state.py` does).
- `test_resumes_after_restart` — drive one turn on agent instance A (pointed at a temp checkpoint root) to reach a mid-interview elicitation pause; discard instance A entirely (simulating a process restart); build fresh instance B pointed at the same temp root; send the pending reply to B; assert the conversation resumes correctly (not restarted from question one) and can proceed to completion.
- `test_conversations_are_isolated` — two distinct `conversation_id`s against the same agent instance get independent checkpoint state; a restart-simulated resume of one never surfaces the other's data.
- `test_error_clears_checkpoint` — force an exception mid-turn; assert the conversation's checkpoint is gone afterward, and a subsequent call for that same `conversation_id` starts a genuinely fresh workflow rather than reviving the broken one.
- Confirm `tests/test_hosted_state.py` needs no changes and stays green — it pins the workflow-mode invariant (the workflow itself must stay checkpoint-free so `ResponsesHostServer` can manage it), which this plan never touches.

### Validation strategy

Run after each batch:
```
task test
task lint
```

Global/final: the same two commands, plus the manual restart-survival smoke described in Batch 4.

### Out of scope

- **Workflow mode** (`hosting.py`'s `create_hosted_agent`/`ResponsesHostServer`/`WorkflowAgent` path, `azure.yaml`, `azd ai agent run`) — already has restart survival via the host's own checkpoint management; no changes.
- **`checkpoint_compat.py`'s allowlist shim** — stays exactly as-is. Confirmed (by pulling the newest published `agent-framework-foundry-hosting` release, `1.0.0b260722`, from PyPI) that the upstream gap it patches around is still open (`# TODO(@taochen): Allow a different checkpoint storage that stores checkpoints externally` in `_responses.py`); removing the shim needs an upstream fix, tracked separately.
- **The Microsoft Agent Framework Durable Extension** (`agent-framework-durabletask`, `azure-functions-durable`, `durabletask-azuremanaged`) — not adopted. These remain unused transitive dependencies in `uv.lock` (pulled in only because `agent-framework`'s meta-package bundles `agent-framework-azurefunctions`), and nothing in this plan imports them.
- **Hardening `conversation_id` derivation under hosted chat mode** (the `"default"` fallback when no `session=` is passed) — explicitly deferred per user decision this session; documented as a pre-existing, intentional assumption rather than fixed here.
- **DevUI's own session semantics** (`agent-framework-devui`) — unrelated; DevUI already supplies a `session.session_id` per conversation, which this plan simply keys checkpoints on.

---

## Section 3 — Tracking List

### Batch 1 — Checkpoint every chat-mode turn

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | Checkpoint-root constant + conversation-id path sanitizer | `src/foundry_agent/chat_agent.py` | ✅ |
| 2      | `_checkpoint_storage_for(conversation_id)` builder, reusing `WORKFLOW_CHECKPOINT_TYPE_NAMES` from `checkpoint_compat.py` | `src/foundry_agent/chat_agent.py` | ✅ |
| 3      | Wire `checkpoint_storage=` into both `Workflow.run(...)` call sites in `_advance()`, plus post-turn pruning to keep only the latest checkpoint | `src/foundry_agent/chat_agent.py` | ✅ |
| Thomas | Verify this batch | `skill:thomas` | ✅ |

**Verify:** `task test` → `task lint` → both green; no behavior change yet for a warm (non-restarted) conversation, confirmed by the existing `test_hosted_state.py` and any existing chat-agent tests still passing unchanged.
**Thomas Gate:** After the `Verify` command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 2 — Resume from checkpoint on cache miss, and fail-safe cleanup

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | On a `_conversations` cache miss, check `get_latest(workflow_name=...)` before falling back to `self._workflow_factory()` | `src/foundry_agent/chat_agent.py` | ✅ (by plans/local-deploy-sim B2, 2026-07-23) |
| 2      | Restore-only `run(checkpoint_id=..., checkpoint_storage=...)` call; recover `pending_request_id` from `get_request_info_events()`; fall back to fresh with a logged warning if nothing pending | `src/foundry_agent/chat_agent.py` | ✅ (by plans/local-deploy-sim B2, 2026-07-23) |
| 3      | On the existing `except Exception` path, best-effort clear that conversation's on-disk checkpoint | `src/foundry_agent/chat_agent.py` | ✅ (by plans/local-deploy-sim B2, 2026-07-23) |
| 4      | Update the **Chat mode** section of the module docstring (restart survival is no longer "lost"; note the still-out-of-scope `"default"` conversation-id assumption) | `src/foundry_agent/hosting.py` | ✅ (by plans/local-deploy-sim B2, 2026-07-23) |
| Thomas | Verify this batch | `skill:thomas` | ⛾ |

**Verify:** `task test` → `task lint` → both green.
**Thomas Gate:** After the `Verify` command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 3 — Test coverage

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | `test_resumes_after_restart` — discard-and-rebuild-agent resume test | `tests/test_chat_agent_persistence.py` (new) | ✅ (by plans/local-deploy-sim B2, 2026-07-23) |
| 2      | `test_conversations_are_isolated` — two conversation_ids never cross-contaminate | `tests/test_chat_agent_persistence.py` | ✅ (by plans/local-deploy-sim B2, 2026-07-23) |
| 3      | `test_error_clears_checkpoint` — a broken run's checkpoint cannot be resurrected | `tests/test_chat_agent_persistence.py` | ✅ (by plans/local-deploy-sim B2, 2026-07-23) |
| 4      | Confirm `tests/test_hosted_state.py` unchanged and green | `tests/test_hosted_state.py` | ✅ (by plans/local-deploy-sim B2, 2026-07-23) |
| Thomas | Verify this batch | `skill:thomas` | ⛾ |

**Verify:** `task test` → new suite green alongside the full existing suite; `task lint` clean.
**Thomas Gate:** After the `Verify` command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify that all tracking-list rows for this batch are marked ✅ in `plan.md`. Mark the Thomas row ✅ only after Thomas issues an **APPROVED** verdict. If Thomas returns **NOT APPROVED**, the batch is not complete.

---

### Batch 4 — Final validation

| #      | Item                                               | File/Area                    | Status |
| ------ | -------------------------------------------------- | ----------------------------- | ------ |
| 1      | Run `task test` — full suite green                 | repo root                     | ⬜ |
| 2      | Run `task lint` — clean                             | repo root                     | ⬜ |
| 3      | Witnessed restart-survival smoke: `task devui`, drive to a mid-interview pause, kill and restart the process, send the pending reply, confirm resume (not a fresh restart) | manual, `task devui` | ⬜ |
| 4      | Scope check: `git diff --stat` confined to `chat_agent.py`, its new test file, and `hosting.py`'s docstring | manual code review | ⬜ |
| Thomas | Full plan sign-off | `skill:thomas` | ⛾ |

**Verify:** `task test` → `task lint` → 0 failures; the manual smoke shows the interview resuming from its actual paused question after a real process restart, not from question one.
**Thomas Gate:** Dispatch `skill:thomas` as a subagent for the full-plan validation pass. Thomas re-runs the global verify command, reviews every section of `plan.md` to confirm all rows are ✅, and issues a final **APPROVED** or **NOT APPROVED** verdict for the plan as a whole. The plan is not complete until this verdict is **APPROVED**.
