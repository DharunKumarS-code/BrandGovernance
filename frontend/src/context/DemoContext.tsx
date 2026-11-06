import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { demoApi, setDemoHeaders, type DemoUser, type Organisation } from '../api/client';

/**
 * DEMO-ONLY organisation/user context. This is not production
 * authentication or security -- it exists only so Phase 3 can demonstrate
 * organisation-scoped data without building real auth yet. The chosen
 * organisation/user are sent as plain request headers (see api/client.ts).
 */

type DemoContextValue = {
  organisations: Organisation[];
  users: DemoUser[];
  organisationId: string | null;
  userId: string | null;
  loading: boolean;
  error: string | null;
  setOrganisationId: (id: string) => void;
  setUserId: (id: string) => void;
};

const Ctx = createContext<DemoContextValue | null>(null);

const STORAGE_ORG_KEY = 'clarivue_demo_org_id';
const STORAGE_USER_KEY = 'clarivue_demo_user_id';

export function DemoProvider({ children }: { children: ReactNode }) {
  const [organisations, setOrganisations] = useState<Organisation[]>([]);
  const [users, setUsers] = useState<DemoUser[]>([]);
  const [organisationId, setOrganisationIdState] = useState<string | null>(
    () => localStorage.getItem(STORAGE_ORG_KEY),
  );
  const [userId, setUserIdState] = useState<string | null>(() => localStorage.getItem(STORAGE_USER_KEY));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Set synchronously on every render (not in a useEffect): a child page's
  // own data-fetch effect can otherwise run before a separate "set headers"
  // effect does, sending a request with stale/missing org-context headers.
  // This runs before any effects fire, so by the time a child mounts and
  // fetches, the headers already match this render's organisationId/userId.
  setDemoHeaders(organisationId, userId);

  useEffect(() => {
    demoApi
      .organisations()
      .then((res) => {
        setOrganisations(res.data);
        if (!organisationId && res.data.length > 0) {
          setOrganisationIdState(res.data[0].id);
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!organisationId) return;
    demoApi
      .usersFor(organisationId)
      .then((res) => {
        setUsers(res.data);
        const stillValid = res.data.some((u) => u.id === userId);
        if (!stillValid && res.data.length > 0) {
          setUserIdState(res.data[0].id);
        }
      })
      .catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organisationId]);

  useEffect(() => {
    if (organisationId) localStorage.setItem(STORAGE_ORG_KEY, organisationId);
    if (userId) localStorage.setItem(STORAGE_USER_KEY, userId);
  }, [organisationId, userId]);

  const setOrganisationId = (id: string) => {
    setOrganisationIdState(id);
    setUserIdState(null);
  };
  const setUserId = (id: string) => setUserIdState(id);

  return (
    <Ctx.Provider
      value={{ organisations, users, organisationId, userId, loading, error, setOrganisationId, setUserId }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useDemoContext() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useDemoContext must be used within a DemoProvider');
  return ctx;
}
