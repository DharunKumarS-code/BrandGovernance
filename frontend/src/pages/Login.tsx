import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatApiError } from '../api/client';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate('/');
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-off-white p-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-1 text-xl font-semibold text-navy">Clarivue AI</h1>
        <p className="mb-6 text-sm text-slate-500">Sign in with your account.</p>

        <label className="mb-1 block text-sm font-medium text-deep-blue">Email</label>
        <input
          type="email"
          required
          autoFocus
          className="mb-4 w-full rounded border px-3 py-2 text-sm"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <label className="mb-1 block text-sm font-medium text-deep-blue">Password</label>
        <input
          type="password"
          required
          className="mb-4 w-full rounded border px-3 py-2 text-sm"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded bg-deep-blue px-4 py-2 text-sm font-medium text-white hover:bg-navy disabled:opacity-50"
        >
          {busy ? 'Signing in...' : 'Sign In'}
        </button>

        <p className="mt-4 text-xs text-slate-400">
          No account yet, or just exploring? Use the demo organisation/user selector in the app instead -- no
          password required for the local demo.
        </p>
      </form>
    </div>
  );
}
