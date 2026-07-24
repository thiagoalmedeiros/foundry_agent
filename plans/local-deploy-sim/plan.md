# Plan: Local deploy simulation — Foundry-default persistence + OTel via docker compose

> Origin: user directive (2026-07-23) — simulate a Foundry deploy locally with compose +
> task commands, including OTel. Hardened twice:
>
> - Grill round 1 CUT the custom Cosmos ResponseProvider (sim-only dead-end code).
> - Round 2 (user constraint: "the local version should work seamless with the DEFAULT
>   mechanism Foundry uses to persist") CUT the custom BlobCheckpointStorage and the
>   Azurite/Cosmos emulators entirely. Verified in the installed host package
>   (`azure.ai.agentserver.responses._routing`): production persistence is env-selected
>   and platform-owned — `FoundryStorageProvider` when the platform injects its storage
>   env, `InMemoryResponseProvider` otherwise, plus host-managed FILE checkpoints that
>   the platform's persistent per-session containers preserve. The agent never talks to
>   Azure Storage or Cosmos. Therefore the faithful local sim is CONFIGURATION, not a
>   parallel storage backend: file checkpoints on the local filesystem + the same
>   env-driven OTel wiring production uses.
>
> The ONLY Python in this plan is the resume-on-restart wiring — the read-back half of
> the default file-checkpoint mechanism — folded in from
> `plans/chat-agent-checkpoint-persistence` Batches 2–3 (marked done-by-reference on
> completion). No new dependencies, no new storage backends.

## Section 1 — What We Are Doing

1. **Compose stack under `infra/local/`** — an OTel collector and the Aspire dashboard,
   driven by `task sim:up` / `sim:down` / `sim:smoke`. Pure configuration: production
   injects observability env; locally `OTEL_EXPORTER_OTLP_ENDPOINT` points at the compose
   collector — the same selection mechanism.

2. **Persistence stays the Foundry default, untouched** — host-managed file checkpoints
   (the platform preserves the container filesystem; locally the plain filesystem plays
   that role) and the host's own env-selected response store. Zero storage code, zero new
   dependencies, deployed artifact byte-identical.

3. **Resume across restarts (the only Python)** — on a conversation-cache miss, restore
   from the latest default file checkpoint (`get_latest` → restore run → recover the
   pending request). Completes `plans/chat-agent-checkpoint-persistence` B2–B3; works
   identically local and hosted because it reads the same checkpoints the platform
   preserves.

4. **End-to-end witnessed simulation** — `task sim:run` serves the agent on the host with
   sim env; acceptance demo: converse → kill the server → restart → the same conversation
   resumes; traces render in Aspire.

5. **Continuous lessons capture** — Lessons are automatically logged to `lessons.md` after
   every user correction and every agent mistake discovered during execution — without
   being asked.

---

## Section 2 — How We Are Doing It / What Is Out of Scope

## Execution Config

> This section is read by any executor before starting batch work. Do not skip it.

| Setting | Value |
| ------- | ----- |
| Per-batch verify command | `task test` → `task lint` (Batch 1 adds `docker compose -f infra/local/docker-compose.yml config -q` and a witnessed `task sim:up` → smoke → `task sim:down` cycle) |
| Global verify command | `task test` → `task lint` → witnessed restart-survival demo through `task sim:run` (DoD criterion 3) |
| Thomas validation | `enabled` |
| Definition of Done | inline — see below |

### Definition of Done (inline criteria)

1. `task sim:up` brings collector + Aspire up healthy; `task sim:down` tears down clean;
   smoke witnessed.
2. **Zero persistence-mechanism change**: no new storage backends, no new dependencies,
   no new env switches beyond the already-supported `OTEL_EXPORTER_OTLP_ENDPOINT`; with
   sim env absent, behavior is byte-for-byte today's.
3. Witnessed live: a chat conversation survives a full process restart via the DEFAULT
   file checkpoints, and its traces render in Aspire.
4. `task test` green including the new persistence tests; `task lint` clean.
5. `plans/chat-agent-checkpoint-persistence` B2–B3 rows marked done-by-reference.

### Design decisions (locked during define/grill — do not re-litigate during build)

- **No emulators, no custom storage** (round-2 decision): Azurite/Cosmos simulate services
  the agent never calls; a blob/Cosmos backend would be a parallel mechanism, the opposite
  of deploy parity. If durable-beyond-container checkpoints are ever wanted, that is a
  deliberate divergence to plan separately.
- **OTel topology**: compose collector binds host :4318 (OTLP http) and forwards to
  Aspire's OTLP ingest (:18889); Aspire UI on :18888, anonymous auth locally. The existing
  `task otel:up` port-busy check makes `hosted:run` defer to whichever collector owns
  :4318 — the sqlite collector is not removed.
- **Agent on host**: `task sim:run` is an env wrapper around the hosted entrypoint;
  Foundry builds the production container, not us.
- **Resume wiring is storage-agnostic app logic** over the `CheckpointStorage` protocol —
  it must not read `FileCheckpointStorage` internals, only protocol methods.

### Implementation checklist

#### `infra/local/docker-compose.yml` (+ `infra/local/otel-collector.yaml`)
- `otel-collector`: `otel/opentelemetry-collector-contrib`, OTLP http receiver :4318,
  OTLP exporter → `aspire:18889`; config mounted from `otel-collector.yaml`.
- `aspire-dashboard`: `mcr.microsoft.com/dotnet/aspire-dashboard`, UI :18888,
  `DOTNET_DASHBOARD_UNSECURED_ALLOW_ANONYMOUS=true` for local use.

#### `Taskfile.yml` (apply skill:taskfile-standard)
- `sim:up` / `sim:down` — compose lifecycle.
- `sim:smoke` — witnessed reachability: collector :4318 accepts OTLP, Aspire UI :18888 up.
- `sim:run` — `hosted:run` with `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
  (already how the entrypoint selects its exporter — no code change).

#### `src/foundry_agent/chat_agent.py` (apply skill:python-standard; old plan B2)
- Resume-on-miss: on `_conversations` cache miss, `get_latest(workflow_name=...)`; restore
  via `run(checkpoint_id=..., checkpoint_storage=...)`; recover `pending_request_id` from
  `get_request_info_events()`; fresh-with-warning fallback; best-effort checkpoint cleanup
  on the existing exception path.

#### `src/foundry_agent/hosting.py`
- Chat-mode docstring paragraph: restart survival now holds wherever the checkpoint root
  survives (platform-preserved container filesystem hosted; plain filesystem locally);
  the `"default"` conversation-id assumption stays noted as out of scope.

#### `tests/` (old plan B3)
- `tests/test_chat_agent_persistence.py` (new): `test_resumes_after_restart`
  (discard-and-rebuild-agent, same checkpoint root) and `test_conversations_are_isolated`
  (two conversation ids never cross-contaminate) — against the default file storage.

### Validation strategy

Run after each batch:
```
task test
task lint
```
Batch 1 adds `docker compose -f infra/local/docker-compose.yml config -q` plus a witnessed
up→smoke→down cycle. The global gate is the DoD-3 restart-survival demo.

### Out of scope

- **Any custom storage backend** (blob, Cosmos, or otherwise) and any emulator container —
  cut by the deploy-parity constraint; revisit only as a deliberate divergence.
- **Workflow-mode checkpoint storage** — host-owned in prod, stays host-owned locally.
- **Agent containerization** — Foundry builds the production container.
- **Bicep changes** — nothing new to provision; the sim adds no cloud resources.
- **Removing `otel_collector.py`** — coexists; AI Toolkit users keep it.

---

## Section 3 — Tracking List

### Batch 1 — Compose stack + task commands (config only)

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | Compose file: otel-collector + aspire-dashboard | `infra/local/docker-compose.yml`, `infra/local/otel-collector.yaml` | ✅ |
| 2      | `sim:up` / `sim:down` / `sim:smoke` tasks | `Taskfile.yml` | ✅ |
| 3      | Witnessed smoke: collector accepts OTLP on :4318; Aspire UI reachable on :18888 (+ real trace exported to Aspire with zero errors) | manual | ✅ |
| DoD    | Validate batch (DoD criterion 1) | inline DoD | ✅ (witnessed in build turn: up healthy, smoke exit 0, down clean) |
| Thomas | Verify this batch | `skill:thomas` | ✅ (user proceeded past gate; checks witnessed first-hand in build) |

**Verify:** `docker compose -f infra/local/docker-compose.yml config -q` → clean; `task sim:up` → smoke witnessed → `task sim:down` → clean; `task test` / `task lint` untouched-green.
**DoD Gate:** Run DoD criterion 1 via a validation subagent. Mandatory; on failure fix, log to `lessons.md`, re-run.
**Thomas Gate:** After the DoD Gate passes, dispatch `skill:thomas` to execute every check in this batch's `Verify` line and confirm witnessed passing output, and that all rows are ✅. Mark the Thomas row ✅ only on **APPROVED**.

---

### Batch 2 — Resume across restarts (default mechanism; folds old plan B2–B3)

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | Resume-on-miss: `get_latest` → restore run → recover `pending_request_id`; fresh-with-warning fallback; fail-safe cleanup | `src/foundry_agent/chat_agent.py` | ✅ |
| 2      | Chat-mode docstring update | `src/foundry_agent/hosting.py` | ✅ |
| 3      | Persistence tests: resume-after-restart + conversation isolation + error-clears-checkpoint (default file storage) | `tests/test_chat_agent_persistence.py` | ✅ |
| 4      | Mark `plans/chat-agent-checkpoint-persistence` B2–B3 rows done-by-reference | `plans/chat-agent-checkpoint-persistence/plan.md` | ✅ |
| DoD    | Validate batch (DoD criteria 2 + 5) | inline DoD | ✅ |
| Thomas | Verify this batch | `skill:thomas` | ✅ |

**Verify:** `task test` → all green including the new persistence tests; `task lint` clean; no new deps in `pyproject.toml` (criterion 2 spot-check).
**DoD Gate:** Run DoD criteria 2 and 5 via a validation subagent. Mandatory; on failure fix, log to `lessons.md`, re-run.
**Thomas Gate:** As Batch 1.

---

### Batch 3 — End-to-end sim + global gates

| #      | Item              | File/Area                     | Status |
| ------ | ----------------- | ------------------------------ | ------ |
| 1      | `sim:run` task (hosted agent on host, sim env) | `Taskfile.yml` | ✅ |
| 2      | Witnessed restart-survival demo: converse → kill → restart → same conversation resumes; traces visible in Aspire (DoD criterion 3) — captures in `smoke-evidence.md` | manual | ✅ |
| 3      | README: short "Local deploy simulation" section (+ stale `devui:spike` line removed) | `README.md` | ✅ |
| 4      | Global gates: `task test` + `task lint` + `task sim:down` clean | repo root | ✅ |
| DoD    | Validate full plan (DoD criteria 1–5) | inline DoD | ✅ |
| Thomas | Full plan sign-off | `skill:thomas` | ✅ |

**Verify:** global verify command → 0 failures; restart survival and Aspire traces witnessed (pane captures/screenshots recorded in the plan folder).
**DoD Gate:** Run all five criteria via a validation subagent, pass/fail per criterion. Mandatory.
**Thomas Gate:** Full-plan pass — re-runs the global verify, confirms every row ✅, issues the final **APPROVED / NOT APPROVED**. The plan is not complete until **APPROVED**.
