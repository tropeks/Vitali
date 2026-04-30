/**
 * Next.js Middleware - auth guard.
 * - Unauthenticated users hitting protected app routes are redirected to /login
 * - Authenticated users hitting /login are redirected to /dashboard
 */
import { NextRequest, NextResponse } from "next/server";

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

function pathMatches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathMatches(pathname, path));
}

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PATH_PREFIXES.some((path) => pathMatches(pathname, path));
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Always allow static files and public paths.
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    isPublicPath(pathname)
  ) {
    return NextResponse.next();
  }

  const userCookie = request.cookies.get("vitali_user")?.value;
  const isAuthenticated = Boolean(userCookie && (() => {
    try { return JSON.parse(userCookie)?.id; } catch { return false; }
  })());

  // Redirect unauthenticated users to login while preserving the app route.
  if (!isAuthenticated && isProtectedPath(pathname)) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = "";
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  // Redirect authenticated users away from login.
  if (isAuthenticated && pathname === "/login") {
    const dashUrl = request.nextUrl.clone();
    dashUrl.pathname = "/dashboard";
    dashUrl.search = "";
    return NextResponse.redirect(dashUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
