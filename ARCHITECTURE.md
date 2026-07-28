# ARCHITECTURE.md — foundry_agent

System design and structure. Working instructions live in
[AGENTS.md](AGENTS.md); setup and rationale prose in [README.md](README.md).

## System components

- **Workflow engine** (`src/foundry_agent/workflow.py`) — MAF graph API:
  Discovery → Elicitation → Validation → Assembler. Elicitation clarifies
  one field group at a time (overriding the elicitation skill's default
  whole-document cadence, EL4); validation runs once, after the last group
  closes. There is no fixed turn cap — the skill's per-point give-up rule
  (EL6) guarantees each group terminates, and unresolved required
  attributes are banked into an advisory appendix. `MAX_USER_INPUT_CHARS`
  bounds any single input.
- **Functional workflow / Flow 2** (`src/foundry_agent/workflow_functional.py`)
  — the MAF functional-API sibling of the graph engine: the same Discovery →
  Elicitation → Assembler flow written as a plain `async @workflow` with
  `@step` calls, but its validation stage is a **deterministic script gate**
  rather than an LLM agent. After the first group walk, the skill's own
  `validate.py` runs as a subprocess (`run_validation_gate`); while it reports
  missing required attributes the loop re-opens only the groups that own them,
  halting when the script passes or after `FLOW2_MAX_CYCLES` (default 40) —
  residual gaps bank into the same advisory appendix. Each `request_info`
  lives inside a `@step` so the functional API's replay-from-top resume
  short-circuits resolved pauses. Flow 1 stays the production/hosted default;
  Flow 2 is served for the DevUI showcase (`main.py --functional`) through
  `FunctionalWorkflowChatAgent` (`chat_agent_functional.py`), which renders each
  pause as assistant text and holds one workflow per conversation in memory (no
  checkpoint storage).
- **Agents** (`src/foundry_agent/agents.py`) — four agents (discovery,
  elicitation, validation, authoring) over one chat client factory.
  Discovery and elicitation use MAF progressive disclosure
  (`SkillsProvider`/`FileSkillsSource`); validation and authoring inline
  per-agent reference packs from the same skill files; validation
  additionally mounts the skill provider so the native `run_skill_script`
  tool can execute the skill's own validation script through the
  subprocess script runner defined here. `run_validation_gate` reuses that
  same runner to execute the skill's `validate.py` **without an LLM** — Flow
  2's deterministic gate.
- **Prompts** (`src/foundry_agent/prompts.py`) — every instruction block,
  the pack manifests, and per-turn prompt clauses; skill identity
  constants (`FORMAT_SKILL_DIR`, `VALIDATION_SCRIPT_NAME`).
- **Domain skills** (`skills/`) — `police-report-format` (the document
  spec + its executable `validation/validate.py`) and `elicitation` (the
  question-loop behavior). All domain knowledge lives here.
- **Serving** (`src/foundry_agent/hosting.py`) — production entrypoint:
  `WorkflowAgent` + `ResponsesHostServer` (`/responses` protocol);
  `HOSTED_AGENT_MODE=chat` serves `WorkflowChatAgent`
  (`src/foundry_agent/chat_agent.py`) for chat-first clients, with
  per-turn file checkpoints and restart resume, and
  `HOSTED_AGENT_MODE=chat-functional` serves Flow 2 as a chat agent
  (`FunctionalWorkflowChatAgent`, in-memory — the surface the Teams bridge
  drives to test Flow 2). `checkpoint_compat.py` is an interim shim widening
  the host's checkpoint-type allowlist.
