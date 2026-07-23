# Batch 7 live smoke — witnessed evidence (2026-07-23)

Production serving path (new global-pipeline workflow) exercised end-to-end
with real model calls against the Azure deployment `gpt-5-mini`
(`thiagoalmedeiros-4833-resource`), in **chat mode**
(`HOSTED_AGENT_MODE=chat`) per DoD criterion 4.

## What was run

1. `HOSTED_AGENT_MODE=chat task hosted:run` — OTLP collector up on :4318,
   `ResponsesHostServer` serving `policy-report-agent` on :8088; checkpoint
   compat shim installed (16 workflow types); Responses protocol
   `azure-ai-agentserver-responses/1.0.0b8`.
2. One `/responses` turn, POSTed directly (mirrors `task hosted:invoke`):
   `"Draft a remote-work security policy for a mid-size fintech."`

A first attempt was killed client-side by a 2-minute curl timeout (the
global pipeline's discovery step alone makes ~3 real model calls — one per
`load_skill`/`read_skill_resource` round-trip — before gap analysis and
elicitation even start, so a single-agent-cadence assumption from the old
per-group design undershot the real latency). The retry used an 8-minute
client timeout and completed cleanly; the server log shows zero errors
across both attempts, so nothing here was a functional failure, only an
undersized first timeout budget.

## Witnessed result

- HTTP **200**, `status: "completed"`, `model: "policy-report-agent"`,
  one output item, **28,751.7ms** server-side (`Inbound POST /responses
  completed with status 200 in 28751.7ms`); zero `ERROR` lines and zero
  `Traceback` lines in the full server log (120 lines, checked with
  `grep -c ERROR` / `grep Traceback`).
- The output item is a **`type: "message"`, `role: "assistant"`,
  `output_text`** turn — real assistant text, **not** a silent
  `request_info` function call, per the DoD-4 requirement for chat mode:

```
**Exclusions**
Why this matters: Exclusions make explicit who or what the policy does
not cover so teams don't assume applicability where it's not intended.
---
I don't see any exclusions listed. Please either (a) state specific
exclusions (for example, 'None', contractor-owned production systems,
vendor-managed devices, or third-party support sessions) or (b) confirm
that there are no exclusions by replying "None".

**Effective date or trigger**
...

**Context narrative**
...

**Business drivers**
...
```

  (four fields batched into one turn — the agent-paced, skill-guided
  cadence Batch 3 introduced, not a one-field-per-turn or 30-field wall).
- Upstream call trace confirms the full pipeline actually ran: 9 calls to
  the Azure `/openai/v1/responses` endpoint across the session (discovery
  reading `policy-report-format` + multiple `references/*.md` resources,
  the `elicitation` skill, global gap analysis, then the batched
  elicitation turn), all `HTTP/1.1 200 OK`.

## Foundry redeploy

Not performed as part of Batch 7 — deferred to `/ship`, as scoped above.

**Update (2026-07-23, `/ship`):** `azd deploy --environment foundry-agent-dev`
completed successfully in 1m20s (agent version 6, no infra/provision
changes needed — only `azure.yaml`'s already-provisioned resources were
touched by code). This project has no git repository, so `skill:docs-sync`
(diff-based) and `skill:merge-and-validate` (branch merge) could not run in
their designed form — `git fetch` failed with "not a git repository."
Docs were already current (Batch 6 rewrote README.md and Thomas verified
it) and the Definition of Done was already Thomas-approved in the prior
full-plan `/verify` pass, so the user explicitly chose to deploy directly
rather than force git mechanics onto a non-git project.

Verified live with a **genuinely new session** (`azd ai agent invoke`,
`conv_988fd213991c4fc400g319SvnQdCQti1CdF1gCXDscluS40Dbg` — a fresh
conversation, not a reused stale session, per the
`policy-report-agent-conversion/lessons.md` warning that old sessions run
the old container image): the response shows the new global-pipeline
behavior end-to-end — a full-document field overview (all ~26 fields with
proposed/from-input provenance) followed by a **clustered, multi-field
confirmation turn** (Policy ID + Title + Policy Type + Policy Owner
together), not the old one-field-per-turn cadence a user had just reported
seeing via the Copilot-facing channel. Server responded in 179.6s (first
byte 13.4s) — consistent with the real multi-agent-call latency logged in
this plan's `lessons.md`. This confirms the deployed agent now runs the
Batch 3 batched-elicitation design, resolving the reported regression.

**Follow-up fix (2026-07-23) — readability regression in the new design
itself.** The version-6 turn above, while correctly batched, opened with a
mandatory whole-document field-status dump (every one of ~26 fields listed
as open/proposed) before the actual clustered question — a real usability
problem, not a redeploy-staleness issue this time. Root cause: literal
instruction text in `ELICITATION_INSTRUCTIONS`
([prompts.py](../../src/foundry_agent/prompts.py)) — "Every prompt lists
every field still open across the whole document... marking which ones
already carry an inferred value" — told the model to echo that list to
the user every turn; the clean turns seen earlier in this file were the
model *under-complying* with its own instructions, not the designed
behavior. Fixed by clarifying the open-fields list is context for the
agent's own cluster selection, never content to repeat back to the user
(`ELICITATION_INSTRUCTIONS`, same file). `task test` (170 passed/0
failed) and `task lint` stayed green after the edit. Re-verified locally
(clean six-field cluster, no dump) then redeployed
(`azd deploy` → version 7, 1m8s) and re-verified against a fresh
`azd ai agent invoke` session (`conv_882134f17cce3560004Dn2pkfP6ZgbiFmIyXZkB3tbb46tv0JS`):
framing line + six EL14 blocks (Policy ID, Title, Policy type, Status,
Version, Policy owner), zero whole-document dump.

**Second follow-up (2026-07-23) — version 7's EL14 blocks were still too
verbose.** User feedback after v7: the per-field "why it matters" +
`---`-divider + suggestion-paragraph shape (each field several lines) was
still not what they wanted — they asked for "a simple bullet list of the
fields and a small description... smaller is good." Confirmed the exact
target shape with the user (one bullet per field: **name** — short clause
+ inline suggestion + confirm ask, no divider, no separate paragraph)
before touching code, given two redeploy cycles had already happened
today. Updated EL14 itself in
[question-loop.md](../../skills/elicitation/references/question-loop.md)
(the invariant, not just this workflow's prompt) plus the two mirroring
bullets in `ELICITATION_INSTRUCTIONS` (`prompts.py`, one for the general
layout, one for the classification/fork case which also had to compress
to one line). `task test` (170 passed/0 failed) and `task lint` stayed
green. Verified locally (six one-line bullets, no dump, no divider), then
redeployed (`azd deploy` → version 8, 1m13s) and re-verified against a
fresh `azd ai agent invoke` session
(`conv_8bb1ffb82b581a9f00XoqkLHtii5q3dthRxDCWRsPopw29GYUk`): exactly the
approved compact shape, e.g. `- **Policy Type** — choose one: Governance /
Operational / Security / Compliance; I favour Security (the prompt calls
it a "security" policy). Please confirm or pick another.`
