import { useState } from 'react';
import {
  formatApiError,
  REVIEW_DECISION_LABELS,
  submissionsApi,
  type DemoUser,
  type Review,
  type ReviewDecision,
  type Submission,
  type SubmissionStatus,
} from '../api/client';

type Props = {
  submissionId: string;
  submissionStatus: SubmissionStatus;
  isReviewerEligible: boolean; // role is reviewer/admin AND not this submission's own creator
  reviews: Review[];
  users: DemoUser[];
  onDecisionMade: (submission: Submission, review: Review) => void;
};

const DECISION_BADGE_CLASSES: Record<ReviewDecision, string> = {
  approved: 'bg-teal/20 text-deep-blue',
  rejected: 'bg-red-100 text-red-700',
  changes_requested: 'bg-amber-100 text-amber-700',
};

export default function ReviewPanel({ submissionId, submissionStatus, isReviewerEligible, reviews, users, onDecisionMade }: Props) {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reviewerName(reviewerId: string) {
    return users.find((u) => u.id === reviewerId)?.name ?? reviewerId;
  }

  async function handleDecision(action: 'approve' | 'reject' | 'request-changes') {
    if (action !== 'approve' && !comment.trim()) {
      setError('A comment is required for this decision.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res =
        action === 'approve'
          ? await submissionsApi.approve(submissionId, comment.trim() || undefined)
          : action === 'reject'
            ? await submissionsApi.reject(submissionId, comment.trim())
            : await submissionsApi.requestChanges(submissionId, comment.trim());
      setComment('');
      onDecisionMade(res.data.submission, res.data.review);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const canDecideNow = submissionStatus === 'pending_review' && isReviewerEligible;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-3 font-semibold text-navy">Review Decision</h3>

      {submissionStatus === 'pending_review' && !isReviewerEligible && (
        <p className="mb-3 text-xs text-slate-400">Awaiting a reviewer's decision.</p>
      )}

      {canDecideNow && (
        <div className="mb-4">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Review comment (required for Reject / Request Changes)"
            className="mb-2 h-20 w-full rounded border px-3 py-2 text-sm"
          />
          {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => handleDecision('approve')}
              disabled={busy}
              className="rounded bg-teal px-4 py-2 text-sm font-medium text-navy hover:opacity-90 disabled:opacity-50"
            >
              {busy ? 'Working...' : 'Approve'}
            </button>
            <button
              onClick={() => handleDecision('request-changes')}
              disabled={busy}
              className="rounded border border-amber-500 px-4 py-2 text-sm font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50"
            >
              Request Changes
            </button>
            <button
              onClick={() => handleDecision('reject')}
              disabled={busy}
              className="rounded border border-red-400 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </div>
      )}

      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Review History</h4>
      {reviews.length === 0 ? (
        <p className="text-sm text-slate-500">No review decisions yet.</p>
      ) : (
        <ul className="space-y-2">
          {reviews.map((r) => (
            <li key={r.id} className="rounded border border-slate-100 bg-slate-50 p-2 text-sm">
              <div className="flex items-center gap-2">
                <span className={`rounded px-2 py-0.5 text-xs font-medium ${DECISION_BADGE_CLASSES[r.decision]}`}>
                  {REVIEW_DECISION_LABELS[r.decision]}
                </span>
                <span className="text-xs text-slate-500">
                  by {reviewerName(r.reviewer_id)} on {new Date(r.created_at).toLocaleString()}
                </span>
              </div>
              {r.comment && <p className="mt-1 text-slate-600">{r.comment}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
