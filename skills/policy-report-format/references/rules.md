# Rules (PR1–PR18)

Advisory quality rules. Violations are reported as findings with the rule
ID; they never block a group (required-attribute gaps are what block —
see validation.md).

## Identity (FG1)

- **PR1** — PA1 matches `POL-<DOMAIN>-<NNN>` exactly (capitals, three-digit
  sequence) and is never reused, even after retirement.
- **PR2** — PA2 is at most 10 words, in title case, with no trailing
  punctuation and no vendor or product names.
- **PR3** — PA3 is exactly one type. A policy that genuinely needs two
  types is two policies; recommend the split.
- **PR4** — PA4 only ever moves Draft → In Review → Approved → Retired.
- **PR5** — PA5 stays 0.x while Draft; first approval is 1.0; later changes
  bump minor (editorial) or major (obligations changed).
- **PR6** — PA6 is a role or body, never an individual's name alone.

## Purpose, scope, drivers (FG2–FG3)

- **PR7** — PA7 is one sentence, ≤ 40 words, following the purpose pattern.
- **PR8** — PA8 states inclusions; PA9 states exclusions; an exclusion
  never contradicts a stated inclusion.
- **PR9** — PA10 is an ISO date or a named event — "soon" and "Q3" are
  findings.
- **PR10** — PA11 is 2–5 paragraphs and contains no modal-verb policy
  statements.
- **PR11** — PA13 cites each instrument by name, with clause-level
  pointers where known.

## Statements (FG5)

- **PR12** — every PA18 entry is numbered `PS-n` and uses exactly one
  modal verb.
- **PR13** — no statement mixes obligation strengths (a MUST clause and a
  SHOULD clause in one sentence).
- **PR14** — when PA20 allows exceptions, it names who may grant them and
  time-bounds every exception.

## Enforcement (FG6–FG7)

- **PR15** — every role bound in PA23 appears in PA25 monitoring or PA26
  consequences; an unmonitored duty is a finding.
- **PR16** — PA26 consequences are graduated and lawful; no ad-hoc
  penalties.

## Lifecycle (FG8)

- **PR17** — PA29 cadence is at most 24 months; at most 12 when PA3 is
  Security or Compliance.
- **PR18** — PA31 names concrete channels and completion evidence
  (attestation, LMS tracking), not just "will be communicated".
