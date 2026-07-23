# Batch 7 live smoke — witnessed evidence (2026-07-22)

Production serving path exercised end-to-end with real model calls against
the Azure deployment `gpt-5-mini` (2025-08-07, GlobalStandard) on
`thiagoalmedeiros-4833-resource`.

## What was run

1. `task hosted:run` — OTLP collector up on :4318, `ResponsesHostServer`
   serving `policy-report-agent` on :8088; checkpoint compat shim installed
   (16 workflow types); Responses protocol 2.0.0.
2. `task hosted:invoke` — default message
   `"Draft a remote-work security policy for a mid-size fintech."` POSTed to
   the OpenAI-compatible `/responses` endpoint.

## Witnessed result

- HTTP **200**, `status: "completed"`, `model: "policy-report-agent"`,
  one output item, **42.95s** server-side; zero tracebacks/ERROR lines in
  the server log; per-request checkpoint created and cleaned up.
- The output item is a **`function_call` named `request_info`** — the
  human-in-the-loop pause the DoD requires — carrying the FG1 opening
  elicitation turn:

```
Let's pin down what this policy is called, what kind of policy it is, and who owns it.

**Policy ID**
The Policy ID is the canonical reference teams use to track, cite, and
version this policy across systems and communications.
---
You provided: POL-SEC-001 (you indicated this comes from the remote-work
security policy). Is POL-SEC-001 the correct Policy ID for this policy?
```

- The framing line is the skill's FG1 framing **verbatim** (EL12); the turn
  addresses exactly one field in the EL14 layout; the inferred value is
  offered for light confirmation (EL13) rather than re-asked.
- The run state in the payload shows the live engine working end-to-end:
  all **8 groups parsed from the skill** with PA ids and adequacy text;
  gap analysis classified the input **Security** and inferred all six FG1
  attributes (`POL-SEC-001`, title "Remote Work Security Policy", type
  Security, status Draft, version 0.1, owner Chief Information Security
  Officer — a role, per PR6); `session_state` carries the `policy_skills`
  provider state, so the skill mount survived into the session.

Full payload: captured during the run (7,741 bytes); the excerpt above is
the user-facing prompt verbatim.

## Observations (out of scope, recorded for later)

- Attribution nuance: the turn says "You provided: POL-SEC-001" for a value
  the agent inferred — the elicitation skill's honest-attribution guidance
  prefers proposal phrasing ("I've drafted…") for inferred values. Prompt
  tuning is explicitly out of this plan's scope; noted for a future quality
  pass.
