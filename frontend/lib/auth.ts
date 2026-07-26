/**
 * Auth types shared across the frontend.
 * UserDTO mirrors the shape stored in the vitali_user cookie (set by the Django auth endpoint).
 */

export interface UserDTO {
  id: string | number;
  full_name: string;
  email: string;
  role_name?: string | null;
  active_modules: string[];
  permissions?: string[];
  /**
   * True for Vitali platform operators (Django superusers). Gates the Plataforma
   * nav group on the client. NOTE: the backend `UserSerializer`
   * (apps/core/serializers.py) does NOT yet emit this field, so it is currently
   * always undefined and Plataforma stays hidden by default (fail-safe). Backend
   * follow-up (S-IA1b): add `is_superuser` to the /me + login serializer fields
   * so real platform operators get the group. The real security boundary remains
   * `IsPlatformAdmin` on the backend regardless.
   */
  is_superuser?: boolean;
}

/**
 * Reads the current user from the (non-httpOnly) `vitali_user` cookie set at
 * login. Client-only — returns null on the server or when the cookie is absent
 * or malformed. The cookie is a UX snapshot; the backend `permission_classes`
 * remains the real security boundary (a hidden control never grants access).
 */
export function getCurrentUser(): UserDTO | null {
  if (typeof document === "undefined") return null;
  const raw = document.cookie
    .split("; ")
    .find((c) => c.startsWith("vitali_user="))
    ?.slice("vitali_user=".length);
  if (!raw) return null;
  try {
    return JSON.parse(decodeURIComponent(raw)) as UserDTO;
  } catch {
    return null;
  }
}

/**
 * True when the current user holds `permission`. UX-only gate (defense in
 * depth): hiding a control is never access control — the backend enforces 403.
 */
export function hasPermission(permission: string): boolean {
  return (getCurrentUser()?.permissions ?? []).includes(permission);
}

/**
 * Returns the JWT access token from the non-httpOnly access_token_js cookie.
 * The httpOnly access_token cookie (used by server-side middleware) is not readable
 * by JS — access_token_js is the parallel client-readable mirror set on login/refresh.
 */
export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return (
    document.cookie
      .split("; ")
      .find((c) => c.startsWith("access_token_js="))
      ?.split("=")[1] ?? null
  );
}
