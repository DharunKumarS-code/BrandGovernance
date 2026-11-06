import { useEffect, useState } from 'react';
import { claimPoliciesApi, formatApiError, type ClaimPolicy } from '../api/client';
import AsyncState, { SuccessBanner } from '../components/AsyncState';
import PageHeader from '../components/PageHeader';

const EMPTY_FORM = { pattern: '', status: 'needs_evidence' as ClaimPolicy['status'], required_disclaimer: '' };

const STATUS_LABELS: Record<ClaimPolicy['status'], { label: string; style: string }> = {
  approved: { label: 'Allowed', style: 'bg-teal/20 text-deep-blue' },
  needs_evidence: { label: 'Requires evidence', style: 'bg-cyan/20 text-deep-blue' },
  banned: { label: 'Restricted', style: 'bg-red-100 text-red-700' },
};

export default function ClaimPolicies() {
  const [policies, setPolicies] = useState<ClaimPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitError, setSubmitError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    claimPoliciesApi
      .list()
      .then((res) => setPolicies(res.data))
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    try {
      await claimPoliciesApi.create({
        pattern: form.pattern,
        status: form.status,
        required_disclaimer: form.required_disclaimer || null,
      });
      setForm(EMPTY_FORM);
      setSuccess('Claim policy created.');
      load();
    } catch (err: any) {
      setSubmitError(formatApiError(err));
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this claim policy?')) return;
    await claimPoliciesApi.remove(id);
    load();
  }

  return (
    <div>
      <PageHeader
        title="Claim Policies"
        subtitle="Decide which marketing claims are allowed, restricted, or need supporting evidence."
      />

      {success && <SuccessBanner message={success} onDismiss={() => setSuccess(null)} />}

      <form onSubmit={handleSubmit} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-3">
        <input required placeholder="Claim pattern (e.g. 'best')" className="rounded border px-2 py-1 text-sm" value={form.pattern} onChange={(e) => setForm({ ...form, pattern: e.target.value })} />
        <select className="rounded border px-2 py-1 text-sm" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as ClaimPolicy['status'] })}>
          <option value="approved">Allowed</option>
          <option value="needs_evidence">Requires evidence</option>
          <option value="banned">Restricted</option>
        </select>
        <input placeholder="Required disclaimer (optional)" className="rounded border px-2 py-1 text-sm" value={form.required_disclaimer} onChange={(e) => setForm({ ...form, required_disclaimer: e.target.value })} />
        <button type="submit" className="col-span-1 rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy md:col-span-3">
          Add policy
        </button>
        {submitError && <p className="col-span-1 text-sm text-red-600 md:col-span-3">{submitError}</p>}
      </form>

      <AsyncState loading={loading} error={error} empty={policies.length === 0} emptyLabel="No claim policies yet.">
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Pattern</th>
                <th className="px-4 py-2">Policy</th>
                <th className="px-4 py-2">Required disclaimer</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {policies.map((policy) => (
                <tr key={policy.id}>
                  <td className="px-4 py-2 font-medium text-navy">"{policy.pattern}"</td>
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-1 text-xs font-medium ${STATUS_LABELS[policy.status].style}`}>
                      {STATUS_LABELS[policy.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-slate-500">{policy.required_disclaimer ?? '-'}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => handleDelete(policy.id)}
                      className="rounded border border-red-300 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncState>
    </div>
  );
}
