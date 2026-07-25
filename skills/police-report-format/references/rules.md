# Rules (PR1–PR14)

Advisory quality rules. Violations are reported as findings with the rule
ID; they never block a group (missing Required attributes are what block —
see validation.md).

## Identity (FG1)

- **PR1** — PA1 matches `IR-<YYYY>-<NNNNN>` exactly (year, five-digit
  sequence) and is never reused.
- **PR2** — PA2 names exactly one primary incident type from the
  classification; additional offenses are listed after it, most serious
  first.
- **PR3** — PA3 only ever moves Draft → Under Review → Approved → Closed.
- **PR4** — PA4 gives the officer's name AND badge/ID number, never a name
  alone.

## Time & place (FG2)

- **PR5** — PA5 and PA6 are ISO date-times (a range is allowed for PA5); PA6
  is never earlier than PA5.
- **PR6** — PA7 is a specific address or a named place with cross-streets —
  "near the park" and "downtown" are findings.

## Parties (FG3)

- **PR7** — PA8 gives a name and at least one contact method, or "Unknown"
  with a stated reason; a bare blank is a finding.
- **PR8** — PA9 records only suspects the content identifies; a description
  ("white sedan, partial plate 7XY") counts, an invented identity does not.

## Narrative (FG4)

- **PR9** — PA11 is past tense and chronological, with observed facts kept
  distinct from reported statements (PC2/PC6).
- **PR10** — PA11 contains no legal conclusions ("the suspect committed
  burglary"); it states the observed facts and leaves the charge to PA16 and
  the disposition to PA17.

## Evidence & property (FG5)

- **PR11** — every PA13 entry carries an item/tag number and a
  chain-of-custody note.
- **PR12** — every PA14 entry gives a description, a quantity, and an
  estimated value where known.

## Actions & review (FG6–FG7)

- **PR13** — when PA16 records an arrest or citation, it names the arrestee,
  the charge(s) with statute where known, and the booking/citation number.
- **PR14** — PA19 names the approving supervisor and an ISO date; an
  approval without a date is a finding.
