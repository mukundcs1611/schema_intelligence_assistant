# Customer Value

## 1. Baseline problem

Onboarding stalls at masking configuration. A customer connects a database,
sees hundreds of columns, and has no way to tell which hold PII or which
masking function applies. The professional services team absorbs this
manually — 3–4 days per customer. It is a scale problem, not a knowledge
problem: every new customer costs the same fixed PS days regardless of how
standard the schema is.

## 2. Measurable outcome — 30-day pilot, 3 customers

| Metric | Baseline | Target | Source |
|---|---|---|---|
| PS time per onboarding | 3–4 days | < 4 hours | PS time log |
| Auto-configuration rate | — | ≥ 80% | `audit_log.db` |
| Review-queue acceptance | — | ≥ 70% | `audit_log.db` — `human_decision` vs suggestion |
| Missed PII | — | zero | PS spot-check of 10% of auto-configured columns |

PS time is the value metric; the others explain it. Review-queue acceptance
is the one that separates a tool that routes uncertainty correctly from one
that routes it correctly but suggests badly.

## 3. Risks and limitations

**Recall varies by schema.** 1.00 recall on the 30-column golden set is
against data we wrote ourselves. Mitigation: PS labels a 50–100 column
sample from the customer's real database (2–3 hours), and we validate
against that before any full run.

**Confidently wrong answers.** The classifier can be wrong at high
confidence. Mitigation: rule/LLM disagreement is capped below the
auto-configure threshold, so conflicts always reach a human; an ungrounded
low-confidence "not PII" is queued rather than silently cleared.

**Known false positives.** Short keywords match inside longer words —
"pan" inside "company". Five known cases, all routed to review, documented
in `BLOCKERS.md`.

## 4. What we would not automate

**Config sign-off.** The tool generates a configuration; it never executes
one. SSN columns masked as EMAIL at scale is worse than the manual process
it replaced.

**Novel categories.** A biometric hash or proprietary national ID the tool
has never seen is a human definition, not an inference.

**Compliance interpretation.** Whether a column is personal data under GDPR
Article 4 is a legal question. We mask what is identified; the customer's
compliance team decides what must be masked.

**Rule promotion.** LLM-suggested keywords are logged for human approval,
never auto-applied. An unreviewed suggestion entering the deterministic
layer would destroy the property that layer exists for.
