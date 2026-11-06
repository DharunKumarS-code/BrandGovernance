import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatApiError, submissionsApi, type SampleAd } from '../api/client';
import PageHeader from '../components/PageHeader';

export default function SubmissionCreate() {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [samples, setSamples] = useState<SampleAd[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [imageUploading, setImageUploading] = useState(false);
  const [imageUploadError, setImageUploadError] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    submissionsApi.samples().then((res) => setSamples(res.data)).catch(() => undefined);
  }, []);

  function loadSample(e: React.ChangeEvent<HTMLSelectElement>) {
    const index = e.target.value;
    if (index === '') return;
    const sample = samples[Number(index)];
    setTitle(sample.title);
    setContent(sample.content);
    e.target.value = '';
  }

  async function handleSave(submitAfter: boolean) {
    if (!title.trim() || !content.trim()) {
      setError('Title and content are both required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await submissionsApi.create(title, content);
      if (submitAfter) {
        await submissionsApi.submit(created.data.id);
      }
      navigate(`/submissions/${created.data.id}`);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  async function handlePdfUpload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const resp = await submissionsApi.uploadPdf(file, title || undefined);
      navigate(`/submissions/${resp.data.id}`);
    } catch (err) {
      setUploadError(formatApiError(err));
    } finally {
      setUploading(false);
    }
  }

  async function handleImageUpload(e: React.FormEvent) {
    e.preventDefault();
    const file = imageInputRef.current?.files?.[0];
    if (!file) return;
    setImageUploading(true);
    setImageUploadError(null);
    try {
      const resp = await submissionsApi.uploadImage(file, title || undefined);
      navigate(`/submissions/${resp.data.id}`);
    } catch (err) {
      setImageUploadError(formatApiError(err));
    } finally {
      setImageUploading(false);
    }
  }

  return (
    <div>
      <PageHeader title="New Submission" subtitle="Write your content directly, upload a PDF, or start from a sample ad." />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <label className="mb-1 block text-sm font-medium text-deep-blue">Submission title</label>
          <input
            className="mb-4 w-full rounded border px-3 py-2 text-sm"
            placeholder="e.g. Nova Buds Pro - Summer Launch Ad"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />

          <div className="mb-2 flex items-center justify-between">
            <label className="block text-sm font-medium text-deep-blue">Content</label>
            {samples.length > 0 && (
              <select
                className="rounded border px-2 py-1 text-xs text-slate-600"
                defaultValue=""
                onChange={loadSample}
              >
                <option value="" disabled>
                  Load sample ad...
                </option>
                {samples.map((s, i) => (
                  <option key={s.title} value={i}>
                    {s.title}
                  </option>
                ))}
              </select>
            )}
          </div>
          <textarea
            className="mb-4 h-56 w-full rounded border px-3 py-2 text-sm"
            placeholder="Write or paste the ad copy here..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />

          {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

          <div className="flex gap-3">
            <button
              onClick={() => handleSave(false)}
              disabled={saving}
              className="rounded border border-deep-blue px-4 py-2 text-sm font-medium text-deep-blue hover:bg-deep-blue/5 disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save Draft'}
            </button>
            <button
              onClick={() => handleSave(true)}
              disabled={saving}
              className="rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy disabled:opacity-50"
            >
              {saving ? 'Submitting...' : 'Submit for Review'}
            </button>
          </div>
          <p className="mt-3 text-xs text-slate-400">
            Save Draft to keep editing later, or Submit for Review to send it straight to a reviewer.
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 font-semibold text-navy">Or upload a PDF</h3>
          <p className="mb-3 text-xs text-slate-500">
            PDF only. The text is pulled out automatically and becomes a new draft you can review before submitting.
          </p>
          <form onSubmit={handlePdfUpload} className="space-y-2">
            <input ref={fileInputRef} type="file" accept=".pdf,application/pdf" className="text-sm" required />
            <button
              type="submit"
              disabled={uploading}
              className="w-full rounded bg-deep-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-navy disabled:opacity-50"
            >
              {uploading ? 'Uploading...' : 'Upload PDF'}
            </button>
            {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}
          </form>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 font-semibold text-navy">Or upload an image</h3>
          <p className="mb-3 text-xs text-slate-500">
            PNG or JPEG only. Used to check brand colours and logo usage against your approved brand assets.
          </p>
          <form onSubmit={handleImageUpload} className="space-y-2">
            <input ref={imageInputRef} type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" className="text-sm" required />
            <button
              type="submit"
              disabled={imageUploading}
              className="w-full rounded bg-deep-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-navy disabled:opacity-50"
            >
              {imageUploading ? 'Uploading...' : 'Upload Image'}
            </button>
            {imageUploadError && <p className="text-sm text-red-600">{imageUploadError}</p>}
          </form>
        </div>
      </div>
    </div>
  );
}
