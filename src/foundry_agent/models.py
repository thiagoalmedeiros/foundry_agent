"""Structured output contracts for the POC agents.

These models are passed as ``response_format`` to agent runs — the standard
Agent Framework structured-output mechanism. They describe the *agents'*
judgments, never the format itself: field groups, attributes, and rules are
read at runtime out of the ``policy-report-format`` skill (see
:mod:`foundry_agent.agents`), so re-clustering a group in the skill changes
this workflow's behaviour with no code change.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Whether a finding blocks completion or is advisory only.

    Missing required attributes block; characteristic (PC) and rule (PR)
    quality findings are advisory per the plan's termination policy.
    """

    BLOCKING = "blocking"
    ADVISORY = "advisory"


class CaptureStatus(str, Enum):
    """The fate of one attribute in an elicitation pass (elicitation EL9)."""

    CLOSED = "closed"
    UNRESOLVED = "unresolved"
    SKIPPED = "skipped"


class Finding(BaseModel):
    """An advisory quality finding against a characteristic (PC) or rule (PR)."""

    reference_id: str = Field(description="Characteristic or rule ID, e.g. 'PC5' or 'PR8'.")
    severity: Severity = Field(default=Severity.ADVISORY)
    summary: str = Field(description="One-sentence statement of the issue.")


class ValidationResult(BaseModel):
    """Validation output: completion verdict with the gaps that remain."""

    complete: bool = Field(description="True when no blocking gaps remain in scope.")
    missing_attribute_ids: list[str] = Field(default_factory=list)
    advisory_findings: list[Finding] = Field(default_factory=list)
    rationale: str = Field(description="Short justification for the verdict.")


class CapturedValue(BaseModel):
    """One attribute's value as elicitation recorded it (elicitation EL7)."""

    attribute_id: str = Field(
        description="The attribute this value fills, e.g. 'PA7' — preserve the ID exactly."
    )
    value: str = Field(description="The value as captured from the user, ready to record.")
    status: CaptureStatus = Field(
        default=CaptureStatus.CLOSED,
        description="'closed' when the value is adequate, 'unresolved' when the user "
        "could not supply an adequate one, 'skipped' when the attribute did not apply.",
    )


class ConversationTurn(BaseModel):
    """One turn of the CURRENT field group's elicitation conversation.

    The agent is re-run with the user's reply on the same session until it sets
    ``conversation_complete`` for the group in hand (elicitation EL4); the
    interview then advances to the next group. A turn clarifies only the current
    group's points, in plain language, never attribute IDs.
    """

    message: str = Field(
        description="The user-facing text for this turn — a natural, plain-language "
        "message clarifying the CURRENT field group's points: confirming what was "
        "inferred from the content and asking for what is missing, guided by the "
        "elicitation skill (EL4/EL14). Never attribute IDs, group codes, or rule IDs."
    )
    conversation_complete: bool = Field(
        description="True ONLY when THIS group's Adequacy is satisfied or its open "
        "points are recorded unresolved — the signal to advance to the next group. "
        "Never merely because the user replied."
    )
    captured: list[CapturedValue] = Field(
        default_factory=list,
        description="Every value captured for this group so far, cumulative — "
        "resend values from earlier turns, do not send only the latest.",
    )


class FieldGroup(BaseModel):
    """One field group exactly as the policy-report-format skill declares it."""

    group_id: str = Field(description="The group's ID as written, e.g. 'FG1'.")
    name: str = Field(description="The group's name, e.g. 'Identification & Classification'.")
    heading: str = Field(
        description="The group's heading verbatim, "
        "e.g. '### FG1 — Identification & Classification'."
    )
    framing: str = Field(
        description="The group's **Framing:** line verbatim — elicitation opens the "
        "group's first turn with it (elicitation EL12). Give the sentence only, "
        "without the '**Framing:**' label that precedes it in the document."
    )
    attribute_ids: list[str] = Field(
        description="Every attribute ID in this group, EXPANDED one per entry: "
        "['PA1', 'PA2', ...] — never a range string like 'PA1-PA6'."
    )
    adequacy: str = Field(description="The group's **Adequacy:** rules verbatim.")

    def framing_line(self) -> str:
        """The framing sentence with the reference's own field label stripped.

        EL12 wants the line verbatim; EL10 forbids surfacing internal labels.
        ``**Framing:**`` is the reference file's field label, not part of the
        sentence, and it reached users verbatim in the 07201817 QA run — so it
        is removed here rather than relying on the agent to omit it.
        """
        line = self.framing.strip()
        for label in ("**Framing:**", "*Framing:*", "Framing:"):
            if line.startswith(label):
                return line[len(label) :].strip()
        return line


class FieldGroups(BaseModel):
    """Discovery output: the format skill's own field groups, in declared order.

    Populated by an agent reading ``field-groups.md`` at runtime — never
    hardcoded; re-clustering a group in the skill changes this with no code
    change (elicitation EL8).
    """

    groups: list[FieldGroup] = Field(
        description="Every field group the format skill declares, in the order it declares them."
    )
