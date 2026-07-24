# AGENTS.md — working in this repository

Instructions for AI agents (and humans) making changes here. Structure and
component detail live in [ARCHITECTURE.md](ARCHITECTURE.md); user-facing
setup lives in [README.md](README.md).

## Key workflows

All entry points are go-task targets ([Taskfile.yml](Taskfile.yml)):

| Command | What it does |
| --- | --- |
| `task test` | Offline test suite (stubbed chat clients — no model calls, no credentials) |
| `task lint` | `ruff check src/ tests/ main.py` |
| `task hosted:run` | Production serving path on :8088 (real model calls; needs `AZURE_OPENAI_*`) |
| `task hosted:invoke` | POST one `/responses` turn to a running server (`MESSAGE="..."`) |
| `task devui` | DevUI dev tooling on :8090 (not the production path) |
| `task sim:up` / `sim:down` / `sim:smoke` | Local deploy-sim stack: OTel collector (:4318) + Aspire dashboard (:18888) |
| `task sim:run` | Serve the agent against the sim stack (chat mode, traces → Aspire) |
| `task otel:up` / `otel:down` | Dev-only sqlite OTLP collector; defers if :4318 is already owned |

Every change lands with `task test` and `task lint` green. Tests are
offline by design — stub clients live in `tests/conftest.py`; never add a
test that needs live credentials.

## Non-negotiable conventions

- **Prefer MAF-native mechanisms.** Before writing (or defending) custom
  plumbing, inspect the installed `agent_framework` /
  `azure.ai.agentserver` API surface (`.venv` introspection). Custom code
  that duplicates a framework capability gets deleted here — precedent:
  the custom skill loader was replaced by the provider's native
  `run_skill_script`, and a custom storage backend for the local sim was
  rejected in favor of the platform's own env-selected persistence.
- **No domain knowledge in code.** Everything about the document domain
  lives in `skills/` (including the skill's own `validation/validate.py`).
  Workflow and agent code must stay domain-free — no attribute ids, enums,
  or thresholds outside skill content and `prompts.py` vocabulary.
- **Deploy parity.** The artifact must run locally and on Foundry with
  environment-only differences. Persistence is platform-owned
  (host-managed file checkpoints; env-selected response store) — do not
  add parallel storage backends for local convenience.
- **Plans discipline.** Non-trivial work runs through a plan folder
  (`plans/<topic>/plan.md` + `lessons.md`): batches ≤4 items, verify
  commands per batch, Thomas-gated. Lessons are appended immediately after
  any correction or non-obvious failure — read the relevant `lessons.md`
  before working in an area.
- **Commit hygiene.** Simplification/refactor commits stay separate from
  feature and fix commits. The repo is local-only (no remote).

## Sharp edges (learned the hard way — see plans/*/lessons.md)

- `agent-framework` and `azure.ai.agentserver` are **beta**; private seams
  (`checkpoint_compat.py`'s host patch) are documented shims awaiting
  upstream hooks — do not deepen dependence on them.
- Skill scripts discovered by `FileSkillsSource` are named by
  **skill-relative path** (`validation/validate.py`, not `validate.py`).
- Editable-install metadata (`src/*.egg-info/SOURCES.txt`) goes stale
  after file deletions and trips reference greps — refresh with
  `uv sync --reinstall-package foundry-agent`, or grep tracked files only.
- When deleting a module, grep `tests/` too: tests of *other* modules may
  import it as a negative-assertion prop.
- The hosting SDK's OTel distro is the sole `TracerProvider` authority —
  configure observability via environment (`OTEL_EXPORTER_OTLP_ENDPOINT`),
  never in code.
- A message arriving while a chat turn is in flight raises "Workflow is
  already running" and the error path resets the conversation including
  its durable checkpoints — known follow-up: treat as "still busy"
  without the reset.
