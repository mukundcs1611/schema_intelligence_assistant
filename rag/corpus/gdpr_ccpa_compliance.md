# GDPR and CCPA Compliance in Data Masking Workflows

## GDPR Requirements and Data Masking

GDPR does not name "data masking" as a specific required control, but its
data minimization and purpose-limitation principles (Article 5) are
directly relevant to non-production environments: personal data should not
be processed for a purpose -- such as software testing -- beyond what it
was originally collected for, unless it has been rendered non-personal.

Masked data, when the masking is genuinely irreversible (no key, no
mapping table retained outside the job's runtime), falls outside GDPR's
definition of personal data for the environment it lives in, because it no
longer relates to an identified or identifiable natural person. This is
why `consistent_mapping` in this platform's masking functions is
per-job-run only -- no persistent lookup table is kept that could re-link a
masked value back to the original data subject after the job completes.

Right-to-erasure (Article 17) requests still apply to the *source* system,
not masked copies -- since masked copies contain no personal data, there is
nothing in them to erase on a per-subject basis.

## CCPA Requirements and Data Masking

CCPA's definition of "deidentified" data (Civ. Code 1798.140) requires that
data cannot reasonably be used to infer information about, or otherwise be
linked to, a particular consumer, and that the business has implemented
technical safeguards prohibiting re-identification. Consistent-mapping
masking within a single job run satisfies the "cannot reasonably be
linked" bar as long as the mapping is not persisted or shared outside that
run -- persisting a name-to-substitute mapping across jobs would undermine
the deidentification claim.

## Audit Trail and Compliance Reporting

Every masking decision -- both the automated classification (is this
column PII, what category, what confidence) and the resulting masking
action -- is written to an audit log at decision time. This is what turns
"we mask sensitive data" into an answerable compliance question: for any
column, at any point, the audit trail can show what was detected, what
confidence the detection carried, whether it was auto-configured or
routed to human review, and what masking function was ultimately applied.
This trail is the artifact compliance teams request during an audit or a
regulator inquiry, and it is generated automatically as a byproduct of
running masking jobs, not assembled after the fact.
