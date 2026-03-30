/**
 * Next.js API Route: POST /api/auth/logout
 * Clears auth cookies and calls Django logout to blacklist the refresh token.
 */
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const DJANGO_API = process.env.DJANGO_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const cookieStore = cookies();
  const accessToken = cookieStore.get("access_token")?.value;
  const refreshToken = cookieStore.get("refresh_token")?.value;

  // Call Django to blacklist the refresh token
  if (refreshToken && accessToken) {
    try {
      await fetch(`${DJANGO_API}/api/v1/auth/logout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ refresh: refreshToken }),
      });
    } catch {
      // Proceed with cookie deletion even if Django is unreachable
    }
  }

  const response = NextResponse.json({ detail: "Logout realizado." });

  // Clear all auth cookies
  for (const cookieName of ["access_token", "access_token_js", "refresh_token", "vitali_user"]) {
    response.cookies.set(cookieName, "", {
      httpOnly: cookieName === "access_token" || cookieName === "refresh_token",
      path: "/",
      maxAge: 0,
    });
  }

  return response;
}
