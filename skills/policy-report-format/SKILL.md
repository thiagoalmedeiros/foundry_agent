---
name: policy-report-format
description: >-
  The source of record for the Policy Report document: its field groups
  (FG1-FG8), attributes (PA1-PA32), characteristics (PC1-PC12), rules
  (PR1-PR18), statement patterns, population guidance, and canonical template.
  Load this skill before making any judgment about what a Policy Report must
  contain or how its fields are written.
---

# Policy Report Format

This skill defines **what a Policy Report is**. It carries no behavior — the
question loop lives in the `elicitation` skill. Every judgment about the
document (which attributes exist, which are required, what adequate looks
like, how the final document is laid out) must come from these references,
never from prior knowledge of policy frameworks.

Stable identifiers — preserve them exactly, never renumber:

- `PAn` — attributes (PA1–PA32), the document's fields.
- `FGn` — field groups (FG1–FG8), the interview's units of work.
- `PCn` — characteristics (PC1–PC12), qualities of a good report.
- `PRn` — rules (PR1–PR18), advisory quality rules.

## Routing table

Read each file's pre-reads first (listed in the file's opening paragraph).

| Task | Read |
| --- | --- |
| Classify the policy type; understand core terms | [references/definitions.md](references/definitions.md) |
| Judge which attributes exist / are required | [references/attributes.md](references/attributes.md) |
| Walk the interview group by group | [references/field-groups.md](references/field-groups.md) |
| Decide whether content supports inferring a value | [references/inference-guidance.md](references/inference-guidance.md) |
| Compose a well-formed value for an attribute | [references/population-guidance.md](references/population-guidance.md) |
| Phrase purpose, scope, or policy statements | [references/statement-patterns.md](references/statement-patterns.md) |
| Check quality characteristics | [references/characteristics.md](references/characteristics.md) |
| Check advisory rules | [references/rules.md](references/rules.md) |
| Judge a group's adequacy / find blockers | [references/validation.md](references/validation.md) |
| Assemble the final document | [references/template.md](references/template.md) |
