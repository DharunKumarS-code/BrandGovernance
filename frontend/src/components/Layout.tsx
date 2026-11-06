import { useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { useDemoContext } from '../context/DemoContext';
import { useAuth } from '../context/AuthContext';
import {
  IconBook,
  IconChart,
  IconClose,
  IconDashboard,
  IconFacts,
  IconMenu,
  IconShield,
  IconSubmissions,
  IconSwatch,
  IconTerminology,
} from './icons';

// Grouped so the sidebar reads as an organised menu rather than a flat
// list -- "Overview" for the dashboard, "Brand Guidelines" for the
// governance data that feeds AI analysis, "Content" for the submission
// and review workflow.
const NAV_GROUPS: { label: string; items: { to: string; label: string; icon: typeof IconBook }[] }[] = [
  {
    label: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: IconDashboard },
      { to: '/analytics', label: 'Analytics', icon: IconChart },
    ],
  },
  {
    label: 'Brand Guidelines',
    items: [
      { to: '/guidelines', label: 'Guideline Documents', icon: IconBook },
      { to: '/facts', label: 'Brand Facts', icon: IconFacts },
      { to: '/terminology', label: 'Terminology', icon: IconTerminology },
      { to: '/claim-policies', label: 'Claim Policies', icon: IconShield },
      { to: '/assets', label: 'Logos & Colours', icon: IconSwatch },
    ],
  },
  {
    label: 'Content',
    items: [{ to: '/submissions', label: 'Submissions', icon: IconSubmissions }],
  },
];

function DemoSelector() {
  const { organisations, users, organisationId, userId, setOrganisationId, setUserId } = useDemoContext();

  return (
    <div className="border-t border-white/10 p-4 text-xs text-white/70">
      <p className="mb-2 font-semibold uppercase tracking-wide text-cyan">Demo Context</p>
      <p className="mb-2 text-[11px] leading-snug text-white/50">
        For this demo, choose who you're acting as below -- not a real login.
      </p>
      <label className="mb-1 block">Organisation</label>
      <select
        className="mb-2 w-full rounded bg-deep-blue px-2 py-1.5 text-white"
        value={organisationId ?? ''}
        onChange={(e) => setOrganisationId(e.target.value)}
      >
        {organisations.map((org) => (
          <option key={org.id} value={org.id}>
            {org.name}
          </option>
        ))}
      </select>
      <label className="mb-1 block">Acting as</label>
      <select
        className="w-full rounded bg-deep-blue px-2 py-1.5 text-white"
        value={userId ?? ''}
        onChange={(e) => setUserId(e.target.value)}
      >
        {users.map((u) => (
          <option key={u.id} value={u.id}>
            {u.name} ({u.role})
          </option>
        ))}
      </select>
    </div>
  );
}

function AuthStatus() {
  const { authUser, logout } = useAuth();
  if (!authUser) {
    return (
      <Link to="/login" className="block px-3 py-1.5 text-xs text-cyan hover:underline">
        Sign in
      </Link>
    );
  }
  return (
    <div className="flex items-center justify-between px-3 py-1.5 text-xs text-white/70">
      <span>
        Signed in as <span className="text-white">{authUser.name}</span>
      </span>
      <button onClick={logout} className="text-cyan hover:underline">
        Sign out
      </button>
    </div>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <div className="p-4">
        <h1 className="text-lg font-semibold text-white">Clarivue AI</h1>
        <p className="text-xs text-white/60">Clarity in Every Creation.</p>
      </div>
      <AuthStatus />
      <nav className="flex-1 space-y-4 overflow-y-auto px-2 pb-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <p className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wide text-white/40">{group.label}</p>
            <div className="space-y-1">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 rounded px-3 py-2 text-sm font-medium transition-colors ${
                      isActive ? 'bg-deep-blue text-cyan' : 'text-white/80 hover:bg-deep-blue hover:text-white'
                    }`
                  }
                >
                  <item.icon />
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <DemoSelector />
    </>
  );
}

export default function Layout() {
  const { loading, error, organisationId, userId } = useDemoContext();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-off-white lg:flex">
      {/* Mobile top bar: hamburger + brand, visible only below the lg
          breakpoint so the sidebar can live off-canvas on small screens
          instead of squeezing page content. */}
      <div className="flex items-center justify-between bg-navy px-4 py-3 text-white lg:hidden">
        <span className="text-base font-semibold">Clarivue AI</span>
        <button
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation menu"
          className="rounded p-1.5 text-white hover:bg-deep-blue"
        >
          <IconMenu />
        </button>
      </div>

      {/* Mobile off-canvas sidebar + backdrop. */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute left-0 top-0 flex h-full w-72 flex-col bg-navy text-white shadow-xl">
            <div className="flex items-center justify-end p-2">
              <button
                onClick={() => setMobileOpen(false)}
                aria-label="Close navigation menu"
                className="rounded p-1.5 text-white/70 hover:bg-deep-blue hover:text-white"
              >
                <IconClose />
              </button>
            </div>
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      {/* Desktop sidebar -- always visible at lg and above. */}
      <aside className="hidden w-64 flex-shrink-0 flex-col bg-navy text-white lg:flex">
        <SidebarContent />
      </aside>

      <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
        {error && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
            Could not load demo context: {error}
          </div>
        )}
        {loading ? (
          <p className="text-slate-500">Loading demo organisation context...</p>
        ) : !organisationId || !userId ? (
          <p className="text-slate-500">
            No demo organisation/user available yet. Run the seed script, then reload.
          </p>
        ) : (
          <Outlet />
        )}
      </main>
    </div>
  );
}
