# Attributes (PA1–PA32)

Pre-reads: [definitions.md](definitions.md) for the policy-type
classification and modal verbs.

Requirement levels: **Required** must be substantively populated.
**Conditional** is treated as Required only when its stated condition holds
for this document; otherwise it may stay empty. **Optional** improves the
report but never blocks. Placeholders (TBD, N/A, "?", empty restatements)
never count as populated.

## FG1 — Identification & Classification

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA1 | Policy ID | Required | Unique identifier, format `POL-<DOMAIN>-<NNN>` (domain code in capitals, three-digit sequence, e.g. `POL-SEC-014`). Never reused, even after retirement. |
| PA2 | Title | Required | The policy's name, at most 10 words, specific enough to distinguish it from sibling policies. |
| PA3 | Policy Type | Required | Exactly one of Governance / Operational / Security / Compliance (see definitions.md). Drives conditional requirements: PA13 and PA28. |
| PA4 | Status | Required | One of Draft / In Review / Approved / Retired. |
| PA5 | Version | Required | Version number; 0.x while draft, 1.0 at first approval, then minor/major bumps. |
| PA6 | Policy Owner | Required | The ROLE accountable for the policy's content and review (e.g. "Chief Information Security Officer"), never an individual's name alone. |

## FG2 — Purpose & Scope

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA7 | Purpose Statement | Required | One sentence following the purpose pattern in statement-patterns.md: what the policy establishes, for whom, to what outcome. |
| PA8 | Scope of Application | Required | Who and what the policy covers: organizational units, roles, systems, data, geographies. Concrete nouns, not "everyone". |
| PA9 | Exclusions | Required | What is explicitly out of scope. "None" is a valid value; an unstated exclusion is not. |
| PA10 | Effective Date | Required | ISO date (YYYY-MM-DD) the policy takes effect, or the named event that triggers it (e.g. "upon Board approval"). |

## FG3 — Background & Drivers

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA11 | Context Narrative | Required | 2–5 paragraphs describing the situation that makes the policy necessary. Narrative only — no policy statements here. |
| PA12 | Business Drivers | Required | The concrete business reasons (cost, risk appetite, incidents, strategy) motivating the policy now. |
| PA13 | Regulatory Drivers | Conditional — required when PA3 is Compliance | The named laws, regulations, or standards the policy answers to (e.g. "LGPD art. 46", "ISO 27001 A.5"), with clause-level pointers where known. |
| PA14 | Risk Addressed | Required | The risk(s) the policy mitigates and the consequence of leaving them unmanaged. |

## FG4 — Definitions & References

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA15 | Key Terms | Required | Definitions of every specialized or ambiguous term the policy statements rely on. "None" only when the statements use no such terms. |
| PA16 | Related Policies | Optional | Sibling or parent policies this one relates to, by ID and title. |
| PA17 | External References | Optional | External frameworks, contracts, or documents referenced by the policy. |

## FG5 — Policy Statements

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA18 | Core Policy Statements | Required | The numbered rules (PS-1, PS-2, …), each a single testable statement with exactly one modal verb per the statement pattern. |
| PA19 | Guiding Principles | Optional | The principles behind the statements, for readers deciding unlisted cases. |
| PA20 | Exception Criteria | Required | Under what conditions exceptions may be granted, by whom, and for how long — or the explicit value "No exceptions". |

## FG6 — Roles & Responsibilities

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA21 | Owner Responsibilities | Required | The policy owner's concrete duties (maintain, interpret, report). |
| PA22 | Approver | Required | The role or body that approves this policy and its revisions. |
| PA23 | Affected Roles & Duties | Required | Every role the policy statements bind, with that role's duties. Every duty created in PA18 must land on a role here. |
| PA24 | Escalation Path | Optional | Where questions, disputes, and suspected violations are raised. |

## FG7 — Compliance & Enforcement

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA25 | Monitoring & Measurement | Required | How compliance is verified (reviews, tooling, metrics) and how often. |
| PA26 | Non-Compliance Consequences | Required | Graduated, lawful consequences of violating the policy. |
| PA27 | Exception Process | Conditional — required when PA20 allows exceptions | How an exception is requested, assessed, recorded, and expired. "Not applicable" when PA20 is "No exceptions". |
| PA28 | Audit Requirements | Conditional — required when PA3 is Security or Compliance | Internal/external audit obligations, evidence to retain, retention period. |

## FG8 — Lifecycle & Communication

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA29 | Review Cadence | Required | How often the policy is reviewed (at most every 24 months; 12 for Security/Compliance types) and what events trigger an early review. |
| PA30 | Revision History Requirements | Optional | How revisions are recorded (change log location and format). |
| PA31 | Communication & Training Plan | Required | How affected people learn of the policy (channels, training) and how completion is evidenced. |
| PA32 | Retirement Criteria | Optional | The conditions under which the policy is retired or superseded. |
