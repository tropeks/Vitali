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
