import type { AuthTokens, User } from '@/types';

const ACCESS_TOKEN_KEY = 'dce_access';
const REFRESH_TOKEN_KEY = 'dce_refresh';
const USER_KEY = 'dce_user';

// ─── Token Storage ────────────────────────────────────────────

export function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens(tokens: AuthTokens): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access);
  localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// ─── User Storage ─────────────────────────────────────────────

export function getStoredUser(): User | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function setStoredUser(user: User): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

// ─── JWT Decode ───────────────────────────────────────────────

interface JWTPayload {
  exp: number;
  iat: number;
  user_id: string;
}

export function decodeJWT(token: string): JWTPayload | null {
  try {
    const base64Payload = token.split('.')[1];
    const payload = atob(base64Payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(payload) as JWTPayload;
  } catch {
    return null;
  }
}

export function isTokenExpired(token: string): boolean {
  const payload = decodeJWT(token);
  if (!payload) return true;
  // Add 30s buffer before actual expiry
  return Date.now() / 1000 > payload.exp - 30;
}

export function isAuthenticated(): boolean {
  const accessToken = getAccessToken();
  if (!accessToken) return false;
  return !isTokenExpired(accessToken);
}
