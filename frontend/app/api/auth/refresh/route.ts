/**
 * Next.js API Route: POST /api/auth/refresh
 * Uses the httpOnly refresh_token cookie to get a new access token from Django.
 */
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const DJANGO_API =
  process.env.DJANGO_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";
const IS_PROD = process.env.NODE_ENV === "production";

export async function POST(req: NextRequest) {
  const cookieStore = cookies();
  const refreshToken = cookieStore.get("refresh_token")?.value;

  if (!refreshToken) {
    return NextResponse.json({ error: "No refresh token." }, { status: 401 });
  }

  const rawHost = req.headers.get("host") ?? "localhost";
  const forwardedHost = rawHost.split(":")[0];

  let djangoResp: Response;
  try {
    djangoResp = await fetch(`${DJANGO_API}/api/v1/auth/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-Host": forwardedHost,
      },
      body: JSON.stringify({ refresh: refreshToken }),
    });
  } catch {
    return NextResponse.json({ error: "Backend unavailable." }, { status: 503 });
  }

  if (!djangoResp.ok) {
    const response = NextResponse.json({ error: "Token inválido." }, { status: 401 });
    // Clear stale cookies
    for (const name of ["access_token", "access_token_js", "refresh_token", "vitali_user"]) {
      response.cookies.set(name, "", { path: "/", maxAge: 0 });
    }
    return response;
  }

  const data = await djangoResp.json() as { access: string; refresh?: string };
  const response = NextResponse.json({ ok: true });

  response.cookies.set("access_token", data.access, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: 15 * 60,
  });

  response.cookies.set("access_token_js", data.access, {
    httpOnly: false,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: 15 * 60,
  });

  // SimpleJWT rotation returns a new refresh token
  if (data.refresh) {
    response.cookies.set("refresh_token", data.refresh, {
      httpOnly: true,
      secure: IS_PROD,
      sameSite: "lax",
      path: "/",
      maxAge: 7 * 24 * 60 * 60,
    });
  }

  return response;
}
