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
