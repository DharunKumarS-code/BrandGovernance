import { useEffect, useRef, useState } from 'react';
import { assetsApi, formatApiError, type Asset } from '../api/client';
import { useDemoContext } from '../context/DemoContext';
import AsyncState, { SuccessBanner } from '../components/AsyncState';
import PageHeader from '../components/PageHeader';

export default function Assets() {
  const { organisationId, userId } = useDemoContext();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [colourName, setColourName] = useState('');
  const [colourHex, setColourHex] = useState('#1458F2');
  const [colourError, setColourError] = useState<string | null>(null);

  const [logoName, setLogoName] = useState('');
  const [logoError, setLogoError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const logoInputRef = useRef<HTMLInputElement>(null);

  function load() {
    setLoading(true);
    assetsApi
      .list()
      .then((res) => setAssets(res.data))
      .catch((err) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleAddColour(e: React.FormEvent) {
    e.preventDefault();
    setColourError(null);
    try {
      await assetsApi.createColour({ name: colourName, status: 'approved', hex_value: colourHex });
      setColourName('');
      setSuccess('Brand colour added.');
      load();
    } catch (err: any) {
      setColourError(formatApiError(err));
    }
  }

  async function handleUploadLogo(e: React.FormEvent) {
    e.preventDefault();
    const file = logoInputRef.current?.files?.[0];
    if (!file) return;
    setLogoError(null);
    setUploading(true);
    try {
      await assetsApi.uploadLogo(file, logoName || file.name, 'approved');
      setLogoName('');
      if (logoInputRef.current) logoInputRef.current.value = '';
      setSuccess('Logo uploaded.');
      load();
    } catch (err: any) {
      setLogoError(formatApiError(err));
    } finally {
      setUploading(false);
    }
  }

  async function handleToggleStatus(asset: Asset) {
    const next = asset.status === 'approved' ? 'deprecated' : 'approved';
    await assetsApi.update(asset.id, { status: next });
    load();
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this asset?')) return;
    await assetsApi.remove(id);
    load();
  }

  const logos = assets.filter((a) => a.type === 'logo');
  const colours = assets.filter((a) => a.type === 'colour');

  return (
    <div>
      <PageHeader title="Logos & Colours" subtitle="Manage the organisation's approved logos and brand colour palette." />

      {success && <SuccessBanner message={success} onDismiss={() => setSuccess(null)} />}

      <AsyncState loading={loading} error={error} empty={false} emptyLabel="">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 font-semibold text-navy">Logos</h3>
            <form onSubmit={handleUploadLogo} className="mb-4 space-y-2">
              <input placeholder="Logo name" className="w-full rounded border px-2 py-1 text-sm" value={logoName} onChange={(e) => setLogoName(e.target.value)} />
              <input ref={logoInputRef} type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" className="text-sm" required />
              <p className="text-xs text-slate-400">PNG or JPG only -- SVG is not supported.</p>
              <button type="submit" disabled={uploading} className="rounded bg-deep-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-navy disabled:opacity-50">
                {uploading ? 'Uploading...' : 'Upload logo'}
              </button>
              {logoError && <p className="text-sm text-red-600">{logoError}</p>}
            </form>
            {logos.length === 0 ? (
              <p className="text-sm text-slate-500">No logos uploaded yet.</p>
            ) : (
              <ul className="space-y-2">
                {logos.map((logo) => (
                  <li key={logo.id} className="flex items-center justify-between rounded border border-slate-100 p-2">
                    <div className="flex items-center gap-3">
                      {logo.file_path && organisationId && userId && (
                        <img
                          src={assetsApi.fileUrl(logo.id, organisationId, userId)}
                          alt={logo.name}
                          className="h-10 w-10 rounded border border-slate-100 object-contain"
                        />
                      )}
                      <div>
                        <p className="text-sm font-medium text-navy">{logo.name}</p>
                        <span className={`rounded px-2 py-0.5 text-xs font-medium ${logo.status === 'approved' ? 'bg-teal/20 text-deep-blue' : 'bg-slate-200 text-slate-600'}`}>
                          {logo.status === 'approved' ? 'Approved' : 'Deprecated'}
                        </span>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleToggleStatus(logo)}
                        className="rounded border border-deep-blue/30 px-2.5 py-1 text-xs font-medium text-deep-blue hover:bg-deep-blue/5"
                      >
                        {logo.status === 'approved' ? 'Deprecate' : 'Approve'}
                      </button>
                      <button
                        onClick={() => handleDelete(logo.id)}
                        className="rounded border border-red-300 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 font-semibold text-navy">Brand colour palette</h3>
            <form onSubmit={handleAddColour} className="mb-4 flex items-center gap-2">
              <input placeholder="Colour name" className="flex-1 rounded border px-2 py-1 text-sm" value={colourName} onChange={(e) => setColourName(e.target.value)} required />
              <input type="color" value={colourHex} onChange={(e) => setColourHex(e.target.value)} className="h-8 w-10 rounded border" />
              <input className="w-24 rounded border px-2 py-1 text-sm" value={colourHex} onChange={(e) => setColourHex(e.target.value)} />
              <button type="submit" className="rounded bg-deep-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-navy">Add</button>
            </form>
            {colourError && <p className="mb-2 text-sm text-red-600">{colourError}</p>}
            {colours.length === 0 ? (
              <p className="text-sm text-slate-500">No brand colours yet.</p>
            ) : (
              <ul className="space-y-2">
                {colours.map((colour) => (
                  <li key={colour.id} className="flex items-center justify-between rounded border border-slate-100 p-2">
                    <div className="flex items-center gap-3">
                      <span className="h-8 w-8 rounded border border-slate-200" style={{ backgroundColor: colour.hex_value ?? undefined }} />
                      <div>
                        <p className="text-sm font-medium text-navy">{colour.name}</p>
                        <p className="text-xs text-slate-500">{colour.hex_value}</p>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDelete(colour.id)}
                      className="rounded border border-red-300 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </AsyncState>
    </div>
  );
}
