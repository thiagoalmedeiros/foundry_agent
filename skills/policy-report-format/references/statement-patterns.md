# Statement Patterns

Pre-reads: [definitions.md](definitions.md) for modal verbs.

Patterns turn raw facts into finished field values. When the user supplies
the ingredients a pattern calls for, COMPOSE the value per the pattern —
do not wait for them to phrase it themselves.

## Purpose statement (PA7)

> This policy establishes **\<what is being mandated or governed\>** for
> **\<who or what it applies to\>** in order to **\<the outcome or risk
> reduction sought\>**.

One sentence, at most 40 words. Example: "This policy establishes mandatory
encryption and handling rules for customer data processed by engineering
teams in order to prevent unauthorized disclosure and meet contractual
confidentiality obligations."

Ingredients: the subject matter, the audience/assets, the intended outcome.

## Policy statement (PA18 entries)

> **PS-\<n\>.** \<Bound role or asset class\> **\<MUST | MUST NOT | SHOULD |
> SHOULD NOT | MAY\>** \<single, testable behavior or state\>
> \[\<trigger or condition, when applicable\>\].

Rules of form: one modal verb per statement; one subject per statement; a
verifier must be able to decide pass/fail from the statement alone.
Example: "PS-3. Employees MUST report suspected policy violations to the
Security Operations team within 24 hours of discovery."

Ingredients: who is bound, the obligation strength, the behavior, any
condition.

## Scope statement (PA8)

> This policy applies to **\<roles/units\>** when **\<activity or
> context\>**, covering **\<systems, data, or assets\>**\[, in
> **\<locations/entities\>**\].

State inclusions first; exclusions belong in PA9.

## Risk statement (PA14)

> Without this policy, **\<threat or failure mode\>** can lead to
> **\<consequence\>**, exposing the organization to **\<impact class:
> financial / legal / operational / reputational\>**.

## Exception criterion (PA20)

> Exceptions **\<MAY be granted | are not permitted\>**\[ by **\<role\>**,
> for at most **\<duration\>**, when **\<condition\>**, recorded in
> **\<register\>**\].

"No exceptions." is a complete, valid value.
