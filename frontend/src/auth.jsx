import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, token } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(!!token.get());

  useEffect(() => {
    if (!token.get()) return;
    api("/api/me").then(setUser).catch(() => token.clear()).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const onLogout = () => setUser(null);
    window.addEventListener("khataz:logout", onLogout);
    return () => window.removeEventListener("khataz:logout", onLogout);
  }, []);

  const signIn = useCallback((result) => { token.set(result.access_token); setUser(result.user); }, []);
  const signOut = useCallback(() => { token.clear(); setUser(null); }, []);

  return (
    <AuthContext.Provider value={{ user, setUser, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
