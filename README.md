# foundry_agent — Police Incident Report authoring agent on Microsoft Agent Framework

A **self-contained Foundry agent template**: a global, agent-paced,
human-in-the-loop authoring interview built on the **Microsoft Agent
Framework** (Python), served as an Azure AI **Foundry Hosted Agent**,
currently carrying a **Police Incident Report** domain. Fork it and swap the
`skills/` content to carry a different document domain — the interview
engine, serving paths, tests, and observability come along unchanged with
**zero code change**: not just the field definitions, but discovery, the
elicitation cadence, and the validation rules are all read from the
mounted skill at run time.

The flow walks the document one field group at a time, in the order the
skill declares:

> Discovery (an LLM agent reads the skill's field groups) → Elicitation (a
> natural multi-turn conversation, one field group at a time, in the
> skill's declared order — inferring what the content supports, confirming
> it, and asking for the rest) → Validation (once, after the last group
> closes: the skill's own deterministic script, run as a tool call, plus
> the agent's adequacy judgment) → the Assembler, which emits a complete
> Police Incident Report per the skill's canonical template.

This is **Flow 1**, written on the MAF **graph API** (executors + edges). A
**functional-API** sibling, **Flow 2**, now ships alongside it: the same
discovery → elicitation → assembler flow written as a plain `async @workflow`,
but its validation stage is a **deterministic script gate** — the skill's own
`validate.py` run directly, with no LLM — that re-elicits only the groups with
missing fields until the script passes or a cycle cap is hit. See
[Two flows: graph API vs functional API](#two-flows-graph-api-vs-functional-api)
below.

## How the domain is defined

**No agent, and no workflow code, carries domain knowledge.** Everything
about what a Police Incident Report *is* — and how it is validated — lives
in two in-repo skills:

- [`skills/police-report-format/`](skills/police-report-format/) — the
  format spec: field groups partitioning attributes, characteristics and
  rules (advisory), record patterns, population/inference guidance,
  the canonical template, **and the skill's own deterministic validation
  script** ([`validation/validate.py`](skills/police-report-format/validation/validate.py)).
- [`skills/elicitation/`](skills/elicitation/) — the behavior skill: the
  question-loop invariants EL1–EL15 (cadence, capture discipline, Socratic
  assist, honest sourcing).

That content reaches agents two ways. The **discovery** and **elicitation**
agents mount skills via MAF's `SkillsProvider` + `FileSkillsSource`
progressive disclosure (`load_skill` / `read_skill_resource`) — discovery
mounts the format skill, elicitation mounts both, amortized by its
multi-turn session. The **validation** and **authoring** agents carry
per-agent reference packs read *verbatim from the same skill files* at
construction time and inlined into their system prompts (cheaper than a
tool loop for stateless calls — the predecessor project measured it). The
validation agent additionally mounts the format skill's provider — not for
disclosure, but so the native `run_skill_script` tool can execute the
skill's validation script.

**Discovery is an LLM agent**, not a deterministic parser: it reads the
skill's Field Groups reference through progressive disclosure and returns
the groups as structured output. This is a deliberate choice for a
swap-the-skill template — an agent tolerates whatever markdown a new
skill's author writes, where a strict parser would force them to match an
exact grammar or watch the interview fail to start.

**Validation is a tool call, not a workflow-level rule.** The Validation
agent extracts every captured attribute value from the candidate content
and runs the *loaded skill's own* `validation/validate.py` through the
skill provider's native `run_skill_script` tool — executed as a
subprocess by a small script runner in
[`agents.py`](src/foundry_agent/agents.py) (the framework defines the
runner protocol but ships no implementation). A build-time existence
check keeps the fail-fast guarantee: a skill shipped without its script
fails at startup rather than mid-interview. The agent then layers its own
substantive adequacy judgment on top of the script's deterministic
result. Swap the skill and its validation rules travel with it; the
workflow contains no attribute ids, enums, or thresholds of its own.

**Elicitation runs one field group at a time**, in the skill's declared
order — this workflow overrides the elicitation skill's default
whole-document cadence (EL4). For each group the agent drives a natural
multi-turn conversation until the group's Adequacy is satisfied, then
advances. Inferred values are presented for light confirmation rather than
re-asked (EL13); a Socratic assist and coach-on-mismatch keep a stuck or
mismatched answer on the same field (EL11) within a follow-up budget (EL6);
honest sourcing labels every value by its origin (EL15).

## Serving paths

Two entrypoints, deliberately distinct:

- **Production — Foundry Hosted Agent** ([`hosting.py`](src/foundry_agent/hosting.py),
  `task hosted:run`). The workflow is wrapped in MAF's `WorkflowAgent` and
  served by `agent-framework-foundry-hosting`'s `ResponsesHostServer`,
  exposing an OpenAI-compatible `/responses` endpoint; human-in-the-loop
  pauses surface as `request_info` function calls. A `HOSTED_AGENT_MODE=chat`
  switch instead serves `WorkflowChatAgent` — plain assistant text — for
  chat-first clients (the Foundry playground, `azd ai agent invoke`) that
  cannot render a raw function-call pause. Chat conversations checkpoint
  every turn and a restarted process resumes them from the latest
  checkpoint (see **Local deploy simulation** below). Deploy config lives
  in [`azure.yaml`](azure.yaml) (`azd provision` / `azd deploy`).
- **Dev tooling only — DevUI** ([`main.py`](src/foundry_agent/main.py),
  `task devui`): an optional local inspector for driving the workflow
  interactively. Not the production path; nothing production depends on it.
  Run `python -m foundry_agent.main --functional` to serve **Flow 2** (the
  functional hybrid workflow) instead of the default graph workflow.
- **Dev tooling only — Teams bridge**
  ([`teams_bridge.py`](src/foundry_agent/teams_bridge.py), `task teams:bridge`):
  a thin, flow-agnostic bridge that lets the local Microsoft 365 Agents
  Playground drive the workflow from a Teams-shaped chat. It forwards each
  inbound message as one bare turn to a running chat-mode `/responses` server
  and relays the assistant text back — the flow is chosen on the *server*
  (`HOSTED_AGENT_MODE`), not in the bridge. See **Drive the workflow from
  Teams** below.

## Layout

```
skills/police-report-format/    # WHAT a Police Incident Report is + its own validation script
skills/elicitation/             # HOW the question loop runs (EL1-EL15)
azure.yaml                      # Foundry hosted-agent deploy config (azd provision/deploy)
main.py                         # Foundry code-deploy entrypoint → foundry_agent.hosting.main
infra/local/                    # local deploy sim: OTel collector + Aspire (docker compose)
src/foundry_agent/
├── hosting.py                  # PRODUCTION entrypoint — WorkflowAgent + ResponsesHostServer (+ chat mode)
├── checkpoint_compat.py        # shim: lets hosted checkpoints restore this workflow's types
├── main.py                     # DevUI entrypoint (optional dev tooling)
├── workflow.py                 # Flow 1 (graph API): discovery → elicitation → validation → assembler
├── workflow_functional.py      # Flow 2 (functional API): same flow + deterministic validate.py gate loop
├── chat_agent.py               # drives the workflow over chat turns; per-turn checkpoints + restart resume
├── chat_agent_functional.py    # serves Flow 2 as a DevUI chat (pauses as text); in-memory, no checkpoints
├── teams_bridge.py             # dev tooling: Teams ↔ workflow bridge (/api/messages → /responses)
├── agents.py                   # 4 agents, skill packs + skill mounts, client factory, script runner
├── prompts.py                  # everything the agents are told: instructions, packs, per-turn clauses
├── usage.py                    # per-stage token accounting + OTel span annotation
├── otel_collector.py           # dev tooling: sqlite-backed OTLP collector (task otel:up)
└── models.py                   # structured-output contracts (response_format)
tests/                          # offline suite (stubbed chat clients) + fixtures/
plans/                          # implementation plans + lessons (project history)
```

Termination policy (in [`workflow.py`](src/foundry_agent/workflow.py)):
required attributes block; advisory findings never do. There is no fixed
turn cap — the elicitation skill's per-point give-up rule (EL6) guarantees
each group terminates, and validation runs once after the last group
closes rather than reopening the conversation. Unresolved required
attributes are *banked*, not retried: they land in the `## Advisory
findings` appendix and the run terminates, so a run always finishes.
`MAX_USER_INPUT_CHARS` bounds any single user input. The conversation's
`AgentSession` rides inside the `request_info` payload so it survives
checkpoint resumes.

## Running

```bash
cp .env.example .env            # then fill in your endpoint + deployment

# Production serving path (Foundry Responses protocol)
task hosted:run                 # serve on :8088 via ResponsesHostServer (real model calls)
task hosted:invoke              # POST one /responses turn to a running hosted:run server
                                #   task hosted:invoke MESSAGE="..." to send your own text

# Optional dev tooling (NOT the production path)
task devui                      # full workflow in DevUI on :8090 (real model calls)

task test                       # offline test suite (stubbed chat clients)
task lint                       # ruff
```

## Drive the workflow from Teams (local Agents Playground)

A worked example of consuming this workflow from a Teams-shaped client. It
needs **two processes**: the chat-mode workflow server, and the bridge.

```bash
# 1. The workflow, in a chat mode (pick the flow HERE — the bridge is agnostic):
HOSTED_AGENT_MODE=chat task hosted:run             # Flow 1 (graph + validation agent)
HOSTED_AGENT_MODE=chat-functional task hosted:run  # Flow 2 (deterministic script gate)

# 2. The bridge, in a second terminal:
task teams:bridge                                  # /api/messages on :3978
```

Then start the [Microsoft 365 Agents
Playground](https://learn.microsoft.com/microsoftteams/platform/toolkit/debug-your-teams-app-test-tool)
— a Teams-like chat UI that needs no tenant, no Azure Bot registration and no
tunnel. It requires Node, and `npx` fetches it on demand:

```bash
npx -y @microsoft/m365agentsplayground     # UI on :56150, opens a browser
```

Its default application endpoint is already `http://localhost:3978/api/messages`
— exactly where the bridge listens — so no configuration is needed. Override
with `--app-endpoint <url>` / `--port <n>` if you moved either.

Now chat: describe an incident, answer each elicitation question, and the
assembled document comes back in the Teams client. A turn runs real model calls,
so replies take roughly 30s–2min; the bridge answers "still working" if you send
another message mid-turn. Because chat-mode continuity lives in the running
server, **restarting `hosted:run` restarts the interview**.

### From VS Code (one F5)

Run and Debug offers exactly two entries — one per workflow — and each starts
all three processes together:

| Entry | Serves |
| --- | --- |
| **Flow 1 — Teams Playground** | graph API + validation agent (`HOSTED_AGENT_MODE=chat`) |
| **Flow 2 — Teams Playground** | functional API + deterministic `validate.py` gate (`chat-functional`) |

Breakpoints work in `teams_bridge.py` and throughout the workflow; stopping the
session stops all three processes. The other configurations in
[`.vscode/launch.json`](.vscode/launch.json) (DevUI, the raw workflow graph, the
Foundry Toolkit visualizer) still exist and still run — they are just marked
`"presentation": { "hidden": true }` to keep the list to two. Delete that line
from any of them to bring it back.

How it works — and why it is this simple:

- Each inbound message becomes one **bare** `/responses` turn
  (`{model, input}` — never `previous_response_id` / `conversation_id`).
  Chat-mode continuity lives in the server's in-process conversation, so
  chaining response ids would replay stored history into the elicitation
  answer and corrupt turn 2.
- Turns are **serialized per conversation**: a message sent while the previous
  turn is still running gets a "still working" reply instead of colliding with
  the in-flight run.
- Auth is **anonymous** — the local Playground sends no bearer token.

**Out of scope (deliberately):** sideloading into a real Teams *tenant* — app
manifest, Azure Bot registration, Dev Tunnel, and Entra auth are all absent.
The bridge is a local learning example, not a deployable Teams app. Concurrent
multi-user conversations are out of scope too: chat mode keys everything to one
`"default"` conversation, so one running server serves one interview at a time.

## Local deploy simulation

Simulates the deployed environment's *wiring*, not its services: the exact
artifact that ships runs locally with only environment differences. There
are deliberately no storage emulators — Foundry persistence is env-selected
and platform-owned (host-managed file checkpoints plus the platform's own
storage API), so the faithful local equivalents are the plain filesystem and
the host's built-in fallbacks. See
[`plans/local-deploy-sim/plan.md`](plans/local-deploy-sim/plan.md).

```bash
task sim:up      # OTel collector (:4318) + Aspire dashboard (http://localhost:18888)
task sim:smoke   # reachability checks for both
task sim:run     # serve the agent on the host (chat mode), traces → Aspire
task sim:down    # tear everything down
```

Restart survival: chat conversations checkpoint every turn under
`.checkpoints/chat/<conversation>/`. Kill `task sim:run` mid-interview,
start it again, send the next message — the conversation resumes from its
latest checkpoint. In production the platform's persistent per-session
containers preserve that checkpoint root; locally the filesystem does.
If `task otel:up`'s sqlite collector already owns :4318, run `task otel:down`
first.

Environment notes (hard-won — see `plans/*/lessons.md`):

- `AZURE_OPENAI_ENDPOINT` must be the **resource root**
  (`https://<res>.services.ai.azure.com`), not the `/api/projects/...`
  project endpoint — the OpenAI client appends `/openai/deployments/...`.
- The deployment named in `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` must actually
  exist on the resource, and your subscription must have **quota** for that
  model (`az cognitiveservices usage list -l <region>`); catalogue
  availability alone is not deployability.
- Hosted auth uses managed identity when no `AZURE_OPENAI_API_KEY` is set.
- `HOSTED_AGENT_MODE=chat` (set in `hosted.env` for the Foundry deployment)
  serves plain-text turns instead of the raw `request_info` protocol — set
  it whenever the client is chat-first (a playground, not a driver that
  handles `function_call_output`).

Deploy to Foundry: `azd provision` then `azd deploy` against
[`azure.yaml`](azure.yaml); set endpoint/deployment first with `azd env set`.

## Forking this template for a new domain

1. Replace `skills/police-report-format/` with your format skill — keep
   the structural contract of `references/field-groups.md` (headings,
   Framing / Attributes / Adequacy fields, coverage map) and the ten
   reference-file names the prompt packs read.
2. Author your skill's own `validation/validate.py` (contract: a
   module-level `validate(captured_values: dict[str, str], groups: list[dict]) -> list[str]`
   returning failing attribute ids, plus the CLI `__main__` wrapper —
   `python validate.py '<captured JSON>' '<groups JSON>'` → failing ids as
   JSON on stdout — because the Validation agent runs it as a subprocess
   via the skill provider's native `run_skill_script` tool. See the
   police-report-format skill's own script and its `validation/SECURITY.md`
   for the trust model. No workflow code changes: the provider discovers
   and runs whatever script the mounted skill ships.
3. Rewrite the instruction blocks in `prompts.py` to your vocabulary — the
   Discovery agent needs no changes; it already reads whatever groups your
   skill declares.
4. Repin the tests (`tests/conftest.py` fixtures and the skill-reading
   tests) and vendor a sample input under `tests/fixtures/`.

The workflow (`workflow.py`) and the agent wiring (`agents.py`, including
its domain-neutral skill-script runner) need **no changes** for a domain
fork — only the skill content and the prompt vocabulary do.

## Two flows: graph API vs functional API

This template ships **both** MAF orchestration surfaces so you can compare
them directly:

- **Flow 1 — graph API** ([`workflow.py`](src/foundry_agent/workflow.py), the
  default). Executors + edges; validation is an LLM agent (the skill's
  `validate.py` via `run_skill_script`, plus an adequacy judgment) run once
  after the last group closes. It checkpoints and resumes cleanly through both
  DevUI and the hosted `/responses` protocol — the production path.
- **Flow 2 — functional API**
  ([`workflow_functional.py`](src/foundry_agent/workflow_functional.py),
  `python -m foundry_agent.main --functional`). A plain `async @workflow` with
  `@step` calls; its validation stage is a **deterministic script gate** — no
  LLM — that re-elicits only the groups with missing fields until `validate.py`
  passes or a cycle cap (`FLOW2_MAX_CYCLES`, default 40) banks the residual gaps
  into the appendix. The functional API expresses that termination loop far more
  readably, at the cost of HITL resume semantics that replay from the top of the
  run — so each `request_info` lives inside a `@step`, letting a resolved pause
  be cached and short-circuited on replay. Flow 2 is served as a **chat agent**
  ([`chat_agent_functional.py`](src/foundry_agent/chat_agent_functional.py)), so
  each elicitation pause reads as ordinary assistant text rather than a DevUI
  "Approval Required" panel — the functional analogue of `WorkflowChatAgent`,
  holding one workflow **per conversation in memory** (so conversations are
  isolated) with no checkpoint storage. Hosted serving and restart-resume for
  Flow 2 remain a deferred follow-up, so Flow 1 stays the production default.
