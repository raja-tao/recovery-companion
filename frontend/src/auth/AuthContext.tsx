import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, tokenStore } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
}

const Ctx = createContext<AuthState | null>(null);

// Patients are asked how they feel once per sign-in.
const MOOD_KEY = "rc.askMood";
export const moodPrompt = {
  request: () => { try { sessionStorage.setItem(MOOD_KEY, "1"); } catch { /* storage unavailable */ } },
  pending: () => { try { return sessionStorage.getItem(MOOD_KEY) === "1"; } catch { return false; } },
  clear: () => { try { sessionStorage.removeItem(MOOD_KEY); } catch { /* storage unavailable */ } },
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    tokenStore.set(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) {
      setReady(true);
      return;
    }
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => tokenStore.set(null))
      .finally(() => setReady(true));
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api<{ access_token: string; user: User }>("/auth/login", { body: { email, password } });
    tokenStore.set(res.access_token);
    if (res.user.role === "PATIENT") moodPrompt.request();
    setUser(res.user);
    return res.user;
  }, []);

  return <Ctx.Provider value={{ user, ready, login, logout }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside provider");
  return c;
}

export const homeFor = (role: string) =>
  ({
    PATIENT: "/patient",
    CAREGIVER: "/caregiver",
    NURSE: "/care-team",
    SURGEON: "/surgeon",
    ADMIN: "/admin/analytics",
  })[role] ?? "/";
