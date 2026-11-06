import { useEffect, useState } from 'react';
import { brandFactsApi, formatApiError, guidelinesApi, type BrandFact, type GuidelineDoc } from '../api/client';
import AsyncState, { SuccessBanner } from '../components/AsyncState';
import PageHeader from '../components/PageHeader';

const EMPTY_FORM = {
  subject: '',
  attribute: '',
  value: '',
  unit: '',
  valid_from: new Date().toISOString().slice(0, 10),
  valid_to: '',
  source_doc_id: '',
  page: '',
  quote: '',
};

export default function Facts() {
  const [facts, setFacts] = useState<BrandFact[]>([]);
  const [docs, setDocs] = useState<GuidelineDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitError, setSubmitError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    Promise.all([brandFactsApi.list(), guidelinesApi.list()])
      .then(([factsRes, docsRes]) => {
        setFacts(factsRes.data);
        setDocs(docsRes.data);
      })
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    try {
      await brandFactsApi.create({
        subject: form.subject,
        attribute: form.attribute,
        value: form.value,
        unit: form.unit || null,
        valid_from: new Date(form.valid_from).toISOString(),
        valid_to: form.valid_to ? new Date(form.valid_to).toISOString() : null,
        source_doc_id: form.source_doc_id || null,
        page: form.page ? Number(form.page) : null,
        quote: form.quote || null,
      });
      setForm(EMPTY_FORM);
      setSuccess('Brand fact created.');
      load();
    } catch (err: any) {
      setSubmitError(formatApiError(err));
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this brand fact?')) return;
    await brandFactsApi.remove(id);
    load();
  }

  return (
    <div>
      <PageHeader
        title="Brand Facts"
        subtitle="The true product facts (specs, prices, dates) that submitted content is checked against."
      />

      {success && <SuccessBanner message={success} onDismiss={() => setSuccess(null)} />}

      <form onSubmit={handleSubmit} className="mb-6 grid grid-cols-2 gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-4">
        <p className="col-span-2 text-sm font-medium text-deep-blue md:col-span-4">Add a new fact</p>
        <input required placeholder="Subject" className="rounded border px-2 py-1 text-sm" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
        <input required placeholder="Attribute" className="rounded border px-2 py-1 text-sm" value={form.attribute} onChange={(e) => setForm({ ...form, attribute: e.target.value })} />
        <input required placeholder="Value" className="rounded border px-2 py-1 text-sm" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
        <input placeholder="Unit (optional)" className="rounded border px-2 py-1 text-sm" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
        <input required type="date" className="rounded border px-2 py-1 text-sm" value={form.valid_from} onChange={(e) => setForm({ ...form, valid_from: e.target.value })} />
        <input type="date" placeholder="Valid to (optional)" className="rounded border px-2 py-1 text-sm" value={form.valid_to} onChange={(e) => setForm({ ...form, valid_to: e.target.value })} />
        <select className="rounded border px-2 py-1 text-sm" value={form.source_doc_id} onChange={(e) => setForm({ ...form, source_doc_id: e.target.value })}>
          <option value="">Source document (optional)</option>
          {docs.map((d) => (
            <option key={d.id} value={d.id}>{d.title}</option>
          ))}
        </select>
        <input type="number" min="1" placeholder="Page" className="rounded border px-2 py-1 text-sm" value={form.page} onChange={(e) => setForm({ ...form, page: e.target.value })} />
        <input placeholder="Supporting quote (verbatim, optional)" className="col-span-2 rounded border px-2 py-1 text-sm md:col-span-4" value={form.quote} onChange={(e) => setForm({ ...form, quote: e.target.value })} />
        <button type="submit" className="col-span-2 rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy md:col-span-4">
          Add fact
        </button>
        {submitError && <p className="col-span-2 text-sm text-red-600 md:col-span-4">{submitError}</p>}
      </form>

      <AsyncState loading={loading} error={error} empty={facts.length === 0} emptyLabel="No brand facts yet.">
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Subject</th>
                <th className="px-4 py-2">Attribute</th>
                <th className="px-4 py-2">Value</th>
                <th className="px-4 py-2">Valid from</th>
                <th className="px-4 py-2">Valid to</th>
                <th className="px-4 py-2">Quote</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {facts.map((fact) => (
                <tr key={fact.id}>
                  <td className="px-4 py-2 font-medium text-navy">{fact.subject}</td>
                  <td className="px-4 py-2">{fact.attribute}</td>
                  <td className="px-4 py-2">{fact.value}{fact.unit ? ` ${fact.unit}` : ''}</td>
                  <td className="px-4 py-2 text-slate-500">{fact.valid_from.slice(0, 10)}</td>
                  <td className="px-4 py-2 text-slate-500">
                    {fact.valid_to ? fact.valid_to.slice(0, 10) : <span className="text-teal">current</span>}
                  </td>
                  <td className="max-w-xs truncate px-4 py-2 text-slate-500" title={fact.quote ?? ''}>{fact.quote ?? '-'}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => handleDelete(fact.id)}
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
