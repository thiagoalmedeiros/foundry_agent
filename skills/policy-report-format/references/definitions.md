# Definitions

The vocabulary every other reference relies on. Read this before
classifying a policy or judging any attribute.

## The policy-type classification (PA3)

Every Policy Report is exactly one of these four types. The classification
drives conditional requirements elsewhere (PA13, PA28) — classify first,
from the dominant intent of the content, then apply the conditionals.

- **Governance** — allocates decision rights and oversight: who decides,
  who delegates, how bodies are composed and report (e.g. data governance
  charter, approval authority policy).
- **Operational** — governs how recurring work is performed and by whom
  (e.g. remote work policy, procurement policy, incident communication).
- **Security** — protects assets (information, systems, facilities, people)
  from harm or misuse; states protective obligations and controls
  (e.g. access control, acceptable use, encryption).
- **Compliance** — exists primarily to satisfy a named external obligation:
  law, regulation, standard, or contract (e.g. privacy/LGPD policy,
  records-retention under a regulation). When the external instrument is
  the reason the policy exists, the type is Compliance even if the subject
  matter is security-flavored.

A document that genuinely needs two types is two policies — split it
(see PR3).

## Modal verbs (used by PA18 statements)

RFC-2119-style, fixed meanings — one modal per statement:

- **MUST / MUST NOT** — absolute obligation or prohibition; violation is
  non-compliance.
- **SHOULD / SHOULD NOT** — strong recommendation; deviation requires a
  documented reason.
- **MAY** — genuinely discretionary.

## Core terms

- **Policy** — a mandatory statement of intent and rules, approved by an
  accountable body. Not a **standard** (specific mandatory configurations),
  not a **procedure** (step-by-step how-to), not a **guideline**
  (non-mandatory advice). Policy statements reference standards and
  procedures; they do not inline them.
- **Policy Report** — the document this skill defines: the policy plus the
  context needed to govern it (drivers, roles, enforcement, lifecycle),
  laid out per the canonical template.
- **Placeholder** — a value that fills the slot without informing: empty,
  "TBD", "TODO", "N/A", "none" (where a substantive value is required),
  "-", "?", "xxx", or a restatement of the attribute's name. Placeholders
  never count as populated (see PC10).
- **Substantively populated** — a value a reviewer could act on: concrete,
  specific to this policy, and consistent with the attribute's definition
  in attributes.md.
