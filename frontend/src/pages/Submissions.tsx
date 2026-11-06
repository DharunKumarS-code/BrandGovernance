import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { formatApiError, submissionsApi, SUBMISSION_STATUS_LABELS, type Submission } from '../api/client';
import AsyncState from '../components/AsyncState';
import PageHeader from '../components/PageHeader';
import { useDemoContext } from '../context/DemoContext';

const STATUS_STYLES: Record<string, string> = {
  draft: 'bg-slate-200 text-slate-600',
  pending_review: 'bg-cyan/20 text-deep-blue',
  changes_requested: 'bg-amber-100 text-amber-700',
  approved: 'bg-teal/20 text-deep-blue',
  rejected: 'bg-red-100 text-red-700',
};

export default function Submissions() {
  const { users, userId } = useDemoContext();
  const [items, setItems] = useState<Submission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    submissionsApi
      .list()
      .then((res) => setItems(res.data))
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }, []);

  const draftCount = items.filter((s) => s.status === 'draft').length;
  const submittedCount = items.filter((s) => s.status === 'pending_review').length;
  const recent = [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 10);

  // Phase 7: a lightweight reviewer queue -- submissions awaiting a decision
  // that this acting user is actually eligible to make (role reviewer/admin,
  // and not their own submission), surfaced above the general list rather
  // than as a separate page, per "clear pending-review section" / "do not
  // redesign the application".
  const currentRole = users.find((u) => u.id === userId)?.role;
  const isReviewerEligible = currentRole === 'reviewer' || currentRole === 'admin';
  const needsMyReview = isReviewerEligible
    ? items.filter((s) => s.status === 'pending_review' && s.creator_id !== userId)
    : [];

  return (
    <div>
      <PageHeader
        title="Submissions"
        subtitle="Create, track and review marketing content."
        action={
          <Link
            to="/submissions/new"
            className="rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy"
          >
            + New Submission
          </Link>
        }
      />

      <AsyncState loading={loading} error={error} empty={false} emptyLabel="">
        <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-3xl font-semibold text-deep-blue">{items.length}</p>
            <p className="mt-1 text-xs text-slate-500">Total submissions</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-3xl font-semibold text-deep-blue">{draftCount}</p>
            <p className="mt-1 text-xs text-slate-500">Drafts</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-3xl font-semibold text-deep-blue">{submittedCount}</p>
            <p className="mt-1 text-xs text-slate-500">Submitted</p>
          </div>
        </div>

        {isReviewerEligible && (
          <div className="mb-6 rounded-lg border border-cyan/40 bg-cyan/5 p-4">
            <h3 className="mb-2 text-sm font-semibold text-deep-blue">Needs Your Review ({needsMyReview.length})</h3>
            {needsMyReview.length === 0 ? (
              <p className="text-xs text-slate-500">Nothing is currently awaiting your review.</p>
            ) : (
              <ul className="space-y-1">
                {needsMyReview.map((s) => (
                  <li key={s.id} className="flex items-center justify-between text-sm">
                    <span className="text-navy">{s.title}</span>
                    <Link
                      to={`/submissions/${s.id}`}
                      className="rounded border border-cyan/50 px-2.5 py-1 text-xs font-medium text-deep-blue hover:bg-cyan/10"
                    >
                      Review
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white/60 p-8 text-center text-sm text-slate-500">
            No submissions yet. Create one to get started.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Title</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Revision</th>
                  <th className="px-4 py-2">Updated</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recent.map((s) => (
                  <tr key={s.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium text-navy">{s.title}</td>
                    <td className="px-4 py-2">
                      <span className={`rounded px-2 py-1 text-xs font-medium ${STATUS_STYLES[s.status]}`}>
                        {SUBMISSION_STATUS_LABELS[s.status]}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-slate-500">v{s.current_revision}</td>
                    <td className="px-4 py-2 text-slate-500">{new Date(s.updated_at).toLocaleString()}</td>
                    <td className="px-4 py-2 text-right">
                      <Link
                        to={`/submissions/${s.id}`}
                        className="rounded border border-deep-blue/30 px-2.5 py-1 text-xs font-medium text-deep-blue hover:bg-deep-blue/5"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncState>
    </div>
  );
}
