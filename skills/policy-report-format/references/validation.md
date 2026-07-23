# Validation

Pre-reads: [field-groups.md](field-groups.md) for each group's Adequacy
paragraph, [attributes.md](attributes.md) for requirement levels,
[rules.md](rules.md) and [characteristics.md](characteristics.md) for
advisory checks.

Validation judges ONE group at a time against its **Adequacy** paragraph,
plus the underlying rules that paragraph restates.

## Blocking vs advisory

- **Blocking**: a required in-scope attribute (or a conditional one whose
  condition holds) is not substantively populated. Report the missing
  attribute IDs; the group reopens.
- **Advisory**: a characteristic (PC) or rule (PR) violation. Report it as
  a finding with its ID; it rides into the final document's advisory
  appendix and NEVER blocks the group.

## The placeholder test (PC10)

Is any required attribute empty, TBD, or placeholder? Placeholders (per
definitions.md: TBD, TODO, N/A, "-", "?", "xxx", empty restatements) do
not count as populated — a required attribute carrying one is a BLOCKING
gap, exactly as if it were absent.

## Conditional attributes

Evaluate the condition first, from the captured content:

- **PA13** — blocking only when PA3 is Compliance.
- **PA27** — blocking only when PA20 allows exceptions.
- **PA28** — blocking only when PA3 is Security or Compliance.

When the condition does not hold, an empty value is correct and must NOT
be reported, even as advisory.

## Judgment discipline

- Vague-but-present is a judgment call: block only when the value fails
  the attribute's definition in attributes.md; otherwise pass it and
  attach the precision concern as an advisory finding.
- Never invent scope: judge only the group named in the prompt; other
  groups get their own pass.
- `complete = true` only when the group's Adequacy paragraph passes in
  full. "Mostly there" is `complete = false` with the specific missing
  IDs listed.
