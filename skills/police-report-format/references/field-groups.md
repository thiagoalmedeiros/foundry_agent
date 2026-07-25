# Field Groups

Pre-reads: [definitions.md](definitions.md) for the incident-type
classification and the Observed/Reported distinction,
[attributes.md](attributes.md) for what each PAn means.

The interview works one group at a time, in the order declared here, and
advances only when the current group's **Adequacy** rules pass. These groups
are the source of record: re-cluster an attribute here and the interview's
shape follows with no code change. Every attribute belongs to exactly one
group.

Each group declares a **Framing** line (the sentence that opens the group's
conversation, verbatim), its **Attributes** row, and an **Adequacy**
paragraph (what "done" means for the group). Adequacy is judged on Required
attributes only; Optional attributes never block, but the Adequacy prose says
when the content should have surfaced one.

### FG1 — Report Identification & Classification

**Framing:** Let's start with the basics — the report number, what kind of incident this is, and who's writing it up.

| Field | Value |
| --- | --- |
| Attributes | PA1 Report Number, PA2 Incident Type, PA3 Report Status, PA4 Reporting Officer |

**Adequacy:** PA1–PA4 are all substantively populated. PA1 matches the
`IR-<YYYY>-<NNNNN>` format. PA2 names one primary incident type from the
classification. PA3 is exactly one of Draft/Under Review/Approved/Closed. PA4
gives the officer's name and badge/ID number. No value is a placeholder.

### FG2 — Date, Time & Location

**Framing:** Now let's pin down exactly when this happened, when it was reported, and where.

| Field | Value |
| --- | --- |
| Attributes | PA5 Date/Time Occurred, PA6 Date/Time Reported, PA7 Incident Location |

**Adequacy:** PA5 is an ISO date-time or an explicit range. PA6 is an ISO
date-time no earlier than PA5. PA7 names a specific address or place with
cross-streets — not a vague area.

### FG3 — Involved Parties

**Framing:** Who's involved? Let's get the complainant or victim down first, then any suspects or witnesses.

| Field | Value |
| --- | --- |
| Attributes | PA8 Complainant / Victim, PA9 Suspect(s), PA10 Witness(es) |

**Adequacy:** PA8 names the complainant/victim with a contact method, or
"Unknown" with a reason. PA9 and PA10 are Optional and never block — but when
the content describes a suspect or a witness, capture them here rather than
leaving the detail buried in the narrative.

### FG4 — Narrative

**Framing:** This is the heart of the report — walk me through what happened, start to finish.

| Field | Value |
| --- | --- |
| Attributes | PA11 Incident Narrative, PA12 Statements Summary |

**Adequacy:** PA11 is a chronological, past-tense account that answers who,
what, when, where, and how, keeping observed facts distinct from reported
ones and free of legal conclusions. PA12 is Optional — populate it when
statements were taken, each attributed to its source.

### FG5 — Evidence & Property

**Framing:** Let's account for any evidence collected and any property that was taken, damaged, or recovered.

| Field | Value |
| --- | --- |
| Attributes | PA13 Physical Evidence, PA14 Property Involved |

**Adequacy:** PA13 and PA14 are Optional and never block. When the narrative
mentions collected evidence, PA13 lists it with item numbers and custody
notes; when property was stolen, damaged, or recovered, PA14 itemizes it with
values. Silence is acceptable only when the incident genuinely involved
neither.

### FG6 — Actions Taken & Disposition

**Framing:** What did you do about it, and where does the case stand now?

| Field | Value |
| --- | --- |
| Attributes | PA15 Actions Taken, PA16 Arrest / Citation, PA17 Case Disposition |

**Adequacy:** PA15 states the concrete actions the officer took. PA17 is
exactly one sanctioned disposition. PA16 is Optional — populate it when an
arrest or citation was made, with arrestee, charges, and booking/citation
number.

### FG7 — Review & Approval

**Framing:** Finally, let's record who's reviewing and approving this report.

| Field | Value |
| --- | --- |
| Attributes | PA18 Reviewing Supervisor, PA19 Approval Status & Date, PA20 Distribution |

**Adequacy:** PA18 names the reviewing supervisor with badge/ID. PA19 states
the approval decision and its ISO date. PA20 is Optional — capture the
distribution when the content specifies it.

### Group → attribute coverage map

| Group | Attributes |
| --- | --- |
| FG1 — Report Identification & Classification | PA1–PA4 |
| FG2 — Date, Time & Location | PA5–PA7 |
| FG3 — Involved Parties | PA8–PA10 |
| FG4 — Narrative | PA11–PA12 |
| FG5 — Evidence & Property | PA13–PA14 |
| FG6 — Actions Taken & Disposition | PA15–PA17 |
| FG7 — Review & Approval | PA18–PA20 |

All 20 attributes are covered exactly once.
