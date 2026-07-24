# ARCHITECTURE.md — foundry_agent

System design and structure. Working instructions live in
[AGENTS.md](AGENTS.md); setup and rationale prose in [README.md](README.md).

## System components

- **Workflow engine** (`src/foundry_agent/workflow.py`) — MAF graph API:
  Discovery → Gap Analysis → Elicitation → Validation → Assembler, with
  validation able to reopen the elicitation conversation. Bounded by
  `MAX_ELICITATION_TURNS` and `MAX_VALIDATION_ROUNDS`; exhausting either
  banks the run (gaps land in an advisory appendix) rather than looping.
- **Agents** (`src/foundry_agent/agents.py`) — five agents over one chat
  client factory. Elicitation uses MAF progressive disclosure
  (`SkillsProvider`/`FileSkillsSource`); the stateless agents inline
  per-agent reference packs from the same skill files; validation
  additionally mounts the skill provider so the native `run_skill_script`
  tool can execute the skill's own validation script through the
  subprocess script runner defined here.
- **Prompts** (`src/foundry_agent/prompts.py`) — every instruction block,
  the pack manifests, and per-turn prompt clauses; skill identity
  constants (`FORMAT_SKILL_DIR`, `VALIDATION_SCRIPT_NAME`).
- **Domain skills** (`skills/`) — `policy-report-format` (the document
  spec + its executable `validation/validate.py`) and `elicitation` (the
  question-loop behavior). All domain knowledge lives here.
- **Serving** (`src/foundry_agent/hosting.py`) — production entrypoint:
  `WorkflowAgent` + `ResponsesHostServer` (`/responses` protocol);
  `HOSTED_AGENT_MODE=chat` serves `WorkflowChatAgent`
  (`src/foundry_agent/chat_agent.py`) for chat-first clients, with
  per-turn file checkpoints and restart resume. `checkpoint_compat.py` is
  an interim shim widening the host's checkpoint-type allowlist.
- **Observability** — the hosting SDK's OTel distro owns the
  `TracerProvider`, driven by `OTEL_EXPORTER_OTLP_ENDPOINT`;
  `usage.py` adds per-stage token accounting. Local viewing: either the
  dev sqlite collector (`otel_collector.py`, `task otel:up`) or the
  compose stack (`infra/local/`, `task sim:up` → Aspire dashboard).

## Directory structure

```
skills/policy-report-format/    # WHAT a Policy Report is + its own validation script
skills/elicitation/             # HOW the question loop runs (EL1-EL14)
azure.yaml                      # Foundry hosted-agent deploy config (azd provision/deploy)
main.py                         # Foundry code-deploy entrypoint → foundry_agent.hosting.main
infra/local/                    # local deploy sim: OTel collector + Aspire (docker compose)
infra/modules/                  # bicep modules for azd provision
src/foundry_agent/
├── hosting.py                  # PRODUCTION entrypoint — WorkflowAgent + ResponsesHostServer (+ chat mode)
├── checkpoint_compat.py        # shim: lets hosted checkpoints restore this workflow's types
├── main.py                     # DevUI entrypoint (optional dev tooling)
├── workflow.py                 # the global pipeline: discovery → analysis → elicitation → validation → assembler
├── chat_agent.py               # drives the workflow over chat turns; per-turn checkpoints + restart resume
├── agents.py                   # 5 agents, skill packs + skill mounts, client factory, script runner
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
| `HOSTED_AGENT_MODE` | `workflow` (default, machine clients) or `chat` (playground-style clients) |
| `CHAT_CHECKPOINT_STORAGE_PATH` | Chat-mode checkpoint root (default `.checkpoints/chat/`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Where the hosting SDK's OTel distro exports (platform-injected in prod) |
| `SKILL_SCRIPT_TIMEOUT_SECONDS` | Wall-clock cap on one skill-script subprocess (default 30) |

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
