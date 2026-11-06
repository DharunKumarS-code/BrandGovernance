import { useEffect, useRef, useState } from 'react';
import { formatApiError, guidelinesApi, type GuidelineChunk, type GuidelineDoc } from '../api/client';
import AsyncState, { SuccessBanner } from '../components/AsyncState';
import PageHeader from '../components/PageHeader';

const STATUS_STYLES: Record<GuidelineDoc['status'], string> = {
  ready: 'bg-teal/20 text-deep-blue',
  processing: 'bg-cyan/20 text-deep-blue',
  pending: 'bg-slate-200 text-slate-600',
  failed: 'bg-red-100 text-red-700',
};

const STATUS_LABELS: Record<GuidelineDoc['status'], string> = {
  ready: 'Ready',
  processing: 'Processing',
  pending: 'Pending',
  failed: 'Failed',
};

export default function Guidelines() {
  const [docs, setDocs] = useState<GuidelineDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<GuidelineDoc | null>(null);
  const [chunks, setChunks] = useState<GuidelineChunk[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function load() {
    setLoading(true);
    guidelinesApi
      .list()
      .then((res) => setDocs(res.data))
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      await guidelinesApi.upload(file);
      setSuccess(`Uploaded "${file.name}" successfully.`);
      if (fileInputRef.current) fileInputRef.current.value = '';
      load();
    } catch (err: any) {
      setUploadError(formatApiError(err));
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(doc: GuidelineDoc) {
    if (!confirm(`Delete "${doc.title}"? This removes its stored file and extracted chunks.`)) return;
    await guidelinesApi.remove(doc.id);
    if (selectedDoc?.id === doc.id) {
      setSelectedDoc(null);
      setChunks([]);
    }
    load();
  }

  async function viewChunks(doc: GuidelineDoc) {
    setSelectedDoc(doc);
    const res = await guidelinesApi.chunks(doc.id);
    setChunks(res.data);
  }

  return (
    <div>
      <PageHeader
        title="Guideline Documents"
        subtitle="Upload your brand guideline PDFs so the AI can check content against them."
      />

      {success && <SuccessBanner message={success} onDismiss={() => setSuccess(null)} />}

      <form onSubmit={handleUpload} className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <label className="mb-2 block text-sm font-medium text-deep-blue">Upload a guideline PDF</label>
        <div className="flex items-center gap-3">
          <input ref={fileInputRef} type="file" accept="application/pdf" className="text-sm" required />
          <button
            type="submit"
            disabled={uploading}
            className="rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy disabled:opacity-50"
          >
            {uploading ? 'Uploading...' : 'Upload'}
          </button>
        </div>
        {uploadError && <p className="mt-2 text-sm text-red-600">{uploadError}</p>}
      </form>

      <AsyncState loading={loading} error={error} empty={docs.length === 0} emptyLabel="No guideline documents uploaded yet.">
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Title</th>
                <th className="px-4 py-2">Filename</th>
                <th className="px-4 py-2">Pages</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {docs.map((doc) => (
                <tr key={doc.id}>
                  <td className="px-4 py-2 font-medium text-navy">{doc.title}</td>
                  <td className="px-4 py-2 text-slate-500">{doc.filename}</td>
                  <td className="px-4 py-2">{doc.page_count}</td>
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-1 text-xs font-medium ${STATUS_STYLES[doc.status]}`}>
                      {STATUS_LABELS[doc.status]}
                    </span>
                  </td>
                  <td className="space-x-2 px-4 py-2 text-right">
                    <button
                      onClick={() => viewChunks(doc)}
                      className="rounded border border-deep-blue/30 px-2.5 py-1 text-xs font-medium text-deep-blue hover:bg-deep-blue/5"
                    >
                      View Chunks
                    </button>
                    <button
                      onClick={() => handleDelete(doc)}
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

      {selectedDoc && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-semibold text-navy">Chunks for "{selectedDoc.title}"</h3>
            <button onClick={() => setSelectedDoc(null)} className="rounded border border-slate-300 px-2.5 py-1 text-xs text-slate-500 hover:bg-slate-50">
              Close
            </button>
          </div>
          {chunks.length === 0 ? (
            <p className="text-sm text-slate-500">No chunks found.</p>
          ) : (
            <ul className="max-h-96 space-y-2 overflow-y-auto text-sm">
              {chunks.map((chunk) => (
                <li key={chunk.id} className="rounded border border-slate-100 bg-slate-50 p-2">
                  <p className="mb-1 text-xs font-medium text-deep-blue">
                    page {chunk.page} · chunk {chunk.chunk_index}
                  </p>
                  <p className="text-slate-600">{chunk.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
