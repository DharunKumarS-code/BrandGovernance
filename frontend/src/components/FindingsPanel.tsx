import { useState } from 'react';
import {
  EVIDENCE_STATUS_LABELS,
  FINDING_VERDICT_LABELS,
  formatApiError,
  submissionsApi,
  type EvidenceStatus,
  type Finding,
  type FindingSeverity,
  type Verdict,
} from '../api/client';

type Props = {
  submissionId: string;
  findings: Finding[];
  isOwner: boolean;
  onFindingUpdated: (updated: Finding) => void;
  onApplyCorrection: (content: string) => void;
};

const SEVERITY_CLASSES: Record<FindingSeverity, string> = {
  high: 'bg-red-50 text-red-700',
  medium: 'bg-amber-50 text-amber-700',
  low: 'bg-slate-100 text-slate-600',
};

const VERDICT_CLASSES: Record<Verdict, string> = {
  contradicted: 'bg-red-50 text-red-700',
  outdated: 'bg-amber-50 text-amber-700',
  unsupported: 'bg-slate-100 text-slate-600',
  verified: 'bg-teal/15 text-deep-blue',
  needs_review: 'bg-cyan/15 text-deep-blue',
};

const EVIDENCE_CLASSES: Record<EvidenceStatus, string> = {
  supported: 'bg-teal/15 text-deep-blue',
  contradicted: 'bg-red-50 text-red-700',
  insufficient: 'bg-slate-100 text-slate-600',
  needs_review: 'bg-cyan/15 text-deep-blue',
};

const STATUS_CLASSES: Record<string, string> = {
  open: 'bg-deep-blue/10 text-deep-blue',
  accepted: 'bg-teal/20 text-deep-blue',
  dismissed: 'bg-slate-100 text-slate-500',
};

