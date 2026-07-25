# Definitions

The vocabulary every other reference relies on. Read this before
classifying an incident or judging any attribute.

## The incident-type classification (PA2)

Every Police Incident Report names one **primary** incident type, drawn from
one of these categories. Classify from the dominant facts of the content; a
report covering several offenses names the most serious as primary and lists
the rest as additional.

- **Crime Against Persons** — force or threat directed at a person
  (assault, battery, robbery, domestic violence, harassment).
- **Crime Against Property** — the taking or damaging of property
  (burglary, theft, motor-vehicle theft, vandalism, arson, fraud).
- **Public Order** — conduct disturbing the peace or public safety
  (disorderly conduct, trespass, noise complaint, intoxication).
- **Traffic** — a collision or moving/parking violation
  (traffic collision, DUI, hit-and-run).
- **Non-Criminal / Service** — no offense established: a welfare check, a
  found-property report, a lost-person report, an information report.

Unlike a conditional model, the category does **not** change which fields are
required — the requirement model is fixed two-level (see attributes.md). The
category informs the narrative and the disposition, nothing more.

## First-hand vs. reported

The load-bearing distinction in every police report:

- **Observed** — a fact the reporting officer perceived directly (saw the
  broken window, smelled alcohol, measured the skid mark).
- **Reported** — a fact a party or witness told the officer. Always
  attributed to its source ("the complainant stated…"), never asserted as
  the officer's own observation.

Blurring the two is the most common report defect (see PC6).

## Sanctioned enumerations

Fixed value sets the deterministic checks and the template rely on:

- **Report Status (PA3)** — exactly one of: `Draft`, `Under Review`,
  `Approved`, `Closed`. It only ever moves forward through that order.
- **Case Disposition (PA17)** — exactly one of: `Open`, `Active`,
  `Cleared by Arrest`, `Cleared by Exception`, `Unfounded`, `Inactive`,
  `Referred`, `Closed`.

## Core terms

- **Incident** — the event the report documents, whether or not it is a crime.
- **Complainant** — the person who reports the incident to police.
- **Victim** — the person against whom an offense was committed (often, but
  not always, the complainant).
- **Suspect** — a person believed to have committed the offense. Naming a
  suspect asserts a fact — it is never inferred (see inference-guidance.md).
- **Witness** — a person with first-hand knowledge who is neither victim nor
  suspect.
- **Narrative** — the officer's chronological, factual account of what
  happened, laid out per the canonical template.
- **Disposition** — the current investigative status of the case (PA17).
- **Chain of custody** — the documented handling of an item of evidence from
  collection onward.
- **Placeholder** — a value that fills the slot without informing: empty,
  "TBD", "TODO", "N/A", "none" (where a substantive value is required),
  "-", "?", "xxx", or a restatement of the attribute's name. Placeholders
  never count as populated (see PC10).
- **Substantively populated** — a value a reviewer could act on: concrete,
  specific to this incident, and consistent with the attribute's definition
  in attributes.md.
