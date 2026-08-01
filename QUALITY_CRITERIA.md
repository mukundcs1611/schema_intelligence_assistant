# QUALITY CRITERIA
## Schema Intelligence Assistant — JD R025606

---

## 1. Detection Thresholds

### The Core Asymmetry

A missed PII column is a compliance incident.
A false positive costs a PS team member 30 seconds.

This asymmetry drives every number below.
Optimise for recall. Accept lower precision.

### Targets

| Metric | Target | Reasoning |
|---|---|---|
| Recall | ≥ 0.90 | Compliance risk of misses outweighs cost of false positives |
| Precision | ≥ 0.70 | False positives go to review queue — cheap to dismiss |

### Confidence Thresholds

| Confidence | Decision | Reasoning |
|---|---|---|
| ≥ 0.80 | Auto-configure | High enough signal to act without human review |
| 0.40 – 0.79 | Review queue | Uncertain — human decides |
| < 0.40 | Not PII | Insufficient evidence from both rule layer and LLM |

**Default threshold: 0.80. Tunable per customer deployment via configuration.**

Any column the detector flags as PII with confidence below 0.80
goes to the review queue — it is never silently dropped.

### Threshold as a Failure Signal

The confidence threshold is also a health metric.

If the threshold must drop below 0.60 to maintain
auto-configuration rate ≥ 80%, the tool's confidence
scores are poorly calibrated for that customer's schema.
This is a failure condition — not a tuning opportunity.

```
Healthy:   threshold 0.80, auto-config rate ≥ 80%
Warning:   threshold 0.70, auto-config rate ≥ 80%
Failure:   threshold < 0.60 to achieve auto-config rate ≥ 80%
```

---

## 2. Test Data Plan

### Development Validation: Synthetic Golden Set

A 30-column labelled dataset created before implementation.

**Composition:**
- 15 PII columns / 15 non-PII columns
- Covers ≥ 8 of the 10 required PII categories
- Three difficulty tiers

**Mandatory edge cases — the detector must handle these:**

| Case | Example | Why |
|---|---|---|
| Obfuscated column name | `fld_23` with email samples | Rules fail on name — LLM must use samples |
| Non-English column name | `nome_completo`, `telefono` | Dictionary miss — LLM must use semantics |
| Masked sample values | `card_no` with `****-****-****-1234` | Regex fails — name must carry confidence |
| Unusual PII name | `national_insurance_number` | UK NATIONAL_ID — not obvious |
| Date that is not DOB | `ship_date`, `created_at` | DATE type ≠ DATE_OF_BIRTH |
| Numeric ID that is not PII | `transaction_id` BIGINT | 9-digit number — order ID not SSN |
| Org name not person | `company_name` | FULL_NAME is for persons only |
| Ambiguous reference | `ref_code` with `C-2024-001` | Contract ID or account number? |

**Honest limitation:** this golden set validates detector logic
on data we invented. It does not guarantee accuracy on real
customer schemas.

### Production Validation: Customer-Labelled Sample

Before the tool runs on a customer's full schema, the PS team
labels a 50-100 column sample from that customer's actual database.
This takes 2-3 hours — not 3-4 days.

The tool is then evaluated against these labels at the default
threshold. If recall on the sample is below 0.90, the threshold
is tuned and the sample re-evaluated before proceeding to the
full schema.

This is the only valid accuracy claim for a specific customer.
The synthetic golden set is a development tool, not a
production guarantee.

---

## 3. Day 1 Success Metric

The implementation is shippable when all of the following hold:

```
Recall on synthetic golden set      ≥ 0.90
Precision on synthetic golden set   ≥ 0.70
Threshold at default 0.80
Auto-configuration rate             ≥ 80%
Every PII detection below 0.80      in review queue (zero exceptions)
eval_report.md shows measured numbers, not claimed ones
```

Recall of 0.90 on synthetic data means the tool is ready
to be validated on real customer data — not that it is
production-ready. Production readiness is determined by
the customer-labelled sample validation described above.

---

## 4. What This System Will Not Guarantee

| Limitation | Mitigation |
|---|---|
| Recall varies by customer schema and naming conventions | Customer-labelled sample validation before full run |
| LLM errors are correlated — same blind spots as training data | Review queue is the uncorrelated human safety net |
| New PII naming patterns emerge over time | PS team corrections feed rule improvement pipeline |
| Confidence scores may be poorly calibrated on unseen schema types | Threshold floor of 0.60 triggers failure alert |

---

## 5. Architecture Stability Commitment

The pipeline contract — ColumnDescriptor in, DetectionResult out —
is the stable interface across all versions. Every component behind
it is replaceable. Every decision is logged to audit storage.

The system is designed for n+1 iterations:
- New PII categories added via configuration, not code changes
- Confidence threshold tunable per customer deployment
- Rule base grows from PS team corrections without redeployment
- Model swappable via environment variable

Targets in this document apply to v1. They will be revised
upward as customer-labelled validation data accumulates.
Any revision will be committed with a note explaining
what evidence drove the change.