function Badge({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${className}`}>{children}</span>;
}

export default function FindingsPanel({ submissionId, findings, isOwner, onFindingUpdated, onApplyCorrection }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState<Record<string, boolean>>({});
  const [evidenceError, setEvidenceError] = useState<Record<string, string | null>>({});
  const [suggestionBusy, setSuggestionBusy] = useState<Record<string, boolean>>({});
  const [suggestionError, setSuggestionError] = useState<Record<string, string | null>>({});
  const [decisionBusy, setDecisionBusy] = useState<Record<string, boolean>>({});
  const [decisionError, setDecisionError] = useState<Record<string, string | null>>({});
  const [previewContent, setPreviewContent] = useState<Record<string, string | null>>({});
  const [dismissReason, setDismissReason] = useState<Record<string, string>>({});

  if (findings.length === 0) {
    return <p className="text-sm text-slate-500">No findings yet. Run analysis on a submitted ("Submitted") revision to generate findings.</p>;
  }

  async function toggleExpand(finding: Finding) {
    const next = expandedId === finding.id ? null : finding.id;
    setExpandedId(next);
    if (next && !finding.evidence) {
      setEvidenceLoading((m) => ({ ...m, [finding.id]: true }));
      setEvidenceError((m) => ({ ...m, [finding.id]: null }));
      try {
        const res = await submissionsApi.evidence(submissionId, finding.id);
        onFindingUpdated({ ...finding, evidence: res.data });
      } catch (err) {
        setEvidenceError((m) => ({ ...m, [finding.id]: formatApiError(err) }));
      } finally {
        setEvidenceLoading((m) => ({ ...m, [finding.id]: false }));
      }
    }
  }

  async function handleGenerateSuggestion(finding: Finding) {
    setSuggestionBusy((m) => ({ ...m, [finding.id]: true }));
    setSuggestionError((m) => ({ ...m, [finding.id]: null }));
    try {
      const res = await submissionsApi.generateSuggestion(submissionId, finding.id);
      onFindingUpdated(res.data);
    } catch (err) {
      setSuggestionError((m) => ({ ...m, [finding.id]: formatApiError(err) }));
    } finally {
      setSuggestionBusy((m) => ({ ...m, [finding.id]: false }));
    }
  }

  async function handleAccept(finding: Finding) {
    setDecisionBusy((m) => ({ ...m, [finding.id]: true }));
    setDecisionError((m) => ({ ...m, [finding.id]: null }));
    try {
      const res = await submissionsApi.acceptSuggestion(submissionId, finding.id);
      onFindingUpdated(res.data.finding);
      setPreviewContent((m) => ({ ...m, [finding.id]: res.data.preview_content }));
    } catch (err) {
      setDecisionError((m) => ({ ...m, [finding.id]: formatApiError(err) }));
    } finally {
      setDecisionBusy((m) => ({ ...m, [finding.id]: false }));
    }
  }

  async function handleDismiss(finding: Finding) {
    setDecisionBusy((m) => ({ ...m, [finding.id]: true }));
    setDecisionError((m) => ({ ...m, [finding.id]: null }));
    try {
      const res = await submissionsApi.dismissSuggestion(submissionId, finding.id, dismissReason[finding.id]?.trim() || undefined);
      onFindingUpdated(res.data);
    } catch (err) {
      setDecisionError((m) => ({ ...m, [finding.id]: formatApiError(err) }));
    } finally {
      setDecisionBusy((m) => ({ ...m, [finding.id]: false }));
    }
  }

  return (
    <ul className="space-y-3">
      {findings.map((finding) => {
        const expanded = expandedId === finding.id;
        const busy = decisionBusy[finding.id] ?? false;

        return (
          <li key={finding.id} className="rounded border border-slate-200 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="bg-navy/10 text-navy">{finding.category}</Badge>
              <Badge className={SEVERITY_CLASSES[finding.severity]}>{finding.severity}</Badge>
              <Badge className={VERDICT_CLASSES[finding.verdict]}>{FINDING_VERDICT_LABELS[finding.verdict]}</Badge>
              <Badge className={STATUS_CLASSES[finding.status]}>{finding.status === 'open' ? 'pending' : finding.status}</Badge>
              <button onClick={() => toggleExpand(finding)} className="ml-auto text-xs font-medium text-deep-blue hover:underline">
                {expanded ? 'Hide details' : 'View evidence & suggestion'}
              </button>
            </div>

            <p className="mt-2 rounded bg-slate-50 px-2 py-1 text-sm italic text-slate-700">&ldquo;{finding.span_text}&rdquo;</p>
            <p className="mt-1 text-sm text-slate-600">{finding.explanation}</p>

            {expanded && (
              <div className="mt-3 space-y-3 border-t border-slate-100 pt-3">
                {/* --- Evidence --- */}
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Evidence</p>
                  {evidenceLoading[finding.id] && <p className="text-sm text-slate-500">Validating evidence...</p>}
                  {evidenceError[finding.id] && <p className="text-sm text-red-600">{evidenceError[finding.id]}</p>}
                  {!evidenceLoading[finding.id] && finding.evidence && (
                    <div className="rounded border border-slate-100 bg-slate-50 p-2 text-sm">
                      <div className="mb-1 flex items-center gap-2">
                        <Badge className={EVIDENCE_CLASSES[finding.evidence.status]}>{EVIDENCE_STATUS_LABELS[finding.evidence.status]}</Badge>
                        {finding.evidence.quote && (
                          <span className={finding.evidence.quote_verified ? 'text-xs text-teal' : 'text-xs text-amber-600'}>
                            {finding.evidence.quote_verified ? '✓ Quotation verified' : '⚠ Quotation could not be verified'}
                          </span>
                        )}
                      </div>
                      <p className="text-slate-600">{finding.evidence.reason}</p>
                      {finding.evidence.guideline_doc_title ? (
                        <p className="mt-1 text-xs text-slate-500">
                          Source: {finding.evidence.guideline_doc_title}
                          {finding.evidence.page != null ? `, page ${finding.evidence.page}` : ''}
                        </p>
                      ) : finding.evidence.source_type === 'asset' && !finding.evidence.unavailable ? (
                        <p className="mt-1 text-xs text-slate-400">Source: this organisation&apos;s approved brand assets.</p>
                      ) : finding.evidence.source_type && !finding.evidence.unavailable ? (
                        <p className="mt-1 text-xs text-slate-400">
                          Source: this organisation&apos;s {finding.evidence.source_type.replace('_', ' ')} rule (no PDF page reference
                          available for this evidence type).
                        </p>
                      ) : finding.evidence.unavailable ? (
                        <p className="mt-1 text-xs text-slate-400">No source reference is available for this finding.</p>
                      ) : null}
                      {finding.evidence.source_text && (
                        <p className="mt-1 rounded bg-white p-2 text-xs text-slate-500">{finding.evidence.source_text}</p>
                      )}
                    </div>
                  )}
                </div>

                {/* --- Suggestion --- */}
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Suggested Correction</p>
                  {suggestionError[finding.id] && <p className="text-sm text-red-600">{suggestionError[finding.id]}</p>}
                  {finding.correction ? (
                    <div className="rounded border border-slate-100 bg-slate-50 p-2 text-sm">
                      {finding.correction.corrected_span ? (
                        <p className="rounded bg-teal/10 px-2 py-1 text-deep-blue">&ldquo;{finding.correction.corrected_span}&rdquo;</p>
                      ) : (
                        <p className="text-slate-500">No safe correction could be generated -- human review is required.</p>
                      )}
                      <p className="mt-1 text-xs text-slate-500">{finding.correction.rationale}</p>
                      {finding.correction.requires_human_review && (
                        <p className="mt-1 text-xs font-medium text-amber-600">Requires human review before applying.</p>
                      )}
                    </div>
                  ) : (
                    <button
                      onClick={() => handleGenerateSuggestion(finding)}
                      disabled={suggestionBusy[finding.id]}
                      className="rounded border border-deep-blue px-3 py-1.5 text-xs font-medium text-deep-blue hover:bg-deep-blue/5 disabled:opacity-50"
                    >
                      {suggestionBusy[finding.id] ? 'Generating...' : 'Generate suggestion'}
                    </button>
                  )}
                </div>

                {/* --- Decision --- */}
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Your Decision</p>
                  {decisionError[finding.id] && <p className="text-sm text-red-600">{decisionError[finding.id]}</p>}
                  {!isOwner && finding.status === 'open' && (
                    <p className="text-xs text-slate-400">Only the submission&apos;s creator can accept or dismiss suggestions.</p>
                  )}
                  {finding.status === 'open' && isOwner && (
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        onClick={() => handleAccept(finding)}
                        disabled={busy}
                        className="rounded bg-teal px-3 py-1.5 text-xs font-medium text-navy hover:opacity-90 disabled:opacity-50"
                      >
                        Accept
                      </button>
                      <input
                        type="text"
                        placeholder="Optional dismiss reason"
                        value={dismissReason[finding.id] ?? ''}
                        onChange={(e) => setDismissReason((m) => ({ ...m, [finding.id]: e.target.value }))}
                        className="rounded border px-2 py-1 text-xs"
                      />
                      <button
                        onClick={() => handleDismiss(finding)}
                        disabled={busy}
                        className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                      >
                        Dismiss
                      </button>
                    </div>
                  )}
                  {finding.status === 'accepted' && (
                    <div>
                      <p className="text-xs text-deep-blue">Accepted{finding.decided_at ? ` on ${new Date(finding.decided_at).toLocaleString()}` : ''}.</p>
                      {previewContent[finding.id] && (
                        <button
                          onClick={() => onApplyCorrection(previewContent[finding.id]!)}
                          className="mt-2 rounded bg-deep-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-navy"
                        >
                          Apply to draft
                        </button>
                      )}
                    </div>
                  )}
                  {finding.status === 'dismissed' && (
                    <p className="text-xs text-slate-500">
                      Dismissed{finding.dismiss_reason ? ` -- ${finding.dismiss_reason}` : ''}
                      {finding.decided_at ? ` on ${new Date(finding.decided_at).toLocaleString()}` : ''}.
                    </p>
                  )}
                </div>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
