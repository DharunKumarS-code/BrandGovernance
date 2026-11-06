import { useEffect, useState } from 'react';
import { formatApiError, terminologyApi, type Terminology as Term } from '../api/client';
import AsyncState, { SuccessBanner } from '../components/AsyncState';
import PageHeader from '../components/PageHeader';

const EMPTY_FORM = { preferred_term: '', banned_variants: '', reason: '' };

export default function Terminology() {
  const [terms, setTerms] = useState<Term[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitError, setSubmitError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    terminologyApi
      .list()
      .then((res) => setTerms(res.data))
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    try {
      await terminologyApi.create({
        preferred_term: form.preferred_term,
        banned_variants: form.banned_variants.split(',').map((v) => v.trim()).filter(Boolean),
        reason: form.reason,
      });
      setForm(EMPTY_FORM);
      setSuccess('Terminology rule created.');
      load();
    } catch (err: any) {
      setSubmitError(formatApiError(err));
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this terminology rule?')) return;
    await terminologyApi.remove(id);
    load();
  }

  return (
    <div>
      <PageHeader
        title="Terminology"
        subtitle="Approved wording, and the restricted terms content should avoid instead."
      />

      {success && <SuccessBanner message={success} onDismiss={() => setSuccess(null)} />}

      <form onSubmit={handleSubmit} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-3">
        <input required placeholder="Approved term" className="rounded border px-2 py-1 text-sm" value={form.preferred_term} onChange={(e) => setForm({ ...form, preferred_term: e.target.value })} />
        <input required placeholder="Restricted variants (comma-separated)" className="rounded border px-2 py-1 text-sm" value={form.banned_variants} onChange={(e) => setForm({ ...form, banned_variants: e.target.value })} />
        <input required placeholder="Reason / usage guidance" className="rounded border px-2 py-1 text-sm" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        <button type="submit" className="col-span-1 rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy md:col-span-3">
          Add rule
        </button>
        {submitError && <p className="col-span-1 text-sm text-red-600 md:col-span-3">{submitError}</p>}
      </form>

      <AsyncState loading={loading} error={error} empty={terms.length === 0} emptyLabel="No terminology rules yet.">
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Restricted term(s)</th>
                <th className="px-4 py-2">Approved replacement</th>
                <th className="px-4 py-2">Reason</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {terms.map((term) => (
                <tr key={term.id}>
                  <td className="px-4 py-2 text-red-600">{term.banned_variants.join(', ')}</td>
                  <td className="px-4 py-2 font-medium text-teal">{term.preferred_term}</td>
                  <td className="px-4 py-2 text-slate-500">{term.reason}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => handleDelete(term.id)}
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
