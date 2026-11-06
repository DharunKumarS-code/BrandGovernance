import { useEffect, useState } from 'react';
import { analyticsApi, formatApiError, type AnalyticsSummary } from '../api/client';
import AsyncState from '../components/AsyncState';
import PageHeader from '../components/PageHeader';

export default function Analytics() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    analyticsApi
      .summary()
      .then((res) => setData(res.data))
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }, []);

  const isEmpty =
    !!data &&
    data.findings_by_category.length === 0 &&
    data.top_terminology_violations.length === 0 &&
    data.top_claim_policy_violations.length === 0 &&
    data.insufficient_evidence_count === 0 &&
    data.unembedded_guideline_chunks === 0;

  return (
    <div>
      <PageHeader title="Analytics" subtitle="Patterns across findings, repeated violations, and guideline coverage gaps." />

      <AsyncState loading={loading} error={error} empty={isEmpty} emptyLabel="No analytics data yet -- analyse some submissions first.">
        {data && (
          <>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Findings by Category &amp; Severity</h3>
            {data.findings_by_category.length === 0 ? (
              <p className="mb-6 text-sm text-slate-500">No findings recorded yet.</p>
            ) : (
              <div className="mb-6 overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-2">Category</th>
                      <th className="px-4 py-2">Severity</th>
                      <th className="px-4 py-2">Count</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.findings_by_category.map((row) => (
                      <tr key={`${row.category}-${row.severity}`}>
                        <td className="px-4 py-2 font-medium text-navy">{row.category}</td>
                        <td className="px-4 py-2 text-slate-600">{row.severity}</td>
                        <td className="px-4 py-2 text-deep-blue">{row.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="mb-6 grid grid-cols-1 gap-6 md:grid-cols-2">
              <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <h3 className="mb-2 font-semibold text-navy">Top Terminology Violations</h3>
                {data.top_terminology_violations.length === 0 ? (
                  <p className="text-sm text-slate-500">No repeated terminology violations yet.</p>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {data.top_terminology_violations.map((v) => (
                      <li key={v.terminology_id} className="flex items-center justify-between">
                        <span className="text-slate-700">{v.preferred_term ?? '(deleted rule)'}</span>
                        <span className="font-medium text-deep-blue">{v.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <h3 className="mb-2 font-semibold text-navy">Top Claim Policy Violations</h3>
                {data.top_claim_policy_violations.length === 0 ? (
                  <p className="text-sm text-slate-500">No repeated claim-policy violations yet.</p>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {data.top_claim_policy_violations.map((v) => (
                      <li key={v.claim_policy_id} className="flex items-center justify-between">
                        <span className="text-slate-700">{v.pattern ?? '(deleted policy)'}</span>
                        <span className="font-medium text-deep-blue">{v.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>

            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Guideline Coverage</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-2xl font-semibold text-deep-blue">{data.insufficient_evidence_count}</p>
                <p className="mt-1 text-xs text-slate-500">Findings with insufficient evidence</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-2xl font-semibold text-deep-blue">{data.unembedded_guideline_chunks}</p>
                <p className="mt-1 text-xs text-slate-500">Guideline chunks not yet embedded</p>
              </div>
            </div>
          </>
        )}
      </AsyncState>
    </div>
  );
}
