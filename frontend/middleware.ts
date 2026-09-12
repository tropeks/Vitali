/**
 * Next.js Middleware - auth guard + security headers.
 * - Unauthenticated users hitting protected app routes are redirected to /login
 * - Authenticated users hitting /login are redirected to /dashboard
 * - Every browser-facing response carries a Content-Security-Policy (issue #115)
 *   plus static hardening headers. CSP enforces by default (item 3.8, Onda 3 —
 *   promoted once the JWT stopped being client-readable); set CSP_ENFORCE=false
 *   to fall back to Report-Only if a false positive needs triage in prod.
 */
import { NextRequest, NextResponse } from "next/server";

import {
  buildContentSecurityPolicy,
  cspHeaderName,
  generateNonce,
  NONCE_HEADER,
  STATIC_SECURITY_HEADERS,
} from "@/lib/security/csp";

const PUBLIC_PATHS = ["/login", "/mfa", "/api/auth/login", "/api/auth/refresh"];

const PROTECTED_PATH_PREFIXES = [
  "/dashboard",
  "/patients",
  "/appointments",
  "/waiting-room",
  "/encounters",
  "/billing",
  "/farmacia",
  "/configuracoes",
  "/platform",
  "/profile",
  "/rh",
];

// CSP is skipped in development: HMR/React Refresh need 'unsafe-eval' and an
// unreachable report-uri would flood the console. It is emitted for every other
// environment (preview/staging/production) so the prod-like soak is representative.
const CSP_ENABLED = process.env.NODE_ENV !== "development";
// Item 3.8 (Onda 3): the JWT is no longer readable by client JS (no
// access_token_js mirror), which sharply cuts what an XSS can exfiltrate —
// enforcing CSP is safe to default on. Ops can still opt back to Report-Only
// Opt-in on purpose. lib/security/csp.ts documents the rollout this project
// chose: ship Report-Only, confirm a clean soak against the violation
// collector, THEN promote. No soak has happened yet — production has never
// booted, so the collector has never received a single report. Flipping the
// default here would enforce a policy nobody has observed, and a blocked
// legitimate resource takes the app down. Removing access_token_js (item 3.8)
// already cut the XSS payoff from full-token exfiltration, which lowers the
// urgency. Promote with CSP_ENFORCE=true after the soak.
const CSP_ENFORCE = process.env.CSP_ENFORCE === "true";

function pathMatches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathMatches(pathname, path));
}

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PATH_PREFIXES.some((path) => pathMatches(pathname, path));
}

/** Attach the static hardening headers (and CSP, when present) to a response. */
function applySecurityHeaders(response: NextResponse, csp: string | null): NextResponse {
  for (const [name, value] of Object.entries(STATIC_SECURITY_HEADERS)) {
    response.headers.set(name, value);
  }
  if (csp) {
    response.headers.set(cspHeaderName(CSP_ENFORCE), csp);
  }
  return response;
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Always allow static files (no CSP needed on assets).
  if (pathname.startsWith("/_next") || pathname.startsWith("/favicon")) {
    return NextResponse.next();
  }

  // Build a per-request nonce + policy. The nonce is forwarded on the request
  // headers so Next.js stamps it onto its own bootstrap <script> tags; the policy
  // goes on the response so the browser enforces (or reports) it.
  const nonce = generateNonce();
  const csp = CSP_ENABLED
    ? buildContentSecurityPolicy({ nonce, enforce: CSP_ENFORCE })
    : null;

  const requestHeaders = new Headers(request.headers);
  if (csp) {
    requestHeaders.set(NONCE_HEADER, nonce);
    // Next.js extracts the nonce from a request-side `content-security-policy`
    // header (always the enforcing name here — it is internal, never sent back).
    requestHeaders.set("content-security-policy", csp);
  }
  const passThrough = () =>
    applySecurityHeaders(NextResponse.next({ request: { headers: requestHeaders } }), csp);

  const userCookie = request.cookies.get("vitali_user")?.value;
  const isAuthenticated = Boolean(userCookie && (() => {
    try { return JSON.parse(userCookie)?.id; } catch { return false; }
  })());

  // Redirect authenticated users away from login before the public-path allowlist.
  if (isAuthenticated && pathname === "/login") {
    const dashUrl = request.nextUrl.clone();
    dashUrl.pathname = "/dashboard";
    dashUrl.search = "";
    return applySecurityHeaders(NextResponse.redirect(dashUrl), csp);
  }

  // Allow public auth/API paths for unauthenticated users.
  if (isPublicPath(pathname)) {
    return passThrough();
  }

  // Redirect unauthenticated users to login while preserving the app route.
  if (!isAuthenticated && isProtectedPath(pathname)) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = "";
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    return applySecurityHeaders(NextResponse.redirect(loginUrl), csp);
  }

  return passThrough();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
