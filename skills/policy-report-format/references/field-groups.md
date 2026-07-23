# Field Groups

Pre-reads: [definitions.md](definitions.md) for the policy-type
classification, [attributes.md](attributes.md) for what each PAn means.

The interview works one group at a time, in the order declared here, and
advances only when the current group's **Adequacy** rules pass. These groups
are the source of record: re-cluster an attribute here and the interview's
shape follows with no code change. Every attribute belongs to exactly one
group.

Each group declares a **Framing** line (the sentence that opens the group's
conversation, verbatim), its **Attributes** row, and an **Adequacy**
paragraph (what "done" means for the group).

### FG1 — Identification & Classification

**Framing:** Let's pin down what this policy is called, what kind of policy it is, and who owns it.

| Field | Value |
| --- | --- |
| Attributes | PA1 Policy ID, PA2 Title, PA3 Policy Type, PA4 Status, PA5 Version, PA6 Policy Owner |

**Adequacy:** PA1–PA6 are all substantively populated. PA1 matches the
`POL-<DOMAIN>-<NNN>` format. PA2 ≤ 10 words. PA3 is exactly one of
Governance/Operational/Security/Compliance. PA6 names a role, not a person.
No value is a placeholder.

### FG2 — Purpose & Scope

**Framing:** Now let's capture why this policy exists and exactly who and what it applies to.

| Field | Value |
| --- | --- |
| Attributes | PA7 Purpose Statement, PA8 Scope of Application, PA9 Exclusions, PA10 Effective Date |

**Adequacy:** PA7 follows the purpose statement pattern. PA8 names the
covered people, systems, or processes concretely. PA9 is explicitly stated —
"None" is acceptable, silence is not. PA10 is an ISO date or a named
triggering event.

### FG3 — Background & Drivers

**Framing:** Give me the story behind this policy — what's driving it and what's at stake without it.

| Field | Value |
| --- | --- |
| Attributes | PA11 Context Narrative, PA12 Business Drivers, PA13 Regulatory Drivers, PA14 Risk Addressed |

**Adequacy:** PA11 is 2–5 paragraphs of situation, not policy statements.
PA12 names at least one concrete driver. PA13 is populated with named
instruments when PA3 is Compliance (otherwise it may be empty). PA14 states
the risk and the consequence of leaving it unmanaged.

### FG4 — Definitions & References

**Framing:** Let's make sure every specialized term and related document is nailed down before we write the rules.

| Field | Value |
| --- | --- |
| Attributes | PA15 Key Terms, PA16 Related Policies, PA17 External References |

**Adequacy:** PA15 defines every term the policy statements rely on ("None"
only when the statements use no specialized terms). PA16 and PA17 are
advisory — populate them when the content mentions related documents, but
they never block the group.

### FG5 — Policy Statements

**Framing:** This is the heart of it — the actual rules this policy lays down.

| Field | Value |
| --- | --- |
| Attributes | PA18 Core Policy Statements, PA19 Guiding Principles, PA20 Exception Criteria |

**Adequacy:** PA18 contains at least one numbered statement (PS-1, PS-2, …),
each following the policy statement pattern with exactly one modal verb.
PA20 explicitly allows or forbids exceptions — "No exceptions" is a valid
value. PA19 is advisory and never blocks.

### FG6 — Roles & Responsibilities

**Framing:** Let's assign every duty in this policy to someone accountable.

| Field | Value |
| --- | --- |
| Attributes | PA21–PA24 |

**Adequacy:** PA21 lists the owner's concrete duties. PA22 names the
approving role or body. PA23 assigns every duty the policy statements create
to a named role. PA24 is advisory — capture the escalation path when the
content offers one.

### FG7 — Compliance & Enforcement

**Framing:** A policy nobody checks is a suggestion — how will compliance be verified and what happens when it isn't?

| Field | Value |
| --- | --- |
| Attributes | PA25 Monitoring & Measurement, PA26 Non-Compliance Consequences, PA27 Exception Process, PA28 Audit Requirements |

**Adequacy:** PA25 states how compliance is verified and how often. PA26
states graduated consequences. PA27 is populated when PA20 allows exceptions
(otherwise "Not applicable"). PA28 is populated when PA3 is Security or
Compliance (otherwise it may be empty).

### FG8 — Lifecycle & Communication

**Framing:** Finally, let's plan how this policy stays alive — reviewed, communicated, and eventually retired.

| Field | Value |
| --- | --- |
| Attributes | PA29 Review Cadence, PA30 Revision History Requirements, PA31 Communication & Training Plan, PA32 Retirement Criteria |

**Adequacy:** PA29 states a cadence of at most 24 months (12 for Security
and Compliance types) or named review triggers. PA31 states how affected
people learn of the policy and how completion is evidenced. PA30 and PA32
are advisory and never block.

### Group → attribute coverage map

| Group | Attributes |
| --- | --- |
| FG1 — Identification & Classification | PA1–PA6 |
| FG2 — Purpose & Scope | PA7–PA10 |
| FG3 — Background & Drivers | PA11–PA14 |
| FG4 — Definitions & References | PA15–PA17 |
| FG5 — Policy Statements | PA18–PA20 |
| FG6 — Roles & Responsibilities | PA21–PA24 |
| FG7 — Compliance & Enforcement | PA25–PA28 |
| FG8 — Lifecycle & Communication | PA29–PA32 |

All 32 attributes are covered exactly once.
