import type { ReactNode } from 'react';

type Props = {
  loading: boolean;
  error: string | null;
  empty: boolean;
  emptyLabel: string;
  children: ReactNode;
};

export function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin text-deep-blue`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

export default function AsyncState({ loading, error, empty, emptyLabel, children }: Props) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-slate-500" role="status" aria-live="polite">
        <Spinner />
        <span>Loading...</span>
      </div>
    );
  }
  if (error)
    return (
      <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
        <span aria-hidden="true" className="text-lg leading-none">
          ⚠
        </span>
        <span>{error}</span>
      </div>
    );
  if (empty)
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white/60 p-8 text-center text-sm text-slate-500">
        {emptyLabel}
      </div>
    );
  return <>{children}</>;
}

export function SuccessBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="mb-4 flex items-center justify-between rounded-lg border border-teal/40 bg-teal/10 p-3 text-sm text-deep-blue" role="status">
      <span className="flex items-center gap-2">
        <span aria-hidden="true">✓</span>
        {message}
      </span>
      <button onClick={onDismiss} className="text-xs text-deep-blue/60 hover:text-deep-blue">
        dismiss
      </button>
    </div>
  );
}
