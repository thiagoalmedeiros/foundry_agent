# Canonical Template

The final Police Incident Report is Markdown with exactly these 12 sections,
in this order, each populated from the named attributes. Emit every section —
a section whose Optional attributes are all absent still appears, carrying
"None." An unresolved Required attribute is rendered as
`*Unresolved — see Advisory findings.*`

The document title line is `# Incident Report <PA1> — <PA2>`.

| # | Section heading | Populated from |
| --- | --- | --- |
| 1 | `## Report Summary` | PA1, PA2, PA3, PA4 as a four-row table (Report No. / Incident Type / Status / Reporting Officer) |
| 2 | `## Date, Time & Location` | PA5, PA6, PA7 as an Occurred / Reported / Location table |
| 3 | `## Involved Parties` | PA8, PA9, PA10 grouped under `### Complainant / Victim`, `### Suspect(s)`, `### Witness(es)` |
| 4 | `## Narrative` | PA11 |
| 5 | `## Statements` | PA12 |
| 6 | `## Evidence` | PA13 as an item list (tag #, description, custody) |
| 7 | `## Property` | PA14 as an item list (description, quantity, value, status) |
| 8 | `## Actions Taken` | PA15 |
| 9 | `## Arrest / Citation` | PA16 ("None." when no arrest or citation was made) |
| 10 | `## Disposition` | PA17 |
| 11 | `## Review & Approval` | PA18, PA19 as a Reviewing Supervisor / Decision / Date table |
| 12 | `## Distribution` | PA20 ("None recorded." when unspecified) |

## Advisory findings appendix

When the run banked unresolved attributes or advisory (PC/PR) findings,
append after section 12:

```markdown
## Advisory findings

- <attribute id + name>: unresolved — <what is missing>
- <PCn/PRn>: <one-sentence finding>
```

Omit the appendix entirely when there is nothing to report. This is the ONLY
place internal IDs (PAn, PCn, PRn) may appear — the 12 sections themselves
stay free of them.
