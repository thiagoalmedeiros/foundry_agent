# Population Guidance

Pre-reads: [attributes.md](attributes.md),
[statement-patterns.md](statement-patterns.md).

How to write each attribute WELL once a basis exists. Values are recorded
short and concrete — a reviewer should act on them without follow-up.

The identity/status defaults below (Status Draft, a provisional
`IR-<YYYY>-00001` number) are safe to fill and flag for confirmation without
asking. The load-bearing facts that
[inference-guidance.md](inference-guidance.md) marks *ask, never invent* —
the date/time occurred, a suspect's identity, the charges — are not: leave
them missing so the interview asks.

## Identity fields (FG1)

- **PA1** — propose `IR-<current year>-00001` when no case number is known and
  say the sequence is provisional.
- **PA2** — name the specific offense, then its category if useful
  ("Residential Burglary", not "a property thing"). List additional offenses
  after the primary, most serious first.
- **PA3** — a new report defaults to Draft unless the content says otherwise.
- **PA4** — promote a bare name to name-plus-badge when the content gives the
  number; if only a name is present, capture it and flag the missing badge.

## Time & place (FG2)

- **PA5/PA6** — normalize any date/time phrasing to ISO; when only a window is
  known, record the range ("between … and …"). Keep occurred ≤ reported.
- **PA7** — give the fullest address the content supports; add cross-streets
  when only a block or place name is known.

## Party fields (FG3)

Record each party with the party-record pattern. Promote a description to a
suspect entry (PA9) even without a name — a description is a valid basis; an
invented identity is not.

## Narrative field (PA11)

Write the account in past tense, chronological order, with the narrative
pattern. Keep observed facts distinct from reported statements, and keep legal
conclusions out — state what was seen and heard; charging is PA16, status is
PA17. Quantify where the content allows ("three rooms ransacked" beats "the
place was a mess").

## Evidence & property (FG5)

Prefer itemized, tagged entries ("Item 2 — laptop, silver, est. $900,
reported stolen") over prose ("some electronics were taken"). Note custody for
every collected item.

## Actions & disposition (FG6)

PA15 states concrete actions ("secured the scene, photographed the point of
entry, canvassed three neighbors"). PA17 is exactly one sanctioned
disposition; add a one-line reason when the content supports it.

## Review fields (FG7)

PA18 names the reviewing supervisor with badge/ID. PA19 pairs the decision
with an ISO date. Default neither — these are recorded when the review
happens, not guessed.
