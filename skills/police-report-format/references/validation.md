# Validation

Pre-reads: [field-groups.md](field-groups.md) for each group's Adequacy
paragraph, [attributes.md](attributes.md) for requirement levels,
[rules.md](rules.md) and [characteristics.md](characteristics.md) for
advisory checks.

Validation judges ONE group at a time against its **Adequacy** paragraph,
plus the underlying rules that paragraph restates.

## Blocking vs advisory

- **Blocking**: a Required in-scope attribute is not substantively populated.
  Report the missing attribute IDs; the group reopens.
- **Advisory**: a characteristic (PC) or rule (PR) violation. Report it as a
  finding with its ID; it rides into the final document's advisory appendix
  and NEVER blocks the group.

Optional attributes never block — no exceptions. A missing suspect, an empty
evidence list, or no arrest is a complete report when the incident had none.
When the content clearly implies an Optional field should be present (a
narrative that describes collected evidence, but PA13 is empty), raise it as
an **advisory** finding, never a blocker.

## The placeholder test (PC10)

Is any Required attribute empty, TBD, or placeholder? Placeholders (per
definitions.md: TBD, TODO, N/A, "-", "?", "xxx", empty restatements) do not
count as populated — a Required attribute carrying one is a BLOCKING gap,
exactly as if it were absent.

## Sanctioned-value checks

Two fields carry a closed value set (definitions.md):

- **PA3 Report Status** — must be exactly one of Draft / Under Review /
  Approved / Closed. A present value outside the set is a BLOCKING gap.
- **PA17 Case Disposition** — must be exactly one sanctioned disposition. A
  present value outside the set is a BLOCKING gap.

## Judgment discipline

- Vague-but-present is a judgment call: block only when the value fails the
  attribute's definition in attributes.md; otherwise pass it and attach the
  precision concern as an advisory finding.
- Never invent scope: judge only the group named in the prompt; other groups
  get their own pass.
- `complete = true` only when the group's Adequacy paragraph passes in full.
  "Mostly there" is `complete = false` with the specific missing IDs listed.
