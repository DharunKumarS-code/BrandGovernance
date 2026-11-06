"""Pure rule-based checks -- terminology and claim-policy. No LLM
involvement at all; these always run, AI-available or not, satisfying
section F's "the system must remain useful even when AI services are
unavailable" for the two check types it names explicitly."""

import re

from app.models import ClaimPolicy, ClaimPolicyStatus, FindingSeverity, Terminology, Verdict


class RuleFinding:
    """Plain container -- not a DB model. The analysis orchestrator turns
    these into FindingCreate documents, filling in the fields (revision_id,
    organisation_id, source=rule, ...) that only it has."""

    def __init__(
        self,
        *,
        category: str,
        severity: FindingSeverity,
        span_text: str,
        explanation: str,
        verdict: Verdict,
        evidence_record_type: str,
        evidence_record_id,
        evidence_quote: str | None,
        suggestion: str | None = None,
    ):
        self.category = category
        self.severity = severity
        self.span_text = span_text
        self.explanation = explanation
        self.verdict = verdict
        self.evidence_record_type = evidence_record_type
        self.evidence_record_id = evidence_record_id
        self.evidence_quote = evidence_quote
        self.suggestion = suggestion


def check_terminology(content: str, terminology_rows: list[Terminology]) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    for term in terminology_rows:
        for variant in term.banned_variants:
            for match in re.finditer(re.escape(variant), content, re.IGNORECASE):
                findings.append(
                    RuleFinding(
                        category="terminology",
                        severity=FindingSeverity.MEDIUM,
                        span_text=match.group(0),
                        explanation=f"Uses '{match.group(0)}' instead of the approved term '{term.preferred_term}'. {term.reason}",
                        verdict=Verdict.CONTRADICTED,
                        evidence_record_type="terminology",
                        evidence_record_id=term.id,
                        evidence_quote=term.reason,
                        suggestion=f"Use '{term.preferred_term}' instead.",
                    )
                )
    return findings


def check_claim_policies(content: str, policy_rows: list[ClaimPolicy]) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    for policy in policy_rows:
        for match in re.finditer(re.escape(policy.pattern), content, re.IGNORECASE):
            if policy.status == ClaimPolicyStatus.BANNED:
                findings.append(
                    RuleFinding(
                        category="claim",
                        severity=FindingSeverity.HIGH,
                        span_text=match.group(0),
                        explanation=f"'{match.group(0)}' matches a banned claim pattern and must not be used.",
                        verdict=Verdict.CONTRADICTED,
                        evidence_record_type="claim_policy",
                        evidence_record_id=policy.id,
                        evidence_quote=policy.pattern,
                    )
                )
            elif policy.status == ClaimPolicyStatus.NEEDS_EVIDENCE:
                findings.append(
                    RuleFinding(
                        category="claim",
                        severity=FindingSeverity.MEDIUM,
                        span_text=match.group(0),
                        explanation=f"'{match.group(0)}' requires supporting evidence before publication.",
                        verdict=Verdict.NEEDS_REVIEW,
                        evidence_record_type="claim_policy",
                        evidence_record_id=policy.id,
                        evidence_quote=policy.required_disclaimer or policy.pattern,
                        suggestion=policy.required_disclaimer,
                    )
                )
            # APPROVED patterns are not findings -- nothing to flag.
    return findings
