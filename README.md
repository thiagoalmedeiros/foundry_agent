# foundry_agent — Policy Report authoring agent on Microsoft Agent Framework

A **self-contained Foundry agent template**: a global, agent-paced,
human-in-the-loop authoring interview built on the **Microsoft Agent
Framework** (Python), served as an Azure AI **Foundry Hosted Agent**,
currently carrying a **Policy Report** domain. Fork it and swap the
`skills/` content to carry a different document domain — the interview
engine, serving paths, tests, and observability come along unchanged with
**zero code change**: not just the field definitions, but discovery, the
elicitation cadence, and the validation rules are all read from the
mounted skill at run time.

The flow is a single pipeline pass over the whole document, not a walk
through separately-scoped groups:

> Discovery (an LLM agent reads the skill's field groups) → Gap Analysis
> (one pass judging every group's attributes at once) → Elicitation (one
> continuous, agent-paced conversation — the agent decides how many
> related open fields to raise per turn, never one at a time and never
> the whole document at once) → Validation (the skill's own deterministic
> script, run as a tool call, plus the agent's adequacy judgment) —
> reopening the same conversation on inadequacy or advancing to the
> Assembler, which emits a complete Policy Report per the skill's
> canonical template.

This is the MAF **workflow-build** (graph API) sibling of this template.
A **sequential-orchestration** sibling — deterministic discovery and
code-based validation, better suited to a template that wants to
demonstrate replacing agent steps with plain Python — is planned
separately and not part of this codebase yet.

## How the domain is defined

**No agent, and no workflow code, carries domain knowledge.** Everything
about what a Policy Report *is* — and how it is validated — lives in two
in-repo skills:

- [`skills/policy-report-format/`](skills/policy-report-format/) — the
  format spec: field groups partitioning attributes, characteristics and
  rules (advisory), statement patterns, population/inference guidance,
  the canonical template, **and the skill's own deterministic validation
  script** ([`validation/validate.py`](skills/policy-report-format/validation/validate.py)).
- [`skills/elicitation/`](skills/elicitation/) — the behavior skill: the
  question-loop invariants EL1–EL14 (cadence, capture discipline, Socratic
  assist, honest attribution).

That content reaches agents two ways. The **elicitation** agent mounts
both skills via MAF's `SkillsProvider` + `FileSkillsSource` progressive
disclosure (`load_skill` / `read_skill_resource`), amortized by its
multi-turn session. The **discovery**, **gap-analysis**, **validation**,
and **authoring** agents carry per-agent reference packs read *verbatim
from the same skill files* at construction time and inlined into their
system prompts (cheaper than a tool loop for stateless calls — the
predecessor project measured it). The validation agent additionally
mounts the format skill's provider — not for disclosure, but so the
native `run_skill_script` tool can execute the skill's validation script.

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

**Elicitation is agent-paced**, per the elicitation skill's own default
cadence (EL4): every open field across every discovered group is handed
to the agent in one prompt, and the agent chooses a small, related
cluster to raise per turn — never one field at a time, never the entire
remaining set at once. Inferred values are presented for light
confirmation rather than re-asked (EL13); a Socratic assist and
coach-on-mismatch keep a stuck or mismatched answer on the same field
(EL11) within a follow-up budget.

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

## Layout

```
skills/policy-report-format/    # WHAT a Policy Report is + its own validation script
skills/elicitation/             # HOW the question loop runs (EL1-EL14)
azure.yaml                      # Foundry hosted-agent deploy config (azd provision/deploy)
main.py                         # Foundry code-deploy entrypoint → foundry_agent.hosting.main
infra/local/                    # local deploy sim: OTel collector + Aspire (docker compose)
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

Termination policy (in [`workflow.py`](src/foundry_agent/workflow.py)):
required attributes block; advisory findings never do. Two budgets bound
the whole run — `MAX_ELICITATION_TURNS` caps the conversation and
`MAX_VALIDATION_ROUNDS` caps how often validation may reopen it. A
document that exhausts either is *banked*, not retried: its gaps land in
the `## Advisory findings` appendix and the run terminates, so a run
always finishes. The conversation's `AgentSession` and the gap-analysis
report both ride inside the `request_info` payload so they survive
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

1. Replace `skills/policy-report-format/` with your format skill — keep
   the structural contract of `references/field-groups.md` (headings,
   Framing / Attributes / Adequacy fields, coverage map) and the ten
   reference-file names the prompt packs read.
2. Author your skill's own `validation/validate.py` (contract: a
   module-level `validate(captured_values: dict[str, str], groups: list[dict]) -> list[str]`
   returning failing attribute ids, plus the CLI `__main__` wrapper —
   `python validate.py '<captured JSON>' '<groups JSON>'` → failing ids as
   JSON on stdout — because the Validation agent runs it as a subprocess
   via the skill provider's native `run_skill_script` tool. See the
   policy-report-format skill's own script and its `validation/SECURITY.md`
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

## Architecture note: graph API vs functional API

The predecessor project implemented an earlier per-group version of this
loop on both MAF orchestration surfaces and recorded the comparison.
Short version: the functional API (`@workflow` + a `while` loop) expresses
a termination policy far more readably, but its HITL resume semantics
(replay-from-top, caller re-supplies all prior answers) had no DevUI
serving path — so this template uses the graph API (executors + edges),
which checkpoints and resumes cleanly through both DevUI and the hosted
`/responses` protocol. Re-evaluate if the functional API's serving story
matures.
