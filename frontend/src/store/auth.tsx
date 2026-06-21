import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import api from '../api/client';
import type { LoginResponse } from '../types';

interface AuthContextType {
  token: string | null;
  username: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [username, setUsername] = useState<string | null>(localStorage.getItem('username'));

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.post<LoginResponse>('/auth/login', { username, password });
    localStorage.setItem('token', res.data.access_token);
    localStorage.setItem('username', res.data.username);
    setToken(res.data.access_token);
    setUsername(res.data.username);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    setToken(null);
    setUsername(null);
  }, []);

  return (
    <AuthContext.Provider value={{ token, username, login, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
