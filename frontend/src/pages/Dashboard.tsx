import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ACTIVITY_ACTION_LABELS,
  dashboardApi,
  formatApiError,
  type DashboardSummary,
} from '../api/client';
import { useDemoContext } from '../context/DemoContext';
import AsyncState from '../components/AsyncState';
import PageHeader from '../components/PageHeader';

const GOVERNANCE_TILES: { key: keyof DashboardSummary; label: string }[] = [
  { key: 'guideline_docs', label: 'Guideline documents' },
  { key: 'brand_facts', label: 'Brand facts' },
  { key: 'terminology', label: 'Terminology rules' },
  { key: 'claim_policies', label: 'Claim policies' },
  { key: 'assets', label: 'Approved assets' },
];

export default function Dashboard() {
  const { organisationId, userId } = useDemoContext();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  function load(showRefreshSpinner = false) {
    if (showRefreshSpinner) setRefreshing(true);
    else setLoading(true);
    setError(null);
    dashboardApi
      .summary()
      .then((res) => setSummary(res.data))
      .catch((err) => setError(formatApiError(err)))
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  }

  // Reload every time the Dashboard page opens (organisation/user switch
  // counts as "opening" it again, since the data is org-scoped).
  useEffect(() => load(), [organisationId, userId]);

  const s = summary?.submissions;
  const issues = summary?.issues;
  const reviews = summary?.reviews;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="A live overview of submissions, AI findings and reviews for the active organisation."
        action={
          <button
            onClick={() => load(true)}
            disabled={loading || refreshing}
            className="rounded border border-deep-blue px-4 py-2 text-sm font-medium text-deep-blue hover:bg-deep-blue/5 disabled:opacity-50"
          >
            {refreshing ? 'Refreshing...' : '↻ Refresh'}
          </button>
        }
      />

      <AsyncState loading={loading} error={error} empty={!summary} emptyLabel="No dashboard data available.">
        {summary && s && issues && reviews && (
          <>
            {/* --- Submission status --- */}
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Submissions</h3>
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {[
                { label: 'Total', value: s.total },
                { label: 'Draft', value: s.draft },
                { label: 'Pending Review', value: s.pending_review },
                { label: 'Changes Requested', value: s.changes_requested },
                { label: 'Approved', value: s.approved },
                { label: 'Rejected', value: s.rejected },
                { label: 'With AI Findings', value: s.with_ai_findings },
              ].map((tile) => (
                <div key={tile.label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                  <p className="text-2xl font-semibold text-deep-blue">{tile.value}</p>
                  <p className="mt-1 text-xs text-slate-500">{tile.label}</p>
                </div>
              ))}
            </div>

            {/* --- Open issues --- */}
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Open Issues Detected</h3>
            <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-2xl font-semibold text-deep-blue">{issues.open_total}</p>
                <p className="mt-1 text-xs text-slate-500">Total open issues</p>
              </div>
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 shadow-sm">
                <p className="text-2xl font-semibold text-red-700">{issues.by_severity.high}</p>
                <p className="mt-1 text-xs text-red-600">High severity</p>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 shadow-sm">
                <p className="text-2xl font-semibold text-amber-700">{issues.by_severity.medium}</p>
                <p className="mt-1 text-xs text-amber-600">Medium severity</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 shadow-sm">
                <p className="text-2xl font-semibold text-slate-600">{issues.by_severity.low}</p>
                <p className="mt-1 text-xs text-slate-500">Low severity</p>
              </div>
            </div>

            {/* --- Review overview --- */}
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Review Overview</h3>
            <p className="mb-2 text-[11px] text-slate-400">
              &ldquo;Completed Reviews&rdquo; counts every reviewer decision ever recorded (including ones later superseded by
              resubmission) -- it is not the same as how many submissions are currently approved/rejected, shown separately below.
            </p>
            <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-2xl font-semibold text-deep-blue">{reviews.pending}</p>
                <p className="mt-1 text-xs text-slate-500">Pending reviews</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-2xl font-semibold text-deep-blue">{reviews.completed}</p>
                <p className="mt-1 text-xs text-slate-500">Completed reviews (decisions)</p>
              </div>
              <div className="rounded-lg border border-teal/40 bg-teal/5 p-4 shadow-sm">
                <p className="text-2xl font-semibold text-deep-blue">{reviews.currently_approved}</p>
                <p className="mt-1 text-xs text-slate-500">Currently approved</p>
              </div>
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 shadow-sm">
                <p className="text-2xl font-semibold text-red-700">{reviews.currently_rejected}</p>
                <p className="mt-1 text-xs text-slate-500">Currently rejected</p>
              </div>
            </div>

            {/* --- Recent activity --- */}
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Recent Activity</h3>
            <div className="mb-6 rounded-lg border border-slate-200 bg-white shadow-sm">
              {summary.recent_activity.length === 0 ? (
                <p className="p-4 text-sm text-slate-500">No recent activity yet.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {summary.recent_activity.map((entry) => (
                    <li key={entry.id} className="flex items-center justify-between px-4 py-2 text-sm">
                      <div>
                        <span className="font-medium text-navy">{ACTIVITY_ACTION_LABELS[entry.action] ?? entry.action}</span>
                        {entry.submission_title && (
                          <>
                            {' -- '}
                            {entry.submission_id ? (
                              <Link to={`/submissions/${entry.submission_id}`} className="text-cyan hover:underline">
                                {entry.submission_title}
                              </Link>
                            ) : (
                              <span className="text-slate-600">{entry.submission_title}</span>
                            )}
                          </>
                        )}
                        <span className="ml-2 text-xs text-slate-400">by {entry.actor_name ?? 'Unknown user'}</span>
                      </div>
                      <span className="text-xs text-slate-400">{new Date(entry.created_at).toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* --- Governance data (unchanged from Phase 1-4) --- */}
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Brand Guideline Data</h3>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
              {GOVERNANCE_TILES.map((tile) => (
                <div key={tile.key} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                  <p className="text-2xl font-semibold text-deep-blue">{summary[tile.key] as number}</p>
                  <p className="mt-1 text-xs text-slate-500">{tile.label}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </AsyncState>
    </div>
  );
}
