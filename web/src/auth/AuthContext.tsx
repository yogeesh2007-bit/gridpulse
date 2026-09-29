import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, onTokenRefreshed, refreshSession, setAccessToken, setSessionLostHandler } from "../lib/api";
import type { AuthResponse, Role, User } from "../lib/types";

type Status = "loading" | "authed" | "anon";

export interface SignUpInput {
  name: string;
  email: string;
  password: string;
  role: Role;
  operator_code?: string;
}

interface AuthContextValue {
  status: Status;
  user: User | null;
  signIn: (email: string, password: string) => Promise<User>;
  signUp: (input: SignUpInput) => Promise<User>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Refresh the access token a minute before it expires. */
const REFRESH_MARGIN_S = 60;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const timer = useRef<number | null>(null);

  const scheduleRefresh = useCallback((expiresIn: number) => {
    if (timer.current) window.clearTimeout(timer.current);
    const delayMs = Math.max(10, expiresIn - REFRESH_MARGIN_S) * 1000;
    timer.current = window.setTimeout(() => void refreshSession(), delayMs);
  }, []);

  const adopt = useCallback(
    (data: AuthResponse | null) => {
      if (data) {
        setAccessToken(data.access_token);
        setUser(data.user);
        setStatus("authed");
        scheduleRefresh(data.expires_in);
      } else {
        setAccessToken(null);
        setUser(null);
        setStatus("anon");
        if (timer.current) window.clearTimeout(timer.current);
      }
    },
    [scheduleRefresh],
  );

  // Restore the session on page load from the httpOnly refresh cookie.
  useEffect(() => {
    let cancelled = false;
    refreshSession().then((data) => {
      if (!cancelled) adopt(data);
    });
    // any later refresh (proactive, or triggered by a 401) keeps this state in sync
    const off = onTokenRefreshed((data) => adopt(data));
    setSessionLostHandler(() => adopt(null));
    return () => {
      cancelled = true;
      off();
      setSessionLostHandler(null);
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [adopt]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const data = await api<AuthResponse>("/api/auth/signin", { json: { email, password }, anonymous: true });
      adopt(data);
      return data.user;
    },
    [adopt],
  );

  const signUp = useCallback(
    async (input: SignUpInput) => {
      const data = await api<AuthResponse>("/api/auth/signup", { json: input, anonymous: true });
      adopt(data);
      return data.user;
    },
    [adopt],
  );

  const signOut = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST", anonymous: true });
    } finally {
      adopt(null);
    }
  }, [adopt]);

  const value = useMemo(() => ({ status, user, signIn, signUp, signOut }), [status, user, signIn, signUp, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export const homeFor = (role: Role) => (role === "operator" ? "/app/operator" : "/app/driver");
