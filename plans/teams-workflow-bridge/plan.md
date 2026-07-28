# Plan: Teams ↔ Workflow bridge for the local Agents Playground

## Section 1 — What We Are Doing

1. **Retire the continuity risk first (spike)** — Prove, against a running
   chat-mode `/responses` server, that forwarding **bare** `{model, input}`
   turns keeps a multi-turn elicitation advancing (no restart, no
   history-poisoning). This is the load-bearing assumption the whole bridge
   rests on; nothing else gets built until it is witnessed and recorded in
   `lessons.md`.

2. **Serve Flow 2 over `/responses` (server-side flow selection)** — Add a new
   `HOSTED_AGENT_MODE` value to `hosting.py` that serves
   `FunctionalWorkflowChatAgent`, so **either** flow is selectable server-side.
   The bridge stays flow-agnostic; the flow is chosen by which server you run.

3. **The Teams bridge** — A thin, flow-agnostic bot
   (`src/foundry_agent/teams_bridge.py`) built on the Microsoft 365 Agents SDK
   (`microsoft-agents-hosting-aiohttp` + `-core`) exposing `/api/messages`. On
   each inbound message activity it POSTs one bare `{model, input}` turn to the
   hosted `/responses` chat endpoint, extracts the assistant text, and relays it
   back to the Playground — serializing turns per conversation so an in-flight
   turn cannot trigger "Workflow is already running".

4. **Task target + docs** — A `task teams:bridge` runner and README/ARCHITECTURE
   updates that show how to drive the workflow from the local Agents Playground,
   with the tenant-sideload path explicitly banked as a non-goal.

5. **Continuous lessons capture** — Lessons are automatically logged to
   `lessons.md` after every user correction and every agent mistake discovered
   during execution — without being asked.

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

1. **Lessons** — Invoke `skill:lessons-learned` in `append` mode immediately
   after any user correction, any non-obvious failure, or any recurring pattern
   discovered. Do not wait to be asked. Do not batch multiple lessons into one call.
2. **Status updates** — Every item must be `🔄` before handoff to review; every
   item must be `✅` before the next batch starts. Never advance with a `⬜` item
   in a completed batch.
3. **Verify gate** — After each batch, run the per-batch verify command. With
   Thomas enabled, invoke `skill:thomas` as a subagent with the batch's exact
   `**Verify:**` checklist. Do not mark items `✅` until Thomas returns a
   WITNESSED PASSING verdict.
