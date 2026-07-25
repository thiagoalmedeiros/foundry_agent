# Attributes (PA1–PA20)

Pre-reads: [definitions.md](definitions.md) for the incident-type
classification, the Observed/Reported distinction, and the sanctioned
enumerations.

Requirement levels — **two only**. **Required** must be substantively
populated for the report to be complete. **Optional** improves the report but
never blocks; populate it when the content offers a basis, leave it empty
otherwise. Placeholders (TBD, N/A, "?", empty restatements) never count as
populated. A field that applies only to some incidents (a suspect, an arrest,
recovered property) is Optional — its group's Adequacy says when to press.

## FG1 — Report Identification & Classification

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA1 | Report Number | Required | Unique case/report identifier, format `IR-<YYYY>-<NNNNN>` (year, five-digit sequence, e.g. `IR-2026-04817`). Never reused. |
| PA2 | Incident Type | Required | The primary incident/offense, plus any additional offenses. Names one primary type per definitions.md (e.g. "Residential Burglary"). |
| PA3 | Report Status | Required | Exactly one of Draft / Under Review / Approved / Closed (see definitions.md). |
| PA4 | Reporting Officer | Required | The authoring officer's name AND badge/ID number (e.g. "Ofc. J. Rivera, #4471"). |

## FG2 — Date, Time & Location

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA5 | Date/Time Occurred | Required | When the incident occurred: an ISO date-time, or a range when exact time is unknown (e.g. "between 2026-06-01 22:00 and 2026-06-02 06:30"). |
| PA6 | Date/Time Reported | Required | When the incident was reported to police (ISO date-time). Never earlier than PA5. |
| PA7 | Incident Location | Required | The specific place of occurrence: street address, or a named place plus cross-streets. Not "the area". |

## FG3 — Involved Parties

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA8 | Complainant / Victim | Required | The reporting party and/or victim: name and at least one contact method, or "Unknown" with the reason it is unknown. |
| PA9 | Suspect(s) | Optional | Each suspect by name or physical/vehicle description, when the content identifies one. Never invented — absent a basis, leave empty. |
| PA10 | Witness(es) | Optional | Each witness and the substance of what they observed, when any exist. |

## FG4 — Narrative

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA11 | Incident Narrative | Required | The officer's chronological, factual account: what was observed, what parties reported, and the actions taken, in past tense. No legal conclusions. |
| PA12 | Statements Summary | Optional | A summary of statements taken from parties or witnesses, each attributed to its source. |

## FG5 — Evidence & Property

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA13 | Physical Evidence | Optional | Evidence collected, each with an item/tag number and a chain-of-custody note. Empty when none was collected. |
| PA14 | Property Involved | Optional | Property stolen, damaged, or recovered — description, quantity, and estimated value where known. |

## FG6 — Actions Taken & Disposition

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA15 | Actions Taken | Required | What the officer did — on scene and in follow-up (secured the scene, canvassed, photographed, notified detectives). |
| PA16 | Arrest / Citation | Optional | Arrest or citation details when made: arrestee, the charge(s) with statute where known, and the booking/citation number. |
| PA17 | Case Disposition | Required | The current investigative status: exactly one sanctioned disposition (see definitions.md). |

## FG7 — Review & Approval

| ID | Name | Requirement | What it is |
| --- | --- | --- | --- |
| PA18 | Reviewing Supervisor | Required | The supervisor who reviews and approves the report: name and badge/ID number. |
| PA19 | Approval Status & Date | Required | The approval decision (Approved / Returned for correction) and its ISO date. |
| PA20 | Distribution | Optional | Where the report is routed (records, detective unit, prosecutor, other agency), when the content specifies. |