- **Teams bridge** (`src/foundry_agent/teams_bridge.py`) — dev tooling: a
  thin, flow-agnostic bridge between the local Microsoft 365 Agents
  Playground and the hosted chat endpoint. The Agents SDK supplies the
  native `/api/messages` binding (`CloudAdapter` + `start_agent_process`);
  each inbound message activity becomes one **bare** `/responses` turn
  (`{model, input}` — no `previous_response_id`/`conversation_id`, since
  chat-mode continuity lives in the server's in-process conversation) and
  the assistant text is relayed back. Turns are serialized per conversation
  so a message arriving mid-run cannot collide with the in-flight turn;
  auth is anonymous (local Playground only — tenant sideload is out of
  scope). The flow is selected on the server via `HOSTED_AGENT_MODE`, so
  the bridge itself is flow-agnostic.
- **Observability** — the hosting SDK's OTel distro owns the
  `TracerProvider`, driven by `OTEL_EXPORTER_OTLP_ENDPOINT`;
  `usage.py` adds per-stage token accounting. Local viewing: either the
  dev sqlite collector (`otel_collector.py`, `task otel:up`) or the
  compose stack (`infra/local/`, `task sim:up` → Aspire dashboard).

## Directory structure

```
skills/police-report-format/    # WHAT a Police Incident Report is + its own validation script
skills/elicitation/             # HOW the question loop runs (EL1-EL15)
azure.yaml                      # Foundry hosted-agent deploy config (azd provision/deploy)
main.py                         # Foundry code-deploy entrypoint → foundry_agent.hosting.main
infra/local/                    # local deploy sim: OTel collector + Aspire (docker compose)
infra/modules/                  # bicep modules for azd provision
src/foundry_agent/
├── hosting.py                  # PRODUCTION entrypoint — WorkflowAgent + ResponsesHostServer (+ chat mode)
├── checkpoint_compat.py        # shim: lets hosted checkpoints restore this workflow's types
├── main.py                     # DevUI entrypoint (optional dev tooling)
├── workflow.py                 # Flow 1 (graph API): discovery → elicitation → validation → assembler
├── workflow_functional.py      # Flow 2 (functional API): same flow + deterministic validate.py gate loop
├── chat_agent.py               # drives the workflow over chat turns; per-turn checkpoints + restart resume
├── chat_agent_functional.py    # serves Flow 2 as a DevUI chat (pauses as text); in-memory, no checkpoints
├── teams_bridge.py             # dev tooling: Teams bridge (/api/messages → bare /responses turns)
├── agents.py                   # 4 agents, skill packs + skill mounts, client factory, script runner
├── prompts.py                  # everything the agents are told: instructions, packs, per-turn clauses
├── usage.py                    # per-stage token accounting + OTel span annotation
├── otel_collector.py           # dev tooling: sqlite-backed OTLP collector (task otel:up)
└── models.py                   # structured-output contracts (response_format)
tests/                          # offline suite (stubbed chat clients) + fixtures/
plans/                          # implementation plans + lessons (project history)
```

## Configuration

Environment-selected everywhere; the deployed artifact is byte-identical
to the local one:

| Variable | Role |
| --- | --- |
| `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | Model access (resource **root** URL; see README notes) |
| `AZURE_OPENAI_API_KEY` | Optional; absent → `DefaultAzureCredential` (the hosted managed-identity path) |
| `HOSTED_AGENT_MODE` | `workflow` (default, machine clients), `chat` (Flow 1, playground-style clients), or `chat-functional` (Flow 2 as a chat agent; in-memory, no restart resume) |
| `CHAT_CHECKPOINT_STORAGE_PATH` | Chat-mode checkpoint root (default `.checkpoints/chat/`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Where the hosting SDK's OTel distro exports (platform-injected in prod) |
| `SKILL_SCRIPT_TIMEOUT_SECONDS` | Wall-clock cap on one skill-script subprocess (default 30) |
| `WORKFLOW_RESPONSES_URL` | Teams bridge → hosted chat endpoint (default `http://localhost:8088/responses`) |
| `WORKFLOW_MODEL_NAME` | `model` label the bridge sends each turn (default `report-interview-agent`) |
| `WORKFLOW_RESPONSES_TIMEOUT_SECONDS` | Bridge per-turn **read** timeout (default 600; a turn runs model calls) |
| `TEAMS_BRIDGE_PORT` | Port the bridge's `/api/messages` listens on (default 3978) |

Non-secret hosted config rides in `hosted.env` (loaded by root `main.py`);
secrets stay in the git-ignored `.env`.

## Persistence

Platform-owned and env-selected — by design, no app-level database:

- **Workflow mode:** host-managed file checkpoints (the platform preserves
  the container filesystem; the host raises if the workflow ships its own
  checkpointing).
- **Chat mode:** per-conversation file checkpoints under
  `CHAT_CHECKPOINT_STORAGE_PATH`, written every turn; a restarted process
  restores the latest checkpoint and resumes the pending elicitation.
- **Response store:** the host auto-selects `FoundryStorageProvider` from
  platform-injected env in production, `InMemoryResponseProvider`
  otherwise.

## Tests

`tests/` is fully offline: `StubChatClient` doubles in `conftest.py`
return canned structured outputs; the real skills on disk are exercised
directly (pack verbatim checks, script CLI round-trips, subprocess runner
end-to-end via real `FileSkillsSource` discovery). Persistence behavior is
pinned in `tests/test_chat_agent_persistence.py` (restart resume,
conversation isolation, error-clears-checkpoint). Run: `task test`.
