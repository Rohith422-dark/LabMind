import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, tokenStore, type Schemas } from "@/api/client";

type Me = Schemas["MeOut"];

interface AuthState {
  me: Me | null;
  loading: boolean;
  can: (permission: string) => boolean;
  login: (username: string, password: string) => Promise<void>;
  demoLogin: (username: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => { tokenStore.clear(); setMe(null); }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) { setLoading(false); return; }
    api<Me>("/auth/me").then(setMe).catch(() => tokenStore.clear()).finally(() => setLoading(false));
  }, [logout]);

  const finish = (r: Schemas["LoginOut"]) => {
    tokenStore.set(r.token);
    setMe({ user: r.user, permissions: r.permissions });
  };

  const value = useMemo<AuthState>(() => ({
    me, loading, logout,
    can: (p) => !!me?.permissions.includes(p),
    login: async (username, password) => finish(await api<Schemas["LoginOut"]>("/auth/login", { method: "POST", json: { username, password } })),
    demoLogin: async (username) => finish(await api<Schemas["LoginOut"]>(`/auth/demo-login?username=${encodeURIComponent(username)}`, { method: "POST" })),
  }), [me, loading, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
