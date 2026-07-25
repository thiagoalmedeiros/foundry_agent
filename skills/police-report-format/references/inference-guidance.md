# Inference Guidance

Pre-reads: [attributes.md](attributes.md),
[statement-patterns.md](statement-patterns.md).

The user should never be asked for something their input already supports.
Input arrives in any shape — an officer's rough notes, a dispatch/CAD log, a
victim's written statement, a voicemail transcript — and it need not use this
skill's vocabulary. Read the WHOLE content and derive each attribute from
whatever is there.

## What counts as a basis

- **Directly stated** — the fact is written, in any phrasing. "I got there
  about 7am and the back door was jimmied" is a basis for PA5/PA6 timing, PA7
  scene, PA11 narrative, and PA2 (burglary).
- **Composable** — the pattern's ingredients are present even though the
  finished entry is not (see statement-patterns.md). A timeline, an
  observation, and a party statement anywhere in the content ARE a basis for
  the PA11 narrative — compose it and present it for confirmation.
- **Strongly implied** — a fact a careful reader would accept without new
  information: "recovered the stolen bike two blocks away" implies PA14
  property (recovered) and informs PA17 (Cleared / Recovered).
- **Combinable across passages** — facts scattered across distant sections
  combine: a dispatch time (PA6), a victim's account of when they left (PA5),
  and a neighbor's sighting (PA10 witness).

## What does NOT count

- A topic mention with no content ("should probably note the camera
  footage") does not populate PA13.
- Your own knowledge of what similar incidents usually involve. Fill from the
  content, or mark the attribute missing.
- Placeholders in the source ("suspect TBD") — carry the gap, not the
  placeholder.

## Attitude

Mark an attribute missing ONLY when the content carries no basis whatsoever.
Everything marked missing becomes a question the user must answer, so
inference left on the table costs them work. A defensible inferred value the
user can correct in one word beats a question they must answer from scratch.
Longer input means MORE populated attributes, not more questions.

## Load-bearing facts: ask, never invent

Infer aggressively — but a police report is a legal record, and a wrong fact
here can taint a case or defame a person. When the content gives no basis for
these, mark them missing so the interview ASKS. Never default them, and never
present a guessed value as a suggestion — a wrongly named suspect or a
fabricated charge is still false.

- **PA5 Date/Time Occurred** — a real time or window from the content. There
  is no safe default; "today" is a guess, not a fact.
- **PA9 Suspect(s)** — only a person the content identifies or describes.
  Never name a suspect the content does not; a wrongly asserted suspect is
  worse than a gap.
- **PA16 Arrest / Citation charges** — the actual charge(s). Never invent a
  statute or a charge the content does not state.
- **PA8 Complainant / Victim identity** — the named party, or "Unknown" with a
  reason. Do not guess an identity.

Everything population-guidance gives a safe default — Status Draft, a
provisional `IR-<YYYY>-00001` number — is inferred and flagged for
confirmation, not asked from scratch. The line is: default the boilerplate,
ask the facts.
