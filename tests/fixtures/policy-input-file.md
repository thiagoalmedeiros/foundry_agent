# Meridian Remote Work Security Assessment

Internal review prepared by the Security Engineering group of Meridian
Financial Technologies. Circulated to the policy working group as source
material for the forthcoming remote-work security policy. This is an
assessment, not the policy itself — obligations proposed here are drafts.

## Current situation

Since the 2024 flexible-work rollout, 62% of Meridian staff work remotely at
least three days a week. The rollout shipped without a security baseline:
remote logins are permitted from unmanaged personal devices, and roughly a
third of daily VPN sessions originate from clients with no disk encryption
attested. Three corporate laptops carrying cached customer records were lost
in the last quarter alone; none had remote-wipe enrolled. Help-desk records
show a steady rise in credential-sharing workarounds when the VPN degrades,
peaking during the March outage tracked in ticket RW-1408.

The audit sample behind these figures covered 480 remote sessions across
February and March. Of those, 71 sessions authenticated without hardware MFA,
and 9 reached the payments staging environment from networks flagged as
high-risk by the egress monitor. The exposure is concentrated in engineering
and customer operations, the two groups with the broadest data access.

## Drivers

- Contractual: two enterprise customers now require evidence of a remote
  access policy with annual attestation before renewal.
- Regulatory: the payments regulator's outsourcing guideline expects
  documented controls over remote access to cardholder-adjacent systems.
- Incident history: the Q1 laptop losses and ticket RW-1408 demonstrate that
  the residual risk is being realized, not hypothetical.

## Proposed obligations (draft)

1. All remote access to production and staging systems must traverse the
   corporate VPN with device posture checks at connect time.
2. Hardware-backed MFA must be required for every remote session touching
   customer data, with no SMS fallback.
3. Personal devices must be enrolled in mobile device management before any
   corporate data is synchronized to them.
4. Remote-wipe capability must be verified quarterly for every enrolled
   device that caches customer records.
5. Credential sharing must be treated as a reportable security event, with a
   24-hour reporting window from discovery.

## Open questions for the policy working group

- Ownership: Security Engineering proposes the CISO as accountable owner,
  with quarterly reporting to the Risk Committee.
- Scope boundary: contractors on customer-operations tooling are in scope;
  the offshore QA vendor's lab network is proposed as an explicit exclusion
  because it is governed by its own contractual controls.
- Exceptions: field sales occasionally demos from customer sites with no VPN
  egress; the working group must decide whether a time-boxed exception
  process is acceptable and who may grant it.
- Review cadence: given the regulator's 12-month expectation for security
  policies, the group should confirm an annual review with incident-triggered
  early review.

Even with every proposed obligation adopted, unmanaged home-network equipment
remains outside Meridian's control, and the audit sample shows posture data is
self-reported for 11% of legacy clients. Compliance must account for this
residual risk.
