import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { authApi, getStoredAuthToken, setAuthToken, setUnauthorizedHandler, type AuthUser } from '../api/client';

type AuthContextValue = {
  authUser: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const Ctx = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getStoredAuthToken();
    if (!token) {
      setLoading(false);
      return;
    }
    setAuthToken(token);
    authApi
      .me()
      .then((res) => setAuthUser(res.data))
      .catch(() => setAuthToken(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthUser(null));
    return () => setUnauthorizedHandler(null);
  }, []);

  async function login(email: string, password: string) {
    const res = await authApi.login(email, password);
    setAuthToken(res.data.access_token);
    setAuthUser(res.data.user);
  }

  function logout() {
    setAuthToken(null);
    setAuthUser(null);
    authApi.logout().catch(() => undefined);
  }

  return <Ctx.Provider value={{ authUser, loading, login, logout }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
