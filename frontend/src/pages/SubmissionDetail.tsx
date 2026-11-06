import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  formatApiError,
  submissionsApi,
  SUBMISSION_STATUS_LABELS,
  type DiffLine,
  type Finding,
  type Review,
  type Revision,
  type Submission,
} from '../api/client';
import { useDemoContext } from '../context/DemoContext';
import AsyncState, { SuccessBanner } from '../components/AsyncState';
import FindingsPanel from '../components/FindingsPanel';
import ReviewPanel from '../components/ReviewPanel';

const EDITABLE_STATUSES = new Set(['draft', 'pending_review', 'changes_requested']);

export default function SubmissionDetail() {
  const { id } = useParams<{ id: string }>();
  const { users, userId, organisationId } = useDemoContext();

  const [submission, setSubmission] = useState<Submission | null>(null);
  const [current, setCurrent] = useState<Revision | null>(null);
  const [history, setHistory] = useState<Revision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [editText, setEditText] = useState('');
  const [editing, setEditing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [fromVersion, setFromVersion] = useState<number | null>(null);
  const [toVersion, setToVersion] = useState<number | null>(null);
  const [diff, setDiff] = useState<DiffLine[] | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);

  // --- Phase 6: findings, evidence, and correction suggestions ----------
  const [findingsList, setFindingsList] = useState<Finding[]>([]);
  const [findingsLoading, setFindingsLoading] = useState(false);
  const [findingsError, setFindingsError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeMessage, setAnalyzeMessage] = useState<string | null>(null);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  // --- Phase 7: reviewer decisions ---------------------------------------
  const [reviewsList, setReviewsList] = useState<Review[]>([]);
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [reviewsError, setReviewsError] = useState<string | null>(null);

  function load() {
    if (!id) return;
    setLoading(true);
    Promise.all([submissionsApi.get(id), submissionsApi.content(id), submissionsApi.revisions(id)])
      .then(([subRes, contentRes, historyRes]) => {
        setSubmission(subRes.data);
        setCurrent(contentRes.data);
        setHistory(historyRes.data);
        setEditText(contentRes.data.content);
        if (historyRes.data.length >= 2) {
          setFromVersion(historyRes.data[historyRes.data.length - 2].version);
          setToVersion(historyRes.data[historyRes.data.length - 1].version);
        }
      })
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }

  useEffect(load, [id]);

  function loadFindings() {
    if (!id) return;
    setFindingsLoading(true);
    submissionsApi
      .findings(id)
      .then((res) => setFindingsList(res.data))
      .catch((err) => setFindingsError(formatApiError(err)))
      .finally(() => setFindingsLoading(false));
  }

  useEffect(loadFindings, [id]);

  function loadReviews() {
    if (!id) return;
    setReviewsLoading(true);
    submissionsApi
      .reviews(id)
      .then((res) => setReviewsList(res.data))
      .catch((err) => setReviewsError(formatApiError(err)))
      .finally(() => setReviewsLoading(false));
  }

  useEffect(loadReviews, [id]);

  function handleReviewDecisionMade(updatedSubmission: Submission, review: Review) {
    setSubmission(updatedSubmission);
    setReviewsList((prev) => [...prev, review]);
    setSuccess(
      review.decision === 'approved'
        ? 'Submission approved.'
        : review.decision === 'rejected'
          ? 'Submission rejected.'
          : 'Changes requested -- the creator can now edit and resubmit.',
    );
  }

  async function handleAnalyze() {
    if (!id) return;
    setAnalyzing(true);
    setAnalyzeError(null);
    setAnalyzeMessage(null);
    try {
      const res = await submissionsApi.analyze(id);
      const report = res.data;
      setAnalyzeMessage(
        `Analysis complete: ${report.findings_count} finding(s) found. ` +
          (report.ai_available
            ? `AI checks completed: ${report.ai_checks_completed.join(', ') || 'none'}.`
            : 'AI is currently unavailable -- rule-based checks only.'),
      );
      loadFindings();
    } catch (err) {
      setAnalyzeError(formatApiError(err));
    } finally {
      setAnalyzing(false);
    }
  }

  function handleApplyCorrection(content: string) {
    setEditText(content);
    setEditing(true);
    setSuccess('Correction applied to the draft below -- review it, then save or submit as a new revision.');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  const creatorName = submission ? users.find((u) => u.id === submission.creator_id)?.name ?? submission.creator_id : '';
  const isOwner = submission?.creator_id === userId;
  const canEdit = submission ? isOwner && EDITABLE_STATUSES.has(submission.status) : false;

  // A reviewer decision is a SEPARATE operation from accepting/dismissing an
  // AI correction suggestion (see FindingsPanel) -- this gates the former.
  const currentUserRole = users.find((u) => u.id === userId)?.role;
  const isReviewerEligible = (currentUserRole === 'reviewer' || currentUserRole === 'admin') && !isOwner;

  async function handleSaveDraft() {
    if (!id) return;
    setBusy(true);
    setActionError(null);
    try {
      await submissionsApi.updateDraft(id, { content: editText });
      setSuccess('Draft saved.');
      setEditing(false);
      load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleReviseAndResubmit() {
    if (!id) return;
    setBusy(true);
    setActionError(null);
    try {
      await submissionsApi.revise(id, editText);
      setSuccess('New revision created. Submission returned to draft -- submit again when ready.');
      setEditing(false);
      load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit() {
    if (!id) return;
    setBusy(true);
    setActionError(null);
    try {
      await submissionsApi.submit(id);
      setSuccess('Submission submitted.');
      load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCompare() {
    if (!id || fromVersion === null || toVersion === null) return;
    setDiffError(null);
    try {
      const res = await submissionsApi.compare(id, fromVersion, toVersion);
      setDiff(res.data.diff);
    } catch (err) {
      setDiffError(formatApiError(err));
    }
  }

  return (
    <div>
      <Link to="/submissions" className="mb-4 inline-block text-sm text-cyan hover:underline">
        &larr; Back to submissions
      </Link>

      <AsyncState loading={loading} error={error} empty={!submission} emptyLabel="Submission not found.">
        {submission && current && (
          <>
            {success && <SuccessBanner message={success} onDismiss={() => setSuccess(null)} />}

            <div className="mb-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-3 flex items-start justify-between">
                <div>
                  <h2 className="text-2xl font-semibold text-navy">{submission.title}</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    Created by {creatorName} on {new Date(submission.created_at).toLocaleString()} &middot; updated{' '}
                    {new Date(submission.updated_at).toLocaleString()}
                  </p>
                </div>
                <span className="rounded px-3 py-1 text-xs font-medium bg-deep-blue/10 text-deep-blue">
                  {SUBMISSION_STATUS_LABELS[submission.status]}
                </span>
              </div>
              <p className="mb-3 text-xs text-slate-500">
                Current revision: v{submission.current_revision}
                {submission.submitted_at && <> &middot; submitted {new Date(submission.submitted_at).toLocaleString()}</>}
              </p>

              {current.image_path && organisationId && userId && (
                <img
                  src={submissionsApi.imageUrl(submission.id, current.version, organisationId, userId)}
                  alt={submission.title}
                  className="mb-3 max-h-96 rounded border border-slate-200 object-contain"
                />
              )}

              {!editing ? (
                current.image_path ? null : (
                  <pre className="whitespace-pre-wrap rounded border border-slate-100 bg-slate-50 p-3 text-sm text-slate-700">
                    {current.content}
                  </pre>
                )
              ) : (
                <textarea
                  className="h-48 w-full rounded border px-3 py-2 text-sm"
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                />
              )}

              {actionError && <p className="mt-3 text-sm text-red-600">{actionError}</p>}

              <div className="mt-4 flex flex-wrap gap-3">
                {!isOwner && (
                  <p className="text-xs text-slate-400">Only the creator ({creatorName}) can edit this submission.</p>
                )}
                {canEdit && !editing && (
                  <button
                    onClick={() => setEditing(true)}
                    className="rounded border border-deep-blue px-4 py-2 text-sm font-medium text-deep-blue hover:bg-deep-blue/5"
                  >
                    Edit content
                  </button>
                )}
                {editing && submission.status === 'draft' && (
                  <button
                    onClick={handleSaveDraft}
                    disabled={busy}
                    className="rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy disabled:opacity-50"
                  >
                    Save Draft
                  </button>
                )}
                {editing && submission.status !== 'draft' && (
                  <button
                    onClick={handleReviseAndResubmit}
                    disabled={busy}
                    className="rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy disabled:opacity-50"
                  >
                    Save as New Revision
                  </button>
                )}
                {editing && (
                  <button
                    onClick={() => {
                      setEditing(false);
                      setEditText(current.content);
                    }}
                    className="rounded px-4 py-2 text-sm text-slate-500 hover:underline"
                  >
                    Cancel
                  </button>
                )}
                {isOwner && submission.status === 'draft' && !editing && (
                  <button
                    onClick={handleSubmit}
                    disabled={busy}
                    className="rounded bg-teal px-4 py-2 text-sm font-medium text-navy hover:opacity-90 disabled:opacity-50"
                  >
                    Submit
                  </button>
                )}
              </div>
            </div>

            <div className="mb-6">
              <AsyncState loading={reviewsLoading} error={reviewsError} empty={false} emptyLabel="">
                <ReviewPanel
                  submissionId={submission.id}
                  submissionStatus={submission.status}
                  isReviewerEligible={isReviewerEligible}
                  reviews={reviewsList}
                  users={users}
                  onDecisionMade={handleReviewDecisionMade}
                />
              </AsyncState>
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="mb-3 font-semibold text-navy">Revision History</h3>
              <ul className="mb-4 divide-y divide-slate-100 text-sm">
                {history.map((rev) => (
                  <li key={rev.id} className="flex items-center justify-between py-2">
                    <div>
                      <span className="font-medium text-navy">v{rev.version}</span>
                      {rev.version === submission.current_revision && (
                        <span className="ml-2 rounded bg-teal/20 px-2 py-0.5 text-xs text-deep-blue">current</span>
                      )}
                      <span className="ml-3 text-xs text-slate-400">{new Date(rev.created_at).toLocaleString()}</span>
                    </div>
                  </li>
                ))}
              </ul>

              {history.length >= 2 && (
                <div className="rounded border border-slate-100 bg-slate-50 p-3">
                  <p className="mb-2 text-xs font-medium text-deep-blue">Compare revisions</p>
                  <div className="mb-3 flex items-center gap-2 text-sm">
                    <select
                      className="rounded border px-2 py-1"
                      value={fromVersion ?? ''}
                      onChange={(e) => setFromVersion(Number(e.target.value))}
                    >
                      {history.map((r) => (
                        <option key={r.version} value={r.version}>
                          v{r.version}
                        </option>
                      ))}
                    </select>
                    <span className="text-slate-400">vs</span>
                    <select
                      className="rounded border px-2 py-1"
                      value={toVersion ?? ''}
                      onChange={(e) => setToVersion(Number(e.target.value))}
                    >
                      {history.map((r) => (
                        <option key={r.version} value={r.version}>
                          v{r.version}
                        </option>
                      ))}
                    </select>
                    <button onClick={handleCompare} className="rounded bg-deep-blue px-3 py-1 text-xs font-medium text-white hover:bg-navy">
                      Compare
                    </button>
                  </div>
                  {diffError && <p className="text-sm text-red-600">{diffError}</p>}
                  {diff && (
                    <pre className="max-h-80 overflow-y-auto rounded border border-slate-200 bg-white p-3 text-xs">
                      {diff.map((line, i) => (
                        <div
                          key={i}
                          className={
                            line.type === 'added'
                              ? 'bg-teal/10 text-emerald-700'
                              : line.type === 'removed'
                                ? 'bg-red-50 text-red-700 line-through decoration-red-300'
                                : 'text-slate-500'
                          }
                        >
                          {line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}
                          {line.text}
                        </div>
                      ))}
                    </pre>
                  )}
                </div>
              )}
            </div>

            <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold text-navy">Findings &amp; Suggestions</h3>
                {submission.status === 'pending_review' && (
                  <button
                    onClick={handleAnalyze}
                    disabled={analyzing}
                    className="rounded bg-cyan px-4 py-2 text-sm font-medium text-navy hover:opacity-90 disabled:opacity-50"
                  >
                    {analyzing ? 'Analyzing...' : 'Analyze Submission'}
                  </button>
                )}
              </div>
              {analyzeMessage && <p className="mb-3 rounded border border-teal/40 bg-teal/10 p-2 text-xs text-deep-blue">{analyzeMessage}</p>}
              {analyzeError && <p className="mb-3 text-sm text-red-600">{analyzeError}</p>}

              <AsyncState loading={findingsLoading} error={findingsError} empty={false} emptyLabel="">
                <FindingsPanel
                  submissionId={submission.id}
                  findings={findingsList}
                  isOwner={isOwner}
                  onFindingUpdated={(updated) =>
                    setFindingsList((prev) => prev.map((f) => (f.id === updated.id ? updated : f)))
                  }
                  onApplyCorrection={handleApplyCorrection}
                />
              </AsyncState>
            </div>
          </>
        )}
      </AsyncState>
    </div>
  );
}
