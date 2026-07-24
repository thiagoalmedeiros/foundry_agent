# Population Guidance

Pre-reads: [attributes.md](attributes.md),
[statement-patterns.md](statement-patterns.md).

How to write each attribute WELL once a basis exists. Values are recorded
short and concrete — a reviewer should act on them without follow-up.

The identity/status defaults below (Version 0.1, Status Draft, a provisional
`POL-<DOMAIN>-001` id) are safe to fill and flag for confirmation without
asking. The load-bearing facts that
[inference-guidance.md](inference-guidance.md) marks *ask, never invent* —
the effective date, named regulatory instruments, an owner with no basis, the
audit obligation — are not: leave them missing so the interview asks.

## Identity fields (FG1)

- **PA1** — derive the domain code from the policy's subject (SEC, HR, FIN,
  IT, DATA, PROC…); propose `POL-<DOMAIN>-001` when no register is known
  and say the sequence is provisional.
- **PA2** — name the subject and the constraint, drop filler words:
  "Remote Access Security Policy", not "A Policy Regarding the Various
  Security Aspects of Remote Access". Count the words; stay at ≤ 10.
- **PA3** — pick the ONE dominant type per definitions.md. When two
  genuinely compete, surface the fork to the user with what each choice
  implies (PA13/PA28 conditionality) — the choice is theirs.
- **PA5/PA4** — new documents default to Version 0.1, Status Draft, unless
  the content says otherwise.
- **PA6** — promote a person to their role: "Maria (our CISO)" → "Chief
  Information Security Officer".

## Narrative fields (PA11, PA12, PA14)

Write situation, cause, and stakes in plain prose. Keep policy rules OUT
of the narrative — if a sentence contains a MUST, it belongs in PA18.
Quantify where the content allows ("three incidents in 2025" beats
"several incidents").

## Rule fields (PA18, PA20)

Number statements PS-1, PS-2, … in the order of importance. Split any
sentence with two obligations into two statements. Every duty a statement
creates must land on a role in PA23 — add the role when composing the
statement.

## Enforcement fields (PA25–PA28)

Prefer verifiable mechanisms ("quarterly access review by IT Ops",
"automated VPN posture check at connect time") over intentions
("compliance will be monitored"). Consequences graduated: coaching →
formal warning → access revocation / disciplinary process, adapted to
what the content supports.

## Lifecycle fields (PA29–PA32)

PA29 states both cadence and triggers ("every 12 months, and after any
material incident or regulatory change"). PA31 names channels AND
evidence ("all-hands announcement + LMS module; completion tracked to
100% of in-scope staff").
