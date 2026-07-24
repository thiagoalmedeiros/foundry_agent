# Batch 3 — witnessed restart-survival demo (2026-07-23)

All output below is captured verbatim from the live run (gpt-5-mini via
`task sim:run`, chat mode, compose collector + Aspire up).

## Turn 1 — opening the interview

Request: `POST /responses` — *"I need a security policy for remote work at a
small fintech. Policy ID POL-SEC-001, call it Remote Work Security Policy."*

Reply (first lines):

> Let's pin down what this policy is called, what kind of policy it is, and who owns it.
>
> - **Policy ID** — POL-SEC-001 (as you stated); please confirm.
> - **Title** — Remote Work Security Policy (as you said); please confirm.
> - **Policy type** — candidate answers: Governance / Operational / Security / Compliance; I favour Security (you requested a security policy); confirm or pick another.
> - **Status** — a suggested value is Draft (inferred for a new document); please confirm.

Checkpoint state after turn 1: `1 file(s)` under `.checkpoints/chat/default/`.

## The restart

```
server killed (the restart)
1
(checkpoints surviving the dead process)
```

`task sim:run` started again — brand-new process, empty conversation cache.

## Turn 2 — the resumed conversation

Request: *"All confirmed: POL-SEC-001, Remote Work Security Policy, type
Security, status Draft, version 1.0, owner is the CISO."*

Reply (first lines) — the interview ADVANCED to the next field group instead
of replaying the opening framing, proving the gap report and captured values
were restored from the checkpoint:

> - **Purpose** — state the policy's purpose: I've drafted: This policy establishes security requirements for remote work for employees and contractors of the fintech … please confirm.
> - **Scope** — name who and what the policy covers: I've drafted: This policy applies to employees and contractors of the small fintech when working remotely …

`starts with error prefix: False`

## Supporting evidence

- Restarted server's log: **0** fallback warnings (`restore failed` /
  `starting fresh` / `nothing pending`) — the silent-success path.
- Collector at steady state: probe trace accepted (`{"partialSuccess":{}}`),
  **0** export errors — traffic reaches Aspire (UI witnessed reachable at
  :18888 by `task sim:smoke`). The only error-shaped log lines across the
  session were boot-order connection-refused retries while Aspire's ingest
  came up, converging every time.
- Teardown clean: `task sim:down` removed containers + network; demo
  checkpoints cleaned; `task test` exit 0; `task lint` exit 0.

## Incidental discovery (out of batch scope, logged in lessons.md)

A message posted while a turn is still in flight on the same conversation
raises "Workflow is already running; concurrent runs are not allowed", and
the error path resets the conversation — now including its durable
checkpoints. A concurrent duplicate message can therefore destroy an
interview's persisted state. Follow-up candidate: treat that specific error
as "still busy — try again" without the reset.
