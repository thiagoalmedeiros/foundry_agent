# Canonical Template

The final Policy Report is Markdown with exactly these 17 sections, in
this order, each populated from the named attributes. Emit every section —
a section whose optional attributes are all absent still appears, carrying
"None." An unresolved required attribute is rendered as
`*Unresolved — see Advisory findings.*`

The document title line is `# <PA2> (<PA1>)`.

| # | Section heading | Populated from |
| --- | --- | --- |
| 1 | `## Document Control` | PA1, PA4, PA5, PA6 as a four-row table |
| 2 | `## Classification` | PA3, with one line on why this type (from the captured rationale) |
| 3 | `## Purpose` | PA7 |
| 4 | `## Scope of Application` | PA8 |
| 5 | `## Exclusions` | PA9 |
| 6 | `## Effective Date` | PA10 |
| 7 | `## Context` | PA11 |
| 8 | `## Business Drivers` | PA12 |
| 9 | `## Regulatory Drivers` | PA13 ("None — not a Compliance policy." when the condition does not hold) |
| 10 | `## Risk Addressed` | PA14 |
| 11 | `## Definitions` | PA15 as a term–definition list |
| 12 | `## Related Documents` | PA16 and PA17, grouped under `### Internal` / `### External` |
| 13 | `## Policy Statements` | PA19 (when present) as a lead-in, then PA18 as the numbered PS-n list, then PA20 under `### Exceptions` |
| 14 | `## Roles & Responsibilities` | PA21, PA22, PA23, PA24 — a role/duty table; approver and escalation called out |
| 15 | `## Compliance & Enforcement` | PA25, PA26, PA27, PA28 in that order |
| 16 | `## Review & Revision` | PA29, PA30, PA32 |
| 17 | `## Communication & Training` | PA31 |

## Advisory findings appendix

When the run banked unresolved attributes or advisory (PC/PR) findings,
append after section 17:

```markdown
## Advisory findings

- <attribute id + name>: unresolved — <what is missing>
- <PCn/PRn>: <one-sentence finding>
```

Omit the appendix entirely when there is nothing to report. This is the
ONLY place internal IDs (PAn, PCn, PRn) may appear — the 17 sections
themselves stay free of them.