4. **Global gate** — After all batches complete, run the global verify command
   and invoke `skill:thomas` for a final full-plan validation pass (including the
   DoD's manual Playground smoke) before presenting results.

## Definition of Done

- `task test` and `task lint` are both green.
- **Manual Agents Playground smoke, witnessed:** the local Microsoft 365 Agents
  Playground, pointed at the bridge's `/api/messages`, drives a **full multi-turn
  interview to a finished document** — once with the server in Flow 1 chat mode
  (`HOSTED_AGENT_MODE=chat`) and once in Flow 2 chat mode
  (`HOSTED_AGENT_MODE=chat-functional`). The elicitation advances turn-over-turn
  (no restart, no duplicated transcript) and the assembled document is returned
  in the Teams client.
- The bridge introduces **no** domain knowledge (AGENTS.md rule) and uses the
  **native** Agents-SDK web binding rather than a hand-rolled `/api/messages`
  route (AGENTS.md "prefer MAF-native mechanisms").

### Implementation checklist

#### `src/foundry_agent/hosting.py`
- Add `create_hosted_functional_chat_agent() -> FunctionalWorkflowChatAgent`:
  build `FunctionalWorkflowChatAgent` over `create_hybrid_workflow`, binding one
  shared `DiscoveryCache` above the factory (mirror `create_hosted_chat_agent`).
- Extend `main()` mode dispatch: `HOSTED_AGENT_MODE=chat-functional` → the new
  functional chat agent; `chat` → Flow 1 chat (unchanged); anything else →
  `workflow` (unchanged). Keep the mode string lower-cased/stripped.
- Update the module docstring's **Chat mode** section to name the new mode and
  note Flow 2 is **in-memory only** (no restart-resume — matches
  `chat_agent_functional.py`'s documented limit).
- Imports: `from foundry_agent.chat_agent_functional import FunctionalWorkflowChatAgent`
  and `from foundry_agent.workflow_functional import create_hybrid_workflow`.

#### `src/foundry_agent/teams_bridge.py` (new)
- `WorkflowResponsesClient`: async client that POSTs
  `{"model": <WORKFLOW_MODEL_NAME>, "input": <text>, "stream": false}` to
  `WORKFLOW_RESPONSES_URL` (default `http://localhost:8088/responses`) with **no**
  `previous_response_id` / `conversation_id` (bare turns — the continuity
  contract proven in Batch 1), and a reply-extractor that pulls the assistant
  text from the Responses payload shape observed in Batch 1.
- Pure helpers `build_request(text)` and `extract_reply(payload)` kept free of
  I/O so they are unit-testable offline.
- Activity handling: an Agents-SDK handler that, on a `message` activity, calls
  the client and `send_activity`s the reply; non-message activities are ignored.
- Per-conversation serialization: an `asyncio.Lock` keyed by
  `turn_context.activity.conversation.id`; if a turn is already in flight for
  that conversation, reply "Still working on your last message…" instead of
  firing a second `/responses` turn.
- Errors (HTTP failure, non-2xx, empty body) surface as visible assistant text,
  never an empty bubble.
- `main()`: build the native `CloudAdapter` in **anonymous** mode (no
  Entra/app-id — local Playground), register `/api/messages`, serve on
  `TEAMS_BRIDGE_PORT` (default `3978`) via the aiohttp hosting helper. Guard with
  `if __name__ == "__main__"`.

#### `pyproject.toml`
- Add `microsoft-agents-hosting-aiohttp` and `microsoft-agents-hosting-core`
  (align to the installed `0.3.x`), with a comment marking them the Teams-bridge
  serving deps. Run `uv sync` and confirm resolution.

#### `Taskfile.yml`
- Add `teams:bridge` (desc + `uv run python -m foundry_agent.teams_bridge`),
  documenting that a chat-mode `task hosted:run` must be up first and which
  `HOSTED_AGENT_MODE` selects which flow. Update the `AGENTS.md` "Key workflows"
  table row.

#### `tests/test_hosting.py`
- Add a case asserting `HOSTED_AGENT_MODE=chat-functional` dispatches to
  `create_hosted_functional_chat_agent` and yields a `FunctionalWorkflowChatAgent`
  (offline — factory dispatch only, no server, no model calls).

#### `tests/test_teams_bridge.py` (new)
- Unit-test `build_request` (bare turn: no `previous_response_id`) and
  `extract_reply` against canned `/responses` payloads captured in Batch 1
  (a text reply and an empty/edge payload).
- Test the handler's per-conversation serialization and error-as-text paths
  with a fake turn context and a stubbed client (offline, no network).

#### `README.md` / `ARCHITECTURE.md`
- README: a "Drive the workflow from Teams (local Agents Playground)" section —
  install/launch the Playground, point it at `http://localhost:3978/api/messages`,
  run `task hosted:run` (`chat` or `chat-functional`) + `task teams:bridge`, walk
  an interview. State the tenant-sideload non-goal.
- ARCHITECTURE: add the bridge to **System components** / directory tree and add
  the `chat-functional` row to the `HOSTED_AGENT_MODE` config table.

### Validation strategy

Run after each batch:
```
task test
```
then:
```
task lint
```
Runtime batches (1 and 5) additionally require the witnessed manual checks named
in their `**Verify:**` lines — the offline suite is stubbed and cannot exercise a
live `/responses` server or the Playground.

### Out of scope

- **Teams tenant sideload** — app manifest, Azure Bot registration, Dev Tunnel,
  Entra auth. Explicitly deferred (grill decision A); the deliverable is the
  bridge pattern proven locally. A `later` follow-up, not this plan.
- **Concurrent multi-user conversations** — chat mode collapses all turns to the
  server's `"default"` conversation, so two Playground conversations at once
  interleave into one workflow. Accepted single-user limit (matches the existing
  `hosting.py` documented limitation).
- **Adaptive cards / rich Teams UI / streaming token-by-token** — the bridge
  relays plain assistant text only.
- **Flow 2 restart-resume / checkpoint parity** — `FunctionalWorkflowChatAgent`
  is in-memory by design; hosted checkpoint parity is a separate follow-up.
- **`workflow.py` / `workflow_functional.py` / agent or skill logic** — untouched;
  the bridge is pure transport, no domain knowledge.

---

## Section 3 — Tracking List

### Batch 1 — De-risk: bare-turn continuity spike

| #      | Item              | File/Area                    | Status |
| ------ | ----------------- | ---------------------------- | ------ |
| 1      | `Run task hosted:run in chat mode; POST turn 1 that triggers elicitation` | runtime (`task hosted:run` `HOSTED_AGENT_MODE=chat`) | ✅ |
| 2      | `POST turn 2 as a bare {model,input}; confirm the interview ADVANCES (no restart, no transcript duplication)` | runtime `/responses` | ✅ |
| 3      | `Capture the exact non-streaming Responses JSON shape for the reply extractor` | scratchpad note | ✅ |
| 4      | `Record the continuity contract + payload shape in lessons.md` | `plans/teams-workflow-bridge/lessons.md` | ✅ |
| Thomas | Verify this batch | `skill:thomas`                | ✅     |

**Verify:** `task test` → `task lint` (both green; no source changes yet) **and** a witnessed runtime transcript showing turn 2 answering turn 1's elicitation prompt correctly (workflow moves to the next question / completes, does not restart). If continuity does **not** hold on bare turns, stop and re-open the design before Batch 3.
**Thomas Gate:** After the Verify checks pass, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output, including the runtime transcript. Thomas will also verify all rows for this batch are ✅ in `plan.md`. Mark the Thomas row ✅ only after an **APPROVED** verdict; **NOT APPROVED** means the batch is incomplete.

---

### Batch 2 — Serve Flow 2 over `/responses`

| #      | Item              | File/Area                    | Status |
| ------ | ----------------- | ---------------------------- | ------ |
| 1      | `create_hosted_functional_chat_agent() with shared DiscoveryCache` | `src/foundry_agent/hosting.py` | ✅ |
| 2      | `main() dispatch: HOSTED_AGENT_MODE=chat-functional → functional chat agent` | `src/foundry_agent/hosting.py` | ✅ |
| 3      | `Docstring + ARCHITECTURE mode table: add chat-functional (in-memory, no resume)` | `hosting.py`, `ARCHITECTURE.md` | ✅ |
| 4      | `Test: chat-functional mode builds a FunctionalWorkflowChatAgent` | `tests/test_hosting.py` | ✅ |
| Thomas | Verify this batch | `skill:thomas`                | ✅     |

**Verify:** `task test` → `task lint` → new mode-dispatch test green; `HOSTED_AGENT_MODE=chat-functional` selects the functional chat agent without touching the `chat` / `workflow` paths.
**Thomas Gate:** After the Verify command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify all rows for this batch are ✅ in `plan.md`. Mark the Thomas row ✅ only after an **APPROVED** verdict; **NOT APPROVED** means the batch is incomplete.

---

### Batch 3 — Bridge core: deps + Responses client (unit-tested)

| #      | Item              | File/Area                    | Status |
| ------ | ----------------- | ---------------------------- | ------ |
| 1      | `Add microsoft-agents-hosting-aiohttp + -core deps; uv sync; confirm resolution` | `pyproject.toml`, `uv.lock` | ✅ |
| 2      | `WorkflowResponsesClient + build_request (bare turn) + extract_reply (I/O-free helpers)` | `src/foundry_agent/teams_bridge.py` | ✅ |
| 3      | `Env config: WORKFLOW_RESPONSES_URL, WORKFLOW_MODEL_NAME, TEAMS_BRIDGE_PORT` | `teams_bridge.py`, `.env.example` | ✅ |
| 4      | `Unit tests: build_request/extract_reply against Batch-1 payloads (offline)` | `tests/test_teams_bridge.py` | ✅ |
| Thomas | Verify this batch | `skill:thomas`                | ✅     |

**Verify:** `task test` → `task lint` → new `test_teams_bridge` unit tests green; `build_request` emits no `previous_response_id`/`conversation_id`; `extract_reply` returns the assistant text for the captured payload and a safe fallback for an empty one. No live network in tests.
**Thomas Gate:** After the Verify command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output. Thomas will also verify all rows for this batch are ✅ in `plan.md`. Mark the Thomas row ✅ only after an **APPROVED** verdict; **NOT APPROVED** means the batch is incomplete.

---

### Batch 4 — Bridge server: activity handler + adapter + serialization

| #      | Item              | File/Area                    | Status |
| ------ | ----------------- | ---------------------------- | ------ |
| 1      | `Message-activity handler → client → send_activity; ignore non-message activities` | `src/foundry_agent/teams_bridge.py` | ✅ |
| 2      | `Per-conversation asyncio.Lock; "still working" reply on overlap; error-as-text` | `teams_bridge.py` | ✅ |
| 3      | `main(): anonymous CloudAdapter + /api/messages on TEAMS_BRIDGE_PORT (native aiohttp helper)` | `teams_bridge.py` | ✅ |
| 4      | `task teams:bridge target + AGENTS.md workflows-table row; handler unit test (fake TurnContext, stub client)` | `Taskfile.yml`, `AGENTS.md`, `tests/test_teams_bridge.py` | ✅ |
| Thomas | Verify this batch | `skill:thomas`                | ✅     |

**Verify:** `task test` → `task lint` → handler tests green (serialization + error-as-text with a fake turn context, no network); `task teams:bridge` boots the aiohttp server and binds `/api/messages` on :3978 (witnessed startup log; no unhandled exception).
**Thomas Gate:** After the Verify command passes, dispatch `skill:thomas` as a subagent to execute every check in this batch's `Verify` line itself and confirm witnessed passing output, including the server-boot log. Thomas will also verify all rows for this batch are ✅ in `plan.md`. Mark the Thomas row ✅ only after an **APPROVED** verdict; **NOT APPROVED** means the batch is incomplete.

---

### Batch 5 — Docs + final validation (Playground smoke, both flows)

| #      | Item              | File/Area                    | Status |
| ------ | ----------------- | ---------------------------- | ------ |
| 1      | `README "Drive the workflow from Teams (local Agents Playground)" + non-goal note` | `README.md` | ✅ |
| 2      | `ARCHITECTURE: bridge component + directory tree entry` | `ARCHITECTURE.md` | ✅ |
| 3      | `Manual Playground smoke: full multi-turn interview → document on Flow 1 AND Flow 2` | runtime (Playground + bridge + hosted server) | ✅ |
| 4      | `Fixes found by the smoke: 600s timeout (was 120s) + _describe() for blank-message errors, with regression test` | `teams_bridge.py`, `.env.example`, `tests/test_teams_bridge.py` | ✅ |
| DoD    | Validate batch    | inline DoD (`## Definition of Done`) | ✅ |
| Thomas | Full plan sign-off | `skill:thomas`               | ✅     |

**Verify:** `task test` → `task lint` → 0 failures; **and** the witnessed Playground smoke of the DoD passes on both `HOSTED_AGENT_MODE=chat` and `chat-functional` — the interview advances turn-over-turn and returns an assembled document in the Teams client.
**DoD Gate:** Run the inline DoD criteria in `## Definition of Done` against the final state using a validation subagent. Mandatory. Mark the DoD row ✅ only after every criterion passes; on any failure, fix it, log the correction in `lessons.md`, and re-run the gate.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` as a subagent for the full-plan validation pass: re-run the global verify command, review every section of `plan.md` to confirm all rows are ✅, and witness the Playground smoke. The plan is complete only on a final **APPROVED** verdict.
